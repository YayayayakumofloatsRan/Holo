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
- `kernel_v3/capabilities.py`: host-visible capability/state catalog spanning
  conversation, workspace, retrieval, finance, memory, resident, transport,
  and system capabilities.
- `kernel_v3/chat/`: multi-turn thread runtime, routing, pending user input,
  journal-derived summaries, and memory admin surfaces.
- `kernel_v3/processors/`: schema-first processor fabric, fake providers,
  optional live model providers, JSON repair, routing, usage, and adapters.
- `kernel_v3/retrieval/`: bounded retrieval FSM, evidence, citations, corpus
  providers, direct URL/source-directory/crawl/SEC EDGAR structured search
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
- workspace write flows with manifest validation and journal redaction of raw
  file bodies;
- non-workspace system-state flows such as `system.time`, where the model
  proposes a host capability and the host reads the current time;
- semantic work plans that can expand one model-proposed capability into many
  ordered tool actions, including 10+ iteration workspace loops;
- non-workspace profile capabilities such as `finance.fundamentals_research`,
  which compile to host-validated retrieval with the finance fundamentals
  source policy instead of collapsing into workspace mode;
- multi-turn chat over journal-derived thread state;
- optional model-backed semantic intake, planner, evaluator, synthesizer, and
  chat routing;
- bounded retrieval with evidence/citation reports and source quality policy;
- durable-memory proposals, approval/rejection, recall, deletion, export, and
  context injection;
- local resident inbox/outbox, leases, schedules, and audit/doctor surfaces;
- finance-fundamentals research profile and local corpus-backed retrieval.
- finance fundamentals source directory entries for SEC/EDGAR, SEC structured
  data, SEC CIK/ticker mapping, SEC archives, SEC financial statement datasets,
  company IR, US/global official statistics, China/HK/UK/Canada/Australia/Japan/
  Singapore disclosure portals, and secondary market sources.
- SEC EDGAR structured source generation for finance fundamentals. Given a
  ticker, CIK, or injected ticker-to-CIK map, Holo can generate official SEC
  submissions, companyfacts, EDGAR search, browse, and ticker-directory
  candidates without doing network search itself.

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
python3 holo-v3 agent "what time is it in UTC?" --mode system
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

Live agent/chat/resident runs expose both input/context and output-generation
controls. `--context-profile large` is the default for live interactive runs;
`huge` and `provider` allow much larger host prompt budgets when the target
model can handle them. `--max-output-tokens provider` omits the provider
`max_tokens` field, while `auto` uses Holo's route defaults and an integer sets
an explicit output cap.
Generation defaults to host-adaptive mode: `--generation-mode auto` adjusts
thinking, reasoning effort, temperature, and timeout from the processor task,
prompt size, and `--latency-target fast|balanced|quality|thorough`. Use
`--generation-mode manual` or explicit `--thinking/--temperature` overrides
when a run needs fixed generation behavior.
Tool calls remain host-validated after model planning: every tool payload is
checked against the tool manifest schema before execution, and workspace search
is bounded to preview matches so a bad query cannot exhaust the loop's artifact
budget before a follow-up `file.read`.
The current DeepSeek V4 router defaults to provider output-token limits for live
interactive routes, so Holo does not clamp capable long-context models unless
the operator explicitly passes an integer `--max-output-tokens`.

```bash
HOLO_V3_LIVE_MODEL=1 python3 holo-v3 agent "inspect a large workspace file" \
  --online \
  --context-profile huge \
  --latency-target thorough \
  --max-output-tokens provider \
  --temperature 0.2
```

Live retrieval is also explicit and host-allowlisted. Do not make network
retrieval a default path.

The live retrieval chain is now broader than a single search endpoint:

- `direct_url_search` extracts safe user/host supplied URLs without network
  access;
- `bounded_crawl_search` can discover links from explicit seed URLs only when
  `HOLO_V3_LIVE_RETRIEVAL=1`, crawl seeds, and host allowlists are configured;
  it can also inspect same-host `sitemap.xml` within bounded limits;
- `research_source_directory_search` exposes domain source directories such as
  finance fundamentals without fetching anything by itself;
- `sec_edgar_structured_search` generates official SEC EDGAR, submissions,
  companyfacts, and ticker-directory candidates for finance fundamentals from
  host-supplied ticker/CIK metadata or an injected ticker-to-CIK map; it performs
  no network request by itself;
- configured JSON HTTP search providers can sit in the same fallback chain.

For crawl-only live inspection:

```bash
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_CRAWL_SEED_URLS=https://api-docs.deepseek.com/ \
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api-docs.deepseek.com \
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=api-docs.deepseek.com \
python3 holo-v3 retrieval-providers --mode live-http
```

For a model-backed live retrieval run, the model still only proposes
`retrieval.run`. The host binds execution metadata such as `max_fetches`,
`max_network_fetches`, research profile, and allowlisted network permission
before `PolicyGate` and loop guards see the action:

```bash
HOLO_V3_LIVE_MODEL=1 \
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_CRAWL_SEED_URLS=https://api-docs.deepseek.com/ \
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api-docs.deepseek.com \
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=api-docs.deepseek.com \
python3 holo-v3 agent "上网检索DeepSeek API文档，概括模型和鉴权方式" \
  --mode retrieval \
  --online \
  --planner model \
  --evaluator model \
  --synthesizer model \
  --live-retrieval \
  --live-max-network-fetches 2
```

Current live crawl is intentionally basic: it can prove the loop, permissions,
artifact storage, evidence, citations, and synthesis path. It now strips
script/style/head/nav/header/footer markup before evidence extraction, so
journaled spans prefer readable page body while raw fetched HTML remains in
`ArtifactStore`. Richer web search APIs, deeper readability heuristics, and
finance-specific source adapters are still the next capability layer.

Retrieval sufficiency is stricter than "any citation exists". The retrieval
evaluator derives explicit query facets such as model, authentication, pricing,
token, endpoint, and rate limits, then requires extracted evidence to cover the
requested facets before the workloop may finalize. Missing facets are journaled
in `retrieval_evaluation_decision`, `retrieval_report`, `evidence_sufficiency`,
and the next planner feedback.

Recent live smoke, using real DeepSeek model calls and real
`api-docs.deepseek.com` crawling, completed this path:

```bash
HOLO_V3_LIVE_MODEL=1 \
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_CRAWL_SEED_URLS=https://api-docs.deepseek.com/ \
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api-docs.deepseek.com \
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=api-docs.deepseek.com \
python3 holo-v3 agent "上网检索DeepSeek API文档，说明模型和鉴权方式" \
  --mode retrieval \
  --online \
  --planner model \
  --evaluator model \
  --synthesizer model \
  --semantic-intake model \
  --live-retrieval \
  --live-max-network-fetches 4 \
  --thinking enabled \
  --reasoning-effort high \
  --temperature 0.2 \
  --max-output-tokens provider
```

The journal for that run showed `processor_request`/`processor_result` with
usage, bounded crawl/fetch artifacts, evidence/citations, evidence sufficiency,
termination decision, and final answer. API keys were not written to journal.

Financial fundamental research is represented as a profile capability rather
than a hard-coded domain branch. A model can propose
`finance.fundamentals_research`; the host compiles that into `retrieval.run`
with the `finance_fundamentals` research profile, source directory context, and
primary-source policy. When the intent carries SEC identifiers, the live
retrieval fallback chain also contributes structured EDGAR candidates before any
generic search endpoint is needed. Multi-intent finance plans can therefore
execute multiple retrieval loop actions before finalization while preserving
host-owned source ranking, artifact storage, evidence sufficiency, and
termination gates.

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
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase93_workspace_write_agent.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase94_capability_space_and_long_loop.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase95_retrieval_crawl_provider.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase98_sec_edgar_provider.py
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
