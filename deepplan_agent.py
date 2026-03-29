#!/usr/bin/env python3
import argparse
import json
import shlex
from typing import Any, Dict, List, Optional, Tuple

from deepplan import (
    add_evidence,
    apply_replan_payload,
    build_reference_discovery_pack,
    get_revision,
    list_revisions,
    load_plan,
    mutate_plan_state,
    now_iso,
    parse_csv,
    plan_fingerprint,
    plan_response,
    plan_summary,
    qa_autoreplan_result,
    qa_report,
    record_idempotency_result,
    reference_discovery_record,
    replay_idempotency_result,
    resolve_revision_reference,
    restore_preview,
    save_validated_plan,
    storage_health_report,
    validate_plan_shape,
)


SCALAR_PLAN_FIELDS = [
    "goal",
    "success_metric",
    "deadline",
    "planning_horizon",
    "review_cadence",
    "selected_option",
]

LIST_PLAN_FIELDS = [
    "phase_plan",
    "constraints",
    "assumptions",
    "options",
    "plan_tasks",
    "execution_tasks",
    "dependencies",
    "experiments",
    "risks",
    "references",
    "insights",
    "direction_insights",
    "market_insights",
    "timing_insights",
    "differentiation_insights",
    "monetization_insights",
    "constraint_insights",
    "risk_signal_insights",
    "evolution_insights",
    "definition_of_done",
]

TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "get_plan",
        "description": "Return the current DeepPlan plan and derived summary.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_qa",
        "description": "Return the weighted QA report for the current plan.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_health",
        "description": "Return storage health, parseability, and recovery diagnostics.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "validate_plan",
        "description": "Validate the current DeepPlan plan structure and nested records.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_history",
        "description": "Return recent plan revisions with snapshot metadata.",
        "input_schema": {
            "type": "object",
            "properties": {"limit": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "restore_revision",
        "description": "Restore the current plan to a previously recorded revision snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "revision_id": {"type": "string"},
                "expected_fingerprint": {"type": "string"},
                "previous": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "preview_restore",
        "description": "Preview the diff and summary impact of restoring a recorded revision snapshot.",
        "input_schema": {
            "type": "object",
            "properties": {
                "revision_id": {"type": "string"},
                "previous": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "run_reference_discovery",
        "description": "Generate and optionally apply a structured reference-discovery pass for an open planning question.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_fingerprint": {"type": "string"},
                "question": {"type": "string"},
                "context": {"type": "string"},
                "references": {"type": "array", "items": {"type": "string"}},
                "rejected": {"type": "array", "items": {"type": "string"}},
                "apply": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "replan",
        "description": "Append execution evidence or planning deltas and run QA with auto-replan if needed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_fingerprint": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "evidence": {"type": "string"},
                "evidence_source": {"type": "string"},
                "evidence_confidence": {"type": "integer"},
                "evidence_axis": {"type": "string"},
                "evidence_date": {"type": "string"},
                "plan_task": {"type": "string"},
                "execution_task": {"type": "string"},
                "phase": {"type": "string"},
                "reference": {"type": "string"},
                "insight": {"type": "string"},
                "direction_insight": {"type": "string"},
                "market_insight": {"type": "string"},
                "timing_insight": {"type": "string"},
                "differentiation_insight": {"type": "string"},
                "monetization_insight": {"type": "string"},
                "constraint_insight": {"type": "string"},
                "risk_signal_insight": {"type": "string"},
                "evolution_insight": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "update_plan",
        "description": "Update top-level plan fields using scalar strings and list values.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_fingerprint": {"type": "string"},
                "goal": {"type": "string"},
                "success_metric": {"type": "string"},
                "deadline": {"type": "string"},
                "planning_horizon": {"type": "string"},
                "review_cadence": {"type": "string"},
                "selected_option": {"type": "string"},
                "phase_plan": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
                "options": {"type": "array", "items": {"type": "string"}},
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
                                "properties": {
                                    "risk": {"type": "string"},
                                    "signal": {"type": "string"},
                                    "mitigation": {"type": "string"},
                                },
                                "required": ["risk", "signal", "mitigation"],
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
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "add_evidence",
        "description": "Append one structured evidence item and optional reference.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_fingerprint": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "claim": {"type": "string"},
                "source": {"type": "string"},
                "confidence": {"type": "integer"},
                "axis": {"type": "string"},
                "date": {"type": "string"},
                "reference": {"type": "string"},
            },
            "required": ["claim"],
            "additionalProperties": False,
        },
    },
    {
        "name": "add_hypothesis",
        "description": "Append one hypothesis log item and optional linked evidence.",
        "input_schema": {
            "type": "object",
            "properties": {
                "expected_fingerprint": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "hypothesis": {"type": "string"},
                "metric": {"type": "string"},
                "target": {"type": "string"},
                "window": {"type": "string"},
                "status": {"type": "string", "enum": ["open", "validated", "invalidated", "pivoted"]},
                "outcome": {"type": "string"},
                "evidence": {"type": "string"},
                "confidence": {"type": "integer"},
                "axis": {"type": "string"},
                "date": {"type": "string"},
            },
            "required": ["hypothesis"],
            "additionalProperties": False,
        },
    },
]

TOOL_VALIDATORS = {
    "get_history": "validate_history_payload",
    "restore_revision": "validate_restore_payload",
    "preview_restore": "validate_preview_restore_payload",
    "run_reference_discovery": "validate_reference_discovery_payload",
    "replan": "validate_replan_payload",
    "update_plan": "validate_update_payload",
    "add_evidence": "validate_evidence_payload",
    "add_hypothesis": "validate_hypothesis_payload",
}

MUTATION_TOOLS = {
    "restore_revision",
    "run_reference_discovery",
    "replan",
    "update_plan",
    "add_evidence",
    "add_hypothesis",
}


def ensure_object_payload(payload: Dict[str, Any]) -> None:
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")


def validate_expected_fingerprint(payload: Dict[str, Any]) -> None:
    if "expected_fingerprint" in payload and not isinstance(payload["expected_fingerprint"], str):
        raise ValueError("expected_fingerprint must be a string")


def validate_idempotency_key(payload: Dict[str, Any]) -> None:
    if "idempotency_key" in payload and not isinstance(payload["idempotency_key"], str):
        raise ValueError("idempotency_key must be a string")


def validate_update_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    allowed = set(SCALAR_PLAN_FIELDS + LIST_PLAN_FIELDS + ["expected_fingerprint"])
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown update_plan fields: {', '.join(unknown)}")

    for field in SCALAR_PLAN_FIELDS:
        if field in payload and not isinstance(payload[field], str):
            raise ValueError(f"{field} must be a string")

    for field in LIST_PLAN_FIELDS:
        if field not in payload:
            continue
        value = payload[field]
        if not isinstance(value, list):
            raise ValueError(f"{field} must be an array")
        if field == "risks":
            for index, item in enumerate(value):
                if isinstance(item, str) and item.strip():
                    continue
                if isinstance(item, dict) and all(isinstance(item.get(key), str) and item.get(key, "").strip() for key in ["risk", "signal", "mitigation"]):
                    continue
                raise ValueError(f"risks[{index}] must be a non-empty string or an object with risk/signal/mitigation")
            continue
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"{field} must contain only strings")


def validate_history_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    allowed = {"limit"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown get_history fields: {', '.join(unknown)}")
    if "limit" in payload and (not isinstance(payload["limit"], int) or isinstance(payload["limit"], bool)):
        raise ValueError("limit must be an integer")


def validate_restore_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    allowed = {"revision_id", "expected_fingerprint", "previous"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown restore_revision fields: {', '.join(unknown)}")
    if "previous" in payload and not isinstance(payload["previous"], bool):
        raise ValueError("previous must be a boolean")
    revision_id = payload.get("revision_id", "")
    if "previous" in payload and payload["previous"]:
        return
    if not isinstance(revision_id, str) or not revision_id.strip():
        raise ValueError("revision_id is required unless previous=true")


def validate_preview_restore_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    allowed = {"revision_id", "previous"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown preview_restore fields: {', '.join(unknown)}")
    if "previous" in payload and not isinstance(payload["previous"], bool):
        raise ValueError("previous must be a boolean")
    revision_id = payload.get("revision_id", "")
    if "previous" in payload and payload["previous"]:
        return
    if not isinstance(revision_id, str) or not revision_id.strip():
        raise ValueError("revision_id is required unless previous=true")


def validate_evidence_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    validate_idempotency_key(payload)
    allowed = {"claim", "source", "confidence", "axis", "date", "reference", "expected_fingerprint", "idempotency_key"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown add_evidence fields: {', '.join(unknown)}")
    claim = payload.get("claim", "")
    if not isinstance(claim, str) or not claim.strip():
        raise ValueError("claim is required")
    for key in ["source", "axis", "date", "reference"]:
        if key in payload and not isinstance(payload[key], str):
            raise ValueError(f"{key} must be a string")
    if "confidence" in payload and (not isinstance(payload["confidence"], int) or isinstance(payload["confidence"], bool)):
        raise ValueError("confidence must be an integer")


def validate_reference_discovery_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    allowed = {"expected_fingerprint", "question", "context", "references", "rejected", "apply"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown run_reference_discovery fields: {', '.join(unknown)}")
    if "question" in payload and not isinstance(payload["question"], str):
        raise ValueError("question must be a string")
    if "context" in payload and not isinstance(payload["context"], str):
        raise ValueError("context must be a string")
    for key in ["references", "rejected"]:
        if key not in payload:
            continue
        value = payload[key]
        if not isinstance(value, list):
            raise ValueError(f"{key} must be an array")
        if not all(isinstance(item, str) for item in value):
            raise ValueError(f"{key} must contain only strings")
    if "apply" in payload and not isinstance(payload["apply"], bool):
        raise ValueError("apply must be a boolean")


def validate_hypothesis_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    validate_idempotency_key(payload)
    allowed = {"hypothesis", "metric", "target", "window", "status", "outcome", "evidence", "confidence", "axis", "date", "expected_fingerprint", "idempotency_key"}
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown add_hypothesis fields: {', '.join(unknown)}")
    hypothesis = payload.get("hypothesis", "")
    if not isinstance(hypothesis, str) or not hypothesis.strip():
        raise ValueError("hypothesis is required")
    for key in ["metric", "target", "window", "status", "outcome", "evidence", "axis", "date"]:
        if key in payload and not isinstance(payload[key], str):
            raise ValueError(f"{key} must be a string")
    if "confidence" in payload and (not isinstance(payload["confidence"], int) or isinstance(payload["confidence"], bool)):
        raise ValueError("confidence must be an integer")
    status = str(payload.get("status", "open")).strip() or "open"
    if status not in {"open", "validated", "invalidated", "pivoted"}:
        raise ValueError("status must be one of: open, validated, invalidated, pivoted")


def validate_replan_payload(payload: Dict[str, Any]) -> None:
    ensure_object_payload(payload)
    validate_expected_fingerprint(payload)
    validate_idempotency_key(payload)
    allowed = {
        "expected_fingerprint",
        "idempotency_key",
        "evidence",
        "evidence_source",
        "evidence_confidence",
        "evidence_axis",
        "evidence_date",
        "plan_task",
        "execution_task",
        "phase",
        "reference",
        "insight",
        "direction_insight",
        "market_insight",
        "timing_insight",
        "differentiation_insight",
        "monetization_insight",
        "constraint_insight",
        "risk_signal_insight",
        "evolution_insight",
    }
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ValueError(f"unknown replan fields: {', '.join(unknown)}")
    for key, value in payload.items():
        if key == "evidence_confidence":
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("evidence_confidence must be an integer")
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")


def merge_plan_updates(plan: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    for field in SCALAR_PLAN_FIELDS:
        if field in payload and isinstance(payload[field], str):
            plan[field] = payload[field].strip()
    for field in LIST_PLAN_FIELDS:
        if field in payload and isinstance(payload[field], list):
            plan[field] = payload[field]
    return plan


def list_tools() -> List[Dict[str, Any]]:
    return TOOL_SCHEMAS


def enrich_tool_result(name: str, result_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    enriched = dict(payload)
    enriched["ok"] = True
    enriched["tool_name"] = name
    enriched["result_type"] = result_type
    return enriched


def maybe_replay_idempotent_tool_result(name: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    idempotency_key = str(payload.get("idempotency_key", "")).strip()
    if not idempotency_key:
        return None
    replayed = replay_idempotency_result(name, idempotency_key)
    if not replayed:
        return None
    return enrich_tool_result(name, "mutation", replayed)


def finalize_idempotent_tool_result(name: str, payload: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    idempotency_key = str(payload.get("idempotency_key", "")).strip()
    if not idempotency_key:
        return result
    return record_idempotency_result(name, idempotency_key, result)


def tool_schema_contract_report() -> Dict[str, Any]:
    schema_names = {item["name"] for item in TOOL_SCHEMAS}
    expected_names = {
        "get_plan",
        "get_qa",
        "get_health",
        "validate_plan",
        "get_history",
        "restore_revision",
        "preview_restore",
        "run_reference_discovery",
        "replan",
        "update_plan",
        "add_evidence",
        "add_hypothesis",
    }
    missing = sorted(expected_names - schema_names)
    unexpected = sorted(schema_names - expected_names)
    missing_validators = sorted(name for name in schema_names if name in TOOL_VALIDATORS and TOOL_VALIDATORS[name] not in globals())
    additional_properties_true = sorted(
        item["name"]
        for item in TOOL_SCHEMAS
        if item.get("input_schema", {}).get("additionalProperties") is not False
    )
    mutation_tools_missing_expected_fingerprint = sorted(
        item["name"]
        for item in TOOL_SCHEMAS
        if item["name"] in MUTATION_TOOLS
        and "expected_fingerprint" not in item.get("input_schema", {}).get("properties", {})
    )
    return {
        "matches": not any(
            [
                missing,
                unexpected,
                missing_validators,
                additional_properties_true,
                mutation_tools_missing_expected_fingerprint,
            ]
        ),
        "tool_count": len(TOOL_SCHEMAS),
        "missing": missing,
        "unexpected": unexpected,
        "missing_validators": missing_validators,
        "additional_properties_true": additional_properties_true,
        "mutation_tools_missing_expected_fingerprint": mutation_tools_missing_expected_fingerprint,
    }


def execute_tool(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if name == "get_plan":
        plan = load_plan()
        return enrich_tool_result(name, "plan", plan_response(plan))

    if name == "get_qa":
        return enrich_tool_result(name, "qa", qa_report(load_plan()))

    if name == "get_health":
        return enrich_tool_result(name, "health", storage_health_report())

    if name == "get_history":
        validate_history_payload(payload)
        return enrich_tool_result(name, "history", {"revisions": list_revisions(int(payload.get("limit", 10)))})

    if name == "validate_plan":
        return enrich_tool_result(name, "validation", validate_plan_shape(load_plan()))

    if name == "restore_revision":
        validate_restore_payload(payload)
        revision = resolve_revision_reference(str(payload.get("revision_id", "")).strip(), bool(payload.get("previous", False)))
        plan = mutate_plan_state(
            lambda current_plan: (
                current_plan.clear(),
                current_plan.update(json.loads(json.dumps(revision["plan"]))),
            ),
            event_payloads=[
                {
                    "ts": now_iso(),
                    "type": "plan_restored",
                    "source": "restore_revision",
                    "revision_id": revision["revision_id"],
                }
            ],
            expected_fingerprint=payload.get("expected_fingerprint"),
            revision_source="restore_revision",
            revision_reason=f"restore:{revision['revision_id']}",
        )
        response = plan_response(plan)
        response["restored_revision_id"] = revision["revision_id"]
        response["qa"] = qa_report(plan)
        return enrich_tool_result(name, "mutation", response)

    if name == "preview_restore":
        validate_preview_restore_payload(payload)
        return enrich_tool_result(
            name,
            "restore_preview",
            restore_preview(str(payload.get("revision_id", "")).strip(), previous=bool(payload.get("previous", False))),
        )

    if name == "run_reference_discovery":
        validate_reference_discovery_payload(payload)
        plan = load_plan()
        question = str(payload.get("question", "")).strip() or str(plan.get("goal", "")).strip()
        pack = build_reference_discovery_pack(
            question=question,
            context=str(payload.get("context", "")).strip(),
            references=payload.get("references", []),
            rejected=payload.get("rejected", []),
        )
        response = {
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
        if bool(payload.get("apply", False)):
            record = reference_discovery_record(pack)
            result = mutate_plan_state(
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
                expected_fingerprint=payload.get("expected_fingerprint"),
                revision_source="run_reference_discovery",
                revision_reason=pack["question"],
            )
            response["applied"] = True
            response["plan"] = result
            response["summary"] = plan_summary(result)
            response["validation"] = validate_plan_shape(result)
            response["fingerprint"] = plan_fingerprint(result)
            response["qa"] = qa_report(result)
        return enrich_tool_result(name, "reference_discovery", response)

    if name == "replan":
        validate_replan_payload(payload)
        replayed = maybe_replay_idempotent_tool_result(name, payload)
        if replayed:
            return replayed
        result = mutate_plan_state(
            lambda plan: apply_replan_payload(plan, payload),
            include_autoreplan=True,
            expected_fingerprint=payload.get("expected_fingerprint"),
            revision_source="replan",
            revision_reason=str(payload.get("evidence", "")).strip(),
        )
        response = {
            "plan": result["plan"],
            "summary": plan_summary(result["plan"]),
            "validation": validate_plan_shape(result["plan"]),
            "fingerprint": plan_fingerprint(result["plan"]),
            "qa": result["qa"],
            "auto_replan": result["auto_replan"],
        }
        return enrich_tool_result(name, "mutation", finalize_idempotent_tool_result(name, payload, response))

    if name == "update_plan":
        validate_update_payload(payload)
        result = mutate_plan_state(
            lambda plan: merge_plan_updates(plan, payload),
            include_autoreplan=True,
            expected_fingerprint=payload.get("expected_fingerprint"),
            revision_source="update_plan",
            revision_reason=str(payload.get("goal", "")).strip(),
        )
        return enrich_tool_result(name, "mutation", {
            "plan": result["plan"],
            "summary": plan_summary(result["plan"]),
            "validation": validate_plan_shape(result["plan"]),
            "fingerprint": plan_fingerprint(result["plan"]),
            "qa": result["qa"],
            "auto_replan": result["auto_replan"],
        })

    if name == "add_evidence":
        validate_evidence_payload(payload)
        replayed = maybe_replay_idempotent_tool_result(name, payload)
        if replayed:
            return replayed
        claim = str(payload.get("claim", "")).strip()
        plan = mutate_plan_state(
            lambda plan: (
                add_evidence(
                    plan,
                    claim,
                    str(payload.get("source", "agent")).strip() or "agent",
                    int(payload.get("confidence", 60)),
                    str(payload.get("axis", "")).strip(),
                    str(payload.get("date", "")).strip(),
                ),
                plan.setdefault("references", []).append(payload["reference"].strip())
                if isinstance(payload.get("reference"), str) and payload["reference"].strip()
                else None,
            ),
            expected_fingerprint=payload.get("expected_fingerprint"),
            revision_source="add_evidence",
            revision_reason=claim,
        )
        response = {"plan": plan, "summary": plan_summary(plan), "validation": validate_plan_shape(plan), "fingerprint": plan_response(plan)["fingerprint"], "qa": qa_report(plan)}
        return enrich_tool_result(
            name,
            "mutation",
            finalize_idempotent_tool_result(name, payload, response),
        )

    if name == "add_hypothesis":
        validate_hypothesis_payload(payload)
        replayed = maybe_replay_idempotent_tool_result(name, payload)
        if replayed:
            return replayed
        hypothesis = str(payload.get("hypothesis", "")).strip()
        status = str(payload.get("status", "open")).strip() or "open"
        evidence = str(payload.get("evidence", "")).strip()
        plan = mutate_plan_state(
            lambda plan: (
                plan.setdefault("hypothesis_log", []).append(
                    {
                        "ts": now_iso(),
                        "hypothesis": hypothesis,
                        "metric": str(payload.get("metric", "")).strip(),
                        "target": str(payload.get("target", "")).strip(),
                        "window": str(payload.get("window", "")).strip(),
                        "status": status,
                        "outcome": str(payload.get("outcome", "")).strip(),
                    }
                ),
                add_evidence(
                    plan,
                    evidence,
                    "hypothesis-test",
                    int(payload.get("confidence", 60)),
                    str(payload.get("axis", "")).strip(),
                    str(payload.get("date", "")).strip(),
                )
                if evidence
                else None,
            ),
            expected_fingerprint=payload.get("expected_fingerprint"),
            revision_source="add_hypothesis",
            revision_reason=hypothesis,
        )
        response = {"plan": plan, "summary": plan_summary(plan), "validation": validate_plan_shape(plan), "fingerprint": plan_response(plan)["fingerprint"], "qa": qa_report(plan)}
        return enrich_tool_result(
            name,
            "mutation",
            finalize_idempotent_tool_result(name, payload, response),
        )

    raise ValueError(f"unknown tool: {name}")


def coerce_scalar(value: str) -> Any:
    lowered = value.lower()
    if lowered.isdigit() or (lowered.startswith("-") and lowered[1:].isdigit()):
        return int(lowered)
    return value


def parse_assignment_tokens(tokens: List[str]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for token in tokens:
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in LIST_PLAN_FIELDS:
            payload[key] = parse_csv(value)
        else:
            payload[key] = coerce_scalar(value)
    return payload


def slash_to_tool(command: str) -> Tuple[str, Dict[str, Any]]:
    tokens = shlex.split(command)
    if not tokens:
        raise ValueError("empty input")
    head = tokens[0].strip()
    payload = parse_assignment_tokens(tokens[1:])

    mapping = {
        "/deepplan": "update_plan",
        "/deepplan.plan": "update_plan",
        "/deepplan.replan": "replan",
        "/deepplan.show": "get_plan",
        "/deepplan.history": "get_history",
        "/deepplan.restore": "restore_revision",
        "/deepplan.restore-preview": "preview_restore",
        "/deepplan.discover": "run_reference_discovery",
        "/deepplan.health": "get_health",
        "/deepplan.qa": "get_qa",
        "/deepplan.validate": "validate_plan",
        "/deepplan.evidence": "add_evidence",
        "/deepplan.hypothesis": "add_hypothesis",
    }
    tool_name = mapping.get(head)
    if not tool_name:
        raise ValueError(f"unsupported slash command: {head}")
    return tool_name, payload


def natural_language_to_tool(text: str) -> Tuple[str, Dict[str, Any]]:
    stripped = text.strip()
    lowered = stripped.lower()
    if stripped.startswith("/"):
        return slash_to_tool(stripped)
    if any(phrase in lowered for phrase in ["qa", "quality check", "quality status"]):
        return "get_qa", {}
    if any(phrase in lowered for phrase in ["health", "status health", "storage health"]):
        return "get_health", {}
    if lowered.startswith("preview restore "):
        return "preview_restore", parse_assignment_tokens(shlex.split(stripped[len("preview restore ") :]))
    if lowered == "preview previous revision":
        return "preview_restore", {"previous": True}
    if any(phrase in lowered for phrase in ["history", "revision history", "plan history"]):
        return "get_history", {}
    if any(phrase in lowered for phrase in ["validate plan", "plan validation", "check plan structure"]):
        return "validate_plan", {}
    if lowered.startswith("replan "):
        return "replan", parse_assignment_tokens(shlex.split(stripped[len("replan ") :]))
    if lowered.startswith("reference discovery "):
        return "run_reference_discovery", parse_assignment_tokens(shlex.split(stripped[len("reference discovery ") :]))
    if lowered.startswith("discover references "):
        return "run_reference_discovery", parse_assignment_tokens(shlex.split(stripped[len("discover references ") :]))
    if any(phrase in lowered for phrase in ["show plan", "current plan", "plan summary", "what is the plan"]):
        return "get_plan", {}
    if lowered.startswith("restore revision "):
        return "restore_revision", parse_assignment_tokens(shlex.split(stripped[len("restore revision ") :]))
    if lowered == "restore previous revision":
        return "restore_revision", {"previous": True}
    if lowered.startswith("add evidence "):
        return "add_evidence", parse_assignment_tokens(shlex.split(stripped[len("add evidence ") :]))
    if lowered.startswith("update plan "):
        return "update_plan", parse_assignment_tokens(shlex.split(stripped[len("update plan ") :]))
    if lowered.startswith("add hypothesis "):
        return "add_hypothesis", parse_assignment_tokens(shlex.split(stripped[len("add hypothesis ") :]))
    raise ValueError("could not map input to a DeepPlan tool")


def cmd_tools(_: argparse.Namespace) -> None:
    print(json.dumps({"tools": list_tools()}, indent=2, ensure_ascii=False))


def cmd_run(args: argparse.Namespace) -> None:
    try:
        tool_name, payload = natural_language_to_tool(args.input)
    except ValueError as exc:
        raise SystemExit(str(exc))
    envelope = {"tool": tool_name, "input": payload}
    if args.dry_run:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
        return
    try:
        result = execute_tool(tool_name, payload)
    except ValueError as exc:
        raise SystemExit(str(exc))
    print(json.dumps({"tool": tool_name, "input": payload, "result": result}, indent=2, ensure_ascii=False))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepPlan local agent wrapper")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("tools")
    s.set_defaults(func=cmd_tools)

    s = sub.add_parser("run")
    s.add_argument("--input", type=str, required=True)
    s.add_argument("--dry-run", action="store_true")
    s.set_defaults(func=cmd_run)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
