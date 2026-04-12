#!/usr/bin/env python3
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import deepplan
from deepplan_server import DeepPlanHandler


CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"
MANIFEST_PATH = CONTRACTS_DIR / "manifest.json"


class DeepPlanStateIsolation:
    def __init__(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_dir = self.root / ".deeplan"
        self.originals: Dict[str, Any] = {}

    def __enter__(self):
        self.originals = {
            "ROOT": deepplan.ROOT,
            "STATE_DIR": deepplan.STATE_DIR,
            "PLAN_PATH": deepplan.PLAN_PATH,
            "DECISIONS_PATH": deepplan.DECISIONS_PATH,
            "RISKS_PATH": deepplan.RISKS_PATH,
            "EVENTS_PATH": deepplan.EVENTS_PATH,
            "REVISIONS_PATH": deepplan.REVISIONS_PATH,
            "EVENT_RETENTION_LIMIT": deepplan.EVENT_RETENTION_LIMIT,
            "REVISION_RETENTION_LIMIT": deepplan.REVISION_RETENTION_LIMIT,
        }
        deepplan.ROOT = self.root
        deepplan.STATE_DIR = self.state_dir
        deepplan.PLAN_PATH = self.state_dir / "plan.json"
        deepplan.DECISIONS_PATH = self.state_dir / "decisions.jsonl"
        deepplan.RISKS_PATH = self.state_dir / "risks.jsonl"
        deepplan.EVENTS_PATH = self.state_dir / "events.jsonl"
        deepplan.REVISIONS_PATH = self.state_dir / "revisions.jsonl"
        return self

    def __exit__(self, exc_type, exc, tb):
        deepplan.ROOT = self.originals["ROOT"]
        deepplan.STATE_DIR = self.originals["STATE_DIR"]
        deepplan.PLAN_PATH = self.originals["PLAN_PATH"]
        deepplan.DECISIONS_PATH = self.originals["DECISIONS_PATH"]
        deepplan.RISKS_PATH = self.originals["RISKS_PATH"]
        deepplan.EVENTS_PATH = self.originals["EVENTS_PATH"]
        deepplan.REVISIONS_PATH = self.originals["REVISIONS_PATH"]
        deepplan.EVENT_RETENTION_LIMIT = self.originals["EVENT_RETENTION_LIMIT"]
        deepplan.REVISION_RETENTION_LIMIT = self.originals["REVISION_RETENTION_LIMIT"]
        self.tempdir.cleanup()


def build_handler(method: str, path: str, body: bytes = b"", headers: Optional[Dict[str, str]] = None) -> DeepPlanHandler:
    handler = DeepPlanHandler.__new__(DeepPlanHandler)
    handler.command = method
    handler.path = path
    handler.headers = {"Content-Length": str(len(body)), **(headers or {})}
    handler.rfile = io.BytesIO(body)
    handler.wfile = io.BytesIO()
    handler._status = None
    handler._sent_headers = {}
    handler.send_response = lambda status, message=None: setattr(handler, "_status", status)
    handler.send_header = lambda key, value: handler._sent_headers.__setitem__(key, value)
    handler.end_headers = lambda: None
    return handler


def decode_response(handler: DeepPlanHandler) -> Dict[str, Any]:
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    return {
        "status": handler._status,
        "payload": payload,
        "headers": handler._sent_headers,
    }


def run_request(method: str, path: str, body: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    handler = build_handler(method, path, body=raw_body, headers=headers)
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    return decode_response(handler)


def load_json_fixture(name: str) -> Dict[str, Any]:
    return json.loads((CONTRACTS_DIR / name).read_text(encoding="utf-8"))


def load_manifest() -> Dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def get_value(payload: Dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            current = current[int(part)]
        else:
            raise KeyError(path)
    return current


def resolve_reference(context: Dict[str, Dict[str, Any]], reference: str) -> Any:
    alias, path = reference.split(".", 1)
    return get_value(context[alias], path)


def assert_contains_all(haystack: Iterable[Any], needles: Iterable[Any]) -> None:
    haystack_values = list(haystack)
    for needle in needles:
        if needle not in haystack_values:
            raise AssertionError(f"missing expected value: {needle!r}")


def assert_contract_assertion(case_id: str, assertion: Dict[str, Any], context: Dict[str, Dict[str, Any]]) -> None:
    target = context[assertion["target"]]
    path = assertion["path"]
    op = assertion["op"]

    if op == "eq":
        expected = resolve_reference(context, assertion["value_from"]) if "value_from" in assertion else assertion["value"]
        assert get_value(target, path) == expected, f"{case_id}: {path}"
        return
    if op == "ne":
        expected = resolve_reference(context, assertion["value_from"]) if "value_from" in assertion else assertion["value"]
        assert get_value(target, path) != expected, f"{case_id}: {path}"
        return
    if op == "gt":
        assert get_value(target, path) > assertion["value"], f"{case_id}: {path}"
        return
    if op == "len_eq":
        assert len(get_value(target, path)) == assertion["value"], f"{case_id}: {path}"
        return
    if op == "non_empty":
        value = get_value(target, path)
        assert bool(value), f"{case_id}: {path}"
        return
    if op == "has_keys":
        value = get_value(target, path)
        assert isinstance(value, dict), f"{case_id}: {path} must be an object"
        for key in assertion["value"]:
            assert key in value, f"{case_id}: missing key {key!r} at {path}"
        return
    if op == "contains":
        value = get_value(target, path)
        assert isinstance(value, list), f"{case_id}: {path} must be a list"
        assert_contains_all(value, assertion["value"])
        return
    if op == "etag_matches_payload_fingerprint":
        etag = str(get_value(target, path))
        fingerprint = str(get_value(target, assertion["fingerprint_path"]))
        assert etag == f'"{fingerprint}"', f"{case_id}: {path} must match {assertion['fingerprint_path']}"
        return
    if op == "quoted_equals_value_from":
        value_from = resolve_reference(context, assertion["value_from"])
        assert str(get_value(target, path)) == f'"{value_from}"', f"{case_id}: {path}"
        return

    raise AssertionError(f"{case_id}: unsupported assertion op {op!r}")


class ContractFixtureTests(unittest.TestCase):
    def test_manifest_lists_expected_cases(self):
        manifest = load_manifest()
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual([case["id"] for case in manifest["cases"]], [
            "plan-envelope",
            "etag-fingerprint",
            "stale-write-conflict",
            "restore-roundtrip",
            "idempotent-evidence-dedupe",
        ])

    def test_plan_envelope_contract(self):
        case = load_json_fixture("plan-envelope.json")
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            response = run_request("GET", "/plan")

        context = {case["steps"][0]["capture"]: response}
        for assertion in case["assertions"]:
            assert_contract_assertion(case["id"], assertion, context)

    def test_etag_fingerprint_contract(self):
        case = load_json_fixture("etag-fingerprint.json")
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            before = run_request("GET", "/plan")
            after = run_request(
                "POST",
                "/plan",
                body=case["write_body"],
                headers={"Content-Type": "application/json", "If-Match": before["headers"]["ETag"]},
            )

        context = {"before": before, "after": after}
        for assertion in case["assertions"]:
            assert_contract_assertion(case["id"], assertion, context)

    def test_stale_write_conflict_contract(self):
        case = load_json_fixture("stale-write-conflict.json")
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            baseline = run_request("GET", "/plan")
            fresh = run_request(
                "POST",
                "/plan",
                body=case["fresh_write_body"],
                headers={"Content-Type": "application/json", "If-Match": baseline["headers"]["ETag"]},
            )
            stale = run_request(
                "POST",
                "/plan",
                body=case["stale_write_body"],
                headers={"Content-Type": "application/json", "If-Match": baseline["headers"]["ETag"]},
            )

        context = {"baseline": baseline, "fresh": fresh, "stale": stale}
        for assertion in case["assertions"]:
            assert_contract_assertion(case["id"], assertion, context)

    def test_restore_roundtrip_contract(self):
        case = load_json_fixture("restore-roundtrip.json")
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan.mutate_plan_state(lambda plan: plan.update(case["seed_plan_first"]), revision_source="contract_seed_first")
            deepplan.mutate_plan_state(lambda plan: plan.update(case["seed_plan_second"]), revision_source="contract_seed_second")
            current = run_request("GET", "/plan")
            preview = run_request("POST", "/restore/preview", body={"previous": True})
            restored = run_request(
                "POST",
                "/restore",
                body={"previous": True},
                headers={"Content-Type": "application/json", "If-Match": current["payload"]["fingerprint"]},
            )

        context = {"current": current, "preview": preview, "restored": restored}
        for assertion in case["assertions"]:
            assert_contract_assertion(case["id"], assertion, context)

    def test_idempotent_evidence_dedupe_contract(self):
        case = load_json_fixture("idempotent-evidence-dedupe.json")
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = run_request("POST", "/evidence", body=case["first_evidence_body"], headers={"Content-Type": "application/json"})
            second = run_request("POST", "/evidence", body=case["first_evidence_body"], headers={"Content-Type": "application/json"})

        context = {"first": first, "second": second}
        for assertion in case["assertions"]:
            assert_contract_assertion(case["id"], assertion, context)
