from __future__ import annotations

import re

from kernel_v3.agent.contracts import SemanticIntake, TaskIntent


_COMPOUND_MARKERS = (
    "然后",
    "再",
    "最后",
    "接着",
    "并且",
    "同时",
    "先",
    "then",
    "after that",
    "finally",
)
_SEGMENT_PATTERN = re.compile(r"(?:然后|最后|接着|并且|同时|after that|finally|then|[，,；;])", re.IGNORECASE)

_RETRIEVAL_MARKERS = ("搜索", "搜", "检索", "上网", "调研", "research", "search", "retrieve", "web", "internet")
_WORKSPACE_READ_MARKERS = ("读", "查看", "检查", "文件", "代码", ".py", ".md", ".json", "read", "file", "workspace")
_WORKSPACE_WRITE_MARKERS = ("写", "保存", "落盘", "本地写", "报告", "write", "save", "report")
_ROLEPLAY_MARKERS = ("扮演", "角色", "jarvis", "贾维斯", "roleplay", "persona")
_TRANSPORT_MARKERS = ("wechat", "微信")
_CONTROL_MARKERS = ("接管", "控制", "登录", "发送", "托管", "control", "take over", "login", "send")
_NOOP_MARKERS = ("什么都不要做", "不要做", "别做", "do nothing", "nothing")
_JOKE_MARKERS = ("笑话", "joke")
_LIVE_NETWORK_MARKERS = ("上网", "web", "internet", "联网", "live")


def analyze_goal(goal: str) -> SemanticIntake:
    text = goal.strip()
    segments = _segments(text)
    intents = [_classify_segment(segment, index) for index, segment in enumerate(segments, start=1)]
    if not intents:
        intents = [
            TaskIntent(
                intent_id="intent-1-clarify",
                kind="clarification",
                text=text,
                sequence_index=1,
                required_capabilities=[],
                risk="none",
                status="needs_user_input",
                metadata={},
            )
        ]
    compound = _is_compound(text, intents)
    blocked = _blocked_capabilities(intents)
    warnings = _warnings(text, intents, compound=compound)
    primary = _primary_intent(intents)
    requires_clarification = _requires_clarification(
        goal=text,
        intents=intents,
        compound=compound,
        blocked_capabilities=blocked,
    )
    response_hint = _response_hint(text, primary, blocked=blocked, compound=compound)
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


def _segments(text: str) -> list[str]:
    normalized = text.strip()
    if not normalized:
        return []
    normalized = re.sub(r"^\s*先\s*", "", normalized)
    parts = [part.strip() for part in _SEGMENT_PATTERN.split(normalized)]
    return [part for part in parts if part]


def _classify_segment(segment: str, index: int) -> TaskIntent:
    lowered = segment.lower()
    if not segment.strip() or segment.strip() in {"?", "？", ".", "。"}:
        return _intent(index, "clarification", segment, risk="none", status="needs_user_input")
    if _contains_any(lowered, _NOOP_MARKERS):
        return _intent(index, "noop", segment, risk="none", status="ready")
    if _contains_any(lowered, _TRANSPORT_MARKERS) and _contains_any(lowered, _CONTROL_MARKERS):
        return _intent(
            index,
            "transport_control",
            segment,
            capabilities=["live_transport:wechat"],
            risk="external_control",
            status="blocked",
            metadata={"transport": "wechat"},
        )
    if _contains_any(lowered, _ROLEPLAY_MARKERS):
        return _intent(index, "roleplay", segment, risk="none", status="ready", metadata={"scope": "current_thread"})
    if _contains_any(lowered, _RETRIEVAL_MARKERS):
        capabilities = ["retrieval.run"]
        metadata = {}
        if _contains_any(lowered, _LIVE_NETWORK_MARKERS):
            metadata["live_network_requested"] = True
        return _intent(index, "retrieval_research", segment, capabilities=capabilities, risk="read", status="ready", metadata=metadata)
    if _contains_any(lowered, _WORKSPACE_WRITE_MARKERS):
        return _intent(index, "workspace_write", segment, capabilities=["workspace:write"], risk="write", status="needs_permission")
    if _contains_any(lowered, _WORKSPACE_READ_MARKERS):
        return _intent(index, "workspace_read", segment, capabilities=["workspace.search", "file.read"], risk="read", status="ready")
    if _contains_any(lowered, _JOKE_MARKERS):
        return _intent(index, "direct_answer", segment, risk="none", status="ready", metadata={"style": "joke"})
    return _intent(index, "direct_answer", segment, risk="none", status="ready")


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


def _is_compound(text: str, intents: list[TaskIntent]) -> bool:
    if len(intents) > 1:
        return True
    lowered = text.lower()
    return sum(1 for marker in _COMPOUND_MARKERS if marker in lowered) >= 2


def _blocked_capabilities(intents: list[TaskIntent]) -> list[str]:
    blocked: list[str] = []
    for intent in intents:
        if intent.kind == "transport_control":
            blocked.extend(intent.required_capabilities)
        elif intent.kind == "workspace_write":
            blocked.extend(intent.required_capabilities)
    return _ordered_unique(blocked)


def _warnings(text: str, intents: list[TaskIntent], *, compound: bool) -> list[str]:
    warnings: list[str] = []
    if compound:
        warnings.append("compound_task_requires_explicit_plan_confirmation")
    for intent in intents:
        if intent.metadata.get("live_network_requested") is True:
            warnings.append("live_network_not_enabled_by_default")
    if any(intent.kind == "roleplay" for intent in intents):
        warnings.append("roleplay_scope_is_current_thread_only")
    if _contains_any(text.lower(), _TRANSPORT_MARKERS):
        warnings.append("live_transports_are_not_kernel_v3_decision_makers")
    return _ordered_unique(warnings)


def _primary_intent(intents: list[TaskIntent]) -> str:
    priority = [
        "transport_control",
        "noop",
        "retrieval_research",
        "workspace_write",
        "workspace_read",
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


def _response_hint(text: str, primary: str, *, blocked: list[str], compound: bool) -> str | None:
    if primary == "noop":
        return "好的，我不会执行任何工具、写入或外部操作。"
    if primary == "roleplay":
        role = "Jarvis" if "jarvis" in text.lower() or "贾维斯" in text else "指定角色"
        return f"可以。我可以在当前对话中按 {role} 的表达风格回应，但这不会改变系统权限、工具边界或长期记忆。"
    if primary == "transport_control":
        return "当前 kernel_v3 不接管 WeChat 或其他 live transport。transports 不是决策层；如需后续接入，应作为独立 transport phase，并继续由宿主校验权限。"
    if compound:
        return None
    if blocked:
        return "当前请求需要未开放的能力：" + ", ".join(blocked)
    return None


def _clarification_question(intents: list[TaskIntent], *, blocked: list[str], compound: bool) -> str:
    if compound:
        pieces = [f"{intent.sequence_index}. {intent.kind}: {intent.text}" for intent in intents]
        capability_text = f" 未开放能力：{', '.join(blocked)}。" if blocked else ""
        return "检测到复合任务，请确认是否拆成以下步骤逐步执行：" + "；".join(pieces) + capability_text
    if blocked:
        return "这个请求需要未开放能力：" + ", ".join(blocked) + "。请确认是否改为只读规划或提供允许的目标。"
    return "请明确目标、文件名或需要检索的问题。"


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
