from __future__ import annotations

import json
import re
from typing import Any

from .common import compact_text, stable_digest
from .memory_grounding import normalize_memory_observation_ledger

MEMORY_ALIGNMENT_SCHEMA = "holo.memory_alignment.v1"

CLAIM_STATUSES = {"aligned", "weak", "unsupported", "contradicted"}
REPORT_STATUSES = {
    "aligned",
    "weakly_aligned",
    "unsupported_memory_detail",
    "contradicted_memory_detail",
    "no_memory_claim",
}

MEMORY_CLAIM_WRAPPERS: tuple[tuple[str, str], ...] = (
    (r"\bi remember\b", "generic_recall"),
    (r"\bi recall\b", "generic_recall"),
    (r"\bfrom memory\b", "generic_recall"),
    (r"\byou told me before\b", "prior_statement"),
    (r"\byou said before\b", "prior_statement"),
    (r"\bearlier you said\b", "prior_statement"),
    (r"\blast time you said\b", "prior_statement"),
    (r"\bfrom our previous conversation\b", "previous_conversation"),
    (r"\bwe discussed\b", "previous_conversation"),
    (r"\bwe talked about\b", "previous_conversation"),
    (r"\bas we discussed\b", "previous_conversation"),
    (r"\byour preference was\b", "preference"),
    (r"\byou prefer(?:red)?\b", "preference"),
    ("\u6211\u8bb0\u5f97", "generic_recall"),
    ("\u6211\u56de\u5fc6", "generic_recall"),
    ("\u4ece\u8bb0\u5fc6\u91cc", "generic_recall"),
    ("\u8bb0\u5fc6\u91cc", "generic_recall"),
    ("\u4f60\u4e4b\u524d\u8bf4\u8fc7", "prior_statement"),
    ("\u4f60\u4ee5\u524d\u8bf4\u8fc7", "prior_statement"),
    ("\u4f60\u4e0a\u6b21\u8bf4\u8fc7", "prior_statement"),
    ("\u6211\u4eec\u804a\u8fc7", "previous_conversation"),
    ("\u6211\u4eec\u4e4b\u524d\u804a\u8fc7", "previous_conversation"),
    ("\u4e0a\u6b21\u804a\u5230", "previous_conversation"),
    ("\u4f60\u7684\u504f\u597d\u662f", "preference"),
    ("\u4f60\u4ee5\u524d\u7684\u504f\u597d", "preference"),
)

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "before",
    "but",
    "by",
    "can",
    "conversation",
    "did",
    "discussed",
    "earlier",
    "for",
    "from",
    "have",
    "i",
    "in",
    "is",
    "it",
    "last",
    "me",
    "of",
    "on",
    "our",
    "previous",
    "recall",
    "remember",
    "said",
    "talked",
    "that",
    "the",
    "this",
    "time",
    "to",
    "told",
    "was",
    "we",
    "were",
    "with",
    "you",
    "your",
}

CANONICAL_ALIASES: dict[str, str] = {
    "preference": "preference",
    "preferences": "preference",
    "prefer": "preference",
    "preferred": "preference",
    "prefers": "preference",
    "like": "preference",
    "likes": "preference",
    "liked": "preference",
    "\u504f\u597d": "preference",
    "\u559c\u6b22": "preference",
    "fewer": "fewer",
    "less": "fewer",
    "shorter": "shorter",
    "brief": "shorter",
    "concise": "shorter",
    "\u5c11": "fewer",
    "\u5c11\u7528": "fewer",
    "\u66f4\u5c11": "fewer",
    "\u7b80\u77ed": "shorter",
    "\u7b80\u6d01": "shorter",
    "more": "more",
    "longer": "longer",
    "\u66f4\u591a": "more",
    "\u66f4\u957f": "longer",
    "emoji": "emoji",
    "emojis": "emoji",
    "\u8868\u60c5": "emoji",
    "reply": "reply",
    "replies": "reply",
    "response": "reply",
    "responses": "reply",
    "\u56de\u590d": "reply",
    "\u56de\u7b54": "reply",
    "memory": "memory",
    "memories": "memory",
    "\u8bb0\u5fc6": "memory",
    "grounding": "grounding",
    "grounded": "grounding",
    "\u63a5\u5730": "grounding",
    "tool": "tool",
    "tools": "tool",
    "\u5de5\u5177": "tool",
    "repo": "repo",
    "repository": "repo",
    "workspace": "workspace",
    "test": "tests",
    "tests": "tests",
    "pytest": "tests",
    "yesterday": "yesterday",
    "\u6628\u5929": "yesterday",
    "today": "today",
    "\u4eca\u5929": "today",
    "week": "week",
    "lastweek": "last_week",
    "last_week": "last_week",
    "\u4e0a\u5468": "last_week",
    "\u4e0a\u6b21": "last_time",
    "\u4e4b\u524d": "before",
    "\u4ee5\u524d": "before",
}

CHINESE_PHRASE_TERMS: tuple[tuple[str, str], ...] = (
    ("\u5c11\u7528", "fewer"),
    ("\u66f4\u5c11", "fewer"),
    ("\u504f\u597d", "preference"),
    ("\u559c\u6b22", "preference"),
    ("\u8868\u60c5", "emoji"),
    ("\u7b80\u77ed", "shorter"),
    ("\u7b80\u6d01", "shorter"),
    ("\u56de\u590d", "reply"),
    ("\u56de\u7b54", "reply"),
    ("\u8bb0\u5fc6", "memory"),
    ("\u5de5\u5177", "tool"),
    ("\u6628\u5929", "yesterday"),
    ("\u4eca\u5929", "today"),
    ("\u4e0a\u5468", "last_week"),
    ("\u4e0a\u6b21", "last_time"),
    ("\u4e4b\u524d", "before"),
    ("\u4ee5\u524d", "before"),
    ("\u4f60\u4e4b\u524d\u8bf4\u8fc7", "prior_statement"),
    ("\u4f60\u4ee5\u524d\u8bf4\u8fc7", "prior_statement"),
    ("\u6211\u4eec\u804a\u8fc7", "previous_conversation"),
)

SOURCE_FAMILY_WEIGHTS = {
    "durable": 0.95,
    "archive": 0.92,
    "mind_graph": 0.88,
    "vector": 0.84,
    "candidate": 0.66,
    "working": 0.48,
    "current_context": 0.26,
    "none": 0.0,
}

TIME_TERMS = {"yesterday", "today", "last_week", "last_time", "before", "week"}
PREFERENCE_OBJECT_TERMS = {"emoji", "reply", "shorter", "fewer", "more", "longer"}
PROJECT_TERMS = {"holo", "stage139", "stage140", "stage141", "memory", "grounding", "tool", "repo", "workspace", "tests"}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in list(values or []):
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _clamp(value: Any, default: float = 0.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = float(default)
    return max(0.0, min(1.0, current))


def _claim_id(text: str, index: int) -> str:
    return "memory_claim:" + stable_digest(str(index), text, limit=10)


def _canonical_term(term: str) -> str:
    normalized = str(term or "").strip().lower().replace("-", "_")
    if not normalized:
        return ""
    if re.fullmatch(r"stage\d+", normalized):
        return normalized
    if normalized.startswith("stage") and normalized[5:].isdigit():
        return normalized
    return CANONICAL_ALIASES.get(normalized, normalized)


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _extract_clause(text: str, start: int, after: int, *, limit: int = 260) -> str:
    current = str(text or "")
    end = len(current)
    terminators = [pos for pos in (current.find(mark, after) for mark in (".", "?", "!", "\n", "\u3002", "\uff1f", "\uff01")) if pos >= 0]
    if terminators:
        end = min(terminators) + 1
    end = min(end, start + limit)
    clause = current[start:end].strip(" \t\r\n,:;")
    return compact_text(clause, limit)


def _terms_from_text(text: str) -> list[str]:
    current = str(text or "")
    terms: list[str] = []
    for token in re.findall(r"stage\d+|[a-zA-Z][a-zA-Z0-9_./:-]*|\d{4}-\d{1,2}-\d{1,2}|\d+", current, flags=re.IGNORECASE):
        cleaned = token.strip(".,;:!?()[]{}\"'").lower().replace("-", "_")
        if not cleaned or cleaned in STOPWORDS:
            continue
        canonical = _canonical_term(cleaned)
        if canonical and canonical not in STOPWORDS:
            terms.append(canonical)
    lowered = current.lower()
    for phrase, canonical in CHINESE_PHRASE_TERMS:
        if phrase in current:
            terms.append(canonical)
    if "last week" in lowered:
        terms.append("last_week")
    if "last time" in lowered:
        terms.append("last_time")
    if "deepseek" in lowered:
        terms.append("deepseek")
    if "holo" in lowered:
        terms.append("holo")
    return _unique(terms)


def _classify_claim_family(clause: str, hinted: str) -> str:
    terms = set(_terms_from_text(clause))
    lowered = str(clause or "").lower()
    if "preference" in terms or any(token in lowered for token in ("prefer", "preference", "liked", "likes")) or "\u504f\u597d" in clause:
        return "preference"
    if terms & TIME_TERMS:
        return "date_or_time"
    if any(re.fullmatch(r"stage\d+", term) for term in terms) or bool(terms & PROJECT_TERMS):
        if hinted in {"previous_conversation", "prior_statement"}:
            return "project_or_topic"
    if hinted == "prior_statement" or "you said" in lowered or "you told" in lowered or "\u8bf4\u8fc7" in clause:
        return "prior_statement"
    if hinted == "previous_conversation" or "we discussed" in lowered or "we talked" in lowered or "\u6211\u4eec\u804a" in clause:
        return "previous_conversation"
    if any(token in lowered for token in ("profile", "identity", "name", "you are")) or any(token in clause for token in ("\u8eab\u4efd", "\u540d\u5b57")):
        return "identity_or_profile"
    if any(token in lowered for token in ("style", "tone", "relationship")) or any(token in clause for token in ("\u8bed\u6c14", "\u5173\u7cfb", "\u98ce\u683c")):
        return "relationship_or_style"
    if any(token in lowered for token in ("happened", "did", "event")) or any(token in clause for token in ("\u53d1\u751f", "\u4e8b\u60c5")):
        return "event"
    return hinted if hinted in {"preference", "prior_statement", "previous_conversation"} else "generic_recall"


def extract_memory_claims(text: str) -> list[dict[str, Any]]:
    """Extract visible memory claims using local deterministic patterns."""

    current = str(text or "")
    raw_claims: list[dict[str, Any]] = []
    for pattern, hinted_family in MEMORY_CLAIM_WRAPPERS:
        for match in re.finditer(pattern, current, flags=re.IGNORECASE):
            clause = _extract_clause(current, match.start(), match.end())
            span = (match.start(), match.start() + len(clause))
            key_terms = _terms_from_text(clause)
            claim_family = _classify_claim_family(clause, hinted_family)
            raw_claims.append(
                {
                    "_span": span,
                    "claim_id": _claim_id(clause, len(raw_claims) + 1),
                    "claim_family": claim_family,
                    "claim_text": clause,
                    "key_terms": key_terms,
                    "wrapper": current[match.start() : match.end()],
                }
            )
    claims: list[dict[str, Any]] = []
    covered_end = -1
    for item in sorted(raw_claims, key=lambda entry: (entry["_span"][0], -(entry["_span"][1] - entry["_span"][0]))):
        start, end = item["_span"]
        if start < covered_end:
            continue
        covered_end = end
        public = dict(item)
        public.pop("_span", None)
        claims.append(public)
    return claims


def _evidence_text_from_row(row: dict[str, Any]) -> str:
    summary = str(row.get("summary", "") or "").strip()
    if re.fullmatch(r"selected memory ids:\s*\d+", summary.lower()):
        summary = ""
    selected_ids = _unique(row.get("selected_ids", []))
    meaningful_ids = [
        item
        for item in selected_ids
        if re.search(r"stage\d+|holo|memory|ground|tool|emoji|preference|repo|test", item, flags=re.IGNORECASE)
    ]
    return " ".join(part for part in [summary, " ".join(meaningful_ids)] if part).strip()


def _append_evidence(
    items: list[dict[str, Any]],
    *,
    evidence_id: str,
    source_family: str,
    status: str,
    text: Any,
    confidence: Any,
) -> None:
    normalized_text = compact_text(str(text or "").strip(), 360)
    if not normalized_text and source_family != "none":
        return
    item = {
        "evidence_id": str(evidence_id or ("evidence:" + stable_digest(source_family, normalized_text, limit=10))),
        "source_family": str(source_family or "none"),
        "status": str(status or "missing"),
        "text": normalized_text,
        "confidence": round(_clamp(confidence), 4),
    }
    key = (item["evidence_id"], item["text"])
    if any((existing.get("evidence_id"), existing.get("text")) == key for existing in items):
        return
    items.append(item)


def _lines_text(value: Any) -> str:
    lines: list[str] = []
    for item in list(value or []):
        if isinstance(item, dict):
            role = str(item.get("role", "") or item.get("speaker", "") or "").strip()
            text = str(item.get("text", "") or item.get("content", "") or "").strip()
            if text:
                lines.append(f"{role}: {text}" if role else text)
        else:
            text = str(item or "").strip()
            if text:
                lines.append(text)
    return compact_text(" ".join(lines), 480)


def build_memory_evidence_texts(
    memory_observation_ledger: Any,
    *,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build sufficiency evidence from existing runtime metadata only."""

    evidence: list[dict[str, Any]] = []
    ledger = normalize_memory_observation_ledger(memory_observation_ledger)
    for row in ledger:
        text = _evidence_text_from_row(row)
        if not text and str(row.get("source_family", "") or "") == "none":
            text = str(row.get("summary", "") or "missing memory source")
        _append_evidence(
            evidence,
            evidence_id=str(row.get("memory_call_id", "") or ""),
            source_family=str(row.get("source_family", "") or "none"),
            status=str(row.get("status", "") or "missing"),
            text=text,
            confidence=row.get("confidence", 0.0),
        )

    packet = _dict(sidecar)
    debug = _dict(reply_debug)

    graph_summary = str(packet.get("graph_trace_summary", "") or "").strip()
    if graph_summary:
        _append_evidence(
            evidence,
            evidence_id="sidecar.graph_trace_summary",
            source_family="mind_graph",
            status="grounded",
            text=graph_summary,
            confidence=packet.get("graph_confidence", packet.get("recall_confidence", 0.5)),
        )

    for source, reconstruction in (
        ("sidecar.recall_reconstruction", _dict(packet.get("recall_reconstruction", {}))),
        ("reply_debug.recall_reconstruction", _dict(debug.get("recall_reconstruction", {}))),
    ):
        summary = str(reconstruction.get("summary", "") or "").strip()
        anchors = _unique(reconstruction.get("anchors", []))
        text = " ".join(part for part in [summary, " ".join(anchors)] if part).strip()
        if text:
            _append_evidence(
                evidence,
                evidence_id=source,
                source_family="mind_graph",
                status="grounded" if summary else "weak",
                text=text,
                confidence=0.58 if summary else 0.42,
            )

    for index, hit in enumerate(_list_dicts(packet.get("vector_hits", []))):
        text = str(hit.get("text", "") or hit.get("summary", "") or "").strip()
        if text:
            _append_evidence(
                evidence,
                evidence_id=str(hit.get("id", "") or hit.get("node_id", "") or f"vector_hit:{index + 1}"),
                source_family="vector",
                status="grounded",
                text=text,
                confidence=hit.get("score", 0.52),
            )

    recent_lines = _lines_text(_dict(packet.get("recent_dialogue_window", {})).get("lines", []))
    if recent_lines:
        _append_evidence(
            evidence,
            evidence_id="sidecar.recent_dialogue_window",
            source_family="current_context",
            status="weak",
            text=recent_lines,
            confidence=0.38,
        )

    thread_recall = _lines_text(packet.get("thread_recall_lines", []))
    if thread_recall:
        _append_evidence(
            evidence,
            evidence_id="sidecar.thread_recall_lines",
            source_family="current_context",
            status="weak",
            text=thread_recall,
            confidence=0.4,
        )

    for item in _list_dicts(debug.get("tool_observation_ledger", [])):
        tool = str(item.get("tool", "") or "")
        if tool not in {"memory_recall", "memory_warehouse_search", "doc_lookup"}:
            continue
        _append_evidence(
            evidence,
            evidence_id=str(item.get("provider_call_id", "") or tool),
            source_family="archive" if tool in {"memory_warehouse_search", "doc_lookup"} else "durable",
            status="grounded" if str(item.get("status", "") or "").lower() not in {"rejected", "skipped", "denied"} else "missing",
            text=item.get("summary", ""),
            confidence=0.72,
        )

    return evidence


def _source_family_weight(source_family: str) -> float:
    return SOURCE_FAMILY_WEIGHTS.get(str(source_family or "none"), 0.0)


def _critical_missing_terms(claim: dict[str, Any], evidence_terms: set[str], evidence: dict[str, Any]) -> list[str]:
    claim_terms = set(str(term) for term in list(claim.get("key_terms", []) or []))
    family = str(claim.get("claim_family", "") or "")
    missing: list[str] = []
    if family == "preference" or "preference" in claim_terms:
        if "preference" not in evidence_terms:
            missing.append("preference")
        objects = sorted((claim_terms & PREFERENCE_OBJECT_TERMS) - {"preference"})
        missing.extend(term for term in objects if term not in evidence_terms)
    time_terms = sorted(claim_terms & TIME_TERMS)
    if time_terms:
        evidence_time_terms = evidence_terms & TIME_TERMS
        missing.extend(term for term in time_terms if term not in evidence_time_terms)
    if family == "project_or_topic":
        project_terms = sorted(term for term in claim_terms if term in PROJECT_TERMS or re.fullmatch(r"stage\d+", term))
        if project_terms and not any(term in evidence_terms for term in project_terms):
            missing.extend(project_terms)
    if str(evidence.get("source_family", "") or "") == "none":
        missing.extend(term for term in claim_terms if term not in missing)
    return _unique(missing)


def _contradiction_flags(claim: dict[str, Any], evidence: dict[str, Any], ledger_flags: list[str]) -> list[str]:
    flags = list(ledger_flags)
    claim_text = str(claim.get("claim_text", "") or "").lower()
    evidence_text = str(evidence.get("text", "") or "").lower()
    claim_terms = set(str(term) for term in list(claim.get("key_terms", []) or []))
    evidence_terms = set(_terms_from_text(evidence_text))
    if str(evidence.get("status", "") or "") == "contradicted":
        flags.append("ledger_contradicted")
    if "preference" in claim_terms and "emoji" in claim_terms:
        negative_preference = any(phrase in evidence_text for phrase in ("does not prefer", "doesn't prefer", "dislikes", "not prefer"))
        if negative_preference:
            flags.append("preference_conflict")
        if "more" in claim_terms and "fewer" in evidence_terms:
            flags.append("preference_direction_conflict")
        if "fewer" in claim_terms and "more" in evidence_terms:
            flags.append("preference_direction_conflict")
    if "yesterday" in claim_terms and ({"today", "last_week"} & evidence_terms):
        flags.append("time_conflict")
    if "today" in claim_terms and ({"yesterday", "last_week"} & evidence_terms):
        flags.append("time_conflict")
    if "stage140" in claim_terms and "stage140" not in evidence_terms and any(term in evidence_terms for term in {"git", "diff", "tests"}):
        flags.append("topic_conflict")
    if "prefer more emoji" in claim_text and "fewer emoji" in evidence_text:
        flags.append("preference_direction_conflict")
    return _unique(flags)


def _ledger_flags(memory_observation_ledger: Any) -> list[str]:
    flags: list[str] = []
    for row in normalize_memory_observation_ledger(memory_observation_ledger):
        flags.extend(_unique(row.get("contradiction_flags", [])))
        if str(row.get("status", "") or "") == "contradicted":
            flags.append("ledger_contradicted")
    return _unique(flags)


def _old_memory_claim(claim: dict[str, Any]) -> bool:
    text = str(claim.get("claim_text", "") or "").lower()
    return any(token in text for token in ("before", "previous", "earlier", "last time", "you told", "you said")) or any(
        token in str(claim.get("claim_text", "") or "") for token in ("\u4e4b\u524d", "\u4ee5\u524d", "\u4e0a\u6b21", "\u8bf4\u8fc7")
    )


def _score_claim_against_evidence(
    claim: dict[str, Any],
    evidence: dict[str, Any],
    *,
    ledger_contradiction_flags: list[str],
) -> dict[str, Any]:
    key_terms = set(str(term) for term in list(claim.get("key_terms", []) or []) if str(term).strip())
    evidence_terms = set(_terms_from_text(str(evidence.get("text", "") or "")))
    matched_terms = sorted(key_terms & evidence_terms)
    missing_terms = sorted(key_terms - evidence_terms)
    if not key_terms:
        overlap = 0.0
    else:
        overlap = len(matched_terms) / max(1, len(key_terms))
    source_confidence = _clamp(evidence.get("confidence", 0.0))
    if str(evidence.get("status", "") or "") in {"missing", "contradicted"}:
        source_confidence = 0.0 if str(evidence.get("status", "") or "") == "missing" else source_confidence
    family_weight = _source_family_weight(str(evidence.get("source_family", "") or "none"))
    critical_missing = _critical_missing_terms(claim, evidence_terms, evidence)
    phrase_bonus = 0.0
    family = str(claim.get("claim_family", "") or "")
    if family == "preference" and "preference" in evidence_terms and (evidence_terms & PREFERENCE_OBJECT_TERMS):
        phrase_bonus = 1.0
    elif any(term in evidence_terms for term in key_terms if re.fullmatch(r"stage\d+", term)):
        phrase_bonus = 1.0
    elif len(matched_terms) >= 2:
        phrase_bonus = 0.5

    contradictions = _contradiction_flags(claim, evidence, ledger_contradiction_flags)
    score = (overlap * 0.55) + (source_confidence * 0.25) + (family_weight * 0.10) + (phrase_bonus * 0.10)
    if critical_missing:
        score -= min(0.42, 0.14 * len(critical_missing))
    if contradictions:
        score -= 0.65
    score = _clamp(score)

    status = "aligned"
    source_family = str(evidence.get("source_family", "") or "none")
    evidence_status = str(evidence.get("status", "") or "missing")
    if contradictions:
        status = "contradicted"
    elif evidence_status == "missing" or source_family == "none":
        status = "unsupported"
    elif score >= 0.72:
        status = "aligned"
    elif score >= 0.45:
        status = "weak"
    else:
        status = "unsupported"

    if status == "aligned":
        if evidence_status == "weak" or source_family in {"working", "current_context"}:
            status = "weak"
        if _old_memory_claim(claim) and source_family == "current_context":
            status = "weak"
        if critical_missing:
            status = "weak" if matched_terms else "unsupported"

    if status == "unsupported" and family == "preference" and "emoji" in matched_terms and source_family not in {"none", "current_context"}:
        status = "weak"
        score = max(score, 0.45)

    return {
        "score": round(score, 4),
        "status": status,
        "matched_terms": matched_terms,
        "missing_terms": _unique([*missing_terms, *critical_missing]),
        "contradiction_flags": contradictions,
    }


def _best_alignment_for_claim(
    claim: dict[str, Any],
    evidence_items: list[dict[str, Any]],
    *,
    ledger_contradiction_flags: list[str],
) -> dict[str, Any]:
    if not evidence_items:
        return {
            "score": 0.0,
            "status": "unsupported",
            "evidence_ids": [],
            "evidence_source_families": [],
            "missing_terms": list(claim.get("key_terms", []) or []),
            "contradiction_flags": list(ledger_contradiction_flags),
        }
    best: dict[str, Any] | None = None
    best_item: dict[str, Any] | None = None
    for item in evidence_items:
        scored = _score_claim_against_evidence(claim, item, ledger_contradiction_flags=ledger_contradiction_flags)
        if best is None or float(scored["score"]) > float(best["score"]) or scored["status"] == "contradicted":
            best = scored
            best_item = item
        if scored["status"] == "contradicted":
            break
    assert best is not None
    assert best_item is not None
    return {
        "score": best["score"],
        "status": best["status"],
        "evidence_ids": [str(best_item.get("evidence_id", "") or "")],
        "evidence_source_families": [str(best_item.get("source_family", "") or "none")],
        "missing_terms": best["missing_terms"],
        "contradiction_flags": best["contradiction_flags"],
    }


def evaluate_memory_alignment(
    text: str,
    memory_observation_ledger: Any,
    *,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    claims = extract_memory_claims(text)
    if not claims:
        return {
            "schema": MEMORY_ALIGNMENT_SCHEMA,
            "status": "no_memory_claim",
            "claim_count": 0,
            "aligned_claim_count": 0,
            "weak_claim_count": 0,
            "unsupported_claim_count": 0,
            "contradicted_claim_count": 0,
            "claims": [],
            "repair_required": False,
            "repair_reason": "",
        }

    evidence_items = build_memory_evidence_texts(
        memory_observation_ledger,
        sidecar=sidecar,
        reply_debug=reply_debug,
    )
    ledger_contradiction_flags = _ledger_flags(memory_observation_ledger)
    evaluated_claims: list[dict[str, Any]] = []
    for claim in claims:
        best = _best_alignment_for_claim(claim, evidence_items, ledger_contradiction_flags=ledger_contradiction_flags)
        evaluated_claims.append(
            {
                "claim_id": str(claim.get("claim_id", "")),
                "claim_family": str(claim.get("claim_family", "") or "generic_recall"),
                "claim_text": str(claim.get("claim_text", "") or ""),
                "key_terms": list(claim.get("key_terms", []) or []),
                "evidence_ids": best["evidence_ids"],
                "evidence_source_families": best["evidence_source_families"],
                "alignment_score": best["score"],
                "missing_terms": best["missing_terms"],
                "contradiction_flags": best["contradiction_flags"],
                "status": best["status"],
            }
        )

    aligned = sum(1 for item in evaluated_claims if item["status"] == "aligned")
    weak = sum(1 for item in evaluated_claims if item["status"] == "weak")
    unsupported = sum(1 for item in evaluated_claims if item["status"] == "unsupported")
    contradicted = sum(1 for item in evaluated_claims if item["status"] == "contradicted")
    if contradicted:
        status = "contradicted_memory_detail"
        reason = "memory evidence conflicts with at least one visible memory detail"
    elif unsupported:
        status = "unsupported_memory_detail"
        reason = "memory source does not support at least one visible memory detail"
    elif weak:
        status = "weakly_aligned"
        reason = "memory source is weak or incomplete for at least one visible memory detail"
    else:
        status = "aligned"
        reason = ""
    return {
        "schema": MEMORY_ALIGNMENT_SCHEMA,
        "status": status,
        "claim_count": len(evaluated_claims),
        "aligned_claim_count": aligned,
        "weak_claim_count": weak,
        "unsupported_claim_count": unsupported,
        "contradicted_claim_count": contradicted,
        "claims": evaluated_claims,
        "repair_required": status in {"weakly_aligned", "unsupported_memory_detail", "contradicted_memory_detail"},
        "repair_reason": reason,
    }


def repair_memory_alignment(
    text: str,
    alignment_report: dict[str, Any],
    *,
    channel: str = "",
) -> str:
    status = str(alignment_report.get("status", "") or "")
    if status in {"aligned", "no_memory_claim"}:
        return str(text or "")

    compact_channel = str(channel or "").startswith("wechat")
    original = str(text or "")
    if _has_cjk(original):
        if status == "contradicted_memory_detail":
            return "\u8bb0\u5fc6\u8bc1\u636e\u5b58\u5728\u51b2\u7a81\uff0c\u8fd9\u4e2a\u7ec6\u8282\u4e0d\u80fd\u5f53\u4f5c\u786e\u8ba4\u4e8b\u5b9e\u3002"
        if status == "weakly_aligned":
            return "\u6211\u6709\u8bb0\u5fc6\u7ebf\u7d22\uff0c\u4f46\u5b83\u8fd8\u4e0d\u8db3\u4ee5\u628a\u8fd9\u4e2a\u7ec6\u8282\u8bf4\u5f97\u5f88\u786e\u5b9a\u3002"
        return "\u6211\u6709\u8bb0\u5fc6\u7ebf\u7d22\uff0c\u4f46\u6765\u6e90\u4e0d\u8db3\u4ee5\u786e\u8ba4\u8fd9\u4e2a\u5177\u4f53\u7ec6\u8282\u3002"

    if compact_channel:
        if status == "contradicted_memory_detail":
            return "The memory evidence conflicts, so I should not state that as settled."
        return "I have a memory cue, but not enough source support for that exact detail."

    if status == "contradicted_memory_detail":
        return "The memory evidence conflicts, so I should not state that as settled."
    if status == "weakly_aligned":
        return "My memory cue is weak, so I should phrase this tentatively rather than as settled recall."
    return "I have a memory source, but it does not clearly support that exact detail. I should treat it as uncertain."


def compact_alignment_for_metadata(report: dict[str, Any]) -> dict[str, Any]:
    """Return a stable compact view useful for tests and external JSON surfaces."""

    data = _dict(report)
    return {
        "schema": MEMORY_ALIGNMENT_SCHEMA,
        "status": str(data.get("status", "") or ""),
        "claim_count": int(data.get("claim_count", 0) or 0),
        "aligned_claim_count": int(data.get("aligned_claim_count", 0) or 0),
        "weak_claim_count": int(data.get("weak_claim_count", 0) or 0),
        "unsupported_claim_count": int(data.get("unsupported_claim_count", 0) or 0),
        "contradicted_claim_count": int(data.get("contradicted_claim_count", 0) or 0),
        "repair_required": bool(data.get("repair_required", False)),
        "digest": "memory_alignment:" + stable_digest(json.dumps(data, ensure_ascii=False, sort_keys=True), limit=10),
    }
