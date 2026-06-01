# Holo Kernel v3

Holo Kernel v3 is the active branch of this repository: a host-owned agent
harness where models propose structured decisions and the host validates,
executes, journals, and verifies every state transition.

This branch is intentionally separate from the older `holo_host` stage line.
Historical stage documents and legacy runtime code remain in the repository for
reference only. New kernel work should start from `kernel_v3/`,
`tests/test_kernel_v3_*.py`, `docs/KERNEL_V3_*.md`, and `AGENTS.md`.

## Active Kernel

- `kernel_v3/`: current host-owned agent harness.
- `kernel_v3/loop.py`: generic `LoopControllerV3`; it must stay
  tool-name-agnostic.
- `kernel_v3/agent/`: single-agent runtime, task recipes, semantic task graph,
  workloop termination, and final answer/failure report assembly.
- `kernel_v3/chat/`: multi-turn thread runtime, routing, pending user input,
  journal-derived summaries, and memory admin surfaces.
- `kernel_v3/processors/`: schema-first processor fabric, fake providers,
  optional live model providers, JSON repair, routing, usage, and adapters.
- `kernel_v3/retrieval/`: bounded retrieval FSM, evidence, citations, corpus
  providers, optional live HTTP provider surfaces, and source inspection.
- `kernel_v3/memory/`: durable memory contracts, store, privacy checks,
  proposal pipeline, projection, migration, and inspection.
- `kernel_v3/resident/`: local resident queue, scheduler, runtime, projection,
  and doctor checks.
- `kernel_v3/research/`: research profiles, local corpus, and source policy for
  domain-directed retrieval.

## Hard Invariants

- The model proposes; the host validates, executes, records, and verifies.
- Journal is the source of truth for task execution and thread continuity.
- Tools never execute without `PolicyGate` validation.
- `LoopControllerV3` must not dispatch by concrete tool/provider names.
- Raw fetched bodies and large payloads belong in `ArtifactStore`, not journal
  or model-visible context.
- Durable memory is host-controlled: model output may propose memory, but it
  cannot directly commit memory.
- No live WeChat or other transport integration belongs inside `kernel_v3`.
- Unit tests must not require API keys, live models, or live network access.

## Current Capability Snapshot

Kernel v3 currently contains the infrastructure for:

- bounded planner -> policy -> tool -> evaluator loops;
- workloop progress, repetition, evidence sufficiency, and termination
  decisions;
- direct, retrieval-grounded, workspace-grounded, clarification, and failure
  flows;
- multi-turn chat over journal-derived thread state;
- optional model-backed semantic intake, planner, evaluator, synthesizer, and
  chat routing;
- bounded retrieval with evidence/citation reports and source quality policy;
- durable-memory proposals, approval/rejection, recall, deletion, export, and
  context injection;
- local resident inbox/outbox, leases, schedules, and audit/doctor surfaces;
- finance-fundamentals research profile and local corpus-backed retrieval.

Live model and live retrieval surfaces are opt-in. They are not default unit-test
dependencies.

## Legacy Boundary

The following paths are legacy or historical unless a task explicitly says
otherwise:

- `holo_host/`
- `holo_memory_library/`
- `windows_helper/`
- `docs/ENGINEERING_HANDOFF_STAGE*.md`
- `docs/STAGE*.md`
- old acceptance commands such as `accept-stage*`

Do not use those files to infer the current kernel v3 architecture. They may be
useful for historical comparison, but they are not the active implementation
surface for this branch.

## CLI Entry Points

Run from the repository root:

```bash
python3 holo-v3 tools
python3 holo-v3 agent "explain kernel v3" --mode direct
python3 holo-v3 chat --thread demo --once "what can you do?"
python3 holo-v3 providers
python3 holo-v3 provider-smoke --fake
python3 holo-v3 retrieve "sample topic"
python3 holo-v3 memory inspect --memory-log kernel_v3/.holo-v3-memory.jsonl
python3 holo-v3 resident status
```

Live model calls are gated:

```bash
HOLO_V3_LIVE_MODEL=1 python3 holo-v3 model-packet --provider deepseek --task-type semantic.intake --goal "search today's news" --show-prompt
```

Interactive model-backed runs default user-visible text to Chinese when the user
does not clearly request another language. Override this per run with
`--response-language en` or set `HOLO_V3_RESPONSE_LANGUAGE=en`.

```bash
HOLO_V3_LIVE_MODEL=1 python3 holo-v3 agent "read README.md and summarize it" --online --response-language zh
```

Live retrieval is also explicit and host-allowlisted. Do not make network
retrieval a default path.

## Validation

Default validation should stay offline:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_*.py
```

Targeted smoke commands:

```bash
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase5_semantic_processors.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase61_workloop.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase62_chat_runtime.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase7_memory_store.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase71_memory_pipeline.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase73_resident_runtime.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase87_research_profile_runtime.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase92_agent_live_retrieval_permission.py
```

Optional live checks must be explicitly gated by environment variables and must
not be required by CI or default test runs.

If `.venv/` is absent, create one and install `pytest`, then run the same
commands through that interpreter.

## Thread Handoff

When continuing this work in a new thread, start here:

1. Confirm branch and scope:

   ```bash
   git status --short --branch
   rg --files | rg '(^kernel_v3/|^tests/test_kernel_v3|^docs/KERNEL_V3_|^AGENTS.md$|^README.md$)'
   ```

2. Read these first:

   - `AGENTS.md`
   - `docs/KERNEL_V3_AGENT_LOOP.md`
   - `docs/KERNEL_V3_PHASE7_PLAN.md`
   - `docs/KERNEL_V3_RESEARCH_SOURCE_POLICY.md`
   - `kernel_v3/loop.py`
   - `kernel_v3/agent/runtime.py`
   - `kernel_v3/processors/contracts.py`
   - `kernel_v3/tools.py`
   - `kernel_v3/policy.py`

3. Treat the following as non-negotiable:

   - no direct tool execution from model output;
   - no model writes to journal or durable memory;
   - no concrete tool-name branches inside `LoopControllerV3`;
   - no live network/model dependency in offline tests;
   - no WeChat/live transport work inside kernel v3;
   - no secret/API-key values in journal, context, trace, artifacts, or docs.

4. If a request references "stage" history, clarify whether it means legacy
   `holo_host` stages or current kernel v3 phases before editing code.

## Public Versus Private Files

Tracked public templates:

- `.subject.example.md`
- `holo_memory_library/subject_seed.example.md`
- `holo_memory_library/voice_profile.example.md`

Local/private deployment files:

- `.subject.local.md`
- `holo_memory_library/subject_seed.md`
- `holo_memory_library/voice_profile.md`
- `.holo_runtime/`
- `holo_memory_library/memories/*.jsonl`
- `artifacts/`
- `windows_helper/wechat_helper.live.json`

Before publishing broad repository changes, run the release hygiene checks if
that legacy release surface is in scope:

```bash
.venv/bin/python scripts/check_public_release_hygiene.py
.venv/bin/python -m pytest -q tests/test_public_release_hygiene.py
```

For kernel v3-only changes, prioritize the `tests/test_kernel_v3_*.py` suite and
the invariants above.
