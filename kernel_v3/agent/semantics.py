from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from kernel_v3.agent.contracts import SemanticIntake, TaskIntent
from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import SEMANTIC_INTAKE_PROMPT_CONTRACT, SEMANTIC_INTAKE_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric


_SEGMENT_PATTERN = re.compile(
    r"(?:然后|最后|接着|并且|同时|after that|finally|then|再(?=去|把|帮|写|搜|检索|搜索|读|读取|查看|讲|扮演|作为)|[，,；;])",
    re.IGNORECASE,
)
_LEADING_SEQUENCE_PATTERN = re.compile(r"^\s*(?:先|first(?:ly)?|1[.)、]?)\s*", re.IGNORECASE)

_NOOP_PATTERN = re.compile(
    r"(?:什么都)?(?:不要|别|不用|无需)\s*(?:做|执行|操作|运行|调用|写|改)|(?:do\s+nothing|don't\s+(?:do|run|execute|write|change))",
    re.IGNORECASE,
)
_ROLE_PATTERN = re.compile(
    r"(?:扮演|饰演|充当|作为|以.+?身份|act\s+as|roleplay\s+as|pretend\s+to\s+be)\s*(?P<role>[^，,。.;；]*)",
    re.IGNORECASE,
)
_CONTROL_PATTERN = re.compile(r"(?:接管|控制|托管|登录|发送|代发|自动操作|control|take\s+over|login|send|operate)", re.IGNORECASE)
_RETRIEVAL_PATTERN = re.compile(r"(?:搜索|搜一下|检索|上网|联网查|调研|research|search|retrieve|look\s+up|browse)", re.IGNORECASE)
_WORKSPACE_READ_PATTERN = re.compile(
    r"(?:读|读取|查看|检查|打开|分析).*(?:文件|代码|目录|workspace|readme|\.py|\.md|\.json)|"
    r"(?:read|open|inspect|check).*(?:file|workspace|readme|\.py|\.md|\.json)",
    re.IGNORECASE,
)
_WORKSPACE_WRITE_PATTERN = re.compile(
    r"(?:本地|文件|workspace|报告|report).*(?:写|保存|落盘|生成|write|save)|"
    r"(?:写|保存|落盘|生成).*(?:本地|文件|报告|workspace|report)|"
    r"(?:write|save|generate).*(?:file|local|report|workspace)",
    re.IGNORECASE,
)
_JOKE_PATTERN = re.compile(r"(?:笑话|joke)", re.IGNORECASE)
_SYNTHESIS_PATTERN = re.compile(r"(?:总结|归纳|扩展|比较|分析|思路|synthesize|summari[sz]e|compare|analy[sz]e)", re.IGNORECASE)


@dataclass(frozen=True)
class CapabilityRule:
    capability: str
    aliases: tuple[str, ...]
    risk: str
    metadata: dict[str, str] = field(default_factory=dict)

    def matches(self, text: str) -> bool:
        lowered = text.lower()
        return any(alias.lower() in lowered for alias in self.aliases)


_LIVE_TRANSPORT_RULES = (
    CapabilityRule("live_transport:wechat", ("wechat", "weixin", "微信"), "external_control", {"transport": "wechat"}),
    CapabilityRule("live_transport:slack", ("slack",), "external_control", {"transport": "slack"}),
    CapabilityRule("live_transport:discord", ("discord",), "external_control", {"transport": "discord"}),
    CapabilityRule("live_transport:email", ("email", "mail", "邮箱", "邮件"), "external_control", {"transport": "email"}),
)
_SAFE_CAPABILITIES = {"retrieval.run", "workspace.search", "file.read", "workspace:read"}


def analyze_goal(goal: str) -> SemanticIntake:
    text = goal.strip()
    intents = _classify_segments(_segments(text))
    if not intents:
        intents = [_clarification_intent("")]
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
) -> SemanticIntake:
    fallback = analyze_goal(goal)
    outcome = fabric.run_json(
        task_type="semantic.intake",
        task_id=task_id,
        run_id=run_id,
        context_id=context_id,
        prompt=_semantic_prompt(goal),
        schema=SEMANTIC_INTAKE_SCHEMA,
        provider=provider,
        model=model,
        parameters={"adapter": "SemanticIntake", "contract_version": 1},
    )
    if outcome.parsed is None:
        return _with_warning(fallback, "semantic_intake_processor_failed")
    return _intake_from_model(goal, outcome.parsed, fallback=fallback)


def _semantic_prompt(goal: str) -> str:
    payload = {
        "contract": SEMANTIC_INTAKE_PROMPT_CONTRACT,
        "contract_version": 1,
        "user_goal": goal,
        "host_capability_catalog": {
            "modes": ["direct_answer", "retrieval_answer", "workspace_answer", "clarify_first"],
            "executable_tools_by_recipe": {
                "retrieval_answer": ["retrieval.run"],
                "workspace_answer": ["workspace.search", "file.read"],
                "direct_answer": [],
                "clarify_first": [],
            },
            "blocked_or_not_default": [
                "workspace:write",
                "shell:exec",
                "network.fetch",
                "live_transport:*",
                "durable_memory:write",
            ],
        },
        "host_rules": [
            "Split compound requests into ordered intents.",
            "Classify role/persona requests as roleplay scoped to the current thread.",
            "Classify transport/account/client control as transport_control and blocked.",
            "Classify local writing/report generation as workspace_write and needs_permission unless an explicit writable recipe is available.",
            "If a compound task includes blocked capabilities, ask for confirmation or scope reduction before execution.",
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


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
    if primary == "transport_control":
        requires_clarification = False
    elif compound or blocked:
        requires_clarification = True
    suggested_mode = _normalize_mode(str(data.get("suggested_mode") or ""), primary=primary, requires_clarification=requires_clarification)
    model_warnings = [str(item) for item in data.get("warnings", [])] if isinstance(data.get("warnings"), list) else []
    warnings = _ordered_unique([*model_warnings, *_warnings(intents, compound=compound)])
    response_hint = _string_or_none(data.get("response_hint")) or _response_hint(primary, intents=intents, blocked=blocked)
    if primary in {"transport_control", "noop", "roleplay"}:
        response_hint = _response_hint(primary, intents=intents, blocked=blocked) or response_hint
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


def _segments(text: str) -> list[str]:
    normalized = _LEADING_SEQUENCE_PATTERN.sub("", text.strip())
    if not normalized:
        return []
    return [part.strip() for part in _SEGMENT_PATTERN.split(normalized) if part.strip()]


def _classify_segments(segments: list[str]) -> list[TaskIntent]:
    intents: list[TaskIntent] = []
    pending_detail: list[str] = []
    for segment in segments:
        intent = _classify_segment(segment, len(intents) + 1)
        if intent.kind == "detail":
            if intents:
                pending_detail.append(segment)
                continue
            intent = _intent(1, "direct_answer", segment, risk="none", status="ready")
        if pending_detail and intents:
            intents[-1] = _append_detail(intents[-1], pending_detail)
            pending_detail = []
        if intent.kind != "detail":
            intents.append(intent)
    if pending_detail and intents:
        intents[-1] = _append_detail(intents[-1], pending_detail)
    return intents


def _model_intents(value: object) -> list[TaskIntent]:
    if not isinstance(value, list):
        return []
    intents: list[TaskIntent] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue
        kind = _normalize_intent_kind(str(item.get("kind") or "direct_answer"))
        text = str(item.get("text") or "")
        capabilities = _string_list(item.get("required_capabilities"))
        risk = str(item.get("risk") or _risk_for_kind(kind))
        status = str(item.get("status") or _status_for_kind(kind))
        metadata = item.get("metadata")
        intents.append(
            _intent(
                index,
                kind,
                text,
                capabilities=capabilities,
                risk=risk,
                status=status,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
        )
    return intents


def _apply_hard_capability_overrides(goal: str, intents: list[TaskIntent]) -> list[TaskIntent]:
    transport = _transport_control_rule(goal)
    if transport is None:
        return intents
    if any(intent.kind == "transport_control" for intent in intents):
        return [
            _merge_capability(intent, transport.capability, risk=transport.risk, status="blocked", metadata=transport.metadata)
            if intent.kind == "transport_control"
            else intent
            for intent in intents
        ]
    return [
        _intent(
            1,
            "transport_control",
            goal,
            capabilities=[transport.capability],
            risk=transport.risk,
            status="blocked",
            metadata=transport.metadata,
        ),
        *_renumber(intents, start=2),
    ]


def _merge_capability(
    intent: TaskIntent,
    capability: str,
    *,
    risk: str,
    status: str,
    metadata: JsonObject,
) -> TaskIntent:
    merged_metadata = {**dict(intent.metadata), **metadata}
    return TaskIntent(
        intent_id=intent.intent_id,
        kind=intent.kind,
        text=intent.text,
        sequence_index=intent.sequence_index,
        required_capabilities=_ordered_unique([*intent.required_capabilities, capability]),
        risk=risk,
        status=status,
        metadata=merged_metadata,
    )


def _renumber(intents: list[TaskIntent], *, start: int) -> list[TaskIntent]:
    result: list[TaskIntent] = []
    for offset, intent in enumerate(intents, start=start):
        result.append(
            TaskIntent(
                intent_id=f"intent-{offset}-{intent.kind}",
                kind=intent.kind,
                text=intent.text,
                sequence_index=offset,
                required_capabilities=list(intent.required_capabilities),
                risk=intent.risk,
                status=intent.status,
                metadata=dict(intent.metadata),
            )
        )
    return result


def _classify_segment(segment: str, index: int) -> TaskIntent:
    stripped = segment.strip()
    if not stripped or stripped in {"?", "？", ".", "。"}:
        return _clarification_intent(stripped, index=index)
    if _NOOP_PATTERN.search(stripped):
        return _intent(index, "noop", stripped, risk="none", status="ready")
    transport = _transport_control_rule(stripped)
    if transport is not None:
        return _intent(
            index,
            "transport_control",
            stripped,
            capabilities=[transport.capability],
            risk=transport.risk,
            status="blocked",
            metadata=transport.metadata,
        )
    role = _role_request(stripped)
    if role is not None:
        return _intent(index, "roleplay", stripped, risk="none", status="ready", metadata={"role": role, "scope": "current_thread"})
    if _RETRIEVAL_PATTERN.search(stripped):
        return _intent(
            index,
            "retrieval_research",
            stripped,
            capabilities=["retrieval.run"],
            risk="read",
            status="ready",
            metadata={"live_network_requested": _requests_live_network(stripped)},
        )
    if _WORKSPACE_WRITE_PATTERN.search(stripped):
        return _intent(index, "workspace_write", stripped, capabilities=["workspace:write"], risk="write", status="needs_permission")
    if _WORKSPACE_READ_PATTERN.search(stripped):
        return _intent(index, "workspace_read", stripped, capabilities=["workspace.search", "file.read"], risk="read", status="ready")
    if _SYNTHESIS_PATTERN.search(stripped):
        return _intent(index, "synthesis", stripped, risk="none", status="ready")
    if _JOKE_PATTERN.search(stripped):
        return _intent(index, "direct_answer", stripped, risk="none", status="ready", metadata={"style": "joke"})
    if _looks_like_detail(stripped):
        return _intent(index, "detail", stripped, risk="none", status="ready")
    return _intent(index, "direct_answer", stripped, risk="none", status="ready")


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


def _append_detail(intent: TaskIntent, details: list[str]) -> TaskIntent:
    text = "，".join([intent.text, *details])
    metadata = dict(intent.metadata)
    metadata["details"] = list(details)
    return TaskIntent(
        intent_id=intent.intent_id,
        kind=intent.kind,
        text=text,
        sequence_index=intent.sequence_index,
        required_capabilities=list(intent.required_capabilities),
        risk=intent.risk,
        status=intent.status,
        metadata=metadata,
    )


def _transport_control_rule(text: str) -> CapabilityRule | None:
    if _CONTROL_PATTERN.search(text) is None:
        return None
    for rule in _LIVE_TRANSPORT_RULES:
        if rule.matches(text):
            return rule
    if re.search(r"(?:transport|channel|bot|客户端|账号|程序|应用|app)", text, re.IGNORECASE):
        return CapabilityRule("live_transport:unknown", ("",), "external_control", {"transport": "unknown"})
    return None


def _role_request(text: str) -> str | None:
    match = _ROLE_PATTERN.search(text)
    if match is None:
        return None
    role = _clean_role(match.group("role") or "")
    return role or "specified_role"


def _clean_role(role: str) -> str:
    cleaned = role.strip(" ：:。.")
    for marker in ("来", "去", "然后", "并", "给我", "帮我", " and ", " then ", " to "):
        index = cleaned.lower().find(marker)
        if index > 0:
            cleaned = cleaned[:index]
            break
    return cleaned.strip(" ：:。.")


def _requests_live_network(text: str) -> bool:
    return bool(re.search(r"(?:上网|联网|live|web|internet|browse)", text, re.IGNORECASE))


def _looks_like_detail(text: str) -> bool:
    if len(text) <= 24 and not re.search(r"(?:去|请|帮|把|执行|调用|run|do|write|read|search)", text, re.IGNORECASE):
        return True
    return False


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
    if capability in _SAFE_CAPABILITIES:
        return False
    if capability.startswith("live_transport:"):
        return True
    if capability in {"workspace:write", "shell:exec", "network.fetch", "durable_memory:write"}:
        return True
    return True


def _warnings(intents: list[TaskIntent], *, compound: bool) -> list[str]:
    warnings: list[str] = []
    if compound:
        warnings.append("compound_task_requires_explicit_plan_confirmation")
    if any(intent.metadata.get("live_network_requested") is True for intent in intents):
        warnings.append("live_network_not_enabled_by_default")
    if any(intent.kind == "roleplay" for intent in intents):
        warnings.append("roleplay_scope_is_current_thread_only")
    if any(intent.kind == "transport_control" for intent in intents):
        warnings.append("live_transports_are_not_kernel_v3_decision_makers")
    return _ordered_unique(warnings)


def _primary_intent(intents: list[TaskIntent]) -> str:
    priority = [
        "transport_control",
        "noop",
        "retrieval_research",
        "workspace_write",
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
    if any(intent.kind == "transport_control" for intent in intents):
        return False
    if compound:
        return True
    if any(intent.kind == "clarification" for intent in intents):
        return True
    return bool(blocked_capabilities)


def _suggested_mode(primary: str, *, requires_clarification: bool) -> str:
    if requires_clarification:
        return "clarify_first"
    if primary == "retrieval_research":
        return "retrieval_answer"
    if primary == "workspace_read":
        return "workspace_answer"
    return "direct_answer"


def _normalize_mode(value: str, *, primary: str, requires_clarification: bool) -> str:
    if requires_clarification:
        return "clarify_first"
    if value in {"direct_answer", "retrieval_answer", "workspace_answer", "clarify_first"}:
        return value
    return _suggested_mode(primary, requires_clarification=requires_clarification)


def _normalize_primary(value: str, intents: list[TaskIntent]) -> str:
    kind = _normalize_intent_kind(value)
    if kind != "direct_answer" or value == "direct_answer":
        return kind
    return _primary_intent(intents)


def _normalize_intent_kind(value: str) -> str:
    allowed = {
        "transport_control",
        "noop",
        "retrieval_research",
        "workspace_write",
        "workspace_read",
        "synthesis",
        "roleplay",
        "clarification",
        "direct_answer",
    }
    return value if value in allowed else "direct_answer"


def _risk_for_kind(kind: str) -> str:
    if kind in {"transport_control"}:
        return "external_control"
    if kind == "workspace_write":
        return "write"
    if kind in {"retrieval_research", "workspace_read"}:
        return "read"
    return "none"


def _status_for_kind(kind: str) -> str:
    if kind == "transport_control":
        return "blocked"
    if kind == "workspace_write":
        return "needs_permission"
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
