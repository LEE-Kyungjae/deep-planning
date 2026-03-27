#!/usr/bin/env python3
import io
import json
import tempfile
import unittest
from pathlib import Path

import deepplan
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


def decode_response(handler: DeepPlanHandler):
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    return handler._status, payload, handler._sent_headers


class DeepPlanServerTests(unittest.TestCase):
    def test_get_plan_returns_fingerprint_and_etag(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            handler = build_handler("GET", "/plan")
            handler.do_GET()
            status, payload, headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertIn("fingerprint", payload)
        self.assertEqual(headers.get("ETag"), f'"{payload["fingerprint"]}"')

    def test_post_plan_if_match_succeeds_and_updates_etag(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = build_handler("GET", "/plan")
            first.do_GET()
            _, initial_payload, headers = decode_response(first)

            body = json.dumps({"goal": "http update"}).encode("utf-8")
            handler = build_handler(
                "POST",
                "/plan",
                body=body,
                headers={"Content-Type": "application/json", "If-Match": headers["ETag"]},
            )
            handler.do_POST()
            status, payload, response_headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertEqual(payload["plan"]["goal"], "http update")
        self.assertNotEqual(payload["fingerprint"], initial_payload["fingerprint"])
        self.assertEqual(response_headers.get("ETag"), f'"{payload["fingerprint"]}"')

    def test_post_plan_rejects_stale_if_match(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = build_handler("GET", "/plan")
            first.do_GET()
            _, initial_payload, headers = decode_response(first)

            fresh_body = json.dumps({"goal": "first update"}).encode("utf-8")
            fresh = build_handler(
                "POST",
                "/plan",
                body=fresh_body,
                headers={"Content-Type": "application/json", "If-Match": headers["ETag"]},
            )
            fresh.do_POST()

            stale_body = json.dumps({"goal": "stale update"}).encode("utf-8")
            stale = build_handler(
                "POST",
                "/plan",
                body=stale_body,
                headers={"Content-Type": "application/json", "If-Match": f'"{initial_payload["fingerprint"]}"'},
            )
            stale.do_POST()
            status, payload, response_headers = decode_response(stale)

        self.assertEqual(status, 412)
        self.assertEqual(payload["error"], "plan fingerprint mismatch")
        self.assertIn("current_fingerprint", payload)
        self.assertEqual(response_headers.get("ETag"), f'"{payload["current_fingerprint"]}"')

    def test_post_plan_rejects_empty_body(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            handler = build_handler("POST", "/plan", body=b"", headers={"Content-Type": "application/json"})
            handler.do_POST()
            status, payload, _headers = decode_response(handler)

        self.assertEqual(status, 400)
        self.assertEqual(payload["error"], "empty_body")

    def test_get_history_returns_revision_entries(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            update = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "history endpoint"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            update.do_POST()
            handler = build_handler("GET", "/history")
            handler.do_GET()
            status, payload, _headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertTrue(payload["revisions"])
        self.assertEqual(payload["revisions"][0]["source"], "update_plan")
        self.assertIn("metadata", payload["revisions"][0])

    def test_get_health_returns_storage_diagnostics(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            handler = build_handler("GET", "/health")
            handler.do_GET()
            status, payload, _headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "ok")
        self.assertIn("logs", payload)
        self.assertIn("revisions", payload["logs"])
        self.assertIn("recovery_candidate_available", payload)

    def test_preview_restore_tool_wrapper_returns_diff_summary(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            update = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "preview baseline"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            update.do_POST()
            history = build_handler("GET", "/history")
            history.do_GET()
            _status, history_payload, _headers = decode_response(history)
            second = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "preview changed"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            second.do_POST()
            handler = build_handler(
                "POST",
                "/tools/preview_restore",
                body=json.dumps({"input": {"revision_id": history_payload["revisions"][-1]["revision_id"]}}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            handler.do_POST()
            status, payload, _headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertIn("changed_fields", payload["result"])
        self.assertIn("goal", payload["result"]["changed_fields"])
        self.assertIn("metadata", payload["result"])
        self.assertIn("diff", payload["result"])

    def test_restore_revision_tool_wrapper_rejects_stale_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first_get = build_handler("GET", "/plan")
            first_get.do_GET()
            _status, initial_payload, initial_headers = decode_response(first_get)

            first_update = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "first restore baseline"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "If-Match": initial_headers["ETag"]},
            )
            first_update.do_POST()

            history = build_handler("GET", "/history")
            history.do_GET()
            _status, history_payload, _headers = decode_response(history)

            second_update = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "second restore baseline"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            second_update.do_POST()

            stale_restore = build_handler(
                "POST",
                "/tools/restore_revision",
                body=json.dumps({"input": {"revision_id": history_payload["revisions"][-1]["revision_id"]}}).encode("utf-8"),
                headers={"Content-Type": "application/json", "If-Match": f'"{initial_payload["fingerprint"]}"'},
            )
            stale_restore.do_POST()
            status, payload, response_headers = decode_response(stale_restore)

        self.assertEqual(status, 412)
        self.assertEqual(payload["error"], "plan fingerprint mismatch")
        self.assertIn("current_fingerprint", payload)
        self.assertEqual(response_headers.get("ETag"), f'"{payload["current_fingerprint"]}"')

    def test_agent_act_maps_restore_preview_command(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            update = build_handler(
                "POST",
                "/plan",
                body=json.dumps({"goal": "agent act preview"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            update.do_POST()
            history = build_handler("GET", "/history")
            history.do_GET()
            _status, history_payload, _headers = decode_response(history)
            handler = build_handler(
                "POST",
                "/agent/act",
                body=json.dumps({"input": f"/deepplan.restore-preview revision_id={history_payload['revisions'][-1]['revision_id']}"}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            handler.do_POST()
            status, payload, _headers = decode_response(handler)

        self.assertEqual(status, 200)
        self.assertEqual(payload["tool"], "preview_restore")
        self.assertIn("changed_fields", payload["result"])


if __name__ == "__main__":
    unittest.main()
