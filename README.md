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

For the 2026-06-14 report-ready Kernel v3 project state, finance benchmark
evidence, demo status, known gaps, and near-term roadmap, see
`docs/KERNEL_V3_PROJECT_STATUS_2026-06-14_ZH.md`. For a compact Chinese talk
track and Q&A notes prepared for the recorded Windows browser demo, see
`docs/KERNEL_V3_DEMO_TALK_NOTES_2026-06-14_ZH.md`.
For the current 2026-06-17 finance problem-solving scoreboard and the latest
live rerun notes, see
`docs/KERNEL_V3_FINANCE_RESULTS_SNAPSHOT_2026-06-17.md`. It separates
evidence-backed results, such as FinAgent full40 `38/40` live and `39/40`
rescored, from FinanceBench held-out results that still require a fresh
`test100` run. After provider access was restored, an isolated 2026-06-17
FinanceBench debug rerun on `financebench_id_03029` passed `1/1`
(`numeric_within_tolerance`) with live retrieval, calculator trace, formula
trace, claim ledger, numeric verifier, and synthesis gate active. This is a
single debug-row capability result, not a held-out `test100` score. A later
same-day deep-loop regression was repaired by wiring workbench follow-up
targets into `deep_agent_loop`; the current live rerun
`.state/kernel_v3/bench/finance/fb_debug50_p0gt95_o000_l001_after_evidence_guard_20260617.jsonl`
also passed `1/1`, matching `1577.0` with `retrieval_runs=7`,
`calculator=1`, `formula=1`, verifier `passed`, and `851,272` tokens. This is
a correctness result; efficiency and broader debug50/test100 accuracy are still
open. A follow-up route probe
`.state/kernel_v3/bench/finance/fb_debug50_p0gt95_o000_l001_after_override_20260617.journal.jsonl`
confirmed that workbench follow-up now promotes direct SEC URLs to the primary
`retrieval.run` query and reached `final_answer_ready`, `finance_fact_ledger`,
and `claim_ledger`; it was manually interrupted during a final provider preflight
and produced no benchmark row, so it is loop-route evidence, not an accuracy
score.
The 2026-06-16 framework review is consolidated in
`docs/KERNEL_V3_FRAMEWORK_LESSONS_FINAL_2026-06-16_ZH.md`; use it as the primary
report and talk reference for what Holo should absorb from LangChain,
LangGraph, Semantic Kernel / Microsoft Agent Framework, Hermes Function
Calling, HERMES Math Agent, and provider cache guidance. It ties those lessons
back to Kernel v3's development history, current architecture, finance pack,
AgentGraph roadmap, benchmark discipline, and the forbidden anti-patterns under
the LLM-owned semantic decision invariant. For a shorter talk-ready version, use
`docs/KERNEL_V3_FRAMEWORK_REFERENCE_BRIEF_2026-06-16_ZH.md`; the source-backed
landing memo and implementation dossier remain in
`docs/KERNEL_V3_FRAMEWORK_REFERENCE_LANDING_2026-06-16_ZH.md` and
`docs/KERNEL_V3_FRAMEWORK_REFERENCE_IMPLEMENTATION_DOSSIER_2026-06-16_ZH.md`.
For the latest decision-oriented report draft, use
`docs/KERNEL_V3_FRAMEWORK_REFERENCE_DECISION_2026-06-16_ZH.md`; it reviews the
external framework references and Kernel v3 development record, then converts
the lessons into concrete Kernel v3.1 architecture decisions, forbidden
anti-patterns, and the next execution checklist.
The 2026-06-17 architecture pivot is recorded in
`docs/KERNEL_V3_FRAMEWORK_PIVOT_2026-06-17_ZH.md`. This is the timestamped
decision point where finance capability work moves from repeated hand-written
low-level SEC/document/table tool fixes toward mature open-source components:
LangGraph for the double-layer agent loop, EdgarTools for SEC/EDGAR/XBRL,
Docling for document/table conversion, OpenBB for broader financial data, and
AutoGen later for multi-agent collaboration experiments. Holo still keeps the
host-owned harness boundary: the LLM owns semantic financial judgment, while
the host validates tools, records journal/fact/claim/formula traces, verifies
results, preserves gold isolation, and reports only live benchmark evidence as
finance capability. The first implementation checkpoint adds
`kernel_v3/finance/open_components.py`, registering `finance.toolchain.describe`,
`sec.edgar.company_filings`, `sec.edgar.financials`, `document.docling.convert`,
and `market.openbb.fetch` as host-policy-bound optional component tools.
The 2026-06-18 mature-loop follow-up is tracked in
`docs/KERNEL_V3_AGENT_LOOP_FOLLOWUP_2026-06-18_ZH.md`. The latest live
debug-row evidence is `financebench_id_00499` at offset 2:
`.state/kernel_v3/bench/finance/fb_debug50_o002_l001_after_structured_noise_guard_20260618.jsonl`
passed `1/1` with `numeric_within_tolerance`, `sec.edgar.financials=3`,
`calculator.compute=4`, `formula_trace_count=4`, verifier gate passed,
synthesis gate passed, and matched numerics `5.1%`, `19.8%`, and `12.4%`.
This is a single live debug-row capability result, not a debug50/test100 score.
The underlying fix is agent-loop/tool-context generalization: SEC structured
facts keep authoritative provenance through candidate facts and `FinanceFact`
metadata; failed `finance.slot_bind` can trigger structured SEC evidence
recovery and rerun model binding; structured tool payloads no longer leak CIKs
or JSON identifiers into natural-language fact extraction.
The same follow-up now records the strict single-agent tool-loop boundary:
`finance-capability` defaults to `agent_loop.single_agent_tool_loop=true`, the
model must request retrieval, SEC/document parsing, slot binding, table work,
calculator, and numeric-verifier calls inside the loop before finalizing, and
the host finalizer is a verifier/synthesis gate rather than a hidden numeric
preflight engine. `finance_agent_loop_contract` and
`assistant.turn.single_agent_tool_loop_contract` expose that boundary to the
model; targeted structural tests pass (`41` deep-loop tests, `50`
finance-open/readiness/profile tests, `310` finance-engine tests). This is
architecture/tool-loop evidence, not a new FinanceBench/FAB/FinQA score.
The subsequent code/interface audit further separates strict loop execution
from legacy formula planning: in `finance-capability`, evaluator feedback no
longer calls legacy `plan_finance_formula(...)`; it only reports model-visible
tool requirements from question requirements and observed tool state. The wider
regression passes (`91` loop/tool/profile tests and `311` finance-engine tests).
The 2026-06-17 follow-up tool-surface iteration is recorded in
`docs/KERNEL_V3_FINANCE_TOOL_SURFACE_2026-06-17_ZH.md`. It adds
`kernel_v3/finance/tool_catalog.py`, making `finance.toolchain.describe` return
the complete model-callable finance tool surface, one-shot tool protocol,
current install summary, and mature open-source component mapping. The lightweight
core now pins and installs EdgarTools, LangGraph, LangChain Core, LiteLLM,
Trafilatura, Polars, DuckDB, SymPy, OpenTelemetry, Pandas, Pydantic, and Rich.
Docling/OpenBB/browser components remain cataloged but isolated from the main
UbuntuHolo venv because full Docling currently pulls Torch/CUDA dependencies on
Linux. This is toolchain evidence, not a finance benchmark score.
The finance preflight boundary is recorded in
`docs/KERNEL_V3_FINANCE_TOOLCHAIN_READINESS_2026-06-17_ZH.md`. Use
`bench finance-tool-audit` for narrow tool-interface checks and
`bench finance-tool-workers` for Docling/OpenBB isolated worker status. These
commands verify whether FB/FQA-relevant tools are visible to the model and
allowed by host policy; they are not long regressions and must not be reported
as benchmark accuracy. Repo-local workers under `.holo_components/` are
auto-discovered when present, with environment variables still taking
precedence for custom paths. The 2026-06-18 readiness gate now treats
`tool.discovery`, `artifact.read`, `artifact.query`, `finance.slot_bind`, and
`finance.verify_numeric` as first-class pre-live requirements: smoke mode verifies
that these tools are model-visible, policy
allowed, executable by the host, and able to return bounded observations/artifact
context for the strict single-agent loop. The latest local gate result was
`status=ok`, `local_smoke_status=ok`, `allowed_tools_count=22`; this remains an
interface/execution check, not a benchmark score.
The 2026-06-18 FB/FQA tool-coverage audit is recorded in
`docs/KERNEL_V3_FB_FQA_TOOL_COVERAGE_2026-06-18_ZH.md`. It maps FinanceBench
debug50/test100 and FinQA/FQA oracle-context task families to concrete tool
requirements and closes the main FinQA/FQA tool ABI gap by adding
`provided_context.parse`. The tool uses mature `pandas`/`lxml`/`beautifulsoup4`
components to convert provided report context, HTML tables, markdown pipe tables,
or JSON table snippets into `text_blocks`, query-ready `tables`, and
`data_table_payloads` for `data.table.query`; host parsing remains structural
only and LLM semantics remain model-owned. The updated readiness gate reports
`status=ok`, `local_smoke_status=ok`, `allowed_tools_count=22`, focused
open/readiness tests `32 passed`, structural loop/profile tests `92 passed`, and
finance-engine tests `311 passed`. This is still not a live FinanceBench/FQA
score.
The no-gold debug50 requirements audit is now executable through
`bench finance-requirements-audit --dataset data/bench/finance/financebench_doc_retrieval.jsonl --split debug50`.
It reads question text and public metadata only, reports task families, risk
flags, required tool categories, and loop-stage coverage, and marks
`no_gold_fields_used=true`, `capability_claim=false`, and
`benchmark_progress_claim=false`. This is a structural contract check for
type-cluster debugging, not a FinanceBench/FinQA score. The same no-gold
inference now lives in `kernel_v3/finance/requirements.py` and is injected into
finance-capability planner directives and compact provider payloads as
`finance_question_requirements`, so the model sees the task-family/tool-category
workbench needs during one-shot tool selection. The same ABI also drives
`bench finance` slicing through `--requirements-family`,
`--requirements-tool-category`, `--requirements-risk-flag`,
`--requirements-loop-stage`, and `--requirements-limit`, enabling small
type-cluster live debug runs without reading gold/reference fields. The deep
agent loop now also maps requirements categories and risk flags into
context-requested provider-native tools, so deferred tools such as
`sec.edgar.financials`, `document.docling.convert`, `data.table.query`,
`calculator.compute`, and `finance.verify_numeric` are expanded when the
current finance task family needs them.
The same-day loop logic audit is recorded in
`docs/KERNEL_V3_AGENT_LOOP_AUDIT_2026-06-17_ZH.md`; its first checkpoint moved
finance/web/long profiles onto a LangGraph-backed controller. The later
reimplementation checkpoint is
`docs/KERNEL_V3_DEEP_AGENT_LOOP_REIMPLEMENTATION_2026-06-17_ZH.md`: after
reviewing the local TypeScript agent-loop snapshot under
`D:\COURSES\人工智能算法实践\code-main\code-main`, Holo now has its own Python
`DeepAgentLoopController`. `finance-capability` defaults to
`agent_loop.runtime_backend = deep_agent_loop`, where a single model turn can
emit multiple tool calls, host policy validates each call, read-only/network
tools can run as an ordered batch and only explicitly concurrency-safe tools
execute in parallel, and all tool results re-enter the journal as model-visible
observations. The single-agent loop now preserves stable `tool_call_id` bindings
through individual observations and batch results, and malformed model tool
calls are returned as synthetic failed observations for replanning instead of
being silently dropped. The tool-calling substrate now includes a generic
`tool.discovery` contract, standard `ToolUseContext` injection for each executed
tool, and an evented `StreamingToolExecutor` that journals queued / started /
completed tool events. Tool batch observations now include budgeted
`content_projection` metadata so long SEC/table/tool results expose shape,
truncation state, and a short preview without flooding the model packet; the
context compiler preserves those projections and `artifact.read` lets the model
inspect bounded artifact previews or bodies only when needed. Finance open
component tools now write long SEC/EDGAR, document, market, and DuckDB table
payloads into `ArtifactStore` blobs when the runtime provides a store; the model
gets a short observation, `artifact_id`, and `artifact.read` hint instead of the
full payload. The next P0
substrate checkpoint adds manifest-level `ToolRuntimeSpec` projection into
tool discovery and execution context, batch-observation tool-result replacement
state, and a processor streaming event contract with OpenAI-compatible SSE
parsing scaffolding. The following P0 continuation wires
`ModelAssistantTurnPlanner(use_streaming=True)` to consume
`ProcessorFabric.stream_events(...)`, normalize OpenAI-style `tool_call_delta`
events into `ToolCallRequest`, and route malformed streamed arguments into
synthetic parse-error observations. This proves stream events can enter the
host policy/tool/journal chain. The next P0 continuation adds a
provider-native OpenAI-compatible tool surface: Holo manifests are projected to
valid provider function names and JSON schemas, `ModelAssistantTurnPlanner`
passes them into streaming requests, and streamed provider function names are
mapped back to canonical Holo tool names before policy/execution. `ProcessorFabric`
now also exposes `iter_stream_events(...)` for true incremental provider stream
consumption while preserving the old list-returning `stream_events(...)`
compatibility path. Context packing now exposes `content_replacement` views from
tool batch results so long tool outputs are represented by stable bounded
replacement previews and artifact-read hints in the next model packet.
`DeepAgentLoopController` now has an eager streaming path: when provider
`tool_call_delta` contains a complete JSON argument object, the host prepares the
tool through the normal policy/guard path, submits execution before the provider
stream is drained, continues consuming stream events, and then records completed
tool observations and the aggregate batch result. Tool execution context now
includes progress channel ids, abort signal ids, and timeout hints; cooperative
tools can call the shared helpers to emit `progress` events and honor host
abort requests. Provider-native tool exposure now respects runtime loading hints:
`always_load` tools are prioritized, while `should_defer` tools are summarized
for discovery instead of flooding the provider `tools` payload.
The 2026-06-18 mature-loop continuation upgrades `StreamingToolExecutor` from
batch-only execution to a reusable incremental state machine with
`begin_incremental`, `add_item`, `drain_completed`, `finish_remaining`,
`discard`, and `close`. `DeepAgentLoopController` now uses that same executor
for provider streaming tool calls instead of maintaining a separate pending
future scheduler, so JSON-turn and native streaming paths share the same
concurrency-safe, exclusive-tool, timeout, progress, cancellation, and
journal-event semantics. This is architecture/tool-loop readiness, not a
FinanceBench or FinQA score.
The same follow-up document now records the next live stability checkpoint:
`JournalStore` loads JSONL line-by-line and records warnings for partial rows,
so a damaged historical ledger no longer prevents isolated live runs from
starting. Workbench follow-up scaffolding also stops auto-repeating the same
retrieval action after a `max_network_fetches` host guard. A real
`financebench_id_04672` probe was manually interrupted after exposing a higher
level convergence issue: wrong-source evidence could still enter fact/claim
ledgers and make final numeric repair trigger another task compile instead of
compressing rejected evidence into a clean replanning state. This is live loop
diagnostic evidence, not a benchmark accuracy result.
The next P0 continuation implements that rejected-evidence workbench boundary:
primary-source binding failures now produce `finance_rejected_evidence_ledger`
and compact `finance_working_state.rejected_evidence`; when
`primary_source_required=true` and no target binding matches, rejected
candidates are withheld from usable working-state facts, excluded from semantic
task-compile inputs and ordinary finance claims, and surfaced through an
`evidence_replan` workbench phase plus evaluator feedback. Market-data tasks
without an explicit primary-source target binding remain on the normal formula
trace path. Targeted structure tests pass (`372` finance/processor tests). This
is agent-loop/workbench maturity evidence, not a FinanceBench or FinQA score.
The next live diagnostic on `financebench_id_04672` confirmed that the rejected
evidence pollution did not recur, but exposed another generic mature-loop
boundary: a deep tool batch could contain `host_guard reason=max_tool_calls`
while the outer evaluator still continued. `decide_termination(...)` now
recognizes host budget guards inside nested deep tool batch payloads and
overrides model `continue` feedback to a host failure report when no final
answer can be delivered. The context compiler also has a minimal `agent_trace`
projection and an explicit omit fallback for very small section budgets. Targeted
structure tests pass (`483` kernel-v3 loop/tool/finance tests). This is
agent-loop stability evidence, not a benchmark score.
The next mature-loop continuation ports the inspected TypeScript loop's
`contextModifier` idea into Holo's host-owned journal boundary. `ToolResult`
can now carry `context_updates`; deep-loop execution standardizes explicit and
observation-derived updates into `tool_context_update` ledger records, links
them from `tool_batch_result.context_update_refs`, and exposes recent compact
updates through a `tool_context_updates` context-pack section. This lets
slot-binding, workbench, artifact, and discovery tools pass next-step context to
the following model turn without letting tools directly choose finance facts or
answers. Targeted structure tests pass (`494` kernel-v3 loop/context/tool/finance
tests). This is agent-loop substrate evidence, not a benchmark score.
The next mature-loop continuation makes the tool surface context-aware. Deferred
tools such as SEC/EDGAR can now be temporarily expanded into the provider-native
tool list when `tool_context_updates`, finance workbench state, or tool discovery
results explicitly name them as the next needed tool. The JSON prompt
`tool_surface` and streaming/native provider surface use the same extracted
tool set, with token-aware visible-tool limits that prioritize `always_load` and
context-requested tools while leaving overflow tools discoverable through
`tool.discovery`. Targeted structure tests pass (`497` kernel-v3 loop/context/
tool/finance tests). This is substrate evidence, not a benchmark score.
The next mature-loop continuation closes the streamed provider tool-result
message path. When a provider-native stream emits tool calls, the deep loop now
executes bounded tools, builds provider-compatible assistant/tool messages, and
sends a continuation request to the same provider/model with bounded
`holo.kernel_v3.provider_tool_result_message.v1` content. Continuations can now
emit further provider-native tool calls: the same streaming parser/executor runs
them, appends new bounded tool results, and repeats the provider continuation up
to a host-owned cap while deduplicating already-seen tool-call ids. The resulting
assistant continuation is recorded in the tool batch observation, while the
evaluator still decides finality. Targeted structure tests pass (`31` deep-loop
tests, `351` loop/native/processor/tool/finance tests, and `499` kernel-v3
structural tests). This is loop substrate evidence, not a benchmark score.
The provider-message replacement continuation extends replacement beyond prompt
strings: deep-loop assistant prompts, `ProcessorFabric` JSON prompts, request
parameters, OpenAI-compatible `provider_messages`, and structured provider
message content now rewrite replaced large tool results to stable bounded
previews before provider dispatch. Deep loop batch observations also persist
full tool results as `tool_result_full` artifacts and expose those artifact ids
through replacement `artifact_refs`, while context budget views compact large
individual `tool_result` observations and omit host-only execution context. This
moves the generic single-agent loop parity estimate beyond the 95% P0
architecture threshold. The next P0 continuation gives completed JSON-turn tool
batches the same runtime timeout/abort boundary as streaming tool execution:
over-time tools now produce `tool_call_timeout` observations and journal
`abort_requested` events instead of blocking the loop. Remaining gaps are
process/network-level signal propagation for already-running non-cooperative
tools and type-family live debug50 evidence.
This estimate is architectural only, not a FinanceBench or FinQA score.
The 2026-06-18 follow-up is recorded in
`docs/KERNEL_V3_AGENT_LOOP_FOLLOWUP_2026-06-18_ZH.md`. A live type-cluster probe
on `financebench_id_04672` exposed a generic streaming-loop defect: workbench
and slot-binding signals identified missing balance-sheet net PP&E, but the
streaming path repeated `artifact.read` instead of executing the workbench
follow-up retrieval. Kernel v3 now checks pending workbench follow-up before
calling the streaming planner, so model/workbench-proposed target URLs can be
scaffolded into `retrieval.run` through the normal policy/tool/journal path.
The workloop also detects repeated `artifact.read` after three identical reads.
Targeted structural tests pass (`21` deep-loop tests, `31` workloop tests).
The attempted live rerun was blocked by sandbox escalation review timeouts, so
this is a loop-contract repair, not a new FinanceBench accuracy claim.
The next 2026-06-18 checkpoint tightens the TypeScript-loop parity further by
turning finance tool results into loop-driving context modifiers. `finance.slot_bind`
already returned model-owned `missing_slots` and `next_action`; Kernel v3 now
projects those fields into `finance_working_state`, evaluator feedback emits
`finance_slot_bind_followup` instead of allowing premature finalization, and the
deep loop scaffolds the model-declared next tool call before invoking the
streaming planner. For `retrieval.run` follow-ups, the host only packages the
model-declared query or missing-slot rationale into a normal retrieval payload;
it does not select answer facts or hard-code benchmark rows. Targeted structural
tests pass (`23` deep-loop tests, `298` finance-engine tests, `31` workloop
tests). This is still a loop-contract improvement, not a FinanceBench/FinQA
score claim.
The next mature-loop parity checkpoint adds a budget-aware `agent_trace`
section to the context pack and lifts it into `assistant.turn` prompts as
`context.state.agent_trace`. The model now sees a stable recent trajectory of
assistant turns, tool calls, observations, feedback, guards, and results without
duplicating large tool payloads; detailed outputs remain in `recent_observations`
and artifacts readable through `artifact.read`. Low-information progress events
and ordinary allowed policy decisions are filtered, and small context budgets
shrink or disable the trace window. Provider availability circuit breaking is
also scoped by provider+model, so a timeout on one DeepSeek model does not
short-circuit a different model on the same provider later in the run. Targeted
structural tests pass (`24` deep-loop tests, `22` context/tool-surface tests,
`18` processor/fabric tests). This is architecture evidence, not a new finance
benchmark score.
The next 2026-06-18 mature-loop parity checkpoint mirrors two more inspected
TypeScript-loop mechanics. `StreamingToolExecutor` now has bounded worker
concurrency and a semantic sibling-cancel callback: shell/write/destructive or
non-read-only exclusive failures can cancel pending siblings, while ordinary
read/network failures preserve independent tool results for replanning. The
`assistant.turn` prompt now includes a host-built `tool_surface` from
`ToolManifest`/`ToolRuntimeSpec`: visible or `always_load` tools expose compact
input schemas and runtime metadata, while deferred tools expose only briefs and
route schema lookup through `tool.discovery`. Targeted structural tests pass
(`25` deep-loop tests, `9` tool-use tests, `15` provider/context tests). This is
agent-loop/tool-interface evidence, not a FinanceBench/FAB/FinQA score claim.
The latest 2026-06-18 ToolSearch parity checkpoint ports one more inspected
TypeScript-loop behavior: `tool.discovery` now supports exact
`select:tool.a,tool.b` loading, reports matched/missing tool names, and returns a
budgeted manifest summary rather than bloating `recent_observations`.
Streaming provider continuations rebuild the native tool surface after each
tool-result round; if a `tool.discovery` result discovered an allowed deferred
tool, that tool's native schema is exposed on the next continuation while policy
and allowed-tool boundaries remain host-owned. The follow-up closes the same
path for non-streaming JSON turns: discovery results now emit a
`tool_context_update` with matched tools as `requested_tool_names`, so the next
`assistant.turn` prompt expands the same deferred schema through the ordinary
context-requested tool surface. `bench finance` also computes a no-gold
requirements slice before live-model preflight when requirements filters are
present, so provider/key blocks still report selected item ids and required tool
categories without writing fake benchmark outputs. Targeted structural tests
pass (`35` deep-loop tests, `11` tool-use tests, `61` finance benchmark tests,
`5` provider-native tests). This is loop/toolchain readiness evidence, not a
live FinanceBench or FinQA score.
The next loop-protocol hardening keeps provider continuation tied to real
provider tool calls only. `tool_call_parse_error` observations and
`__invalid_tool_call__` synthetic actions still enter the journal and
`tool_batch_result` for outer-loop replanning, but they no longer fabricate
assistant/tool messages inside the provider conversation. Valid executed tool
results still continue through provider-native tool-result messages. Targeted
deep-loop structure tests pass (`36` tests). This is protocol integrity work,
not a finance benchmark score.
The next same-day mature-loop checkpoint closes provider-visible full
tool-result artifacts. Each executed tool result now gets a stable
`tool_result_full` artifact as soon as execution completes, so the same
provider continuation tool message can include `tool_result_artifact_id` and an
`artifact_read_hint` for `artifact.read` instead of waiting for the later batch
observation. Batch observations reuse the same artifact id, while next-turn
context only surfaces the full-result artifact hint for truncated long results
to avoid context-budget inflation on small tool outputs. Targeted structural
tests pass (`36` deep-loop tests, `16` tool/provider tests, `61` finance
benchmark harness tests). This is agent-loop/tool-result contract readiness,
not a live FinanceBench or FinQA score.
The following mature-loop checkpoint upgrades the artifact workbench from
whole-blob reads to bounded queries. `artifact.query` is now an always-loaded,
read-only, concurrency-safe tool that can select JSON paths, search JSON
subtrees or table-row lists, and search text artifact lines without forcing the
model to pull an entire SEC filing, table extraction, retrieval report, or full
tool-result JSON into context. Provider full-result hints now include
`artifact_query_hint`, replacement hints prefer `artifact.query` before broad
`artifact.read`, and the finance loop standard tool interface/capability
catalog describe the new path. Targeted structural tests pass (`81` loop/tool/
finance-open-component tests, `11` processor usage tests, `61` finance benchmark
harness tests). This is P0 workbench readiness, not a live finance score.
The follow-up closes the exposure path: retrieval, workspace-answer, and
workspace-write recipes now include `artifact.query`; planner allowed-tool sets
and `tool.discovery` allowed manifests include it alongside `artifact.read`.
Finance runtime tests confirm the tool is present in recipe allowed tools,
runtime manifests, and model-planner allowed sets. Targeted structural tests
pass (`92` tool/deep/provider/finance-open/processor tests, `3` finance-engine
planner tests, `61` finance benchmark harness tests). This is model-visible
tool-surface readiness, not a live finance score.
The next finance tool-runtime P0 checkpoint makes those tool contracts executable
rather than merely descriptive. `retrieval.run`, SEC/EDGAR, Trafilatura, OpenBB,
DuckDB, SymPy, `calculator.compute`, `finance.slot_bind`, and
`finance.verify_numeric` now expose runtime hints for `always_load`, read-only
status, concurrency, timeout, result persistence, and open-world access. Heavy
`document.docling.convert` remains read-only but explicitly non-concurrency-safe
with a cancel/timeout boundary to protect UbuntuHolo stability. `sec.edgar.financials`
also accepts `fiscal_year` and `period`/`target_period`, projecting SEC candidate
records or period columns to the requested fiscal period without choosing the
financial line item or answer. Targeted structural tests pass (`79` related
tests). This is tool-interface readiness, not a new finance benchmark score.
The streaming path now also mirrors the inspected TypeScript
`StreamingToolExecutor` scheduling rule: a streamed tool starts immediately
when possible, explicitly concurrency-safe tools may run together, and exclusive
tools block later tools until completion. The CLI exposes this path via
`--agent-loop-streaming` / `--no-agent-loop-streaming`, which writes
`agent_loop.provider_streaming` into execution metadata instead of requiring
internal recipe edits. Streamed tool-call chunks are keyed by provider `index`
while preserving the real `tool_call_id`, and tools are not executed until a
non-empty JSON argument object has arrived. Finance final numeric preflight task
compilation is bounded and non-retrying so provider stalls cannot hang an
already-completed live run at ledger-writing time. These are loop-stability
contracts, not benchmark score claims.
The 2026-06-18 mature-loop continuation ports the inspected executor's sibling
abort contract into Holo. `ToolRuntimeSpec` now includes
`failure_cancels_siblings`; `StreamingToolExecutor` can call an `abort_one`
hook for already-running sibling tools when a failure invalidates the batch; and
`DeepAgentLoopController` connects that hook to each prepared tool's
`ToolAbortSignal`, journaling `abort_requested` with reason
`sibling_tool_failed`. This closes the Holo-level cooperative abort path for
running sibling tools while keeping normal read/network failures independent.
Targeted structural tests prove both the executor callback and the deep-loop
`_host_context` signal path. This is agent-loop stability work, not benchmark
score evidence.
The follow-up live diagnostic on `financebench_id_04672` exposed the next
generic boundary in the same mature-loop line: a completed deep
`tool_batch_result` could contain a child `host_guard` / `loop_guard` for
`max_tool_calls`, but the deep loop still called the normal evaluator and let
the model continue with an oversized context. `DeepAgentLoopController` now
recognizes host budget guards inside nested batch results before evaluator
dispatch, writes a host `step_limit_exceeded` feedback and guard record, and
only invokes an explicit `finalize_guard` hook when the evaluator provides one.
This mirrors the inspected TypeScript loop's hard host-boundary behavior:
semantic decisions stay model-owned, while budgets and abort/stop contracts stay
outside the model. Targeted structural tests pass (`125` loop/tool/provider/
finance-open tests). This is loop-stability evidence, not a FinanceBench/FinQA
accuracy claim.
The next mature-loop checkpoint ports the same fallback/discard/rebuild idea to
final synthesis. `Synthesizer` now checks `processor_budget.max_prompt_chars_per_call`
before provider dispatch; if a retrieval/fact/citation packet is too large, it
rebuilds a compact synthesis packet with bounded evidence, citations,
finance-fact ledger, FormulaTrace, support indices, hints, and previews. The
model still owns the final financial judgment; host-side compaction only keeps
the workbench state within provider budget and exposes
`synthesis_budget_compaction` as a prompt-visible boundary. Targeted structural
tests pass (`108` agent-loop/tool/synthesizer tests plus `3` finance prompt
contract tests). The same live `financebench_id_03029` probe that previously
failed as `processor_budget_exceeded` now passes `1/1`
(`numeric_within_tolerance`, matched `1577.0`, no processor errors) in
`.state/kernel_v3/bench/finance/run_fb_debug_o000_l001_live_20260618_streaming_v2.jsonl`.
This is a live single-row regression result, not a debug50/test100 score.
The finance document toolchain now applies the same result-budgeting principle
inside `document.docling.convert`: PDF URLs first use the lightweight existing
PDF extraction stack before heavy Docling, nested Docling import probes fall
back cleanly to the isolated worker, and converted documents expose
`focus_snippets` ahead of truncated text so the model can see high-signal
candidate filing lines without host-side answer selection. This is a tool
interface and evidence-visibility fix; finance capability numbers still require
separate live model runs with gold/reference kept out of model context. Live
finance runs should use `.venv/bin/python`, because the project venv contains
the installed SEC/document/table dependencies that the system Python may not
have.
The follow-up live streaming probe on `financebench_id_03029` showed that this
toolchain path works but exposed a higher-level evidence contract break:
`document.docling.convert` returned the exact PP&E purchase line in
`focus_snippets`, yet the finalizer still failed with `missing_retrieval_report`
because only `retrieval.run` observations were promoted into retrieval
evidence/citation substrate. Kernel v3 now promotes finance open-component
observations, including Docling focus snippets and SEC/OpenBB/DuckDB/SymPy
payloads, through the existing synthetic `toolchain_grounding` report path. The
LLM still chooses facts and conclusions; the host only makes model-called tool
observations visible to the same evidence, citation, ledger, verifier, and
synthesis contracts.
The verified live rerun
`.state/kernel_v3/bench/finance/fb_debug50_stream_grounding_o000_l001_20260617.jsonl`
passed `financebench_id_03029` at `1/1` with `numeric_within_tolerance`:
`document.docling.convert` and `sec.edgar.financials` supplied model-called
evidence, synthetic toolchain grounding produced `210` finance facts and `210`
claims, one calculator/formula trace ran, numeric verifier, verifier gate, and
synthesis gate all passed, and the matched value was `1577.0`. This is a single
debug-row live result, not a debug50/test100 score; it also remains expensive at
`282,939` tokens.
The latest 2026-06-18 live repair on `financebench_id_04672` closes the next
tool-contract gap. Earlier live attempts found the right area but either lost
filing scale (`$ 8,738` became bare `8738`) or let cash-flow PP&E purchases
bind to a balance-sheet net PP&E slot. Kernel v3 now propagates nearby filing
scale scopes into natural-text facts, rejects cash-flow PP&E purchase rows for
balance-sheet net PP&E target binding, and lets `sec.edgar.financials` fall
back to official SEC companyfacts JSON when EdgarTools cannot run without a
valid `EDGAR_IDENTITY`. SEC financials records are promoted as toolchain
candidate facts with `concept`, `fp`, `start`, `end`, `frame`, and `accn` so the
LLM can bind line item and period from raw fields. The live rerun
`.state/kernel_v3/bench/finance/fb_debug50_o001_l001_after_sec_fallback_20260618.jsonl`
passed `1/1` with `numeric_within_tolerance`, final answer `$8.738 billion`,
numeric verifier/gate/synthesis gate passed, `sec.edgar.financials` used once,
`154` finance facts, `2` formula traces, and `363,559` tokens. This is a single
live debug-row result, not a debug50/test100 score.
The next same-day mature-loop checkpoint is recorded in section 17 of
`docs/KERNEL_V3_AGENT_LOOP_FOLLOWUP_2026-06-18_ZH.md`. It ports another
Claude-Code-style tool contract into Holo's finance path: model one-shot tool
payloads for `finance.verify_numeric` can now be normalized from minimal
fact/formula/citation/evidence objects instead of failing on missing optional
contract fields, while malformed non-object rows still fail at the host schema
boundary. Formula planning also infers SEC structured XBRL priority from
concept/form/fp/source URI, so a true `PropertyPlantAndEquipmentNet` companyfacts
row outranks natural-text PP&E fragments when binding capital-intensity
PP&E/assets slots. Targeted structural tests pass (`353` loop/provider/streaming/
finance tests plus `py_compile` and `git diff --check`). An attempted live rerun
on `financebench_id_00499` produced `tokens=0` and `missing_api_key_env:7`
because UbuntuHolo could not read the Windows provider key through broken
Windows interop; that run is recorded only as environment blockage, not finance
capability evidence.
The following checkpoint adds a hard live-benchmark preflight for that failure
mode. Live chat/agent/`bench finance` now verifies `DEEPSEEK_API_KEY` before
starting model-backed work, attempts one safe Windows User/Machine environment
import into the current process, and blocks with
`missing_live_model_api_key` if the key is still unavailable while
`HOLO_V3_LIVE_MODEL=1`. Blocked finance benchmark runs do not create
`results.jsonl` or `summary.json`, preventing zero-token provider failures from
polluting benchmark evidence. Targeted validation passed (`107` chat/finance
benchmark CLI tests plus `py_compile`), and an actual temporary CLI smoke
returned the expected blocked status without writing output files.
`finance-fact-fast` remains on the LangGraph fast lane for now. This is a
structural loop milestone, not a finance benchmark score.
The next 2026-06-18 mature-loop checkpoint closes three more loop-host
contracts copied from the inspected TypeScript agent-loop architecture. Live
model preflight can now import `DEEPSEEK_API_KEY` from an explicit key file or
the local `.holo_runtime/secrets/deepseek.key` without exposing the key value;
streaming provider continuations now stop immediately when a just-executed tool
round hits a host budget guard such as `max_tool_calls`; and
`StreamingToolExecutor` can convert host-side execution exceptions into a
normal `tool_host_exception` tool-result observation instead of crashing the
agent loop. Invalid tool payloads now include a model-visible recovery protocol:
inspect the schema with `tool.discovery query='select:<tool>'`, then retry with
the returned input schema. A live DeepSeek model-smoke succeeded through the
local key-file path. A live FinanceBench probe for `financebench_id_04672`
completed end-to-end after the continuation guard but failed
`numeric_outside_tolerance` (`0/1`, matched `1.577` vs expected `8.7` in
post-run dev scoring), so it is diagnostic evidence only, not a finance score
improvement. Final structural validation passed (`129` core
deep-loop/tool/provider/processor/finance-open/workloop tests, `61` finance
benchmark harness tests, and `git diff --check`), with targeted
tool/deep/provider-native checks covered inside that set.
The next same-day mature-loop lifecycle checkpoint ports another QueryEngine
practice from the inspected TypeScript agent-loop project: every deep-loop turn
now writes a compact `agent_loop_turn_result` ledger record before returning or
continuing. The record captures the phase, transition, turn id, feedback status,
guard reason, counters, tool-result status counts, failed tool summaries, and
observation/feedback refs. `ContextPackCompiler` includes the compacted record
inside `agent_trace`, so the next model turn can reason from a structured
lifecycle transition instead of inferring it from scattered assistant/action/
observation/feedback records. This is agent-loop contract evidence, not a
FinanceBench/FinQA score. Structural validation passed (`41` targeted
deep-loop/context tests, `34` context/tool/provider tests, `335`
finance-engine/workloop tests, `52` finance-open/tool-readiness/provider/tool
tests, plus `py_compile`).
The next same-day mature-loop finalization checkpoint closes the generic defect
behind the diagnostic `financebench_id_04672` failure. Finance finalization now
treats unresolved required answer slots as a terminal gate: if retrieval/workbench
or model-owned slot state still names a required finance slot, the first
synthesized answer cannot headline a nearby/proxy number as final. The host
records `missing_required_finance_slots_v1`, asks the model to repair the answer
into an explicit "not separately itemized" / "not available in the provided
evidence" limited answer, then continues through the existing quality and numeric
verifier path. Resolved slots from later `slot_bind` or ready `TransformPlan`
records are deducted, and optional formula-planner misses for source-grounded
explanations do not block finalization. This is a mature agent-loop contract
repair, not a FinanceBench/FinQA accuracy score. Structural validation passed
(`304` finance engine tests, `92` runtime/context/deep-loop/workbench tests, plus
`py_compile`).
The debug50 architecture reset is recorded in
`docs/KERNEL_V3_DEBUG50_REQUIREMENTS_AND_GENERIC_FINANCE_LOOP_2026-06-17_ZH.md`.
It stops per-question patching, groups the first 50 FinanceBench debug prompts
by reusable task families, and promotes a benchmark-agnostic finance agent loop
contract into `finance.toolchain.describe`, the planner directive, and the
provider compact packet. This is an interface/architecture milestone, not a
benchmark score.
The external-loop parity audit is recorded in
`docs/KERNEL_V3_EXTERNAL_LOOP_PARITY_AUDIT_2026-06-17_ZH.md`. It compares the
local TypeScript agent-loop project against Holo Kernel v3. After the latest P0
continuations, provider-native eager tool execution, cooperative progress/abort,
provider-message replacement, and durable tool-result artifacts are structural
capabilities rather than paper plans. The remaining hard gaps are forceful
subprocess/network cancellation for non-cooperative tools, runtime result/progress
injection into the same provider conversation, dynamic token-aware tool-set
expansion, resume/fork cache-stability audit, and type-family live debug50
evaluation. This is a design audit, not a finance benchmark score.
The first 2026-06-14 general-capability line, covering DeepSeek cache
discipline, stable context ordering, managed memory context, and general
agent-gauntlet priorities, is tracked in
`docs/KERNEL_V3_GENERAL_CAPABILITY_LINE1_2026-06-14_ZH.md`. Kernel v3 now has
a native general gauntlet entry at `python -m kernel_v3.cli bench general`.
The 2026-06-15 finance slot-binding/cache pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-15_FINANCE_SLOT_BIND_CACHE.md`; it moves strict
finance preflight closer to the intended LLM-owned task.compile -> slot_bind ->
calculator trace loop, fixes a live `finance.slot_bind` schema failure, adds
model-planned chained calculator execution, and records the remaining HD/LOW DIO
numeric mismatch and synthesis-packet size bottleneck.
The multi-question finance ability snapshot is tracked in
`docs/KERNEL_V3_FINANCE_ABILITY_METRICS_2026-06-15.md`; it separates true live
accuracy evidence, workflow/substrate health checks, no-gold public sets, and
single-item debugging runs.
The 2026-06-15 prompt-economy follow-up keeps full journal trace state while
using a lighter provider prompt for direct/semantic/system turns; the low-cost
DeepSeek live smoke passed 2/2 with total tokens reduced from 60,616 to 47,412
and cache hit ratio improved from 26.9195% to 59.4381%.
The 2026-06-16 finance processor/cache progress is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-16_PROCESSOR_USAGE_CACHE_METRICS.md`; recent
sections cover model-owned slot-binding basis, competing fact clusters carried
through synthesis and numeric judge, synthesizer unknown-reference repair, and
unit-mismatch repair guidance for `finance.verify_numeric`. The latest section
also carries verifier repair context into compact finance synthesis repair, so
the repair LLM sees unit/source-binding diagnostics instead of only a short
repair instruction, and exposes retrieval metric-intent diagnostics as weak
model-visible hints for finance slot binding, synthesis, and numeric judge
without polluting raw facts.
The FinanceBench snapshots for 2026-06-16 and 2026-06-17 also record generic
formula scaffolds for DPO, multi-year average capex/revenue, effective-tax-rate
change, positive working capital, interest coverage, and unadjusted EBITDA
families, with the latest follow-up adding asset turnover, average COGS/revenue,
liquidation value per share, debt-change, and component-percent-of-total
programs, plus cash-equivalents change, PP&E change, store-count change, and
operating/investing/financing cash-flow activity comparison. The latest margin
series pass adds operating/gross margin profile change and gross-margin
consistency range scaffolds, and the newest table-rank pass adds a generic
category-metric ranking scaffold for segment, region, product category,
short-term investment type, liability-line, and derivative notional questions.
The host prepares evidence slots and calculator-visible `max`/`min` transforms;
the LLM still maps the extreme value to the cited category and explains the
answer. The newest follow-up also routes "biggest drop"/decline-by-region
questions through that ranking scaffold instead of treating them as plain
geography disclosure, and upgrades VaR prior-year comparison questions to a
`market_risk_var_change` period-change scaffold with prior/current VaR
evidence slots. It also adds `percent_of_sales_change` for questions that ask
whether a metric as a percent of sales/net sales increased or decreased across
periods. The same line now includes a generic `metric_lookup`
identity transform for direct filing line-item extraction such as capex, net
PP&E, AR/AP, inventories, COGS, net income, adjusted EBITDA, operating cash
flow, dividends, restructuring costs, assets/current assets/current
liabilities, VaR, credit facilities, transaction proceeds/gains, expected
benefit payments, separation/spin-off expected payments, and sales-change
disclosures such as "real change in sales" excluding FX. The latest disclosure
pass adds a generic `disclosure_lookup` scaffold for
registered securities, dividend history, 8-K summaries, acquisitions,
industries, products/services, customers/geographies, legal proceedings,
governance/proxy/vote items, guidance, separations/discontinued operations,
nonrecurring events, revenue/inventory/expense drivers, restructuring
liabilities, and remaining market-risk disclosures. In question-only
static coverage, recognized FinanceBench formula plans and EvidenceSpec rows
now reach `150/150`; this is code-regression evidence for the next live run,
not a benchmark accuracy score. The same 2026-06-17 line now includes a live
debug fix for target line-item evidence binding: focused workbench excerpts,
alias-aware target row selection, and compiled-program hint propagation moved
the first FinanceBench doc-retrieval capex row from repeated missing-fact
loops to a passed live answer with `237,555` tokens, `12` fetches, `202` facts,
`202` claims, calculator/formula traces present, and verifier/synthesis gates
passed.

For a presentation-oriented Chinese system review of Kernel v3, including the
architecture, finance capability surface, benchmark/task coverage, demo plan,
current local changes, gaps, and next priorities, see
`docs/KERNEL_V3_SYSTEM_REVIEW_2026-06-13_ZH.md`.

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
`docs/KERNEL_V3_PROGRESS_2026-06-08_MEMORY_DIGEST_SEC_EXTRACTION.md`. The
2026-06-09 public-benchmark import and behavior-graph pass is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-09_BENCHMARK_GRAPH.md`. The current
finance benchmark work and handoff status are tracked in
`docs/KERNEL_V3_FINANCE_BENCHMARK_TRACK.md`. As of 2026-06-10, Kernel v3 has a
v1 finance substrate with structured finance facts, deterministic calculator
traces, numeric verification, FAB v2 public/dev10 import and scoring, and
fast-lane budget controls. It has closed representative live tasks such as
HD/LOW DIO, KHC adjusted EBITDA bridge, PFE/Seagen transaction multiple, and
WSC adjusted EBITDA add-back trend, but it should not yet be described as a
stable Finance Agent v2 solver. The main open gap is robust generalization to
harder filing/modeling tasks such as DCF/LBO, fixed-charge coverage, MLR,
valuation multiples, and purchase-price-allocation analysis.
As of 2026-06-13, the current demo-ready Kernel v3 finance case is
FinanceBench `financebench_id_02987`: Activision Blizzard FY2019 fixed asset
turnover from the 2019 10-K source URL. The promoted live run
`run_demo_financebench_activision_fat_live_20260613` passes strict scoring with
`pass_rate=1.0`, `numeric_accuracy=1.0`, `overall_score=1.0`, `workflow_score=1.0`,
245 finance facts, 245 claim-ledger records, a transform plan, citations, and a
synthesis gate pass. The Windows-accessible dashboard defaults to this run at
`http://localhost:8787/` when `kernel_v3.demo_dashboard` is running. The current
dashboard is chat-first: the right side is the interactive Holo console, while
the left side shows compact WSL workspace state and a large Agent Loop Runtime
panel. That panel now focuses on a graphical SVG loop, search-branch strip, and
click-through inspector; the old Events and Model Context panes were removed so
the actual loop has more room. The browser no longer depends on high-frequency
full-state polling for the agent loop: `/api/live` streams lightweight
Server-Sent Events from the Kernel v3 journal and updates topology, retrieval
branches, and transcript fragments as events are appended; `/api/state` is now a
slower calibration path for workspace, benchmark, and command metadata. The chat
panel also includes a large white Runtime Console that streams host-visible
model request/result packets, structured outputs, tool calls, retrieval events,
evidence, verifier gates, and final/failure records in a command-line style
view. Closed turns freeze the visible graph and force the console status to
`complete`, so late journal records cannot make an answered turn look like it is
still running. Its scrollable default prompt bank now separates strict
benchmark-style prompts from longer research tasks. The strict/stable prompts
include Activision FY2019 fixed asset turnover, 3M FY2018 capex, 3M FY2018 net
PP&E, 3M FY2022 capital intensity, 3M operating-margin drivers, 3M ex-M&A
segment growth, Goldman FY2024 net revenues, and NextEra FY2024 operating
revenues. The longer research prompts cover HD vs LOW FY2024 DIO, KHC adjusted
EBITDA bridge quality, Pfizer/Seagen transaction EV/revenue multiple, and WSC
adjusted EBITDA add-back trends. It
supports thread switching, new demo threads, local screen clearing, model-routed
Auto Chat, Finance Deep mode with larger finance retrieval/tool budgets, and
stable hard finance prompts for recording. It also supports item-level demo
selection; for recording, the stronger historical
Activision trace is available with
`run_prefix=run_financebench_doc_live10_capability_parallel_v2` and
`item_id=financebench_id_02987`, showing 15 calculator calls, 738 finance
facts, 1048 citations, and verifier `passed`. The dashboard also surfaces the
same-item stability evidence: 3/3 live pass traces across the promoted
single-item run and two live10 capability batches, with two verifier-passed
calculator-heavy traces. The same
iteration also improved model-owned retrieval follow-up: LLM workbench
`decision=continue` now routes back through standard `retrieval.run` instead of
allowing premature finalization. The FAB v2 HD/LOW DIO task remains a high
stress case for multi-issuer COGS/inventory search and is not yet the promoted
demo result.
The post-demo finance ability pass on 2026-06-13 strengthens real line-item
disambiguation rather than adding answer tables. Generic target bindings such
as `revenue` are now refined when the user's question explicitly asks for a
more specific metric phrase such as `net revenues`; the finance fact ledger
preserves specific captions such as `net revenues`, `total revenues and other
income`, and `sales and other operating revenues`; and the
`finance-capability` prompt tells the LLM to treat same-period SEC companyfacts
revenue concepts as competing evidence and inspect the 10-K statement table
before finalizing when the caption is ambiguous. The focused regression suite
passed with 298 tests. A minimal live FE_009 Goldman net-revenues rerun was
attempted as
`run_goldman_net_revenues_metric_binding_live_20260613`, but DeepSeek returned
`HTTP 402: Insufficient Balance` before any model tokens or retrieval calls, so
that run is recorded as provider/account blockage, not capability evidence.
As of 2026-06-11, DCF/LBO are no longer only benchmark annotations: the finance
domain pack has modeling-lite transform planning for DCF and LBO, operating
cash flow / capex fact extraction, transparent assumption diagnostics, and
missing-slot acquisition hints. This is a deterministic substrate v1 for
auditable modeling traces, not a claim that Holo already solves full DCF/LBO
benchmark tasks end to end.
The 2026-06-11 retrieval workbench pivot is tracked in
`docs/KERNEL_V3_PROGRESS_2026-06-11_RETRIEVAL_WORKBENCH.md`.
The newest substrate work starts lifting finance lessons into domain-general
kernel primitives: `ClaimLedger`, `SlotFrame`, `EvidencePolicy`,
`TransformPlan`, and `VerifierGateResult`. Finance now projects its fact ledger,
formula plans, and numeric verification into those generic records while still
keeping the deterministic finance domain pack intact. This is intended to keep
Holo from becoming a finance-only benchmark script collection; future
mathematics, code, legal, policy, and research domain packs should reuse the
same slot/evidence/claim/transform/verification spine.
The same substrate now feeds acquisition hints back into retrieval: missing
finance formula facts are expressed as `SlotFrame` missing slots and an
`EvidencePolicy`, and document expansion uses those generic requirements to
prefer annual/quarterly filings for non-GAAP reconciliation/add-back tasks
instead of drifting into market-stat pages or unrelated event filings.
Reconciliation slot frames now also expose `period_series` and `source_table`,
so bridge/add-back work can distinguish "found a number" from "found the
multi-period reconciliation table needed for analyst-grade review."
The current retrieval architecture is pivoting away from threshold-centered
search decisions toward a model-guided evidence workbench. `retrieval.workbench`
is now a schema-first processor packet inside `RetrievalOperator`: after source
acquisition, fetch, extraction, deterministic qualification, and evidence
compaction, the model receives a bounded workbench packet with the task goal,
workflow type, source/fetch summaries, extracted spans, accepted evidence,
rejected evidence previews and reasons, citation state, and known slot/claim
state. The model judges source roles, accepted/rescued/rejected evidence IDs,
slot coverage, semantic missing slots, next queries, next source families, next
document targets, assumptions, and limitations. The host still owns hard
validation: the model may only reference existing IDs, cannot invent evidence or
citations, and cannot bypass authority, policy, budget, provenance, numeric
verification, or synthesis gates. Host-approved workbench rescues now promote
valid rejected/compacted evidence into real evidence and citation records, while
hard rejections such as weak authority, target mismatch, wrong SEC entity, and
template placeholders remain blocked. Workbench next queries/source families are
also converted into retrieval next-tool actions when evidence is still
insufficient. If a model planner call fails after an insufficient retrieval
report, the host can now execute the latest workbench semantic next move as a
bounded `retrieval.run` fallback; workbench follow-up payloads preserve their
model-selected query instead of being rewritten by generic query
diversification. Retrieval reports and finance benchmark metrics expose
workbench decisions, semantic missing slots, requested rescues, actual rescues,
blocked rescues, and next moves so live runs can distinguish "search failed"
from "document/evidence judgment found a semantic gap."
Workbench and judge packets are strict interfaces, not free-form advice. Each
LLM-owned judgment must fit a schema, gets journaled as a packet, and is then
validated by host provenance / policy / citation checks. The same ownership
split now applies to finance answer validation. When deterministic numeric
support checks flag unsupported numbers, semantic judgment moves to
`finance.numeric_judge`: the model classifies core numeric claims, non-core
numeric noise, missing slots, supported candidate values, whether more tool work
is required, and the exact synthesis repair instruction. The host numeric
verifier remains a hard citation/calculator/provenance check, but its diagnostics
are advisory for semantic judgment rather than the final answer arbiter. If the
judge packet cannot run because the provider is unavailable or returns invalid
JSON, Holo journals a `synthesis_gate_result` with
`gate_id=llm_semantic_numeric_judge_unavailable_v1`; traces therefore show
"LLM semantic verifier unavailable" instead of hiding that state behind a generic
`unsupported_answer_number` failure.
`finance-capability` treats that state as blocking: if `task.compile`,
`finance.numeric_judge`, or model synthesis cannot provide the required
semantic judgment, the host records the missing model-owned packet and returns a
failure/next-action instead of authoring a semantic final answer from rules.
`finance-fact-fast` still keeps conservative host fallback answers for cheap
regression and smoke runs, but those fallbacks are explicitly not the capability
lane.
The current
retrieval loop counts actual tool observations rather than payload-declared
fetch budgets, model-visible context compacts large mission/retrieval/runtime
payloads before processor calls, mission continuations preserve the original
root goal while passing the current directive separately, `chat.route` remains
model-owned with structured route-relation validation instead of phrase tables,
durable memory is visible as both project and thread context views, SEC
companyfacts/direct-URL retrieval now preserves structured financial evidence
such as concept, metric, annual/quarterly period, filing, and value fields,
finance evidence compaction uses query-derived metric intent so total-assets,
net-sales, energy-revenue, and total-revenues questions keep the closest SEC
line-item evidence instead of a generic revenue/equity row, SEC ticker/CIK
directory lookups are ranked ahead of companyfacts when the current task is
identity resolution,
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
- answer-quality learning proposals. When the host rejects or repairs a final
  answer because it misses the declared answer profile, the quality-check gap
  can become a non-blocking, reviewable memory proposal. The proposal stores
  only the profile, gap list, evidence/citation refs, answer length, and repair
  directive, not the raw failed answer; it remains pending until explicitly
  approved. Thread RAG and processor prompt compaction preserve
  `source_kind=answer_quality_check` and `quality_gaps`, so later planner calls
  see the self-iteration signal instead of a generic memory preview;
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
  `thread_rag_context.self_iteration`; active `memory.recall` hits also become
  self-iteration signals with recalled memory ids, available structured slots,
  quality gaps, and next-action hints. Prioritized `attention_blocks` are also
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
  memory-write authority. Approved memory can also expose a bounded
  `structured_summary` with safe slot values, such as answer-quality gaps or
  next-action hints, while keeping the original structured payload hashed and
  bounded;
- active-memory recall as loop working memory. Safe `memory.recall`
  observations are compacted into
  `thread_rag_context.active_memory_recalls`, including recalled ids, scope
  totals, summaries, structured summaries, provenance refs, filtered
  diagnostics, and bounded match diagnostics that explain which terms, fields,
  or structured slots made a memory relevant. Later planner packets can use
  the recalled facts before trying another recall, and can distinguish a
  generic background hit from an actionable self-iteration signal such as an
  answer-quality gap or next-action hint;
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
- Finance deterministic substrate for benchmark work: retrieval evidence can be
  projected into a `FinanceFactLedger`, common analyst formulas can be compiled
  into host-run `calculator.compute` traces, and finance final answers can pass
  through `finance.verify_numeric` before delivery. FAB v2 curated dev10 support
  and post-run annotation scoring are documented in
  `docs/KERNEL_V3_FINANCE_BENCHMARK_TRACK.md`.
- Domain-general substrate records for future packs: finance facts are also
  projected into `claim_ledger` records, finance formula plans into generic
  `transform_plan` records, finance task requirements into `slot_frame` records
  with an `EvidencePolicy`, and numeric verification into
  `verifier_gate_result` records. These records are deliberately domain-neutral:
  finance is the first adapter, not the kernel's only target domain. Benchmark
  trace metrics now expose generic substrate counters such as
  `claim_ledger_present`, `claim_count`, `slot_frame_present`,
  `missing_slot_count`, `transform_plan_count`,
  `ready_transform_plan_count`, `missing_slot_transform_plan_count`,
  `verifier_gate_status`, `verifier_gate_passed`, and
  `verifier_gate_issue_count`.
- Transaction/acquisition retrieval now treats issuer event pages and SEC 8-K
  event filings as first-class acquisition paths. The source layer can render
  multi-issuer company IR candidates, the operator critic emits
  `find_alternate_event_source` when a high-value issuer event page fails, SEC
  submission expansion ranks merger/agreement 8-Ks ahead of earnings/cost
  action 8-Ks, and extraction prioritizes M&A cash-consideration spans under
  tight span budgets. SEC complete submission bundles now use a larger readable
  window so exhibit content beyond the old prefix limit can enter the fact
  ledger. This now closes the PFE/SGEN-style FAB v2 transaction-multiple smoke
  with retrieval, ledger, calculator, and numeric verification; broader
  transaction-accounting and purchase-price-allocation coverage still needs
  more fact-ledger and formula-planner work.
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

Finance capability progress must be measured with live model runs. Permanent
rule from 2026-06-17: fake/offline commands are allowed only for
code-regression, schema, compile, and safety guards. They must never be reported
as FinanceBench, FAB/FinAgent, FinQA, or finance problem-solving accuracy.
Any score or ability claim needs a real provider/live retrieval run, with
gold/reference material used only for post-run scoring.
Default validation should stay narrow. For ordinary toolchain or loop changes,
prefer targeted unit tests plus `bench finance-tool-audit --execute-local-smoke`
when relevant. Do not run broad regressions by habit; use long or multi-item live
benchmark runs only when the objective is explicitly to measure finance problem
solving on a debug or held-out slice.

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
journal-event streaming over host-visible runtime packets and audit records. Console
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

Finance benchmark track:

Normalize public benchmark exports before running or scoring them:

```bash
holo-v3 bench finance-import \
  --benchmark finance_agent_benchmark \
  --input data/raw/finance_agent_benchmark.csv \
  --output .state/kernel_v3/bench/finance/finance_agent_benchmark.normalized.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/finance_agent_benchmark.manifest.json
```

Finance Agent v2 public questions can be imported from a local copy of the
public text file:

```bash
holo-v3 bench finance-import \
  --benchmark finance_agent_v2_public \
  --input data/raw/fabv2_public.txt \
  --output .state/kernel_v3/bench/finance/fabv2_public_dev.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/fabv2_public_dev.manifest.json
```

Known small public benchmark files can also be fetched into `data/raw` and
immediately normalized. This is the preferred reproducible path when raw files
are absent locally:

```bash
holo-v3 bench finance-fetch \
  --benchmark financebench \
  --output data/raw/financebench.jsonl \
  --normalized-output .state/kernel_v3/bench/finance/financebench_oracle.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/financebench_oracle.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/financebench_oracle.gold.jsonl \
  --mode oracle_evidence

holo-v3 bench finance-fetch \
  --benchmark finqa \
  --split test \
  --output data/raw/finqa_test.json \
  --normalized-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/finqa_test_oracle_context.gold.jsonl \
  --mode oracle_context
```

`finance-fetch` has a default `--max-bytes` guard and supports `--url` for a
local mirror or alternate export. Use `--limit`/`--offset` with
`--normalized-output` for small smoke subsets.

2026-06-11 smoke verification: the built-in fetch lane successfully downloaded
PatronusAI FinanceBench merged rows (`958,087` bytes) and FinQA `dev`
(`10,954,658` bytes), then normalized `5` oracle-mode rows from each with
`0` skipped rows and generated matching `.gold.jsonl` annotation sidecars under
`.state/kernel_v3/bench/finance/`. This verifies the gold-backed public
benchmark data path; it is not a live model score.

Follow-up runtime smoke on the same day tightened the oracle-context path. The
runtime now turns benchmark-provided oracle evidence into citable retrieval
evidence before finalization, even when the live retrieval/network lane is not
available. The first FinanceBench oracle item
(`run_financebench_oracle_smoke1_after_fallback_synthesis_gate`) now passes with
numeric accuracy `1.0`, citation preservation `1.0`, claim/slot/transform
presence `1.0`, answer numeric support `1.0`, and numeric verifier pass `1.0`
in a no-network fake-processor smoke. This uses only the provided evidence
excerpt, not the reference answer. The first FinQA oracle-context item
(`run_finqa_oracle_smoke1_after_table_average_synthesis_gate`) now also closes:
the provided context is promoted into citable evidence, a table-average
calculator preflight emits one `calculator.compute` formula trace, verifier and
synthesis gates pass, and the annotation re-score is `1.0` for overall,
workflow, substrate, and numeric scores. This proves the oracle-context path can
drive a simple FinQA numeric-reasoning item; it is still a single-item smoke,
not a broad FinQA accuracy claim.

The first FinQA oracle-context subset diagnostic also ran against `20` local
`dev` rows without network access or benchmark gold in prompts
(`run_finqa_oracle20_confirm_formula_patterns_v1`). Generic table/text
arithmetic preflight now handles recurring numeric-reasoning shapes such as
table averages, cumulative return from indexed values, percentage-of-total,
period change, simple projection, and pretax/after-tax difference. On that
subset, pass rate and numeric accuracy are `0.30`, calculator-used and
formula-trace rates are `0.60`, substrate score is `0.925`, workflow score is
`0.96`, citation preservation is `0.95`, synthesis-gate pass is `1.0`, and
unsupported numeric claim rate is `0.0`. The remaining misses expose formula
binding and target-cell selection gaps, so this is an oracle-context engineering
diagnostic rather than an official FinQA score.

Public gold-backed baseline runs have now started; see
`docs/KERNEL_V3_PUBLIC_BENCHMARK_BASELINES_2026-06-11.md` for the compact table.
The first FinanceBench-150 `oracle_evidence` no-network/fake-processor baseline
(`run_financebench_150_oracle_evidence_fake_v1`) scores pass rate `0.20`,
numeric accuracy `0.2381`, workflow score `0.9132`, substrate score `1.0`,
citation preservation `0.8733`, and unsupported numeric claim rate `0.1067`.
This verifies that public FinanceBench oracle evidence can drive the generic
claim/slot/transform/verifier/synthesis spine, but it also exposes numerical
target-selection and calculator-binding gaps.

FinanceBench `doc_retrieval` was separately run as a no-network negative
control (`run_financebench_150_doc_retrieval_fake_v1`) and as a live 3-item
source-acquisition probe (`run_financebench_doc_retrieval_live_limit3_v1`). The
negative control is not a capability score; it only confirms Holo does not
fabricate support when evidence is absent. The live3 probe performed real
retrieval work (`1.3333` average retrieval runs, `8` to `16` fetches per item)
but still scored `0/3` because it did not convert retrieved sources into citable
finance facts or formula inputs. This is now the concrete FinanceBench
doc-retrieval gap.
After the retrieval workbench pivot, focused live1 probes first exposed a
narrower target-binding failure: `run_financebench_doc_live1_workbench_v6`
produced citable facts and full workflow substrate, but supported the answer
with secondary/current StockAnalysis cash-flow data (`899M`) rather than the
FY2018 10-K cash-flow statement value (`1577M`). Issue #3 then closed the
first FinanceBench doc-retrieval item with host-owned target-document binding:
`run_financebench_doc_live1_binding_v7` passed with `numeric_within_tolerance`,
`retrieval_runs=1`, `facts=114`, `claims=114`, citation preservation `1.0`,
numeric verifier / verifier gate / synthesis gate all `passed`, unsupported
numeric claim rate `0`, and answer numeric support `100%`.

Issue #3 P0 narrows this failure with no answer table. FinanceBench doc-retrieval items
can carry a `target_document_binding` with company, document name/link/type,
target period, required statement/table, and required line item. Retrieval
Workbench packets expose that binding to the model, document extraction can
surface target table windows such as the cash-flow statement PP&E purchase row,
and the finance ledger/verifier run a host-owned
`primary_source_numeric_binding` resolver before final answer support. The host
therefore rejects secondary/current market values such as StockAnalysis `899M`
when the task requires the FY2018 primary filing cash-flow capex row. This is a
provenance and period-binding gate, not a hardcoded answer table. The follow-up
`run_financebench_doc_live3_binding_v1` small probe first showed `1/3`: all
three items reached claim ledger, slot frame, and transform plan, while items 2
and 3 were blocked by unsupported numeric synthesis / missing line-item
support. A targeted follow-up, `run_financebench_doc_live3_binding_v2`, is now
`2/3`: item 2 passes after fixing inline document-period parsing for
`Assume ...` prompts and binding balance-sheet net PP&E / net PPNE to SEC
`PropertyPlantAndEquipmentNet`. The run reports pass rate / numeric accuracy
`0.6667`, claim-ledger / slot-frame / transform-plan present rate `1.0`,
citation preservation `0.6667`, synthesis-gate pass rate `0.6667`, and
unsupported numeric claim rate `0.3333`. Item 3 remains a real
capital-intensity workflow gap: the workbench identifies missing PP&E / assets /
capex / operating-cash-flow slots, but the current run still lacks a supported
calculator/verifier path for the qualitative judgment.
Task Compiler v1 now makes that gap explicit instead of leaving it as a raw
retrieval failure. Finance questions are compiled into generic `TaskSpec`,
`EvidenceSpec`, and `TransformSpec` records before synthesis, and runtime
journals a `compiled_task_program` record alongside the claim ledger and slot
frame. In `run_financebench_doc_live3_task_compiler_v1`, the same live3 slice
remains `2/3`, but compiled-program coverage is `1.0`; item 3 is now a
`compute` task with five evidence specs, three capital-intensity transform
specs, and explicit missing slots for capital expenditures, operating cash
flow, net PP&E, and assets. The verifier/synthesis gates still reject the final
unsupported numeric answer, which is the correct host-owned failure mode until
those slots are filled and calculator traces exist.

The next target-slot iteration closes that first FinanceBench doc-retrieval
slice. `run_financebench_doc_live3_target_slots_v4` passes `3/3` with live
retrieval, pass rate / numeric accuracy `1.0`, claim-ledger / slot-frame /
transform-plan presence `1.0`, citation preservation `1.0`, numeric verifier /
verifier gate / synthesis gate pass rate `1.0`, unsupported numeric claim rate
`0`, and calculator/formula trace rate `0.3333`. The previously failing
capital-intensity item now retrieves FY2022 SEC companyfacts slots for revenue,
operating cash flow, capex, net PP&E, and assets, runs a host calculator trace
for `capital_expenditures / revenue`, and answers the benchmark's `5.1%`
numeric target with citable evidence.

The finalization/toolchain follow-up closes the same slice more cleanly as
`run_financebench_doc_live3_after_source_equivalence`: pass rate, numeric
accuracy, verifier-gate pass rate, synthesis-gate pass rate, citation
preservation, workflow score, substrate score, and dev annotation overall score
are all `1.0`, with unsupported numeric claim rate `0`. This run validates two
agent-loop fixes: quality-gated financial answers with an existing ledger now
fall back to a host-owned ClaimLedger answer instead of returning a failure
report, and synthesis/verifier failures with a valid FormulaTrace can fall back
to a formula-trace-only answer that strips model-generated unsupported numbers.
The capital-intensity workflow now carries `net_income` as a required slot and
emits model-output ratios for capex/revenue, capex/operating cash flow,
PPE/assets, and return on assets; item 3 matches the `5.1%`, `20.0%`, and
`12.4%` gold numerics. The scorer also treats target-bound structured SEC
companyfacts as an equivalent companion to the target filing only when
`primary_source_numeric_binding_status=selected`, while generic companyfacts
remain insufficient for FinanceBench `doc_retrieval`.

The same changes were expanded to a first FinanceBench doc-retrieval live10
baseline: `run_financebench_doc_live10_target_slots_v1` scores pass rate
`0.30`, numeric accuracy `0.30`, workflow score `0.6572`, substrate score
`0.60`, citation preservation `0.40`, calculator/formula trace rate `0.20`,
verifier gate pass rate `1.0` where verifier gates run, and unsupported numeric
claim rate `0`. This is a baseline, not a solved benchmark. The failures are now
clearer: several later rows produce zero finance facts/claims because target
PDF/table extraction and source acquisition are not yet robust beyond the
closed 3M slice, while one disclosure-style row has facts but the answer
contract does not match the qualitative security-list task.

On 2026-06-12 the first slice was re-run with live model + live retrieval
outside the sandbox network path as `run_financebench_doc_live3_model_net_v1`.
It still closes `3/3` with pass rate / numeric accuracy `1.0`, citation
preservation `1.0`, unsupported numeric claim rate `0`, and average retrieval
runs `1.3333`; this is the current reportable evidence that the closed live3
path is not only a fake/offline harness result. A follow-up on the fourth
FinanceBench doc-retrieval row exposed the next real gap: the Retrieval
Workbench correctly marks missing source-grounded operating-margin driver
slots, and the host can now use those missing slots to force a target-source
follow-up, but final synthesis/repair is not yet reliable for qualitative
disclosure answers. `run_financebench_doc_item4_model_net_v6` reaches
retrieval runs `2`, source hosts including `investors.3m.com`, behavior score
`1.0`, workflow/substrate score `1.0`, citation preservation `1.0`, and
unsupported numeric claim rate `0`; it still fails the numeric answer score.
`run_financebench_doc_item4_model_net_v7` exposed a benchmark-scoring false
positive: the old scorer treated the company token `3M` as `3,000,000` and
marked a failure report as passed. The scorer and FinanceBench annotation export
now reject bare compact company/name tokens as gold numerics and do not allow a
non-sentinel `failure_report` with no `final_answer` to pass; the same v7 row
re-scores as failed with expected numeric `1.7`.

The later item4 probes are run-version names for the fourth FinanceBench
doc-retrieval row (`financebench_id_01226`), not question numbers. v20 is the
important negative control: after tightening the source contract, the row no
longer passed from generic `data.sec.gov` companyfacts and instead failed with
`required_source_url_citation_missing`. v21/v22 then closed the row with target
SEC filing evidence: status `passed`, score reason `numeric_within_tolerance`,
citation preservation `1.0`, claim-ledger / slot-frame / transform-plan
presence `1.0`, verifier and synthesis gates passed, and source hosts include
`www.sec.gov` rather than only `data.sec.gov`. The remaining score artifact was
not model capability but annotation source identity: old FinanceBench
annotations compressed the target investor filing URL down to
`investors.3m.com`, while the run cited the official SEC archive for the same
accession. The benchmark scorer now preserves `required_source_urls` in new
annotations, records `target_document_source_urls` in trace metrics, and treats
same-accession SEC archive documents as equivalent target filings while still
rejecting generic companyfacts. This iteration deliberately keeps the packet
rich enough for the model to judge document role, row relevance, and missing
slots. v21 used about `382k` model tokens and v22 about `523k`; that is an
accepted reliability tradeoff until evidence capture and synthesis quality are
stable.

The next no-model scoring pass (`run_financebench_doc_item4_model_net_v22_rescore`)
confirms that source-equivalence fix: the fourth-row dev annotation overall
score is now `1.0`, with required source hit `4/4`, required source URL hit
`1/1`, numeric score `1.0`, workflow/substrate score `1.0`, and pass rate
`1.0`. To improve the next live runs rather than merely rescore old output,
FinanceBench `doc_retrieval` retrieval payloads now carry a compact
`compiled_task_hint` before acquisition. That hint is generated from
`TaskSpec` / `EvidenceSpec` / `TransformSpec` using the question and target
document binding, and the Retrieval Workbench packet exposes it to the LLM as
work-program context. It is explicitly not treated as evidence; host citation,
source, numeric, and synthesis gates still decide whether any final answer is
allowed. Workbench packet construction is also now task-aware: instead of
blindly sending the first large batch of sources, spans, accepted evidence, and
rejected evidence, it scores candidates against the compiled evidence specs,
transform specs, target document contract, statement, line item, and table-like
signals, then preserves high-value target filing candidates inside a compact
packet. Document summaries now also expose bounded reader diagnostics and
task-ranked table-like snippets, so the LLM workbench can judge whether a target
PDF/filing was parsed, whether table rows were visible, and which row-like
numeric excerpts may fill the compiled slots. These snippets are context for
semantic judgment, not evidence by themselves; final citations, source
authority, numeric support, and synthesis gates remain host-owned. Current
iteration prioritizes functional packet completeness over token economy; live
token reduction is a later optimization only after evidence and synthesis
quality hold.

The 2026-06-12 FinanceBench follow-up adds a small but general transform
coverage improvement for fixed-asset-turnover questions. The finance task
compiler now projects the requested ratio into explicit `revenue`,
`property_plant_and_equipment_net_current`, and
`property_plant_and_equipment_net_prior` slots plus a calculator transform:
`revenue / ((current net PP&E + prior net PP&E) / 2)`. This is not an answer
table; it exposes the evidence/computation program so the LLM workbench can
decide how to acquire and bind source facts while host provenance, citation,
numeric, and synthesis gates remain mandatory. Local regression confirms that
FinanceBench row `financebench_id_02987` now compiles to that program. The
later live `finance-capability` rerun
`run_financebench_doc_item9_fixed_asset_turnover_v8` passes that row with
`numeric_within_tolerance`: `retrieval_runs=1`, `fetches=12`, `facts=369`,
`claims=369`, `slots_missing=0`, `calculator_call_count=1`,
`formula_trace_count=1`, numeric verifier / verifier gate / synthesis gate all
`passed`, citation preservation `1.0`, answer numeric support `100%`, and
unsupported numeric claim rate `0`. This is a one-row capability closure, not a
claim that the broader FinanceBench live10 baseline is solved.

The follow-up trace narrowed that failure into two concrete harness issues.
First, the model-first task compiler could downgrade an explicit user-defined
ratio into a plain lookup, dropping the fallback transform and required PP&E
slots before retrieval had a chance to acquire them. The compiler now preserves
explicit deterministic formula contracts when the fallback program came from the
question itself: model output can still refine the task, but it cannot silently
remove required slots, transforms, or tool-chain missing-slot hints for a
non-risky explicit formula. Second, the retrieval workbench packet for the same
row reached roughly `148k` prompt characters and triggered an empty/invalid JSON
model response. Workbench source/document/span/evidence/rejection limits are now
smaller, while target-document and task-relevant candidates are still preserved;
the large-candidate unit test keeps the serialized workbench packet below
`55k` characters. These are capability fixes, not a new score claim. The next
live validation is a fresh `finance-capability` item9 rerun after this compact
packet path.

To make long live runs inspectable before benchmark JSONL rows are written,
`bench finance-progress` now renders a workflow snapshot directly from the
journal. It can select by `--task-id`, `--thread-id`, or `--thread-prefix`, and
shows task compile, retrieval, workbench, toolchain, claim/slot, transform,
calculator, verifier, synthesis, latest error, open processor calls, and recent
events. The command now defaults to a tail-bounded journal scan
(`--tail-bytes 67108864`; use `--tail-bytes 0` for historical full scans), so
checking progress does not repeatedly read a GB-scale global journal. It also
accepts `--run-root` to summarize the isolated benchmark directory:
`results.jsonl` line count, `summary.json` pass/fail/token fields, HTTP cache
file/byte counts, worker-state files, and matching live `bench finance`
processes from `/proc`.

The diagnostic block exposes DocumentReader parser counts / latest parser /
target-span counts, Workbench decision and semantic missing slots, SlotFrame
missing slots, formula status and missing facts, fact-ledger metric/source
coverage, and the latest benchmark status/reason. On the old item9 v2 trace it
exposes the real failure shape: four retrieval/workbench rounds, 48 fetch
attempts, 44 extractions, a toolchain plan, but zero
claim-ledger/slot-frame/transform/calculator records. On the passing item9 v8
trace it instead shows formula `ready`, `facts=369`, no missing slots, and
benchmark status `passed`, so users can tell whether a long live run is stuck,
still acquiring evidence, or already through the verifier/synthesis gates.

The first post-EdgarTools live debug rerun using this monitor was
`financebench_id_01226` at FinanceBench offset 3, run under
`finance-capability` with DeepSeek live model and SEC live retrieval. It passed
1/1 with `numeric_within_tolerance`; `summary.json` reports
`average_total_tokens=448778`. Gold/reference material was used only through
`--dev-gold` for post-run scoring and was not placed in runtime prompt/tool
context/retrieval context/memory. This is a debug-row live result, not a
test100 held-out score claim. Details are recorded in
`docs/KERNEL_V3_PROGRESS_2026-06-17_FINANCE_PROCESS_VISIBILITY.md`.

A post-change no-network rescore of the existing stable4 live outputs
(`run_stable4_event_resolver_v1_rescore_after_reader_packet`) confirms the
regression contract for previously closed representative tasks: answer and
citation presence remain `1.0`, claim ledger / slot frame / transform plan /
calculator / formula trace / verifier gate rates remain `1.0`, and unsupported
numeric claim rate remains `0.0`. The four rows are still ungraded with respect
to public pass/fail because this curated dev slice has annotation signals rather
than official FAB gold.

The finance synthesis gate also has a tighter conservative fallback path. When
model synthesis fails schema validation or emits unsupported material numbers,
the host fallback now preserves cited evidence context with bounded evidence
excerpts while masking row/table numbers as `[number]`; exact financial outputs
still have to come from the claim ledger or FormulaTrace. This makes fallback
answers more useful than a bare source list without relaxing the unsupported
numeric-claim policy.

The same compiled work program now reaches document extraction, not just the
Workbench prompt. `extract_spans()` reads `compiled_task_hint.evidence_specs`
and uses each EvidenceSpec's slot, accepted attributes, target period,
statement, and line item to generate target-document table spans. Adjacent rows
for different compiled slots are deduplicated by slot instead of by position
alone, so capital-intensity style tasks can expose revenue, capex, PP&E, assets,
and operating-cash-flow rows as separate citable candidates from the same
filing. Companyfacts readable-text projection also receives those compiled
terms through metadata intent text, improving multi-slot fact projection without
hard-coding item answers.

The fixed-asset-turnover fix also improves the document/fact handoff rather
than adding an item-specific answer table. Target filing PDF extraction now
prefers optional PyMuPDF, pypdf/PyPDF2, and pdfminer readers before the literal
fallback. Compiled EvidenceSpecs drive statement and line-item span selection,
target slots are preserved during span dedupe, target-bound natural table rows
become structured facts, and the formula planner prefers those filing table-row
facts over noisy narrative values.

FinanceBench `doc_retrieval` is now treated as a split evaluation program, not
one monolithic tuning set. The 150 public rows are divided into
`financebench_debug50` / `debug50` at offsets `0-49` and
`financebench_test100` / `test100` / `holdout100` at offsets `50-149`. The
debug50 slice is the only FinanceBench public slice used to inspect traces,
build failure taxonomy, and improve generic workflow mechanisms. The test100
slice is reserved for held-out accuracy after the system configuration is
frozen. Do not tune against item-level failures from test100 and then reuse that
same run as the held-out score. This keeps the project narrative honest: Holo
uses a bounded public debugging slice to improve source acquisition, document
reading, fact binding, toolchain use, and synthesis gates, then checks those
mechanisms on unseen FinanceBench rows with a separate 100-question accuracy
report.

The `live10` development slice also exposed a source-acquisition boundary that
looked like an agent-loop failure but was actually a missing host handoff. In
some `finance-capability` runs the planner carried the FinanceBench target
document URL inside the natural-language objective or
`compiled_task_hint.task_spec.objective`, while the retrieval host only promoted
structured `source_urls` fields to direct fetch targets. Retrieval therefore
wasted turns on SEC search/index pages instead of fetching the benchmark target
PDF first. The host now extracts explicit HTTP URLs from
`target_document_binding`, `source_refs`, prompt context, the root goal, and the
compiled task objective, then creates direct acquisition sources from them. The
URL is still not evidence; it is only an acquisition target. The LLM workbench
judges the retrieved document and the host still enforces citation, primary
source, numeric, verifier, and synthesis gates. A focused
`finance-capability` rerun, `run_financebench_doc_item1_target_doclink_v1`,
passes FinanceBench row `financebench_id_03029` with target PDF extraction,
`facts=373`, `claims=373`, source URL hit `1/1`, numeric verifier / verifier
gate / synthesis gate all passed, and answer numeric support `100%`. The
current complete live10 score to report remains the prior completed best
`5/10`; the next full live10 run should measure whether the target-URL
promotion and item9 document/fact closure lift that completed score.

Retrieval finalization now also treats loop budget exhaustion as a partial-answer
condition when citable evidence already exists. `max_tool_calls`,
`model_planner_processor_failed`, and `planner_processor_failed` can enter
source-grounded partial synthesis instead of immediately producing a generic
failure report, while citations, claim-ledger traces, verifier gates, and
synthesis gates remain host-owned. This closes the common FinanceBench shape
where retrieval has already found filing evidence but the loop stops before the
final answer path uses it.

The task compiler now also emits a model-facing `tool_chain_plan` inside each
compiled program. This is the current bridge from static workflow records to
LLM-led tool assembly: the plan lists missing slots, evidence specs, transform
specs, available tools (`retrieval.run`, `calculator.compute`, and host
verifier/synthesis gates), and candidate next moves while marking
`decision_owner=model`. Runtime replan hints expose a compact
`execution_program` to the planner before retrieval, and Retrieval Workbench
packets preserve the same `tool_chain_plan` for semantic evidence judgment.
The host does not treat the plan as evidence or a fixed script; it only
verifies provenance, source authority, citations, numeric support, policy, and
budgets after the model chooses the next move.

2026-06-17 finance tool-surface audit: Kernel v3 now exposes a complete
finance tool catalog through `finance.toolchain.describe` and keeps a compact
install summary in the planner packet. The callable open-component wrappers now
include Trafilatura extraction, DuckDB/Pandas read-only table SQL, and SymPy
symbolic/high-precision math in addition to SEC EdgarTools, Docling, OpenBB,
calculator, verifier, workspace, shell, and script tools. Finance profiles see
this tool surface even when a numeric verifier was not the only requested
capability. Recoverable component failures such as `dependency_missing`,
`component_call_failed`, `route_not_allowlisted`, or unsupported document/table
inputs re-enter the agent loop as replanning feedback; policy blocks and budget
guards remain host-owned safety boundaries.

The finance/retrieval fast lane is now a real composable workbench instead of a
fixed retrieval package. `finance-fact-fast` runtime metadata enables
`composable_toolchain`, and `retrieval_answer` recipes built from that profile
expose `retrieval.run`, read-only workspace tools (`workspace.list`,
`workspace.search`, `file.read`), `shell.exec`, and `calculator.compute` to the
model planner. The retrieval registry is built on the same permissioned
workspace registry before adding retrieval and calculator tools, so local
benchmark files, cached filings, traces, and temporary analysis commands are
actual executable tools rather than capability-catalog promises. `shell.exec`
is still host-owned: it requires `shell:exec`, an executable allowlist, PolicyGate
validation, and journaled stdout/stderr observations.

There is also a capability-first finance lane, `finance-capability`. It keeps
the LLM-led task compiler and composable toolchain, but opens a stronger
workbench surface: workspace read/write, `script.exec`, `shell.exec`, high
retrieval budgets, and larger model/context budgets. `script.exec` is the
preferred Codex-style temporary parser path: the model supplies a Python script
and expected output shape, the host writes it under `.holo_toolchain/scripts`,
runs it with bounded timeout, artifacts the script/output, and journals the
step. This keeps the workflow flexible without making shell output sovereign.
In this profile, semantic fallback is blocked: host scaffolds may expose tool
interfaces, provenance, budgets, and schema constraints, but cannot replace the
LLM's task decomposition, source/evidence relevance judgment, slot/transform
selection, numeric semantic repair, or final synthesis decision.
As of the 2026-06-13 LLM-first finalization pass, this is also true at the
retrieval and numeric gates: incomplete planned retrieval subgoals are advisory
when citable evidence already exists, and the runtime proceeds to model
synthesis instead of emitting a host-authored failure report. Deterministic
numeric verification still records provenance and support diagnostics, but
`finance.numeric_judge` can accept a semantically correct core answer when it
answers the question, does not require more work, and contains no unsupported
core numeric values. Host rules therefore remain safety, schema, budget,
calculation, and provenance boundaries; they are not the final semantic judge.

The execution program itself is now model-first in the finance fast lane.
`task.compile` is a structured processor packet that asks the LLM to produce
`TaskSpec`, `EvidenceSpec`, `TransformSpec`, `SlotFrame`, and a
`tool_chain_plan` from the question, target binding, compact fact ledger, and
host fallback scaffold. Runtime invokes this compiler before the first model
planner step when `finance-fact-fast` exposes `model_task_compiler`; the compact
program is placed in planner context as `execution_program` and journaled as a
preflight `compiled_task_program`. The deterministic finance compiler remains a
fallback and schema/provenance boundary, not the semantic owner. This shifts the
core judgment of "what work program should solve this task" to the LLM while the
host continues to validate tool permissions, citations, source authority,
numeric support, synthesis gates, and budgets.
For `finance-capability`, the same compiler is strict: if the LLM compiler is
unavailable or returns invalid JSON, runtime journals a
`task_compile_model_unavailable` program with the missing slot
`llm_task_compile_judgment` instead of letting deterministic formulas or source
rules stand in as semantic judgment.

The planner binding path also preserves model-selected composable tools. A
Retrieval Workbench `continue` decision still pulls premature `respond` actions
back into source acquisition, but it no longer overrides an explicit allowed
tool action such as `workspace.search`, `file.read`, `shell.exec`, or
`calculator.compute`. This keeps the safety gate intact while preventing the
finance fast lane from silently regressing into a retrieval-only loop after the
model chooses a local parsing or analysis step.

Composable tool outputs now enter the same grounding path used by retrieval
evidence. In `retrieval_answer`, successful `workspace.list`,
`workspace.search`, `file.read`, `workspace.write`, `shell.exec`, and
`script.exec` observations are converted into bounded evidence/citation
candidates; if no normal retrieval report exists, the host creates a synthetic
toolchain grounding report and runs the usual finance fact ledger, claim ledger,
numeric verifier, and synthesis gate. Model-authored parsers can emit JSON
`facts`, table/row payloads, or key-value lines such as
`entityName=... concept=... metric=... value=...`; the host journals them as
`toolchain_grounding_candidate` records and promotes each candidate fact into
separate evidence/citation candidates before ClaimLedger extraction. The same
merged retrieval/toolchain grounding is used before finalization by the finance
formula planner: if a model-selected `script.exec`, `shell.exec`, or `file.read`
step fills enough source-backed facts, Holo will schedule `calculator.compute`
before allowing a free-text final answer. This closes the loop from
LLM-selected temporary tooling to host-validated deterministic calculation.
The same path now journals `toolchain_artifact` for script/source/output
artifacts and `toolchain_failure` for failed local tools, so the next model
planning round can reason from the actual parser error or generated artifact
rather than losing failed toolchain steps as silent non-evidence. Finance
fallback answers prefer ClaimLedger/FormulaTrace-backed facts before raw
evidence previews; raw source-grounded previews are sanitized for numeric
fallbacks so accession numbers, filenames, and table fragments do not become
unsupported answer numbers.

FinQA `dev` oracle-context `100` no-network/fake-processor baseline
(`run_finqa_dev_oracle100_fake_v1`) scores pass rate / numeric accuracy `0.15`,
workflow score `0.925`, substrate score `0.8816`, calculator/formula-trace rate
`0.37`, citation preservation `0.92`, and unsupported numeric claim rate `0.06`.
The larger sample confirms that the remaining FinQA weakness is formula and
target binding, not citation preservation or unsupported-number hallucination.

FinanceBench-150 can be normalized from a local CSV/JSON/JSONL export in three
explicit modes:

```bash
holo-v3 bench finance-import \
  --benchmark financebench \
  --mode oracle_evidence \
  --input data/raw/financebench.jsonl \
  --output .state/kernel_v3/bench/finance/financebench_oracle.jsonl \
  --manifest-output .state/kernel_v3/bench/finance/financebench_oracle.manifest.json \
  --annotation-output .state/kernel_v3/bench/finance/financebench_oracle.gold.jsonl

holo-v3 bench finance-import \
  --benchmark financebench \
  --mode doc_retrieval \
  --input data/raw/financebench.jsonl \
  --output .state/kernel_v3/bench/finance/financebench_doc_retrieval.jsonl \
  --annotation-output .state/kernel_v3/bench/finance/financebench_doc_retrieval.gold.jsonl

holo-v3 bench finance-import \
  --benchmark financebench \
  --mode question_only \
  --input data/raw/financebench.jsonl \
  --output .state/kernel_v3/bench/finance/financebench_question_only.jsonl \
  --annotation-output .state/kernel_v3/bench/finance/financebench_question_only.gold.jsonl
```

`oracle_evidence` prompts the benchmark evidence excerpt but never the reference
answer or justification. `doc_retrieval` prompts document metadata/link only,
forcing Holo to acquire support. `question_only` removes both provided evidence
and document hints from the prompt. This lets reports separate answer quality,
document acquisition, and bare-question generalization.
`--annotation-output` writes the post-run scoring sidecar for `--dev-gold`:
workflow slots, evidence policy, required traces, dealbreakers, source
requirements, and numeric expectations extracted from the reference answer.
The sidecar is never prompt context.

FinQA now uses the same import-mode discipline:

```bash
holo-v3 bench finance-import \
  --benchmark finqa \
  --mode oracle_context \
  --input data/raw/finqa_dev.json \
  --output .state/kernel_v3/bench/finance/finqa_dev_oracle_context.jsonl \
  --annotation-output .state/kernel_v3/bench/finance/finqa_dev_oracle_context.gold.jsonl
```

FinQA oracle-context annotations now enter the generic workflow harness as
`numeric_reasoning` tasks with required slots (`question_context`,
`input_values`, `formula_or_operation`, `answer_unit`), expected
`calculator.compute` / verifier / synthesis-gate traces, and a provided-context
evidence policy. The reference program remains scoring-only and is not prompt
context.

```bash
HOLO_V3_LIVE_MODEL=1 holo-v3 bench finance \
  --dataset .state/kernel_v3/bench/finance/finance_agent_benchmark.normalized.jsonl \
  --limit 10 \
  --online \
  --research-profile finance_fundamentals \
  --research-depth deep \
  --live-retrieval \
  --live-search-strategy adaptive
```

The benchmark runner records one Holo run per question, writes JSONL item
results plus a summary, and keeps benchmark gold answers out of model/tool
prompts. `bench finance-import` supports `finance_agent_benchmark`, `secque`,
`finance_agent_v2_public`, `financebench`, `financeqa`, and `finqa` local CSV/JSON/JSONL/text
exports, preserving a provenance manifest while keeping gold answers, rubrics,
and reference reasoning out of agent prompts. Live benchmark runs are guarded by
fetch-count, per-response byte, process download-budget, and shared-cache controls; see
`docs/KERNEL_V3_LIVE_BENCHMARK_COST_CONTROL.md` before running broad parallel
live evaluations. Existing predictions can be scored without running Holo:

```bash
holo-v3 bench finance \
  --dataset data/finagent.jsonl \
  --predictions artifacts/finance_predictions.jsonl
```

Live finance benchmark runs use an explicit execution lane. The benchmark
default is `finance-fact-fast`, which bypasses resident mission supervision and
workmethod framing so simple public benchmark questions do not pay the full
long-mission cost. Its step and tool budgets are hard control-plane limits: the
host will not silently expand a fast profile into the 2048-step resident budget,
and `ProcessorFabric` blocks over-budget model calls before sending a provider
request. The current `finance-fact-fast` token budget is intentionally relaxed
for reliability while the finance substrate stabilizes; it is fast by
mission/workmethod bypass and step/tool caps, not yet by a tight token envelope.
Use `finance-capability` when the priority is problem-solving power over speed:
it exposes workspace write and `script.exec` for temporary parsers, raises
tool/model/retrieval budgets, and journals `toolchain_plan`,
`toolchain_step_proposed`, `toolchain_step_executed`, and
`toolchain_grounding_candidate` records for audit.

Finance lanes also include a deterministic finance substrate:

- `FinanceFactLedger` turns retrieval evidence, especially SEC companyfacts
  spans, into structured finance facts with metric, fiscal period, value, unit,
  evidence ref, and citation ref.
- `FinanceFormulaPlanner` is a host-side compiler for common analyst formulas
  such as CAGR, DIO, margin, basis-point deltas, EV/Revenue, YoY growth, and
  bridge subtotals. It binds formulas to fact-ledger inputs when enough facts
  exist; otherwise it emits missing-fact diagnostics for the next loop.
- `calculator.compute` is a host tool using Decimal arithmetic and an AST
  whitelist; the model proposes the formula, the host executes it.
- `finance.verify_numeric` runs as a host final gate for finance profiles that
  require numeric verification. Unsupported answer numbers, unit/scale
  mismatches, period mismatches, missing formula traces, missing fact ledgers,
  assumption-label gaps, and ledger extraction gaps become structured failure
  reports instead of polished but unsupported answers.

The repo includes a small FAB v2-style development slice:

```bash
holo-v3 bench finance \
  --dataset data/bench/finance/fabv2_dev10.jsonl \
  --dev-gold data/bench/finance/fabv2_dev10.gold.jsonl \
  --predictions artifacts/finance_predictions.jsonl \
  --output artifacts/fabv2_dev10_results.jsonl \
  --summary-output artifacts/fabv2_dev10_summary.json
```

`--dev-gold` is post-run scoring material only. It is never inserted into the
agent prompt. The dev10 dataset and gold annotation now describe each item as a
workflow pressure test, not just a finance question: `workflow_type`,
`required_slots`, `evidence_policy`, `required_transforms`, `dealbreakers`,
`expected_trace`, and `failure_taxonomy`. The summary reports behavior score,
numeric score, substrate score, workflow score, calculator usage, formula trace
count, claim/slot/transform coverage, verifier and synthesis gate status,
answer numeric support rate, unsupported numeric claim rate, missing-slot
recovery, cost per solved task, repeatability when duplicate item runs are
present, workflow type distribution, and finance numeric failure taxonomy.

The repository also keeps the official Finance Agent v2 public question file as
`data/raw/fabv2_public.txt` and its normalized local import as
`data/bench/finance/fabv2_public.jsonl`. This public27 set has no public gold,
so use it for behavior/substrate/cost/failure-taxonomy coverage rather than
official accuracy claims. A separate
`data/bench/finance/holo_finance_workflow_challenge.jsonl` file defines
50 workflow-oriented challenge tasks across compute/compare, reconciliation,
event transactions, valuation multiples, coverage ratios, earnings analysis,
disclosure diff, market-event analysis, modeling-lite, and regulatory-ratio
workflows. These items have workflow annotations and dealbreakers but no gold
answers; they are a pressure suite for trace quality, not a score target.

Latest public27 live workflow run:
`run_public27_workflow_v1` ran all 27 public questions with `finance-fact-fast`,
mission disabled, live retrieval, model planner, fake evaluator, model
synthesizer, compact context, and serial execution. Because the public file has
no gold, the run is ungraded for accuracy. It reports behavior/substrate health:
claim-ledger, slot-frame, and transform-plan present rates `0.6296`,
calculator-used and formula-trace rates `0.2222`, citation preservation
`0.2593`, numeric-verifier and verifier-gate pass rates `0.0909`,
synthesis-gate pass rate `0.1111`, unsupported numeric claim rate `0.3704`,
average numeric support `0.4456`, average retrieval runs `2.2593`, and average
tokens `87,928.4`. Failure modes cluster around qualitative disclosure tasks
that need a generic ClaimLedger and numeric tasks where SynthesisGate correctly
blocks unsupported numbers. This is the public generalization baseline, not a
success claim.

Latest live benchmark status: the finance substrate now closes the stable4
showcase items through the generic workflow spine. The 2026-06-10 dev10 rerun
(`run_dev10_event_resolver_v1`) used `finance-fact-fast`, mission disabled,
live retrieval, model planner, fake evaluator, model synthesizer, compact
context, and serial execution. The first four items, HD/LOW DIO, KHC adjusted
EBITDA bridge, PFE/Seagen transaction multiple, and WSC adjusted EBITDA
add-back trend, each closed with retrieval evidence, structured finance facts,
claim ledgers, slot frames, transform plans, calculator/formula traces,
citations, numeric verification, and verifier-gate pass. PFE/Seagen is no
longer just an occasional smoke pass: the new SEC event-source resolver derived
EX-99.1 transaction disclosure candidates from SEC submissions metadata, filled
transaction value and revenue slots, triggered `calculator.compute`, and passed
numeric verification in both the PFE-only rerun and the full dev10 rerun. These
are real live runs, not fixed-answer tests.

The full curated dev10 is still not solved as a benchmark, but the latest
score is materially stronger than the older `0.8111` baseline. The newest run
produced post-run dev annotation `overall_score=0.9056`, behavior `0.9167`,
substrate `0.8`, numeric `1.0`, calculator-used rate `0.4`,
formula-trace-present rate `0.4`, claim-ledger and slot-frame present rates
`1.0`, transform-plan present rate `1.0`, verifier-gate pass rate `0.5`,
synthesis-gate pass rate `0.5`, citation-present rate `0.6`, and average
answer numeric support `0.7953`. At that checkpoint, the remaining failures were
concentrated in harder modeling/valuation tasks such as CRM DCF, EPAM LBO,
TGT/WMT fixed-charge coverage, LULU/VSCO EV/EBITDA, CNC MLR rebate, and
PFE/Seagen purchase-price allocation. Subsequent passes have promoted
EV/EBITDA, purchase-price allocation, fixed-charge coverage, and MLR rebate into
planner coverage; fresh live benchmark reruns are still required before treating
those historical failures as closed in the benchmark score. That is the desired
reliability posture: unsupported finance numbers should be stopped, not polished
into a confident answer.

2026-06-11 modeling-lite substrate update: DCF and LBO now have deterministic
`TransformPlan` support in the finance formula planner. DCF can bind free cash
flow directly or derive a base free-cash-flow input from operating cash flow
less capital expenditures, then generate a discounted cash-flow calculator
payload with explicit growth, discount-rate, terminal-growth, and forecast-year
assumption diagnostics. LBO can bind entry enterprise value, debt/cash, EBITDA,
leverage, exit multiple, EBITDA growth, debt-paydown, and hold-period
assumptions into a sponsor IRR calculator payload. Missing DCF/LBO slots now
feed structured retrieval hints and source-family policy back into the agent
loop. This improves the workflow substrate for CRM DCF / EPAM LBO-style tasks,
and fresh live reruns now show both tasks reaching formula traces; their dev10
scores still should not be upgraded until the answer gate removes unsupported
numeric claims and labels assumptions cleanly.

Fresh 2026-06-11 live modeling-lite checks confirm the substrate enters the
real loop but also show the remaining answer gate gap. A CRM DCF single-item
run (`run_modeling_lite_dcf_lbo_v1`) produced `retrieval_runs=1`,
`calculator_call_count=1`, `formula_trace_count=1`, `finance_fact_count=106`,
and `claim_count=106`, but failed `finance.verify_numeric` because the final
answer still contained unsupported material numbers. EPAM LBO initially had no
calculator trace; after adding revenue-margin and entry-multiple modeling
fallbacks, `run_epam_lbo_after_revenue_margin_fallback_v1` produced
`calculator_call_count=1`, `formula_trace_count=1`, `transform_plan_count=2`,
and `substrate_score=0.8889`. It still failed the verifier and synthesis gate
because the answer path needs stronger assumption separation and removal of
unsupported numeric claims. This is progress in the workflow substrate, not a
full modeling benchmark pass.

DCF/LBO model trace hardening now makes these modeling paths more than a single
opaque calculator expression. `calculator.compute` accepts planner diagnostics
and writes them into `FormulaTrace`, so DCF/LBO runs can carry auditable model
schedules through the journal. DCF traces include annual projected free cash
flow, discount factors, present values, terminal free cash flow, terminal value,
PV of terminal value, enterprise value, net debt, equity value, and optional
equity value per share when share count is available and requested. LBO traces
include entry enterprise value, initial debt, sponsor equity, annual EBITDA and
debt-paydown schedule, exit enterprise value, exit debt, exit equity value,
MOIC, and sponsor IRR. The calculator remains deterministic; assumptions are
explicitly labeled in diagnostics instead of being treated as retrieved facts.
The model-output selector also aligns the calculator result with the user's
requested valuation output: DCF can return enterprise value, equity value, or
equity value per share, while LBO can return sponsor IRR, MOIC, or exit equity
value. This prevents benchmark/user questions from being scored against the
wrong default modeling output even when the right value exists elsewhere in the
trace diagnostics.

The finance numeric verifier now treats `FormulaTrace.diagnostics.model_outputs`
and explicit `assumptions` as supported calculator-derived values. This lets
DCF/LBO answers cite enterprise value, equity value, MOIC, IRR, discount/growth
assumptions, and related bridge outputs without being incorrectly blocked as
unsupported numbers. The host conservative fallback also summarizes key
DCF/LBO model outputs and labels modeling assumptions when the model synthesizer
adds unsupported figures. This improves answer-gate robustness, but CRM DCF /
EPAM LBO still need fresh live reruns before their benchmark statuses are
upgraded.

After adding workflow annotations, replay-scoring the same live dev10 results
with `run_dev10_event_resolver_v1.workflow_scored` yields
`overall_score=0.9114`, behavior `0.9167`, substrate `0.8889`,
workflow `0.8399`, numeric `1.0`, unsupported numeric claim rate `0.4`,
citation preservation `0.6`, and the same core transform/modeling gaps. This is
the more honest project metric because it checks whether the agent walked the
expected slot/evidence/claim/transform/verifier/synthesis path, not only whether
the final answer looked plausible.

2026-06-11 Finance Workflow RC hardening:
the current release-candidate artifacts have been regenerated and frozen under
`.state/kernel_v3/bench/finance/` as markdown reports:
`run_stable4_event_resolver_v1.report.md`,
`run_dev10_event_resolver_v1.report.md`,
`run_dev10_event_resolver_v1.workflow_report.md`, and
`run_public27_workflow_v1.report.md`. These reports preserve the current RC
story: stable4 is the closed workflow showcase, dev10 is the curated scored
regression set, workflow-rescore is the stricter trace-oriented score, and
public27 is an ungraded external generalization health check. The tracked
GitHub-facing summary is
[`docs/KERNEL_V3_FINANCE_WORKFLOW_RC_2026-06-11.md`](docs/KERNEL_V3_FINANCE_WORKFLOW_RC_2026-06-11.md).
The 2026-06-13 capability-first live iteration is tracked in
[`docs/KERNEL_V3_LIVE_ITERATION_2026-06-13.md`](docs/KERNEL_V3_LIVE_ITERATION_2026-06-13.md).
That note records the current LLM-owned judgment pivot, compact LLM synthesis
rescue, high-parallel FAB dev10 and FinanceBench doc-retrieval live results,
and the remaining document/table grounding and numeric-selection gaps. It now
also records the global FinAgent FE live10 dev/test split: both the dev
high-score slice and the separate 10-item test/holdout slice scored `8/10`
strict and `8/10` under the post-run reasonable/source-grounded judge, while
preserving complete citation, ClaimLedger, SlotFrame, TransformPlan,
numeric-verifier, and synthesis-gate traces. A broader live holdout stress run
scored `9/20`, and two live failure-regression batches repaired five real
previous failures: `FE_009` Goldman net revenues, `FE_031` Apple R&D,
`FE_037` JPMorgan net interest income, `NR_005` Meta net income growth, and
`NR_004` NVIDIA gross margin. The remaining known gaps are total-revenue
line-item disambiguation, incorrect-premise synthesis closure, revenue
denominator acquisition for some margin questions, and debt-to-equity final
answer alignment. The FinanceBench doc-retrieval live10 slice is still not
solved, but it now exposes claim/slot/transform and synthesis-gate traces
instead of failing as an opaque retrieval loop.

The next public27 work is now deliberately narrow. Generic source-grounded
retrieval finalization writes a domain-neutral `ClaimLedger`, `SlotFrame`, and
`TransformPlan` even when a qualitative disclosure task has no formula to run,
so non-numeric research tasks can still be measured by the workflow spine.
The finance SynthesisGate also has a conservative repair path: when a model
answer contains unsupported material finance numbers, host fallback strips the
unsupported numeric claim, preserves available citation refs, and returns a
limitation answer instead of failing only because no calculator trace exists.
This is intended to improve public27 citation preservation and synthesis-gate
pass rates, but the public27 metrics above remain the baseline until a fresh
live rerun is completed.
The latest KHC adjusted-EBITDA bridge pass improves the deterministic substrate:
the fact ledger now keeps an `Adjusted EBITDA` amount even when the next table
title is an EPS reconciliation, and bridge planning groups facts by
citation/evidence/source before selecting one reconciliation-table column. This
prevents annual and quarterly facts, or two adjacent annual columns, from being
summed together in one formula trace. If a candidate component subtotal does not
match the reported adjusted subtotal, the formula planner now falls back to a
conservative `reported_adjusted` calculator trace instead of emitting a bad
mixed-component formula. That fallback uses related reconciliation-table facts
to preserve scale such as `in millions`, so a disclosed `6,003` in a millions
table is traced as `6003000000 USD`, not `6003 USD`. A live KHC smoke after this
fix reached one retrieval run, one calculator trace, 218 finance facts,
`finance.verify_numeric=passed`, 100% answer numeric support, and 100% post-run
dev annotation score. The user-visible answer is still a host fallback when the
model synthesizer includes unsupported numbers, so product-quality synthesis is
still a follow-up; the reliability gate is now doing the right thing.
The synthesizer prompt and retrieval-report diagnostics now state the finance
numeric-claim policy explicitly: material finance numbers must come from
calculator traces, finance/claim ledger facts, or explicitly labeled
assumptions; unsupported numbers must be omitted or moved into limitations
before the host verifier checks them again.
The main failure mode is still `required_trace_missing` on harder modeling and
assumption-policy tasks, especially cases such as CRM DCF and EPAM LBO. The
coverage families for fixed charges, EV/EBITDA, purchase-price allocation, and
MLR rebate now have host-side FormulaTrace coverage, but still need fresh live
reruns to prove end-to-end benchmark closure. The next work is to expand
`FinanceFormulaPlanner`, ledger extraction, and optional LLM-assisted fact/noise
review for remaining task families while keeping the deterministic numeric gate
intact.

EV/EBITDA has since been promoted into the formula planner. The host can now
recognize EV/EBITDA intent, compute it from direct EBITDA or from complete
EBITDA components, group comparison tasks by entity, and compile a targeted
missing-fact retrieval action when market cap / enterprise value, debt, cash,
or EBITDA inputs are absent. `FinanceFactLedger` also extracts market-data-page
facts such as market cap, enterprise value, total debt, total cash, and EBITDA
from natural text, so those facts can feed host calculator traces when acquired.
Source-query generation now includes Yahoo Finance key-statistics pages and
ranks them first for EV/EBITDA valuation missing-fact queries.
A live LULU/VSCO rerun still did not close because the acquired evidence lacked
those inputs, but the failure is now explicit `missing_facts` instead of
`no_supported_formula_intent`.

Use `--execution-profile long-mission` only when the task is intended to
exercise the full resident loop.

```bash
holo-v3 bench finance \
  --dataset .state/kernel_v3/bench/finance/finance_agent_benchmark_public.normalized.jsonl \
  --limit 5 \
  --execution-profile finance-fact-fast \
  --live-retrieval
```

Task behavior graphs can be exported for benchmark reports and debugging:

```bash
holo-v3 behavior-graph <task_id> --format json
holo-v3 behavior-graph <task_id> --format dot --output graph.dot
holo-v3 bench finance-graph --results artifacts/finance_bench_results.jsonl --format dot --output finance_bench.dot
holo-v3 bench finance-report --results artifacts/finance_bench_results.jsonl --output finance_bench_report.md
holo-v3 workflow-view --thread-prefix financebench-doc-item3 --output .state/kernel_v3/visuals/item3.html
```

The task graph is journal-derived and links model requests/results, actions,
retrieval queries, sources, fetches, artifacts, documents, evidence, citations,
feedback, and final answers or failure reports. The benchmark graph summarizes
many result rows by status, category, score reason, failure mode, citation
coverage, FormulaTrace fact/citation/evidence provenance, processor task/error
clusters, cache hit ratio, token use, retrieval runs, fetches, repetition, and
answer length. Both views store previews, refs, hashes, and diagnostics rather
than raw fetched
bodies. The benchmark report renders the same result file into Markdown, HTML,
or JSON for project reports and review meetings.
`workflow-view` is the presentation/debugging view for a single run. It scans the
journal JSONL directly, so it works on WSL thread-local journals while a run is
in progress, and renders a standalone HTML page that Windows can open in a
browser. The page shows stage topology, packet timeline, LLM processor packets,
model-owned workbench/judge decisions, tool and retrieval events, claim/slot/
transform substrate records, verifier/synthesis gates, final/failure state, and
the compact JSON behind each packet. This is the intended demo surface for
explaining the internal workflow through host-visible packets, tool observations,
evidence records, and verifier state.

See `docs/KERNEL_V3_FINANCE_BENCHMARK_TRACK.md` for the scoring schema and
planned Finance Agent Benchmark / FinAgent / SECQUE / FinanceQA path.

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

Recent finance modeling hardening also carries FormulaTrace model context all
the way to final synthesis and numeric judgment. DCF/LBO-style traces now expose
compact `assumptions`, `defaulted_assumptions`, `model_outputs`, and projection
summaries to the LLM judge and synthesizer, while the host policy states that
assumptions are not filing facts and unsupported model drivers or comparison
thresholds must not be invented. This improves general modeling-task repair
without adding answer tables or host-side semantic selection.
Debt-to-equity traces now also carry selected numerator/denominator line-item
semantics, so a ratio computed with total liabilities can be stated as such
instead of being silently rewritten as debt-only.
Margin planning also accepts more statement-level revenue denominator variants
already preserved by the fact ledger, including `sales and other operating
revenues`, `operating revenues`, `net revenue`, and related SEC revenue
concepts, while keeping deferred/contract-liability/segment pollution blocked.
Incorrect-premise finance questions now get a weak `question_numeric_premise`
hint path: question-embedded currency/scale/percent figures are compared against
supported FinanceFact and FormulaTrace values and exposed to synthesis and
`finance.numeric_judge`, so the LLM can state a corrected actual value when the
evidence contradicts the premise. The host only carries the hint; it does not
decide the semantic answer.
Purchase-price-allocation questions now have a dedicated formula planner path
for business-combination and acquisition-accounting tasks. The planner binds
purchase consideration, goodwill, and identifiable intangible assets into
FormulaTrace payloads, can focus on goodwill-only or intangible-only subclaims,
prefers acquisition-table facts over balance-sheet totals when both are present,
and rejects per-share purchase prices as total consideration so merger press
release evidence does not pollute the calculation.
Fixed-charge coverage questions now have a dedicated planner and retrieval path
as well. The ledger canonicalizes filing line items such as earnings available
for fixed charges and total fixed charges, the planner computes the coverage
multiple from direct disclosures or a pretax-income-plus-fixed-charges basis,
and missing-fact retrieval seeds SEC companyfacts / Exhibit 12 terms instead of
falling back to a generic search.
MLR rebate questions now have a regulatory-ratio planner path. The ledger
canonicalizes medical loss ratio, MLR standard, premium denominator, claims/QI
numerator, and rebate line items; the planner computes actual MLR from reported
ratio or complete numerator/denominator facts, then computes rebate as the
positive shortfall versus the required standard times adjusted premium revenue.
It does not default the standard unless the question or evidence states the
standard or a clear individual/small-group/large-group market segment.

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
