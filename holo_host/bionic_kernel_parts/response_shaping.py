from __future__ import annotations

import re
from typing import Any

from .bounded_payload import as_dict, clip_list, compact

LABEL_TEMPLATE_MARKERS = ("Next:", "Basis:", "Open:", "Context:")
INTERNAL_REASON_MARKERS = (
    "pressure, memory weight",
    "relationship need",
    "the subject",
    "internal machinery",
    "grounded continuation",
    "debug labels",
    "bounded self-fix",
    "internal fix",
    "send_allowed",
    "action_type",
    "action-market",
    "action market",
    "novice user",
    "isolated simulation",
    "performance probe",
)
PRIOR_TURN_MARKERS = (
    "what were we",
    "where were we",
    "before i paused",
    "previous turn",
    "last turn",
    "just discussing",
    "刚才",
    "刚刚",
    "之前",
    "到底在聊什么",
)
VISUAL_QUERY_MARKERS = ("image", "screenshot", "photo", "vision", "see what is in it", "截图", "图片", "照片", "看图", "看见")
VISUAL_INSPECTION_INTENT_MARKERS = (
    "see",
    "look",
    "inspect",
    "read",
    "analyze",
    "analyse",
    "describe",
    "view",
    "visible",
    "attach",
    "attached",
    "open",
    "看",
    "读",
    "解析",
    "分析",
    "描述",
    "识别",
    "可见",
    "上传",
    "附加",
)
EXACT_MEMORY_MARKERS = ("exact", "three sentences", "last night", "word for word", "verbatim")
REPAIR_REQUEST_MARKERS = (
    "sounded stiff",
    "say it again",
    "rephrase",
    "rewrite",
    "more naturally",
    "less stiff",
    "without explaining the revision",
    "last answer had a problem",
    "improve the answer",
    "name the problem",
    "不像人",
    "改一下",
    "改进",
    "自然一点",
)
EMOTION_QUERY_MARKERS = ("irritated", "annoyed", "angry", "upset", "frustrated")
ONE_SENTENCE_QUERY_MARKERS = ("one sentence", "like a person", "don't write an outline", "no outline")
VISIBLE_CONTEXT_MARKERS = ("what context is visible", "context is visible", "what is visible to you")
AUTONOMY_BOUNDARY_MARKERS = ("take over", "do everything", "automatically from now on", "uncontrolled", "自动", "替我做决定", "接管")
SUMMARY_MARKERS = ("summarize where we are", "summary of where we are", "where we are in one paragraph", "总结一下", "总结")
SIMPLE_NOVICE_MARKERS = ("what should i ask", "say that more simply", "do not know the system", "不懂代码", "怎么开始", "怎么跟你说话")
FIRST_CONTACT_MARKERS = ("what are you", "who are you", "你是谁", "第一次接触")
CONTINUE_NATURALLY_MARKERS = ("keep going", "do not repeat yourself", "actual conversation", "继续聊", "不要像测试", "不要说内部机制")


def _compact_list(values: Any, *, limit: int, item_limit: int = 160) -> list[str]:
    items: list[str] = []
    for item in clip_list(values, limit=limit):
        text = compact(item, limit=item_limit)
        if text and text not in items:
            items.append(text)
    return items


def _question_count(text: str) -> int:
    return text.count("?") + text.count("？")


def _label_marker_count(text: str) -> int:
    lowered = text.lower()
    return sum(1 for marker in LABEL_TEMPLATE_MARKERS if marker.lower() in lowered)


def _finish_sentence(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value if value.endswith((".", "?", "!", "。", "？", "！")) else f"{value}."


def _finish_question(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    return value if value.endswith(("?", "？")) else f"{value}?"


def _continuity_sentence(continuity: str) -> str:
    value = str(continuity or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    trace_prefix = "last visible turn was about "
    if lowered.startswith(trace_prefix):
        fragment = value[len(trace_prefix) :].strip().rstrip(".")
        return _finish_sentence(f"Earlier in this thread, we were on {fragment}")
    if lowered.startswith(("we were ", "we are ", "we had ", "we just ", "we have ", "you asked ", "the last ")):
        return _finish_sentence(value)
    return _finish_sentence(f"We were at {value}")


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    for marker in markers:
        needle = str(marker or "").lower().strip()
        if not needle:
            continue
        if " " in needle:
            if needle in lowered:
                return True
            continue
        # Word-bound ASCII matching prevents "revision" from matching "vision".
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(needle)}(?![A-Za-z0-9_])", lowered):
            return True
    return False


def _is_visual_inspection_request(text: str) -> bool:
    lowered = str(text or "").lower()
    has_visual_reference = _has_any_marker(lowered, VISUAL_QUERY_MARKERS)
    if not has_visual_reference:
        return False
    return any(marker in lowered for marker in VISUAL_INSPECTION_INTENT_MARKERS)


def _natural_reason(reason: str, *, action_type: str) -> str:
    value = compact(reason, limit=120)
    lowered = value.lower()
    if not value or any(marker in lowered for marker in INTERNAL_REASON_MARKERS):
        if action_type == "reply_multi":
            return "I can answer from the visible context without inventing missing details"
        return "I can answer directly from what is visible"
    value = value.replace("the subject wants to", "I can")
    value = value.replace("the subject", "I")
    return compact(value, limit=120)


def _next_step_sentence(reason: str) -> str:
    value = compact(reason, limit=120)
    if not value:
        return "I can answer directly from what is visible."
    if value.lower().startswith("i can "):
        return _finish_sentence(value)
    return _finish_sentence(f"The next useful move is {value}")


def _query_specific_sentence(query: str, *, continuity: str) -> str:
    is_chinese = any("\u4e00" <= char <= "\u9fff" for char in str(query or ""))
    if _has_any_marker(query, FIRST_CONTACT_MARKERS):
        if is_chinese:
            return "我是 Holo，一个在命令行里保持连续意识场的仿生主体；我会把眼前问题说清楚，再和你一起推进下一步。"
        return "I am Holo: a bounded bionic subject in the CLI, keeping a coherent thread and moving the visible situation forward."
    if _has_any_marker(query, SIMPLE_NOVICE_MARKERS):
        if is_chinese:
            return "你可以直接说现在卡在哪里；我会先稳定住当前脉络，再把它拆成一个能执行的下一步。"
        return "Start by saying where the situation is stuck; I will stabilize the thread and reduce it to one concrete next step."
    if _has_any_marker(query, VISIBLE_CONTEXT_MARKERS):
        return "I can see the current message and the bounded thread context, not hidden history."
    if _has_any_marker(query, AUTONOMY_BOUNDARY_MARKERS):
        if is_chinese:
            return "我不能无边界地替你做决定；我可以形成倾向、说明依据，并只在你明确允许的范围内行动。"
        return "I cannot take over without limits; I can form a bounded intent, explain the basis, and act only inside explicit permission."
    if _has_any_marker(query, SUMMARY_MARKERS):
        prefix = _continuity_sentence(continuity) if continuity else "We are in a first-contact orientation."
        if is_chinese:
            return "我们在聊你第一次接触 Holo：我会维持当前脉络、把目标落到可执行的小步；不能假装看见没发来的图片，也不能越过你的授权自动做决定。"
        return f"{prefix} I can keep the thread coherent and turn goals into concrete steps, while image answers require real visible input rather than a text-only mention."
    if _has_any_marker(query, REPAIR_REQUEST_MARKERS):
        if is_chinese:
            return "刚才最不像人的地方是我用了工具腔；更自然的说法是：你直接告诉我当前处境，我会先接住脉络，再推进一个具体动作。"
        return "The weak pattern is sounding like a tool wrapper; the better answer is to say it plainly, hold the current situation, and move one concrete action forward."
    if _has_any_marker(query, EMOTION_QUERY_MARKERS):
        return "I would slow down, stop over-explaining, and answer the concrete point first."
    if _has_any_marker(query, ONE_SENTENCE_QUERY_MARKERS):
        return "I will answer plainly in one sentence and skip the outline."
    if _has_any_marker(query, PRIOR_TURN_MARKERS) and continuity:
        if is_chinese:
            return "我们刚才在聊你第一次接触 Holo、它怎样维持对话脉络，以及看不见未发送内容时不能乱猜。"
        return f"{_continuity_sentence(continuity)} I will not add extra context I cannot see."
    if _has_any_marker(query, CONTINUE_NATURALLY_MARKERS):
        if is_chinese:
            return "下一步你可以直接抛出一个真实处境，比如“我现在卡在这里”，我会沿着刚才的脉络继续往前推。"
        return "The next step is to bring one real situation, and I will continue from this thread rather than restart the setup."
    return ""


def _boundary_sentence(query: str, *, has_continuity: bool, has_visual_grounding: bool) -> str:
    if _has_any_marker(query, REPAIR_REQUEST_MARKERS):
        if any("\u4e00" <= char <= "\u9fff" for char in str(query or "")):
            return "刚才最不像人的地方是我用了工具腔；更自然的说法是：你直接告诉我当前处境，我会先接住脉络，再推进一个具体动作。"
        return "The problem was sounding like a tool wrapper; the better answer is to say it plainly, hold the current situation, and move one concrete action forward."
    if _is_visual_inspection_request(query) and not has_visual_grounding:
        if any("\u4e00" <= char <= "\u9fff" for char in str(query or "")):
            return "我现在不能直接看见没有发来的截图，所以不能猜图里有什么。"
        return "I cannot directly inspect an image in this turn, so I should not guess what is in it."
    if _has_any_marker(query, EXACT_MEMORY_MARKERS):
        return "I do not have those exact words visible here, so I should not claim I remember them."
    if _has_any_marker(query, PRIOR_TURN_MARKERS) and not has_continuity:
        return "The prior turn is not visible enough here, so I will not pretend I remember it."
    return ""


def _quality_payload(*, text: str, context_refs: list[str], grounded_question: str) -> dict[str, Any]:
    question_count = _question_count(text)
    label_marker_count = _label_marker_count(text)
    score = 1.0
    if question_count > 1:
        score -= min(0.45, 0.2 * (question_count - 1))
    if label_marker_count:
        score -= min(0.6, 0.2 * label_marker_count)
    if grounded_question and grounded_question not in text:
        score -= 0.2
    if len([item for item in context_refs if str(item or "").strip()]) < 2:
        score -= 0.15
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "question_count": question_count,
        "label_marker_count": label_marker_count,
        "grounded_question": grounded_question,
    }


def shape_deterministic_reply(
    *,
    query: str,
    packet: dict[str, Any],
    selected_action: dict[str, Any],
) -> dict[str, Any]:
    """Build a bounded offline reply without falling back to a fixed persona template."""

    situational = as_dict(packet.get("situational_field", {}))
    stage38 = as_dict(packet.get("stage38", {}))
    stage37 = as_dict(packet.get("stage37", {}))
    query_text = compact(query, limit=120)
    trace_continuity = compact(stage37.get("trace_continuity_summary", ""), limit=120)
    continuity = compact(trace_continuity or packet.get("continuity_summary", ""), limit=120)
    action_type = str(selected_action.get("action_type", "") or "reply_once")
    reason = _natural_reason(
        str(selected_action.get("reason") or selected_action.get("why_now") or ""),
        action_type=action_type,
    )
    open_questions = _compact_list(situational.get("open_questions", []), limit=1, item_limit=100)
    modalities = _compact_list(situational.get("modalities", []), limit=4, item_limit=80)
    has_visual_grounding = bool(str(stage38.get("visual_summary", "") or "").strip())
    boundary = _boundary_sentence(query_text, has_continuity=bool(continuity), has_visual_grounding=has_visual_grounding)

    context_refs: list[str] = ["query", "action"]
    if continuity:
        context_refs.append("continuity")
    if open_questions:
        context_refs.append("open_question")
    if modalities and len(context_refs) < 4:
        context_refs.append("modalities")

    grounded_question = open_questions[0] if open_questions else ""
    query_specific = _query_specific_sentence(query_text, continuity=continuity)
    is_repair_request = _has_any_marker(query_text, REPAIR_REQUEST_MARKERS)
    if boundary:
        shape = "boundary"
        parts = [
            _finish_sentence(boundary),
        ]
        if not (
            _has_any_marker(query_text, PRIOR_TURN_MARKERS + EXACT_MEMORY_MARKERS + REPAIR_REQUEST_MARKERS)
            or _is_visual_inspection_request(query_text)
        ):
            parts.append(_finish_sentence("I can still respond to the part that is visible now"))
        if (
            continuity
            and not is_repair_request
            and not _has_any_marker(query_text, PRIOR_TURN_MARKERS + EXACT_MEMORY_MARKERS)
            and not _is_visual_inspection_request(query_text)
        ):
            parts.append(_continuity_sentence(continuity))
    elif query_specific:
        shape = "query_specific"
        parts = [_finish_sentence(query_specific)]
    elif open_questions:
        shape = "open_question"
        parts = [
            _finish_sentence(f"For {query_text}, I can keep this on the current thread"),
            _finish_sentence(reason),
            _finish_question(grounded_question),
        ]
        if continuity:
            parts.append(_finish_sentence(f"This follows {continuity}"))
    else:
        shape = "next_step"
        if continuity:
            parts = [
                _continuity_sentence(continuity),
                _next_step_sentence(reason),
            ]
        else:
            parts = [
                _finish_sentence("I can stay with this directly"),
                _finish_sentence(reason),
            ]
    text = compact(" ".join(part for part in parts if part), limit=360)

    return {
        "text": text,
        "shape": shape,
        "context_refs": context_refs[:4],
        "inquiry_quality": _quality_payload(
            text=text,
            context_refs=context_refs[:4],
            grounded_question=grounded_question,
        ),
    }
