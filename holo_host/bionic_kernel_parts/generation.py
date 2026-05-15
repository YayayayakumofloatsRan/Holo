from __future__ import annotations

import re
from typing import Any

from ..config import HostConfig
from ..models import ProcessorTaskRequest
from .bounded_payload import bounded_dict, compact
from .contracts import SPEECH_ACTIONS, STAGE29_NAME
from .response_shaping import shape_deterministic_reply


LABEL_MARKERS = ("next:", "basis:", "open:", "context:")
THEATRICAL_EMOTION_MARKERS = ("ready to bite", "pour you some wine", "growl it out")
EMOTION_QUERY_MARKERS = ("irritated", "annoyed", "angry", "upset", "frustrated")
MEMORY_OVERCLAIM_MARKERS = (
    "across our conversations",
    "across conversations",
    "i remember the details",
    "i remember details",
    "i keep track of what you share",
    "use them later",
    "personal memory",
    "companion who keeps track",
)
ASCII_VISUAL_QUERY_MARKERS = ("image", "screenshot", "photo", "visual")
NON_ASCII_VISUAL_QUERY_MARKERS = ("截图", "图片", "照片", "读图", "看图", "视觉")
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


def _question_count(text: str) -> int:
    return str(text or "").count("?") + str(text or "").count("？")


def _label_marker_count(text: str) -> int:
    lowered = str(text or "").lower()
    return sum(1 for marker in LABEL_MARKERS if marker in lowered)


def _processor_quality_payload(text: str) -> dict[str, Any]:
    question_count = _question_count(text)
    label_count = _label_marker_count(text)
    score = 1.0
    if question_count > 1:
        score -= min(0.45, 0.2 * (question_count - 1))
    if label_count:
        score -= min(0.6, 0.2 * label_count)
    if "**" in str(text or ""):
        score -= 0.15
    return {
        "score": round(max(0.0, min(1.0, score)), 4),
        "question_count": question_count,
        "label_marker_count": label_count,
        "grounded_question": "",
    }


def _strip_markdown_emphasis(text: str) -> str:
    return str(text or "").replace("**", "").replace("__", "")


def _bound_questions(text: str, *, limit: int = 1) -> str:
    count = 0
    chars: list[str] = []
    for char in str(text or ""):
        if char in {"?", "？"}:
            count += 1
            chars.append(char if count <= limit else "。")
            continue
        chars.append(char)
    bounded = "".join(chars)
    while "。。" in bounded:
        bounded = bounded.replace("。。", "。")
    return bounded


def _emotion_guard_text(query: str) -> str:
    lowered_query = str(query or "").lower()
    if any(marker in lowered_query for marker in EMOTION_QUERY_MARKERS):
        return "I would slow down, stop over-explaining, and answer the concrete point first."
    return "I will keep the reply plain and concrete."


def _is_visual_query(text: str) -> bool:
    lowered = str(text or "").lower()
    has_visual_reference = any(
        re.search(rf"(?<![A-Za-z0-9_]){re.escape(marker)}(?![A-Za-z0-9_])", lowered)
        for marker in ASCII_VISUAL_QUERY_MARKERS
    ) or any(marker in lowered for marker in NON_ASCII_VISUAL_QUERY_MARKERS)
    if not has_visual_reference:
        return False
    return any(marker in lowered for marker in VISUAL_INSPECTION_INTENT_MARKERS)


class BionicGeneration:
    def __init__(self, *, config: HostConfig, runner: Any | None = None) -> None:
        self.config = config
        self.runner = runner

    def generate(
        self,
        *,
        query: str,
        packet: dict[str, Any],
        selected_action: dict[str, Any],
        channel: str,
        adapter: str,
        thread_key: str,
    ) -> dict[str, Any]:
        action_type = str(selected_action.get("action_type", "") or "")
        if action_type not in SPEECH_ACTIONS:
            return {
                "mode": "action_no_generation",
                "text": "",
                "provider": "",
                "model": "",
                "reason": f"selected action {action_type or '<unknown>'} is not a speech action",
            }
        if self.runner is None:
            shaped = shape_deterministic_reply(query=query, packet=packet, selected_action=selected_action)
            return {
                "mode": "deterministic_fallback",
                "text": shaped["text"],
                "provider": "deterministic",
                "model": "",
                "shape": shaped["shape"],
                "context_refs": shaped["context_refs"],
                "inquiry_quality": shaped["inquiry_quality"],
            }
        continuity = compact(packet.get("continuity_summary", ""), limit=280)
        stage38 = bounded_dict(packet.get("stage38", {}), depth=3)
        visual_grounding = compact(stage38.get("visual_summary", ""), limit=280)
        capability_line = (
            "Capability boundary: if no image summary is visible, say you cannot inspect the image in this turn; "
            "do not mention internal routing."
        )
        visual_line = (
            f"Visible image summary: {visual_grounding}. Use only this summary; do not claim to see more than it says."
            if visual_grounding
            else "No visible image summary is available for this turn."
        )
        prompt = "\n".join(
            [
                "Reply as Holo in one compact natural turn without label-template prefixes.",
                "Do not expose internal machinery, scoring terms, or debug labels in the user-facing reply.",
                "Keep the wording plain and concrete; avoid theatrical metaphors or test-harness phrasing.",
                "Convert the current stream state into action: name the object of attention, separate known evidence from missing input, and offer one concrete next step.",
                "For first-contact users, show the bionic loop through useful behavior rather than labels like bionic subject or CLI.",
                "Do not claim cross-conversation personal memory or self-learning; describe learning only as current-thread evidence update unless a stored memory is visible.",
                "If asking, ask at most one grounded question tied to the current continuity.",
                "Do not invent prior work. If continuity is empty, say the prior turn is not visible here.",
                capability_line,
                visual_line,
                f"Reply intent: {selected_action.get('action_type', 'reply_once')}",
                f"Grounding basis: {compact(selected_action.get('reason') or selected_action.get('why_now') or '', limit=220)}",
                f"Continuity: {continuity}",
                f"User query: {query}",
            ]
        )
        request = ProcessorTaskRequest(
            task_type="reply",
            prompt=prompt,
            provider_hint=str(self.config.runtime.processor_backend or ""),
            metadata={"stage": STAGE29_NAME, "channel": channel, "adapter": adapter, "thread_key": thread_key},
        )
        result = self.runner.run_task(request)
        metadata = bounded_dict(result.metadata or {}, depth=3)
        text = self._guard_processor_text(
            text=str(result.text or ""),
            query=query,
            continuity=continuity,
            metadata=metadata,
            has_visual_grounding=bool(visual_grounding),
        )
        context_refs = ["query", "action"]
        if continuity:
            context_refs.append("continuity")
        if visual_grounding:
            context_refs.append("visual_grounding")
        return {
            "mode": "processor_fabric",
            "text": text,
            "provider": str(metadata.get("provider", "") or ""),
            "model": str(metadata.get("model", "") or ""),
            "metadata": metadata,
            "inquiry_quality": _processor_quality_payload(text),
            "context_refs": context_refs,
        }

    def _guard_processor_text(
        self,
        *,
        text: str,
        query: str,
        continuity: str,
        metadata: dict[str, Any],
        has_visual_grounding: bool = False,
    ) -> str:
        query_text = str(query or "")
        lowered_query = query_text.lower()
        capabilities = metadata.get("capabilities", {}) if isinstance(metadata.get("capabilities", {}), dict) else {}
        image_support = capabilities.get("image_support")
        visual_query = _is_visual_query(lowered_query)
        if visual_query and image_support is not True and not has_visual_grounding:
            return _strip_markdown_emphasis(
                "I cannot directly inspect an image in this turn from text alone. "
                "If you provide the image through the supported image input path, I can answer from the visible image summary instead of guessing."
            )
        continuity_query = any(
            marker in lowered_query
            for marker in ("刚才", "上一轮", "之前", "修到哪里", "where were we", "previous turn", "last turn")
        )
        if continuity_query and not continuity.strip():
            visible_query = compact(query_text, limit=120)
            return _strip_markdown_emphasis(
                "The previous turn is not visible in this context, so I should not invent where we left off. "
                f"The visible request is: {visible_query}"
            )
        clean_text = _strip_markdown_emphasis(str(text or ""))
        lowered_text = clean_text.lower()
        if any(marker in lowered_text for marker in THEATRICAL_EMOTION_MARKERS):
            return _emotion_guard_text(query_text)
        if any(marker in lowered_text for marker in MEMORY_OVERCLAIM_MARKERS):
            return (
                "I can use the current thread evidence, separate what is known from what is missing, "
                "and turn your next real situation into the next concrete step."
            )
        return _bound_questions(clean_text, limit=1)
