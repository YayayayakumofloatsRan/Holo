from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from kernel_v3.contracts import JsonObject, ProcessorRequest, ProcessorResult


@dataclass(frozen=True, kw_only=True)
class ProcessorRoute:
    task_type: str
    provider: str
    model: str
    timeout_seconds: int = 30
    parameters: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class JsonSchema:
    name: str
    required: dict[str, str]
    optional: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ProcessorOutcome:
    request: ProcessorRequest
    result: ProcessorResult
    parsed: JsonObject | None
    provider: str
    model: str
    task_type: str
    duration_ms: int
    repaired: bool = False
    repair_attempts: int = 0
    raw_text: str | None = None


@dataclass(frozen=True, kw_only=True)
class FinalAnswer:
    status: str
    answer: str | None
    citation_refs: list[str]
    confidence: float
    limitations: list[str]
    used_evidence: list[str]
    error: str | None = None

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "answer": self.answer,
            "citation_refs": list(self.citation_refs),
            "confidence": self.confidence,
            "limitations": list(self.limitations),
            "used_evidence": list(self.used_evidence),
            "error": self.error,
        }


class ProcessorProvider(Protocol):
    name: str
    model: str

    def run(self, request: ProcessorRequest) -> ProcessorResult:
        ...


PLANNER_SCHEMA = JsonSchema(
    name="planner.propose",
    required={
        "action_id": "str",
        "kind": "str",
        "description": "str",
        "payload": "dict",
        "reasons": "list",
        "side_effect_class": "str",
    },
    optional={"name": "str|null", "score": "number"},
)

EVALUATOR_SCHEMA = JsonSchema(
    name="evaluator.assess",
    required={"status": "str", "missing_evidence": "list"},
    optional={"answer": "str|null", "stop_reason": "str|null", "reason": "str"},
)

RETRIEVAL_WORKBENCH_SCHEMA = JsonSchema(
    name="retrieval.workbench",
    required={},
    optional={},
)

TASK_COMPILE_SCHEMA = JsonSchema(
    name="task.compile",
    required={
        "task_spec": "dict",
        "evidence_specs": "list",
        "transform_specs": "list",
    },
    optional={
        "slot_frame": "dict",
        "tool_chain_plan": "dict",
        "missing_slots": "list",
        "reason_summary": "str",
        "diagnostics": "dict",
    },
)

SYNTHESIZER_SCHEMA = JsonSchema(
    name="synthesizer.answer",
    required={
        "answer": "str",
        "citation_refs": "list",
        "confidence": "number",
        "limitations": "list",
        "used_evidence": "list",
    },
)


SEMANTIC_INTAKE_SCHEMA = JsonSchema(
    name="semantic.intake",
    required={
        "primary_intent": "str",
        "suggested_mode": "str",
        "compound": "bool",
        "requires_clarification": "bool",
        "intents": "list",
        "blocked_capabilities": "list",
        "warnings": "list",
        "response_hint": "str|null",
        "clarification_question": "str|null",
    },
)


CHAT_ROUTE_SCHEMA = JsonSchema(
    name="chat.route",
    required={
        "route": "str",
        "command": "str|null",
        "target_task_id": "str|null",
        "confidence": "number",
        "reasons": "list",
    },
    optional={"route_relation": "dict"},
)


MISSION_ASSESS_SCHEMA = JsonSchema(
    name="mission.assess",
    required={
        "decision": "str",
        "coverage_score": "number",
        "covered_requirements": "list",
        "missing_requirements": "list",
        "next_directive": "dict|null",
        "confidence": "number",
        "reason_summary": "str",
    },
    optional={"unsupported_claims": "list"},
)


CHAT_ROUTE_PROMPT_CONTRACT = """Return one JSON object matching chat.route.
Fields: route string, command string or null, target_task_id string or null,
confidence number 0..1, reasons string array, optional route_relation object.
route_relation may include same_task boolean, is_standalone_goal boolean,
and relation_reason string.
Allowed routes: summary, new_task, continue_task, continue_plan, answer_pending_question.
Allowed commands: approve_plan, reject_plan, or null.
Use broad semantic judgment over the current user turn and provided thread state.
Pending user input is context, not a forced route. Use answer_pending_question only
when the turn directly supplies the missing information, approval, rejection, or
parameter for the pending task. Use new_task for a complete standalone goal, even
when an older broad clarification is pending. Use summary only for prior
conversation recap, not current agent/runtime state. Summary is for broad
overview/recap/list-history requests. If the user asks a specific question whose
answer should be extracted from current thread context, route new_task so the
normal agent can answer naturally from the compiled thread context. A broad
pending clarification from a vague turn such as "I do not understand" must not
capture later operational goals such as search, retrieval, research, file
read/write, time, or system-state requests; classify those as new_task. Use
summary only for explicit broad recap/history requests; a bare confusion turn
such as "I do not understand" is not a summary request.
When pending_user_input is true, always fill route_relation from semantic
comparison, not from phrase matching. If the turn is a standalone goal rather
than an answer to the pending question, set same_task=false and
is_standalone_goal=true.
The model only classifies the turn. The host validates state, policy, pending questions,
unfinished plans, and execution. Never request tool execution or memory writes here."""


SEMANTIC_INTAKE_PROMPT_CONTRACT = """Return one JSON object matching semantic.intake.
Fields: primary_intent string, suggested_mode one of direct_answer/semantic_answer/retrieval_answer/workspace_answer/workspace_write/system_answer/clarify_first,
compound boolean, requires_clarification boolean, intents array, blocked_capabilities string array,
warnings string array, response_hint string or null, clarification_question string or null.
Each intent object should include: kind, text, sequence_index, required_capabilities, risk, status, metadata.
Example shape:
{"primary_intent":"roleplay","suggested_mode":"direct_answer","compound":false,"requires_clarification":false,"intents":[{"kind":"roleplay","text":"Act as a cautious legal intern","sequence_index":1,"required_capabilities":[],"risk":"none","status":"ready","metadata":{"style":"legal intern"}}],"blocked_capabilities":[],"warnings":[],"response_hint":null,"clarification_question":null}
Example detailed research output contract:
{"primary_intent":"frontier_research","suggested_mode":"retrieval_answer","compound":false,"requires_clarification":false,"intents":[{"kind":"frontier_research","text":"research recent papers and open problems","sequence_index":1,"required_capabilities":["retrieval.run","academic.frontier_research"],"risk":"none","status":"ready","metadata":{"domain":"academic","answer_profile_hint":{"format":"detailed_report","detail_level":"detailed","target_sections":["摘要","关键文献与来源","前沿方向","争议与开放问题","证据质量与局限"],"quality_gate":"strict"}}}],"blocked_capabilities":[],"warnings":[],"response_hint":null,"clarification_question":null}
Use broad semantic judgment instead of keyword matching. Split compound user requests into ordered intents.
Do not require user clarification merely because there are multiple safe steps. For safe read-only compound tasks with clear arguments, set requires_clarification=false and keep the executable mode. Use semantic_answer for broad safe non-tool work such as roleplay, professional framing, education, communication drafting, operations planning, product/risk review, strategy, project planning, and other host-visible semantic work that should not collapse to workspace. Ask the user only when critical scope/tool arguments are missing, a capability is blocked, or the user explicitly requests interruption/confirmation.
For local file/report generation, use suggested_mode=workspace_write and required_capabilities including workspace.write or workspace:write when the host can validate a concrete workspace-relative path and text payload. Put {"workspace.write":{"path":"...","text":"..."}} under metadata.capability_args when available.
The intent kind may be an open semantic label; executable routing comes from
required_capabilities and host validation, not from a fixed phrase table.
Use the host capability catalog as the state/capability vocabulary. Do not
collapse broad tasks into workspace labels when a better capability family
exists, such as finance.*, durable_memory.*, artifact.*, data.*, code.*,
project.*, resident.*, transport.*, calendar.*, system.*, or security.*.
If a capability is planned, host_only, not_configured, or requires permission,
represent that boundary in required_capabilities/status/warnings instead of
pretending it is executable.
When a capability needs structured arguments, put them under metadata.capability_args,
keyed by capability name, for example {"file.read":{"path":"README.md"}}.
For multi-part research, metadata.capability_args may contain a list of payloads
for one capability, for example {"retrieval.run":[{"query":"official filing revenue"},{"query":"issuer investor relations margin"}]}.
The host will expand each payload into one bounded tool proposal and still
validate policy, budgets, evidence, and termination.
For retrieval-heavy work in any domain, include a model-owned generic
metadata.retrieval_strategy under the retrieval.run payload when useful. This
strategy is not a domain template; it is the model's current research plan. It
may include task_understanding, domain_hypotheses, source_family_plan,
query_plan, avoid_repeating, fallback_moves, evidence_criteria, and stop_when.
Use it for mathematics, physics, policy, engineering, finance, humanities,
private workspace research, or any other domain where the best source families
and query moves require semantic judgment.
When useful, include metadata.domain, metadata.activity, metadata.resource, and
metadata.execution_surface to preserve broad agent state such as finance,
database, cloud, workflow, knowledge_base, multimodal, resident, transport,
calendar, security, or physical-world boundaries. These metadata fields do not
grant permission; they help the host preserve state instead of collapsing all
work into workspace.
When useful, include metadata.state_axes with broad operating-state coordinates
from the host catalog, such as goal_structure, dependency_state,
commitment_state, preference_state, memory_scope, planning_depth,
operation_runtime, quality_bar, interruption_policy, authority, temporal, and
identity_boundary. These coordinates describe the task for host audit and
planning; they do not authorize tools.
When the user asks for a detailed report, deep research, memo, comprehensive
analysis, or a short/brief answer, preserve that output preference in
metadata.answer_profile_hint with keys such as format, detail_level,
target_sections, language, and quality_gate. Use quality_gate="strict" only
when the user or task semantics require a materially complete answer shape;
otherwise use quality_gate="advisory". This is an output contract hint, not
permission.
For host-state questions such as current time, environment facts, or runtime status, use
suggested_mode=system_answer and required_capabilities such as ["system.time"]; put
optional arguments under metadata.capability_args, for example {"system.time":{"timezone":"Asia/Shanghai"}}.
For memory/continuity questions such as "what do you remember", "what did we
discuss", user preferences, or prior project decisions, use
suggested_mode=semantic_answer and required_capabilities such as
["durable_memory.search"]. Put optional payload under metadata.capability_args,
for example {"memory.recall":{"query":"recent project preferences","scope_mode":"both"}}.
Durable memory read/search is allowed as a host tool when configured; durable
memory writes still require proposal/review and are never executed directly.
For workspace directory listing, use suggested_mode=workspace_answer and required_capabilities
["workspace.list"]; put optional arguments under metadata.capability_args, for example
{"workspace.list":{"path":"."}}. For known file content, use file.read. For locating
unknown files, use workspace.search.
The model classifies and proposes structure only. The host validates capabilities, policy, execution, memory, and stop.
Do not request live transports, direct tool execution, memory writes, or unavailable tools as executable actions."""


PLANNER_PROMPT_CONTRACT = """Return one JSON object matching planner.propose.
Fields: action_id string, kind one of respond/tool/ask_user, name string or null,
description string, payload object, score number 0..1, reasons string array,
side_effect_class one of none/read/write/destructive/shell/network.
Example direct answer:
{"action_id":"act-direct-1","kind":"respond","name":null,"description":"answer within provided context","payload":{"text":"I can answer from the current context, or ask the host to use an approved tool when needed."},"score":0.86,"reasons":["no external tool required"],"side_effect_class":"none"}
Example host tool proposal:
{"action_id":"act-retrieval-1","kind":"tool","name":"retrieval.run","description":"collect bounded external evidence","payload":{"goal":"Find official API documentation","query":"official API documentation"},"score":0.9,"reasons":["current external evidence is required"],"side_effect_class":"network"}
Example model-owned retrieval strategy proposal:
{"action_id":"act-retrieval-strategy-1","kind":"tool","name":"retrieval.run","description":"run a domain-general research strategy chosen from the task semantics","payload":{"query":"hyperbolic dynamics frontier research open problems","max_queries":12,"metadata":{"retrieval_strategy":{"strategy_id":"model-academic-frontier-1","task_understanding":"Find recent research directions and open problems, not basic definitions.","domain_hypotheses":["mathematics","dynamical systems"],"source_family_plan":[{"family":"scholarly_preprint","reason":"frontier work appears first in preprints"},{"family":"scholarly_publisher","reason":"journal papers and surveys support claims"},{"family":"scholarly_index","reason":"indexes expose authors, venues, and related papers"}],"query_plan":[{"query":"hyperbolic dynamics recent papers open problems survey","purpose":"survey and open problem framing","source_family":"scholarly_index"},{"query":"site:arxiv.org hyperbolic dynamics open problems recent","purpose":"preprint frontier search","source_family":"scholarly_preprint"},{"query":"hyperbolic dynamics state of the art survey ergodic theory","purpose":"publisher or survey sources","source_family":"scholarly_publisher"}],"avoid_repeating":["dictionary definitions","generic encyclopedia pages"],"fallback_moves":[{"query":"hyperbolic dynamics conference proceedings recent advances"},{"query":"uniformly hyperbolic systems recent survey open questions"}],"evidence_criteria":["recent papers, surveys, proceedings, DOI/arXiv records"],"stop_when":["multiple independent scholarly sources cover directions and limitations"]},"search_strategy":"aggregate"}},"score":0.91,"reasons":["the task requires semantic source selection beyond a fixed domain template"],"side_effect_class":"network"}
Example workspace write proposal:
{"action_id":"act-write-1","kind":"tool","name":"workspace.write","description":"write a host-validated workspace artifact","payload":{"path":"reports/summary.md","text":"# Summary\n..."},"score":0.86,"reasons":["user requested a local file artifact"],"side_effect_class":"write"}
Example workspace directory proposal:
{"action_id":"act-list-1","kind":"tool","name":"workspace.list","description":"list a workspace directory","payload":{"path":"."},"score":0.9,"reasons":["the user asked to inspect the local directory"],"side_effect_class":"read"}
Example active memory recall:
{"action_id":"act-memory-1","kind":"tool","name":"memory.recall","description":"recall workspace and thread memory before answering","payload":{"query":"user preferences and recent project decisions","scope_mode":"both","limit":12},"score":0.88,"reasons":["the answer depends on prior workspace/thread memory"],"side_effect_class":"read"}
Example clarification:
{"action_id":"act-clarify-1","kind":"ask_user","name":null,"description":"ask for missing scope","payload":{"question":"Which market, region, and time range should I research?"},"score":0.82,"reasons":["research scope is underspecified"],"side_effect_class":"none"}
For user-visible respond/ask_user payload text, match the user's language when it is clear.
If a response_language preference is present in context, use it as the default for user-visible text when the user's requested language is unclear or mixed.
For user-visible respond/ask_user payload text, never begin with generic
agreement or flattery. If the user is correcting the system or reporting a bug,
name the specific issue and propose the next concrete action instead of saying
"you are right" or an equivalent acknowledgement.
For roleplay/persona requests, speak in the requested role without parenthesized stage directions or action narration unless the user explicitly asks for script/stage directions/action narration.
Treat compound user requests as multiple subrequests. If the context contains a ready host-validated plan with allowed tools and clear payloads, propose the next executable safe action instead of asking for confirmation.
When context.state.agent_retrieval_plan_state contains planned_subgoals, choose a retrieval.run goal_id from that list, usually next_recommended_goal_id, and preserve that goal_id in the payload so host coverage can track progress.
When feedback.status is continue, inspect feedback.missing_evidence and the latest observations, then propose a materially new next action when one is available. Avoid repeating the same action payload unless the context shows new progress or the host explicitly asks for a retry.
When context.state.agent_replan_hints.status is needs_replan, use its retrieval gaps, suggested_query_hints, suggested_search_strategies, do_not_finalize_until, and avoid_repeating fields to propose one materially different safe action. Do not answer as final while any do_not_finalize_until rule is unmet.
When context.state.mission_context is present, treat mission_context.mission_state.root_goal as the global objective for the whole task, not merely as commentary. Use mission_context.directive and context.state.thread_rag_context to understand previous attempts, evidence, failures, and conversation continuity. If the previous run failed but the mission directive says continue, propose a materially different safe action instead of giving up or asking the user by default.
When context.state.thread_rag_context.task_continuity is present, treat it as
the host-compiled working note for this task: preserve current_objective, cover
open_requirements, honor avoid_repeating unless the strategy materially
changes, and use suggested_actions as candidate next moves rather than final
answers.
When context.state.durable_memory_context is present, treat it as the passive
scoped memory snapshot already paged into this run. Use its top_items and view
totals when they cover the task; if prior knowledge is needed but the snapshot
is sparse, propose memory.recall when that tool is available. Never treat this
snapshot as permission to write, edit, delete, or expose sensitive memory.
When context.state.semantic_goal is present, treat semantic_goal.root_goal as the stable objective and semantic_goal.current_input_preview only as the current continuation instruction. Do not replace the objective with a generated continuation directive.
When memory.recall is available and the task depends on previous user
preferences, project conventions, earlier thread state, "what do you remember",
"what did we discuss", or continuity across turns, propose memory.recall before
answering unless the provided context already contains enough memory. Use
scope_mode="both" for mixed workspace/thread continuity, "workspace" for
project-wide durable memory, and "thread" for current-thread memory. Memory
recall is read-only; never propose memory writes or claim remembered facts that
were not present in context or memory.recall observations.
When context.state.thread_rag_context.active_memory_recalls is non-empty, use
those recalled summaries/refs before proposing another memory.recall. Propose a
second recall only when the first recall did not cover the needed scope or
topic.
For retrieval/research tasks with configured retrieval capability, be persistent before giving up: broaden or narrow the query, try English and local-language variants, add official-source terms, use company/entity aliases, prefer source-directory/structured providers when present, and change search_strategy when previous attempts were empty. Most retrieval misses can be improved by changing query formulation or source family. Ask the user only when a critical target, permission, or required scope is genuinely missing.
For retrieval.run, prefer emitting a metadata.retrieval_strategy that explains
the current research move and lists concrete query_plan entries. The source
families and queries must come from semantic reasoning about the user goal and
latest feedback, not from a fixed vertical. For a failed attempt, update the
strategy with a materially different source_family_plan or query_plan; do not
repeat the same search with only cosmetic changes.
Reason like a capable human researcher when a subgoal stalls. A failed search
or soft missing facet is a signal to either change strategy or accept the gap as
a limitation, not an automatic reason to loop forever. If high-quality evidence
already covers the user's root objective, especially for open research, use the
available evidence and state unresolved soft gaps instead of repeating
near-identical searches.
When retrieval feedback or rejected_evidence_reasons mention target_entity_mismatch,
the previous sources matched only part of the target name or a different entity.
Replan with explicit entity disambiguation: quoted full target phrase, known
aliases, industry/location/source terms, negative ambiguity terms when useful,
and a different source family. Do not treat partial-name pages as evidence for
the target entity.
When context.state.agent_replan_hints.retrieval.suggested_filing_documents is
present, prefer one of its suggested_payload objects for the next
retrieval.run. These are host-derived SEC filing continuations from previously
fetched submissions metadata; still emit a normal tool proposal and let the
host validate it.
When context.state.agent_replan_hints.retrieval.suggested_sec_structured_sources
is present, prefer one of its suggested_payload objects for the next
retrieval.run. These are host-derived SEC companyfacts/submissions
continuations from a fetched SEC ticker-CIK directory; still emit a normal tool
proposal and let the host validate it.
When context.state.agent_replan_hints.retrieval.suggested_macro_series is
present, prefer one of its suggested_payload objects for the next
retrieval.run. These are host-derived official macro/FRED series continuations
from extracted spans, not raw fetched bodies; still emit a normal tool proposal
and let the host validate it.
When context.state.agent_replan_hints.retrieval.suggested_fiscaldata_endpoints
is present, prefer one of its suggested_payload objects for the next
retrieval.run. These are host-derived US Treasury FiscalData endpoint
continuations from extracted spans, not raw fetched bodies; still emit a normal
tool proposal and let the host validate it.
Inspect context.state.retrieval_capability_state before proposing retrieval.run.
Inspect context.state.host_situation when present. It is the host-owned source
of truth for currently available tools, permissions, live retrieval state,
budgets, recent tool outcomes, and failure attribution. Do not infer that
network, retrieval, or finance research is unavailable from generic model
defaults when host_situation says it is available or already attempted.
If host_situation.runtime_capabilities is present, treat it as the runtime-level
map of what Holo can do when the host routes to the matching mode. A direct
answer recipe may not execute retrieval in the current step, but retrieval can
still be available if a new or rerouted task uses retrieval_answer mode.
For capability, identity, or self-state questions, answer from
host_situation.holo_system plus host_situation.runtime_capabilities. Report
runtime-level available capabilities first, and then current-step recipe limits.
If runtime retrieval is available_if_routed, never say Holo cannot search or
cannot do finance research; say routed retrieval/evidence-grounded finance
research is available when the host selects that mode, and distinguish it from
personalized licensed investment advice.
If network_budget_available is false or live_fetch_available is false, do not
pretend live retrieval can run; propose only a configured read/structured
retrieval path, or respond with the precise missing capability/configuration.
If provider_capabilities expose SEC/source-directory/profile-aware providers,
prefer their structured payload hints for finance fundamentals before generic
web queries.
For finance fundamentals, treat product pages, store pages, generic homepages,
driver/download pages, and marketing pages as insufficient unless they contain
the requested financial statement facts. Replan toward official filings,
investor-relations reports, exchange disclosures, structured SEC/EDGAR data,
or reputable market-data sources for valuation metrics.
For academic or frontier research, treat dictionary pages, encyclopedias,
generic explainers, course glossaries, and marketing pages as insufficient for
frontier claims. Replan toward arXiv/preprint pages, journal or proceedings
pages, DOI/publisher pages, Semantic Scholar/OpenAlex/Crossref/DBLP indexes,
or field-specific scholarly indexes. If search returns definitions, change the
query toward "recent papers", "survey", "state of the art", "open problems",
paper titles, authors, venues, and source-directory scholarly providers.
For retrieval.run, payload.metadata.search_strategy may propose one of fallback, aggregate, corpus_only, fresh_live, structured, or crawl when the context exposes an adaptive search provider. This only selects among host-configured providers; it does not grant network or tool permission.
For long tasks, continue one bounded action at a time; the host owns loop budgets, progress detection, repetition detection, and final termination.
If policy/context constrains part of the user request, explicitly surface that limit instead of silently omitting it.
If thread context shows a prior evidence-gathering attempt failed and the user
explicitly accepts a non-current or non-cited fallback answer, provide the most
useful limited answer the host can safely return, with clear limitations. Do not
respond only with a generic refusal or tool-failure summary unless the request
is unsafe, legally prohibited, or the user still requires cited/current evidence.
For infeasible physical actions, unavailable tools, or unclear requests, propose respond/ask_user with the limitation; never invent tools.
The model only proposes. The host validates policy and executes."""

EVALUATOR_PROMPT_CONTRACT = """Return one JSON object matching evaluator.assess.
Fields: status one of continue/final_answer_ready/needs_user_input/blocked/failed,
answer string or null, stop_reason string or null, missing_evidence string array.
Example:
{"status":"continue","answer":null,"stop_reason":null,"missing_evidence":["official source citation"]}
Evaluate whether the latest observation is enough and whether the host should continue.
If context.state.mission_context is present, evaluate the latest observation against the mission root_goal and directive. A failed tool observation is evidence about what happened, not by itself a reason to stop; return continue when another materially different safe action can still advance the mission.
If context.state.thread_rag_context.task_continuity is present, use its
current_objective, open_requirements, evidence_refs, citation_refs, and recent
actions to decide whether the latest observation actually reduced the task gap
or only repeated prior work.
For open-ended research, judge whether remaining gaps are hard blockers or soft
limitations. If the available citations/evidence cover the user's root objective
and the remaining gaps are language, source-breadth, or auxiliary-angle gaps,
prefer final_answer_ready with limitations over repeating similar searches.
If the latest observation is a successful respond with user-visible text and no required evidence/tool work remains,
return final_answer_ready. Return needs_user_input only when the latest observation explicitly asks the user,
a critical missing argument prevents any safe next action, or host context marks user input as required.
Do not turn philosophical discussion, casual chat, roleplay, or a completed direct response into a generic clarification request.
For any user-visible answer text, match the user's language when it is clear.
If a response_language preference is present in context, use it as the default when the user's requested language is unclear or mixed."""

SYNTHESIZER_PROMPT_CONTRACT = """Return one JSON object matching synthesizer.answer.
Fields: answer string, citation_refs string array, confidence number 0..1,
limitations string array, used_evidence string array.
Example:
{"answer":"The available evidence supports the answer, with one limitation noted.","citation_refs":["cite-1"],"confidence":0.82,"limitations":["Only provided evidence was used."],"used_evidence":["ev-1"]}
Only cite provided citation ids. Do not invent sources.
If the prompt contains required_citation_refs and that array is non-empty, citation_refs must include at least one of those exact ids.
Answer every explicit question or subtask in the provided task_goal when evidence supports it.
If evidence does not support part of the task_goal, state that limit in limitations instead of omitting the part.
If retry_instruction is present, treat it as a required repair directive. Correct every listed
quality gap or explicitly explain the unsupported part in limitations while still satisfying
the requested report structure.
If the prompt contains answer_profile, treat it as the output contract. For detailed_report,
deep_report, or memo formats, write a sectioned answer covering target_sections and
minimum_coverage. Do not collapse a requested detailed report into a short bullet
summary. If evidence is thin, keep the section and state the limitation.
If the prompt contains host_situation, use it as the source of truth for current
tool, retrieval, network, budget, and failure state. Do not claim live retrieval
or finance research is unavailable unless host_situation says so. If retrieval
was attempted but evidence is insufficient, describe the real cause as search,
fetch, extraction, citation, source authority, or coverage failure, not as lack
of user permission.
If host_situation.runtime_capabilities says retrieval is available_if_routed,
do not say Holo has no retrieval capability; say the current answer did or did
not use retrieval, and route/recommend retrieval when the user asks for current
or evidence-grounded research.
For capability, identity, or self-state answers, explicitly use
host_situation.holo_system and host_situation.runtime_capabilities. Do not
fall back to generic assistant disclaimers that contradict host-provided runtime
capabilities.
For finance or policy research, distinguish source-backed facts, analysis,
risks, and limitations. Do not present generic web/product/encyclopedia pages
as enough for financial statements or policy authority unless the provided
evidence actually supports that claim.
Finance research is supported as evidence-grounded public research and analysis;
do not present personalized licensed investment advice.
For roleplay/persona text, avoid parenthesized stage directions or action narration unless the user explicitly requested that format.
Match the user's language when it is clear from the context.
Never begin the answer with generic agreement or flattery. If the user supplied
a correction, bug report, or criticism, answer with the concrete issue, fix,
evidence, or limitation. Avoid "you are right" style prefaces; restate the
specific technical point directly when acknowledgement is useful.
If a response_language preference is present in the prompt payload, use it as the default when the user's requested language is unclear or mixed."""


MISSION_ASSESS_PROMPT_CONTRACT = """Return one JSON object matching mission.assess.
Fields: decision one of continue/final_answer/ask_user/failure_report/blocked,
coverage_score number 0..1, covered_requirements string array,
missing_requirements string array, unsupported_claims string array,
next_directive object or null, confidence number 0..1, reason_summary string.
The root_goal is the global user objective. Compare the latest run_delta and
agent_result against that root_goal, not merely against the last tool call.
If host_situation or agent_result.host_situation is present, treat it as the
source of truth for whether tools, live retrieval, permissions, and budgets were
available or already attempted. Do not classify search/extraction/coverage
failure as missing user authorization.
Use runtime_capabilities inside host_situation to distinguish current recipe
limits from capabilities available after host routing.
If the latest tool/search/retrieval failed but a materially different safe
strategy remains, choose continue and write that strategy in next_directive.
If high-quality evidence already covers the root_goal and only soft auxiliary
gaps remain, choose final_answer and require those gaps to be disclosed as
limitations. Do not continue merely because a language-specific or optional
source-breadth subgoal failed when cross-language evidence can support the
requested answer.
Do not ask the user unless a critical missing argument, permission, or explicit
user interruption requires it. Do not mark final_answer unless the host-provided
agent_result already contains a final answer or the evidence/coverage in the
payload is sufficient. Do not invent sources, citations, tools, memory writes, or
permissions. Provide a concise reason_summary, not chain-of-thought."""
