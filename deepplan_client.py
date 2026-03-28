#!/usr/bin/env python3
import json
from dataclasses import dataclass
from http.client import HTTPConnection
from typing import Any, Callable, Dict, List, Optional, Tuple


class DeepPlanClientError(RuntimeError):
    def __init__(self, status: int, payload: Dict[str, Any], headers: Dict[str, str]) -> None:
        message = str(payload.get("error", f"http_{status}"))
        super().__init__(message)
        self.status = status
        self.payload = payload
        self.headers = headers


class DeepPlanConflictError(DeepPlanClientError):
    def __init__(
        self,
        status: int,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        *,
        expected_fingerprint: str = "",
        current_fingerprint: str = "",
        operation: str = "",
        step: str = "",
        can_refresh: bool = True,
    ) -> None:
        super().__init__(status, payload, headers)
        self.expected_fingerprint = expected_fingerprint
        self.current_fingerprint = current_fingerprint
        self.operation = operation
        self.step = step
        self.can_refresh = can_refresh

    def with_context(self, operation: str, step: str) -> "DeepPlanConflictError":
        return DeepPlanConflictError(
            self.status,
            self.payload,
            self.headers,
            expected_fingerprint=self.expected_fingerprint,
            current_fingerprint=self.current_fingerprint,
            operation=operation,
            step=step,
            can_refresh=self.can_refresh,
        )


class DeepPlanClientOperationError(RuntimeError):
    def __init__(self, operation: str, step: str, cause: DeepPlanClientError) -> None:
        super().__init__(f"{operation} failed during {step}: {cause}")
        self.operation = operation
        self.step = step
        self.cause = cause
        self.status = cause.status
        self.payload = cause.payload
        self.headers = cause.headers


RequestTransport = Callable[[str, str, Optional[Dict[str, Any]], Optional[Dict[str, str]]], Tuple[int, Dict[str, Any], Dict[str, str]]]


def diff_top_level_fields(before: Dict[str, Any], after: Dict[str, Any]) -> List[str]:
    changed: List[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append(key)
    return changed


def default_transport_factory(host: str, port: int, timeout: float = 10.0) -> RequestTransport:
    def transport(method: str, path: str, body: Optional[Dict[str, Any]], headers: Optional[Dict[str, str]]) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
        connection = HTTPConnection(host, port, timeout=timeout)
        raw_body = None
        merged_headers = dict(headers or {})
        if body is not None:
            raw_body = json.dumps(body).encode("utf-8")
            merged_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=raw_body, headers=merged_headers)
        response = connection.getresponse()
        payload = json.loads(response.read().decode("utf-8"))
        response_headers = dict(response.getheaders())
        connection.close()
        return response.status, payload, response_headers

    return transport


@dataclass
class DeepPlanClient:
    transport: RequestTransport
    tracked_fingerprint: str = ""

    @classmethod
    def from_http(cls, host: str = "127.0.0.1", port: int = 8787, timeout: float = 10.0) -> "DeepPlanClient":
        return cls(transport=default_transport_factory(host, port, timeout=timeout))

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Optional[Dict[str, Any]] = None,
        expected_fingerprint: str = "",
        use_tracked_fingerprint: bool = False,
    ) -> Dict[str, Any]:
        headers: Dict[str, str] = {}
        fingerprint = expected_fingerprint or (self.tracked_fingerprint if use_tracked_fingerprint else "")
        if fingerprint:
            headers["If-Match"] = f'"{fingerprint}"'
        status, payload, response_headers = self.transport(method, path, body, headers or None)
        etag = str(response_headers.get("ETag", "")).strip()
        if etag.startswith('"') and etag.endswith('"') and len(etag) >= 2:
            self.tracked_fingerprint = etag[1:-1]
        elif isinstance(payload, dict) and isinstance(payload.get("fingerprint"), str):
            self.tracked_fingerprint = payload["fingerprint"]
        if status >= 400:
            current_fingerprint = ""
            if isinstance(payload, dict):
                current_fingerprint = str(payload.get("current_fingerprint", "")).strip()
            if not current_fingerprint and etag.startswith('"') and etag.endswith('"') and len(etag) >= 2:
                current_fingerprint = etag[1:-1]
            if status == 412 and isinstance(payload, dict) and str(payload.get("error", "")).strip() == "plan fingerprint mismatch":
                raise DeepPlanConflictError(
                    status,
                    payload,
                    response_headers,
                    expected_fingerprint=fingerprint,
                    current_fingerprint=current_fingerprint,
                )
            raise DeepPlanClientError(status, payload, response_headers)
        return payload

    def _build_cycle_operation_result(
        self,
        *,
        operation: str,
        before: Dict[str, Any],
        mutation_result: Dict[str, Any],
        after: Dict[str, Any],
        step_results: Dict[str, Any],
    ) -> Dict[str, Any]:
        before_score = int(before.get("qa", {}).get("score", 0))
        after_score = int(after.get("qa", {}).get("score", 0))
        return {
            "ok": True,
            "operation": operation,
            "result_type": "planning_cycle",
            "pre_fingerprint": before.get("fingerprint", ""),
            "post_fingerprint": after.get("fingerprint", ""),
            "changed_fields": diff_top_level_fields(before.get("plan", {}), after.get("plan", {})),
            "qa_delta": after_score - before_score,
            "mutation_result": mutation_result,
            "step_results": step_results,
            "pre_cycle": before,
            "post_cycle": after,
        }

    def get_plan(self) -> Dict[str, Any]:
        return self.request("GET", "/plan")

    def get_qa(self) -> Dict[str, Any]:
        return self.request("GET", "/qa")

    def get_health(self) -> Dict[str, Any]:
        return self.request("GET", "/health")

    def get_cycle(self, *, history_limit: int = 10) -> Dict[str, Any]:
        return self.request("GET", f"/cycle?limit={int(history_limit)}")

    def get_history(self) -> Dict[str, Any]:
        return self.request("GET", "/history")

    def validate_plan(self) -> Dict[str, Any]:
        return self.request("GET", "/validate")

    def update_plan(self, payload: Dict[str, Any], *, expected_fingerprint: str = "") -> Dict[str, Any]:
        return self.request("POST", "/plan", body=payload, expected_fingerprint=expected_fingerprint, use_tracked_fingerprint=True)

    def replan(self, payload: Dict[str, Any], *, expected_fingerprint: str = "") -> Dict[str, Any]:
        return self.request("POST", "/replan", body=payload, expected_fingerprint=expected_fingerprint, use_tracked_fingerprint=True)

    def add_evidence(self, payload: Dict[str, Any], *, expected_fingerprint: str = "") -> Dict[str, Any]:
        return self.request("POST", "/evidence", body=payload, expected_fingerprint=expected_fingerprint, use_tracked_fingerprint=True)

    def run_tool(self, tool_name: str, payload: Dict[str, Any], *, expected_fingerprint: str = "") -> Dict[str, Any]:
        return self.request("POST", f"/tools/{tool_name}", body={"input": payload}, expected_fingerprint=expected_fingerprint)

    def preview_restore(self, *, revision_id: str = "", previous: bool = False) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if revision_id:
            payload["revision_id"] = revision_id
        if previous:
            payload["previous"] = True
        return self.request("POST", "/restore/preview", body=payload)

    def restore_revision(self, *, revision_id: str = "", previous: bool = False, expected_fingerprint: str = "") -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if revision_id:
            payload["revision_id"] = revision_id
        if previous:
            payload["previous"] = True
        if not expected_fingerprint and self.tracked_fingerprint:
            expected_fingerprint = self.tracked_fingerprint
        return self.request("POST", "/restore", body=payload, expected_fingerprint=expected_fingerprint)

    def apply_and_get_cycle(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        history_limit: int = 10,
        expected_fingerprint: str = "",
    ) -> Dict[str, Any]:
        mutation_map = {
            "update_plan": self.update_plan,
            "replan": self.replan,
            "add_evidence": self.add_evidence,
        }
        if operation not in mutation_map:
            raise ValueError(f"unsupported operation: {operation}")
        before = self.get_cycle(history_limit=history_limit)
        try:
            mutation_result = mutation_map[operation](payload, expected_fingerprint=expected_fingerprint)
        except DeepPlanConflictError as exc:
            raise exc.with_context(operation, "mutation") from exc
        except DeepPlanClientError as exc:
            raise DeepPlanClientOperationError(operation, "mutation", exc) from exc
        try:
            after = self.get_cycle(history_limit=history_limit)
        except DeepPlanClientError as exc:
            raise DeepPlanClientOperationError(operation, "post_cycle", exc) from exc
        return self._build_cycle_operation_result(
            operation=operation,
            before=before,
            mutation_result=mutation_result,
            after=after,
            step_results={operation: mutation_result},
        )

    def apply_and_get_cycle_with_retry(
        self,
        operation: str,
        payload: Dict[str, Any],
        *,
        history_limit: int = 10,
        expected_fingerprint: str = "",
    ) -> Dict[str, Any]:
        attempt = 1
        try:
            result = self.apply_and_get_cycle(
                operation,
                payload,
                history_limit=history_limit,
                expected_fingerprint=expected_fingerprint,
            )
            result["retried"] = False
            result["attempts"] = attempt
            return result
        except DeepPlanConflictError as exc:
            if not exc.can_refresh:
                raise
            refreshed = self.get_cycle(history_limit=history_limit)
            attempt += 1
            retry_fingerprint = str(refreshed.get("fingerprint", "")).strip() or exc.current_fingerprint
            result = self.apply_and_get_cycle(
                operation,
                payload,
                history_limit=history_limit,
                expected_fingerprint=retry_fingerprint,
            )
            result["retried"] = True
            result["attempts"] = attempt
            result["retry_from_fingerprint"] = exc.expected_fingerprint
            result["retry_to_fingerprint"] = retry_fingerprint
            return result

    def capture_evidence_cycle(
        self,
        evidence_payload: Dict[str, Any],
        *,
        replan_payload: Optional[Dict[str, Any]] = None,
        history_limit: int = 10,
    ) -> Dict[str, Any]:
        before = self.get_cycle(history_limit=history_limit)
        try:
            evidence_result = self.add_evidence(evidence_payload)
        except DeepPlanConflictError as exc:
            raise exc.with_context("capture_evidence_cycle", "add_evidence") from exc
        except DeepPlanClientError as exc:
            raise DeepPlanClientOperationError("capture_evidence_cycle", "add_evidence", exc) from exc
        replan_input = dict(replan_payload or {})
        claim = str(evidence_payload.get("claim", "")).strip()
        source = str(evidence_payload.get("source", "")).strip()
        confidence = evidence_payload.get("confidence")
        axis = str(evidence_payload.get("axis", "")).strip()
        date = str(evidence_payload.get("date", "")).strip()
        if claim and "evidence" not in replan_input:
            replan_input["evidence"] = claim
        if source and "evidence_source" not in replan_input:
            replan_input["evidence_source"] = source
        if isinstance(confidence, int) and not isinstance(confidence, bool) and "evidence_confidence" not in replan_input:
            replan_input["evidence_confidence"] = confidence
        if axis and "evidence_axis" not in replan_input:
            replan_input["evidence_axis"] = axis
        if date and "evidence_date" not in replan_input:
            replan_input["evidence_date"] = date
        try:
            replan_result = self.replan(replan_input)
        except DeepPlanConflictError as exc:
            raise exc.with_context("capture_evidence_cycle", "replan") from exc
        except DeepPlanClientError as exc:
            raise DeepPlanClientOperationError("capture_evidence_cycle", "replan", exc) from exc
        try:
            after = self.get_cycle(history_limit=history_limit)
        except DeepPlanClientError as exc:
            raise DeepPlanClientOperationError("capture_evidence_cycle", "post_cycle", exc) from exc
        result = self._build_cycle_operation_result(
            operation="capture_evidence_cycle",
            before=before,
            mutation_result=replan_result,
            after=after,
            step_results={
                "add_evidence": evidence_result,
                "replan": replan_result,
            },
        )
        result["evidence_result"] = evidence_result
        result["replan_result"] = replan_result
        return result
