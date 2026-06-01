# Kernel v3 Progress 2026-06-02: Agent Loop, Retrieval Sufficiency, State Space

## What Changed

- Retrieval sufficiency now checks requested query facets, not only whether any
  evidence/citation exists. Facets currently cover model, authentication,
  pricing, token, endpoint, and rate-limit style requests.
- `RetrievalReport.diagnostics` now carries evaluator diagnostics so workloop
  decisions and planner feedback can see missing facets.
- Workloop evidence sufficiency now respects insufficient retrieval reports.
  A model evaluator cannot finalize when the host retrieval report says the
  evidence is incomplete.
- Planner feedback now merges model-reported missing evidence with host-derived
  evidence gaps, so a model planner can replan from concrete missing facets.
- Finance is now a first-class profile capability: a model may propose
  `finance.fundamentals_research`, and the host compiles it to `retrieval.run`
  with the finance fundamentals research profile.
- The semantic capability catalog now exposes broader state dimensions:
  task lifecycle, evidence, tooling, memory, resident runtime, and user control.
- The finance source directory was expanded as a search-resource library, not a
  financial content cache. It now includes SEC CIK/ticker mapping, SEC archives,
  SEC financial statement datasets, Companies House, SEDAR+, ASX, EDINET, SGX,
  and global official-statistics families in addition to the existing SEC,
  company IR, China/HK exchange, US statistics, and secondary market sources.
- Finance source policy now recognizes those official/global domains as primary
  regulatory, exchange, or government-statistic sources.
- `sec_edgar_structured_search` was added as a finance-profile-aware retrieval
  provider. It produces official SEC ticker-directory, EDGAR search/browse,
  submissions JSON, and companyfacts JSON candidates from ticker/CIK metadata or
  an injected ticker-to-CIK map. It performs no network access itself; fetches
  still go through the host-configured retrieval provider and allowlist.
- Live retrieval fallback construction now includes the SEC structured provider
  before generic configured search providers, so finance fundamentals tasks can
  use primary SEC URLs without relying on a broad web search API.
- `research_source_query_search` was added as a generic, template-driven
  source-directory query provider. It renders entry-declared
  `query_url_templates` from host metadata such as company, ticker, metric, and
  query; validates placeholders and allowed hosts; and returns official search
  URLs without network access or agent-side domain branching.
- Finance source entries now include curated official query templates for SEC
  EDGAR search, Companies House company search, FRED series search, and World
  Bank Data search.
- `kernel_v3.research.identity` now provides a shared host-owned
  `IssuerIdentity` resolver. It normalizes SEC tickers/CIKs, company and issuer
  names, and ASX/HKEX/SGX-style exchange codes from query text and host
  metadata, including injected ticker-to-CIK maps. SEC EDGAR and source-query
  providers now reuse this resolver instead of duplicating identifier parsing.
  Non-US exchange-code patterns such as `ASX:BHP` are not treated as SEC
  tickers.
- Finance source-query templates now cover additional official disclosure entry
  points: CNINFO full-text search, HKEX title search, ASX issuer announcements,
  EDINET document search, and SGX company announcements. SEC query expansion was
  tightened so generic "annual report" language does not route non-US issuer
  tasks to EDGAR without SEC-specific signals.
- Live retrieval CLI network budgeting now treats `--live-max-network-fetches`
  as the total query+fetch guard. Research-depth defaults can provide query and
  fetch shape, but the host trims planned fetches so a live run is not rejected
  before execution merely because profile defaults exceed the explicit total
  budget.
- The semantic capability/state catalog was expanded beyond workspace-centric
  categories. It now exposes artifact, data, code, project, calendar, security,
  browser/page, market-news/market-data, credential, and device-control
  boundaries as first-class capability/state families. Planned or host-only
  capabilities remain non-executable; they exist so model packets can describe
  broad tasks without inventing tools or collapsing everything into workspace
  mode.
- Model planner mode now journals dynamic work plans and replan updates. Each
  planner iteration records the latest feedback, selected action preview, and
  revision number, so a long-running model-driven loop is inspectable instead
  of being only a sequence of opaque processor calls.
- Agent runtime now supports host-owned loop budget metadata and CLI flags
  (`--max-agent-steps`, `--max-agent-tool-calls`,
  `--max-agent-artifact-bytes`). Model-planner workspace/retrieval/write modes
  get bounded long-loop defaults, while callers can explicitly tighten or
  expand the guard ceilings.
- The semantic capability/state catalog now has a broader Hermes-oriented
  ontology rather than a workspace-shaped mode list. It exposes roleplay,
  knowledge explanation, document/report/email drafting, web research, market
  news/data, competitive landscape, browser/session boundary, external API,
  and long-running monitor domains, plus state axes for intent scope,
  execution surface, output contract, evidence, permissions, resident state,
  and user control.
- Task graph routing now maps `web.research`, `finance.market_news`,
  `finance.market_data`, and `finance.competitive_landscape` to the retrieval
  recipe and `retrieval.run` when host policy permits. High-risk capabilities
  such as device control remain blocked host boundaries instead of becoming
  fake tools.
- Bounded crawl discovery now ranks discovered page/sitemap candidates against
  query and metadata terms before applying the source budget. Seed URLs remain
  in the returned source set for provenance, but the crawler no longer spends a
  tight source budget on the first unrelated navigation links when a more
  relevant research page is present later in the page or sitemap.
- The finance source directory now covers common secondary market-data and
  reputable-news entry points in addition to primary filings/statistics:
  Yahoo Finance quote/lookup, Nasdaq market activity, MarketWatch stock pages,
  Reuters search, Bloomberg search, Financial Times search, and CNBC search.
  These entries provide where-to-look pointers and query templates; they do
  not cache financial content.
- Retrieval sufficiency now distinguishes finance subtask authority needs.
  Fundamentals keep the primary-source requirement. Market-news, market-data,
  and competitive-landscape tasks set `source_authority_requirement` to
  `secondary_or_better`, allowing reputable news/market-data evidence for
  current context while preserving primary-source gating for filing claims.
- `aggregate_search` was added as an explicit live retrieval search strategy.
  It collects bounded candidates from every enabled search provider,
  deduplicates by URI, and ranks the merged set by query/source authority before
  the retrieval operator applies its source/fetch budget. This avoids a generic
  first provider preventing later primary/corpus/source-directory candidates
  from being considered.
- The semantic state space is now exposed to planner context as
  `semantic_state_space`, not only to semantic intake. It includes autonomy,
  world model, resource kind, action phase, authority, temporal, risk,
  identity-boundary, and communication-channel axes so live model packets can
  reason over more than `workspace:*` state without inventing executable tools.
- Model-planner retrieval actions now inherit finance-profile defaults from
  the host-validated semantic plan. If model intake classified a task as
  `finance.fundamentals_research`, the host adds the finance fundamentals
  research profile even when the model's `planner.propose` payload only
  contains a query/source URL.
- Retrieval insufficiency feedback now includes source-authority gaps, not just
  generic `sufficient_retrieval_evidence`. A weak source under a primary-source
  finance task produces `source_authority:primary` and `primary_source`, which
  the next planner packet can use to replan toward official filings or issuer
  materials.
- Live retrieval now shares `ArtifactStore` and `ResearchCorpusStore` with the
  agent runtime when a corpus is configured. The live search chain is
  cache-first (`research_corpus`) and then falls back to direct URLs,
  structured/source-query providers, JSON HTTP search, crawl discovery, and
  source directories. Corpus hits fetch from artifact blobs; new live fetches
  are indexed back into the corpus for later loops.
- `adaptive_search` was added as a planner-visible but host-owned search
  strategy provider. When configured with
  `HOLO_V3_LIVE_SEARCH_STRATEGY=adaptive`, retrieval actions may propose
  `metadata.search_strategy` values such as `corpus_only`, `fresh_live`,
  `aggregate`, `structured`, or `crawl`. The provider only selects among
  configured providers; PolicyGate, fetch allowlists, artifact storage,
  sufficiency checks, and termination remain host-owned.
- The semantic task graph now attaches a `state_profile` to every node instead
  of relying only on `mode` or `workspace:*` tool names. Each profile records
  domain, activity, resource, execution surface, permission state, route class,
  capability families/statuses, evidence posture, output contract, autonomy,
  risk posture, and expandable `state_axes`. Planner context receives a
  compact `semantic_state_profile_summary`, so a model can distinguish
  finance, legal, medical, education, communication, operations, product,
  risk, cybersecurity, database, cloud, workflow, knowledge-base, multimodal,
  resident, transport, calendar, system, security, and physical-world boundary
  state while the host still decides what can execute.
- The runtime now projects those state profiles as first-class agent state:
  `context.state.semantic_state_profiles`,
  `context.state.semantic_state_profile_summary`, and a journaled
  `agent_state_profile` record. The declared `semantic_state_space` vocabulary
  was also made self-consistent with generated profile values, including legal
  sources, medical sources, message drafts, workflow runs, database tables,
  cloud resources, media inputs, external-account boundaries,
  planned/host-only permission states, and boundary/failure output contracts.
- Source-directory-driven crawl was added behind explicit live retrieval env
  gates. `HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY=1` lets the bounded crawler draw
  seeds from curated profile source entries; `HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST=1`
  merges concrete source-directory hosts into crawl/fetch allowlists. This
  enables a finance-profile planner action with `metadata.search_strategy=crawl`
  to go from source library to crawler discovery to fetched evidence without
  embedding specific URLs in the model packet.
- The finance source library now includes additional common research entry
  points: central bank data portals, US Treasury/FiscalData, fund/ETF
  disclosures, earnings-call transcript aggregators, and credit-rating agency
  searches. They remain source pointers rather than cached market content;
  source policy marks central-bank, Treasury, and fund disclosures as primary
  families and transcript/rating sources as secondary context.
- Source-directory search now ranks curated entries by query and task metadata
  before applying the source budget. This prevents tight-budget market-news,
  market-data, macro/rate, transcript, or rating tasks from always spending the
  first fetch on the static SEC directory entries. The provider journals
  `top_source_directory_ids`, matched terms, and relevance scores while still
  leaving network permission, fetch allowlists, evidence sufficiency, and
  source-authority gates to the host.
- Source-query template expansion now uses the same ranking substrate after
  safe template rendering. Candidate URLs are rendered, host-validated,
  deduplicated, ranked by source/task relevance, and only then truncated by
  `max_sources`, preventing a generic query-echo template from crowding out the
  relevant Reuters/Yahoo/Treasury/transcript/rating search URL.
- Retrieval replanning now has an explicit host-state packet:
  `context.state.agent_replan_hints`. It is compiled from journal records after
  each iteration and journaled in `agent_work_plan_update`. For insufficient
  retrieval it includes missing facets/source authority, attempted
  query/strategy/provider summaries, recent payload hashes, suggested query
  and search-strategy changes, and `do_not_finalize_until` rules. This gives a
  live model a structured next-action interface instead of forcing it to infer
  loop state from raw record history or fixed phrase behavior.
- `retrieval.run` now supports the same plural capability payload contract as
  workspace actions. A single model semantic intent can place a list under
  `metadata.capability_args["retrieval.run"]`; the host expands it into
  multiple ordered retrieval actions, preserving query metadata such as finance
  research profile, research task kind, and source-authority requirement.
  This lets one LLM planning packet drive multi-subtopic research loops without
  giving the model direct tool execution authority.
- Multi-payload retrieval now has run-level planned subgoal coverage. The
  workloop groups host-planned `goal-plan-*` retrieval reports by goal id and
  requires each latest planned subgoal report to be sufficient before final
  synthesis. A later successful retrieval no longer hides an earlier failed
  subtopic; incomplete subgoals produce `retrieval_subgoal:<goal_id>` missing
  evidence and a `FailureReport`.
- Explicit retrieval `queries` and `query_templates` now drive their own safe
  default query budget. If a model packet provides several query strings but
  omits `max_queries`, the host derives the default from the explicit list
  length before global retrieval caps. Research-depth defaults no longer
  accidentally truncate a structured multi-query search plan.
- Dynamic model planner mode now receives planned retrieval coverage in
  `agent_replan_hints`. Planned subgoal ids are derived from the semantic task
  plan as well as executed actions, so the model can declare several research
  subgoals up front, execute them one at a time, and retry only the incomplete
  subgoal when host coverage remains insufficient.
- Planner context now includes `agent_retrieval_plan_state`, a low-noise
  retrieval work-plan packet with planned subgoals, pending/complete/incomplete
  goal ids, latest status by goal id, and `next_recommended_goal_id`. This gives
  live models an explicit way to choose the next bounded retrieval action from
  the host-validated plan instead of inferring it from raw journal history.

## Validation

Offline kernel v3 regression:

```bash
.venv/bin/pytest -q tests/test_kernel_v3_*.py
```

Result:

```text
498 passed
```

Additional deterministic coverage now includes:

- global primary finance-source classification;
- a multi-intent `finance.fundamentals_research` task that compiles into two
  `retrieval.run` loop actions and finalizes only after both reports are
  sufficient.
- SEC EDGAR structured source generation from explicit CIK metadata and from an
  injected ticker-to-CIK map;
- live retrieval provider inspection showing `sec_edgar_structured_search` in
  the fallback search chain;
- a multi-step finance agent loop that uses SEC structured candidates, fetches
  fake SEC submissions/companyfacts bodies, journals provider-backed retrieval,
  continues once, then finalizes with two citations.
- source-directory query expansion from company and macro metadata;
- source-directory query-template host allowlist rejection;
- shared issuer identity resolution for metadata, query CIKs, injected SEC
  ticker-to-CIK maps, and selected exchange-code patterns;
- guard coverage that prevents non-US exchange codes from generating SEC EDGAR
  candidates as if they were US tickers;
- SEC EDGAR structured search using the shared identity resolver.
- official query URL generation for ASX, HKEX, SGX, EDINET, and CNINFO;
- a three-step exchange-disclosure agent loop that retrieves ASX, HKEX, and SGX
  official entry points and finalizes after three citations.
- a second multi-step finance agent loop using official Companies House and
  FRED query URLs, showing planner-intent expansion into two retrieval loop
  actions and host-owned finalization with two citations.
- a model-planner dynamic workspace loop that performs 11 planner/evaluator
  processor cycles, 11 `file.read` actions, 11 work-plan updates, and then
  finalizes from journal-derived evidence/citations.
- broad direct capabilities such as roleplay/persona remain direct-answer
  nodes rather than being collapsed into workspace;
- market-news/web-research semantic capabilities route to `retrieval.run` and
  finalize from citations;
- dangerous device-control capability remains a blocked host boundary;
- bounded crawl query ranking preserves a relevant AAPL 10-K revenue link under
  a two-source budget even when unrelated navigation links appear first.
- source-query expansion for market data and news renders Yahoo Finance,
  Nasdaq, MarketWatch, Reuters, Bloomberg, FT, and CNBC entry points with host
  validation;
- a two-step market-data plus market-news agent flow uses those source-query
  URLs, journals research profile/authority requirements, performs two
  retrieval loop actions, and finalizes from two citations.
- aggregate search provider tests show that a low-authority generic web result
  and a later SEC primary filing can be merged, ranked, and handed to the
  agent so only the SEC filing is fetched under a one-source/one-fetch budget.
- model-planner retrieval tests show that finance profile defaults are applied
  by the host even when the model payload omits them;
- a two-iteration retrieval loop test shows that weak-source evidence creates
  source-authority feedback, the second planner call sees that gap, and a retry
  against an SEC source finalizes with citations.
- the same replan test now asserts that the second planner context and
  `agent_work_plan_update` contain `agent_replan_hints` with missing
  source-authority state, suggested official-source query terms, search
  strategy changes, recent payload hashes, and host-owned
  `do_not_finalize_until` rules.
- a single-intent finance research test now feeds three `retrieval.run`
  payloads through semantic intake. The host expands them into three loop
  actions for revenue, margin, and competitive landscape research, journals
  decreasing work-plan remaining counts, continues twice, and finalizes after
  three citations.
- a companion failure test verifies that when one of three planned retrieval
  subgoals is insufficient, Holo records planned retrieval coverage, refuses
  final synthesis despite a later successful subgoal, and returns a
  `planned_retrieval_subgoals_incomplete` failure report with the failed
  subgoal id.
- a single-payload multi-query test verifies that a finance retrieval payload
  with three explicit queries and no model-specified `max_queries` still
  performs three bounded search attempts, even under light research-depth
  defaults, and finalizes from the primary SEC result.
- a dynamic model-planner test now executes four planner/tool iterations:
  three planned finance retrieval subgoals, one weak margin source, a later
  successful services source, then a host-packet-driven retry of only
  `goal-plan-1-2`. The run finalizes only after planned coverage becomes
  sufficient for every subgoal.
- the same dynamic replanning test now asserts that the first planner context
  exposes `agent_retrieval_plan_state` with all planned subgoals and that the
  retry planner update carries `next_recommended_goal_id=goal-plan-1-2`.
- live retrieval/corpus bridge tests show that a configured corpus is searched
  before live HTTP, and that an agent's first live SEC fetch is indexed into
  corpus so a second run can answer from artifact-backed corpus evidence without
  another network transport call.
- adaptive search strategy tests show that planner metadata can switch from
  `corpus_only` to `aggregate` after source-authority feedback, producing a
  second retrieval loop that finds a primary SEC source and finalizes.
- semantic state-profile tests show that broad domains such as finance,
  database, workflow, and knowledge-base are preserved in task graph node
  metadata and planner context instead of being collapsed into workspace mode;
  planned or not-configured capabilities remain host boundaries.
- source-directory crawl tests show that the crawler can use finance profile
  source entries as bounded seeds, while live config tests verify the feature is
  opt-in and redacted;
- source-query and source-policy tests cover central-bank, Treasury, fund/ETF,
  transcript, and credit-rating entry points with primary/secondary authority
  classification;
- an agent crawl test shows a model semantic packet can request
  `finance.fundamentals_research` with `search_strategy=crawl`, after which the
  host seeds SEC discovery from the source directory, fetches the discovered
  filing URL, and finalizes from citations.

Live model scenarios:

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -m kernel_v3.cli model-scenarios \
  --provider deepseek \
  --profile balanced \
  --thinking enabled \
  --reasoning-effort high \
  --temperature 0.2
```

Result:

```text
5 scenarios passed
```

Live agent retrieval smoke:

```bash
HOLO_V3_LIVE_MODEL=1 \
HOLO_V3_LIVE_RETRIEVAL=1 \
HOLO_V3_LIVE_CRAWL_SEED_URLS=https://api-docs.deepseek.com/ \
HOLO_V3_LIVE_SEARCH_ALLOWED_HOSTS=api-docs.deepseek.com \
HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS=api-docs.deepseek.com \
.venv/bin/python -m kernel_v3.cli agent "上网检索DeepSeek API文档，说明模型和鉴权方式" \
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

Result:

```text
completed
```

The live trace showed semantic intake, planner, evaluator, and synthesizer
processor calls against DeepSeek; bounded crawl/fetch against
`api-docs.deepseek.com`; artifact-backed evidence/citations; and a host-owned
termination decision. The DeepSeek API key was not present in the journal.

Live finance retrieval smoke:

```bash
HOLO_V3_LIVE_FINANCE=1 \
HOLO_V3_LIVE_MODEL=1 \
.venv/bin/pytest -q tests/live/test_kernel_v3_phase101_live_finance_retrieval.py
```

Result:

```text
1 passed
```

This exercised the current finance path against actual DeepSeek processor calls
and actual SEC HTTP fetches. The model produced a structured semantic packet and
planner proposal; the host forced policy/budget validation; SEC structured
source generation produced official `data.sec.gov`/`sec.gov` candidates; live
HTTP fetch stored raw bodies as artifacts; retrieval sufficiency finalized the
loop; and the synthesizer produced a Chinese answer using known citation refs.
The journal contained processor usage and retrieval/fetch records, but not the
DeepSeek API key or raw secret environment values.

Live DeepSeek user-acceptance checks now validate host-gated route sets instead
of a single canned route. For example, broad market-research prompts may either
ask for essential missing scope or perform a useful bounded `retrieval.run`
when a provider is configured; the test no longer forces `ask_user` as the only
valid outcome.

## Remaining Boundary

This iteration improves the core loop and state/capability surface. It does not
make arbitrary web search a default path, does not add live transports, and does
not let models execute tools or commit memory directly. Search quality still
needs broader dedicated source/search adapters before finance-grade research can
be considered reliable. The SEC provider is a useful primary-source brick, not a
complete financial research stack: richer issuer identity resolution,
exchange-specific filing adapters, current-market/news search, and deeper
crawler/readability quality remain open capability layers.
