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
  semantic state profiles, workloop termination, and final answer/failure
  report assembly.
- `kernel_v3/capabilities.py`: host-visible capability/state catalog spanning
  conversation, roleplay, document/report work, workspace, retrieval, web
  research, finance, memory, artifact, data, code, project, resident,
  transport, calendar, system, and security capabilities.
- `kernel_v3/chat/`: multi-turn thread runtime, routing, pending user input,
  journal-derived summaries, and memory admin surfaces.
- `kernel_v3/processors/`: schema-first processor fabric, fake providers,
  optional live model providers, JSON repair, routing, usage, and adapters.
- `kernel_v3/retrieval/`: bounded retrieval FSM, evidence, citations, corpus
  providers, direct URL/source-directory/query-template/crawl/SEC EDGAR
  structured search providers, optional live HTTP provider surfaces, and source
  inspection.
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
- semantic research plans that can expand one model-proposed `retrieval.run`
  capability into multiple ordered retrieval actions from
  `metadata.capability_args["retrieval.run"]` payload arrays, so one LLM packet
  can drive multi-subtopic research while each retrieval remains host-validated;
- run-level planned retrieval coverage: for multi-subtopic research, Holo
  tracks the latest retrieval report for each host-planned `goal-plan-*`
  subgoal and refuses to finalize if any subgoal remains missing or
  insufficient;
- explicit multi-query retrieval payloads: when a model/host payload supplies
  `queries` or `query_templates`, Holo derives a safe default `max_queries` from
  that list so one retrieval subgoal can run multiple bounded search attempts
  without the model needing to guess budget fields;
- model-planner dynamic loops that recompile context, re-call
  `planner.propose`, journal plan revisions, and continue for 10+ bounded
  iterations when evaluator feedback says more work remains;
- non-workspace profile capabilities such as `finance.fundamentals_research`,
  which compile to host-validated retrieval with the finance fundamentals
  source policy instead of collapsing into workspace mode;
- a broader semantic capability/state surface for Hermes-style growth:
  roleplay/persona, document/report/email drafting, artifact generation,
  web/market research, finance competitive landscape, legal/contract,
  medical-information, education, creative, communication, operations,
  product, risk/compliance, cybersecurity-review, data/table analysis,
  code/test work, project/task status, calendar/reminder intent, transport
  boundaries, credential/secret boundaries, browser/session boundaries, and
  device-control boundaries are represented explicitly even when they are
  only planned or host-only;
- planner-visible semantic state axes beyond workspace, including autonomy,
  world model, resource kind, action phase, temporal status, source authority,
  identity boundary, communication channel, and risk;
- Hermes-style operating-state axes are now first-class planner/context
  vocabulary, not executable tools: goal structure, dependency state,
  commitment state, preference state, memory scope, planning depth, operation
  runtime, quality bar, and interruption policy let model packets describe
  broad agent work without collapsing everything into `workspace:*`;
- per-intent semantic state profiles in the task graph. Each node now carries
  host-visible `domain`, `activity`, `resource`, `execution_surface`,
  `permission_state`, `route_class`, capability families/statuses, evidence
  posture, output contract, autonomy, risk posture, and expandable
  `state_axes`, so broad model packets preserve finance, legal, medical,
  education, communication, operations, product, risk, cybersecurity,
  database, cloud, workflow, knowledge-base, multimodal, resident, transport,
  calendar, system, and security state without pretending those categories
  are executable tools;
- runtime state-profile projection: every agent task journals
  `agent_state_profile`, and planner context exposes top-level
  `semantic_state_profiles` plus `semantic_state_profile_summary`. This keeps
  non-workspace state such as database, cloud, multimodal, calendar, security,
  resident, transport, and finance visible to model planning and host audit
  without making planned/host-only categories executable;
- multi-turn chat over journal-derived thread state;
- optional model-backed semantic intake, planner, evaluator, synthesizer, and
  chat routing;
- bounded retrieval with evidence/citation reports and source quality policy;
- bounded crawl discovery now ranks discovered page/sitemap candidates against
  the query before applying the source budget, so limited fetch budgets prefer
  relevant research pages over generic navigation links;
- text-based PDF retrieval extraction for official reports and exchange
  disclosures: raw PDF bodies remain artifacts, while readable PDF string
  literals become evidence spans; scanned/OCR-only PDFs remain insufficient
  evidence until a future OCR tool is configured;
- structured JSON/CSV retrieval extraction for financial databases such as SEC
  companyfacts, FRED, and Treasury/FiscalData-style responses: raw payloads
  remain artifacts, while flattened rows/fields become readable evidence spans;
- durable-memory proposals, approval/rejection, recall, deletion, export, and
  context injection;
- local resident inbox/outbox, leases, schedules, and audit/doctor surfaces;
- finance-fundamentals research profile and local corpus-backed retrieval.
- model-planner retrieval binding that applies host-validated research profile
  defaults from semantic intake/task plans before tool execution;
- retrieval workloop feedback that carries missing query facets and missing
  source-authority signals into the next planner packet, allowing bounded
  replan attempts without weakening host termination guards;
- planner-visible `agent_replan_hints` compiled from journal records after
  insufficient retrieval. The packet carries missing facets/source authority,
  attempted query/strategy/provider summaries, payload hashes to avoid
  repeating, suggested next search strategies/query hints, ranked
  source-directory targets for profiled research, and `do_not_finalize_until`
  rules for the next model planner call;
- dynamic planner retries for planned retrieval subgoals: semantic task plans
  can declare multiple `goal-plan-*` retrieval subgoals, and
  `agent_replan_hints` reports incomplete subgoal ids even when the latest
  retrieval report itself was sufficient, allowing the model planner to retry
  only the failed subgoal before finalization;
- planner-visible `agent_retrieval_plan_state`, which exposes planned
  retrieval subgoals, pending/complete/incomplete goal ids, latest report
  status by goal id, and the next recommended `goal_id` for model planner
  packets;
- adaptive search strategy selection for retrieval: when configured, a model
  planner can propose `metadata.search_strategy` values such as `corpus_only`,
  `fresh_live`, `aggregate`, `structured`, or `crawl`, and the host selects only
  among configured providers under existing policy and fetch allowlists;
- live retrieval/corpus bridging: when corpus and artifact logs are configured,
  Holo searches the local research corpus before live providers, fetches corpus
  hits from artifact blobs, and indexes newly fetched live pages back into the
  corpus for later agent loops;
- finance fundamentals source directory entries for SEC/EDGAR, SEC structured
  data, SEC CIK/ticker mapping, SEC archives, SEC financial statement datasets,
  company IR, US/global official statistics, China/HK/UK/Canada/Australia/Japan/
  Singapore disclosure portals, and secondary market sources.
- SEC EDGAR structured source generation for finance fundamentals. Given a
  ticker, CIK, or injected ticker-to-CIK map, Holo can generate official SEC
  submissions, companyfacts, EDGAR search, browse, and ticker-directory
  candidates without doing network search itself.
- SEC Archives filing-document candidate generation. When a host/model
  retrieval payload carries CIK plus accession number and optional
  `primaryDocument`, Holo derives the official primary filing document,
  complete submission text, and filing directory URLs before generic SEC
  browse/search candidates, while rejecting unsafe document names.
- Template-driven official source-query expansion for finance fundamentals.
  Source directory entries can declare safe `query_url_templates`; Holo renders
  them from host metadata such as company, ticker, metric, and query, validates
  the resulting host against the entry allowlist, and only then exposes them as
  retrieval candidates.
- Host-owned issuer identity resolution for finance retrieval. Ticker, SEC CIK,
  company/issuer names, and selected exchange codes are normalized once and
  reused by SEC EDGAR and source-query providers instead of being guessed
  independently inside each provider.
- Non-US official disclosure entry points for finance retrieval, including
  CNINFO, HKEX, ASX, EDINET, and SGX source-query templates. These remain
  candidate source URLs; network fetch still requires explicit host allowlists.

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
  finance fundamentals without fetching anything by itself. It ranks directory
  entries against the query plus task metadata such as `research_task_kind`,
  preferred source families, and source-authority requirements before applying
  the source budget, so market-news tasks prefer reputable-news entry points,
  market-data tasks prefer quote/data portals, and macro/rate tasks prefer
  official statistics, central-bank, or Treasury entries;
- `sec_edgar_structured_search` generates official SEC EDGAR, submissions,
  companyfacts, and ticker-directory candidates for finance fundamentals from
  host-supplied ticker/CIK metadata or an injected ticker-to-CIK map; it performs
  no network request by itself;
- `research_source_query_search` expands curated source-directory
  `query_url_templates` into official search URLs, such as Companies House
  company search and FRED series search, after placeholder and host validation.
  It ranks rendered template candidates with the same query/task-aware source
  directory scoring before applying `max_sources`, so a tight-budget market
  news or market-data run does not lose the right search URL to an earlier
  generic template that merely echoed the query;
- source-directory-driven crawl can be enabled explicitly with
  `HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY=1` plus
  `HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST=1`. In that mode the crawler can use
  curated finance source-directory base URLs and `crawl_seed_urls` as bounded
  discovery seeds, while fetches still go through the host HTTP provider,
  allowlists, artifact storage, evidence checks, and loop guards;
- the finance source directory also exposes common secondary market-data and
  reputable-news entry points such as Yahoo Finance quote/lookup, Nasdaq market
  activity, MarketWatch stock pages, Reuters search, Bloomberg search, Financial
  Times search, and CNBC search. It now also includes central-bank data portals,
  US Treasury/FiscalData, fund/ETF disclosure entry points, earnings-call
  transcript aggregators, and credit-rating agency search entry points. These
  are source pointers, not cached financial content. Transcript, rating, news,
  and market-data sources remain secondary evidence unless paired with primary
  filings, issuer materials, official statistics, central-bank data, Treasury
  data, or fund disclosures;
- configured JSON HTTP search providers can sit in the same fallback chain.
- `aggregate_search` can be enabled for live retrieval to collect candidates
  from multiple providers, rank them by query relevance and source authority,
  and only then apply the source budget. This is useful for longer research
  loops where a generic first provider should not prevent later primary or
  corpus sources from being considered.
- `adaptive_search` can be enabled with
  `HOLO_V3_LIVE_SEARCH_STRATEGY=adaptive`. In that mode the planner may propose
  a per-action `metadata.search_strategy` such as `corpus_only`, `fresh_live`,
  `aggregate`, `structured`, or `crawl`. This is a provider selector, not a
  permission grant.
- if `--corpus-log`/`--corpus-index` and an artifact log are configured, the
  same live operator becomes cache-first: `research_corpus` is searched before
  live providers, corpus hits are fetched from artifact blobs, and new live
  fetches are written back to the corpus.

For crawl-only live inspection:

```bash
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_CRAWL_SEED_URLS=https://api-docs.deepseek.com/ \
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api-docs.deepseek.com \
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=api-docs.deepseek.com \
python3 holo-v3 retrieval-providers --mode live-http
```

For finance-profile crawl seeded by the curated source directory:

```bash
HOLO_V3_LIVE_RETRIEVAL=1
HOLO_V3_LIVE_SEARCH_STRATEGY=adaptive
HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY=1
HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST=1
HOLO_V3_LIVE_CRAWL_MAX_SOURCE_DIRECTORY_SEEDS=4
```

For multi-provider research, set:

```bash
HOLO_V3_LIVE_SEARCH_STRATEGY=aggregate
HOLO_V3_LIVE_SEARCH_MAX_SOURCES_PER_PROVIDER=3
```

The default remains `fallback` to preserve narrow live-smoke behavior.

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
generic search endpoint is needed. When the intent carries company or macro
metadata, template-backed source-directory entries can generate official
Companies House, FRED, and World Bank query URLs without hard-coding agent
branches. Multi-intent finance plans can therefore execute multiple retrieval
loop actions before finalization while preserving host-owned source ranking,
artifact storage, evidence sufficiency, and termination gates.
When a prior SEC submissions/company metadata step exposes an accession number
and `primaryDocument`, the next retrieval payload can carry those fields and
the SEC provider will construct the direct `Archives/edgar/data/...` filing
document URL. This lets a fundamentals loop move from metadata discovery to
the original 10-K/10-Q filing body without asking the model to invent SEC path
rules. The agent also derives `agent_replan_hints.retrieval.suggested_filing_documents`
from journaled SEC submissions extraction spans, so a live planner can see a
host-built suggested payload for the next `retrieval.run` without reading raw
artifact bodies or bypassing PolicyGate.
Market-news, market-data, and competitive-landscape finance intents use the
same profile directory but set a different source authority requirement:
secondary-or-better sources can satisfy those tasks, while fundamentals still
require primary sources. The retrieval report records that requirement in
diagnostics so an operator can see why a Reuters/Yahoo-style result was
accepted for news/market context but would not satisfy a primary filing claim.
Issuer identity normalization is still offline and deterministic: it can use
host metadata, query text, and injected ticker-to-CIK maps, but it does not call
external services or claim that an unresolved company has been verified.
SEC source expansion is intentionally scoped to SEC/EDGAR/10-K/10-Q style
queries, so generic "annual report" language for ASX/HKEX/SGX issuers does not
silently route to EDGAR.

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
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase99_source_query_provider.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase100_issuer_identity.py
```

Optional live checks must be explicitly gated by environment variables and must
not be required by CI or default test runs.

Live finance smoke, gated and non-default:

```bash
HOLO_V3_LIVE_FINANCE=1 \
HOLO_V3_LIVE_MODEL=1 \
.venv/bin/python -m pytest -q tests/live/test_kernel_v3_phase101_live_finance_retrieval.py
```

This uses the optional DeepSeek provider plus SEC structured retrieval/fetch
allowlists inside the test. It validates the real model-packet path, host
network budget, SEC artifact-backed evidence, citation-gated finalization, and
secret redaction.

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
