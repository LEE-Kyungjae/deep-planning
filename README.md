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

- Shared plan format (`schemas/plan.schema.json`)
- CLI (`deepplan.py`)
- Minimal local HTTP service (`deepplan_server.py`)
- Agent wrapper + tool schema (`deepplan_agent.py`)
- Automatic quality checks on `plan` and `replan`
- Local state in `/.deeplan/`

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
python3 deepplan_agent.py tools
python3 deepplan_agent.py run --input '/deepplan.qa'
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
- `show`: print current plan summary
- `ideate`: generate plan ideas from lightweight user context and optionally apply one
- `insight`: generate viewpoint-expansion insight pack and optionally apply it
- `review`: run cycle-based planning review with recommendations and next questions
- `evidence`: add structured evidence linked to planning axes
- `hypothesis`: append testable hypothesis entries and optional test evidence

## HTTP Service

DeepPlan also exposes a minimal local HTTP service without external dependencies:

```bash
python3 deepplan_server.py --host 127.0.0.1 --port 8787
```

Available endpoints:

- `GET /health`: service health check
- `GET /plan`: full current plan + derived summary
- `GET /qa`: QA report as JSON
- `GET /tools`: available tool schemas for agent/tool callers
- `POST /plan`: update core plan fields using a JSON object
- `POST /evidence`: append one evidence item using JSON
- `POST /tools/<tool_name>`: run one tool with `{"input": {...}}`
- `POST /agent/act`: map slash/natural-language input to a tool call

Example:

```bash
curl http://127.0.0.1:8787/plan
curl http://127.0.0.1:8787/qa
curl http://127.0.0.1:8787/tools
curl -X POST http://127.0.0.1:8787/evidence \
  -H 'Content-Type: application/json' \
  -d '{"claim":"User pain repeated in interviews","source":"interview-notes","confidence":72,"axis":"market"}'
curl -X POST http://127.0.0.1:8787/tools/add_hypothesis \
  -H 'Content-Type: application/json' \
  -d '{"input":{"hypothesis":"Narrow segment returns weekly","metric":"weekly-active-pilot-users","target":">=20","window":"14 days"}}'
curl -X POST http://127.0.0.1:8787/agent/act \
  -H 'Content-Type: application/json' \
  -d '{"input":"/deepplan.evidence claim=\"Repeated pain in interviews\" source=interviews confidence=75 axis=market"}'
```

## Agent Wrapper

DeepPlan now includes a local wrapper for slash-style and lightweight natural-language control:

```bash
python3 deepplan_agent.py tools
python3 deepplan_agent.py run --input '/deepplan.show'
python3 deepplan_agent.py run --input '/deepplan.plan goal="Ship local agent layer" planning_horizon="4 weeks" review_cadence=weekly'
python3 deepplan_agent.py run --input '/deepplan.evidence claim="Repeated planning pain" source=interviews confidence=72 axis=market'
python3 deepplan_agent.py run --input 'show plan'
python3 deepplan_agent.py run --input 'qa'
```

Supported slash commands:

- `/deepplan.plan`
- `/deepplan.show`
- `/deepplan.qa`
- `/deepplan.evidence`
- `/deepplan.hypothesis`

## Slash Command Mapping

If your agent supports slash commands, map them to CLI:
- `/deepplan` -> `python3 deepplan.py plan ...`
- `/deepplan.replan` -> `python3 deepplan.py replan ...`
- `/deepplan.decide` -> `python3 deepplan.py decide ...`
- `/deepplan.risk` -> `python3 deepplan.py risk ...`
- `/deepplan.qa` -> `python3 deepplan.py qa`

## Storage

- `/.deeplan/plan.json`
- `/.deeplan/decisions.jsonl`
- `/.deeplan/risks.jsonl`
- `/.deeplan/events.jsonl`

This is intentionally minimal and meant to be used by AI agents (Codex/Claude Code) as a common local planning primitive.
