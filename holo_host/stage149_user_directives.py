from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest

STAGE149_SCHEMA = "holo.stage149.user_directives.v1"

EMOJI_RE = re.compile(r"[\U0001F1E6-\U0001FAFF\u2600-\u27BF\ufe0f]+")
ASCII_EMOTICON_RE = re.compile(r"(?<!\w)(?:[:;=8xX]-?[)(DPp/\\|]|[)(]-?[:;=8xX])")

NO_EMOJI_OBJECT_HINTS = ("emoji", "emoticon", "表情", "表情符号")
NO_EMOJI_NEGATION_HINTS = ("不要", "不再", "别", "别再", "少", "减少", "收住", "禁止", "avoid", "do not", "don't", "less", "fewer")
ROLEPLAY_HINTS = ("role play", "roleplay", "role-play", "角色扮演", "扮演", "cosplay", "cos")
ROLEPLAY_NEGATION_HINTS = ("不要", "不再", "别", "别再", "不是", "禁止", "avoid", "do not", "don't", "not")


def _compact(value: Any, limit: int = 180) -> str:
    return compact_text(" ".join(str(value or "").strip().split()), limit)


def _row_text(row: dict[str, Any]) -> str:
    for key in ("user_text", "text", "body_text", "query", "archive_user_excerpt"):
        text = str(row.get(key, "") or "").strip()
        if text:
            return text
    return ""


def _row_id(row: dict[str, Any], prefix: str, index: int) -> str:
    return str(row.get("id", "") or row.get("message_id", "") or row.get("turn_id", "") or f"{prefix}:{index}")


def _source_rows(
    *,
    user_text: str,
    history: list[dict[str, Any]] | None,
    archive_rows: list[dict[str, Any]] | None,
    sidecar: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(list(archive_rows or [])[-80:]):
        if isinstance(row, dict):
            text = _row_text(row)
            if text:
                rows.append({"source": "archive", "source_id": _row_id(row, "archive", index), "text": _compact(text)})
    for index, row in enumerate(list(history or [])[-24:]):
        if isinstance(row, dict):
            direction = str(row.get("direction", "") or "").lower()
            if direction not in {"inbound", "user", "external_user", ""}:
                continue
            text = _row_text(row)
            if text:
                rows.append({"source": "recent_dialogue", "source_id": _row_id(row, "history", index), "text": _compact(text)})
    packet = dict(sidecar or {})
    recent_window = dict(packet.get("recent_dialogue_window", {})) if isinstance(packet.get("recent_dialogue_window", {}), dict) else {}
    for index, line in enumerate(list(recent_window.get("lines", []) or [])[-12:]):
        text = str(line or "").strip()
        if text:
            rows.append({"source": "sidecar_recent_dialogue", "source_id": f"sidecar_recent:{index}", "text": _compact(text)})
    graph_summary = str(packet.get("graph_trace_summary", "") or "").strip()
    if graph_summary:
        rows.append({"source": "graph_trace_summary", "source_id": "graph_trace_summary", "text": _compact(graph_summary, 500)})
    if str(user_text or "").strip():
        rows.append({"source": "current_turn", "source_id": f"current:{stable_digest(user_text)}", "text": _compact(user_text)})
    return rows


def _has_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(hint in lowered or hint in text for hint in hints)


def _detect_no_emoji(text: str) -> bool:
    return _has_any(text, NO_EMOJI_OBJECT_HINTS) and _has_any(text, NO_EMOJI_NEGATION_HINTS)


def _detect_no_roleplay(text: str) -> bool:
    return _has_any(text, ROLEPLAY_HINTS) and _has_any(text, ROLEPLAY_NEGATION_HINTS)


def _directive(directive_type: str, summary: str, row: dict[str, Any], *, priority: float) -> dict[str, Any]:
    return {
        "directive_id": f"{directive_type}:{stable_digest(summary, row.get('source_id', ''))}",
        "directive_type": directive_type,
        "summary": summary,
        "source_family": str(row.get("source", "") or "unknown"),
        "source_ids": [str(row.get("source_id", ""))],
        "priority": round(max(0.0, min(1.0, priority)), 4),
        "confidence": 0.92,
        "hard": True,
    }


def build_stage149_user_directives(
    *,
    user_text: str,
    channel: str = "",
    thread_key: str = "",
    chat_name: str = "",
    history: list[dict[str, Any]] | None = None,
    archive_rows: list[dict[str, Any]] | None = None,
    sidecar: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows = _source_rows(user_text=user_text, history=history, archive_rows=archive_rows, sidecar=sidecar)
    directives_by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        text = str(row.get("text", "") or "")
        if _detect_no_emoji(text):
            directives_by_type["visible_no_emoji"] = _directive(
                "visible_no_emoji",
                "visible speech must not contain emoji or emoticons unless the user explicitly reverses this preference",
                row,
                priority=1.0,
            )
        if _detect_no_roleplay(text):
            directives_by_type["identity_not_roleplay"] = _directive(
                "identity_not_roleplay",
                "Holo should speak as the local subject runtime, not as roleplay or fictional-character imitation",
                row,
                priority=1.0,
            )
    directives = list(directives_by_type.values())
    return {
        "schema": STAGE149_SCHEMA,
        "stage": "stage149-user-directive-kernel",
        "status": "active" if directives else "base_only",
        "channel": channel,
        "thread_key": thread_key,
        "chat_name": chat_name,
        "core_identity": {
            "mode": "subject_runtime_not_roleplay",
            "summary": "Holo's visible identity is the local subject runtime and memory state, not a roleplay costume.",
            "priority": 0.96,
        },
        "directives": directives,
        "hard_directive_count": sum(1 for item in directives if bool(item.get("hard", False))),
        "evidence_count": len(rows),
        "provider_call_added": False,
        "memory_write_added": False,
    }


def has_directive(report: dict[str, Any] | None, directive_type: str) -> bool:
    if not isinstance(report, dict):
        return False
    return any(isinstance(item, dict) and item.get("directive_type") == directive_type for item in list(report.get("directives", [])))


def stage149_prompt_lines(report: dict[str, Any] | None) -> list[str]:
    if not isinstance(report, dict) or not report:
        return []
    lines = [
        "visible_identity_mode=subject_runtime_not_roleplay",
        "core_identity: speak as Holo's local subject runtime, not as a fictional-character roleplay.",
    ]
    for item in list(report.get("directives", []))[:6]:
        if not isinstance(item, dict):
            continue
        directive_type = str(item.get("directive_type", "") or "")
        if directive_type == "visible_no_emoji":
            lines.append("hard_directive: no emoji or emoticons in visible speech.")
        elif directive_type == "identity_not_roleplay":
            lines.append("hard_directive: do not roleplay; do not explain yourself as a character imitation.")
        else:
            summary = _compact(item.get("summary", ""), 140)
            if summary:
                lines.append(f"hard_directive: {summary}")
    return lines[:10]


def apply_stage149_visible_directives(text: str, report: dict[str, Any] | None) -> str:
    repaired = str(text or "")
    if not repaired:
        return repaired
    if has_directive(report, "visible_no_emoji"):
        repaired = EMOJI_RE.sub("", repaired)
        repaired = ASCII_EMOTICON_RE.sub("", repaired)
        repaired = re.sub(r"[ \t]+([\u3002\uff0c\uff1f\uff01,.!?;；：:])", r"\1", repaired)
        repaired = re.sub(r"[ \t]{2,}", " ", repaired)
    if report:
        roleplay_patterns = (
            r"作为\s*赫萝\s*角色扮演[，,、\s]*",
            r"作为\s*赫萝[，,、\s]*",
            r"作为\s*一个?\s*角色扮演[，,、\s]*",
            r"我(?:会|是在)?\s*角色扮演[，,、\s]*",
            r"\brole\s*-?\s*play(?:ing)?\b[:,，、\s]*",
        )
        for pattern in roleplay_patterns:
            repaired = re.sub(pattern, "", repaired, flags=re.IGNORECASE)
    repaired = re.sub(r"\s+([，。！？；：,.!?;:])", r"\1", repaired)
    return repaired.strip()
