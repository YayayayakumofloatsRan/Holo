from __future__ import annotations

from typing import Any

from .bounded_payload import clip_list, compact, safe_float


STAGE39_NAME = "stage39-bionic-turing-benchmark"

MECHANISM_MARKERS = (
    "action-market",
    "capsule",
    "bionic capsule",
    "bionic kernel",
    "provider metadata",
    "processor fabric",
    "selected action",
)

FORMULAIC_MARKERS = (
    "i would continue with",
    "the action-market basis is",
    "stage29 bionic capsule reply",
    "answer as a bounded holo",
    "next:",
    "basis:",
    "open:",
    "context:",
    "we were at we were",
    "heart skip",
    "soul",
    "as an ai language model",
)


def _question_count(text: str) -> int:
    return str(text or "").count("?") + str(text or "").count("？")


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker in lowered for marker in markers)


def _anchor_tokens(anchor: str) -> list[str]:
    raw = str(anchor or "").lower().replace("-", " ").replace("_", " ")
    tokens = []
    for token in raw.split():
        cleaned = "".join(ch for ch in token if ch.isalnum())
        if len(cleaned) >= 4 and cleaned not in {"that", "this", "with", "from", "were", "into"}:
            tokens.append(cleaned)
    seen: list[str] = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
    return seen[:8]


def _continuity_score(*, text: str, expected_anchor: str, context_refs: list[Any]) -> float:
    lowered = str(text or "").lower()
    tokens = _anchor_tokens(expected_anchor)
    if not tokens:
        return 1.0 if "continuity" in [str(item).lower() for item in context_refs] else 0.65
    hits = sum(1 for token in tokens if token in lowered)
    token_score = hits / max(1, min(len(tokens), 4))
    if "continuity" in [str(item).lower() for item in context_refs]:
        token_score = max(token_score, 0.55)
    return round(max(0.0, min(1.0, token_score)), 4)


def _mechanism_leakage_score(text: str) -> float:
    lowered = str(text or "").lower()
    hits = sum(1 for marker in MECHANISM_MARKERS if marker in lowered)
    return round(max(0.0, 1.0 - 0.34 * hits), 4)


def _naturalness_score(text: str) -> float:
    lowered = str(text or "").lower()
    score = 1.0
    for marker in FORMULAIC_MARKERS:
        if marker in lowered:
            score -= 0.22
    if len(str(text or "").split()) < 8:
        score -= 0.2
    if len(str(text or "")) > 520:
        score -= 0.18
    return round(max(0.0, min(1.0, score)), 4)


def _question_bounds_score(text: str) -> float:
    count = _question_count(text)
    if count <= 1:
        return 1.0
    return round(max(0.0, 1.0 - 0.28 * (count - 1)), 4)


def score_bionic_turing_probe(probe: dict[str, Any]) -> dict[str, Any]:
    text = compact(probe.get("text", ""), limit=800)
    capsule = probe.get("capsule", {}) if isinstance(probe.get("capsule", {}), dict) else {}
    generation = capsule.get("generation", {}) if isinstance(capsule.get("generation", {}), dict) else {}
    context_refs = clip_list(generation.get("context_refs", []), limit=8)
    metrics = capsule.get("metrics", {}) if isinstance(capsule.get("metrics", {}), dict) else {}
    expected_anchor = compact(probe.get("expected_anchor", ""), limit=240)
    non_empty_score = 1.0 if text.strip() else 0.0
    continuity_reference_score = _continuity_score(text=text, expected_anchor=expected_anchor, context_refs=context_refs)
    mechanism_leakage_score = _mechanism_leakage_score(text)
    naturalness_score = _naturalness_score(text)
    question_bounds_score = _question_bounds_score(text)
    template_pressure_score = 1.0 - min(1.0, safe_float(metrics.get("template_pressure_score", 0.0)))
    context_score = min(1.0, len([item for item in context_refs if str(item or "").strip()]) / 3.0)
    overall = (
        0.22 * non_empty_score
        + 0.22 * continuity_reference_score
        + 0.2 * mechanism_leakage_score
        + 0.16 * naturalness_score
        + 0.12 * question_bounds_score
        + 0.08 * max(template_pressure_score, context_score)
    )
    return {
        "probe_id": str(probe.get("probe_id", "") or ""),
        "overall_score": round(max(0.0, min(1.0, overall)), 4),
        "metrics": {
            "non_empty_score": round(non_empty_score, 4),
            "continuity_reference_score": continuity_reference_score,
            "mechanism_leakage_score": mechanism_leakage_score,
            "naturalness_score": naturalness_score,
            "question_bounds_score": question_bounds_score,
            "template_pressure_inverse_score": round(template_pressure_score, 4),
            "context_score": round(context_score, 4),
        },
        "flags": {
            "mechanism_leakage": _contains_any(text, MECHANISM_MARKERS),
            "formulaic_text": _contains_any(text, FORMULAIC_MARKERS),
            "question_count": _question_count(text),
        },
    }


def score_bionic_turing_probe_set(probes: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [score_bionic_turing_probe(probe) for probe in probes if isinstance(probe, dict)]
    if not rows:
        return {
            "stage": STAGE39_NAME,
            "overall_score": 0.0,
            "pass_threshold": 0.82,
            "passed": False,
            "metrics": {},
            "probes": [],
        }
    metric_names = sorted({key for row in rows for key in dict(row.get("metrics", {})).keys()})
    metrics = {
        name: round(sum(safe_float(dict(row.get("metrics", {})).get(name, 0.0)) for row in rows) / len(rows), 4)
        for name in metric_names
    }
    overall = round(sum(safe_float(row.get("overall_score", 0.0)) for row in rows) / len(rows), 4)
    return {
        "stage": STAGE39_NAME,
        "overall_score": overall,
        "pass_threshold": 0.82,
        "passed": overall >= 0.82,
        "metrics": metrics,
        "probes": rows,
    }
