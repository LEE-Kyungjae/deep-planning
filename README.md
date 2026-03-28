# DeepPlan (MVP)

DeepPlan is a local, agent-friendly **Plan Intelligence** engine.
It focuses on one thing: making planning quality the core value.

## Why DeepPlan

Most AI products are excellent at `task -> implement`.
DeepPlan intentionally focuses on the only layer before that:

- what to build
- why now
- what not to build
- how to detect failure early

`Plan` is not prompt preparation.
`Plan` is the business and product decision layer.
DeepPlan is `Plan-only` by design.

## Product Thesis

In the AI era, execution is increasingly commoditized.
Direction quality is not.

If planning is weak, faster execution only accelerates the wrong path.
DeepPlan exists to reduce that failure mode.

## Target User

DeepPlan supports users with existing ideas, but its core strength is:

- users in a zero-idea state
- users who only know: "I want to build something, but I have not decided what"

DeepPlan should guide this ultra-early stage into a concrete, testable plan.

## Planning Philosophy

Humans bring context from life, experience, and intent.
AI should provide insight to elevate thinking quality, not just generate tasks.

Because model outputs can drift toward average patterns, DeepPlan planning should
force higher-signal inputs:

1. Strong references
2. Actionable insights
3. Audience interest detection
4. Need intensity detection
5. High information density
6. Multiple viewpoints

## First 10-Minute Outputs

For zero-idea users, DeepPlan should produce these quickly:

1. Problem/User hypothesis (who has what pain)
2. Three direction options with one explicit choice
3. A testable initial plan (metric, deadline, first tasks)

## Product Boundary

DeepPlan handles:

- idea discovery
- direction setting
- planning logic
- success/failure criteria definition

DeepPlan does not handle:

- task execution orchestration
- implementation workflows
- post-task delivery automation

Those layers are already saturated by other AI tools.
DeepPlan is the layer that decides what deserves execution.

## Value Thesis

In this thesis:

- `Plan` is where strategic value and monetization leverage live
- `Task+` layers are increasingly low-differentiation
- future advantage comes from building better plans, not faster generic execution

## What It Provides

- Shared/exportable plan format (`schemas/plan.schema.json`)
- CLI (`deepplan.py`)
- Minimal local HTTP service (`deepplan_server.py`)
- Agent wrapper + tool schema (`deepplan_agent.py`)
- Automatic quality checks on `plan` and `replan`
- Local regression checks (`Makefile`, `tests/test_deepplan.py`)
- Repo-local state in `.deeplan/`

## Evidence + Hypothesis Loop

DeepPlan now supports evidence-backed planning and hypothesis tracking:

- `evidence` accepts structured objects (`claim`, `source`, `confidence`, `axis`, `date`)
- `hypothesis_log` tracks testable hypotheses over time (`open/validated/invalidated/pivoted`)
- QA includes weighted quality checks:
  - insight quality weighted by depth + axis-linked evidence
  - evidence quality (quantity, confidence, source diversity)
  - hypothesis loop coverage

## Insight Axes (Long-Horizon Planning)

DeepPlan maps planning insight into eight required axes:

1. `direction_insights`
2. `market_insights`
3. `timing_insights`
4. `differentiation_insights`
5. `monetization_insights`
6. `constraint_insights`
7. `risk_signal_insights`
8. `evolution_insights`

`qa` checks whether all 8 axes are covered.

## Horizon Fields

Long-horizon planning is first-class in DeepPlan:

- `planning_horizon` (for example: `12 weeks`, `6 months`)
- `review_cadence` (for example: `weekly`, `biweekly`)
- `phase_plan` (milestone phases across the horizon)

## Messaging Drafts

### Slogans

1. Plan is the product.
2. Decide what matters before AI builds it.
3. In the AI era, direction is alpha.

### Landing Copy (Short)

DeepPlan is a Plan Intelligence tool for the AI era.
Execution is cheap. Direction is expensive.
When you do not know what to build yet, DeepPlan helps you turn ambiguity
into a focused, testable, monetizable plan.

## Quick Start

```bash
python3 deepplan.py init
python3 deepplan.py ideate --profile "solo builder" --interests "automation,creator tools" --count 5
python3 deepplan.py plan \
  --goal "Ship DeepPlan MVP CLI" \
  --success-metric "CLI supports plan/replan/decide/risk by 2026-03-15" \
  --deadline "2026-03-15" \
  --planning-horizon "12 weeks" \
  --review-cadence "weekly" \
  --phase-plan "phase1 framing,phase2 validation,phase3 refinement" \
  --constraints "single developer, local repo only" \
  --direction-insights "Why this initiative matters now" \
  --market-insights "Who has the strongest pain and why" \
  --timing-insights "Why now is the right timing" \
  --differentiation-insights "How this is strategically different" \
  --monetization-insights "How value turns into revenue" \
  --constraint-insights "Key constraints and workaround strategy" \
  --risk-signal-insights "Earliest failure signal and response" \
  --evolution-insights "How the plan evolves weekly"
python3 deepplan.py qa
python3 deepplan.py evidence --claim "Segment shows repeated pain" --source "interview-notes" --confidence 70 --axis market
python3 deepplan.py hypothesis --hypothesis "Narrow segment will adopt weekly" --metric "weekly-active-pilot-users" --target ">=20" --window "14 days" --status open
python3 deepplan.py insight --topic "AI planning co-work" --references "success:linear,fail:overbuild,counter:no-code tools" --apply
python3 deepplan.py review --period "week-1" --signals "low-activation,weak-retention" --apply
python3 deepplan.py show
python3 deepplan.py validate
python3 deepplan_agent.py tools
python3 deepplan_agent.py run --input '/deepplan.qa'
python3 deepplan_agent.py run --input '/deepplan.validate'
python3 deepplan_agent.py run --input '/deepplan.replan evidence="pilot users reported repeated friction" evidence_confidence=75 evidence_axis=market'
python3 deepplan_agent.py run --input 'show plan'
python3 deepplan_server.py --port 8787
```

## Commands

- `init`: create `/.deeplan/` files
- `plan`: create/update plan and run automatic QA
- `replan`: append execution evidence and re-run automatic QA
- `decide`: add decision record
- `risk`: add risk record
- `qa`: run QA checks manually
- `validate`: validate plan structure and nested record types
- `schema`: print the runtime schema, check for drift, or rewrite `schemas/plan.schema.json`
- `health`: print storage health, parseability, and recovery diagnostics
  - includes latest recoverable revision and whether the current plan matches it
  - includes current event/revision retention windows
- `maintenance`: inspect retention state or prune bounded operational logs with `--apply`
- `show`: print current plan summary, including the latest auto-replan signal when present
- `history`: print recent revision snapshots
- `restore`: restore the current plan from a recorded revision snapshot
  - `restore --preview`: preview changed fields and summary impact before mutation
  - restore preview now includes structured field-level diff summaries
  - `restore --previous`: target the immediately previous revision without specifying `revision_id`
- `ideate`: generate plan ideas from lightweight user context and optionally apply one
- `insight`: generate viewpoint-expansion insight pack and optionally apply it
- `review`: run cycle-based planning review with recommendations and next questions
- `evidence`: add structured evidence linked to planning axes
- `hypothesis`: append testable hypothesis entries and optional test evidence

## Dev Checks

```bash
make check
make test
make compile
make schema-check
```

## HTTP Service

DeepPlan also exposes a minimal local HTTP service without external dependencies:

```bash
python3 deepplan_server.py --host 127.0.0.1 --port 8787
```

Available endpoints:

- `GET /health`: storage health, parseability, and recovery diagnostics
- `GET /cycle`: plan + QA + health + recent revision history in one snapshot
- `GET /plan`: full current plan + derived summary, plus a `fingerprint` field and `ETag` header
- `GET /qa`: QA report as JSON
- `GET /history`: recent revision snapshots
- `GET /validate`: structural validation report for the current plan
- `GET /tools`: available tool schemas for agent/tool callers
- `POST /plan`: update core plan fields using a JSON object and run QA with auto-replan if needed
- `POST /evidence`: append one evidence item using JSON
- `POST /replan`: append execution evidence or incremental plan deltas and run QA with auto-replan if needed
- `POST /restore/preview`: preview one restore target directly without the `/tools` wrapper
- `POST /restore`: restore one revision directly with the same `If-Match` concurrency contract as other writes
- `POST /tools/<tool_name>`: run one tool with `{"input": {...}}`
- `POST /agent/act`: map slash/natural-language input to a tool call

Write endpoints support optimistic concurrency:

- Send `If-Match: "<fingerprint>"` on HTTP writes to reject stale updates with `412 Precondition Failed`
- Agent/tool callers can pass `expected_fingerprint` in mutation payloads
- Successful plan reads and writes return the latest `fingerprint`

Example:

```bash
curl http://127.0.0.1:8787/cycle?limit=5
curl http://127.0.0.1:8787/plan
curl http://127.0.0.1:8787/qa
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/history
curl http://127.0.0.1:8787/validate
curl http://127.0.0.1:8787/tools
curl -X POST http://127.0.0.1:8787/evidence \
  -H 'Content-Type: application/json' \
  -d '{"claim":"User pain repeated in interviews","source":"interview-notes","confidence":72,"axis":"market"}'
curl -X POST http://127.0.0.1:8787/replan \
  -H 'Content-Type: application/json' \
  -d '{"evidence":"Pilot users reported repeated friction","evidence_source":"pilot","evidence_confidence":75,"evidence_axis":"market"}'
curl -X POST http://127.0.0.1:8787/restore/preview \
  -H 'Content-Type: application/json' \
  -d '{"previous":true}'
curl -X POST http://127.0.0.1:8787/plan \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "<fingerprint-from-get-plan>"' \
  -d '{"goal":"Ship local agent layer"}'
curl -X POST http://127.0.0.1:8787/tools/add_hypothesis \
  -H 'Content-Type: application/json' \
  -d '{"input":{"hypothesis":"Narrow segment returns weekly","metric":"weekly-active-pilot-users","target":">=20","window":"14 days"}}'
curl -X POST http://127.0.0.1:8787/tools/preview_restore \
  -H 'Content-Type: application/json' \
  -d '{"input":{"revision_id":"<revision-id>"}}'
curl -X POST http://127.0.0.1:8787/agent/act \
  -H 'Content-Type: application/json' \
  -d '{"input":"/deepplan.evidence claim=\"Repeated pain in interviews\" source=interviews confidence=75 axis=market"}'
```

## Agent Wrapper

DeepPlan now includes a local wrapper for slash-style and lightweight natural-language control:

```bash
python3 deepplan_agent.py tools
python3 deepplan_agent.py run --input '/deepplan.show'
python3 deepplan_agent.py run --input '/deepplan.health'
python3 deepplan_agent.py run --input '/deepplan.restore-preview revision_id=<revision-id>'
python3 deepplan_agent.py run --input 'preview previous revision'
python3 deepplan_agent.py run --input '/deepplan.plan goal="Ship local agent layer" planning_horizon="4 weeks" review_cadence=weekly'
python3 deepplan_agent.py run --input '/deepplan.replan evidence="Pilot retention improved" evidence_confidence=70 evidence_axis=market'
python3 deepplan_agent.py run --input '/deepplan.history'
python3 deepplan_agent.py run --input '/deepplan.evidence claim="Repeated planning pain" source=interviews confidence=72 axis=market'
python3 deepplan_agent.py run --input 'show plan'
python3 deepplan_agent.py run --input 'qa'
python3 deepplan.py schema --check
python3 deepplan.py maintenance --apply
```

Supported slash commands:

- `/deepplan`
- `/deepplan.plan`
- `/deepplan.replan`
- `/deepplan.show`
- `/deepplan.health`
- `/deepplan.history`
- `/deepplan.restore`
- `/deepplan.restore-preview`
- `/deepplan.qa`
- `/deepplan.validate`
- `/deepplan.evidence`
- `/deepplan.hypothesis`

Mutation tools now also accept an optional `expected_fingerprint` field so callers can reject stale writes without going through HTTP.
Tool responses now include stable `ok`, `tool_name`, and `result_type` fields to simplify downstream orchestration.

## Python Client

This repo now includes a lightweight integration-facing client in `deepplan_client.py`.

Example:

```python
from deepplan_client import DeepPlanClient

client = DeepPlanClient.from_http("127.0.0.1", 8787)
cycle = client.get_cycle(history_limit=5)
plan = client.get_plan()
updated = client.update_plan({"goal": "Ship local agent layer"})
wrapped = client.apply_and_get_cycle(
    "update_plan",
    {"goal": "Ship local agent layer", "success_metric": "Reach 2 pilots", "deadline": "2026-04-03"},
    history_limit=3,
)
restored = client.apply_and_get_cycle(
    "restore_revision",
    {"previous": True},
    history_limit=3,
)
retried = client.apply_and_get_cycle_with_retry(
    "update_plan",
    {"goal": "Ship local agent layer"},
    expected_fingerprint="stale-fingerprint",
)
cycle_result = client.capture_evidence_cycle(
    {"claim": "Pilot friction repeated", "source": "pilot-call", "confidence": 74, "axis": "market"},
    replan_payload={"plan_task": "Tighten onboarding loop"},
)
preview = client.preview_restore(previous=True)
```

High-level client wrappers now raise `DeepPlanConflictError` for stale fingerprint conflicts and `DeepPlanClientOperationError` for step-scoped multi-call failures.
By default, retry-after-refresh is only enabled for `update_plan`; append-style operations like `add_evidence` and `replan` require `allow_non_idempotent_retry=True`.

## Agent Input Mapping

Bundled wrapper behavior:
- `/deepplan` and `/deepplan.plan` -> `update_plan` tool payload
- `/deepplan.replan` -> `replan` tool payload
- `/deepplan.show` -> `get_plan`
- `/deepplan.health` -> `get_health`
- `/deepplan.history` -> `get_history`
- `/deepplan.restore` -> `restore_revision`
- `/deepplan.restore-preview` -> `preview_restore`
- `/deepplan.qa` -> `get_qa`
- `/deepplan.validate` -> `validate_plan`
- `/deepplan.evidence` -> `add_evidence`
- `/deepplan.hypothesis` -> `add_hypothesis`

Natural-language examples:
- `python3 deepplan_agent.py run --input 'update plan goal=\"Ship local agent layer\" deadline=2026-04-15'`
- `python3 deepplan_agent.py run --dry-run --input '/deepplan.replan evidence=\"Pilot users returned\" evidence_confidence=70 evidence_axis=market'`
- `python3 deepplan.py ideate --profile "solo builder" --interests "automation,creator tools" --count 5 --apply 2`

## Storage

- `.deeplan/plan.json`
- `.deeplan/decisions.jsonl`
- `.deeplan/risks.jsonl`
- `.deeplan/events.jsonl`
- `.deeplan/revisions.jsonl`

This is intentionally minimal and meant to be used by AI agents (Codex/Claude Code) as a common local planning primitive.
