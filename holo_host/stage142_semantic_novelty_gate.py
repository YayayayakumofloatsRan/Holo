from __future__ import annotations

import re
from typing import Any

from .common import compact_text
from .memory_alignment import extract_memory_claims
from .memory_grounding import claimed_memory_families
from .models import ReplyBubble
from .tool_grounding import evaluate_tool_grounding

STAGE142_SCHEMA = "holo.stage142.semantic_novelty_gate.v1"

REPORT_STATUSES = {
    "passed",
    "suppressed_duplicate",
    "repaired_contradiction",
    "blocked_ungrounded_claim",
}

GENERIC_OFFER_PATTERNS = (
    r"\blet me know\b",
    r"\bif you need\b",
    r"\bhow can i help\b",
    r"\banything else\b",
    r"\bi'?m here to help\b",
    r"\bfeel free to ask\b",
    "\u8fd8\u9700\u8981\u6211",
    "\u6709\u4ec0\u4e48\u9700\u8981",
    "\u6211\u53ef\u4ee5\u5e2e",
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "can",
    "for",
    "from",
    "have",
    "i",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "this",
    "to",
    "we",
    "with",
    "you",
    "your",
}

USEFUL_NEW_ROLES = {
    "answer",
    "clarification",
    "correction",
    "tool_feedback",
    "memory_grounding",
    "visual_grounding",
    "risk_notice",
    "reasoning_step",
    "commitment",
    "summary",
    "ask_next",
    "fallback_limitation",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _tokens(text: str) -> set[str]:
    current = str(text or "").lower()
    tokens = {
        token.strip(".,;:!?()[]{}\"'")
        for token in re.findall(r"stage\d+|[a-zA-Z][a-zA-Z0-9_./:-]*|\d+", current, flags=re.IGNORECASE)
    }
    result = {token for token in tokens if token and token not in STOPWORDS and len(token) > 1}
    for phrase, token in (
        ("\u8bb0\u5fc6", "memory"),
        ("\u5de5\u5177", "tool"),
        ("\u68c0\u67e5", "checked"),
        ("\u6d4b\u8bd5", "tests"),
        ("\u4fee\u590d", "repair"),
        ("\u51b2\u7a81", "conflict"),
        ("\u4e0d\u786e\u5b9a", "uncertain"),
        ("\u4e0d\u652f\u6301", "unsupported"),
        ("\u7ebf\u7d22", "cue"),
        ("\u98ce\u9669", "risk"),
        ("\u627f\u8bfa", "commitment"),
        ("\u603b\u7ed3", "summary"),
        ("\u9700\u8981", "need"),
    ):
        if phrase in str(text or ""):
            result.add(token)
    return result


def _first_sentence(text: str) -> str:
    current = str(text or "").strip()
    if not current:
        return ""
    parts = re.split(r"(?<=[.!?\u3002\uff01\uff1f])\s+|[\n\r]+", current, maxsplit=1)
    return parts[0].strip()


def _normalize_sentence(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower()).strip(" .,;:!?")


def _remove_leading_duplicate_text(text: str, previous: str) -> tuple[str, bool]:
    current = str(text or "").strip()
    prior = str(previous or "").strip()
    if not current or not prior:
        return current, False
    if _normalize_sentence(current) == _normalize_sentence(prior):
        return "", True
    if current.startswith(prior):
        return current[len(prior) :].lstrip(" \n\r\t,.;:!?"), True
    first = _first_sentence(current)
    if first and _normalize_sentence(first) == _normalize_sentence(prior):
        return current[len(first) :].lstrip(" \n\r\t,.;:!?"), True
    return current, False


def classify_semantic_role(text: str, purpose: str = "") -> str:
    lowered = str(text or "").lower()
    raw = str(text or "")
    purpose_text = str(purpose or "").lower()
    if purpose_text == "fast_reaction" or re.fullmatch(r"\s*(ok|okay|got it|understood|yes|no|sure)[.!]?\s*", lowered):
        return "ack"
    if any(token in lowered for token in ("actually", "correction", "correcting", "i should correct", "i need to correct")) or any(
        token in raw for token in ("\u66f4\u6b63", "\u4fee\u6b63", "\u521a\u624d\u4e0d\u51c6")
    ):
        return "correction"
    if any(token in lowered for token in ("tool", "checked", "inspected", "ran", "pytest", "git", "workspace", "file", "command")) or any(
        token in raw for token in ("\u5de5\u5177", "\u68c0\u67e5", "\u8fd0\u884c", "\u547d\u4ee4")
    ):
        return "tool_feedback"
    if any(token in lowered for token in ("memory source", "memory cue", "from memory", "remember", "recall", "source support")) or any(
        token in raw for token in ("\u8bb0\u5fc6", "\u7ebf\u7d22", "\u6765\u6e90")
    ):
        return "memory_grounding"
    if any(token in lowered for token in ("image", "camera", "visual", "seen", "frame")) or any(token in raw for token in ("\u89c6\u89c9", "\u6444\u50cf", "\u753b\u9762")):
        return "visual_grounding"
    if any(token in lowered for token in ("risk", "unsafe", "privacy", "permission", "cannot", "not enough", "unavailable", "limitation")) or any(
        token in raw for token in ("\u98ce\u9669", "\u6743\u9650", "\u4e0d\u8db3", "\u65e0\u6cd5")
    ):
        return "fallback_limitation"
    if lowered.strip().endswith("?") or raw.strip().endswith("\uff1f") or any(token in lowered for token in ("which", "what do you want", "should i")):
        return "ask_next"
    if any(token in lowered for token in ("i will", "i'll", "next i", "i can do", "commit", "promise")) or any(token in raw for token in ("\u6211\u4f1a", "\u63a5\u4e0b\u6765", "\u627f\u8bfa")):
        return "commitment"
    if any(token in lowered for token in ("because", "therefore", "so the", "step", "reason")) or any(token in raw for token in ("\u56e0\u4e3a", "\u6240\u4ee5", "\u6b65\u9aa4")):
        return "reasoning_step"
    if any(token in lowered for token in ("summary", "in short", "overall", "conclusion")) or any(token in raw for token in ("\u603b\u7ed3", "\u7b80\u800c\u8a00\u4e4b")):
        return "summary"
    if any(token in lowered for token in ("done", "completed", "fixed", "updated", "added", "passed", "verified")) or any(
        token in raw for token in ("\u5b8c\u6210", "\u4fee\u597d", "\u901a\u8fc7", "\u9a8c\u8bc1")
    ):
        return "answer"
    if any(token in lowered for token in ("means", "is that", "the point", "to clarify")) or any(token in raw for token in ("\u6f84\u6e05", "\u610f\u601d\u662f")):
        return "clarification"
    if lowered.strip().endswith(".") or raw.strip().endswith("\u3002"):
        return "answer"
    return "unknown"


def _is_generic_offer(text: str) -> bool:
    current = str(text or "")
    return any(re.search(pattern, current, flags=re.IGNORECASE) for pattern in GENERIC_OFFER_PATTERNS)


def _tool_blocked(text: str, tool_grounding: dict[str, Any] | None) -> bool:
    report = _dict(tool_grounding)
    if str(report.get("status", "") or "") != "ungrounded_tool_claim":
        return False
    local = evaluate_tool_grounding(text, [])
    missing = set(str(item) for item in list(report.get("missing_families", []) or []))
    claimed = set(str(item) for item in list(local.get("claimed_families", []) or []))
    return bool(missing & claimed)


def _is_limitation_text(text: str) -> bool:
    lowered = str(text or "").lower()
    raw = str(text or "")
    return any(
        token in lowered
        for token in (
            "not enough",
            "not clearly support",
            "source unavailable",
            "memory cue",
            "weak",
            "uncertain",
            "cannot verify",
            "not state",
            "conflicts",
        )
    ) or any(token in raw for token in ("\u4e0d\u8db3", "\u4e0d\u80fd\u786e\u8ba4", "\u7ebf\u7d22", "\u51b2\u7a81", "\u4e0d\u786e\u5b9a"))


def _memory_blocked(
    text: str,
    memory_grounding: dict[str, Any] | None,
    memory_alignment: dict[str, Any] | None,
) -> bool:
    has_memory_claim = bool(claimed_memory_families(text) or extract_memory_claims(text))
    if not has_memory_claim:
        return False
    if _is_limitation_text(text):
        return False
    grounding_status = str(_dict(memory_grounding).get("status", "") or "")
    alignment_status = str(_dict(memory_alignment).get("status", "") or "")
    return grounding_status in {"ungrounded_memory_claim", "contradicted_memory_claim"} or alignment_status in {
        "unsupported_memory_detail",
        "contradicted_memory_detail",
    }


def _contradiction_flags(candidate: str, prior_text: str) -> list[str]:
    current = str(candidate or "").lower()
    prior = str(prior_text or "").lower()
    flags: list[str] = []
    if not current or not prior:
        return flags
    explicit_repair = any(token in current for token in ("actually", "correction", "correcting", "i should correct", "to correct"))
    if explicit_repair:
        return flags
    if re.search(r"\bi can\b", prior) and re.search(r"\bi (?:cannot|can't|can not)\b", current):
        flags.append("can_conflict")
    if re.search(r"\bi (?:cannot|can't|can not)\b", prior) and re.search(r"\bi can\b", current):
        flags.append("can_conflict")
    if re.search(r"\b(will|done|completed|passed)\b", prior) and re.search(r"\b(won't|will not|not done|failed)\b", current):
        flags.append("status_conflict")
    if re.search(r"\b(yes|true)\b", prior) and re.search(r"\b(no|false)\b", current):
        flags.append("polarity_conflict")
    if "\u53ef\u4ee5" in prior and "\u4e0d\u80fd" in current:
        flags.append("can_conflict")
    return flags


def _has_concrete_task_progress(text: str) -> bool:
    lowered = str(text or "").lower()
    raw = str(text or "")
    return any(
        token in lowered
        for token in ("ran", "checked", "fixed", "updated", "added", "removed", "verified", "passed", "failed", "created", "wrote")
    ) or any(token in raw for token in ("\u5b8c\u6210", "\u4fee\u590d", "\u901a\u8fc7", "\u9a8c\u8bc1", "\u65b0\u589e", "\u68c0\u67e5"))


def _grounding_limitation_new(text: str, memory_grounding: dict[str, Any] | None, memory_alignment: dict[str, Any] | None) -> bool:
    if not _is_limitation_text(text):
        return False
    return str(_dict(memory_grounding).get("status", "") or "") not in {"", "grounded"} or str(_dict(memory_alignment).get("status", "") or "") not in {
        "",
        "aligned",
        "no_memory_claim",
    }


def _tool_newly_reported(text: str, tool_grounding: dict[str, Any] | None) -> bool:
    if classify_semantic_role(text) != "tool_feedback":
        return False
    report = _dict(tool_grounding)
    return bool(report.get("observed_families") or str(report.get("status", "") or "") == "grounded")


def _detail_requested(stream_plan: dict[str, Any] | None) -> bool:
    plan = _dict(stream_plan)
    return bool(plan.get("user_requested_detail", False) or plan.get("detail_requested", False)) or int(plan.get("expression_budget", 0) or 0) > 2


def evaluate_stage142_bubbles(
    bubbles: list[ReplyBubble],
    *,
    stream_plan: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    channel: str = "",
) -> dict[str, Any]:
    candidates = list(bubbles or [])
    evaluations: list[dict[str, Any]] = []
    emitted_text = ""
    first_role = ""
    suppressed = 0
    repaired = 0
    emitted = 0
    blocked = 0
    status = "passed"

    for index, bubble in enumerate(candidates):
        original_text = str(bubble.text or "").strip()
        role = classify_semantic_role(original_text, bubble.purpose)
        if index == 0:
            first_role = role
        trimmed_text, trimmed = _remove_leading_duplicate_text(original_text, emitted_text)
        analysis_text = trimmed_text if trimmed else original_text
        prior_tokens = _tokens(emitted_text)
        current_tokens = _tokens(analysis_text)
        if not current_tokens:
            overlap = 1.0 if prior_tokens else 0.0
        else:
            overlap = len(current_tokens & prior_tokens) / max(1, len(current_tokens))
        novelty = max(0.0, min(1.0, 1.0 - overlap))
        contradictions = _contradiction_flags(analysis_text, emitted_text)
        grounding_blocked = _tool_blocked(analysis_text, tool_grounding) or _memory_blocked(analysis_text, memory_grounding, memory_alignment)
        suppression_reason = ""
        should_emit = True

        if index == 0:
            should_emit = bool(analysis_text)
            if not should_emit:
                suppression_reason = "empty_first_bubble"
        else:
            useful_role_change = role != first_role and role in USEFUL_NEW_ROLES
            newly_reported_tool = _tool_newly_reported(analysis_text, tool_grounding)
            grounding_limitation = _grounding_limitation_new(analysis_text, memory_grounding, memory_alignment)
            explicit_repair = role == "correction"
            concrete_progress = _has_concrete_task_progress(analysis_text)
            requested_detail = _detail_requested(stream_plan)
            if grounding_blocked:
                should_emit = False
                suppression_reason = "grounding_blocked"
                blocked += 1
            elif contradictions and not explicit_repair:
                should_emit = False
                suppression_reason = "unrepaired_contradiction"
                status = "repaired_contradiction"
            elif _is_generic_offer(analysis_text) and novelty < 0.55:
                should_emit = False
                suppression_reason = "generic_offer_without_new_state"
            elif not analysis_text:
                should_emit = False
                suppression_reason = "duplicate_prefix_only"
            elif role == first_role and novelty < 0.45 and not any(
                [newly_reported_tool, grounding_limitation, explicit_repair, concrete_progress, requested_detail]
            ):
                should_emit = False
                suppression_reason = "same_role_low_novelty"
            elif novelty < 0.45 and not any(
                [useful_role_change, newly_reported_tool, grounding_limitation, explicit_repair, concrete_progress, requested_detail]
            ):
                should_emit = False
                suppression_reason = "low_novelty"

        if trimmed and should_emit:
            repaired += 1
        if should_emit:
            emitted += 1
            emitted_text = " ".join(part for part in [emitted_text, analysis_text] if part).strip()
        else:
            suppressed += 1
            if status == "passed":
                status = "blocked_ungrounded_claim" if grounding_blocked else "suppressed_duplicate"

        evaluations.append(
            {
                "bubble_index": index,
                "purpose": str(bubble.purpose or ""),
                "semantic_role": role,
                "novelty_score": round(novelty, 4),
                "overlap_score": round(overlap, 4),
                "contradiction_flags": contradictions,
                "grounding_blocked": bool(grounding_blocked),
                "should_emit": bool(should_emit),
                "suppression_reason": suppression_reason,
                "repaired_text": compact_text(analysis_text, 360) if trimmed and should_emit else "",
            }
        )

    if blocked:
        status = "blocked_ungrounded_claim"
    elif any(item["suppression_reason"] == "unrepaired_contradiction" for item in evaluations):
        status = "repaired_contradiction"
    elif suppressed and status == "passed":
        status = "suppressed_duplicate"

    return {
        "schema": STAGE142_SCHEMA,
        "candidate_count": len(candidates),
        "emitted_count": emitted,
        "suppressed_count": suppressed,
        "repaired_count": repaired,
        "evaluations": evaluations,
        "status": status,
    }


def apply_stage142_gate(
    bubbles: list[ReplyBubble],
    *,
    stream_plan: dict[str, Any] | None = None,
    tool_grounding: dict[str, Any] | None = None,
    memory_grounding: dict[str, Any] | None = None,
    memory_alignment: dict[str, Any] | None = None,
    channel: str = "",
) -> tuple[list[ReplyBubble], dict[str, Any]]:
    candidates = list(bubbles or [])
    report = evaluate_stage142_bubbles(
        candidates,
        stream_plan=stream_plan,
        tool_grounding=tool_grounding,
        memory_grounding=memory_grounding,
        memory_alignment=memory_alignment,
        channel=channel,
    )
    kept: list[ReplyBubble] = []
    for bubble, evaluation in zip(candidates, list(report.get("evaluations", []) or [])):
        if not bool(evaluation.get("should_emit", False)):
            continue
        repaired_text = str(evaluation.get("repaired_text", "") or "").strip()
        text = repaired_text if repaired_text else str(bubble.text or "").strip()
        if not text:
            continue
        kept.append(ReplyBubble(text=text, delay_ms=max(0, int(bubble.delay_ms or 0)), purpose=bubble.purpose))
    return kept[:5], report
