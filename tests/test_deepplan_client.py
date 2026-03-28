#!/usr/bin/env python3
import io
import json
import tempfile
import unittest
from pathlib import Path

import deepplan
from deepplan_client import DeepPlanClient, DeepPlanClientError, DeepPlanClientOperationError, DeepPlanConflictError
from deepplan_server import DeepPlanHandler


class DeepPlanStateIsolation:
    def __init__(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.state_dir = self.root / ".deeplan"
        self.originals = {}

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


def build_handler(method: str, path: str, body: bytes = b"", headers=None) -> DeepPlanHandler:
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


def handler_transport(method: str, path: str, body=None, headers=None):
    raw_body = json.dumps(body).encode("utf-8") if body is not None else b""
    handler = build_handler(method, path, body=raw_body, headers=headers)
    if method == "GET":
        handler.do_GET()
    else:
        handler.do_POST()
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    return handler._status, payload, handler._sent_headers


class DeepPlanClientTests(unittest.TestCase):
    def test_get_plan_tracks_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            result = client.get_plan()

        self.assertTrue(result["ok"])
        self.assertEqual(client.tracked_fingerprint, result["fingerprint"])

    def test_get_cycle_returns_integrated_snapshot_and_tracks_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            seed = deepplan.mutate_plan_state(
                lambda plan: plan.update(
                    {
                        "goal": "client cycle",
                        "success_metric": "Reach 2 pilots",
                        "deadline": "2026-04-03",
                    }
                ),
                revision_source="test_client_cycle",
            )
            client = DeepPlanClient(transport=handler_transport)
            result = client.get_cycle(history_limit=1)

        self.assertEqual(result["result_type"], "cycle")
        self.assertEqual(result["plan"]["goal"], "client cycle")
        self.assertIn("score", result["qa"])
        self.assertIn("status", result["health"])
        self.assertEqual(result["history_limit"], 1)
        self.assertEqual(len(result["history"]), 1)
        self.assertEqual(client.tracked_fingerprint, deepplan.plan_fingerprint(seed))

    def test_update_plan_uses_tracked_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            client.get_plan()
            result = client.update_plan(
                {
                    "goal": "client update",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )

        self.assertEqual(result["plan"]["goal"], "client update")
        self.assertEqual(client.tracked_fingerprint, result["fingerprint"])

    def test_restore_previous_works_through_client(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            first = client.update_plan(
                {
                    "goal": "client previous first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            second = client.update_plan({"goal": "client previous second"})
            preview = client.preview_restore(previous=True)
            restored = client.restore_revision(previous=True, expected_fingerprint=second["fingerprint"])

        self.assertEqual(preview["selected_via"], "previous")
        self.assertEqual(preview["metadata"]["goal"], "client previous first")
        self.assertEqual(restored["plan"]["goal"], "client previous first")
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_capture_evidence_cycle_returns_typed_multi_step_result(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            client.update_plan(
                {
                    "goal": "client evidence cycle",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            result = client.capture_evidence_cycle(
                {
                    "claim": "Repeated pilot friction",
                    "source": "pilot-call",
                    "confidence": 74,
                    "axis": "market",
                },
                replan_payload={"plan_task": "Tighten onboarding loop"},
                history_limit=2,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["operation"], "capture_evidence_cycle")
        self.assertEqual(result["result_type"], "planning_cycle")
        self.assertNotEqual(result["pre_fingerprint"], result["post_fingerprint"])
        self.assertIn("evidence", result["changed_fields"])
        self.assertIn("plan_tasks", result["changed_fields"])
        self.assertEqual(result["evidence_result"]["plan"]["evidence"][-1]["claim"], "Repeated pilot friction")
        self.assertEqual(result["replan_result"]["plan"]["plan_tasks"][-1], "Tighten onboarding loop")
        self.assertEqual(result["post_cycle"]["plan"]["evidence"][-1]["source"], "pilot-call")
        self.assertEqual(result["post_cycle"]["history_limit"], 2)
        self.assertEqual(client.tracked_fingerprint, result["post_fingerprint"])
        self.assertIn("add_evidence", result["step_results"])
        self.assertIn("replan", result["step_results"])

    def test_apply_and_get_cycle_wraps_update_plan_with_post_cycle_snapshot(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            result = client.apply_and_get_cycle(
                "update_plan",
                {
                    "goal": "wrapped update",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
                history_limit=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["operation"], "update_plan")
        self.assertEqual(result["mutation_result"]["plan"]["goal"], "wrapped update")
        self.assertEqual(result["post_cycle"]["plan"]["goal"], "wrapped update")
        self.assertEqual(result["post_cycle"]["history_limit"], 1)
        self.assertEqual(client.tracked_fingerprint, result["post_fingerprint"])

    def test_apply_and_get_cycle_wraps_restore_revision_with_post_cycle_snapshot(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            first = client.update_plan(
                {
                    "goal": "wrapped restore first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            second = client.update_plan({"goal": "wrapped restore second"})
            result = client.apply_and_get_cycle(
                "restore_revision",
                {"previous": True},
                expected_fingerprint=second["fingerprint"],
                history_limit=1,
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["operation"], "restore_revision")
        self.assertEqual(result["mutation_result"]["plan"]["goal"], "wrapped restore first")
        self.assertEqual(result["post_cycle"]["plan"]["goal"], "wrapped restore first")
        self.assertEqual(result["post_cycle"]["history_limit"], 1)
        self.assertEqual(client.tracked_fingerprint, result["post_fingerprint"])
        self.assertNotEqual(first["fingerprint"], second["fingerprint"])

    def test_apply_and_get_cycle_surfaces_typed_operation_error(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            with self.assertRaises(DeepPlanClientOperationError) as ctx:
                client.apply_and_get_cycle("add_evidence", {"claim": " "})

        self.assertEqual(ctx.exception.operation, "add_evidence")
        self.assertEqual(ctx.exception.step, "mutation")
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(ctx.exception.payload["error"], "claim is required")

    def test_stale_fingerprint_raises_typed_conflict_error(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            first = client.get_plan()
            client.update_plan(
                {
                    "goal": "fresh write",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            with self.assertRaises(DeepPlanConflictError) as ctx:
                client.update_plan({"goal": "stale write"}, expected_fingerprint=first["fingerprint"])

        self.assertEqual(ctx.exception.status, 412)
        self.assertEqual(ctx.exception.payload["error"], "plan fingerprint mismatch")
        self.assertEqual(ctx.exception.expected_fingerprint, first["fingerprint"])
        self.assertTrue(ctx.exception.current_fingerprint)
        self.assertTrue(ctx.exception.can_refresh)

    def test_apply_and_get_cycle_surfaces_typed_conflict_error_with_operation_context(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            initial = client.get_plan()
            client.update_plan(
                {
                    "goal": "conflict baseline",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            with self.assertRaises(DeepPlanConflictError) as ctx:
                client.apply_and_get_cycle(
                    "update_plan",
                    {"goal": "stale wrapped update"},
                    expected_fingerprint=initial["fingerprint"],
                )

        self.assertEqual(ctx.exception.operation, "update_plan")
        self.assertEqual(ctx.exception.step, "mutation")
        self.assertEqual(ctx.exception.status, 412)
        self.assertEqual(ctx.exception.expected_fingerprint, initial["fingerprint"])
        self.assertTrue(ctx.exception.current_fingerprint)

    def test_apply_and_get_cycle_with_retry_recovers_from_stale_fingerprint_once(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            initial = client.get_plan()
            client.update_plan(
                {
                    "goal": "retry baseline",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            result = client.apply_and_get_cycle_with_retry(
                "update_plan",
                {"goal": "retry recovered"},
                expected_fingerprint=initial["fingerprint"],
                history_limit=1,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["retried"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["operation"], "update_plan")
        self.assertEqual(result["post_cycle"]["plan"]["goal"], "retry recovered")
        self.assertEqual(result["retry_from_fingerprint"], initial["fingerprint"])
        self.assertTrue(result["retry_to_fingerprint"])
        self.assertEqual(client.tracked_fingerprint, result["post_fingerprint"])

    def test_apply_and_get_cycle_with_retry_recovers_restore_revision_once(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            initial = client.get_plan()
            client.update_plan(
                {
                    "goal": "retry restore first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            latest = client.update_plan({"goal": "retry restore second"})
            result = client.apply_and_get_cycle_with_retry(
                "restore_revision",
                {"previous": True},
                expected_fingerprint=initial["fingerprint"],
                history_limit=1,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["retried"])
        self.assertEqual(result["attempts"], 2)
        self.assertEqual(result["operation"], "restore_revision")
        self.assertEqual(result["post_cycle"]["plan"]["goal"], "retry restore first")
        self.assertEqual(result["retry_from_fingerprint"], initial["fingerprint"])
        self.assertTrue(result["retry_to_fingerprint"])
        self.assertNotEqual(latest["fingerprint"], result["post_fingerprint"])

    def test_apply_and_get_cycle_with_retry_does_not_retry_validation_error(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            with self.assertRaises(DeepPlanClientOperationError) as ctx:
                client.apply_and_get_cycle_with_retry("add_evidence", {"claim": " "})

        self.assertEqual(ctx.exception.operation, "add_evidence")
        self.assertEqual(ctx.exception.step, "mutation")
        self.assertEqual(ctx.exception.status, 400)

    def test_apply_and_get_cycle_with_retry_does_not_retry_add_evidence_by_default(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            initial = client.get_plan()
            client.update_plan(
                {
                    "goal": "retry add evidence baseline",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            with self.assertRaises(DeepPlanConflictError) as ctx:
                client.apply_and_get_cycle_with_retry(
                    "add_evidence",
                    {"claim": "Pilot friction repeated", "source": "pilot-call", "confidence": 74},
                    expected_fingerprint=initial["fingerprint"],
                )

        self.assertEqual(ctx.exception.operation, "add_evidence")
        self.assertEqual(ctx.exception.step, "mutation")
        self.assertEqual(ctx.exception.expected_fingerprint, initial["fingerprint"])

    def test_apply_and_get_cycle_with_retry_can_opt_in_for_add_evidence(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            client = DeepPlanClient(transport=handler_transport)
            initial = client.get_plan()
            client.update_plan(
                {
                    "goal": "retry add evidence opt-in",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                }
            )
            result = client.apply_and_get_cycle_with_retry(
                "add_evidence",
                {"claim": "Opt-in retry evidence", "source": "pilot-call", "confidence": 74},
                expected_fingerprint=initial["fingerprint"],
                allow_non_idempotent_retry=True,
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["retried"])
        self.assertEqual(result["operation"], "add_evidence")
        self.assertEqual(result["post_cycle"]["plan"]["evidence"][-1]["claim"], "Opt-in retry evidence")


if __name__ == "__main__":
    unittest.main()
