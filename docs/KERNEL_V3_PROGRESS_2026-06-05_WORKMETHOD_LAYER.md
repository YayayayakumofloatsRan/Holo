# Kernel v3 WorkMethod Layer

Date: 2026-06-05

## Purpose

This iteration adds a WorkMethod layer between semantic task understanding and
the existing host-owned loop. The goal is not to add another controller. The
goal is to give each task a compact, model-shapable work packet that says:

- what work is being attempted;
- what output shape and done criteria matter;
- what tool and memory surfaces are relevant;
- what the thread working set already contains;
- what failure moves should be tried before asking the user or stopping.

This helps the planner/evaluator loop carry human-like work continuity without
hard-coding finance, math, physics, or any other domain as fixed scripts.

## Added

- `kernel_v3/workmethod/contracts.py`
  - `WorkFrame`
  - `WorkMethod`
  - `ThreadWorkingSet`
  - `WorkGapAssessment`
  - `StrategyShift`
  - `WorkMethodState`
- `kernel_v3/workmethod/supervisor.py`
  - rule fallback framing;
  - optional model-backed `workmethod.frame`;
  - optional model-backed `workmethod.gap`;
  - structured strategy-shift proposals from run deltas.
- `kernel_v3/workmethod/memory.py`
  - journal/thread-derived working-set construction;
  - successful findings, failed attempts, open gaps, user preferences, and trace refs.
- `kernel_v3/workmethod/prompts.py`
  - schema-first prompt contracts for frame and gap assessment.

## Runtime Integration

- `AgentRuntime` now creates a `workmethod_state` before building the task
  recipe and journals it after the loop creates the real `task_id/run_id`.
- `ContextBundle.state` now exposes compact `workmethod` context to the model
  planner/evaluator path.
- `_planner_directive()` now carries the same compact workmethod packet for all
  modes.
- `MissionSupervisor` now journals `work_gap_assessment` and, when needed,
  `strategy_shift` after each task run. If a mission continues, the next
  `mission_directive` is enriched with the strategy shift so the following
  planner call sees what to avoid and what method to try next.

## Provider Routing

New processor task types were added:

- `workmethod.frame`
- `workmethod.gap`

DeepSeek v4 routing includes both task types. In deterministic/fake tests,
WorkMethod stays on the rule fallback by default so it does not disturb older
fake-provider prompt capture. In live DeepSeek/OpenAI-compatible runs, the
workmethod packets are model-backed unless explicitly overridden.

`holo-v3 model-packet --task-type workmethod.frame` and
`holo-v3 model-packet --task-type workmethod.gap` show the exact redacted packet
shape without performing a network call.

## Host Boundaries

- WorkMethod does not execute tools.
- WorkMethod does not authorize policy.
- WorkMethod does not write durable memory.
- WorkMethod does not replace `LoopControllerV3`.
- Strategy shifts are hints carried into the next planner context; the normal
  host path still validates planner action packets through `PolicyGate` and
  `ToolRegistry`.

## Verification

Deterministic:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase117_workmethod_layer.py
.venv/bin/python -m pytest -q tests/test_kernel_v3*.py
```

Result:

```text
5 passed in tests/test_kernel_v3_phase117_workmethod_layer.py
710 passed in 73.71s for tests/test_kernel_v3*.py
```

Live smoke:

```bash
HOLO_V3_LIVE_MODEL=1 ./holo-v3 model-smoke --provider deepseek --model deepseek-v4-flash --thinking disabled
./holo-v3 chat --thread smoke-workmethod --once '一句话介绍你是谁' --output human --online --profile fast --thinking disabled --max-agent-steps 3 --no-live-retrieval
```

The live chat path called:

- `chat.route`
- `semantic.intake`
- `workmethod.frame`
- `planner.propose`
- `evaluator.assess`
- `mission.assess`
- `workmethod.gap`

and completed with a final answer.
