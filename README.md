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
- `kernel_v3/mission/`: global mission supervisor, mission directives, run-delta
  assessment, and thread-scoped working-memory/RAG context for long task
  continuity.
- `kernel_v3/capabilities.py`: host-visible capability/state catalog spanning
  conversation, roleplay, document/report work, workspace, retrieval, web
  research, finance, memory, artifact, data, code, project, resident,
  transport, calendar, system, and security capabilities.
- `kernel_v3/chat/`: multi-turn thread runtime, routing, pending user input,
  journal-derived summaries, and memory admin surfaces.
- `kernel_v3/processors/`: schema-first processor fabric, fake providers,
  optional live model providers, JSON repair, routing, usage, provider
  availability circuit breaking, and adapters.
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

## Storage Layout

Kernel v3 now separates full audit logs from user-facing thread transcripts.
The global journal remains the authoritative execution ledger, but interactive
thread history is mirrored into per-thread files so users do not need to inspect
one large JSONL blob.

Default paths are rooted at `.state/kernel_v3/`:

- `.state/kernel_v3/journal/global.jsonl`: full audit ledger for tasks, model
  calls, tools, policy decisions, retrieval, chat events, and final results.
- `.state/kernel_v3/journal/global.sqlite`: SQLite index for the global ledger.
- `.state/kernel_v3/threads/<thread_id>/thread.jsonl`: user-facing transcript
  for one chat thread. This contains chat turns, routing summaries, commands,
  assistant results, and thread summaries, not raw fetched bodies.
- `.state/kernel_v3/memory/memory.jsonl`: durable memory event log, created once
  memory proposals/items exist.
- `.state/kernel_v3/memory/memory.sqlite`: durable memory metadata/index.

`HOLO_V3_STATE_DIR` can override the `.state/kernel_v3` root. Legacy files such
as `kernel_v3/.holo-v3-journal.jsonl` are not deleted automatically; they are old
single-ledger state files and should be treated as migration input, not the
normal thread-history surface.

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

Recent kernel-v3 hardening is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-03_RETRIEVAL_LOOP_HARDENING.md` and
`docs/KERNEL_V3_PROGRESS_2026-06-04_ACADEMIC_RESEARCH_PROFILE.md`, with the
latest open-research loop and attention work in
`docs/KERNEL_V3_PROGRESS_2026-06-04_OPEN_RESEARCH_ATTENTION.md`. The 2026-06-05
loop-coupling and memory-context pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_LOOP_COUPLING_MEMORY.md`. The same day's
strategy-supervision and safety-boundary pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_STRATEGY_SUPERVISION.md`, and the next
retrieval-campaign pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_RETRIEVAL_CAMPAIGN.md`. Source-quality
feedback and discovery-only fallback hardening are tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_SOURCE_QUALITY_FEEDBACK.md`. The current
retrieval campaign and live-smoke pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_DEEP_RETRIEVAL_SYSTEM.md`. The WorkMethod
layer and strategy-shift handoff are tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-05_WORKMETHOD_LAYER.md`. The 2026-06-06
discovery-expansion and retrieval benchmark pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-06_DISCOVERY_EXPANSION.md`. The current
system-time/resident scheduling pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-06_RESIDENT_TIME_PRIORITY.md`. The current
memory/RAG research and implementation target is summarized in
`docs/KERNEL_V3_MEMORY_RAG_RESEARCH_2026-06-07.md`. The 2026-06-08 memory
digest and SEC companyfacts extraction pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-08_MEMORY_DIGEST_SEC_EXTRACTION.md`. The current
retrieval loop counts actual tool observations rather than payload-declared
fetch budgets, model-visible context compacts large mission/retrieval/runtime
payloads before processor calls, mission continuations preserve the original
root goal while passing the current directive separately, `chat.route` remains
model-owned with structured route-relation validation instead of phrase tables,
durable memory is visible as both project and thread context views, SEC
companyfacts/direct-URL retrieval now preserves structured financial evidence
such as concept, metric, annual/quarterly period, filing, and value fields,
deep retrieval can run model-owned retrieval strategy packets first, then fall
back to adaptive host query campaigns with large candidate pools, concurrent
fetch, source-family rejection, and structured coverage-gap diagnostics. A
strategy packet can carry domain hypotheses, source-family plans, concrete query
plans, fallback moves, evidence criteria, and stop conditions, so mathematics,
physics, finance, policy, engineering, and other research domains do not need
separate hard-coded search scripts. Scholarly/frontier research can also use an
`academic_research` profile with academic source families, discovery-only source
handling, topic-coverage gates, live arXiv paper discovery, and paper-level
metadata extraction for arXiv Atom, OpenAlex, Crossref, and Semantic Scholar
responses. Scholarly metadata evidence must match core topic anchors from the
user goal, so generic `research`/`review`/`paper` wording alone is not enough to
pass the evidence gate.

Kernel v3 currently contains the infrastructure for:

- bounded planner -> policy -> tool -> evaluator loops;
- workloop progress, repetition, evidence sufficiency, and termination
  decisions;
- mission-level global task supervision above the inner loop. The inner
  `LoopControllerV3` still owns step execution, while `MissionRuntime` compares
  each run against the original user goal, journals coverage/gaps, and either
  issues a new `MissionDirective`, finalizes, asks for genuinely missing user
  input, or returns a failure report;
- `mission.assess` processor packets for optional model-backed coverage
  assessment. The model can suggest coverage and next strategy, but the host
  validates the decision and never lets mission assessment execute tools,
  bypass policy, or commit memory;
- a WorkMethod layer that frames each task as a compact work packet containing
  the current work frame, done criteria, method, failure moves, user-interaction
  policy, and thread working set. In live model mode, `workmethod.frame` and
  `workmethod.gap` are schema-first processor packets; in deterministic/fake
  tests they fall back to host rules. The packet enters planner context but
  does not execute tools, grant permissions, or replace `LoopControllerV3`;
- work-gap assessment and strategy-shift records above the inner loop. After a
  run, `MissionSupervisor` journals `work_gap_assessment` and, when needed,
  `strategy_shift`, then passes avoid-repeat and materially-different-method
  hints into the next `mission_directive`;
- mission directives that become hard planner context instead of passive text.
  If the mission supervisor says a retrieval loop must avoid a failed query,
  switch strategy, or fill missing requirements, the next planner packet sees
  those constraints as `agent_replan_hints`; the host retrieval strategy
  supervisor then validates the next `retrieval.run` payload against them;
- LLM-declared answer profiles for research work. `semantic.intake` may emit
  `metadata.answer_profile_hint` with `format`, `detail_level`,
  `target_sections`, and `quality_gate`; the host validates that packet,
  exposes it to planner/synthesizer context, journals final-answer quality
  checks, and blocks only strict-profile outputs that do not meet the declared
  answer shape. This is a packet contract, not keyword matching;
- strict research-answer repair. Finance, academic, and policy research reports
  default to strict answer quality when they resolve to detailed/deep reports.
  A low-quality model synthesis gets one structured `synthesizer.answer` repair
  pass with concrete gaps before the host returns
  `final_answer_quality_insufficient`; failed quality checks also enter thread
  RAG as `answer_quality_gap` attention blocks;
- research-result memory proposals. When a strict research answer passes the
  quality gate and durable memory is configured, the host can create a pending
  compact `research_note` proposal from the final answer, citation refs,
  evidence refs, and research mission metadata. The proposal stores a bounded
  summary, key findings, limitations, refs, and provenance rather than the full
  report body. The model still cannot commit durable memory directly;
- non-blocking task-reflection memory proposals. When a task fails after real
  attempts, the host can distill the root goal, failure mode, attempted actions,
  missing evidence, next action, and host diagnostics into a reviewable
  workflow-memory proposal. These learning proposals enter thread RAG/attention
  context for later planner packets but do not block the next user turn and do
  not auto-commit durable memory;
- thread-scoped learning carryover. Non-blocking learning proposals from recent
  tasks in the same thread are included in later thread RAG context, so the next
  planner packet can see prior failure lessons even before they are approved as
  committed durable memory. Other threads do not receive those proposals;
- self-iteration context in planner/evaluator packets. Recent retrieval
  failures, answer-quality gaps, avoid-repeat query signatures, recommended
  next actions, and thread learning refs are compacted into
  `thread_rag_context.self_iteration`; prioritized `attention_blocks` are also
  preserved in processor prompt context, so the next loop sees what failed and
  what should materially change without reading raw journal blobs;
- task-continuity context in planner/evaluator packets. Mission assessments,
  mission directives, feedback, retrieval gaps, recent actions, evidence refs,
  and citation refs are compacted into `thread_rag_context.task_continuity`,
  so the next loop receives a journal-derived working note with the current
  objective, open requirements, avoid-repeat signatures, suggested actions, and
  stop conditions;
- durable-memory context in processor packets. Passive committed memory
  snapshots now include a lightweight `durable_memory_context` with project and
  thread view totals, memory ids, top safe summaries, and an active-recall hint.
  This lets the model use already paged memory or propose `memory.recall`
  when the snapshot is too sparse, without exposing raw bodies or granting
  memory-write authority;
- direct, retrieval-grounded, workspace-grounded, clarification, and failure
  flows;
- workspace directory listing through `workspace.list`, separate from file
  search/read and without shell execution. User-facing workspace observations
  hide Holo internal state surfaces such as `.state`, `.codex`, `.agents`,
  `.holo-v3-*`, SQLite indexes, and cache directories;
- workspace write flows with manifest validation and journal redaction of raw
  file bodies;
- non-workspace system-state flows such as `system.time`, where the model
  proposes a host capability and the host reads the current time;
- safe host context state such as thread/task/run identity through
  `system.environment`; this is model-visible context for response planning, not
  shell access, process inspection, or a time-tool alias;
- system capability ABI validation. Time/date/clock intent aliases such as
  `time_query`, `system_time_query`, and `current_time_query` are normalized to
  the canonical `system_time` intent and force a `system_answer` recipe when
  they carry `system.time`; generic system-state, self-description, or
  capability-check packets are still downgraded to semantic/direct answers if a
  live model incorrectly attaches `system.time`;
- semantic work plans that can expand one model-proposed capability into many
  ordered tool actions, including 10+ iteration workspace loops;
- semantic research plans that can expand one model-proposed `retrieval.run`
  capability into multiple ordered retrieval actions from
  `metadata.capability_args["retrieval.run"]` payload arrays, so one LLM packet
  can drive multi-subtopic research while each retrieval remains host-validated;
- run-level planned retrieval coverage: for multi-subtopic research, Holo
  tracks the latest retrieval report for each required host-planned
  `goal-plan-*` subgoal and refuses to finalize while a required subgoal
  remains missing or insufficient. Discovery expansions remain visible in the
  research graph and diagnostics, but `next_tool_actions` are suppressed once
  the retrieval report is sufficient so successful evidence does not keep
  nudging the planner into redundant acquisition;
- model-planner retrieval binding: if a model proposes `retrieval.run` without
  a `goal_id`, the host binds it to the next incomplete required planned
  retrieval subgoal. The model can focus on query/source/strategy while the
  host preserves plan coverage and termination semantics;
- retrieval payload normalization separates "what to extract" from "where to
  fetch". If semantic intake or a host plan supplies a meaningful query plus an
  explicit URL, and the model planner later emits a URL-only `retrieval.run`
  query, the host preserves the semantic query and moves the URL into
  `metadata.source_urls`. This keeps direct-source tasks from losing extraction
  terms while still forcing citations to come from the requested source;
- explicit multi-query retrieval payloads: when a model/host payload supplies
  `queries` or `query_templates`, Holo derives a safe default `max_queries` from
  that list so one retrieval subgoal can run multiple bounded search attempts
  without the model needing to guess budget fields;
- model-owned retrieval strategy payloads: when the model supplies
  `metadata.retrieval_strategy.query_plan`, Holo preserves that strategy through
  action binding, executes those model-chosen queries first, disables fixed host
  query axes by default, and keeps host supervision focused on validation,
  dedupe, budget, policy, evidence, and termination;
- discovery expansion inside the retrieval operator. Academic/source-directory
  discovery pages such as arXiv, OpenAlex, Crossref, Semantic Scholar, Springer,
  and Cambridge are compiled into concrete fetchable document/API candidates
  before ranking/fetching. Reports now expose `next_tool_actions`, an
  `operator_critic`, and a compact research graph of query -> source family ->
  discovery page -> document -> evidence -> citation;
- retrieval behavior benchmarking through `holo-v3 retrieval-benchmark
  <task_id>`, which summarizes live-run loop counts, query repetition, fetch
  success rate, evidence/citation counts, final answer length, failure mode,
  next tool actions, and research-graph coverage without asserting fixed
  answers;
- resident queue and scheduler priority. Inbox messages and local schedules now
  carry a first-class `priority` field, and resident workers claim due work by
  priority before age. Scheduler ticks preserve schedule priority when they
  enqueue normal resident inbox messages;
- host-owned reminder compilation for resident workers. Relative reminder
  messages such as "十分钟后提醒我喝水" compile into deterministic local
  schedules and a ready outbox confirmation; when due, the schedule emits a
  normal resident inbox message. The compiler does not route chat, call models,
  or bypass the queue/scheduler audit path;
- human resident status output with `holo-v3 resident --output human status`,
  showing queue claimable/running/retry/outbox/pending-input counts plus active,
  due, recurring, and next-due schedule state.
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
- thread-local working context in processor packets: pending questions,
  original task, recent turns, latest result/failure, and bounded task traces
  are compacted into semantic/planner context so follow-up turns can continue
  the same task without relying on phrase tables;
- thread-scoped RAG/working-memory context for the agent loop: recent turns,
  assistant results, task traces, evidence refs, citation refs, and failure
  diagnostics are compacted from the journal and injected into planner/evaluator
  packets. It also exposes prioritized attention blocks for recent failures,
  current evidence, recent final answers, and latest task state. This is
  thread-local and does not write durable memory;
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
  remain artifacts. SEC companyfacts JSON is projected into compact annual
  summary rows plus metric rows such as concept, metric, unit, value,
  annual/quarterly period, fiscal period, form, filing date, and accession
  number before evidence ranking. The annual summary rows group the latest
  revenue, net income, EPS, cash-flow, balance-sheet, and related concepts by
  fiscal year so financial answers are not forced to infer a report from
  scattered old XBRL facts. Annual filings are preferred for
  annual/fundamental queries while quarterly facts remain available for
  recent-period coverage; generic JSON/CSV still uses bounded readable
  projections;
- finance/technical research profiles can be inferred from structured semantic
  domains as well as explicit capability names. This keeps a model packet like
  `domain=finance_fundamentals` connected to the finance source policy even if
  the planner only proposes a generic `retrieval.run`;
- academic/frontier research is now represented as a first-class semantic
  profile. Model packets can express `academic.research`,
  `academic.frontier_research`, `academic.literature_review`,
  `academic.paper_search`, or `academic.scholarly_sources`; the host maps those
  to scholarly source policies, rejects dictionary/encyclopedia evidence for
  academic research, treats source-directory/search surfaces as discovery-only,
  checks that evidence covers the user's core topic terms, and can use the live
  arXiv API to discover concrete paper pages instead of citing generic search
  pages;
- open-ended research can finish with explicit limitations when enough citable
  evidence already covers the root objective but remaining planned retrieval
  subgoals are soft gaps such as language coverage, source breadth, or auxiliary
  angles. Finance, policy, and hard factual metric tasks keep strict planned
  retrieval coverage;
- durable-memory proposals, approval/rejection, recall, deletion, export, and
  context injection;
- active memory recall inside the agent loop through `memory.recall`: the model
  may propose a read-only memory lookup for prior preferences, workspace/project
  conventions, thread continuity, or "what do you remember" style questions;
  the host recalls committed durable memory from workspace/project scope,
  current-thread scope, or both, journals only safe previews/refs/hashes, audits
  the access in the memory log, and feeds the observation back into the next
  planner/evaluator step. This is not direct memory writeback and not a
  fixed-response RAG shortcut;
- local resident inbox/outbox, leases, schedules, and audit/doctor surfaces;
- resident control-plane cancellation through `holo-v3 resident cancel
  <message_id>`, which marks pending/running/retry messages as canceled,
  clears leases/retry timers, journals the cancellation, and prevents worker
  claim/replay;
- finance-fundamentals research profile and local corpus-backed retrieval;
- model-planner retrieval binding that applies host-validated research profile
  defaults from semantic intake/task plans before tool execution;
- host-owned retrieval strategy supervision: after the model proposes
  `retrieval.run`, the host checks whether the payload materially changes the
  failed search state. Repeated queries can be rewritten into diversified query
  batches, source-family switches, or structured/direct-source payloads derived
  from prior diagnostics. Direct URLs, SEC/FRED/FiscalData structured payloads,
  and genuinely new search strategies are treated as valid strategy
  transitions rather than overwritten;
- query-campaign planning for deep retrieval. When a task has research depth,
  large source/fetch budgets, aggregate/adaptive search, or profile strategy,
  the retrieval FSM expands one base query into a bounded multi-view campaign:
  profile templates, model/mission hints, source-family switches, and generic
  research axes. Campaign diagnostics record selected/skipped query signatures
  so later loops can avoid repeating unproductive searches;
- retrieval failure attribution in every report. Failed or insufficient runs now
  identify the primary failing layer, such as `search_no_sources`,
  `fetch_failed_or_empty`, `extraction_no_spans`, `all_evidence_rejected`, or
  `source_authority_gap`/`coverage_gap`, and include a `next_strategy_hint` for
  the next planner loop;
- retrieval source-quality feedback. `SourceAssessment` is summarized into
  `source_quality`, weak profile sources do not become formal citations,
  authority gaps stay visible in report and mission context, and fallback search
  continues past discovery-only index/search pages when later providers can
  return fetchable primary sources;
- retrieval workloop feedback that carries missing query facets and missing
  source-authority signals into the next planner packet, allowing bounded
  replan attempts without weakening host termination guards;
- planner-visible `agent_replan_hints` compiled from journal records after
  insufficient retrieval. The packet carries missing facets/source authority,
  attempted query/strategy/provider summaries, payload hashes to avoid
  repeating, suggested next search strategies/query hints, ranked
  source-directory targets for profiled research, and `do_not_finalize_until`
  rules for the next model planner call;
- planner-visible `retrieval_capability_state`, which exposes whether
  `retrieval.run` is registered, which search/fetch provider ids are configured,
  whether live fetch is available, whether network budget exists, and which
  profile-aware structured providers are visible. This is model input for
  planning, while PolicyGate and loop guards still own execution;
- processor-visible `host_situation`, a compact host-owned state packet that
  summarizes task/thread ids, recipe limits, allowed tools, live retrieval
  availability, recent actions, retrieval/search/fetch attempts, latest
  processor/API results, termination/failure reasons, and failure attribution.
  It is injected into chat routing, semantic intake runtime context,
  planner/evaluator context, synthesizer payloads, mission assessment, and
  failure reports so models do not hallucinate that network, finance research,
  or tools are unavailable when the host already attempted them. It contains
  only refs, previews, counters, provider ids, and diagnostics, never raw fetched
  bodies or secrets. Completed, needs-user-input, and failed task exits now
  journal a terminal `host_situation`, and trace output renders a concise host
  situation summary for operator review. Thread working context and thread RAG
  now carry compact `host_situation` trace items into later turns so follow-up
  planner/evaluator calls inherit the previous loop's real capability and
  failure state. `ChatRuntimeResult` and `chat_agent_result` journal records
  also persist the compact host situation for success and failure turns, so
  summaries, resident projections, and future routing can inspect it without
  replaying raw logs;
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
- generic research-profile policy: `research_profile` now defines source
  authority, query templates, discovery source kinds, evidence facets, numeric
  fact requirements, extraction aliases, and evidence compaction. Finance
  fundamentals and technical documentation are profile instances under the same
  `retrieval.run` loop rather than separate controller branches;
- evidence compaction before citation synthesis: retrieval can search/fetch
  broadly, then select a smaller source-authority/facet-aware evidence package
  before journaling citations and calling the synthesizer. This keeps deep
  research loops from dumping every candidate span into the final model packet;
- generic target-entity consistency for deep retrieval: when a query contains a
  clear multi-token target such as a named organization, retrieval ranks
  sources by target match, rejects obvious source candidates before fetch when
  their title/snippet/URI do not cover the requested entity, and rejects spans
  whose page only matches a partial or different entity. Rejected sources and
  spans are journaled with target diagnostics, required/missing target phrases,
  and previews, so the next planner packet can change the disambiguation
  strategy instead of treating noisy pages as citations;
- template/shell-page evidence rejection: extracted spans dominated by
  templating placeholders such as `{{field}}`, `${field}`, or `<% field %>` are
  not accepted as evidence. Search pages and app shells can still be useful
  diagnostics, but they do not satisfy evidence/citation gates;
- retrieval rejection diagnostics now count as workloop progress. Wrong-entity
  pages, failed source families, and other rejected evidence do not satisfy the
  task, but they are useful feedback for the next loop iteration and mission
  directive;
- deep-retrieval repetition guards are sized for real research. Repeated failed
  fetch targets no longer stop the loop after two misses by default; mission
  supervision still caps total iterations and can return a failure report when
  all materially different strategies are exhausted;
- finance fundamentals source directory entries for SEC/EDGAR, SEC structured
  data, SEC CIK/ticker mapping, SEC archives, SEC financial statement datasets,
  company IR, US/global official statistics, China/HK/UK/Canada/Australia/Japan/
  Singapore disclosure portals, and secondary market sources.
- SEC EDGAR structured source generation for finance fundamentals. Given a
  ticker, CIK, or injected ticker-to-CIK map, Holo can generate official SEC
  submissions, companyfacts, EDGAR search, browse, and ticker-directory
  candidates without doing network search itself.
- SEC ticker-CIK continuation hints for finance fundamentals. When an earlier
  retrieval step extracts a ticker/CIK pair from the official SEC ticker
  directory, the next planner context includes a host-built
  `suggested_sec_structured_sources` payload for SEC submissions/companyfacts
  retrieval. Raw fetched bodies stay in artifacts; the hint is derived from
  extracted spans and still requires a normal `retrieval.run` proposal.
- SEC discovery artifacts are not final finance evidence. SEC ticker-directory,
  submissions, EDGAR search, browse, and filing-directory pages can complete
  discovery subgoals and provide continuation hints, but finance final answers
  require primary filing bodies, companyfacts metrics, official statistics, or
  other qualified financial evidence with citation refs.
- SEC Archives filing-document candidate generation. When a host/model
  retrieval payload carries CIK plus accession number and optional
  `primaryDocument`, Holo derives the official primary filing document,
  complete submission text, and filing directory URLs before generic SEC
  browse/search candidates, while rejecting unsafe document names. Filing
  continuation hints are filtered to financial report forms such as `10-K`,
  `10-Q`, `20-F`, and `40-F`.
- FRED structured source generation for official macro data. When a retrieval
  payload carries `fred_series_id` / `series_id`, Holo derives the official
  FRED series page and CSV observations URL without doing web search itself.
  Macro-data finance tasks also prefer government-statistic, central-bank, and
  Treasury source families so company-filing templates do not pollute CPI/rate
  style retrieval.
- FiscalData structured source generation for US Treasury data. When a
  retrieval payload carries `fiscaldata_api_path`, Holo derives the official
  `api.fiscaldata.treasury.gov/services/api/fiscal_service/...` JSON endpoint
  with bounded fields/filter/sort/page parameters. It validates the official
  path prefix and rejects unsafe query params before exposing the source.
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
  candidate source URLs; network fetch still requires live retrieval permission
  plus either curated/source-search allowlists, discovered web-search result
  permission, or an explicit smoke-test override.
- empty retrieval observations with zero evidence and zero citations no longer
  count as loop progress. The failed/empty fact is journaled and re-enters the
  workloop, but progress, repetition, evidence sufficiency, and termination are
  still evaluated before the agent answers or fails.
- network retrieval cost is host-owned. `LoopControllerV3` uses the tool
  manifest's `network_fetch_cost_field` and default cost when checking network
  guards, so model-supplied payload fields such as `network_fetch_count` cannot
  exaggerate or bypass the configured budget.
- final-answer quality checks enforce explicit source requirements. When the
  user or semantic metadata names a required source URL, the answer may only
  pass if at least one used citation resolves to that URL or a safe prefix of
  it; citations from unrelated search results do not satisfy the task.
- private/sensitive context is blocked before external model calls unless an
  explicit host parameter authorizes that boundary crossing. ProcessorFabric
  journals the request/result metadata, but does not send secret-like prompts,
  sensitive durable-memory sections, or private-context markers to DeepSeek or
  another external provider by default. Local/fake providers remain available
  for controlled diagnostics.

Live model and live retrieval are not default unit-test dependencies. Online
`chat`, `agent`, and resident `run/run-once` now get bounded live web-discovery
permission by default so retrieval tasks do not look read-only; pass
`--no-live-retrieval` to disable that surface. Low-level `retrieve` and
`retrieval-providers` commands remain explicit because they are debugging and
index-building tools.

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
chmod +x holo-v3 scripts/install-holo-v3-cli.sh
scripts/install-holo-v3-cli.sh
```

After installation, `holo-v3` is available on the WSL user PATH through
`~/.local/bin/holo-v3`. The launcher resolves the repository root and uses
`.venv/bin/python` when the local virtualenv exists.

The product entry point is now the bare command:

```bash
holo-v3
```

Bare `holo-v3` starts the interactive chat console in live model mode. If
`DEEPSEEK_API_KEY` is not configured, it fails fast instead of silently falling
back to fake/offline processors. `HOLO_V3_LIVE_MODEL=1` remains accepted for
explicit live-smoke commands, but the interactive product entry point can use
the DeepSeek key directly. Deterministic offline checks must be explicit, for
example:

```bash
holo-v3 chat --offline --thread demo --once "what can you do?"
```

```bash
holo-v3 tools
holo-v3 agent "explain kernel v3" --mode direct
holo-v3 agent "扮演一个谨慎的初级律师，说明你会怎么做" --mode semantic
holo-v3 agent "what time is it in UTC?" --mode system
holo-v3 chat --thread demo
holo-v3 providers
holo-v3 provider-smoke --fake
holo-v3 retrieve "sample topic"
holo-v3 memory inspect --memory-log kernel_v3/.holo-v3-memory.jsonl
holo-v3 resident status
```

Interactive `holo-v3 chat` uses a human-readable terminal view when attached to
a TTY: colored status headers, compact task/run refs, and the current
`holo[thread]>` prompt. Scripted use stays machine-readable by default:
`--once` and piped stdin still emit JSON unless `--output human` is requested;
when human output is requested, `--once` uses the same streaming activity view
as the interactive shell.
Console input is normalized before it reaches the agent loop: terminal
backspace/delete controls are applied, control characters are stripped, and lone
Unicode surrogate codepoints are replaced. The journal applies the same UTF-8
safety boundary before canonical hashing/writing, so malformed terminal input
cannot crash a turn.
Use `/thread switch <id>` or `/thread new <id>` inside the interactive console
to move between journal-backed chat threads, `/threads` to list known threads,
`/history [limit]` to show recent user/assistant records for the current
thread, `/settings` to inspect or change live model routing, `/json on|off` to
toggle raw JSON, and `/color on|off` for ANSI styling.
`/thread new <id>` writes a `chat_thread_event`, so an empty thread is visible
in `/threads` before the first user turn.
Human output prints a colored `processing...` marker and then streams a compact
`steps` block as new journal records are written during the turn. Public phases
are visually separated with stable labels such as `[model]`, `[route]`,
`[reason]`, `[tool]`, `[policy]`, `[observe]`, `[retrieval]`, `[evidence]`,
`[final]`, and `[failure]`; each event line keeps one phase color across both
the label and body, with nested indentation for policy/tool/observation,
retrieval/evidence, and workloop reasoning records. Human-mode command results
also leave a blank line before the next prompt. Final answers highlight
`cite-*` refs, URLs, and bolded important spans in orange. This lets a user see
model packets, public route/action reasons, policy checks, tool calls,
observations, retrieval search/fetch/extract events, evaluator feedback,
workloop decisions, and final/failure records while the turn is running. This is
journal-event streaming, not hidden chain-of-thought or token streaming. Console
colors live in `kernel_v3/chat/theme.py`, separate from command routing and chat
runtime logic.

Interactive model routing can be configured globally or per thread:

```text
/settings
/settings profile speed|balanced|quality
/settings profile quality --global
/settings set planner model pro thinking on effort high target quality
/settings reset
/settings reset --global
```

The global file is `.state/kernel_v3/settings/model.json`. Thread-local
overrides live beside the transcript under
`.state/kernel_v3/threads/<thread_id>/settings.json`. Effective settings start
from the balanced display default: DeepSeek V4 Flash for every processor stage,
thinking disabled, temperature `0.0`, and medium effort. That default is not
treated as a hard lock; Holo's host-owned adaptive generation can still upgrade
when the run asks for a quality/thorough target. User-saved global or thread
settings are applied to the live `ProcessorRouter` before each turn and can
lock the selected model, thinking mode, and temperature for the chosen stages.
`chat.route` stays on Flash with thinking disabled even in quality profile, so
thread routing remains fast while deeper semantic/planning/evaluation/synthesis
stages can be upgraded.

Pending `ask_user` state does not force the next turn to resume the old task in
model-routed chat. The route packet receives the pending task summary, but a
complete standalone request starts a `new_task`; `answer_pending_question` is
reserved for turns that actually provide the missing slot, approval, rejection,
or parameter for the pending task. Conversation recap routes are thread-level
introspection results: they can mention an existing pending task in the recap,
but they do not bind the response header to that task or reprint it as a fresh
`needs input` prompt.

Model planner/provider failures are internal runtime failures, not user
clarifications. AgentRuntime journals the failed processor packet and returns a
`FailureReport` with missing evidence, attempted actions, and a suggested next
action instead of creating a fake pending `needs_user_input` prompt.
ProcessorFabric also opens a per-process provider availability circuit after a
network/unavailable provider failure, so the same agent run does not repeatedly
wait on an unreachable live model API. Subsequent processor results are
journaled as `provider_circuit_open` with the previous redacted error preview.
Likewise, a successful direct/semantic `respond` with user-visible text is a
valid terminal answer when no citation/tool requirement remains; the workloop
does not turn that completed response into a generic "please provide more
information" prompt merely because the evaluator suggested clarification.

`model-packet` is the no-network way to inspect the exact provider envelope:

```bash
holo-v3 model-packet --provider deepseek --task-type semantic.intake --goal "search today's news" --show-prompt
```

Live `chat`, `agent`, and resident model runs use `DEEPSEEK_API_KEY` from
the environment. `HOLO_V3_LIVE_MODEL=1` remains accepted for explicit
live-smoke workflows, but it is not required when the provider key is already
configured. Use `--offline` only for explicit host diagnostics.

`--mode semantic` is the broad safe non-tool recipe for roleplay, professional
framing, strategy, project planning, communication drafting, product/risk
review, and other semantic work that should not be collapsed into workspace.
It grants no tools and no external side effects; model packets can still carry
rich state profiles while the host validates policy, journals, and stops.

Interactive model-backed runs default user-visible text to Chinese when the user
does not clearly request another language. Override this per run with
`--response-language en` or set `HOLO_V3_RESPONSE_LANGUAGE=en`.

```bash
holo-v3 agent "read README.md and summarize it" --response-language zh
```

Live agent/chat/resident runs expose both input/context and output-generation
controls. `--context-profile provider` is the default for live interactive
runs, giving the host packet a provider-scale input budget when the target
model can handle it. `large` and `huge` remain available as explicit smaller
operator caps. `--max-output-tokens provider` omits the provider
`max_tokens` field, while `auto` uses Holo's route defaults and an integer sets
an explicit output cap.
Generation defaults to host-adaptive mode and is latency-oriented by default:
`--generation-mode auto` adjusts thinking, reasoning effort, temperature, and
timeout from the processor task, prompt size, model choice, and
`--latency-target fast|balanced|quality|thorough`. The default `balanced`
target keeps ordinary semantic intake, planning, evaluation, and synthesis on
the lightweight DeepSeek V4 Flash route with thinking disabled, even when the
host provides a large context packet. Pro/thinking is reserved for explicit
`quality` / `thorough` targets or an explicit `--model` / `--thinking`
override. Use `--generation-mode manual`, explicit `--model`, `--thinking`, or
`--temperature` overrides when a run needs fixed generation behavior.
Tool calls remain host-validated after model planning: every tool payload is
checked against the tool manifest schema before execution. `workspace.list`
returns bounded directory entries without shell execution, `workspace.search`
returns bounded preview matches, and `file.read` collects full file evidence
only for explicit file-body reads. Tool or guard failures are journaled as
observations that re-enter evaluator/workloop handling; the agent runtime still
produces a final answer or failure report for the user.
The current DeepSeek V4 router defaults to provider output-token limits for live
interactive routes, so Holo does not clamp capable long-context models unless
the operator explicitly passes an integer `--max-output-tokens`. The processor
system prompt also tells the model to optimize for task completion and answer
usefulness rather than token minimization.

```bash
HOLO_V3_LIVE_MODEL=1 holo-v3 agent "inspect a large workspace file" \
  --context-profile provider \
  --latency-target thorough \
  --max-output-tokens provider \
  --temperature 0.2
```

Live retrieval is host-owned and bounded. Online `chat`, `agent`, and resident
`run/run-once` automatically enable a safe web-discovery surface with
`bing_html,duckduckgo_html`, aggregate search, and fetch permission only for
URLs returned by those search providers. `--live-retrieval` is still available
as a per-command authorization surface, and `--no-live-retrieval` disables live
retrieval even in online chat. Network fetches still require `PolicyGate`
permission, fetch budgets, and either host allowlists, discovered web-search
result permission, curated source-directory allowlists, or the explicit
`--live-allow-all-hosts` smoke-test override. Do not add fake sources to make a
live run look successful.

For real research work, live defaults are intentionally roomy rather than
demo-sized: the total live network budget defaults to `409600`, while each
`retrieval.run` defaults to at most `4096` fetch attempts before source ranking
and provider limits. The finance fundamentals profile defaults to `deep`, and
that depth expands retrieval to `128` queries, `5000` ranked sources, `2048`
fetches, and `64` spans per document before the retrieval operator's global
safety caps. These are ceilings, not mandatory spend; the loop now accounts
for actual fetch attempts when a retrieval report is available. Planner
decisions, provider output, ranking, evidence sufficiency, repetition, and
loop guards still decide when to stop.

Live fetched-body size defaults to `16 MB` per response
(`HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES` / `--live-max-bytes`). This is large enough
for common official structured payloads such as SEC companyfacts JSON while
still keeping raw bodies in ArtifactStore and out of planner/evaluator context.
Operators can tighten this for constrained environments or raise it for
specialized deployments.

Fetch is parallelized inside `RetrievalOperator` with bounded
`fetch_concurrency` while ArtifactStore writes and journal records remain in
rank order. Search query execution remains ordered because provider diagnostics
are stateful; provider-level fanout should be implemented inside aggregate or
adaptive search providers where each child provider can report its own
diagnostics safely.

The live retrieval chain is now broader than a single search endpoint:

- `direct_url_search` extracts safe user/host supplied URLs without network
  access;
- `live_web_search` can be enabled with
  `HOLO_V3_LIVE_WEB_SEARCH_PROVIDERS` or `--live-web-search-provider`. It uses
  bounded HTML search discovery providers such as `duckduckgo_html`,
  `duckduckgo_lite`, and `bing_html` to produce safe `SearchSource` candidates.
  Search-result pages are not treated as evidence by themselves; the existing
  fetch, artifact, extraction, evidence, citation, and sufficiency pipeline must
  still validate the discovered pages;
- `bounded_crawl_search` can discover links from explicit seed URLs only when
  live retrieval is enabled by `--live-retrieval` or
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
- `fred_structured_search` generates official FRED series-page and CSV
  observation candidates from host/model-supplied `fred_series_id` metadata. It
  performs no network request by itself and rejects unsafe series identifiers;
- `fiscaldata_structured_search` generates official US Treasury FiscalData API
  candidates from host/model-supplied `fiscaldata_api_path` metadata. It
  performs no network request by itself and validates the endpoint path plus
  query parameters;
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
- `live_http_fetch` can optionally allow safe URLs discovered by
  `live_web_search` via `HOLO_V3_LIVE_FETCH_DISCOVERED_SEARCH_HOSTS=1` or
  `--live-fetch-discovered-search-hosts`. This is narrower than
  `--live-allow-all-hosts`: only URLs marked as web-search results are eligible,
  and normal scheme, credential, secret-like URL, size, timeout, artifact, and
  network-budget checks still apply. The CLI enables this dynamic fetch mode by
  default when a live web search provider is explicitly configured;
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

The built-in research source directory is the host-owned catalog of trusted
entry points. It is separate from web search: the directory tells Holo where a
profile should look first, while the corpus stores fetched, artifact-backed
documents for fast local reuse.

For finance fundamentals, the current trusted catalog includes primary sources
such as SEC EDGAR filings, SEC CompanyFacts/submissions, SEC financial statement
datasets, issuer investor-relations pages, CNINFO/SSE/SZSE, HKEX, Companies
House, SEDAR+, ASX, EDINET, SGX, FRED/BEA/BLS, World Bank/IMF/BIS/OECD, central
bank portals, US Treasury/FiscalData, and fund/ETF disclosures. It also includes
secondary market/news context such as Yahoo Finance, Nasdaq, MarketWatch,
Reuters, Bloomberg, Financial Times, CNBC, AP, transcript aggregators, and
credit-rating agency entry points. Secondary sources do not satisfy
primary-source requirements by themselves.

Inspect the trusted source directory:

```bash
holo-v3 sources list --profile finance_fundamentals --authority primary
holo-v3 sources families --profile finance_fundamentals
holo-v3 sources plan "NVIDIA 10-K fundamentals revenue margin SEC filing" \
  --profile finance_fundamentals
holo-v3 sources seeds --profile finance_fundamentals --family treasury_data
```

`sources plan` is the fast website-index route. It hashes the user query in
the returned payload and ranks trusted sites by task/source metadata, so the
agent can prefer official filing/statistics/issuer portals before using generic
web search. It is not a table of answers and it does not treat source pointers
as evidence.

Build or refresh a local high-speed corpus from real fetched documents:

```bash
holo-v3 retrieve "AAPL 10-K revenue and margin" \
  --live-retrieval \
  --live-web-search-provider bing_html \
  --live-search-strategy aggregate \
  --profile finance_fundamentals \
  --artifact-log kernel_v3/.holo-v3-artifacts.jsonl \
  --corpus-log kernel_v3/.holo-v3-corpus.jsonl \
  --corpus-index kernel_v3/.holo-v3-corpus.sqlite \
  --index-corpus

holo-v3 retrieve "AAPL 10-K revenue" \
  --from-corpus \
  --profile finance_fundamentals \
  --artifact-log kernel_v3/.holo-v3-artifacts.jsonl \
  --corpus-log kernel_v3/.holo-v3-corpus.jsonl \
  --corpus-index kernel_v3/.holo-v3-corpus.sqlite
```

For crawl-only live inspection:

```bash
holo-v3 retrieval-providers --mode live-http \
  --live-retrieval \
  --live-crawl-seed-url https://api-docs.deepseek.com/ \
  --live-search-allowed-host api-docs.deepseek.com \
  --live-fetch-allowed-host api-docs.deepseek.com
```

For general web search discovery without a JSON search API:

```bash
holo-v3 retrieval-providers --mode live-http \
  --live-retrieval \
  --live-web-search-provider default \
  --live-search-strategy aggregate
```

For a model-backed general web lookup, keep the model in the planner/evaluator
role and let the host execute the web search/fetch/evidence pipeline:

```bash
holo-v3 agent "搜索一下今天的热点新闻，并给出来源" \
  --mode retrieval \
  --planner model \
  --evaluator model \
  --synthesizer model \
  --live-retrieval \
  --live-web-search-provider default \
  --live-search-strategy aggregate
```

For finance-profile crawl seeded by the curated source directory:

```bash
holo-v3 retrieval-providers --mode live-http \
  --profile finance_fundamentals \
  --live-retrieval \
  --live-search-strategy adaptive \
  --live-crawl-source-directory \
  --live-source-directory-allowlist \
  --live-crawl-max-source-directory-seeds 4
```

For multi-provider research, set:

```bash
holo-v3 retrieval-providers --mode live-http \
  --live-retrieval \
  --live-search-strategy aggregate \
  --live-search-max-sources-per-provider 3 \
  --live-allow-all-hosts
```

The default remains `fallback` to preserve narrow live-smoke behavior.

For a model-backed live retrieval run, the model still only proposes
`retrieval.run`. The host binds execution metadata such as `max_fetches`,
`max_network_fetches`, research profile, and allowlisted network permission
before `PolicyGate` and loop guards see the action:

```bash
holo-v3 agent "上网检索DeepSeek API文档，概括模型和鉴权方式" \
  --mode retrieval \
  --planner model \
  --evaluator model \
  --synthesizer model \
  --live-retrieval \
  --live-crawl-seed-url https://api-docs.deepseek.com/ \
  --live-search-allowed-host api-docs.deepseek.com \
  --live-fetch-allowed-host api-docs.deepseek.com \
  --live-max-network-fetches 2
```

Current live crawl/search is still bounded by design: it can prove the loop,
permissions, artifact storage, evidence, citations, and synthesis path. It now
has both open web search discovery and seed/sitemap crawl discovery, while raw
fetched HTML remains in `ArtifactStore`. Deeper readability heuristics and
more finance-specific source adapters remain future capability layers.

Retrieval sufficiency is stricter than "any citation exists". The retrieval
evaluator derives explicit query facets such as model, authentication, pricing,
token, endpoint, and rate limits, then requires extracted evidence to cover the
requested facets before the workloop may finalize. Missing facets are journaled
in `retrieval_evaluation_decision`, `retrieval_report`, `evidence_sufficiency`,
and the next planner feedback.

Recent live smoke, using real DeepSeek model calls and real
`api-docs.deepseek.com` crawling, completed this path:

```bash
holo-v3 agent "上网检索DeepSeek API文档，说明模型和鉴权方式" \
  --mode retrieval \
  --planner model \
  --evaluator model \
  --synthesizer model \
  --semantic-intake model \
  --live-retrieval \
  --live-crawl-seed-url https://api-docs.deepseek.com/ \
  --live-search-allowed-host api-docs.deepseek.com \
  --live-fetch-allowed-host api-docs.deepseek.com \
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
The same profile layer now supports non-finance research. For example,
`technical_documentation` defines official documentation/source repository/
standards-body authority, endpoint/authentication/parameter/response/rate-limit
facets, docs-specific query expansion, and evidence compaction. It still uses
the same planner packet shape, PolicyGate validation, RetrievalOperator,
EvidenceEvaluator, and synthesizer citation checks.
When a prior SEC submissions/company metadata step exposes an accession number
and `primaryDocument`, the next retrieval payload can carry those fields and
the SEC provider will construct the direct `Archives/edgar/data/...` filing
document URL. This lets a fundamentals loop move from metadata discovery to
the original 10-K/10-Q filing body without asking the model to invent SEC path
rules. The agent also derives `agent_replan_hints.retrieval.suggested_filing_documents`
from journaled SEC submissions extraction spans, so a live planner can see a
host-built suggested payload for the next `retrieval.run` without reading raw
artifact bodies or bypassing PolicyGate. The dynamic model-planner regression
now covers this loop: first retrieve SEC submissions metadata, recompile
context with the continuation hint, then have the next `planner.propose` use
the hinted payload to fetch the original filing document.
Market-news, market-data, and competitive-landscape finance intents use the
same profile directory but set a different source authority requirement:
secondary-or-better sources can satisfy those tasks, while fundamentals still
require primary sources. The retrieval report records that requirement in
diagnostics so an operator can see why a Reuters/Yahoo-style result was
accepted for news/market context but would not satisfy a primary filing claim.
Issuer identity normalization is still offline and deterministic: it can use
host metadata, query text, and injected ticker-to-CIK maps, but it does not call
external services or claim that an unresolved company has been verified.
For official macro data, a loop can first use a source-directory FRED search
URL, then derive `agent_replan_hints.retrieval.suggested_macro_series` from
journaled extraction spans such as `series_id=CPIAUCSL`. The next
`planner.propose` can use that suggested payload to call `retrieval.run` with
`fred_series_id`, and the host `fred_structured_search` provider builds the
official series page and CSV candidates. This keeps the model in charge of the
semantic next step while the host owns URL construction, ranking, artifacts,
citations, and stop conditions.
For US Treasury/FiscalData tasks, the same pattern exists through
`agent_replan_hints.retrieval.suggested_fiscaldata_endpoints`: after a dataset
discovery step exposes an official `/services/api/fiscal_service/...` path in
extracted spans, the next model planner packet can propose a normal
`retrieval.run` payload with `fiscaldata_api_path`, and the host
`fiscaldata_structured_search` provider constructs the bounded API candidate.
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
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase109_research_employee_core.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase110_active_memory_recall.py
.venv/bin/python -m pytest -q tests/test_kernel_v3_phase120_host_situation.py
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
