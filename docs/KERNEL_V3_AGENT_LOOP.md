# Kernel v3 Agent Loop Notes

Kernel v3 is a host-owned single-agent harness. The model may propose,
evaluate, or synthesize, but the host validates policy, executes tools,
journals every transition, checks evidence, and decides when to stop.

## Current Loop

One agent task runs through this chain:

1. compile context from journal
2. planner proposes one `CandidateAction`
3. `PolicyGate` validates the action and tool manifest
4. `ToolRegistry` executes only allowed actions
5. evaluator returns feedback
6. `WorkloopEvaluator` derives progress, repetition, evidence sufficiency,
   and a host-owned termination decision
7. `StopController` and loop guards stop, continue, ask the user, or fail
8. final answer or failure report is journaled

`LoopControllerV3` remains tool-name-agnostic. Concrete flows such as
retrieval and workspace answering are configured by recipes, registries, and
operators outside the controller.

## Semantic Task Graph

Model-backed semantic intake is now normalized into a host-visible
`TaskGraphProposal` before an agent recipe is selected. This graph is not an
execution engine. It is an audit and validation layer over the model's proposed
semantic structure:

- each proposed task node carries kind, goal, dependencies, capabilities,
  evidence requirements, and a suggested recipe mode;
- the host validates blocked capabilities, dependency integrity, node limits,
  and whether user confirmation is required;
- `AgentRuntime` journals `semantic_task_graph` with both the proposal and the
  validation decision;
- `LoopControllerV3` still receives only the selected recipe, planner,
  PolicyGate, registry, and evaluator. It remains tool-name-agnostic.

This is the anti-table path for compound and open-ended requests. The fake
semantic fallback stays conservative, while model mode can propose broad task
structure through JSON and the host validates it before anything runs.

## Stop Semantics

The agent stops when one of these host-visible conditions is reached:

- sufficient evidence exists and evaluator feedback is terminal
- citations are required but missing and no allowed action can repair them
- the same action/query/path/observation/missing-evidence/failure repeats
- consecutive steps make no host-derived progress
- user input is required
- policy or resource guards block continuation
- loop limits are reached: steps, tool calls, network fetches, artifact bytes,
  or duration

Model feedback is never the only stop authority. It is combined with host
progress signals, repetition detection, evidence checks, and loop guards.

## Run Scope

Multi-turn and resumed tasks may share one task id, but each resume creates a
new run id. Runtime decisions that can affect completion are run-scoped:

- evidence sufficiency reads only current-run evidence, citations, and file
  observations
- retrieval and workspace finalization use only current-run grounding
- failure reports list current-run attempted actions, sources, missing
  evidence, and last observations
- repetition and no-progress counters are isolated per run
- recipe action ids are bound to the current run to avoid trace collisions

This prevents a later failed resume from completing with stale evidence from an
earlier successful run.

## Chat And Resident Model Path

`ChatRuntime` and the resident worker are routing shells around
`AgentRuntime`; they are not separate decision layers. They can now pass the
same Phase5 execution modes used by `holo-v3 agent`:

- `planner_mode`
- `evaluator_mode`
- `synthesizer_mode`
- `semantic_mode`

The default remains fully offline fake mode. CLI model modes for `holo-v3 chat`
and `holo-v3 resident run/run-once` are gated by `HOLO_V3_LIVE_MODEL=1`, then
use the configured provider fabric. This lets a resident worker use model-backed
semantic intake or planner/evaluator/synthesizer behavior without letting the
worker execute tools directly, bypass PolicyGate, or become a transport-level
decision maker.

## Iteration 2026-05-31

Hardening completed in this iteration:

- blocked model `semantic.intake.response_hint` from becoming a final answer
- made repetition and no-progress detection run-scoped
- made evidence sufficiency and finalization grounding run-scoped
- made failure report attempt/observation summaries run-scoped
- bound recipe action ids to run ids
- added regression tests for stale retrieval evidence, stale workspace file
  reads, and semantic-intake answer leakage

Validation used:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_kernel_v3*.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q kernel_v3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_public_release_hygiene.py -q -p no:cacheprovider
git diff --check
```
