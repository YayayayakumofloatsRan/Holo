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

## Interactive Chat CLI

`holo-v3 chat` is the human entry point over the same journal-backed
`ChatRuntime`; it does not add another decision layer. In a terminal, chat
renders compact colored status headers, task/run refs, answers, pending
questions, and trace counts. Machine paths stay stable: `--once` and piped
stdin emit JSON by default unless `--output human` is requested.

The interactive console has local commands for thread and display management:
`/thread switch <id>`, `/thread new <id>`, `/threads`, `/json on|off`,
`/color on|off`, and `/quit`. These commands only select the journal-backed
thread or change rendering; runtime commands such as `/status`, `/summary`,
`/trace`, `/plan`, and `/memory` are still handled by `ChatRuntime`.

## Adaptive Processor Generation

Live processor calls pass through a host-owned generation policy before the
request reaches a provider. In `--generation-mode auto`, the policy derives a
small `generation_policy` diagnostic from processor task type, prompt length,
and `--latency-target fast|balanced|quality|thorough`, then adjusts thinking,
reasoning effort, temperature, and timeout for that call. Defaults are
quality-oriented: `balanced` keeps reasoning enabled for semantic intake,
planning, evaluation, and synthesis, while `fast` is the explicit low-latency
path. The host does not add a `max_tokens` cap by default when
`--max-output-tokens provider` is used, so capable long-context models are not
artificially shortened. Explicit controls such as
`--generation-mode manual`, `--thinking enabled|disabled`, or `--temperature`
remain user overrides.

This is not an intent table. It does not classify user phrases. It only tunes
provider packet shape after the host has already chosen the processor task and
compiled the prompt.

Tool execution is bound to the policy decision for the exact action. A
`PolicyDecision` with `allowed=True` cannot be reused for a different
`action_id`; `ToolRegistry` blocks that as `policy_decision_action_mismatch`
before calling the tool executor. This keeps direct registry callers aligned
with the loop's host-owned validation path.

## Tool Payload Boundary

Planner output is not trusted as executable tool input merely because the tool
name is allowlisted. `ToolRegistry` validates payloads against each
`ToolManifest.input_schema` after policy binding and before executor dispatch.
Schemas can define required fields, simple types, bounds, and safe aliases. For
example, `workspace.search` requires a non-empty `query` and may canonicalize a
model-proposed `path` alias into that query; `file.read` requires a non-empty
workspace-relative `path`.

This boundary is what lets live model planning remain broad without turning
minor JSON-shape mistakes into runaway side effects. Invalid payloads become a
blocked observation with `reason=invalid_tool_payload`, which re-enters the
normal evaluator/workloop path instead of bypassing host control.

Workspace search is intentionally lightweight. It skips internal runtime and
VCS directories, caps matches, and stores only preview artifacts for search
results. Full file bodies are collected only by `file.read`, where the
workspace finalizer can turn the read observation into evidence and citations.
This keeps the multi-step loop from exhausting artifact budgets before the
agent can perform the follow-up read.

Workspace writes are now first-class host tools, not side effects hidden in a
planner response. `workspace.write` requires a workspace-relative `path` and a
complete UTF-8 `text` payload. The manifest marks `text` as
`journal=preview_hash`, so action records and plan previews keep only bounded
preview/hash/length metadata while the raw body belongs to the artifact/write
path. The write recipe may read/search first, then writes once and stops after
the host observes the write.

System-state tools are a separate capability family from workspace. For
example, a live semantic processor may return a packet with
`suggested_mode="system_answer"`, `required_capabilities=["system.time"]`, and
`metadata.capability_args={"system.time":{"timezone":"UTC"}}`. The host turns
that into a `system.time` tool call, journals a `system_time` observation,
counts it as `new_system_observation`, and finalizes from that observation.
This makes host state explicit without giving the model shell access or hidden
environment reads.

## Context Redaction Boundary

`ContextPackCompiler` is the last host-owned boundary before planner,
evaluator, router, or synthesizer processors see task context. Its redactor
handles project private-path markers, explicit secret keys, bearer/API-token
patterns, and secret-like URL query values inside ordinary strings. This means
artifact metadata, citation URIs, observations, and compact context sections
are rechecked before they can enter model-visible context, even if an upstream
provider or tool omitted a privacy projection. Raw artifact blobs remain in
`ArtifactStore`; model context receives bounded refs, previews, hashes, and
redacted metadata.

Trace rendering uses the same secret-like redaction for dynamic operator text
such as action payloads, retrieval query/URI fields, evidence previews,
feedback missing-evidence entries, and guard data. The journal remains the
source of truth, but the default inspection surface avoids turning audits into
a secret disclosure path.

The loop's main journal path also applies the same boundary before writing
secret-like dynamic fields. User input records, task input summaries, action
payloads, observations, feedback, guards, and final result payloads keep their
structure, but secret-like strings are replaced with redaction markers and a
raw data hash. The in-process action/observation objects still flow through
PolicyGate, ToolRegistry, and evaluators unchanged; the durable audit record
does not persist the secret text.

`ChatRuntime` uses the same shared journal redaction helper for chat turns,
routing decisions, command records, pending-user answers, agent results,
semantic task-plan decisions, and thread summaries. This keeps thread continuity
auditable without letting chat history or summaries become a second secret
storage path.

Processor adapters redact prompt payloads before serialization, and
`ProcessorFabric` runs processor request/result journal projections through the
same helper. Live providers therefore do not receive obvious secret-like URL
tokens from planner/evaluator/synthesizer context, and processor trace records
keep only bounded previews, hashes, usage, and redaction metadata.

## Semantic Task Graph

Model-backed semantic intake is now normalized into a host-visible
`TaskGraphProposal` and `TaskExecutionPlan` before an agent recipe is selected.
This graph/plan layer is not an execution engine. It is an audit and validation
layer over the model's proposed semantic structure:

- each proposed task node carries kind, goal, dependencies, capabilities,
  evidence requirements, a suggested recipe mode, and a host-derived
  semantic `state_profile`;
- the host validates blocked capabilities, dependency integrity, node limits,
  and whether user confirmation is required;
- `AgentRuntime` journals `semantic_task_graph` with both the proposal and the
  validation decision;
- `AgentRuntime` journals `semantic_task_plan` with ordered host-visible steps,
  approval requirements, blocked capabilities, and a confirmation prompt;
- `LoopControllerV3` still receives only the selected recipe, planner,
  PolicyGate, registry, and evaluator. It remains tool-name-agnostic.

This is the anti-table path for compound and open-ended requests. The fake
semantic fallback stays conservative, while model mode can propose broad task
structure through JSON and the host validates it before anything runs.

Semantic intake is intentionally capability-driven. Model mode may emit an
open `kind` / semantic label such as a domain-specific research or operator
task; the host no longer collapses unknown labels into `direct_answer`. The
task graph preserves that label for audit, then compiles execution from
`required_capabilities` such as `retrieval.run`, `workspace.search`, or
`file.read`. Unknown labels with safe read capabilities can still select the
right recipe, while unknown labels that request blocked capabilities remain
non-executable and require user confirmation or scope reduction. This keeps
open-ended semantics in the processor layer and keeps permissions, tools,
evidence, and termination in the host layer.

The execution `mode` is only a recipe selector, not the full agent state
space. Each semantic node also receives a broader operating-state profile with
axes such as `goal_structure`, `dependency_state`, `commitment_state`,
`preference_state`, `memory_scope`, `planning_depth`, `operation_runtime`,
`quality_bar`, and `interruption_policy`. These axes let live model packets
describe roleplay, professional advice boundaries, finance research,
resident/background work, preference application, human-world requests, and
unconfigured connectors without inventing tools. The host still decides which
parts can execute, which require approval, and when the loop should stop.

`semantic_answer` is the broad safe non-tool recipe. It is used when model
semantic intake explicitly chooses a broad semantic task surface, or when the
operator selects `--mode semantic`. It does not grant tools, network, memory
commit, transport, browser, shell, or device access. Its purpose is to stop
collapsing roleplay, professional framing, operations planning, product/risk
review, communication drafting, project planning, and other Hermes-level
semantic categories into either `workspace_answer` or a generic direct fallback.
The planner still emits a normal `respond`/`ask_user` packet, and the host still
owns validation, journal, progress, and termination.

When a semantic node needs concrete tool arguments, model mode can place them in
`metadata.capability_args` keyed by capability name. For example,
`{"workspace.search":{"query":"overview"},"file.read":{"path":"README.md"}}`
lets the host run a workspace read without guessing a filename from free text.
These arguments are still only proposals: the plan records them for audit, the
recipe turns them into bounded `CandidateAction` payloads, and `PolicyGate` plus
`ToolRegistry` remain responsible for validation and execution.

Capability arguments may be plural. If the model returns a list such as
`{"file.read":[{"path":"docs/a.md"},{"path":"docs/b.md"}]}`, the host expands
that one semantic node into multiple ordered `file.read` actions. The recipe
budgets, work plan updates, repetition checks, and finalizer all see the real
expanded action count. This is how the current loop can run 10+ useful
iterations from one broad instruction while still knowing when the plan is
complete.

The same plural payload contract now applies to retrieval. A model semantic
packet may place an array under `metadata.capability_args["retrieval.run"]`,
for example one payload for official revenue filings, one for issuer margin
materials, and one for competitive landscape context. `AgentRuntime` expands
those payloads into separate ordered `retrieval.run` actions, preserves the
payload metadata such as research profile and source-authority requirements,
and lets the existing workloop decide `continue` or `final_answer` after each
observation. This gives LLM-driven planning a broad research interface without
letting the model bypass PolicyGate, source budgets, evidence sufficiency, or
termination guards.

For host-planned retrieval subgoals, sufficiency is aggregated by planned
`goal_id`. A later successful retrieval cannot hide an earlier failed subtopic:
the workloop records `planned_retrieval_coverage` in `evidence_sufficiency`,
and finalization checks that every latest `goal-plan-*` retrieval report is
`sufficient`. If any planned subgoal is missing or insufficient after the plan
is exhausted, `AgentRuntime` returns a `FailureReport` with
`retrieval_subgoal:<goal_id>` missing evidence instead of synthesizing an
unsupported complete answer. Dynamic retry/replan paths remain safe because a
new report for the same planned `goal_id` replaces the older status.

Dynamic model planner mode receives the same coverage signal through
`state.agent_replan_hints`. Planned retrieval goal ids are derived from the
semantic task plan as well as executed actions, so the model can declare a
multi-subgoal research plan first and then execute it one bounded action at a
time. If one planned subgoal is insufficient while a later subgoal succeeds,
the next planner packet still has `status=needs_replan`,
`incomplete_planned_goal_ids`, and `do_not_finalize_until` rules for the failed
subgoal. A model can then retry only that `goal_id`, and host finalization will
allow synthesis once the latest report for every planned goal is sufficient.

The first planner packet also receives `state.agent_retrieval_plan_state`. This
is the low-noise work-plan view for retrieval: it lists `planned_subgoals`
with their `goal_id`, query preview, research profile, authority requirement,
and strategy; it also lists pending, complete, and incomplete goal ids plus a
`next_recommended_goal_id`. Model planner mode should propose one bounded
`retrieval.run` action using that `goal_id`. This lets the LLM choose and update
work over broad research state without relying on a hidden phrase table or
parsing raw journal history.

Inside a single retrieval payload, the model may also provide explicit
`queries` or `query_templates`. These are search attempts for one subgoal, not
separate agent actions. If `max_queries` is omitted, the host derives the
default query budget from the explicit list length, then still applies global
retrieval caps. This prevents a good model packet such as
`{"queries":["generic query","official filing query","issuer IR query"]}` from
being accidentally truncated by a light research-depth default, while still
letting an explicit `max_queries` field intentionally tighten the budget.

Model planner mode can also run as a dynamic workloop instead of a pre-expanded
static plan. In that path, every loop iteration recompiles context, sends the
latest feedback and journal-derived state to `planner.propose`, receives one
candidate action, and journals an `agent_work_plan_update` with the model's
selected next action. The first planner call also journals an `agent_work_plan`
with `strategy=dynamic_replan_each_iteration`, the allowed tools, and the host
loop budget. This gives the model room to choose the next step from new
observations while preserving host-owned policy checks, repetition detection,
evidence sufficiency, loop guards, and termination.

Dynamic planner loops are still bounded. Model planner mode raises the default
workspace/retrieval/write loop ceilings enough for long tasks, and callers can
set explicit `agent_loop` metadata or CLI flags such as `--max-agent-steps`,
`--max-agent-tool-calls`, and `--max-agent-artifact-bytes`. These limits are
host configuration, not model authority. If the evaluator asks to continue but
the loop stops making progress, repeats the same payload, or exceeds a guard,
the workloop returns a failure report instead of running forever.

After an insufficient retrieval iteration, the next planner context includes
`state.agent_replan_hints`. This is a compact journal-derived packet, not model
memory and not a tool. It records the latest feedback, evidence sufficiency,
retrieval report status, missing query facets, source-authority gaps, attempted
queries/provider ids/search strategies, recent action payload hashes,
suggested query/search-strategy changes, ranked `suggested_source_targets` for
profiled research, and `do_not_finalize_until` rules.
The planner contract tells live models to use this packet to propose one
materially different safe action and avoid final answers while host evidence
rules are unmet. The host still enforces PolicyGate, repetition detection,
evidence sufficiency, and final termination.

For finance-profile retrieval, `suggested_source_targets` comes from the
curated source directory ranked against the current query, missing evidence,
and source-authority requirement. It gives the next planner packet source ids,
source families, authority levels, base URLs, query/crawl hints, template ids,
and host-owned payload metadata such as `search_strategy`; it does not include
raw fetched bodies or make those sources executable without a normal
`retrieval.run` action.

For SEC fundamentals loops, the same replan packet can include
`retrieval.suggested_filing_documents`. These are derived from journaled
extraction spans of SEC submissions JSON, not from raw artifact bodies. Each
entry carries CIK, accession number, optional `primaryDocument`, form/report
date, and a suggested `retrieval.run` payload that will route through the SEC
structured provider to the official Archives filing document. The model still
only proposes that payload; the host validates, fetches, stores artifacts, and
decides whether the evidence is enough.

For macro-data loops, `retrieval.suggested_macro_series` follows the same
boundary. It is derived from extraction spans such as `series_id=CPIAUCSL`, then
offers a normal `retrieval.run` payload carrying `fred_series_id`, primary
source requirements, macro-data task kind, and `search_strategy="structured"`.
The `fred_structured_search` provider converts that metadata into official FRED
series-page and CSV candidates; it does not fetch the network itself or bypass
ranking, artifacts, citations, or termination policy.

Treasury/FiscalData continuation uses the same shape through
`retrieval.suggested_fiscaldata_endpoints`. It is derived only from extracted
spans containing an official `/services/api/fiscal_service/...` path. The
suggested payload carries `fiscaldata_api_path`, primary-source requirements,
macro-data task kind, and structured search strategy; the
`fiscaldata_structured_search` provider then constructs the bounded official
FiscalData API URL with safe query parameters.

The capability catalog in context is intentionally broader than the currently
enabled tool set. It exposes conversation, roleplay, document/report work,
workspace, retrieval, web research, finance, legal, medical, education,
creative, communication, operations, product, risk, cybersecurity, memory,
artifact, data, database, code, cloud, workflow, knowledge-base, multimodal,
project, resident, transport, calendar, browser/session boundaries, system,
and security families with statuses such as `enabled`,
`available_with_permission`, `not_configured`, `planned`, and `host_only`. It
also exposes state axes such as intent scope, execution surface, evidence,
permissions, output contract, resident state, user control, autonomy, world
model, resource kind, action phase, temporal status, source authority, identity
boundary, communication channel, and risk. The planner context now receives a
compact `semantic_state_space` snapshot derived from that catalog, so live
model packets can describe broad Hermes-style tasks without reducing every
state to `workspace:*`. This is not a phrase table: the model chooses broad
semantic labels and capability ids; the host maps only known executable
capability families to recipes and keeps planned, host-only, credential,
transport, browser, and device boundaries out of `ToolRegistry`.

Each task-graph node also gets a compact `metadata.state_profile`. The profile
records `domain`, `activity`, `resource`, `execution_surface`,
`permission_state`, `route_class`, capability families/statuses, evidence
posture, output contract, autonomy, risk posture, and expandable `state_axes`.
`AgentRuntime` passes a top-level `semantic_state_profiles` list and
`semantic_state_profile_summary` into planner context, and journals the same
projection as `agent_state_profile`. This gives model-backed planning a richer
state interface than the recipe mode alone: a single node can carry, for
example, both `workflow` and `knowledge_base` capability families, while the
host still marks `knowledge_base.maintain` as planned/non-executable. The
state-profile vocabulary is kept in sync with the declared
`semantic_state_space`, so profile values such as `legal_source`,
`medical_source`, `message_draft`, `workflow_run`, `database_table`,
`cloud_resource`, `media_input`, `external_account_boundary`, `planned`,
`host_only`, and `failure_or_boundary_report` are explicit host-visible states
rather than ad-hoc strings hidden in test fixtures.

Non-workspace research capabilities can still become executable when there is
a safe host route. For example, `web.research`, `finance.market_news`,
`finance.market_data`, and `finance.competitive_landscape` compile to the
retrieval recipe and `retrieval.run` rather than being collapsed into
workspace mode. Conversely, high-risk capabilities such as
`device.input.control`, live transports, browser session attachment, direct
credential reads, and shell execution remain host boundaries even if the model
names them correctly.

Live retrieval can be cache-first when a research corpus is configured. The
live operator now accepts the same `ArtifactStore` and `ResearchCorpusStore`
that `AgentRuntime` uses. Its search chain checks `research_corpus` before
direct URLs, structured source providers, source-query templates, JSON HTTP
search, crawl discovery, and source directories. Its fetch chain routes
`research_corpus` sources back through `ArtifactStore` and uses live HTTP only
as the fallback. Newly fetched live pages are still written to artifact blobs
and indexed into the corpus by `RetrievalOperator`, so a later agent loop can
reuse previously fetched evidence without another network call.

When the live search strategy is configured as `adaptive`, the model planner
may propose `retrieval.run.payload.metadata.search_strategy` for the next
bounded retrieval action. Supported values are `fallback`, `aggregate`,
`corpus_only`, `fresh_live`, `structured`, and `crawl`. These values only select
among host-configured search providers. They do not create new tools, grant
network permission, bypass fetch allowlists, or weaken evidence/termination
gates. This is the search-side counterpart to dynamic work plans: after
feedback such as `primary_source` or `query_facet:*`, the next planner packet
can choose a materially different search path while the host still executes one
bounded action at a time.

Finance research capabilities share one source-directory substrate but do not
share one sufficiency rule. `finance.fundamentals_research` keeps the strict
primary-source requirement for filings, issuer materials, exchange disclosures,
and official statistics. `finance.market_news`, `finance.market_data`, and
`finance.competitive_landscape` set `source_authority_requirement` to
`secondary_or_better`, so reputable news and market-data providers can satisfy
current-news or quote-context tasks without being misrepresented as primary
filing evidence. The retrieval report records the effective authority
requirement and source-authority counts.

When retrieval evidence is insufficient, the workloop converts host-derived
retrieval diagnostics into planner feedback. Missing query facets appear as
`query_facet:*`; missing authority now appears as `source_authority:primary`,
`primary_source`, or `source_authority:secondary_or_better` as appropriate.
Model planner mode receives those exact gaps on the next `planner.propose`
packet. The model can then propose a materially different query/source, while
the host still validates policy, source/fetch budgets, progress, repetition,
and final termination.

Model planner actions are also rebound to recipe constraints before execution.
For example, a live model may propose only `{"name":"retrieval.run",
"payload":{"query":"..."}}`; the host then merges the recipe's execution
metadata such as `max_fetches`, `max_network_fetches`, research profile, and
interaction preferences before the action reaches `PolicyGate` and loop guards.
This keeps model packets broad and semantic while keeping budgets and
permissions host-owned.

Live retrieval is one of the expanded non-workspace state spaces. The agent can
enter a network retrieval recipe, use host-configured direct URL, JSON search,
bounded crawl, sitemap discovery, source-directory, corpus, and fetch
providers, then return evidence/citations into the same workloop termination
path. Crawled HTML is stored raw as artifacts but evidence spans are extracted
from readable body text, so downstream evaluator/synthesizer packets see
citations instead of raw page chrome.

Text-based PDF fetches are handled the same way: the raw PDF body remains in
ArtifactStore, while retrieval extracts readable PDF string literals into
evidence spans marked `pdf_text_literals`. Scanned PDFs or compressed PDFs that
do not expose readable text simply produce insufficient evidence and must be
handled by later OCR/readability tooling rather than guessed answers.

Structured JSON and CSV fetches also receive readable projections before span
ranking. SEC companyfacts-style JSON is flattened into path/value lines, while
CSV rows become header/keyed row text. Raw structured payloads remain artifacts;
planner/evaluator/synthesizer packets see only extracted spans and diagnostics
such as `json_readable_text` or `csv_readable_text`.

Bounded crawl can now be seeded from the curated finance source directory when
the host explicitly sets `HOLO_V3_LIVE_CRAWL_SOURCE_DIRECTORY=1`. With
`HOLO_V3_LIVE_SOURCE_DIRECTORY_ALLOWLIST=1`, live retrieval merges concrete
source-directory hosts into crawl/fetch allowlists. This lets a planner choose
`metadata.search_strategy="crawl"` for a finance-profile retrieval action and
have the host discover pages from SEC, Treasury, central-bank, fund-disclosure,
or other curated entry points without hard-coding those URLs in planner output.
The setting is still opt-in, redacted in diagnostics, and bounded by the same
network, source, fetch, artifact, sufficiency, and termination guards.

Bounded crawl discovery now ranks discovered page and sitemap candidates
against query/metadata terms before applying the source budget. Seed URLs stay
visible as provenance, but if a page exposes many links the crawler prefers
query-matching research pages over generic navigation links. This improves the
agent loop under small `max_sources`/`max_fetches` guards without adding a
site-specific phrase table.

Live retrieval can also use an aggregate search strategy. In fallback mode, the
first provider that returns any source wins. In aggregate mode, the host asks
each enabled provider for a bounded number of sources, deduplicates by URI,
then ranks the combined set by query match and research-profile source
authority before returning sources to the retrieval operator. This prevents a
low-authority generic result from consuming the pre-rank source budget when a
later provider has a primary filing, corpus document, or source-directory
entry. The mode is explicit through live retrieval config and remains host
controlled; the model still proposes only `retrieval.run`.

## Durable Memory Boundary

Durable memory uses a split audit model. `MemoryStore` is the memory subsystem's
append-only fact log and can retain the approved memory item/proposal payloads
needed for replay and export. The task Journal remains the agent run audit
surface, so `MemoryPipeline` journals only memory manifests: ids, scope,
state, provenance refs, risk flags, preview/hash/length fields, and redaction
metadata. Shadow candidates, proposals, committed items, and tombstones do not
duplicate full candidate text, proposed item bodies, or deletion reasons into
the main Journal. Approval is still host controlled, and secret-like candidates
are rejected before a shadow candidate or proposal is recorded.
`MemoryStore.inspect()` follows the same operator-facing rule: active, expired,
deleted, and pending proposal samples expose ids, state, scope, and
summary preview/hash metadata rather than full summaries.

## Plan Review Commands

`ChatRuntime` exposes `/plan` as a host-owned review surface for the latest
`semantic_task_plan` in the thread:

- `/plan` or `/plan show` renders the latest model-proposed, host-validated
  plan;
- `/plan reject [plan_id] [reason]` journals a
  `semantic_task_plan_decision` and does not execute anything;
- `/plan approve [plan_id]` journals approval and runs only the first safe
  executable step through `AgentRuntime`;
- `/plan run [plan_id]` repeatedly runs safe executable steps through
  `AgentRuntime` until a host boundary is reached;
- `/plan finalize [plan_id]` builds a plan-level final answer only from
  journaled outputs of completed approved steps.

Approval is deliberately narrow. It does not execute an arbitrary model graph
and it does not bypass `LoopControllerV3`. The selected step must be ready or
waiting for confirmation, use only safe read/respond/ask-user capabilities, and
then it is re-entered through the normal recipe, planner, PolicyGate, registry,
workloop, and finalization path. Blocked capabilities such as shell execution,
workspace writes, live transports, network fetches, and durable-memory writes
remain non-executable in this path.

Plan approval is also step-aware. Approved steps are recorded by
`plan_ref + node_id`, so repeated `/plan approve` calls do not rerun the same
tool step. A later safe step can run only after its dependency node was
approved and completed through the same journaled decision path. Completion is
not inferred from approval alone; the spawned child task must have a journaled
`agent_final_answer` before it can unlock dependent steps. Failed or
needs-user-input child tasks stop the plan run instead of allowing downstream
work to proceed with missing evidence. Dependent
`respond` or synthesis nodes are not executed as standalone direct answers,
because they would not carry the prior step's evidence context; those require a
future explicit plan-level synthesizer/finalizer instead of an implicit direct
fallback.

The plan finalizer is deliberately conservative. It does not call tools, does
not re-run semantic intake, and does not invent citations. It reads completed
approved step decisions, loads their `agent_final_answer` records, preserves
their `citation_refs` and `used_evidence`, and journals
`semantic_task_plan_final_answer` on the original plan task. If a dependency has
not completed, finalization fails with a journaled command result instead of
filling the gap.

For resident-style progress, `/plan run` is the bounded workloop form of plan
execution. It recomputes the next executable step from journal state after each
child task, records every approval as `semantic_task_plan_decision`, and stops
when a child task needs user input, fails, no safe step remains, or the
plan-level finalizer can produce an answer from completed dependency outputs.
Blocked write/shell/live-transport/memory capabilities remain boundaries, not
things to skip silently. `/plan approve` still performs a single-step approval;
if no more safe tool steps remain and finalizer dependencies are complete, it
also converges to the same host finalizer. A repeated approval after
finalization returns the existing `semantic_task_plan_final_answer` instead of
writing a duplicate.

When the active pending question is a host-generated plan confirmation, natural
language approval or rejection goes through the same bounded `chat.route`
processor contract as other turn routing. The provider may propose
`route="answer_pending_question"` with `command="approve_plan"` or
`command="reject_plan"`, and `ChatRuntime` then verifies that a pending plan
confirmation actually exists before mapping it to `/plan approve` or
`/plan reject`. There is no kernel-level phrase table for open-ended approval,
continuation, or summary semantics.

`/plan` also renders journal-derived progress. It reports per-step pending,
approved, completed, blocked, or finalized state from
`semantic_task_plan_decision`, spawned task ids, spawned statuses, dependency
final answer refs, and the plan-level final answer ref when present. This
progress is computed from journal records, not from model memory or hidden
state.

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

Network fetch limits are costed before execution, not only after a tool returns.
For `network` side-effect actions, the loop reads a generic cost from payload
fields such as `max_fetches` / `network_fetch_count`, or from the manifest's
`default_network_fetch_cost`. The loop does not branch on concrete tool names;
this lets a future live retrieval/search operator declare bounded page-fetch
cost without getting a special path in `LoopControllerV3`.

Research profiles can shape retrieval without adding domain logic to the loop.
For example, the finance fundamentals profile contributes primary-source query
templates, source-family preferences, citation requirements, and depth presets
(`light`, `balanced`, `deep`). `AgentRuntime` compiles the selected depth into
ordinary `retrieval.run` payload fields such as `max_queries`, `max_sources`,
`max_fetches`, and `max_spans_per_document`; live retrieval can also carry a
`network_fetch_count` so search and fetch cost are budgeted before execution.
The retrieval operator journals the selected query strategy in
`retrieval_query_plan` and still evaluates sufficiency through evidence,
citations, and source authority.

The finance source directory is not a content database. It is a structured map
of where an agent should search for fundamentals evidence: SEC filings and
companyfacts, company investor-relations pages, official statistics, China/HK
exchange disclosure systems, and secondary market/news sources. When the
finance profile is active, the directory is injected into context as source
metadata so the model can choose better query targets while live search/fetch
still remains opt-in and host-allowlisted.

`research_source_directory_search` is query-aware rather than a static dump of
that directory. It scores source entries against the query, safe task metadata,
source family preferences, source-authority requirements, use cases, query
hints, crawl notes, and entry-declared template match terms before applying the
source budget. This matters when the budget is tight: `finance.market_news`
should surface Reuters/Bloomberg/FT/CNBC-style entries before SEC filings,
`finance.market_data` should surface quote/data portals before generic
filings, and macro/rate research should surface official statistics, central
bank, or Treasury entries. The ranking only changes candidate order and
diagnostics; it does not fetch pages, grant network permission, or make
secondary sources satisfy primary-source requirements.

`research_source_query_search` uses the same ranking substrate after rendering
safe `query_url_templates`. This avoids a subtle failure mode where an earlier
official-search template can echo the whole user query and consume
`max_sources` before a more relevant Reuters, Yahoo Finance, central-bank,
Treasury, transcript, or rating-agency template is considered. The rendered URL
still has to pass placeholder validation and the entry host allowlist first.

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
- `turn_router_mode`

The default remains fully offline fake mode. CLI model modes for
`holo-v3 agent`, `holo-v3 chat`, and `holo-v3 resident run/run-once` are gated
by `HOLO_V3_LIVE_MODEL=1`, then use the configured provider fabric. Operators
can either enable individual model-backed pieces with `--planner model`,
`--semantic-intake model`, `--turn-router model`, and related flags, or use
`--online` / `--live-model` to enable the model-backed semantic stack for an
interactive run. This lets a resident worker use model-backed semantic intake,
turn routing, or planner/evaluator/synthesizer behavior without letting the
worker execute tools directly, bypass PolicyGate, or become a transport-level
decision maker.

`holo-v3 model-packet` renders the exact OpenAI-compatible request envelope the
host would send for a processor task without performing a network call. It
shows provider, model, route parameters, timeout, endpoint, redacted headers,
`response_format={"type":"json_object"}`, optional `thinking` and
`reasoning_effort`, plus a prompt preview/hash. Use `--show-prompt` only for a
local debugging session where the prompt is safe to display. API keys stay in
the process environment and are never written to journal, trace, context, or
packet output.

DeepSeek live runs read `DEEPSEEK_API_KEY` from the environment. In WSL, the
recommended local setup is a private `~/.holo_env` file sourced by `~/.bashrc`;
the file must remain outside the repository and mode `600`.

The OpenAI-compatible/DeepSeek provider path performs bounded retries for
transient network failures such as TLS EOF, timeout, HTTP 429, and HTTP 5xx.
It does not retry bad request errors such as HTTP 400. This prevents a brief
network fault from being misread as an agent loop failure while preserving hard
provider/schema errors as normal failed processor results.

The processor system prompt controls only user-visible text fields inside the
structured JSON result. It keeps technical, legal, financial, and safety
answers rigorous and pragmatic, while allowing ordinary small talk, harmless
roleplay, and light humor to sound more natural and less tool-like. This style
guidance cannot override PolicyGate, evidence/citation requirements, memory
review rules, or host-owned termination.

Memory traces are structured audit views, not memory exports. `memory-trace`
renders candidate/proposal/approval/commit/delete/migration events with ids,
policy/status, privacy class, bounded previews, and hashes. Secret-like memory
candidates that were rejected are shown only by reason, risk flags, and hash.
Memory-write turns remain review-first. When semantic intake asks for
`durable_memory:write`, the host can create a pending memory proposal, then the
pending question and resident outbox name the proposal id and the memory review
commands. The resident worker still does not commit durable memory by itself.

Resident outbox payloads keep a compact `ChatRuntimeResult` manifest. Resident
run results also surface `chat_route`, compact `command_result`,
`pending_question`, and `final_answer_ref` so a supervisor can see whether a
message approved, rejected, finalized, or answered a pending plan without
scraping visible text. Large command payloads such as rendered traces are stored
as preview/hash manifests in resident payloads and resident journal events.
Outbox administration events such as `resident_outbox_ack` and
`resident_outbox_retried` journal the same manifest projection, not the full
reply body or payload.
Resident inbox administration and claim events likewise record transport state,
text preview/hash, and metadata manifests rather than duplicating the full user
message body in resident-specific journal records.
Pending plan-confirmation outboxes are marked `answered` when the user's later
message approves or rejects the plan. Pending-user-input answer marking is
scoped to the answered task id, so multiple waiting questions in the same thread
do not clear each other.
Memory-review outboxes are also cleared only by an explicit successful
`/memory approve <proposal_id>` or `/memory reject <proposal_id>` command whose
command result carries a `resolved_pending` manifest matching that pending
outbox's proposal id. The queue marks those rows by exact outbox id, not by
broad thread state, so unrelated waiting questions remain visible to the
resident supervisor.

Resident loop summaries include the queue health snapshot and scheduler health
used to decide the loop result. A loop no longer reports `completed` when
unresolved failed, dead-letter, failed-outbox, retry-wait, delivery-failed,
pending-user-input, or scheduler-failed work remains after an idle turn. It
reports `failed` for scheduler tick/status failures, unresolved
failed/dead-letter inbox work, or failed agent/command outbox work,
`delivery_failed` for failed outbox delivery, `retry_wait` for delayed retry
work, and `awaiting_user_input` when the next useful step is a user reply. This
keeps long-running supervision from confusing "no claimable message right now"
with a healthy completed queue.

Resident queue inspection is bounded at the queue layer. Health issues and
sample inbox/outbox rows are queried with SQL limits and clamped before
rendering, so a long-running resident database can be inspected without loading
or returning every historical message. Inspection samples are operational
manifests: message text is exposed only as a bounded preview plus length/hash,
and metadata/outbox payloads are value-hash manifests rather than raw JSON
bodies.

Worker exception records also journal the queue state that was actually written
after containment. `resident_inbox_failed` includes `resulting_status`,
`attempts`, and `next_attempt_at_ms`, and its state delta uses `retry_wait`,
`dead_letter`, or the observed queue status rather than a generic `failed`.
This keeps resident traces aligned with the retry/dead-letter state machine.
`resident-trace` renders a bounded tail view by default and reports how many
older resident records were truncated, so trace inspection remains usable after
long resident runs.

The resident scheduler is deliberately below the agent loop. It stores local
schedule records, ticks due schedules, and enqueues normal resident inbox
messages with deterministic message ids. It does not route chat turns, execute
tools, call providers, or synthesize answers. Once a scheduled item enters the
inbox, `ResidentRuntime` handles it through the same `ChatRuntime` and
`AgentRuntime` path as any other message. The `resident schedule-*` commands
are local operator surfaces, not live transport integrations. Long-running
workers can opt into `resident run --tick-schedules` or `resident run-once
--tick-schedules`; without that explicit flag, run and run-once preserve normal
queue-only behavior. Schedule ticks and inspection samples are clamped inside
`ResidentScheduler`, so a large CLI/runtime limit cannot cause one resident
iteration to enqueue or render an unbounded number of schedules. Scheduler
journal records and inspection samples use schedule/message manifests with
text preview/hash and metadata manifests rather than duplicating the full
scheduled prompt body. `resident status` and `resident inspect` include
schedule health, including due schedules
and unbounded recurring schedules, so operators can see whether a resident loop
should run with schedule ticking enabled. When
schedule ticking is enabled and no inbox item is claimable, `resident run`
reports `waiting_for_schedule` instead of plain `idle` if a future active
schedule is still pending; the loop result includes `schedule_status` so a
supervisor can see the next due time.
Resident run loops also accept `--max-duration-ms` as a host-owned wall-clock
budget in addition to `--max-iterations`. Hitting that budget returns
`max_duration_ms` and journals the loop result; it does not let the model decide
termination and it does not change `run-once` semantics.

`resident doctor` is the read-only operator snapshot for long-running work. It
aggregates queue inspection, schedule inspection, and any configured durable
memory, research corpus, or retrieval-provider inspections into one status,
issue list, and action list. It does not create memory/corpus stores unless
their CLI paths are configured, and it does not enqueue, approve memory,
retrieve, fetch, or execute tools. When the journal and artifact store are
configured, doctor also asks durable memory inspection to verify committed
memory provenance refs and artifact refs, using metadata/blob presence checks
only. If a research profile is configured, doctor asks corpus inspection for
that profile's scoped health instead of relying on global corpus health; a
healthy unrelated corpus no longer hides an empty or stale finance corpus.
Retrieval-provider inspection is capability-only: it reports fake/corpus/
future-live provider metadata, network capability, and research-profile support
without running retrieval or reading artifact bodies. Retrieval-provider errors,
such as an empty fallback search chain, are promoted into the doctor status and
recommended actions so a resident supervisor does not mistake an unusable
research configuration for a healthy worker. Doctor also isolates component
inspection failures: if queue, schedule, memory, corpus, or retrieval inspection
raises, the report still returns `error` with the component, failure code,
exception type, and redacted exception message instead of crashing the operator
path. This keeps long-running memory and research operation auditable without
exposing raw artifact payloads.
The CLI `resident doctor` command also appends a compact
`resident_doctor_report` journal record. That record keeps component statuses,
issue codes, recommended actions, selected safe counters, and a hash of the
full returned report; inspection samples and raw payloads are not embedded.
`resident-trace` renders those doctor records with component health, issue
codes, compact action hints, and the report hash, so operator snapshots remain
visible in the same bounded resident trace stream as worker activity.

Crash recovery is outbox-aware. If a worker already wrote an outbox but crashed
or lost ownership before completing the inbox message, a later worker that
reclaims the inbox first checks for the existing `in_reply_to` outbox. When it
finds one, it journals `resident_outbox_recovered`, completes the inbox, and
does not re-run `ChatRuntime` or the agent loop. This prevents duplicated tool
work and duplicated agent journal records after a partial worker failure.

Before writing a new outbox after `ChatRuntime` returns, the worker must renew
its queue lease. Successful renewals are journaled as `resident_lease_renewed`.
If the lease was stolen or expired and reclaimed by another worker, the stale
worker returns `lease_lost_before_outbox` and does not append a reply. This
keeps long-running resident tasks from producing duplicate outbound messages
after ownership changes.

Failed delivery recovery is an explicit resident operation. `resident
retry-outbox <outbox_id>` records retry metadata in the payload and journals
`resident_outbox_retried`. Ordinary reply outboxes return to `ready`. Pending
user-input outboxes remember the state they failed from and return to
`pending_user_input`, so retrying question delivery does not collapse a waiting
question into an ordinary ready reply. Generic `resident ack --status ready` is
not a retry path for failed delivery, and `resident ack --status acknowledged`
cannot clear a `delivery_failed` outbox. Operators must retry delivery first,
then acknowledge the retried outbox after actual delivery. This keeps transport
recovery auditable without treating it as a user acknowledgment.

Natural-language turn routing is processor-shaped rather than phrase-table
driven. A model or fake provider may emit a bounded `chat.route` proposal such
as `summary`, `continue_task`, `continue_plan`, `answer_pending_question`, or
`new_task`; `ChatRuntime` then validates that proposal against the current
thread state and journal. If the proposal asks to continue a plan, the host only
routes to `continue_plan` when an unfinished approved plan exists in the thread,
and it executes the same host-owned `/plan run` path. Finalized plans are not
reused.

Live semantic scenario tests must not include answer-key JSON in provider
prompts. They provide only the contract, task context, host rules, and
acceptance criteria. The local validator checks the returned JSON afterward.
This keeps DeepSeek/OpenAI-compatible smokes from becoming prompt-level
golden-output copying while preserving deterministic fake-provider tests.

## Iteration 2026-05-31

Hardening completed in this iteration:

- blocked model `semantic.intake.response_hint` from becoming a final answer
- made repetition and no-progress detection run-scoped
- made evidence sufficiency and finalization grounding run-scoped
- made failure report attempt/observation summaries run-scoped
- bound recipe action ids to run ids
- removed answer-key JSON from live semantic scenario prompts
- added bounded `/plan run` for journal-driven multi-step plan continuation
- added regression tests for stale retrieval evidence, stale workspace file
  reads, semantic-intake answer leakage, scenario prompt leakage, and
  multi-step plan continuation boundaries

Validation used:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_kernel_v3*.py -q -p no:cacheprovider
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m compileall -q kernel_v3
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/test_public_release_hygiene.py -q -p no:cacheprovider
git diff --check
```

## Iteration 2026-06-01

Hardening completed in this iteration:

- added manifest-validated `workspace.write` as a real host tool with raw body
  kept out of action journal records;
- expanded the capability/state catalog beyond workspace into conversation,
  retrieval, finance, memory, resident, transport, and system families;
- added `system_answer` and `system.time` as an executable non-workspace state
  path;
- added `semantic_answer` as a first-class broad non-tool semantic recipe so
  safe professional, planning, roleplay, communication, product/risk, and
  strategy work can preserve rich state profiles without becoming workspace;
- allowed semantic `capability_args` lists to expand into many ordered tool
  actions, enabling 10+ iteration work plans from one model packet;
- added `agent_work_plan` and incremental `agent_work_plan_update` audit records
  for recipe-driven long loops;
- added finance fundamentals source-directory metadata for domain-directed
  search planning;
- changed DeepSeek V4 live routes to omit provider `max_tokens` by default and
  added bounded retry for transient provider network faults;
- verified live DeepSeek packets for both a 12-file workspace loop and a
  `system.time` task.

Validation used:

```bash
.venv/bin/pytest -q tests/test_kernel_v3_*.py
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -c '<DeepSeek 12-file loop smoke>'
HOLO_V3_LIVE_MODEL=1 .venv/bin/python -c '<DeepSeek system.time smoke>'
```
