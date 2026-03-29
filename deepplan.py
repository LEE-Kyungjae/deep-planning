#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from deepplan_store import FilePlanStore, PlanConflictError


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / ".deeplan"
PLAN_PATH = STATE_DIR / "plan.json"
DECISIONS_PATH = STATE_DIR / "decisions.jsonl"
RISKS_PATH = STATE_DIR / "risks.jsonl"
EVENTS_PATH = STATE_DIR / "events.jsonl"
REVISIONS_PATH = STATE_DIR / "revisions.jsonl"
EVENT_RETENTION_LIMIT = 1000
REVISION_RETENTION_LIMIT = 100
STATE_LOCK = None


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_state() -> None:
    _sync_store_paths()
    STORE.ensure_state()


def default_plan() -> Dict:
    return {
        "version": "0.5.0",
        "updated_at": now_iso(),
        "goal": "",
        "success_metric": "",
        "deadline": "",
        "planning_horizon": "",
        "review_cadence": "",
        "phase_plan": [],
        "constraints": [],
        "assumptions": [],
        "options": [],
        "selected_option": "",
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
        "evidence": [],
        "hypothesis_log": [],
        "reference_discoveries": [],
    }


def migrate_plan(plan: Dict) -> Dict:
    if "tasks" in plan and ("plan_tasks" not in plan and "execution_tasks" not in plan):
        tasks = plan.get("tasks", [])
        split = len(tasks) // 2
        plan["plan_tasks"] = tasks[:split]
        plan["execution_tasks"] = tasks[split:]
    plan.pop("tasks", None)

    for key, default in [
        ("version", "0.5.0"),
        ("updated_at", now_iso()),
        ("goal", ""),
        ("success_metric", ""),
        ("deadline", ""),
        ("planning_horizon", ""),
        ("review_cadence", ""),
        ("phase_plan", []),
        ("constraints", []),
        ("assumptions", []),
        ("options", []),
        ("selected_option", ""),
        ("plan_tasks", []),
        ("execution_tasks", []),
        ("dependencies", []),
        ("experiments", []),
        ("risks", []),
        ("references", []),
        ("insights", []),
        ("direction_insights", []),
        ("market_insights", []),
        ("timing_insights", []),
        ("differentiation_insights", []),
        ("monetization_insights", []),
        ("constraint_insights", []),
        ("risk_signal_insights", []),
        ("evolution_insights", []),
        ("definition_of_done", []),
        ("evidence", []),
        ("hypothesis_log", []),
        ("reference_discoveries", []),
    ]:
        plan.setdefault(key, default)

    plan["version"] = "0.5.0"
    return plan


def _load_plan_unlocked() -> Dict:
    _sync_store_paths()
    return STORE.load_plan_unlocked()


def load_plan() -> Dict:
    _sync_store_paths()
    return STORE.load_plan()


def _save_plan_unlocked(plan: Dict) -> None:
    _sync_store_paths()
    STORE.save_plan_unlocked(plan)


def save_plan(plan: Dict) -> None:
    _sync_store_paths()
    STORE.save_plan(plan)


def validate_risk_item(item, index: int) -> List[str]:
    errors: List[str] = []
    prefix = f"risks[{index}]"
    if isinstance(item, str):
        if not item.strip():
            errors.append(f"{prefix} must not be empty")
        return errors
    if not isinstance(item, dict):
        return [f"{prefix} must be a string or object"]
    for key in ["risk", "signal", "mitigation"]:
        if not isinstance(item.get(key), str) or not item.get(key, "").strip():
            errors.append(f"{prefix}.{key} must be a non-empty string")
    return errors


def validate_evidence_item(item, index: int) -> List[str]:
    errors: List[str] = []
    prefix = f"evidence[{index}]"
    if isinstance(item, str):
        if not item.strip():
            errors.append(f"{prefix} must not be empty")
        return errors
    if not isinstance(item, dict):
        return [f"{prefix} must be a string or object"]
    for key in ["claim", "source", "date"]:
        if not isinstance(item.get(key), str) or not item.get(key, "").strip():
            errors.append(f"{prefix}.{key} must be a non-empty string")
    confidence = item.get("confidence")
    if not isinstance(confidence, int) or isinstance(confidence, bool):
        errors.append(f"{prefix}.confidence must be an integer")
    elif confidence < 0 or confidence > 100:
        errors.append(f"{prefix}.confidence must be between 0 and 100")
    axis = item.get("axis", "")
    if axis != "" and not isinstance(axis, str):
        errors.append(f"{prefix}.axis must be a string")
    return errors


def validate_hypothesis_item(item, index: int) -> List[str]:
    errors: List[str] = []
    prefix = f"hypothesis_log[{index}]"
    if not isinstance(item, dict):
        return [f"{prefix} must be an object"]
    for key in ["ts", "hypothesis", "status"]:
        if not isinstance(item.get(key), str) or not item.get(key, "").strip():
            errors.append(f"{prefix}.{key} must be a non-empty string")
    for key in ["metric", "target", "window", "outcome"]:
        value = item.get(key, "")
        if value != "" and not isinstance(value, str):
            errors.append(f"{prefix}.{key} must be a string")
    status = item.get("status", "")
    if isinstance(status, str) and status and status not in {"open", "validated", "invalidated", "pivoted"}:
        errors.append(f"{prefix}.status must be one of: open, validated, invalidated, pivoted")
    return errors


def validate_reference_discovery_item(item, index: int) -> List[str]:
    errors: List[str] = []
    prefix = f"reference_discoveries[{index}]"
    if not isinstance(item, dict):
        return [f"{prefix} must be an object"]
    for key in ["ts", "question", "search_mode"]:
        if not isinstance(item.get(key), str) or not item.get(key, "").strip():
            errors.append(f"{prefix}.{key} must be a non-empty string")
    for key in ["trigger_signals", "selection_criteria", "candidate_queries", "shortlisted_references", "rejected_references"]:
        value = item.get(key)
        if not isinstance(value, list):
            errors.append(f"{prefix}.{key} must be an array")
            continue
        if not all(isinstance(entry, str) and entry.strip() for entry in value):
            errors.append(f"{prefix}.{key} must contain only non-empty strings")
    for key in ["context", "decision", "notes"]:
        value = item.get(key, "")
        if value != "" and not isinstance(value, str):
            errors.append(f"{prefix}.{key} must be a string")
    return errors


def validate_plan_shape(plan: Dict) -> Dict:
    expected = default_plan()
    errors: List[str] = []

    if not isinstance(plan, dict):
        return {"valid": False, "errors": ["plan must be an object"]}

    for key, template in expected.items():
        if key not in plan:
            errors.append(f"missing required field: {key}")
            continue
        value = plan[key]
        if isinstance(template, str):
            if not isinstance(value, str):
                errors.append(f"{key} must be a string")
        elif isinstance(template, list):
            if not isinstance(value, list):
                errors.append(f"{key} must be an array")

    if isinstance(plan.get("risks"), list):
        for index, item in enumerate(plan["risks"]):
            errors.extend(validate_risk_item(item, index))
    if isinstance(plan.get("evidence"), list):
        for index, item in enumerate(plan["evidence"]):
            errors.extend(validate_evidence_item(item, index))
    if isinstance(plan.get("hypothesis_log"), list):
        for index, item in enumerate(plan["hypothesis_log"]):
            errors.extend(validate_hypothesis_item(item, index))
    if isinstance(plan.get("reference_discoveries"), list):
        for index, item in enumerate(plan["reference_discoveries"]):
            errors.extend(validate_reference_discovery_item(item, index))

    return {"valid": len(errors) == 0, "errors": errors}


def build_plan_schema() -> Dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://deepplan.local/schemas/plan.schema.json",
        "title": "DeepPlan",
        "type": "object",
        "required": list(default_plan().keys()),
        "properties": {
            "version": {"type": "string"},
            "updated_at": {"type": "string"},
            "goal": {"type": "string"},
            "success_metric": {"type": "string"},
            "deadline": {"type": "string"},
            "planning_horizon": {"type": "string"},
            "review_cadence": {"type": "string"},
            "phase_plan": {"type": "array", "items": {"type": "string"}},
            "constraints": {"type": "array", "items": {"type": "string"}},
            "assumptions": {"type": "array", "items": {"type": "string"}},
            "options": {"type": "array", "items": {"type": "string"}},
            "selected_option": {"type": "string"},
            "plan_tasks": {"type": "array", "items": {"type": "string"}},
            "execution_tasks": {"type": "array", "items": {"type": "string"}},
            "dependencies": {"type": "array", "items": {"type": "string"}},
            "experiments": {"type": "array", "items": {"type": "string"}},
            "risks": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "required": ["risk", "signal", "mitigation"],
                            "properties": {
                                "risk": {"type": "string"},
                                "signal": {"type": "string"},
                                "mitigation": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    ]
                },
            },
            "references": {"type": "array", "items": {"type": "string"}},
            "insights": {"type": "array", "items": {"type": "string"}},
            "direction_insights": {"type": "array", "items": {"type": "string"}},
            "market_insights": {"type": "array", "items": {"type": "string"}},
            "timing_insights": {"type": "array", "items": {"type": "string"}},
            "differentiation_insights": {"type": "array", "items": {"type": "string"}},
            "monetization_insights": {"type": "array", "items": {"type": "string"}},
            "constraint_insights": {"type": "array", "items": {"type": "string"}},
            "risk_signal_insights": {"type": "array", "items": {"type": "string"}},
            "evolution_insights": {"type": "array", "items": {"type": "string"}},
            "definition_of_done": {"type": "array", "items": {"type": "string"}},
            "evidence": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "required": ["claim", "source", "confidence", "date"],
                            "properties": {
                                "claim": {"type": "string"},
                                "source": {"type": "string"},
                                "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                                "axis": {"type": "string"},
                                "date": {"type": "string"},
                            },
                            "additionalProperties": True,
                        },
                    ]
                },
            },
            "hypothesis_log": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["ts", "hypothesis", "status"],
                    "properties": {
                        "ts": {"type": "string"},
                        "hypothesis": {"type": "string"},
                        "metric": {"type": "string"},
                        "target": {"type": "string"},
                        "window": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["open", "validated", "invalidated", "pivoted"],
                        },
                        "outcome": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "reference_discoveries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["ts", "question", "search_mode", "trigger_signals", "selection_criteria", "candidate_queries", "shortlisted_references", "rejected_references"],
                    "properties": {
                        "ts": {"type": "string"},
                        "question": {"type": "string"},
                        "context": {"type": "string"},
                        "search_mode": {"type": "string"},
                        "trigger_signals": {"type": "array", "items": {"type": "string"}},
                        "selection_criteria": {"type": "array", "items": {"type": "string"}},
                        "candidate_queries": {"type": "array", "items": {"type": "string"}},
                        "shortlisted_references": {"type": "array", "items": {"type": "string"}},
                        "rejected_references": {"type": "array", "items": {"type": "string"}},
                        "decision": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
        },
        "additionalProperties": True,
    }


def schema_path() -> Path:
    return ROOT / "schemas" / "plan.schema.json"


def load_plan_schema() -> Dict:
    return json.loads(schema_path().read_text(encoding="utf-8"))


def schema_drift_report() -> Dict:
    runtime_schema = build_plan_schema()
    file_schema = load_plan_schema()
    matches = runtime_schema == file_schema
    return {
        "matches": matches,
        "schema_path": str(schema_path()),
        "runtime_required_count": len(runtime_schema.get("required", [])),
        "file_required_count": len(file_schema.get("required", [])),
        "runtime_property_count": len(runtime_schema.get("properties", {})),
        "file_property_count": len(file_schema.get("properties", {})),
    }


def ensure_non_empty_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def ensure_confidence(value: int, field_name: str = "confidence") -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field_name} must be an integer")
    if value < 0 or value > 100:
        raise ValueError(f"{field_name} must be between 0 and 100")
    return value


def ensure_valid_plan(plan: Dict) -> Dict:
    report = validate_plan_shape(plan)
    if not report["valid"]:
        raise ValueError("plan validation failed: " + "; ".join(report["errors"]))
    return plan


def save_validated_plan(plan: Dict) -> None:
    ensure_valid_plan(plan)
    save_plan(plan)


def _save_validated_plan_unlocked(plan: Dict) -> None:
    ensure_valid_plan(plan)
    _save_plan_unlocked(plan)


def plan_fingerprint(plan: Dict) -> str:
    material = dict(plan)
    material.pop("updated_at", None)
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalize_fingerprint(value: Optional[str]) -> str:
    text = str(value or "").strip()
    if text.startswith("W/"):
        text = text[2:].strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        text = text[1:-1]
    return text.strip()


def revision_metadata(plan: Dict) -> Dict:
    qa = qa_report(plan)
    summary = plan_summary(plan)
    return {
        "goal": str(plan.get("goal", "")).strip(),
        "updated_at": str(plan.get("updated_at", "")).strip(),
        "qa_result": qa["result"],
        "qa_score": qa["score"],
        "qa_threshold": qa["threshold"],
        "reference_count": summary["reference_count"],
        "evidence_count": summary["evidence_count"],
        "risk_count": summary["risk_count"],
        "hypothesis_count": summary["hypothesis_count"],
        "plan_task_count": summary["plan_task_count"],
        "execution_task_count": summary["execution_task_count"],
    }


STORE = FilePlanStore(
    state_dir=STATE_DIR,
    plan_path=PLAN_PATH,
    decisions_path=DECISIONS_PATH,
    risks_path=RISKS_PATH,
    events_path=EVENTS_PATH,
    revisions_path=REVISIONS_PATH,
    default_plan_factory=default_plan,
    migrate_plan=migrate_plan,
    now_iso=now_iso,
    plan_fingerprint=plan_fingerprint,
    normalize_fingerprint=normalize_fingerprint,
    ensure_valid_plan=ensure_valid_plan,
    qa_autoreplan_result=lambda *args, **kwargs: qa_autoreplan_result(*args, **kwargs),
    revision_metadata_builder=revision_metadata,
    retention_limits={
        "events": EVENT_RETENTION_LIMIT,
        "revisions": REVISION_RETENTION_LIMIT,
    },
)
STATE_LOCK = STORE.lock


def _sync_store_paths() -> None:
    STORE.state_dir = STATE_DIR
    STORE.plan_path = PLAN_PATH
    STORE.decisions_path = DECISIONS_PATH
    STORE.risks_path = RISKS_PATH
    STORE.events_path = EVENTS_PATH
    STORE.revisions_path = REVISIONS_PATH
    STORE.retention_limits = {
        "events": EVENT_RETENTION_LIMIT,
        "revisions": REVISION_RETENTION_LIMIT,
    }


def plan_response(plan: Dict) -> Dict:
    return {
        "plan": plan,
        "summary": plan_summary(plan),
        "validation": validate_plan_shape(plan),
        "fingerprint": plan_fingerprint(plan),
    }


def cycle_snapshot(history_limit: int = 10) -> Dict:
    plan = load_plan()
    plan_result = plan_response(plan)
    return {
        "ok": True,
        "result_type": "cycle",
        "plan": plan_result["plan"],
        "summary": plan_result["summary"],
        "validation": plan_result["validation"],
        "fingerprint": plan_result["fingerprint"],
        "qa": qa_report(plan),
        "health": storage_health_report(),
        "history": list_revisions(limit=history_limit),
        "history_limit": history_limit,
    }


def apply_replan_payload(plan: Dict, payload: Dict) -> Dict:
    evidence_text = str(payload.get("evidence", "")).strip()
    if evidence_text:
        add_evidence(
            plan,
            ensure_non_empty_text(evidence_text, "evidence"),
            str(payload.get("evidence_source", "replan")).strip() or "replan",
            ensure_confidence(int(payload.get("evidence_confidence", 60)), "evidence_confidence"),
            str(payload.get("evidence_axis", "")).strip(),
            str(payload.get("evidence_date", "")).strip(),
        )

    for field, key in [
        ("plan_task", "plan_tasks"),
        ("execution_task", "execution_tasks"),
        ("phase", "phase_plan"),
        ("reference", "references"),
        ("insight", "insights"),
        ("direction_insight", "direction_insights"),
        ("market_insight", "market_insights"),
        ("timing_insight", "timing_insights"),
        ("differentiation_insight", "differentiation_insights"),
        ("monetization_insight", "monetization_insights"),
        ("constraint_insight", "constraint_insights"),
        ("risk_signal_insight", "risk_signal_insights"),
        ("evolution_insight", "evolution_insights"),
    ]:
        value = str(payload.get(field, "")).strip()
        if value:
            plan.setdefault(key, []).append(value)

    return plan


def _append_jsonl_unlocked(path: Path, payload: Dict) -> None:
    _sync_store_paths()
    STORE.append_jsonl_unlocked(path, payload)


def append_jsonl(path: Path, payload: Dict) -> None:
    _sync_store_paths()
    STORE.append_jsonl(path, payload)


def get_idempotency_record(scope: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
    wanted_scope = str(scope).strip()
    wanted_key = str(idempotency_key).strip()
    if not wanted_scope or not wanted_key:
        return None
    for item in reversed(read_jsonl(EVENTS_PATH)):
        if not isinstance(item, dict):
            continue
        if str(item.get("type", "")).strip() != "idempotency_record":
            continue
        if str(item.get("scope", "")).strip() != wanted_scope:
            continue
        if str(item.get("idempotency_key", "")).strip() != wanted_key:
            continue
        return item
    return None


def with_idempotency_metadata(result: Dict[str, Any], idempotency_key: str, *, replayed: bool) -> Dict[str, Any]:
    enriched = json.loads(json.dumps(result))
    enriched["idempotency_key"] = str(idempotency_key).strip()
    enriched["idempotency_replayed"] = replayed
    return enriched


def record_idempotency_result(scope: str, idempotency_key: str, result: Dict[str, Any]) -> Dict[str, Any]:
    normalized_scope = str(scope).strip()
    normalized_key = str(idempotency_key).strip()
    if not normalized_scope or not normalized_key:
        return result
    recorded = with_idempotency_metadata(result, normalized_key, replayed=False)
    append_jsonl(
        EVENTS_PATH,
        {
            "ts": now_iso(),
            "type": "idempotency_record",
            "scope": normalized_scope,
            "idempotency_key": normalized_key,
            "fingerprint": str(recorded.get("fingerprint", "")).strip(),
            "result": recorded,
        },
    )
    return recorded


def replay_idempotency_result(scope: str, idempotency_key: str) -> Optional[Dict[str, Any]]:
    record = get_idempotency_record(scope, idempotency_key)
    if not record:
        return None
    result = record.get("result")
    if not isinstance(result, dict):
        return None
    return with_idempotency_metadata(result, idempotency_key, replayed=True)


def make_revision_entry(plan: Dict, source: str, reason: str = "", previous_fingerprint: str = "") -> Dict:
    _sync_store_paths()
    return STORE.make_revision_entry(plan, source, reason=reason, previous_fingerprint=previous_fingerprint)


def _append_revision_unlocked(plan: Dict, source: str, reason: str = "", previous_fingerprint: str = "") -> Dict:
    _sync_store_paths()
    return STORE.append_revision_unlocked(plan, source, reason=reason, previous_fingerprint=previous_fingerprint)


def append_revision(plan: Dict, source: str, reason: str = "", previous_fingerprint: str = "") -> Dict:
    _sync_store_paths()
    return STORE.append_revision(plan, source, reason=reason, previous_fingerprint=previous_fingerprint)


def mutate_plan_state(
    mutate_fn,
    event_payloads: Optional[List[Dict]] = None,
    include_autoreplan: bool = False,
    expected_fingerprint: Optional[str] = None,
    revision_source: str = "mutate_plan_state",
    revision_reason: str = "",
):
    _sync_store_paths()
    return STORE.mutate_plan_state(
        mutate_fn,
        event_payloads=event_payloads,
        include_autoreplan=include_autoreplan,
        expected_fingerprint=expected_fingerprint,
        revision_source=revision_source,
        revision_reason=revision_reason,
    )


def read_jsonl(path: Path) -> List[Dict]:
    _sync_store_paths()
    return STORE.read_jsonl(path)


def jsonl_health(path: Path) -> Dict:
    _sync_store_paths()
    return STORE.jsonl_health(path)


def maintenance_report(apply: bool = False) -> Dict:
    _sync_store_paths()
    return STORE.maintenance_report(apply=apply)


def storage_health_report() -> Dict:
    ensure_state()
    issues: List[str] = []
    plan_exists = PLAN_PATH.exists()
    plan_parseable = False
    plan_valid = False
    plan_error = ""
    current_fingerprint = ""
    revision_count = 0
    latest_revision_id = ""
    latest_revision_fingerprint = ""
    latest_recoverable_revision_id = ""
    latest_recoverable_revision_fingerprint = ""
    current_matches_latest_revision = False
    recovery_candidate_available = False
    try:
        plan = load_plan()
        plan_parseable = True
        validation = validate_plan_shape(plan)
        plan_valid = validation["valid"]
        if not validation["valid"]:
            issues.extend(validation["errors"])
        current_fingerprint = plan_fingerprint(plan)
    except Exception as exc:
        plan_error = str(exc)
        issues.append(f"plan_load_failed:{exc}")

    event_log = jsonl_health(EVENTS_PATH)
    revision_log = jsonl_health(REVISIONS_PATH)
    decision_log = jsonl_health(DECISIONS_PATH)
    risk_log = jsonl_health(RISKS_PATH)
    revision_count = revision_log["valid_objects"]
    for label, report in [
        ("events", event_log),
        ("revisions", revision_log),
        ("decisions", decision_log),
        ("risks", risk_log),
    ]:
        if report["invalid_lines"]:
            issues.append(f"{label}_invalid_lines:{report['invalid_lines']}")
        if report.get("over_limit_by", 0):
            issues.append(f"{label}_over_retention:{report['over_limit_by']}")

    revisions = list_revisions(limit=1)
    if revisions:
        latest_revision = revisions[0]
        latest_revision_id = str(latest_revision.get("revision_id", "")).strip()
        latest_revision_fingerprint = str(latest_revision.get("fingerprint", "")).strip()
        latest_recoverable_revision_id = latest_revision_id
        latest_recoverable_revision_fingerprint = latest_revision_fingerprint
        recovery_candidate_available = bool(latest_recoverable_revision_id)
        current_matches_latest_revision = bool(current_fingerprint and latest_revision_fingerprint and current_fingerprint == latest_revision_fingerprint)
        if current_fingerprint and latest_revision_fingerprint and current_fingerprint != latest_revision_fingerprint:
            issues.append("current_plan_differs_from_latest_revision")
    elif not plan_parseable:
        issues.append("no_recoverable_revision_available")

    writable = True
    writable_error = ""
    try:
        probe = STATE_DIR / ".healthcheck.tmp"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except Exception as exc:
        writable = False
        writable_error = str(exc)
        issues.append(f"write_failed:{exc}")

    status = "ok"
    if issues:
        status = "degraded"
    if not plan_parseable or not writable:
        status = "error"

    return {
        "status": status,
        "state_dir": str(STATE_DIR),
        "plan_exists": plan_exists,
        "plan_parseable": plan_parseable,
        "plan_valid": plan_valid,
        "plan_error": plan_error,
        "current_fingerprint": current_fingerprint,
        "revision_count": revision_count,
        "latest_revision_id": latest_revision_id,
        "latest_revision_fingerprint": latest_revision_fingerprint,
        "latest_recoverable_revision_id": latest_recoverable_revision_id,
        "latest_recoverable_revision_fingerprint": latest_recoverable_revision_fingerprint,
        "current_matches_latest_revision": current_matches_latest_revision,
        "recovery_candidate_available": recovery_candidate_available,
        "writable": writable,
        "writable_error": writable_error,
        "logs": {
            "events": event_log,
            "revisions": revision_log,
            "decisions": decision_log,
            "risks": risk_log,
        },
        "retention": maintenance_report(apply=False),
        "issues": issues,
    }


def list_revisions(limit: int = 10) -> List[Dict]:
    items = [item for item in read_jsonl(REVISIONS_PATH) if isinstance(item, dict)]
    if limit <= 0:
        return list(reversed(items))
    return list(reversed(items[-limit:]))


def get_revision(revision_id: str) -> Dict:
    wanted = revision_id.strip()
    if not wanted:
        raise ValueError("revision_id is required")
    for item in read_jsonl(REVISIONS_PATH):
        if item.get("revision_id") == wanted:
            return item
    raise ValueError(f"unknown revision_id: {wanted}")


def latest_revision() -> Optional[Dict]:
    revisions = list_revisions(limit=1)
    return revisions[0] if revisions else None


def get_revision_by_fingerprint(fingerprint: str) -> Optional[Dict]:
    wanted = fingerprint.strip()
    if not wanted:
        return None
    for item in read_jsonl(REVISIONS_PATH):
        if str(item.get("fingerprint", "")).strip() == wanted:
            return item
    return None


def resolve_revision_reference(revision_id: str = "", previous: bool = False) -> Dict:
    if previous:
        latest = latest_revision()
        if not latest:
            raise ValueError("no revisions recorded")
        previous_fingerprint = str(latest.get("previous_fingerprint", "")).strip()
        if previous_fingerprint:
            previous_revision = get_revision_by_fingerprint(previous_fingerprint)
            if previous_revision:
                return previous_revision
        revisions = list_revisions(limit=2)
        if len(revisions) >= 2:
            return revisions[1]
        raise ValueError("no previous revision available")
    return get_revision(revision_id)


def diff_plan_fields(current_plan: Dict, target_plan: Dict) -> List[str]:
    keys = sorted(set(current_plan) | set(target_plan))
    changed: List[str] = []
    for key in keys:
        if current_plan.get(key) != target_plan.get(key):
            changed.append(key)
    return changed


def summarize_diff_value(value):
    if isinstance(value, list):
        return {"type": "array", "count": len(value)}
    if isinstance(value, dict):
        return {"type": "object", "keys": sorted(value.keys())}
    text = str(value)
    return {"type": "scalar", "value": text[:120]}


def structured_plan_diff(current_plan: Dict, target_plan: Dict) -> List[Dict]:
    diff: List[Dict] = []
    for field in diff_plan_fields(current_plan, target_plan):
        diff.append(
            {
                "field": field,
                "before": summarize_diff_value(current_plan.get(field)),
                "after": summarize_diff_value(target_plan.get(field)),
            }
        )
    return diff


def restore_preview(revision_id: str = "", previous: bool = False) -> Dict:
    current_plan = load_plan()
    revision = resolve_revision_reference(revision_id=revision_id, previous=previous)
    target_plan = json.loads(json.dumps(revision["plan"]))
    current_fingerprint = plan_fingerprint(current_plan)
    target_fingerprint = plan_fingerprint(target_plan)
    changed_fields = diff_plan_fields(current_plan, target_plan)
    structured_diff = structured_plan_diff(current_plan, target_plan)
    return {
        "revision_id": revision["revision_id"],
        "selected_via": "previous" if previous else "revision_id",
        "source": revision.get("source", ""),
        "reason": revision.get("reason", ""),
        "metadata": revision.get("metadata", {}),
        "current_fingerprint": current_fingerprint,
        "target_fingerprint": target_fingerprint,
        "changed_fields": changed_fields,
        "change_count": len(changed_fields),
        "diff": structured_diff,
        "no_op": current_fingerprint == target_fingerprint,
        "current_summary": plan_summary(current_plan),
        "target_summary": plan_summary(target_plan),
    }


def last_auto_replan_event(plan: Optional[Dict] = None) -> Optional[Dict]:
    current_updated_at = str(plan.get("updated_at", "")).strip() if isinstance(plan, dict) else ""
    current_fingerprint = plan_fingerprint(plan) if isinstance(plan, dict) else ""
    for event in reversed(read_jsonl(EVENTS_PATH)):
        if event.get("type") != "auto_replan":
            continue
        final_fingerprint = str(event.get("final_fingerprint", "")).strip()
        initial_fingerprint = str(event.get("initial_fingerprint", "")).strip()
        if current_fingerprint:
            if final_fingerprint and final_fingerprint == current_fingerprint:
                return event
            if not final_fingerprint and initial_fingerprint and initial_fingerprint == current_fingerprint:
                return event
            continue
        if not current_updated_at:
            return event
        final_updated_at = str(event.get("final_updated_at", "")).strip()
        initial_updated_at = str(event.get("initial_updated_at", "")).strip()
        if final_updated_at and final_updated_at == current_updated_at:
            return event
        if not final_updated_at and initial_updated_at and initial_updated_at == current_updated_at:
            return event
    return None


def non_empty(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() != ""
    if isinstance(v, list):
        return len(v) > 0
    if isinstance(v, dict):
        return len(v) > 0
    return True


def parse_csv(v: str) -> List[str]:
    return [x.strip() for x in v.split(",") if x.strip()]


def normalize_axis_label(v: str) -> str:
    aliases = {
        "direction": "direction_insights",
        "market": "market_insights",
        "timing": "timing_insights",
        "differentiation": "differentiation_insights",
        "monetization": "monetization_insights",
        "constraints": "constraint_insights",
        "constraint": "constraint_insights",
        "risk-signals": "risk_signal_insights",
        "risk_signal": "risk_signal_insights",
        "risk": "risk_signal_insights",
        "evolution": "evolution_insights",
    }
    value = v.strip().lower()
    return aliases.get(value, value)


def evidence_object(claim: str, source: str, confidence: int, axis: str = "", evidence_date: str = "") -> Dict:
    return {
        "claim": claim.strip(),
        "source": source.strip() if source else "manual",
        "confidence": max(0, min(100, confidence)),
        "axis": normalize_axis_label(axis) if axis else "",
        "date": evidence_date.strip() if evidence_date else date.today().isoformat(),
    }


def legacy_evidence_object(entry: str) -> Dict:
    text = entry.strip()
    if not text:
        return {}
    review_match = re.match(r"^\[review:(?P<period>[^\]]+)\]\s+score=(?P<score>\d+)/(?P<total>\d+);", text)
    if review_match:
        period = review_match.group("period").strip()
        return evidence_object(
            f"Review cycle recorded for {period}: {text}",
            "review-cycle",
            70,
            "evolution_insights",
        )
    return {}


def evidence_objects(plan: Dict) -> List[Dict]:
    items = []
    for x in plan.get("evidence", []):
        if isinstance(x, dict):
            items.append(x)
        elif isinstance(x, str):
            legacy = legacy_evidence_object(x)
            if legacy:
                items.append(legacy)
    return items


def add_evidence(plan: Dict, claim: str, source: str, confidence: int = 60, axis: str = "", evidence_date: str = "") -> None:
    plan.setdefault("evidence", []).append(evidence_object(claim, source, confidence, axis, evidence_date))


def infer_reference_trigger_signals(question: str, context: str = "") -> List[str]:
    text = f"{question} {context}".lower()
    signal_map = [
        ("github", "github_examples"),
        ("repo", "repository_examples"),
        ("prompt", "prompt_patterns"),
        ("agent", "agent_patterns"),
        ("design", "design_patterns"),
        ("ui", "ui_patterns"),
        ("ux", "ux_patterns"),
        ("reference", "reference_lookup"),
        ("example", "example_lookup"),
        ("case", "case_study_lookup"),
        ("similar", "similar_implementation_lookup"),
        ("benchmark", "benchmark_lookup"),
        ("docs", "documentation_lookup"),
        ("official", "official_documentation_lookup"),
        ("paper", "research_lookup"),
    ]
    matches = [label for keyword, label in signal_map if keyword in text]
    return matches or ["generic_reference_lookup"]


def infer_reference_search_mode(question: str, context: str = "") -> str:
    signals = infer_reference_trigger_signals(question, context)
    if any(signal in signals for signal in ["github_examples", "repository_examples", "prompt_patterns", "agent_patterns"]):
        return "github-pattern-scan"
    if any(signal in signals for signal in ["official_documentation_lookup", "documentation_lookup"]):
        return "docs-scan"
    if any(signal in signals for signal in ["research_lookup", "benchmark_lookup"]):
        return "research-scan"
    if any(signal in signals for signal in ["design_patterns", "ui_patterns", "ux_patterns"]):
        return "design-pattern-scan"
    return "general-reference-scan"


def compact_topic_slug(question: str, fallback: str = "topic") -> str:
    tokens = re.findall(r"[a-z0-9]+", question.lower())
    selected = tokens[:6]
    return "-".join(selected) if selected else fallback


def build_reference_discovery_pack(question: str, context: str = "", references: Optional[List[str]] = None, rejected: Optional[List[str]] = None) -> Dict[str, Any]:
    clean_question = ensure_non_empty_text(question, "question")
    clean_context = context.strip()
    shortlisted = [item.strip() for item in references or [] if isinstance(item, str) and item.strip()]
    rejected_items = [item.strip() for item in rejected or [] if isinstance(item, str) and item.strip()]
    search_mode = infer_reference_search_mode(clean_question, clean_context)
    trigger_signals = infer_reference_trigger_signals(clean_question, clean_context)
    topic_slug = compact_topic_slug(clean_question)

    selection_criteria = [
        "Prefer references that directly address the active planning question rather than generic inspiration.",
        "Prefer references with reusable decision patterns, not just polished outputs.",
        "Reject references that optimize runtime/framework novelty instead of the target planning problem.",
    ]
    if search_mode == "github-pattern-scan":
        selection_criteria.append("Prioritize repositories with explicit prompt structure, role boundaries, or workflow examples.")
    elif search_mode == "design-pattern-scan":
        selection_criteria.append("Prioritize product UX hierarchy and information architecture guidance over visual polish alone.")
    elif search_mode == "docs-scan":
        selection_criteria.append("Prioritize primary-source docs over summaries or tertiary commentary.")
    elif search_mode == "research-scan":
        selection_criteria.append("Prioritize comparable evaluation setups and measurable outcomes.")

    candidate_queries = [
        clean_question,
        f"{topic_slug} best reference examples",
        f"{topic_slug} {search_mode}",
    ]
    if "github-pattern-scan" == search_mode:
        candidate_queries.append(f"site:github.com {clean_question}")
    if "design-pattern-scan" == search_mode:
        candidate_queries.append(f"{clean_question} product ux hierarchy")

    plan_updates = {
        "plan_tasks": [
            f"Run reference discovery for: {clean_question}",
            "Score shortlisted references against explicit selection criteria before adopting any pattern.",
        ],
        "execution_tasks": [
            "Apply one selected reference pattern and measure whether it improves the target planning decision.",
        ],
        "evolution_insights": [
            "When the conversation shifts to examples or references, trigger discovery and log selection criteria before committing to a direction.",
        ],
    }

    decision = (
        f"Use {search_mode} before committing on '{clean_question}'."
        if not shortlisted
        else f"Review {len(shortlisted)} shortlisted reference(s) before adopting any pattern for '{clean_question}'."
    )

    return {
        "question": clean_question,
        "context": clean_context,
        "search_mode": search_mode,
        "trigger_signals": trigger_signals,
        "selection_criteria": selection_criteria,
        "candidate_queries": candidate_queries,
        "shortlisted_references": shortlisted,
        "rejected_references": rejected_items,
        "decision": decision,
        "notes": "",
        "plan_updates": plan_updates,
    }


def reference_discovery_record(pack: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ts": now_iso(),
        "question": str(pack.get("question", "")).strip(),
        "context": str(pack.get("context", "")).strip(),
        "search_mode": str(pack.get("search_mode", "")).strip(),
        "trigger_signals": [item.strip() for item in pack.get("trigger_signals", []) if isinstance(item, str) and item.strip()],
        "selection_criteria": [item.strip() for item in pack.get("selection_criteria", []) if isinstance(item, str) and item.strip()],
        "candidate_queries": [item.strip() for item in pack.get("candidate_queries", []) if isinstance(item, str) and item.strip()],
        "shortlisted_references": [item.strip() for item in pack.get("shortlisted_references", []) if isinstance(item, str) and item.strip()],
        "rejected_references": [item.strip() for item in pack.get("rejected_references", []) if isinstance(item, str) and item.strip()],
        "decision": str(pack.get("decision", "")).strip(),
        "notes": str(pack.get("notes", "")).strip(),
    }


def default_deadline(days: int = 14) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def generate_ideas(args: argparse.Namespace) -> List[Dict]:
    interests = parse_csv(args.interests) if args.interests else []
    skills = parse_csv(args.skills) if args.skills else []
    profile = args.profile.strip() if args.profile else "solo builder"
    horizon = args.deadline.strip() if args.deadline else default_deadline(14)
    time_limit = args.time_per_day.strip() if args.time_per_day else "1h/day"
    budget = args.budget.strip() if args.budget else "$0"
    focus_terms = interests if interests else ["your workflow", "your learning", "your output quality"]

    templates = [
        {
            "name": "Workflow Automation",
            "goal": "Automate one repetitive {focus} task end-to-end",
            "metric": "Reduce manual time on {focus} by 30% by {deadline}",
            "plan_tasks": [
                "Map the current manual workflow and baseline time.",
                "Select one high-friction step to automate first.",
            ],
            "execution_tasks": [
                "Build the smallest working automation script/tool.",
                "Run for one week and compare baseline vs after metrics.",
            ],
        },
        {
            "name": "Portfolio Artifact",
            "goal": "Ship a public mini-project around {focus}",
            "metric": "Publish a working demo and one write-up by {deadline}",
            "plan_tasks": [
                "Define MVP scope and success criteria for the demo.",
                "Collect 3 references from similar projects.",
            ],
            "execution_tasks": [
                "Implement MVP with one differentiating feature.",
                "Publish demo, doc, and changelog.",
            ],
        },
        {
            "name": "Learning Sprint",
            "goal": "Complete a focused sprint to improve {focus} capability",
            "metric": "Deliver 3 practical outputs proving {focus} improvement by {deadline}",
            "plan_tasks": [
                "Choose a narrow syllabus and output format.",
                "Define weekly checkpoints with explicit evidence.",
            ],
            "execution_tasks": [
                "Produce output #1 and gather feedback.",
                "Produce output #2/#3 and review gaps.",
            ],
        },
        {
            "name": "Insight Pipeline",
            "goal": "Build a repeatable system to collect and summarize {focus} insights",
            "metric": "Generate 10 curated insights and 3 actions by {deadline}",
            "plan_tasks": [
                "Define sources and capture format.",
                "Set quality bar for actionable insights.",
            ],
            "execution_tasks": [
                "Run weekly collection and summarization loop.",
                "Apply top 3 insights and measure outcomes.",
            ],
        },
    ]

    ideas: List[Dict] = []
    for i in range(max(1, min(args.count, 10))):
        t = templates[i % len(templates)]
        focus = focus_terms[i % len(focus_terms)]
        goal = t["goal"].format(focus=focus, deadline=horizon)
        metric = t["metric"].format(focus=focus, deadline=horizon)
        assumptions = [
            f"{profile} can sustain {time_limit} for this project.",
            f"Budget stays within {budget} without external paid tooling.",
        ]
        if skills:
            assumptions.append(f"Existing skills ({', '.join(skills[:3])}) are enough for MVP delivery.")
        constraints = [f"time: {time_limit}", f"budget: {budget}", "scope: single focused outcome"]
        ideas.append(
            {
                "title": t["name"],
                "goal": goal,
                "success_metric": metric,
                "deadline": horizon,
                "constraints": constraints,
                "assumptions": assumptions,
                "plan_tasks": t["plan_tasks"],
                "execution_tasks": t["execution_tasks"],
                "definition_of_done": [
                    "Primary success metric is measured with before/after evidence.",
                    "At least one artifact (code/doc/demo) is published.",
                ],
                "experiments": ["Run a 7-day pilot and log outcomes."],
            }
        )
    return ideas


def task_balance_ok(plan: Dict) -> bool:
    p = len(plan.get("plan_tasks", []))
    e = len(plan.get("execution_tasks", []))
    total = p + e
    if total < 4 or p == 0 or e == 0:
        return False
    ratio = p / total
    return 0.4 <= ratio <= 0.6


def insight_axes_covered(plan: Dict) -> bool:
    axes = [
        "direction_insights",
        "market_insights",
        "timing_insights",
        "differentiation_insights",
        "monetization_insights",
        "constraint_insights",
        "risk_signal_insights",
        "evolution_insights",
    ]
    return all(non_empty(plan.get(k)) for k in axes)


def axis_quality(plan: Dict, axis_key: str) -> float:
    insight_count = len(plan.get(axis_key, []))
    insight_component = min(insight_count, 3) / 3.0
    linked_evidence = any(
        isinstance(ev, dict) and normalize_axis_label(str(ev.get("axis", ""))) == axis_key
        for ev in evidence_objects(plan)
    )
    evidence_component = 1.0 if linked_evidence else 0.0
    return min(1.0, insight_component * 0.7 + evidence_component * 0.3)


def weighted_insight_quality(plan: Dict) -> float:
    axes = [
        "direction_insights",
        "market_insights",
        "timing_insights",
        "differentiation_insights",
        "monetization_insights",
        "constraint_insights",
        "risk_signal_insights",
        "evolution_insights",
    ]
    if not axes:
        return 0.0
    return sum(axis_quality(plan, k) for k in axes) / len(axes)


def evidence_quality_ok(plan: Dict) -> bool:
    ev = evidence_objects(plan)
    if len(ev) < 3:
        return False
    high_conf = sum(1 for x in ev if int(x.get("confidence", 0)) >= 60)
    sources = {str(x.get("source", "")).strip() for x in ev if str(x.get("source", "")).strip()}
    return high_conf >= 2 and len(sources) >= 2


def hypothesis_loop_ok(plan: Dict) -> bool:
    logs = plan.get("hypothesis_log", [])
    if not isinstance(logs, list) or len(logs) == 0:
        return False
    return all(isinstance(item, dict) and non_empty(item.get("hypothesis")) for item in logs)


def horizon_defined(plan: Dict) -> bool:
    return non_empty(plan.get("planning_horizon")) and non_empty(plan.get("review_cadence"))


def reference_discovery_logged(plan: Dict) -> bool:
    discoveries = plan.get("reference_discoveries", [])
    references = plan.get("references", [])
    if not isinstance(discoveries, list):
        return False
    if not isinstance(references, list) or len(references) == 0:
        return True
    return len(discoveries) > 0


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    weight: int
    critical: bool = False


def run_qa(plan: Dict) -> Tuple[int, List[CheckResult], bool]:
    checks: List[CheckResult] = []

    checks.append(CheckResult("goal_clarity", non_empty(plan.get("goal")), "Goal is present and outcome-oriented.", 10, True))
    checks.append(
        CheckResult(
            "measurability",
            non_empty(plan.get("success_metric")) and non_empty(plan.get("deadline")),
            "Success metric and deadline are both defined.",
            10,
            True,
        )
    )
    checks.append(CheckResult("constraints", non_empty(plan.get("constraints")), "Constraints are explicitly listed.", 8))
    checks.append(CheckResult("assumptions", non_empty(plan.get("assumptions")), "Core assumptions are extracted.", 8))
    checks.append(
        CheckResult(
            "options_comparison",
            len(plan.get("options", [])) >= 2 and non_empty(plan.get("selected_option")),
            "At least two options and one selected option exist.",
            8,
        )
    )
    checks.append(
        CheckResult(
            "references_coverage",
            len(plan.get("references", [])) >= 3,
            "Plan includes at least three references (docs, cases, benchmarks).",
            10,
        )
    )
    checks.append(
        CheckResult(
            "reference_discovery_loop",
            reference_discovery_logged(plan),
            "External references are paired with at least one logged discovery/selection pass.",
            5,
        )
    )
    checks.append(
        CheckResult(
            "insight_axes_coverage",
            insight_axes_covered(plan),
            "Eight long-horizon insight axes are all covered.",
            10,
        )
    )
    checks.append(
        CheckResult(
            "insight_quality_weighted",
            weighted_insight_quality(plan) >= 0.6,
            "Weighted insight quality (insight depth + axis-linked evidence) is at least 0.6.",
            12,
            True,
        )
    )
    checks.append(
        CheckResult(
            "evidence_quality",
            evidence_quality_ok(plan),
            "Evidence includes minimum quantity, confidence, and source diversity.",
            10,
        )
    )
    checks.append(
        CheckResult(
            "planning_horizon",
            horizon_defined(plan),
            "Planning horizon and review cadence are explicitly defined.",
            10,
            True,
        )
    )
    checks.append(CheckResult("phase_plan", non_empty(plan.get("phase_plan")), "Plan includes milestone phases for long-horizon co-work.", 8))
    checks.append(
        CheckResult(
            "verification_loop",
            non_empty(plan.get("experiments")),
            "Validation experiments exist for key assumptions.",
            8,
        )
    )
    checks.append(CheckResult("hypothesis_loop", hypothesis_loop_ok(plan), "Hypothesis log exists with testable hypotheses.", 8))
    checks.append(
        CheckResult(
            "risk_coverage",
            non_empty(plan.get("risks")),
            "Top risks include early signals and mitigations.",
            8,
        )
    )
    checks.append(
        CheckResult(
            "dependencies",
            non_empty(plan.get("dependencies")),
            "External dependencies/blockers are documented.",
            5,
        )
    )
    checks.append(
        CheckResult(
            "definition_of_done",
            non_empty(plan.get("definition_of_done")),
            "Definition of done exists.",
            5,
            True,
        )
    )

    score = 0
    critical_failure = False
    for c in checks:
        if c.passed:
            score += c.weight
        if c.critical and not c.passed:
            critical_failure = True
    return score, checks, critical_failure


def qa_report(plan: Dict) -> Dict:
    score, checks, critical_failure = run_qa(plan)
    total = qa_total_weight(checks)
    threshold = qa_pass_threshold(checks)
    result = "CRITICAL_FAILURE" if critical_failure else "PASS" if score >= threshold else "NEEDS_REPLAN"
    validation = validate_plan_shape(plan)
    return {
        "score": score,
        "total": total,
        "threshold": threshold,
        "critical_failure": critical_failure,
        "result": result,
        "validation": validation,
        "checks": [
            {
                "name": c.name,
                "passed": c.passed,
                "detail": c.detail,
                "weight": c.weight,
                "critical": c.critical,
            }
            for c in checks
        ],
    }


def qa_total_weight(checks: List[CheckResult]) -> int:
    return sum(c.weight for c in checks)


def qa_pass_threshold(checks: List[CheckResult]) -> int:
    total = qa_total_weight(checks)
    return int(total * 0.7 + 0.9999)


def print_qa(score: int, checks: List[CheckResult], critical_failure: bool) -> None:
    total = qa_total_weight(checks)
    threshold = qa_pass_threshold(checks)
    print(f"QA score: {score}/{total}")
    for c in checks:
        icon = "PASS" if c.passed else "FAIL"
        critical = " [CRITICAL]" if c.critical else ""
        print(f"- {icon} {c.name}{critical}: {c.detail}")
    if critical_failure:
        print("Result: CRITICAL_FAILURE")
    elif score < threshold:
        print(f"Result: NEEDS_REPLAN (score < {threshold})")
    else:
        print("Result: PASS")


def plan_summary(plan: Dict) -> Dict:
    p = len(plan.get("plan_tasks", []))
    e = len(plan.get("execution_tasks", []))
    total = p + e
    covered = sum(
        1
        for key in [
            "direction_insights",
            "market_insights",
            "timing_insights",
            "differentiation_insights",
            "monetization_insights",
            "constraint_insights",
            "risk_signal_insights",
            "evolution_insights",
        ]
        if non_empty(plan.get(key))
    )
    recent_auto_replan = last_auto_replan_event(plan)
    health = storage_health_report()
    return {
        "goal": plan.get("goal"),
        "success_metric": plan.get("success_metric"),
        "deadline": plan.get("deadline"),
        "planning_horizon": plan.get("planning_horizon"),
        "review_cadence": plan.get("review_cadence"),
        "updated_at": plan.get("updated_at"),
        "phase_count": len(plan.get("phase_plan", [])),
        "plan_task_count": p,
        "execution_task_count": e,
        "plan_ratio": round((p / total * 100), 1) if total > 0 else None,
        "reference_count": len(plan.get("references", [])),
        "reference_discovery_count": len(plan.get("reference_discoveries", [])),
        "insight_count": len(plan.get("insights", [])),
        "insight_axes_covered": covered,
        "insight_axes_total": 8,
        "weighted_insight_quality": round(weighted_insight_quality(plan), 2),
        "evidence_count": len(evidence_objects(plan)),
        "hypothesis_count": len(plan.get("hypothesis_log", [])),
        "risk_count": len(plan.get("risks", [])),
        "storage_health": {
            "status": health["status"],
            "revision_count": health["revision_count"],
            "issues": health["issues"],
        },
        "recent_auto_replan": {
            "blocked": recent_auto_replan.get("blocked", []),
            "actions": recent_auto_replan.get("actions", []),
            "initial_result": recent_auto_replan.get("initial_result", ""),
            "final_result": recent_auto_replan.get("final_result", recent_auto_replan.get("initial_result", "")),
            "score_delta": recent_auto_replan.get("score_delta", 0),
        }
        if recent_auto_replan
        else None,
    }


def extend_unique_strings(values: List[str], candidates: List[str]) -> List[str]:
    existing = {value.strip() for value in values if isinstance(value, str)}
    for candidate in candidates:
        normalized = candidate.strip()
        if normalized and normalized not in existing:
            values.append(normalized)
            existing.add(normalized)
    return values


def add_autoreplan_action(actions: List[str], message: str) -> None:
    if message not in actions:
        actions.append(message)


def ensure_axis_insight_depth(plan: Dict, axis_key: str, suggestions: List[str]) -> bool:
    values = plan.setdefault(axis_key, [])
    before = len(values)
    if before >= 3:
        return False
    extend_unique_strings(values, suggestions[: max(0, 3 - before)])
    return len(values) > before


def derive_planning_horizon(deadline_text: str) -> str:
    if not deadline_text:
        return "12 weeks"
    try:
        deadline_date = datetime.strptime(deadline_text, "%Y-%m-%d").date()
    except ValueError:
        return "12 weeks"
    days = max(1, (deadline_date - date.today()).days)
    weeks = max(1, round(days / 7))
    if weeks >= 8:
        return f"{weeks} weeks"
    return f"{days} days"


def derive_review_cadence(horizon_text: str) -> str:
    if "month" in horizon_text or "week" in horizon_text:
        return "weekly"
    return "twice-weekly"


def auto_replan(plan: Dict, checks: List[CheckResult]) -> Tuple[Dict, List[str], List[str]]:
    actions: List[str] = []
    failed = [c.name for c in checks if not c.passed]
    blocked = [name for name in failed if name in {"goal_clarity", "measurability"}]
    if blocked:
        return plan, actions, blocked

    if "constraints" in failed and not plan.get("constraints"):
        plan["constraints"] = ["Define practical limits for time, budget, and staffing."]
        add_autoreplan_action(actions, "Added baseline constraints.")
    if "assumptions" in failed and not plan.get("assumptions"):
        plan["assumptions"] = ["Key assumptions need explicit validation."]
        add_autoreplan_action(actions, "Added baseline assumptions.")
    if "options_comparison" in failed:
        plan["options"] = extend_unique_strings(plan.get("options", []), [
            "Conservative option: narrow scope and faster delivery.",
            "Balanced option: medium scope with staged rollout.",
            "Aggressive option: broad scope with higher risk.",
        ])
        if len(plan["options"]) >= 2 and not plan.get("selected_option"):
            plan["selected_option"] = plan["options"][0]
        add_autoreplan_action(actions, "Completed option comparison and selected a provisional path.")
    if "references_coverage" in failed and len(plan.get("references", [])) < 3:
        before = len(plan.get("references", []))
        plan["references"] = extend_unique_strings(plan.get("references", []), [
            "Spec-driven planning examples",
            "Agent workflow docs",
            "Postmortem of failed planning cases",
        ])
        if len(plan["references"]) > before:
            add_autoreplan_action(actions, "Added missing reference coverage.")
    if "reference_discovery_loop" in failed:
        before = len(plan.get("plan_tasks", []))
        plan["plan_tasks"] = extend_unique_strings(plan.get("plan_tasks", []), [
            "Run and log one reference discovery pass before adopting external patterns.",
        ])
        if len(plan["plan_tasks"]) > before:
            add_autoreplan_action(actions, "Added reference-discovery follow-up task.")
    if "insight_axes_coverage" in failed and len(plan.get("insights", [])) < 3:
        before = len(plan.get("insights", []))
        plan["insights"] = extend_unique_strings(plan.get("insights", []), [
            "Treat planning as first-class work, not overhead.",
            "Require evidence links for every critical decision.",
            "Replan from execution signals, not intuition.",
        ])
        if len(plan["insights"]) > before:
            add_autoreplan_action(actions, "Added generic planning insights.")
    if "insight_axes_coverage" in failed:
        if not plan.get("direction_insights"):
            plan["direction_insights"] = ["State why this initiative matters now and what outcome it must create."]
            add_autoreplan_action(actions, "Filled missing direction insight.")
        if not plan.get("market_insights"):
            plan["market_insights"] = ["Identify the highest-pain user segment and current alternatives."]
            add_autoreplan_action(actions, "Filled missing market insight.")
        if not plan.get("timing_insights"):
            plan["timing_insights"] = ["Define why this timing is favorable now and what delay would cost."]
            add_autoreplan_action(actions, "Filled missing timing insight.")
        if not plan.get("differentiation_insights"):
            plan["differentiation_insights"] = ["Describe one clear strategic difference versus existing options."]
            add_autoreplan_action(actions, "Filled missing differentiation insight.")
        if not plan.get("monetization_insights"):
            plan["monetization_insights"] = ["Link user value to a concrete monetization path."]
            add_autoreplan_action(actions, "Filled missing monetization insight.")
        if not plan.get("constraint_insights"):
            plan["constraint_insights"] = ["List execution constraints and the intended workaround strategy."]
            add_autoreplan_action(actions, "Filled missing constraint insight.")
        if not plan.get("risk_signal_insights"):
            plan["risk_signal_insights"] = ["Define one early failure signal and the immediate response."]
            add_autoreplan_action(actions, "Filled missing risk-signal insight.")
        if not plan.get("evolution_insights"):
            plan["evolution_insights"] = ["Define how the plan will be revised on a weekly or monthly cadence."]
            add_autoreplan_action(actions, "Filled missing evolution insight.")
    if "insight_quality_weighted" in failed:
        depth_templates = {
            "direction_insights": [
                "Clarify the concrete outcome this initiative must create in the next review cycle.",
                "Name the decision this plan should make easier or faster.",
                "State what will be deprioritized to protect direction quality.",
            ],
            "market_insights": [
                "Name the narrowest segment with repeated pain and current workaround behavior.",
                "Describe the frequency and severity of the target pain.",
                "Identify what makes this segment care now rather than later.",
            ],
            "timing_insights": [
                "Describe the external change that makes this timing favorable.",
                "State the cost of waiting one review cycle longer.",
                "Note which near-term window could close if delayed.",
            ],
            "differentiation_insights": [
                "State the first-session difference users should notice versus alternatives.",
                "Describe the capability incumbents do not serve well.",
                "Clarify which tradeoff is acceptable to preserve differentiation.",
            ],
            "monetization_insights": [
                "Map the main user value to a willingness-to-pay signal.",
                "Describe the earliest monetizable outcome this plan can produce.",
                "State what pricing proxy would validate this direction.",
            ],
            "constraint_insights": [
                "List the hardest execution limit for the next horizon.",
                "Describe the mitigation if that limit tightens unexpectedly.",
                "State what scope cap prevents resource dilution.",
            ],
            "risk_signal_insights": [
                "Name the earliest disconfirming signal for this direction.",
                "Define the trigger that should force a replan decision.",
                "State which metric would indicate false momentum.",
            ],
            "evolution_insights": [
                "Specify what evidence must be reviewed each cycle.",
                "Describe what kind of signal changes the plan versus the execution layer.",
                "State which learning should compound into the next phase plan.",
            ],
        }
        depth_added = False
        for axis_key, suggestions in depth_templates.items():
            if ensure_axis_insight_depth(plan, axis_key, suggestions):
                depth_added = True
        if depth_added:
            add_autoreplan_action(actions, "Expanded insight depth across all planning axes.")
    if "planning_horizon" in failed:
        if not plan.get("planning_horizon"):
            plan["planning_horizon"] = derive_planning_horizon(plan.get("deadline", ""))
            add_autoreplan_action(actions, "Set planning horizon from deadline or default.")
        if not plan.get("review_cadence"):
            plan["review_cadence"] = derive_review_cadence(plan["planning_horizon"])
            add_autoreplan_action(actions, "Set review cadence from planning horizon.")
    if "phase_plan" in failed and not plan.get("phase_plan"):
        plan["phase_plan"] = [
            "Phase 1 (Weeks 1-2): Problem framing and reference collection.",
            "Phase 2 (Weeks 3-6): Option testing and strategic choice.",
            "Phase 3 (Weeks 7-12): Signal tracking and plan refinement.",
        ]
        add_autoreplan_action(actions, "Added default phase plan.")
    if len(plan.get("plan_tasks", [])) < 2:
        before = len(plan.get("plan_tasks", []))
        plan["plan_tasks"] = extend_unique_strings(plan.get("plan_tasks", []), [
            "Collect references and extract constraints.",
            "Generate and compare three strategy options.",
            "Define milestone review checkpoints.",
            "Prepare next-cycle replan criteria.",
        ])
        if len(plan["plan_tasks"]) > before:
            add_autoreplan_action(actions, "Expanded plan tasks.")
    if len(plan.get("execution_tasks", [])) < 2:
        before = len(plan.get("execution_tasks", []))
        plan["execution_tasks"] = extend_unique_strings(plan.get("execution_tasks", []), [
            "Run the next small validation loop with a real user or artifact.",
            "Capture outcome signals against the success metric.",
        ])
        if len(plan["execution_tasks"]) > before:
            add_autoreplan_action(actions, "Expanded execution tasks.")
    if "verification_loop" in failed and not plan.get("experiments"):
        plan["experiments"] = ["Run one pilot iteration and compare against success metric."]
        add_autoreplan_action(actions, "Added validation experiment.")
    if "evidence_quality" in failed:
        existing_evidence = evidence_objects(plan)
        existing_claims = {
            item.get("claim", "").strip()
            for item in existing_evidence
            if isinstance(item, dict)
        }
        existing_sources = {
            item.get("source", "").strip()
            for item in existing_evidence
            if isinstance(item, dict) and item.get("source", "").strip()
        }
        high_conf = sum(1 for item in existing_evidence if isinstance(item, dict) and int(item.get("confidence", 0)) >= 60)
        seeded_evidence = [
            ("Primary user pain appears frequently.", "interview-notes", 65, "market_insights"),
            ("Current alternatives fail to solve core workflow.", "competitor-review", 70, "differentiation_insights"),
            ("Users show willingness to pay for time savings.", "pricing-survey", 60, "monetization_insights"),
        ]
        added_evidence = 0
        for claim, source, confidence, axis in seeded_evidence:
            if claim in existing_claims:
                continue
            needs_count = len(evidence_objects(plan)) < 3
            needs_confidence = high_conf < 2 and confidence >= 60
            needs_sources = len(existing_sources) < 2 and source not in existing_sources
            if not any([needs_count, needs_confidence, needs_sources]):
                continue
            add_evidence(plan, claim, source, confidence, axis)
            existing_claims.add(claim)
            existing_sources.add(source)
            if confidence >= 60:
                high_conf += 1
            added_evidence += 1
            if len(evidence_objects(plan)) >= 3 and high_conf >= 2 and len(existing_sources) >= 2:
                break
        if added_evidence:
            add_autoreplan_action(actions, "Added evidence to restore minimum quality coverage.")
    if "hypothesis_loop" in failed and not plan.get("hypothesis_log"):
        plan["hypothesis_log"] = [
            {
                "ts": now_iso(),
                "hypothesis": "A narrow segment has painful repeated need for this solution.",
                "metric": "weekly-active-pilot-users",
                "target": ">= 20",
                "window": "14 days",
                "status": "open",
                "outcome": "",
            }
        ]
        add_autoreplan_action(actions, "Added baseline hypothesis.")
    if "risk_coverage" in failed and not plan.get("risks"):
        plan["risks"] = [
            {
                "risk": "Scope drift",
                "signal": "New requirements added mid-cycle",
                "mitigation": "Freeze sprint scope and defer extras",
            }
        ]
        add_autoreplan_action(actions, "Added baseline risk record.")
    if "dependencies" in failed and not plan.get("dependencies"):
        plan["dependencies"] = ["Agent runtime support (Codex/Claude Code)"]
        add_autoreplan_action(actions, "Added baseline dependency.")
    if "definition_of_done" in failed and not plan.get("definition_of_done"):
        plan["definition_of_done"] = ["All core commands work and QA >= 70."]
        add_autoreplan_action(actions, "Added definition of done.")

    return plan, actions, blocked


def qa_autoreplan_result(plan: Dict, base_revision_entry: Optional[Dict] = None) -> Dict:
    score, checks, critical_failure = run_qa(plan)
    initial = qa_report(plan)
    threshold = qa_pass_threshold(checks)
    initial_fingerprint = plan_fingerprint(plan)
    outcome = {
        "plan": plan,
        "initial_qa": initial,
        "qa": initial,
        "auto_replan": {
            "triggered": False,
            "blocked": [],
            "actions": [],
        },
    }
    if score >= threshold and not critical_failure:
        return outcome

    updated_plan, actions, blocked = auto_replan(plan, checks)
    outcome["auto_replan"] = {
        "triggered": True,
        "blocked": blocked,
        "actions": actions,
    }
    event_payload = {
        "ts": now_iso(),
        "type": "auto_replan",
        "source": "qa_autoreplan_result",
        "blocked": blocked,
        "actions": actions,
        "initial_result": initial["result"],
        "initial_score": initial["score"],
        "threshold": initial["threshold"],
        "initial_updated_at": plan.get("updated_at", ""),
        "initial_fingerprint": initial_fingerprint,
    }
    if blocked:
        append_jsonl(EVENTS_PATH, event_payload)
        return outcome

    save_validated_plan(updated_plan)
    auto_revision = append_revision(
        updated_plan,
        "qa_autoreplan_result",
        reason="auto_replan",
        previous_fingerprint=initial_fingerprint,
    )
    outcome["plan"] = updated_plan
    outcome["qa"] = qa_report(updated_plan)
    outcome["auto_replan"]["revision_id"] = auto_revision["revision_id"]
    event_payload.update(
        {
            "final_result": outcome["qa"]["result"],
            "final_score": outcome["qa"]["score"],
            "score_delta": outcome["qa"]["score"] - initial["score"],
            "final_updated_at": outcome["plan"].get("updated_at", ""),
            "final_fingerprint": plan_fingerprint(outcome["plan"]),
        }
    )
    append_jsonl(EVENTS_PATH, event_payload)
    return outcome


def cmd_init(_: argparse.Namespace) -> None:
    ensure_state()
    print(f"Initialized state in {STATE_DIR}")


def cmd_plan(args: argparse.Namespace) -> None:
    def apply_updates(plan: Dict) -> None:
        plan["goal"] = args.goal or plan.get("goal", "")
        plan["success_metric"] = args.success_metric or plan.get("success_metric", "")
        plan["deadline"] = args.deadline or plan.get("deadline", "")
        plan["planning_horizon"] = args.planning_horizon or plan.get("planning_horizon", "")
        plan["review_cadence"] = args.review_cadence or plan.get("review_cadence", "")

        if args.constraints:
            plan["constraints"] = parse_csv(args.constraints)
        if args.assumptions:
            plan["assumptions"] = parse_csv(args.assumptions)
        if args.options:
            plan["options"] = parse_csv(args.options)
        if args.selected_option:
            plan["selected_option"] = args.selected_option.strip()
        if args.plan_tasks:
            plan["plan_tasks"] = parse_csv(args.plan_tasks)
        if args.execution_tasks:
            plan["execution_tasks"] = parse_csv(args.execution_tasks)
        if args.phase_plan:
            plan["phase_plan"] = parse_csv(args.phase_plan)
        if args.references:
            plan["references"] = parse_csv(args.references)
        if args.insights:
            plan["insights"] = parse_csv(args.insights)
        if args.direction_insights:
            plan["direction_insights"] = parse_csv(args.direction_insights)
        if args.market_insights:
            plan["market_insights"] = parse_csv(args.market_insights)
        if args.timing_insights:
            plan["timing_insights"] = parse_csv(args.timing_insights)
        if args.differentiation_insights:
            plan["differentiation_insights"] = parse_csv(args.differentiation_insights)
        if args.monetization_insights:
            plan["monetization_insights"] = parse_csv(args.monetization_insights)
        if args.constraint_insights:
            plan["constraint_insights"] = parse_csv(args.constraint_insights)
        if args.risk_signal_insights:
            plan["risk_signal_insights"] = parse_csv(args.risk_signal_insights)
        if args.evolution_insights:
            plan["evolution_insights"] = parse_csv(args.evolution_insights)
        if args.dependencies:
            plan["dependencies"] = parse_csv(args.dependencies)
        if args.experiments:
            plan["experiments"] = parse_csv(args.experiments)
        if args.definition_of_done:
            plan["definition_of_done"] = parse_csv(args.definition_of_done)

    result = mutate_plan_state(
        apply_updates,
        event_payloads=[{"ts": now_iso(), "type": "plan_updated", "source": "cmd_plan", "goal": args.goal or ""}],
        include_autoreplan=True,
        revision_source="cmd_plan",
        revision_reason=args.goal or "",
    )
    report = result["initial_qa"]
    print_qa(
        report["score"],
        [CheckResult(**check) for check in report["checks"]],
        report["critical_failure"],
    )

    if result["auto_replan"]["triggered"]:
        print("Auto replan triggered.")
        if result["auto_replan"]["blocked"]:
            print(f"Auto replan blocked by manual fields: {', '.join(result['auto_replan']['blocked'])}")
            return
        if result["auto_replan"]["actions"]:
            print("Auto replan actions:")
            for action in result["auto_replan"]["actions"]:
                print(f"- {action}")
        print("Post-replan QA:")
        post = result["qa"]
        print_qa(
            post["score"],
            [CheckResult(**check) for check in post["checks"]],
            post["critical_failure"],
        )


def cmd_replan(args: argparse.Namespace) -> None:
    result = mutate_plan_state(
        lambda plan: apply_replan_payload(plan, vars(args)),
        event_payloads=[{"ts": now_iso(), "type": "replan", "source": "cmd_replan", "evidence": args.evidence or ""}],
        include_autoreplan=True,
        revision_source="cmd_replan",
        revision_reason=args.evidence or "",
    )
    report = result["initial_qa"]
    print_qa(
        report["score"],
        [CheckResult(**check) for check in report["checks"]],
        report["critical_failure"],
    )
    if result["auto_replan"]["triggered"]:
        print("Auto replan triggered.")
        if result["auto_replan"]["blocked"]:
            print(f"Auto replan blocked by manual fields: {', '.join(result['auto_replan']['blocked'])}")
            return
        if result["auto_replan"]["actions"]:
            print("Auto replan actions:")
            for action in result["auto_replan"]["actions"]:
                print(f"- {action}")
        print("Post-replan QA:")
        post = result["qa"]
        print_qa(
            post["score"],
            [CheckResult(**check) for check in post["checks"]],
            post["critical_failure"],
        )


def cmd_decide(args: argparse.Namespace) -> None:
    ensure_state()
    payload = {
        "ts": now_iso(),
        "title": args.title.strip(),
        "chosen": args.chosen.strip(),
        "reason": args.reason.strip(),
        "rejected": [r.strip() for r in args.rejected.split(",") if r.strip()] if args.rejected else [],
    }
    append_jsonl(DECISIONS_PATH, payload)
    print("Decision recorded.")


def cmd_risk(args: argparse.Namespace) -> None:
    ensure_state()
    payload = {"ts": now_iso(), "risk": args.risk.strip(), "signal": args.signal.strip(), "mitigation": args.mitigation.strip()}
    append_jsonl(RISKS_PATH, payload)
    print("Risk recorded.")


def cmd_evidence(args: argparse.Namespace) -> None:
    claim = ensure_non_empty_text(args.claim, "claim")
    mutate_plan_state(
        lambda plan: (
            add_evidence(
                plan,
                claim,
                args.source.strip() if args.source else "manual",
                ensure_confidence(args.confidence),
                args.axis or "",
                args.date or "",
            ),
            plan.setdefault("references", []).append(args.reference.strip()) if args.reference else None,
        ),
        event_payloads=[
            {
                "ts": now_iso(),
                "type": "evidence_added",
                "source": "cmd_evidence",
                "claim": claim,
                "axis": normalize_axis_label(args.axis) if args.axis else "",
                "confidence": ensure_confidence(args.confidence),
            }
        ],
        revision_source="cmd_evidence",
        revision_reason=claim,
    )
    print("Evidence recorded.")


def cmd_hypothesis(args: argparse.Namespace) -> None:
    hypothesis = ensure_non_empty_text(args.hypothesis, "hypothesis")
    payload = {
        "ts": now_iso(),
        "hypothesis": hypothesis,
        "metric": args.metric.strip() if args.metric else "",
        "target": args.target.strip() if args.target else "",
        "window": args.window.strip() if args.window else "",
        "status": args.status,
        "outcome": args.outcome.strip() if args.outcome else "",
    }
    mutate_plan_state(
        lambda plan: (
            plan.setdefault("hypothesis_log", []).append(payload),
            add_evidence(
                plan,
                ensure_non_empty_text(args.evidence, "evidence"),
                "hypothesis-test",
                ensure_confidence(args.confidence),
                args.axis or "",
                args.date or "",
            )
            if args.evidence
            else None,
        ),
        event_payloads=[
            {
                "ts": now_iso(),
                "type": "hypothesis_added",
                "source": "cmd_hypothesis",
                "status": args.status,
                "hypothesis": hypothesis,
            }
        ],
        revision_source="cmd_hypothesis",
        revision_reason=hypothesis,
    )
    print("Hypothesis recorded.")


def cmd_qa(_: argparse.Namespace) -> None:
    plan = load_plan()
    score, checks, critical_failure = run_qa(plan)
    print_qa(score, checks, critical_failure)


def cmd_validate(_: argparse.Namespace) -> None:
    plan = load_plan()
    report = validate_plan_shape(plan)
    print(json.dumps(report, indent=2, ensure_ascii=False))


def cmd_schema(args: argparse.Namespace) -> None:
    runtime_schema = build_plan_schema()
    if args.check:
        report = schema_drift_report()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"Schema Match: {'yes' if report['matches'] else 'no'}")
            print(f"Schema Path: {report['schema_path']}")
            print(f"Runtime Properties: {report['runtime_property_count']}")
            print(f"File Properties: {report['file_property_count']}")
        if not report["matches"]:
            raise SystemExit("schema drift detected")
        return
    if args.write:
        schema_path().write_text(json.dumps(runtime_schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote schema to {schema_path()}")
        return
    print(json.dumps(runtime_schema, indent=2, ensure_ascii=False))


def cmd_health(args: argparse.Namespace) -> None:
    report = storage_health_report()
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print(f"Status: {report['status']}")
    print(f"State Dir: {report['state_dir']}")
    print(f"Plan Parseable: {'yes' if report['plan_parseable'] else 'no'}")
    print(f"Plan Valid: {'yes' if report['plan_valid'] else 'no'}")
    print(f"Writable: {'yes' if report['writable'] else 'no'}")
    print(f"Revision Count: {report['revision_count']}")
    print(f"Current Fingerprint: {report['current_fingerprint'] or 'n/a'}")
    print(f"Latest Recoverable Revision: {report['latest_recoverable_revision_id'] or 'n/a'}")
    print(f"Current Matches Latest Revision: {'yes' if report['current_matches_latest_revision'] else 'no'}")
    for label, entry in report["retention"]["logs"].items():
        if entry["retention_limit"] > 0:
            print(f"{label.title()} Retention: {entry['line_count']}/{entry['retention_limit']}")
    if report["issues"]:
        print("Issues:")
        for issue in report["issues"]:
            print(f"- {issue}")
    else:
        print("Issues: none")


def cmd_maintenance(args: argparse.Namespace) -> None:
    report = maintenance_report(apply=bool(args.apply))
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    print(f"Applied: {'yes' if report['applied'] else 'no'}")
    for label, entry in report["logs"].items():
        limit = entry["retention_limit"]
        print(
            f"{label}: lines={entry['line_count']} limit={limit or 'unbounded'} "
            f"pruned={entry.get('pruned_lines', 0)}"
        )


def cmd_show(_: argparse.Namespace) -> None:
    plan = load_plan()
    summary = plan_summary(plan)
    plan_ratio = f"{summary['plan_ratio']:.1f}%" if summary["plan_ratio"] is not None else "n/a"
    print(f"Goal: {summary['goal']}")
    print(f"Success Metric: {summary['success_metric']}")
    print(f"Deadline: {summary['deadline']}")
    print(f"Planning Horizon: {summary['planning_horizon']}")
    print(f"Review Cadence: {summary['review_cadence']}")
    print(f"Updated: {summary['updated_at']}")
    print(f"Phases: {summary['phase_count']}")
    print(f"Plan Tasks: {summary['plan_task_count']}")
    print(f"Execution Tasks: {summary['execution_task_count']}")
    print(f"Plan Ratio: {plan_ratio}")
    print(f"References: {summary['reference_count']}")
    print(f"Reference Discoveries: {summary['reference_discovery_count']}")
    print(f"Insights: {summary['insight_count']}")
    print(f"Insight Axes Covered: {summary['insight_axes_covered']}/{summary['insight_axes_total']}")
    print(f"Insight Quality (weighted): {summary['weighted_insight_quality']:.2f}")
    print(f"Evidence Items: {summary['evidence_count']}")
    print(f"Hypotheses: {summary['hypothesis_count']}")
    print(f"Risks: {summary['risk_count']}")
    print(f"Storage Health: {summary['storage_health']['status']}")
    revisions = list_revisions(limit=1)
    print(f"Revision Count: {len(read_jsonl(REVISIONS_PATH))}")
    if revisions:
        print(f"Latest Revision: {revisions[0]['revision_id']} ({revisions[0]['source']})")
    if summary["recent_auto_replan"]:
        recent = summary["recent_auto_replan"]
        print(
            "Recent Auto Replan: "
            f"{recent['initial_result']} -> {recent['final_result']} "
            f"(score delta: {recent['score_delta']})"
        )
        if recent["blocked"]:
            print(f"Recent Auto Replan Blocked: {', '.join(recent['blocked'])}")
        if recent["actions"]:
            print("Recent Auto Replan Actions:")
            for action in recent["actions"]:
                print(f"- {action}")


def cmd_history(args: argparse.Namespace) -> None:
    revisions = list_revisions(limit=args.limit)
    if args.json:
        print(json.dumps({"revisions": revisions}, indent=2, ensure_ascii=False))
        return
    if not revisions:
        print("No revisions recorded.")
        return
    for item in revisions:
        reason = f" | {item['reason']}" if item.get("reason") else ""
        metadata = item.get("metadata", {})
        qa_label = ""
        if metadata.get("qa_result"):
            qa_label = f" | qa={metadata['qa_result']}:{metadata.get('qa_score', 0)}"
        goal = metadata.get("goal", "")
        goal_label = f" | goal={goal}" if goal else ""
        print(f"{item['revision_id']} | {item['ts']} | {item['source']}{reason}{qa_label}{goal_label}")


def cmd_restore(args: argparse.Namespace) -> None:
    if getattr(args, "preview", False):
        preview = restore_preview(getattr(args, "revision_id", ""), previous=getattr(args, "previous", False))
        if getattr(args, "json", False):
            print(json.dumps(preview, indent=2, ensure_ascii=False))
            return
        print(f"Revision: {preview['revision_id']}")
        print(f"Source: {preview['source']}")
        if preview["reason"]:
            print(f"Reason: {preview['reason']}")
        if preview["metadata"]:
            print(f"Target QA: {preview['metadata'].get('qa_result', '')} ({preview['metadata'].get('qa_score', 0)})")
            if preview["metadata"].get("goal"):
                print(f"Target Goal: {preview['metadata']['goal']}")
        print(f"No-op: {'yes' if preview['no_op'] else 'no'}")
        print(f"Change Count: {preview['change_count']}")
        if preview["diff"]:
            print("Changed Fields:")
            for item in preview["diff"]:
                before = item["before"]
                after = item["after"]
                if before["type"] == "scalar" and after["type"] == "scalar":
                    print(f"- {item['field']}: {before.get('value', '')} -> {after.get('value', '')}")
                else:
                    print(f"- {item['field']}: {before['type']} -> {after['type']}")
        return

    revision = resolve_revision_reference(getattr(args, "revision_id", ""), previous=getattr(args, "previous", False))
    restored = mutate_plan_state(
        lambda plan: (plan.clear(), plan.update(json.loads(json.dumps(revision["plan"])))),
        event_payloads=[
            {
                "ts": now_iso(),
                "type": "plan_restored",
                "source": "cmd_restore",
                "revision_id": revision["revision_id"],
            }
        ],
        expected_fingerprint=args.expected_fingerprint or None,
        revision_source="cmd_restore",
        revision_reason=f"restore:{revision['revision_id']}",
    )
    print(f"Restored revision {revision['revision_id']}")
    print(f"Current fingerprint: {plan_fingerprint(restored)}")


def cmd_insight(args: argparse.Namespace) -> None:
    ensure_state()
    plan = load_plan()
    topic = args.topic.strip() if args.topic else plan.get("goal", "").strip() or "new initiative"
    context = args.context.strip() if args.context else ""
    references = parse_csv(args.references) if args.references else []

    assumptions = [
        f"Assumption: demand exists for '{topic}' in the selected segment.",
        f"Assumption: timing is favorable within {plan.get('planning_horizon') or 'the current horizon'}.",
        "Assumption: strategic differentiation can be made visible to users quickly.",
    ]
    viewpoints = [
        f"Market view: Which user segment has painful, frequent demand around '{topic}'?",
        f"Timing view: What changes in the next 3-6 months make this more or less valuable?",
        "Monetization view: Which willingness-to-pay signal appears earliest?",
        "Constraint view: Which hard limit (time, capital, distribution) will block momentum first?",
        "Risk view: What early signal would prove the direction is wrong?",
    ]
    challenge = [
        "Counterpoint: If users can solve this with existing tools, differentiation may be weak.",
        "Counterpoint: If activation requires heavy behavior change, adoption may stall.",
        "Counterpoint: If monetization depends on scale, short-horizon value may be low.",
    ]
    next_questions = [
        "Which segment has the highest pain-frequency pair?",
        "What single metric would prove direction quality in 2 weeks?",
        "Which assumption is most expensive if wrong?",
    ]

    proposal = {
        "direction_insights": [f"Anchor direction: '{topic}' must solve a high-frequency pain, not a nice-to-have."],
        "market_insights": ["Prioritize one narrow segment with repeated pain and clear alternatives."],
        "timing_insights": ["Validate why now: identify one external shift that increases urgency."],
        "differentiation_insights": ["Define one strategic difference users can notice in the first session."],
        "monetization_insights": ["Map user value to earliest willingness-to-pay signal."],
        "constraint_insights": ["Explicitly cap scope by time and resources for this horizon."],
        "risk_signal_insights": ["Define one disconfirming signal that triggers immediate replan."],
        "evolution_insights": ["Run cadence-based replanning with evidence at each review checkpoint."],
    }

    output = {
        "topic": topic,
        "context": context,
        "assumptions_to_challenge": assumptions,
        "viewpoint_expansion": viewpoints,
        "counter_views": challenge,
        "next_questions": next_questions,
        "reference_queue": references,
        "axis_proposals": proposal,
    }

    if args.apply:
        mutate_plan_state(
            lambda current_plan: (
                [current_plan.setdefault(key, []).extend(values) for key, values in proposal.items()],
                current_plan.setdefault("references", []).extend(references) if references else None,
                [
                    add_evidence(current_plan, f"Reference captured for topic '{topic}'.", ref, 60, "market_insights")
                    for ref in references[:3]
                ]
                if references
                else None,
            ),
            event_payloads=[
                {
                    "ts": now_iso(),
                    "type": "insight_generated",
                    "source": "cmd_insight",
                    "topic": topic,
                    "applied": True,
                }
            ],
            revision_source="cmd_insight",
            revision_reason=topic,
        )
        print("Insight pack applied to current plan.")

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        print(f"Topic: {topic}")
        print("Viewpoint Expansion:")
        for v in viewpoints:
            print(f"- {v}")
        print("Counter Views:")
        for c in challenge:
            print(f"- {c}")
        print("Next Questions:")
        for q in next_questions:
            print(f"- {q}")
        if references:
            print("Reference Queue:")
            for r in references:
                print(f"- {r}")


def cmd_discover(args: argparse.Namespace) -> None:
    ensure_state()
    plan = load_plan()
    question = args.question.strip() if args.question else plan.get("goal", "").strip()
    pack = build_reference_discovery_pack(
        question=question,
        context=args.context.strip() if args.context else "",
        references=parse_csv(args.references) if args.references else [],
        rejected=parse_csv(args.rejected) if args.rejected else [],
    )
    output = {
        "question": pack["question"],
        "context": pack["context"],
        "search_mode": pack["search_mode"],
        "trigger_signals": pack["trigger_signals"],
        "selection_criteria": pack["selection_criteria"],
        "candidate_queries": pack["candidate_queries"],
        "shortlisted_references": pack["shortlisted_references"],
        "rejected_references": pack["rejected_references"],
        "decision": pack["decision"],
        "plan_updates": pack["plan_updates"],
    }

    if args.apply:
        record = reference_discovery_record(pack)
        mutate_plan_state(
            lambda current_plan: (
                current_plan.setdefault("reference_discoveries", []).append(record),
                current_plan.setdefault("references", []).extend(pack["shortlisted_references"]) if pack["shortlisted_references"] else None,
                current_plan.setdefault("plan_tasks", []).extend(
                    [item for item in pack["plan_updates"]["plan_tasks"] if item not in current_plan.get("plan_tasks", [])]
                ),
                current_plan.setdefault("execution_tasks", []).extend(
                    [item for item in pack["plan_updates"]["execution_tasks"] if item not in current_plan.get("execution_tasks", [])]
                ),
                current_plan.setdefault("evolution_insights", []).extend(
                    [item for item in pack["plan_updates"]["evolution_insights"] if item not in current_plan.get("evolution_insights", [])]
                ),
                add_evidence(
                    current_plan,
                    f"Reference discovery logged for '{pack['question']}' via {pack['search_mode']}.",
                    "reference-discovery",
                    72,
                    "evolution",
                ),
            ),
            event_payloads=[
                {
                    "ts": now_iso(),
                    "type": "reference_discovery",
                    "source": "cmd_discover",
                    "question": pack["question"],
                    "search_mode": pack["search_mode"],
                    "shortlisted_count": len(pack["shortlisted_references"]),
                }
            ],
            revision_source="cmd_discover",
            revision_reason=pack["question"],
        )
        output["applied"] = True
        print("Reference discovery applied to current plan.")

    if args.json:
        print(json.dumps(output, indent=2, ensure_ascii=False))
        return

    print(f"Question: {output['question']}")
    print(f"Search Mode: {output['search_mode']}")
    print("Trigger Signals:")
    for item in output["trigger_signals"]:
        print(f"- {item}")
    print("Selection Criteria:")
    for item in output["selection_criteria"]:
        print(f"- {item}")
    print("Candidate Queries:")
    for item in output["candidate_queries"]:
        print(f"- {item}")
    if output["shortlisted_references"]:
        print("Shortlisted References:")
        for item in output["shortlisted_references"]:
            print(f"- {item}")
    if output["rejected_references"]:
        print("Rejected References:")
        for item in output["rejected_references"]:
            print(f"- {item}")
    print(f"Decision: {output['decision']}")


def missing_insight_axes(plan: Dict) -> List[str]:
    axis_map = {
        "direction_insights": "direction",
        "market_insights": "market",
        "timing_insights": "timing",
        "differentiation_insights": "differentiation",
        "monetization_insights": "monetization",
        "constraint_insights": "constraints",
        "risk_signal_insights": "risk-signals",
        "evolution_insights": "evolution",
    }
    return [label for key, label in axis_map.items() if not non_empty(plan.get(key))]


def cmd_review(args: argparse.Namespace) -> None:
    ensure_state()
    plan = load_plan()
    score, checks, critical_failure = run_qa(plan)
    total = qa_total_weight(checks)
    threshold = qa_pass_threshold(checks)

    missing_axes = missing_insight_axes(plan)
    has_horizon = horizon_defined(plan)
    has_phases = non_empty(plan.get("phase_plan"))
    discovery_count = len(plan.get("reference_discoveries", []))
    has_reference_loop = reference_discovery_logged(plan)
    period = args.period.strip() if args.period else "current cycle"
    notes = args.notes.strip() if args.notes else ""
    signals = parse_csv(args.signals) if args.signals else []

    next_questions: List[str] = []
    if missing_axes:
        next_questions.append(f"Which evidence can fill missing insight axes first: {', '.join(missing_axes)}?")
    if not has_horizon:
        next_questions.append("What planning horizon and review cadence are realistic for this initiative?")
    if not has_phases:
        next_questions.append("What 3-phase milestone structure should guide the next horizon?")
    if not has_reference_loop:
        next_questions.append("Which external reference question needs a logged discovery pass before the next decision?")
    if not signals:
        next_questions.append("What early risk signal should be tracked in the next review cycle?")
    if not hypothesis_loop_ok(plan):
        next_questions.append("What testable hypothesis should be added for the next cycle?")
    next_questions.extend(
        [
            "Which assumption became stronger or weaker since last review?",
            "What should be explicitly deprioritized in the next cycle?",
        ]
    )

    recommendations: List[str] = []
    if score < threshold or critical_failure:
        recommendations.append("Strengthen plan quality to pass QA before expanding scope.")
    if missing_axes:
        recommendations.append("Generate and apply insight pack for missing axes.")
    if not has_horizon:
        recommendations.append("Set planning horizon and review cadence explicitly.")
    if not has_phases:
        recommendations.append("Define phase milestones for the active horizon.")
    if not has_reference_loop:
        recommendations.append("Run reference discovery and log selection criteria before relying on external examples.")
    if not hypothesis_loop_ok(plan):
        recommendations.append("Add hypothesis entries with metric/target/window and update status each cycle.")
    if signals:
        recommendations.append(f"Review incoming signals and decide replan trigger: {', '.join(signals)}.")

    report = {
        "period": period,
        "score": score,
        "score_total": total,
        "pass_threshold": threshold,
        "critical_failure": critical_failure,
        "missing_insight_axes": missing_axes,
        "horizon_defined": has_horizon,
        "phase_plan_defined": has_phases,
        "reference_discovery_count": discovery_count,
        "reference_discovery_logged": has_reference_loop,
        "signals": signals,
        "notes": notes,
        "recommendations": recommendations,
        "next_questions": next_questions[:5],
    }

    if args.apply:
        cycle_note = f"[review:{period}] score={score}/{total}; missing_axes={','.join(missing_axes) if missing_axes else 'none'}"
        mutate_plan_state(
            lambda current_plan: (
                add_evidence(current_plan, cycle_note, "review-cycle", 70, "evolution_insights"),
                current_plan.setdefault("evolution_insights", []).append(
                    f"Review outcome for {period}: prioritize {missing_axes[0] if missing_axes else 'quality maintenance'}."
                ),
            ),
            event_payloads=[
                {
                    "ts": now_iso(),
                    "type": "review",
                    "source": "cmd_review",
                    "period": period,
                    "score": score,
                    "critical_failure": critical_failure,
                }
            ],
            revision_source="cmd_review",
            revision_reason=period,
        )
        report["applied"] = True

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(f"Review Period: {period}")
        print(f"QA: {score}/{total} (threshold: {threshold})")
        print(f"Critical Failure: {'yes' if critical_failure else 'no'}")
        print(f"Missing Insight Axes: {', '.join(missing_axes) if missing_axes else 'none'}")
        print(f"Horizon Defined: {'yes' if has_horizon else 'no'}")
        print(f"Phase Plan Defined: {'yes' if has_phases else 'no'}")
        if signals:
            print(f"Signals: {', '.join(signals)}")
        if notes:
            print(f"Notes: {notes}")
        print("Recommendations:")
        for r in recommendations:
            print(f"- {r}")
        print("Next Planning Questions:")
        for q in next_questions[:5]:
            print(f"- {q}")


def cmd_ideate(args: argparse.Namespace) -> None:
    ensure_state()
    ideas = generate_ideas(args)
    append_jsonl(
        EVENTS_PATH,
        {
            "ts": now_iso(),
            "type": "ideate",
            "source": "cmd_ideate",
            "count": len(ideas),
            "profile": args.profile or "",
        },
    )

    if args.json:
        print(json.dumps(ideas, indent=2, ensure_ascii=False))
    else:
        for idx, idea in enumerate(ideas, start=1):
            print(f"[{idx}] {idea['title']}")
            print(f"  Goal: {idea['goal']}")
            print(f"  Success Metric: {idea['success_metric']}")
            print(f"  Deadline: {idea['deadline']}")
            print(f"  Constraints: {', '.join(idea['constraints'])}")
            print("")

    if args.apply:
        choice = args.apply - 1
        if choice < 0 or choice >= len(ideas):
            raise SystemExit(f"--apply must be between 1 and {len(ideas)}")

        selected = ideas[choice]
        plan = mutate_plan_state(
            lambda current_plan: current_plan.update(
                {
                    "goal": selected["goal"],
                    "success_metric": selected["success_metric"],
                    "deadline": selected["deadline"],
                    "constraints": selected["constraints"],
                    "assumptions": selected["assumptions"],
                    "plan_tasks": selected["plan_tasks"],
                    "execution_tasks": selected["execution_tasks"],
                    "experiments": selected["experiments"],
                    "definition_of_done": selected["definition_of_done"],
                }
            ),
            event_payloads=[
                {
                    "ts": now_iso(),
                    "type": "idea_applied",
                    "source": "cmd_ideate",
                    "selected_index": args.apply,
                    "goal": selected["goal"],
                }
            ],
            revision_source="cmd_ideate",
            revision_reason=selected["goal"],
        )
        print(f"Applied idea #{args.apply} to current plan.")
        score, checks, critical_failure = run_qa(plan)
        print_qa(score, checks, critical_failure)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DeepPlan local planning engine (MVP)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("plan")
    s.add_argument("--goal", type=str, default="")
    s.add_argument("--success-metric", type=str, default="")
    s.add_argument("--deadline", type=str, default="")
    s.add_argument("--planning-horizon", type=str, default="")
    s.add_argument("--review-cadence", type=str, default="")
    s.add_argument("--constraints", type=str, default="")
    s.add_argument("--assumptions", type=str, default="")
    s.add_argument("--options", type=str, default="")
    s.add_argument("--selected-option", type=str, default="")
    s.add_argument("--plan-tasks", type=str, default="")
    s.add_argument("--execution-tasks", type=str, default="")
    s.add_argument("--phase-plan", type=str, default="")
    s.add_argument("--references", type=str, default="")
    s.add_argument("--insights", type=str, default="")
    s.add_argument("--direction-insights", type=str, default="")
    s.add_argument("--market-insights", type=str, default="")
    s.add_argument("--timing-insights", type=str, default="")
    s.add_argument("--differentiation-insights", type=str, default="")
    s.add_argument("--monetization-insights", type=str, default="")
    s.add_argument("--constraint-insights", type=str, default="")
    s.add_argument("--risk-signal-insights", type=str, default="")
    s.add_argument("--evolution-insights", type=str, default="")
    s.add_argument("--dependencies", type=str, default="")
    s.add_argument("--experiments", type=str, default="")
    s.add_argument("--definition-of-done", type=str, default="")
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("replan")
    s.add_argument("--evidence", type=str, default="")
    s.add_argument("--evidence-source", type=str, default="")
    s.add_argument("--evidence-confidence", type=int, default=60)
    s.add_argument("--evidence-axis", type=str, default="")
    s.add_argument("--evidence-date", type=str, default="")
    s.add_argument("--plan-task", type=str, default="")
    s.add_argument("--execution-task", type=str, default="")
    s.add_argument("--phase", type=str, default="")
    s.add_argument("--reference", type=str, default="")
    s.add_argument("--insight", type=str, default="")
    s.add_argument("--direction-insight", type=str, default="")
    s.add_argument("--market-insight", type=str, default="")
    s.add_argument("--timing-insight", type=str, default="")
    s.add_argument("--differentiation-insight", type=str, default="")
    s.add_argument("--monetization-insight", type=str, default="")
    s.add_argument("--constraint-insight", type=str, default="")
    s.add_argument("--risk-signal-insight", type=str, default="")
    s.add_argument("--evolution-insight", type=str, default="")
    s.set_defaults(func=cmd_replan)

    s = sub.add_parser("decide")
    s.add_argument("--title", type=str, required=True)
    s.add_argument("--chosen", type=str, required=True)
    s.add_argument("--reason", type=str, required=True)
    s.add_argument("--rejected", type=str, default="")
    s.set_defaults(func=cmd_decide)

    s = sub.add_parser("risk")
    s.add_argument("--risk", type=str, required=True)
    s.add_argument("--signal", type=str, required=True)
    s.add_argument("--mitigation", type=str, required=True)
    s.set_defaults(func=cmd_risk)

    s = sub.add_parser("evidence")
    s.add_argument("--claim", type=str, required=True)
    s.add_argument("--source", type=str, default="manual")
    s.add_argument("--confidence", type=int, default=60)
    s.add_argument("--axis", type=str, default="")
    s.add_argument("--date", type=str, default="")
    s.add_argument("--reference", type=str, default="")
    s.set_defaults(func=cmd_evidence)

    s = sub.add_parser("hypothesis")
    s.add_argument("--hypothesis", type=str, required=True)
    s.add_argument("--metric", type=str, default="")
    s.add_argument("--target", type=str, default="")
    s.add_argument("--window", type=str, default="")
    s.add_argument("--status", choices=["open", "validated", "invalidated", "pivoted"], default="open")
    s.add_argument("--outcome", type=str, default="")
    s.add_argument("--evidence", type=str, default="")
    s.add_argument("--confidence", type=int, default=60)
    s.add_argument("--axis", type=str, default="")
    s.add_argument("--date", type=str, default="")
    s.set_defaults(func=cmd_hypothesis)

    s = sub.add_parser("qa")
    s.set_defaults(func=cmd_qa)

    s = sub.add_parser("validate")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("schema")
    s.add_argument("--check", action="store_true")
    s.add_argument("--write", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_schema)

    s = sub.add_parser("health")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_health)

    s = sub.add_parser("maintenance")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_maintenance)

    s = sub.add_parser("show")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("history")
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_history)

    s = sub.add_parser("restore")
    s.add_argument("--revision-id", type=str, default="")
    s.add_argument("--previous", action="store_true")
    s.add_argument("--expected-fingerprint", type=str, default="")
    s.add_argument("--preview", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_restore)

    s = sub.add_parser("ideate")
    s.add_argument("--profile", type=str, default="")
    s.add_argument("--interests", type=str, default="")
    s.add_argument("--skills", type=str, default="")
    s.add_argument("--time-per-day", type=str, default="1h/day")
    s.add_argument("--budget", type=str, default="$0")
    s.add_argument("--deadline", type=str, default="")
    s.add_argument("--count", type=int, default=5)
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply", type=int, default=0, help="Apply selected idea index to current plan (1-based).")
    s.set_defaults(func=cmd_ideate)

    s = sub.add_parser("insight")
    s.add_argument("--topic", type=str, default="")
    s.add_argument("--context", type=str, default="")
    s.add_argument("--references", type=str, default="")
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_insight)

    s = sub.add_parser("discover")
    s.add_argument("--question", type=str, default="")
    s.add_argument("--context", type=str, default="")
    s.add_argument("--references", type=str, default="")
    s.add_argument("--rejected", type=str, default="")
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_discover)

    s = sub.add_parser("review")
    s.add_argument("--period", type=str, default="")
    s.add_argument("--signals", type=str, default="")
    s.add_argument("--notes", type=str, default="")
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply", action="store_true")
    s.set_defaults(func=cmd_review)
    return p


def main() -> None:
    parser = build_parser()
    try:
        args = parser.parse_args()
        args.func(args)
    except ValueError as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
