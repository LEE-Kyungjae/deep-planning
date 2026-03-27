#!/usr/bin/env python3
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import deepplan
import deepplan_agent


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


class DeepPlanRegressionTests(unittest.TestCase):
    def test_slash_command_mapping_covers_restore_preview(self):
        tool_name, payload = deepplan_agent.slash_to_tool("/deepplan.restore-preview revision_id=rev-123")

        self.assertEqual(tool_name, "preview_restore")
        self.assertEqual(payload, {"revision_id": "rev-123"})

    def test_natural_language_mapping_covers_restore_revision(self):
        tool_name, payload = deepplan_agent.natural_language_to_tool("restore revision revision_id=rev-456")

        self.assertEqual(tool_name, "restore_revision")
        self.assertEqual(payload, {"revision_id": "rev-456"})

    def test_natural_language_mapping_covers_previous_revision_shortcuts(self):
        preview_tool, preview_payload = deepplan_agent.natural_language_to_tool("preview previous revision")
        restore_tool, restore_payload = deepplan_agent.natural_language_to_tool("restore previous revision")

        self.assertEqual(preview_tool, "preview_restore")
        self.assertEqual(preview_payload, {"previous": True})
        self.assertEqual(restore_tool, "restore_revision")
        self.assertEqual(restore_payload, {"previous": True})

    def test_qa_autoreplan_upgrades_thin_plan_to_pass(self):
        plan = deepplan.default_plan()
        plan["goal"] = "Test goal"
        plan["success_metric"] = "Reach 3 pilot users"
        plan["deadline"] = "2026-04-10"

        with DeepPlanStateIsolation():
            result = deepplan.qa_autoreplan_result(plan)

        self.assertTrue(result["auto_replan"]["triggered"])
        self.assertEqual(result["auto_replan"]["blocked"], [])
        self.assertEqual(result["qa"]["result"], "PASS")
        self.assertEqual(result["qa"]["result"], "PASS")
        self.assertGreaterEqual(result["qa"]["score"], result["qa"]["threshold"])
        self.assertTrue(result["plan"]["planning_horizon"])
        self.assertTrue(result["plan"]["review_cadence"])
        self.assertGreaterEqual(len(result["plan"]["references"]), 3)

    def test_qa_autoreplan_blocks_manual_core_fields(self):
        plan = deepplan.default_plan()

        with DeepPlanStateIsolation():
            result = deepplan.qa_autoreplan_result(plan)

        self.assertTrue(result["auto_replan"]["triggered"])
        self.assertIn("goal_clarity", result["auto_replan"]["blocked"])
        self.assertIn("measurability", result["auto_replan"]["blocked"])
        self.assertEqual(result["qa"]["result"], "CRITICAL_FAILURE")

    def test_update_plan_tool_returns_autoreplan_metadata(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            result = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "Thin plan test",
                    "success_metric": "Hit 2 pilots",
                    "deadline": "2026-04-01",
                    "constraints": [],
                    "assumptions": [],
                    "options": [],
                    "plan_tasks": [],
                    "execution_tasks": [],
                    "dependencies": [],
                    "experiments": [],
                    "risks": [],
                    "references": [],
                    "insights": [],
                    "direction_insights": [],
                    "market_insights": [],
                    "timing_insights": [],
                    "differentiation_insights": [],
                    "monetization_insights": [],
                    "constraint_insights": [],
                    "risk_signal_insights": [],
                    "evolution_insights": [],
                    "definition_of_done": [],
                },
            )
            event_lines = deepplan.EVENTS_PATH.read_text(encoding="utf-8").strip().splitlines()
            auto_replan_events = [json.loads(line) for line in event_lines if '"type": "auto_replan"' in line]
            summary = deepplan.plan_summary(result["plan"])

        self.assertIn("auto_replan", result)
        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_name"], "update_plan")
        self.assertEqual(result["result_type"], "mutation")
        self.assertTrue(result["auto_replan"]["triggered"])
        self.assertEqual(result["auto_replan"]["blocked"], [])
        self.assertEqual(result["qa"]["result"], "PASS")
        self.assertEqual(result["validation"], {"valid": True, "errors": []})
        self.assertEqual(result["fingerprint"], deepplan.plan_fingerprint(result["plan"]))
        self.assertTrue(auto_replan_events)
        self.assertIn("final_score", auto_replan_events[-1])
        self.assertIn("score_delta", auto_replan_events[-1])
        self.assertIsNotNone(summary["recent_auto_replan"])
        self.assertEqual(summary["recent_auto_replan"]["final_result"], "PASS")
        self.assertTrue(summary["recent_auto_replan"]["actions"])

    def test_mutate_plan_state_rejects_stale_expected_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            initial = deepplan.load_plan()
            initial_fingerprint = deepplan.plan_fingerprint(initial)
            updated = deepplan.mutate_plan_state(lambda plan: plan.update({"goal": "first"}))
            self.assertEqual(updated["goal"], "first")

            with self.assertRaises(deepplan.PlanConflictError) as ctx:
                deepplan.mutate_plan_state(
                    lambda plan: plan.update({"goal": "second"}),
                    expected_fingerprint=initial_fingerprint,
                )

        self.assertEqual(ctx.exception.current_fingerprint, deepplan.plan_fingerprint(updated))

    def test_update_plan_tool_rejects_stale_expected_fingerprint(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool("get_plan", {})
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "fresh write",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            with self.assertRaisesRegex(deepplan.PlanConflictError, "plan fingerprint mismatch"):
                deepplan_agent.execute_tool(
                    "update_plan",
                    {
                        "goal": "stale write",
                        "expected_fingerprint": first["fingerprint"],
                    },
                )

    def test_replan_tool_validates_confidence_type(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            with self.assertRaisesRegex(ValueError, "evidence_confidence must be an integer"):
                deepplan_agent.execute_tool(
                    "replan",
                    {
                        "evidence": "pilot feedback",
                        "evidence_confidence": "high",
                    },
                )

    def test_replan_tool_persists_incremental_fields_and_metadata(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "Seed plan",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                    "constraints": [],
                    "assumptions": [],
                    "options": [],
                    "plan_tasks": [],
                    "execution_tasks": [],
                    "dependencies": [],
                    "experiments": [],
                    "risks": [],
                    "references": [],
                    "insights": [],
                    "direction_insights": [],
                    "market_insights": [],
                    "timing_insights": [],
                    "differentiation_insights": [],
                    "monetization_insights": [],
                    "constraint_insights": [],
                    "risk_signal_insights": [],
                    "evolution_insights": [],
                    "definition_of_done": [],
                },
            )
            result = deepplan_agent.execute_tool(
                "replan",
                {
                    "evidence": "pilot users returned after week one",
                    "evidence_confidence": 71,
                    "evidence_axis": "market",
                    "plan_task": "Refine segment definition",
                    "execution_task": "Interview three pilot users",
                    "reference": "pilot:week-1",
                },
            )

        self.assertIn("summary", result)
        self.assertIn("validation", result)
        self.assertIn("auto_replan", result)
        self.assertEqual(result["validation"], {"valid": True, "errors": []})
        self.assertEqual(result["qa"]["result"], "PASS")
        self.assertIn("Refine segment definition", result["plan"]["plan_tasks"])
        self.assertIn("Interview three pilot users", result["plan"]["execution_tasks"])
        self.assertIn("pilot:week-1", result["plan"]["references"])
        self.assertTrue(
            any(
                isinstance(item, dict) and item.get("claim") == "pilot users returned after week one"
                for item in result["plan"]["evidence"]
            )
        )

    def test_blocked_autoreplan_event_has_no_final_score(self):
        plan = deepplan.default_plan()

        with DeepPlanStateIsolation():
            result = deepplan.qa_autoreplan_result(plan)
            events = [json.loads(line) for line in deepplan.EVENTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertTrue(result["auto_replan"]["triggered"])
        self.assertTrue(result["auto_replan"]["blocked"])
        auto_replan_events = [event for event in events if event.get("type") == "auto_replan"]
        self.assertEqual(len(auto_replan_events), 1)
        self.assertNotIn("final_score", auto_replan_events[0])
        self.assertNotIn("score_delta", auto_replan_events[0])

    def test_no_autoreplan_does_not_emit_autoreplan_event(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            plan = deepplan.load_plan()
            plan.update(
                {
                    "goal": "Complete plan",
                    "success_metric": "Reach 3 pilots",
                    "deadline": "2026-04-05",
                    "planning_horizon": "3 weeks",
                    "review_cadence": "weekly",
                    "constraints": ["time: 1h/day"],
                    "assumptions": ["Target users have recurring pain."],
                    "options": ["Option A", "Option B"],
                    "selected_option": "Option A",
                    "plan_tasks": ["Define references", "Choose strategy"],
                    "execution_tasks": ["Run pilot", "Track outcomes"],
                    "dependencies": ["Agent runtime support"],
                    "experiments": ["Run one pilot loop."],
                    "risks": [{"risk": "Scope drift", "signal": "new requests", "mitigation": "freeze scope"}],
                    "references": ["ref-a", "ref-b", "ref-c"],
                    "insights": ["Planning matters", "Evidence matters", "Replan from signals"],
                    "direction_insights": ["why now", "decision leverage", "deprioritize distractions"],
                    "market_insights": ["target segment pain", "high-frequency need", "switching pain"],
                    "timing_insights": ["window is open", "delay costs learning", "market timing matters"],
                    "differentiation_insights": ["distinct angle", "visible first-session difference", "clear tradeoff"],
                    "monetization_insights": ["value to revenue path", "early pricing proxy", "paid signal"],
                    "constraint_insights": ["time limited", "resource cap", "scope cap"],
                    "risk_signal_insights": ["early churn signal", "false momentum metric", "replan trigger"],
                    "evolution_insights": ["weekly plan review", "review evidence", "compound learning"],
                    "definition_of_done": ["QA passes", "pilot is measured"],
                    "evidence": [
                        {"claim": "Users repeated pain weekly", "source": "interviews", "confidence": 72, "axis": "market", "date": "2026-03-20"},
                        {"claim": "Alternatives fail core workflow", "source": "competitor-review", "confidence": 70, "axis": "differentiation", "date": "2026-03-20"},
                        {"claim": "Users pay for time savings", "source": "pricing-survey", "confidence": 66, "axis": "monetization", "date": "2026-03-20"},
                    ],
                    "hypothesis_log": [
                        {"ts": "2026-03-20T00:00:00+00:00", "hypothesis": "Narrow segment returns weekly", "metric": "wau", "target": ">=3", "window": "7 days", "status": "open", "outcome": ""}
                    ],
                    "phase_plan": ["Phase 1", "Phase 2", "Phase 3"],
                }
            )
            deepplan.save_validated_plan(plan)
            result = deepplan.qa_autoreplan_result(plan)
            events = [json.loads(line) for line in deepplan.EVENTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertFalse(result["auto_replan"]["triggered"])
        self.assertFalse(any(event.get("type") == "auto_replan" for event in events))

    def test_critical_failure_can_still_trigger_autoreplan_when_score_is_high(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            plan = deepplan.load_plan()
            plan.update(
                {
                    "goal": "High score critical failure",
                    "success_metric": "Reach 3 pilots",
                    "deadline": "2026-04-05",
                    "planning_horizon": "3 weeks",
                    "review_cadence": "weekly",
                    "constraints": ["time: 1h/day"],
                    "assumptions": ["Users have recurring pain."],
                    "options": ["Option A", "Option B"],
                    "selected_option": "Option A",
                    "plan_tasks": ["Define references", "Choose strategy"],
                    "execution_tasks": ["Run pilot", "Track outcomes"],
                    "dependencies": ["Agent runtime support"],
                    "experiments": ["Run one pilot loop."],
                    "risks": [{"risk": "Scope drift", "signal": "new requests", "mitigation": "freeze scope"}],
                    "references": ["ref-a", "ref-b", "ref-c"],
                    "insights": ["Planning matters", "Evidence matters", "Replan from signals"],
                    "direction_insights": ["why now", "decision leverage", "deprioritize distractions"],
                    "market_insights": ["target segment pain", "high-frequency need", "switching pain"],
                    "timing_insights": ["window is open", "delay costs learning", "market timing matters"],
                    "differentiation_insights": ["distinct angle", "visible first-session difference", "clear tradeoff"],
                    "monetization_insights": ["value to revenue path", "early pricing proxy", "paid signal"],
                    "constraint_insights": ["time limited", "resource cap", "scope cap"],
                    "risk_signal_insights": ["early churn signal", "false momentum metric", "replan trigger"],
                    "evolution_insights": ["weekly plan review", "review evidence", "compound learning"],
                    "definition_of_done": [],
                    "evidence": [
                        {"claim": "Users repeated pain weekly", "source": "interviews", "confidence": 72, "axis": "market", "date": "2026-03-20"},
                        {"claim": "Alternatives fail core workflow", "source": "competitor-review", "confidence": 70, "axis": "differentiation", "date": "2026-03-20"},
                        {"claim": "Users pay for time savings", "source": "pricing-survey", "confidence": 66, "axis": "monetization", "date": "2026-03-20"},
                    ],
                    "hypothesis_log": [
                        {"ts": "2026-03-20T00:00:00+00:00", "hypothesis": "Narrow segment returns weekly", "metric": "wau", "target": ">=3", "window": "7 days", "status": "open", "outcome": ""}
                    ],
                    "phase_plan": ["Phase 1", "Phase 2", "Phase 3"],
                }
            )
            result = deepplan.qa_autoreplan_result(plan)

        self.assertTrue(result["auto_replan"]["triggered"])
        self.assertEqual(result["auto_replan"]["blocked"], [])
        self.assertEqual(result["qa"]["result"], "PASS")
        self.assertTrue(result["plan"]["definition_of_done"])

    def test_plan_summary_ignores_stale_autoreplan_event(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "Summary freshness",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                    "constraints": [],
                    "assumptions": [],
                    "options": [],
                    "plan_tasks": [],
                    "execution_tasks": [],
                    "dependencies": [],
                    "experiments": [],
                    "risks": [],
                    "references": [],
                    "insights": [],
                    "direction_insights": [],
                    "market_insights": [],
                    "timing_insights": [],
                    "differentiation_insights": [],
                    "monetization_insights": [],
                    "constraint_insights": [],
                    "risk_signal_insights": [],
                    "evolution_insights": [],
                    "definition_of_done": [],
                },
            )
            plan = deepplan.load_plan()
            plan["goal"] = "Manual follow-up edit"
            deepplan.save_validated_plan(plan)
            summary = deepplan.plan_summary(plan)

        self.assertIsNone(summary["recent_auto_replan"])

    def test_show_prints_recent_auto_replan_summary(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "Show summary test",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                    "constraints": [],
                    "assumptions": [],
                    "options": [],
                    "plan_tasks": [],
                    "execution_tasks": [],
                    "dependencies": [],
                    "experiments": [],
                    "risks": [],
                    "references": [],
                    "insights": [],
                    "direction_insights": [],
                    "market_insights": [],
                    "timing_insights": [],
                    "differentiation_insights": [],
                    "monetization_insights": [],
                    "constraint_insights": [],
                    "risk_signal_insights": [],
                    "evolution_insights": [],
                    "definition_of_done": [],
                },
            )
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                deepplan.cmd_show(None)
            output = stdout.getvalue()

        self.assertIn("Recent Auto Replan:", output)
        self.assertIn("Recent Auto Replan Actions:", output)

    def test_update_plan_records_revision_history_and_restore_revision_tool(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "first goal",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            second = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "second goal",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            history = deepplan_agent.execute_tool("get_history", {"limit": 10})
            restored = deepplan_agent.execute_tool(
                "restore_revision",
                {
                    "revision_id": history["revisions"][-1]["revision_id"],
                    "expected_fingerprint": second["fingerprint"],
                },
            )

        self.assertGreaterEqual(len(history["revisions"]), 2)
        self.assertEqual(history["revisions"][0]["source"], "update_plan")
        self.assertIn("metadata", history["revisions"][0])
        self.assertEqual(history["revisions"][0]["metadata"]["qa_result"], "PASS")
        self.assertEqual(restored["restored_revision_id"], history["revisions"][-1]["revision_id"])
        self.assertEqual(restored["plan"]["goal"], "first goal")
        self.assertEqual(restored["fingerprint"], deepplan.plan_fingerprint(restored["plan"]))

    def test_cmd_history_and_restore_print_revision_info(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "history print test",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            revisions = deepplan.list_revisions(limit=1)
            history_stdout = io.StringIO()
            with redirect_stdout(history_stdout):
                deepplan.cmd_history(type("Args", (), {"limit": 5, "json": False})())
            restore_stdout = io.StringIO()
            with redirect_stdout(restore_stdout):
                deepplan.cmd_restore(
                    type(
                        "Args",
                        (),
                        {
                            "revision_id": revisions[0]["revision_id"],
                            "expected_fingerprint": "",
                        },
                    )()
                )

        self.assertIn(revisions[0]["revision_id"], history_stdout.getvalue())
        self.assertIn("Restored revision", restore_stdout.getvalue())
        self.assertIn("qa=", history_stdout.getvalue())

    def test_preview_restore_reports_changed_fields_without_mutation(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "preview first goal",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            second = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "preview second goal",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            history = deepplan_agent.execute_tool("get_history", {"limit": 10})
            preview = deepplan_agent.execute_tool(
                "preview_restore",
                {
                    "revision_id": history["revisions"][-1]["revision_id"],
                },
            )
            current_plan = deepplan.load_plan()

        self.assertFalse(preview["no_op"])
        self.assertIn("goal", preview["changed_fields"])
        self.assertIn("metadata", preview)
        self.assertEqual(preview["metadata"]["goal"], "preview first goal")
        self.assertTrue(preview["diff"])
        goal_diff = next(item for item in preview["diff"] if item["field"] == "goal")
        self.assertEqual(goal_diff["before"]["type"], "scalar")
        self.assertEqual(goal_diff["after"]["type"], "scalar")
        self.assertEqual(current_plan["goal"], "preview second goal")
        self.assertEqual(preview["current_fingerprint"], second["fingerprint"])

    def test_restore_revision_tool_emits_plan_restored_event(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "restore source goal",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            second = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "restore target goal",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            history = deepplan_agent.execute_tool("get_history", {"limit": 10})
            deepplan_agent.execute_tool(
                "restore_revision",
                {
                    "revision_id": history["revisions"][-1]["revision_id"],
                    "expected_fingerprint": second["fingerprint"],
                },
            )
            events = [json.loads(line) for line in deepplan.EVENTS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        self.assertTrue(any(event.get("type") == "plan_restored" and event.get("source") == "restore_revision" for event in events))

    def test_restore_previous_revision_without_revision_id(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "previous first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            second = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "previous second",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            restored = deepplan_agent.execute_tool(
                "restore_revision",
                {
                    "previous": True,
                    "expected_fingerprint": second["fingerprint"],
                },
            )

        self.assertEqual(restored["plan"]["goal"], "previous first")

    def test_preview_previous_revision_without_revision_id(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "preview previous first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "preview previous second",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            preview = deepplan_agent.execute_tool("preview_restore", {"previous": True})

        self.assertEqual(preview["selected_via"], "previous")
        self.assertEqual(preview["metadata"]["goal"], "preview previous first")

    def test_storage_health_report_detects_invalid_event_lines(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan.EVENTS_PATH.write_text('{"type":"ok"}\nnot-json\n', encoding="utf-8")
            report = deepplan.storage_health_report()

        self.assertEqual(report["status"], "degraded")
        self.assertEqual(report["logs"]["events"]["invalid_lines"], 1)
        self.assertTrue(any(issue.startswith("events_invalid_lines:1") for issue in report["issues"]))

    def test_revision_retention_prunes_to_latest_window(self):
        with DeepPlanStateIsolation():
            deepplan.REVISION_RETENTION_LIMIT = 2
            deepplan.ensure_state()
            first = deepplan.mutate_plan_state(
                lambda plan: plan.update(
                    {
                        "goal": "retained first",
                        "success_metric": "Reach 2 pilots",
                        "deadline": "2026-04-03",
                    }
                ),
                revision_source="test_retention",
            )
            second = deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "retained second"}),
                expected_fingerprint=deepplan.plan_fingerprint(first),
                revision_source="test_retention",
            )
            deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "retained third"}),
                expected_fingerprint=deepplan.plan_fingerprint(second),
                revision_source="test_retention",
            )
            revisions = deepplan.list_revisions(limit=0)

        self.assertEqual(len(revisions), 2)
        self.assertEqual([item["metadata"]["goal"] for item in revisions], ["retained third", "retained second"])

    def test_restore_previous_survives_revision_pruning_floor(self):
        with DeepPlanStateIsolation():
            deepplan.REVISION_RETENTION_LIMIT = 1
            deepplan.ensure_state()
            first = deepplan.mutate_plan_state(
                lambda plan: plan.update(
                    {
                        "goal": "restore floor first",
                        "success_metric": "Reach 2 pilots",
                        "deadline": "2026-04-03",
                    }
                ),
                revision_source="test_restore_floor",
            )
            second = deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "restore floor second"}),
                expected_fingerprint=deepplan.plan_fingerprint(first),
                revision_source="test_restore_floor",
            )
            deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "restore floor third"}),
                expected_fingerprint=deepplan.plan_fingerprint(second),
                revision_source="test_restore_floor",
            )
            restored = deepplan_agent.execute_tool(
                "restore_revision",
                {
                    "previous": True,
                    "expected_fingerprint": deepplan.plan_fingerprint(deepplan.load_plan()),
                },
            )

        self.assertEqual(restored["plan"]["goal"], "restore floor second")

    def test_event_retention_prunes_to_latest_window(self):
        with DeepPlanStateIsolation():
            deepplan.EVENT_RETENTION_LIMIT = 2
            deepplan.ensure_state()
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt1"})
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt2"})
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt3"})
            events = deepplan.read_jsonl(deepplan.EVENTS_PATH)

        self.assertEqual([event["type"] for event in events], ["evt2", "evt3"])

    def test_storage_health_report_tracks_latest_recoverable_revision(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            result = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "health revision test",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            report = deepplan.storage_health_report()

        self.assertTrue(report["recovery_candidate_available"])
        self.assertTrue(report["latest_recoverable_revision_id"])
        self.assertEqual(report["latest_recoverable_revision_fingerprint"], result["fingerprint"])
        self.assertTrue(report["current_matches_latest_revision"])

    def test_storage_health_report_flags_divergence_from_latest_revision(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "divergence baseline",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            plan = deepplan.load_plan()
            plan["goal"] = "manual divergence"
            deepplan.save_validated_plan(plan)
            report = deepplan.storage_health_report()

        self.assertFalse(report["current_matches_latest_revision"])
        self.assertIn("current_plan_differs_from_latest_revision", report["issues"])

    def test_storage_health_report_includes_retention_limits_after_prune(self):
        with DeepPlanStateIsolation():
            deepplan.EVENT_RETENTION_LIMIT = 2
            deepplan.REVISION_RETENTION_LIMIT = 2
            deepplan.ensure_state()
            first = deepplan.mutate_plan_state(
                lambda plan: plan.update(
                    {
                        "goal": "health retention first",
                        "success_metric": "Reach 2 pilots",
                        "deadline": "2026-04-03",
                    }
                ),
                revision_source="test_health_retention",
            )
            second = deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "health retention second"}),
                expected_fingerprint=deepplan.plan_fingerprint(first),
                revision_source="test_health_retention",
            )
            deepplan.mutate_plan_state(
                lambda plan: plan.update({"goal": "health retention third"}),
                expected_fingerprint=deepplan.plan_fingerprint(second),
                revision_source="test_health_retention",
            )
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt1"})
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt2"})
            deepplan.append_jsonl(deepplan.EVENTS_PATH, {"type": "evt3"})
            report = deepplan.storage_health_report()

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["logs"]["events"]["retention_limit"], 2)
        self.assertEqual(report["logs"]["events"]["line_count"], 2)
        self.assertEqual(report["logs"]["revisions"]["retention_limit"], 2)
        self.assertEqual(report["logs"]["revisions"]["line_count"], 2)
        self.assertEqual(report["retention"]["logs"]["events"]["line_count"], 2)

    def test_cmd_health_prints_storage_diagnostics(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                deepplan.cmd_health(type("Args", (), {"json": False})())
            output = stdout.getvalue()

        self.assertIn("Status:", output)
        self.assertIn("Revision Count:", output)
        self.assertIn("Writable:", output)
        self.assertIn("Latest Recoverable Revision:", output)
        self.assertIn("Events Retention:", output)

    def test_runtime_schema_matches_checked_in_schema(self):
        report = deepplan.schema_drift_report()

        self.assertTrue(report["matches"])
        self.assertEqual(report["runtime_required_count"], report["file_required_count"])
        self.assertEqual(report["runtime_property_count"], report["file_property_count"])

    def test_cmd_schema_check_prints_contract_status(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            deepplan.cmd_schema(type("Args", (), {"check": True, "write": False, "json": False})())
        output = stdout.getvalue()

        self.assertIn("Schema Match: yes", output)

    def test_cmd_run_dry_run_returns_restore_preview_envelope(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            deepplan_agent.cmd_run(
                type(
                    "Args",
                    (),
                    {
                        "input": "/deepplan.restore-preview revision_id=rev-789",
                        "dry_run": True,
                    },
                )()
            )
        payload = json.loads(stdout.getvalue())

        self.assertEqual(payload["tool"], "preview_restore")
        self.assertEqual(payload["input"], {"revision_id": "rev-789"})

    def test_tool_schema_contract_report_matches_runtime_expectations(self):
        report = deepplan_agent.tool_schema_contract_report()

        self.assertTrue(report["matches"])
        self.assertEqual(report["missing"], [])
        self.assertEqual(report["unexpected"], [])
        self.assertEqual(report["missing_validators"], [])
        self.assertEqual(report["additional_properties_true"], [])
        self.assertEqual(report["mutation_tools_missing_expected_fingerprint"], [])

    def test_get_plan_returns_normalized_result_fields(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            result = deepplan_agent.execute_tool("get_plan", {})

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_name"], "get_plan")
        self.assertEqual(result["result_type"], "plan")

    def test_preview_restore_returns_normalized_result_fields(self):
        with DeepPlanStateIsolation():
            deepplan.ensure_state()
            first = deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "normalized preview first",
                    "success_metric": "Reach 2 pilots",
                    "deadline": "2026-04-03",
                },
            )
            deepplan_agent.execute_tool(
                "update_plan",
                {
                    "goal": "normalized preview second",
                    "expected_fingerprint": first["fingerprint"],
                },
            )
            result = deepplan_agent.execute_tool("preview_restore", {"previous": True})

        self.assertTrue(result["ok"])
        self.assertEqual(result["tool_name"], "preview_restore")
        self.assertEqual(result["result_type"], "restore_preview")


if __name__ == "__main__":
    unittest.main()
