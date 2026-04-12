# DeepPlan HTTP API

This document specifies the current local HTTP service exposed by `deepplan_server.py`.

## Transport Rules

- The service MUST speak JSON over HTTP.
- Request bodies for write operations MUST be JSON objects.
- Responses MUST use `Content-Type: application/json; charset=utf-8`.
- JSON request and response bodies MUST be UTF-8.

## Read Endpoints

### `GET /plan`

Returns the current plan envelope.

The response MUST include:

- `plan`
- `summary`
- `validation`
- `fingerprint`
- `contract_version`
- `implementation_version`

If a fingerprint is available, the response MUST also include `ETag: "<fingerprint>"`.

### `GET /qa`

Returns the current QA report.

### `GET /health`

Returns storage health and recovery diagnostics.

If the storage status is `error`, the HTTP status MUST be `503`.
Otherwise the HTTP status MUST be `200`.

### `GET /cycle?limit=<n>`

Returns a combined read snapshot.

The response MUST include:

- `ok`
- `result_type` with value `cycle`
- `plan`
- `summary`
- `validation`
- `fingerprint`
- `contract_version`
- `implementation_version`
- `qa`
- `health`
- `history`
- `history_limit`

`limit` MUST be a non-negative integer when provided.

### `GET /history`

Returns recent revision entries.

### `GET /validate`

Returns structural validation for the current plan.

### `GET /tools`

Returns the tool schema catalogue.

## Write Endpoints

### `POST /plan`

Updates the plan.

The request body MUST be a JSON object.
If `If-Match` is present, the server MUST treat it as the expected fingerprint.
On success, the server MUST return the updated tool result and SHOULD emit an `ETag` header for the new fingerprint.

### `POST /evidence`

Appends one evidence item.

The request MAY include `idempotency_key`.
If a matching idempotency record exists, the server MUST replay the stored result instead of appending a duplicate evidence entry.

### `POST /replan`

Applies a planning delta, may append evidence, and runs QA/autoreplan behavior.

The request MAY include `idempotency_key`.

### `POST /restore/preview`

Returns a restore preview without mutating plan state.

The request body MAY contain `revision_id` or `previous`.
This endpoint MUST NOT require `If-Match`.

### `POST /restore`

Restores the plan to a previously recorded revision.

The request body MAY contain `revision_id` or `previous`.
If `If-Match` is present, the server MUST use it as the expected fingerprint.

### `POST /agent/act`

Accepts `{"input": "<prompt>"}` and maps the prompt to a tool call.

The response MUST include:

- `tool`
- `input`
- `result`

### `POST /tools/<tool_name>`

Executes the named tool wrapper.

The request body MUST be a JSON object.
If the body contains `input`, that object MUST be used as the tool input.
Otherwise the entire request body MUST be treated as the tool input.

## Error Semantics

The service MUST use JSON error envelopes.

The current implementation emits these error cases:

- `400` for invalid JSON, empty bodies, non-object bodies, or validation failures
- `404` for unknown paths
- `412` for fingerprint conflicts
- `500` for unexpected internal errors

On fingerprint conflicts, the error payload MUST include `error: "plan fingerprint mismatch"` and SHOULD include `current_fingerprint`.
