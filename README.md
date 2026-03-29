# DeepPlan

DeepPlan is a local, agent-friendly planning kernel.

It is built for the layer before execution:

- what to build
- why now
- what evidence supports the plan
- what would invalidate it
- when to replan

DeepPlan is intentionally not an execution orchestrator. It is the planning and decision layer that other tools, agents, and runtimes can build on top of.

## Project Thesis

DeepPlan exists because execution is getting cheaper while direction is not.

In the AI era, more systems can generate code, content, tasks, and workflows.
That does not solve the harder problem:

- choosing the right direction
- rejecting weak directions early
- finding better evidence before execution hardens the wrong path
- keeping product and business intent coherent over time

DeepPlan is built on one belief:

`Plan is the product.`

This repo should keep pressure on the planning layer itself:

- better goals
- better hypotheses
- better evidence
- better failure detection
- better replanning

If planning is weak, faster execution only accelerates the wrong path.

## Product Boundary

DeepPlan is `plan-only` by design.

DeepPlan should own:

- idea discovery
- direction setting
- planning logic
- success and failure criteria
- evidence-backed replanning
- revision-aware recovery

DeepPlan should not own:

- task execution orchestration
- delivery automation
- general agent runtime concerns
- workflow scheduling
- channel or chat surfaces

Those layers can be built around DeepPlan, but they should not blur the purpose of this repo.

## What DeepPlan Is

DeepPlan now has four access layers around the same planning core:

- CLI: direct local planning workflows
- HTTP service: local integration surface
- Agent wrapper: slash-command and tool-style control
- Python client: typed integration contract for external repos

The core guarantees are:

- schema-backed plan shape
- QA and validation on core mutations
- revision snapshots and safe restore preview
- optimistic concurrency via fingerprints
- storage health and recovery diagnostics

## Why This Matters

Most AI products are strong at `task -> implement`.
DeepPlan is intentionally focused on the layer before that.

The value thesis is:

- `Plan` is where strategic value and monetization leverage live
- generic execution layers are increasingly commoditized
- future advantage comes from better plans, not just faster output

## Core Concepts

DeepPlan centers on one mutable plan plus supporting logs.

- `plan`: the current structured planning state
- `evidence`: concrete signals tied to planning axes
- `hypothesis_log`: testable bets and outcomes
- `reference_discoveries`: logged reference-search questions, criteria, and shortlisted candidates
- `risks`: failure modes, early signals, mitigation
- `revisions`: immutable plan snapshots over time
- `events`: operational history such as auto-replan activity

Long-horizon planning is first-class:

- `planning_horizon`
- `review_cadence`
- `phase_plan`

Insight coverage is organized across eight axes:

1. `direction_insights`
2. `market_insights`
3. `timing_insights`
4. `differentiation_insights`
5. `monetization_insights`
6. `constraint_insights`
7. `risk_signal_insights`
8. `evolution_insights`

## State Model

DeepPlan stores repo-local state in `.deeplan/`:

- `plan.json`: current plan
- `decisions.jsonl`: decision log
- `risks.jsonl`: risk log
- `events.jsonl`: operational events
- `revisions.jsonl`: revision snapshots

The runtime also tracks:

- `fingerprint`: optimistic concurrency token for the current plan
- revision history for restore and audit
- storage health, recovery candidates, and retention windows

## Interface Guide

Use the interface that matches the job:

- CLI: manual planning, local iteration, shell workflows
- HTTP: editor tools, sidecars, external local services
- Agent wrapper: slash commands and natural-language tool routing
- Python client: typed integration from another repo

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
python3 deepplan.py discover --question "design agent examples" --context "Need GitHub references for product UX hierarchy" --references "repo-a,repo-b" --apply
python3 deepplan.py hypothesis --hypothesis "Narrow segment will adopt weekly" --metric "weekly-active-pilot-users" --target ">=20" --window "14 days" --status open
python3 deepplan.py show
python3 deepplan.py history
python3 deepplan.py restore --preview --previous
python3 deepplan.py health
```

## Planning Semantics

DeepPlan is designed around explicit planning loops:

- `plan`: define or overwrite core direction
- `evidence`: add structured market/product signal
- `discover`: structure reference search before adopting external patterns
- `hypothesis`: track testable assumptions
- `replan`: adjust execution-facing plan state from new evidence
- `review`: inspect plan quality and next questions
- `restore`: recover an earlier planning snapshot safely

QA is built into core plan mutations and can trigger auto-replan when the plan is thin but recoverable.

## Concurrency, Restore, and Retry

### Fingerprints

Every current plan state has a `fingerprint`.

- Writes can include `expected_fingerprint`
- HTTP callers use `If-Match: "<fingerprint>"`
- stale writes return `412 Precondition Failed`

### Restore

Restore is treated as a normal write:

- preview via `restore --preview` or `POST /restore/preview`
- restore via `restore` or `POST /restore`
- restore uses the same concurrency contract as other writes

### Retry Policy

The Python client has typed conflict and retry semantics:

- `DeepPlanConflictError`: stale fingerprint conflict
- `DeepPlanClientOperationError`: higher-level multi-step failure
- `DeepPlanHealthGateError`: optional write blocked by degraded storage health
- append-style operations can carry `idempotency_key` to safely dedupe retries

Default retry policy is conservative:

- automatic refresh-and-retry is enabled for `update_plan`
- `restore_revision` is also treated as safe overwrite-style retry
- append-style operations such as `add_evidence` and `replan` require `allow_non_idempotent_retry=True`
- when opt-in retry is enabled for append-style operations, the client injects an `idempotency_key` if one is missing
- generalized write flows can require healthy storage with `require_healthy=True`

## CLI

Main commands:

- `init`: create `.deeplan/` state files
- `plan`: create or overwrite core plan fields
- `replan`: append execution evidence and plan deltas
- `decide`: append a decision record
- `risk`: append a risk record
- `evidence`: append structured evidence
- `discover`: generate or apply a reference-discovery pass
- `hypothesis`: append structured hypothesis entries
- `qa`: run QA checks manually
- `validate`: validate plan structure and nested records
- `schema`: inspect or rewrite `schemas/plan.schema.json`
- `health`: print storage health and recovery diagnostics
- `maintenance`: inspect or apply bounded log maintenance
- `show`: print current plan summary
- `history`: print revision history
- `restore`: preview or restore a prior revision
- `ideate`: generate option seeds from lightweight context
- `insight`: generate viewpoint-expansion insight packs
- `review`: run cycle-based review with recommendations

Development checks:

```bash
make check
make test
make compile
make schema-check
```

## HTTP API

Start the local service:

```bash
python3 deepplan_server.py --host 127.0.0.1 --port 8787
```

Available endpoints:

- `GET /plan`: current plan, summary, validation, fingerprint
- `GET /qa`: QA report
- `GET /health`: storage health and recovery diagnostics
- `GET /cycle`: plan + QA + health + recent history snapshot
- `GET /history`: revision history
- `GET /validate`: structural validation
- `GET /tools`: agent tool schemas
- `POST /plan`: update plan fields
- `POST /evidence`: append one evidence item
- `POST /replan`: append plan deltas and rerun QA
- `POST /restore/preview`: preview restore target directly
- `POST /restore`: restore a revision directly
- `POST /tools/<tool_name>`: execute one tool wrapper
- `POST /agent/act`: map slash/natural-language input to a tool call

Example:

```bash
curl http://127.0.0.1:8787/cycle?limit=5
curl http://127.0.0.1:8787/plan
curl http://127.0.0.1:8787/qa
curl http://127.0.0.1:8787/health
curl http://127.0.0.1:8787/history
curl -X POST http://127.0.0.1:8787/plan \
  -H 'Content-Type: application/json' \
  -H 'If-Match: "<fingerprint-from-get-plan>"' \
  -d '{"goal":"Ship local agent layer"}'
curl -X POST http://127.0.0.1:8787/restore/preview \
  -H 'Content-Type: application/json' \
  -d '{"previous":true}'
```

## Agent Wrapper

The local wrapper exposes slash-style and lightweight natural-language control:

```bash
python3 deepplan_agent.py tools
python3 deepplan_agent.py run --input '/deepplan.show'
python3 deepplan_agent.py run --input '/deepplan.health'
python3 deepplan_agent.py run --input '/deepplan.history'
python3 deepplan_agent.py run --input '/deepplan.restore-preview revision_id=<revision-id>'
python3 deepplan_agent.py run --input 'preview previous revision'
python3 deepplan_agent.py run --input '/deepplan.plan goal="Ship local agent layer" planning_horizon="4 weeks" review_cadence=weekly'
python3 deepplan_agent.py run --input '/deepplan.replan evidence="Pilot retention improved" evidence_confidence=70 evidence_axis=market'
python3 deepplan_agent.py run --input '/deepplan.evidence claim="Repeated planning pain" source=interviews confidence=72 axis=market'
python3 deepplan_agent.py run --input 'show plan'
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

Tool responses use stable `ok`, `tool_name`, and `result_type` fields.

## Python Client

The repo includes a lightweight integration-facing client in `deepplan_sdk/`.

```python
from deepplan_sdk import (
    DeepPlanClient,
    DeepPlanClientOperationError,
    DeepPlanConflictError,
    DeepPlanHealthGateError,
)

client = DeepPlanClient.from_http("127.0.0.1", 8787)

cycle = client.get_cycle(history_limit=5)
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
    idempotency_key="pilot-friction-cycle-1",
)
```

Use the client when another repo needs DeepPlan as a planning kernel without re-implementing:

- stale-write handling
- refresh-and-retry policy
- post-write cycle snapshots
- restore preview / restore flows
- optional health-gated writes

See also:

- `docs/integration-agentscope.md`
- `docs/deepplan-agents-bootstrap.md`
- `examples/deepplan_kernel_adapter.py`
- `examples/deepplan_planner_host.py`
- `deepplan_client.py` remains as a compatibility import path

Install the SDK surface locally from this repo:

```bash
python3 -m pip install -e .
```

## Product Thesis

In the AI era, execution is increasingly commoditized.
Direction quality is not.

If planning is weak, faster execution only accelerates the wrong path.
DeepPlan exists to reduce that failure mode.

DeepPlan is `plan-only` by design:

- idea discovery
- direction setting
- planning logic
- success and failure criteria

It intentionally does not try to own execution orchestration or delivery automation.

## Planning Philosophy

Humans bring context from life, experience, and intent.
AI should improve thinking quality, not just generate tasks.

DeepPlan planning favors:

1. Strong references
2. Actionable insights
3. Audience interest detection
4. Need intensity detection
5. High information density
6. Multiple viewpoints

## First 10-Minute Outputs

For zero-idea or weakly formed ideas, DeepPlan should quickly produce:

1. Problem / user hypothesis
2. Three direction options with one explicit choice
3. A testable initial plan with metric, deadline, and first tasks

## Messaging Drafts

Slogans:

1. Plan is the product.
2. Decide what matters before AI builds it.
3. In the AI era, direction is alpha.

Short copy:

DeepPlan is a Plan Intelligence tool for the AI era.
Execution is cheap. Direction is expensive.
When you do not know what to build yet, DeepPlan helps turn ambiguity into a focused, testable, monetizable plan.
