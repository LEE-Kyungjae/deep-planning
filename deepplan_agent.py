#!/usr/bin/env python3
import argparse
import json
import shlex
from typing import Any, Dict, List, Tuple

from deepplan import (
    add_evidence,
    load_plan,
    now_iso,
    parse_csv,
    plan_summary,
    qa_report,
    save_plan,
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
        "name": "update_plan",
        "description": "Update top-level plan fields using scalar strings and list values.",
        "input_schema": {
            "type": "object",
            "properties": {
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
                "risks": {"type": "array", "items": {"type": "object"}},
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


def execute_tool(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if name == "get_plan":
        plan = load_plan()
        return {"plan": plan, "summary": plan_summary(plan)}

    if name == "get_qa":
        return qa_report(load_plan())

    if name == "update_plan":
        plan = load_plan()
        plan = merge_plan_updates(plan, payload)
        save_plan(plan)
        return {"plan": plan, "summary": plan_summary(plan), "qa": qa_report(plan)}

    if name == "add_evidence":
        claim = str(payload.get("claim", "")).strip()
        if not claim:
            raise ValueError("claim is required")
        plan = load_plan()
        add_evidence(
            plan,
            claim,
            str(payload.get("source", "agent")).strip() or "agent",
            int(payload.get("confidence", 60)),
            str(payload.get("axis", "")).strip(),
            str(payload.get("date", "")).strip(),
        )
        if isinstance(payload.get("reference"), str) and payload["reference"].strip():
            plan.setdefault("references", []).append(payload["reference"].strip())
        save_plan(plan)
        return {"plan": plan, "summary": plan_summary(plan), "qa": qa_report(plan)}

    if name == "add_hypothesis":
        hypothesis = str(payload.get("hypothesis", "")).strip()
        if not hypothesis:
            raise ValueError("hypothesis is required")
        status = str(payload.get("status", "open")).strip() or "open"
        if status not in {"open", "validated", "invalidated", "pivoted"}:
            raise ValueError("status must be one of: open, validated, invalidated, pivoted")
        plan = load_plan()
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
        )
        evidence = str(payload.get("evidence", "")).strip()
        if evidence:
            add_evidence(
                plan,
                evidence,
                "hypothesis-test",
                int(payload.get("confidence", 60)),
                str(payload.get("axis", "")).strip(),
                str(payload.get("date", "")).strip(),
            )
        save_plan(plan)
        return {"plan": plan, "summary": plan_summary(plan), "qa": qa_report(plan)}

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
        "/deepplan.show": "get_plan",
        "/deepplan.qa": "get_qa",
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
    if any(phrase in lowered for phrase in ["show plan", "current plan", "plan summary", "what is the plan"]):
        return "get_plan", {}
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
    tool_name, payload = natural_language_to_tool(args.input)
    envelope = {"tool": tool_name, "input": payload}
    if args.dry_run:
        print(json.dumps(envelope, indent=2, ensure_ascii=False))
        return
    result = execute_tool(tool_name, payload)
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
