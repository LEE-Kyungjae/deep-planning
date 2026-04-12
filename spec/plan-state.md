# DeepPlan Plan State

This document specifies the canonical plan state stored by the current DeepPlan repository.

## Scope

DeepPlan MUST keep its authoritative planning state in a single repo-local JSON object at `.deeplan/plan.json`.
DeepPlan MUST treat the plan as the source of truth for planning direction, evidence, hypotheses, references, and revisionable decision context.

## Storage Layout

The repo-local state directory MUST be `.deeplan/`.

The current implementation uses these files:

- `.deeplan/plan.json`
- `.deeplan/decisions.jsonl`
- `.deeplan/risks.jsonl`
- `.deeplan/events.jsonl`
- `.deeplan/revisions.jsonl`

`plan.json` MUST contain the current mutable plan.
The `.jsonl` files MUST be treated as append-only logs.

## Required Plan Fields

`plan.json` MUST be a JSON object with all of the following top-level keys:

- `schema_version`
- `version`
- `updated_at`
- `goal`
- `success_metric`
- `deadline`
- `planning_horizon`
- `review_cadence`
- `phase_plan`
- `constraints`
- `assumptions`
- `options`
- `selected_option`
- `plan_tasks`
- `execution_tasks`
- `dependencies`
- `experiments`
- `risks`
- `references`
- `insights`
- `direction_insights`
- `market_insights`
- `timing_insights`
- `differentiation_insights`
- `monetization_insights`
- `constraint_insights`
- `risk_signal_insights`
- `evolution_insights`
- `definition_of_done`
- `evidence`
- `hypothesis_log`
- `reference_discoveries`

## Field Types

The current implementation requires these types:

- `schema_version`, `version`, `updated_at`, `goal`, `success_metric`, `deadline`, `planning_horizon`, `review_cadence`, and `selected_option` MUST be strings.
- `phase_plan`, `constraints`, `assumptions`, `options`, `plan_tasks`, `execution_tasks`, `dependencies`, `experiments`, `references`, `insights`, `direction_insights`, `market_insights`, `timing_insights`, `differentiation_insights`, `monetization_insights`, `constraint_insights`, `risk_signal_insights`, `evolution_insights`, `definition_of_done`, `evidence`, `hypothesis_log`, and `reference_discoveries` MUST be arrays.
- `risks` MUST be an array of strings or objects.

For nested records:

- A string `risk` entry MUST be non-empty.
- A risk object MUST include `risk`, `signal`, and `mitigation` as non-empty strings.
- An evidence string entry MUST be non-empty.
- An evidence object MUST include `claim`, `source`, and `date` as non-empty strings, and `confidence` as an integer from 0 to 100.
- A hypothesis object MUST include `ts`, `hypothesis`, and `status` as non-empty strings.
- A reference-discovery object MUST include `ts`, `question`, and `search_mode` as non-empty strings.

## Mutation Rules

- `updated_at` MUST change on each persisted save.
- Consumers MUST NOT use `updated_at` as a stable identity token.
- The plan fingerprint MUST ignore `updated_at`.
- The canonical task split is `plan_tasks` plus `execution_tasks`; legacy `tasks` input may be migrated, but `tasks` is not part of the canonical state shape.
- `schema_version` MUST be present and MUST be a string. Current new plans use `0.5.0`.
- `version` MUST be present as a compatibility alias and MUST equal `schema_version`.

## Revision Logs

- `revisions.jsonl` MUST store immutable plan snapshots.
- Each revision entry MUST include a revision identifier, timestamp, source, fingerprint, previous fingerprint, and plan snapshot.
- `events.jsonl` MAY store operational events such as idempotency records and auto-replan metadata.
- `decisions.jsonl` and `risks.jsonl` are append-only logs for decision and risk records.

## Retention

Event and revision logs are subject to bounded retention.
Pruning MUST preserve the newest entries first and MUST be best effort.
Retention settings are implementation-controlled and MAY vary by environment.
