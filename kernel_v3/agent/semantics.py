from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Pattern

from kernel_v3.capabilities import SAFE_SEMANTIC_CAPABILITIES, semantic_capability_catalog
from kernel_v3.agent.contracts import SemanticIntake, TaskIntent
from kernel_v3.context.redaction import Redactor
from kernel_v3.contracts import JsonObject
from kernel_v3.interaction import interaction_preferences
from kernel_v3.processors.contracts import SEMANTIC_INTAKE_PROMPT_CONTRACT, SEMANTIC_INTAKE_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric


_PRIVATE_REASONING_PATTERN = re.compile(
    r"(?:思考过程|思维链|推理过程|内部推理|inner\s+(?:thought|reasoning)|chain[-\s]?of[-\s]?thought|show\s+.*reasoning|show\s+.*thought)",
    re.IGNORECASE,
)
_SHELL_EXEC_PATTERN = re.compile(
    r"(?:shell|bash|powershell|cmd\.exe|终端|命令行|执行命令|运行命令|run\s+(?:a\s+)?(?:shell\s+)?command|rm\s+-rf|sudo\b|chmod\b|curl\s+|wget\s+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HostBoundaryRule:
    intent_kind: str
    pattern: Pattern[str]
    risk: str
    status: str
    required_capabilities: tuple[str, ...] = ()
    warning: str | None = None
    response_hint: str | None = None

    def matches(self, text: str) -> bool:
        return self.pattern.search(text) is not None


_HOST_BOUNDARY_RULES = (
    HostBoundaryRule(
        intent_kind="private_reasoning",
        pattern=_PRIVATE_REASONING_PATTERN,
        risk="private_reasoning",
        status="blocked",
        warning="private_reasoning_is_not_exposed",
        response_hint="我不能展示隐藏的逐步思考过程或私有推理链。可以提供简要理由、结论依据、可审计 trace、证据和下一步计划。",
    ),
    HostBoundaryRule(
        intent_kind="shell_execution",
        pattern=_SHELL_EXEC_PATTERN,
        risk="shell",
        status="blocked",
        required_capabilities=("shell:exec",),
        warning="shell_execution_requires_explicit_future_capability",
        response_hint="当前 kernel_v3 不直接执行 shell/终端命令。需要这类能力时，应在后续工具 phase 中通过 PolicyGate、审批、artifact 记录和回滚策略显式开放。",
    ),
)


_INTENT_KIND_ALIASES = {
    "time_query": "system_time",
    "system_time_query": "system_time",
    "current_time_query": "system_time",
    "current_time": "system_time",
    "current_date": "system_time",
    "date_query": "system_time",
    "system_date": "system_time",
    "clock_query": "system_time",
    "system_clock": "system_time",
    "now_query": "system_time",
    "calendar_reminder": "calendar_or_reminder",
    "reminder": "calendar_or_reminder",
    "alarm": "calendar_or_reminder",
    "scheduled_reminder": "calendar_or_reminder",
}


def analyze_goal(goal: str) -> SemanticIntake:
    """Boundary-only offline intake.

    The fake path intentionally does not keyword-route open-ended user semantics
    such as roleplay, retrieval, workspace actions, transport control, or memory
    writes. Model-backed semantic intake must propose those structures; the host
    then validates capabilities and policy.
    """
    text = goal.strip()
    intents = _classify_goal(text)
    compound = _is_compound(text, intents)
    blocked = _blocked_capabilities(intents)
    warnings = _warnings(intents, compound=compound)
    primary = _primary_intent(intents)
    requires_clarification = _requires_clarification(
        goal=text,
        intents=intents,
        compound=compound,
        blocked_capabilities=blocked,
    )
    response_hint = _response_hint(primary, intents=intents, blocked=blocked)
    clarification = _clarification_question(intents, blocked=blocked, compound=compound) if requires_clarification else None
    suggested_mode = _suggested_mode(primary, requires_clarification=requires_clarification)
    return SemanticIntake(
        intake_id="semantic-intake-1",
        goal=goal,
        primary_intent=primary,
        suggested_mode=suggested_mode,
        compound=compound,
        requires_clarification=requires_clarification,
        intents=[intent.to_dict() for intent in intents],
        blocked_capabilities=blocked,
        warnings=warnings,
        response_hint=response_hint,
        clarification_question=clarification,
    )


def analyze_goal_with_processor(
    goal: str,
    *,
    fabric: ProcessorFabric,
    task_id: str | None,
    run_id: str,
    context_id: str,
    provider: str | None = None,
    model: str | None = None,
    response_language: str | None = None,
    runtime_context: JsonObject | None = None,
) -> SemanticIntake:
    outcome = fabric.run_json(
        task_type="semantic.intake",
        task_id=task_id,
        run_id=run_id,
        context_id=context_id,
        prompt=_semantic_prompt(goal, response_language=response_language, runtime_context=runtime_context),
        schema=SEMANTIC_INTAKE_SCHEMA,
        provider=provider,
        model=model,
        parameters={
            "adapter": "SemanticIntake",
            "contract_version": 1,
            **_processor_budget_parameters(runtime_context),
        },
    )
    if outcome.parsed is None:
        return _processor_failed_intake(goal, response_language=response_language)
    return _intake_from_model(goal, outcome.parsed, fallback=analyze_goal(goal))


def _semantic_prompt(
    goal: str,
    *,
    response_language: str | None = None,
    runtime_context: JsonObject | None = None,
) -> str:
    preferences = interaction_preferences(response_language=response_language)
    payload = {
        "contract": SEMANTIC_INTAKE_PROMPT_CONTRACT,
        "contract_version": 1,
        "user_goal": goal,
        "runtime_context": _compact_runtime_context(runtime_context),
        "interaction_preferences": preferences,
        "response_language": preferences["response_language"],
        "host_capability_catalog": semantic_capability_catalog(),
        "host_rules": [
            "Split compound requests into ordered intents.",
            "Do not set requires_clarification merely because a task is compound.",
            "For safe read-only compound tasks with clear tool arguments, set requires_clarification=false and keep the executable mode.",
            "Ask the user only when critical scope/tool arguments are missing, a capability is blocked, or the user explicitly requests interruption/confirmation.",
            "Use response_language as the default language for user-visible clarification text when the user's requested language is unclear or mixed.",
            "Use broad semantic judgment instead of sample-specific phrase matching.",
            (
                "Use open semantic labels when useful; required_capabilities "
                "are the executable tool contract the host validates."
            ),
            (
                "For API documentation, developer docs, SDK docs, endpoint, "
                "authentication, parameter, schema, rate-limit, or pricing "
                "research, use technical.api_documentation or "
                "technical.documentation_research so the host can select the "
                "technical_documentation research profile."
            ),
            (
                "For scholarly, academic, mathematical, scientific, frontier, "
                "paper, preprint, survey, literature-review, or open-problem "
                "research, use academic.research, academic.frontier_research, "
                "academic.literature_review, or academic.paper_search so the "
                "host can select the academic_research profile. Do not reduce "
                "academic frontier research to dictionary lookup."
            ),
            (
                "Place structured tool arguments in intent.metadata.capability_args "
                "keyed by capability name."
            ),
            (
                "For finance-capability tasks with named entities, tickers, periods, filings, "
                "deals, metrics, or public data needs, prefer retrieval_answer with "
                "retrieval.run/finance.* capabilities. Do not require clarification merely "
                "because source URLs, CIKs, or formula inputs must be retrieved."
            ),
            (
                "When useful, place broad state hints in intent.metadata.domain, "
                "activity, resource, and execution_surface; these are state "
                "coordinates, not permissions."
            ),
            "Classify role/persona requests as roleplay scoped to the current thread.",
            "Classify transport/account/client control as transport_control and blocked.",
            "Classify unavailable tool, device, account, or execution requests as blocked capabilities instead of pretending they ran.",
            "Classify requests for hidden/private reasoning as private_reasoning and do not expose chain-of-thought.",
            "Classify local writing/report generation as workspace_write. Use status=ready when path and text can be proposed safely; use needs_user_input only when critical write target or content is missing.",
            "If a compound task includes blocked capabilities, ask for confirmation or scope reduction before execution.",
            (
                "When runtime_context.thread_working_context.route is answer_pending_question, "
                "interpret user_goal as an answer to the pending question and original task, "
                "not as a standalone vague request."
            ),
            (
                "Use runtime_context.thread_working_context.original_task, pending_question, "
                "recent_turns, and recent_task_trace to preserve thread-local working memory."
            ),
            (
                "If the user accepts a fallback or limitation proposed by the previous assistant turn, "
                "continue the original task under that limitation instead of asking a new generic clarification."
            ),
            "If unsure, preserve uncertainty in clarification_question instead of forcing a keyword-style class.",
        ],
    }
    redacted, _markers = Redactor().redact(payload)
    safe = redacted if isinstance(redacted, dict) else {"user_goal": "[REDACTED:SECRET]"}
    return json.dumps(safe, ensure_ascii=False, sort_keys=True)


def _compact_runtime_context(value: JsonObject | None) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    allowed: JsonObject = {}
    for key in (
        "thread_working_context",
        "task_execution_step",
        "interaction_preferences",
        "agent_loop",
        "processor_budget",
        "host_situation",
        "answer_profile",
        "research_mission",
    ):
        item = value.get(key)
        if isinstance(item, dict):
            allowed[key] = _compact_prompt_value(item)
    return allowed


def _processor_budget_parameters(runtime_context: JsonObject | None) -> JsonObject:
    if not isinstance(runtime_context, dict):
        return {}
    budget = runtime_context.get("processor_budget")
    if not isinstance(budget, dict):
        return {}
    return {"processor_budget": dict(budget)}


def _compact_prompt_value(value):
    if isinstance(value, str):
        return _compact_text(value, limit=640)
    if isinstance(value, list):
        return [_compact_prompt_value(item) for item in value[:12]]
    if isinstance(value, dict):
        return {str(key): _compact_prompt_value(item) for key, item in list(value.items())[:32]}
    return value


def _compact_text(text: str, *, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)] + "..."


def _intake_from_model(goal: str, data: JsonObject, *, fallback: SemanticIntake) -> SemanticIntake:
    intents = _model_intents(data.get("intents"))
    if not intents:
        intents = [TaskIntent.from_dict(item) for item in fallback.intents]
    intents = _apply_hard_capability_overrides(goal, intents)
    compound = _bool(data.get("compound")) or len(intents) > 1
    model_blocked = [str(item) for item in data.get("blocked_capabilities", [])] if isinstance(data.get("blocked_capabilities"), list) else []
    blocked = _ordered_unique([*model_blocked, *_blocked_capabilities(intents)])
    primary = _normalize_primary(str(data.get("primary_intent") or ""), intents)
    requires_clarification = _bool(data.get("requires_clarification"))
    if primary in {"transport_control", *_host_boundary_kinds()}:
        requires_clarification = False
    elif blocked:
        requires_clarification = True
    elif _has_non_ready_intent(intents):
        requires_clarification = True
    suggested_mode = _normalize_mode(
        str(data.get("suggested_mode") or ""),
        primary=primary,
        requires_clarification=requires_clarification,
        intents=intents,
    )
    model_warnings = [str(item) for item in data.get("warnings", [])] if isinstance(data.get("warnings"), list) else []
    warnings = _ordered_unique([*model_warnings, *_warnings(intents, compound=compound)])
    response_hint = _response_hint(primary, intents=intents, blocked=blocked)
    clarification = _string_or_none(data.get("clarification_question"))
    if requires_clarification and not clarification:
        clarification = _clarification_question(intents, blocked=blocked, compound=compound)
    return SemanticIntake(
        intake_id="semantic-intake-1",
        goal=goal,
        primary_intent=primary,
        suggested_mode=suggested_mode,
        compound=compound,
        requires_clarification=requires_clarification,
        intents=[intent.to_dict() for intent in intents],
        blocked_capabilities=blocked,
        warnings=warnings,
        response_hint=response_hint,
        clarification_question=clarification,
    )


def _classify_goal(text: str) -> list[TaskIntent]:
    if not text:
        return [_clarification_intent("")]
    intents: list[TaskIntent] = []
    boundary = _first_host_boundary(text)
    if boundary is not None:
        intents.append(
            _intent(
                len(intents) + 1,
                boundary.intent_kind,
                text,
                capabilities=list(boundary.required_capabilities),
                risk=boundary.risk,
                status=boundary.status,
            )
        )
    return intents or [_intent(1, "direct_answer", text, risk="none", status="ready")]


def _model_intents(value: object) -> list[TaskIntent]:
    if not isinstance(value, list):
        return []
    intents: list[TaskIntent] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        raw_kind = str(item.get("kind") or item.get("semantic_label") or "direct_answer")
        kind = _normalize_intent_kind(raw_kind)
        text = str(item.get("text") or "")
        capabilities = _string_list(item.get("required_capabilities"))
        if kind == "memory_write":
            capabilities = _ordered_unique([*capabilities, "durable_memory:write"])
        capabilities = _validated_capabilities_for_intent(kind, capabilities)
        risk = str(item.get("risk") or _risk_for_kind(kind))
        status = str(item.get("status") or _status_for_kind(kind))
        metadata = item.get("metadata")
        normalized_metadata = metadata if isinstance(metadata, dict) else {}
        normalized_metadata = dict(normalized_metadata)
        normalized_metadata.setdefault("semantic_label", raw_kind.strip() or kind)
        normalized_metadata.setdefault("host_semantic_label", kind)
        intents.append(
            _intent(
                index,
                kind,
                text,
                capabilities=capabilities,
                risk=risk,
                status=status,
                metadata=normalized_metadata,
            )
        )
    return intents


def _validated_capabilities_for_intent(kind: str, capabilities: list[str]) -> list[str]:
    normalized = _normalize_intent_kind(kind)
    return [
        capability
        for capability in capabilities
        if capability != "system.time" or normalized == "system_time"
    ]


def _apply_hard_capability_overrides(goal: str, intents: list[TaskIntent]) -> list[TaskIntent]:
    result = intents
    for rule in _matching_host_boundaries(goal):
        result = _ensure_boundary_intent(goal, result, rule)
    return result


def _ensure_boundary_intent(goal: str, intents: list[TaskIntent], rule: HostBoundaryRule) -> list[TaskIntent]:
    if any(intent.kind == rule.intent_kind for intent in intents):
        return intents
    return [
        *intents,
        _intent(
            len(intents) + 1,
            rule.intent_kind,
            goal,
            capabilities=list(rule.required_capabilities),
            risk=rule.risk,
            status=rule.status,
        ),
    ]


def _matching_host_boundaries(text: str) -> list[HostBoundaryRule]:
    return [rule for rule in _HOST_BOUNDARY_RULES if rule.matches(text)]


def _host_boundary_kinds() -> tuple[str, ...]:
    return tuple(rule.intent_kind for rule in _HOST_BOUNDARY_RULES)


def _host_boundary_for_kind(kind: str) -> HostBoundaryRule | None:
    for rule in _HOST_BOUNDARY_RULES:
        if rule.intent_kind == kind:
            return rule
    return None


def _intent(
    index: int,
    kind: str,
    text: str,
    *,
    capabilities: list[str] | None = None,
    risk: str,
    status: str,
    metadata: dict[str, object] | None = None,
) -> TaskIntent:
    return TaskIntent(
        intent_id=f"intent-{index}-{kind}",
        kind=kind,
        text=text,
        sequence_index=index,
        required_capabilities=list(capabilities or []),
        risk=risk,
        status=status,
        metadata=dict(metadata or {}),
    )


def _clarification_intent(text: str, *, index: int = 1) -> TaskIntent:
    return _intent(index, "clarification", text, risk="none", status="needs_user_input")


def _first_host_boundary(text: str) -> HostBoundaryRule | None:
    for rule in _HOST_BOUNDARY_RULES:
        if rule.matches(text):
            return rule
    return None


def _is_compound(text: str, intents: list[TaskIntent]) -> bool:
    return len(intents) > 1


def _blocked_capabilities(intents: list[TaskIntent]) -> list[str]:
    return _ordered_unique(
        [
            capability
            for intent in intents
            for capability in intent.required_capabilities
            if _is_blocked_capability(capability)
        ]
    )


def _is_blocked_capability(capability: str) -> bool:
    if not capability:
        return False
    if capability in SAFE_SEMANTIC_CAPABILITIES:
        return False
    if capability.startswith("live_transport:"):
        return True
    if capability in {"workspace:write", "shell:exec", "network.fetch", "durable_memory:write"}:
        return True
    return True


def _warnings(intents: list[TaskIntent], *, compound: bool) -> list[str]:
    warnings: list[str] = []
    if any(intent.metadata.get("live_network_requested") is True for intent in intents):
        warnings.append("live_network_not_enabled_by_default")
    if any(intent.kind == "roleplay" for intent in intents):
        warnings.append("roleplay_scope_is_current_thread_only")
    if any(intent.kind == "transport_control" for intent in intents):
        warnings.append("live_transports_are_not_kernel_v3_decision_makers")
    for intent in intents:
        boundary = _host_boundary_for_kind(intent.kind)
        if boundary is not None and boundary.warning:
            warnings.append(boundary.warning)
    return _ordered_unique(warnings)


def _primary_intent(intents: list[TaskIntent]) -> str:
    priority = [
        "transport_control",
        *_host_boundary_kinds(),
        "noop",
        "memory_write",
        "retrieval_research",
        "workspace_write",
        "system_time",
        "workspace_read",
        "synthesis",
        "roleplay",
        "clarification",
        "direct_answer",
    ]
    kinds = {intent.kind for intent in intents}
    for kind in priority:
        if kind in kinds:
            return kind
    return intents[0].kind if intents else "clarification"


def _requires_clarification(
    *,
    goal: str,
    intents: list[TaskIntent],
    compound: bool,
    blocked_capabilities: list[str],
) -> bool:
    if not goal.strip() or goal.strip() in {"?", "？", ".", "。"}:
        return True
    if any(intent.kind == "transport_control" or intent.kind in _host_boundary_kinds() for intent in intents):
        return False
    if any(intent.kind == "clarification" for intent in intents):
        return True
    if _has_non_ready_intent(intents):
        return True
    return bool(blocked_capabilities)


def _suggested_mode(primary: str, *, requires_clarification: bool) -> str:
    if requires_clarification:
        return "clarify_first"
    if primary == "retrieval_research":
        return "retrieval_answer"
    if primary == "workspace_read":
        return "workspace_answer"
    if primary == "workspace_write":
        return "workspace_write"
    if primary == "system_time":
        return "system_answer"
    if _semantic_mode_primary(primary):
        return "semantic_answer"
    return "direct_answer"


def _normalize_mode(
    value: str,
    *,
    primary: str,
    requires_clarification: bool,
    intents: list[TaskIntent] | None = None,
) -> str:
    if requires_clarification:
        return "clarify_first"
    if _requires_system_tool(intents or []):
        return "system_answer"
    if value == "system_answer" and primary != "system_time" and not _requires_system_tool(intents or []):
        return "semantic_answer"
    if value in {
        "direct_answer",
        "semantic_answer",
        "retrieval_answer",
        "workspace_answer",
        "workspace_write",
        "system_answer",
        "clarify_first",
    }:
        return value
    return _suggested_mode(primary, requires_clarification=requires_clarification)


def _requires_system_tool(intents: list[TaskIntent]) -> bool:
    return any("system.time" in intent.required_capabilities for intent in intents)


def _semantic_mode_primary(primary: str) -> bool:
    return primary not in {
        "direct_answer",
        "clarification",
        "retrieval_research",
        "workspace_read",
        "workspace_write",
        "system_time",
        "transport_control",
        *_host_boundary_kinds(),
    }


def _has_non_ready_intent(intents: list[TaskIntent]) -> bool:
    return any(intent.status in {"needs_user_input", "needs_permission", "needs_review", "blocked", "invalid"} for intent in intents)


def _processor_failed_intake(goal: str, *, response_language: str | None = None) -> SemanticIntake:
    question = (
        "The semantic processor did not return an executable structured plan. Please retry or narrow the task."
        if str(response_language or "").lower().startswith("en")
        else "语义处理器没有返回可执行的结构化计划。请重试，或缩小任务范围。"
    )
    return SemanticIntake(
        intake_id="semantic-intake-1",
        goal=goal,
        primary_intent="processor_contract_failed",
        suggested_mode="clarify_first",
        compound=False,
        requires_clarification=True,
        intents=[
            _intent(
                1,
                "processor_contract_failed",
                goal,
                risk="processor_contract",
                status="needs_user_input",
            ).to_dict()
        ],
        blocked_capabilities=[],
        warnings=["semantic_intake_processor_failed"],
        response_hint=None,
        clarification_question=question,
    )


def _normalize_primary(value: str, intents: list[TaskIntent]) -> str:
    kind = _normalize_intent_kind(value)
    if kind == "direct_answer" and any(intent.kind != "direct_answer" for intent in intents):
        return _primary_intent(intents)
    if kind != "direct_answer" or value.strip() == "direct_answer":
        return kind
    return _primary_intent(intents)


def _normalize_intent_kind(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return "direct_answer"
    safe = "".join(
        ch if ch.isalnum() or ch in {"_", "-", ".", ":"} else "_"
        for ch in cleaned
    ).strip("_").lower()
    if safe in _INTENT_KIND_ALIASES:
        return _INTENT_KIND_ALIASES[safe]
    return safe or "direct_answer"


def _risk_for_kind(kind: str) -> str:
    if kind == "transport_control":
        return "external_control"
    boundary = _host_boundary_for_kind(kind)
    if boundary is not None:
        return boundary.risk
    if kind in {"workspace_write", "memory_write"}:
        return "write"
    if kind in {"retrieval_research", "workspace_read"}:
        return "read"
    return "none"


def _status_for_kind(kind: str) -> str:
    if kind == "transport_control" or kind in _host_boundary_kinds():
        return "blocked"
    if kind == "memory_write":
        return "needs_review"
    if kind == "clarification":
        return "needs_user_input"
    return "ready"


def _response_hint(primary: str, *, intents: list[TaskIntent], blocked: list[str]) -> str | None:
    if primary == "noop":
        return "好的，我不会执行任何工具、写入或外部操作。"
    if primary == "roleplay":
        role = _first_metadata_value(intents, "role") or "指定角色"
        return f"可以。我可以在当前对话中按 {role} 的表达风格回应，但这不会改变系统权限、工具边界或长期记忆。"
    if primary == "transport_control":
        transport = _first_metadata_value(intents, "transport") or "live transport"
        return f"当前 kernel_v3 不接管 {transport} 或其他 live transport。transports 不是决策层；如需后续接入，应作为独立 transport phase，并继续由宿主校验权限。"
    boundary = _host_boundary_for_kind(primary)
    if boundary is not None and boundary.response_hint:
        return boundary.response_hint
    if primary == "memory_write":
        return "可以生成 durable memory 提案，但不会自动写入长期记忆；需要宿主规则和用户审批后才会提交。"
    if blocked:
        return "当前请求需要未开放的能力：" + ", ".join(blocked)
    return None


def _with_warning(intake: SemanticIntake, warning: str) -> SemanticIntake:
    return SemanticIntake(
        intake_id=intake.intake_id,
        goal=intake.goal,
        primary_intent=intake.primary_intent,
        suggested_mode=intake.suggested_mode,
        compound=intake.compound,
        requires_clarification=intake.requires_clarification,
        intents=list(intake.intents),
        blocked_capabilities=list(intake.blocked_capabilities),
        warnings=_ordered_unique([*intake.warnings, warning]),
        response_hint=intake.response_hint,
        clarification_question=intake.clarification_question,
    )


def _clarification_question(intents: list[TaskIntent], *, blocked: list[str], compound: bool) -> str:
    if compound:
        pieces = [f"{intent.sequence_index}. {intent.kind}: {intent.text}" for intent in intents]
        capability_text = f" 未开放能力：{', '.join(blocked)}。" if blocked else ""
        return "检测到复合任务，请确认是否拆成以下步骤逐步执行：" + "；".join(pieces) + capability_text
    if blocked:
        return "这个请求需要未开放能力：" + ", ".join(blocked) + "。请确认是否改为只读规划或提供允许的目标。"
    return "请明确目标、文件名或需要检索的问题。"


def _first_metadata_value(intents: list[TaskIntent], key: str) -> str | None:
    for intent in intents:
        value = intent.metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _bool(value: object) -> bool:
    return value if isinstance(value, bool) else False


def _string_or_none(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, str)]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
