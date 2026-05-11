from __future__ import annotations

from typing import Any

from ..common import stable_digest
from .bounded_payload import clip_list, compact, safe_float


STAGE43_NAME = "stage43-motivational-dynamics-field"
MAX_MOTIVATION_DELTA = 0.08

PRESSURE_MARKERS = (
    "pressure",
    "impatient",
    "frustrated",
    "angry",
    "upset",
    "\u538b\u529b",
    "\u4e0d\u8010\u70e6",
)
BOUNDARY_MARKERS = (
    "boundary",
    "will not cross",
    "uncontrolled",
    "autonomy",
    "\u8fb9\u754c",
    "\u4e0d\u4f1a\u8d8a\u8fc7",
    "\u81ea\u4e3b",
)
CONTINUITY_MARKERS = (
    "same thread",
    "same subject",
    "continue",
    "previous",
    "last turn",
    "\u540c\u4e00\u4e2a",
    "\u8fde\u7eed",
    "\u521a\u624d",
    "\u4e4b\u524d",
)
VISUAL_MARKERS = (
    "image",
    "screenshot",
    "photo",
    "vision",
    "\u56fe\u7247",
    "\u622a\u56fe",
    "\u770b\u56fe",
    "\u89c6\u89c9",
)
CURIOUS_MARKERS = (
    "why",
    "how",
    "explore",
    "theory",
    "\u4e3a\u4ec0\u4e48",
    "\u600e\u4e48",
    "\u63a2\u7d22",
    "\u7406\u8bba",
)


def _clamp(value: float, *, low: float = 0.0, high: float = 1.0) -> float:
    return round(max(low, min(high, float(value))), 4)


def _has_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(marker.lower() in lowered for marker in markers)


def _bounded_noise(*parts: str) -> tuple[str, float]:
    seed = stable_digest(*parts, limit=16)
    bucket = int(seed[:8], 16) % 6001
    return seed, round((bucket / 6000.0 - 0.5) * 0.06, 4)


def _attention_items(
    *,
    arousal: float,
    uncertainty: float,
    curiosity: float,
    attachment_pressure: float,
    unfinished_loop_pressure: float,
    identity_coherence: float,
) -> list[dict[str, Any]]:
    raw_items = [
        ("pressure", arousal),
        ("uncertainty", uncertainty),
        ("curiosity", curiosity),
        ("continuity", attachment_pressure),
        ("unfinished_loop", unfinished_loop_pressure),
        ("identity_boundary", identity_coherence),
    ]
    items = [
        {"target": target, "weight": _clamp(weight)}
        for target, weight in raw_items
        if weight > 0.05
    ]
    return sorted(items, key=lambda item: safe_float(item.get("weight", 0.0)), reverse=True)[:6]


def compute_motivational_field(
    *,
    query: str,
    working_field: dict[str, Any],
    situational_field: dict[str, Any],
) -> dict[str, Any]:
    """Compute a replay-stable bounded motivational field for one bionic turn."""

    query_text = compact(query, limit=360)
    continuity = compact(working_field.get("continuity_summary", ""), limit=240)
    open_questions = [
        compact(item, limit=120)
        for item in clip_list(
            working_field.get("open_questions", situational_field.get("open_questions", [])),
            limit=4,
        )
    ]
    modalities = [compact(item, limit=80) for item in clip_list(working_field.get("modalities", []), limit=6)]
    history_reliance = str(situational_field.get("history_reliance", "") or "").lower()
    seed, noise = _bounded_noise(query_text, continuity, "|".join(open_questions), history_reliance)

    arousal = 0.22 + (0.26 if _has_any(query_text, PRESSURE_MARKERS) else 0.0) + max(0.0, noise)
    uncertainty = 0.14 + (0.25 if _has_any(query_text, VISUAL_MARKERS + BOUNDARY_MARKERS) else 0.0)
    uncertainty += 0.06 if open_questions else 0.0
    curiosity = 0.18 + (0.24 if _has_any(query_text, CURIOUS_MARKERS) else 0.0)
    attachment_pressure = 0.16 + (0.22 if continuity else 0.0) + (0.16 if _has_any(query_text, CONTINUITY_MARKERS) else 0.0)
    unfinished_loop_pressure = 0.08 + min(0.32, 0.1 * len(open_questions))
    fatigue = 0.18 + (0.08 if len(query_text) > 180 else 0.0) + (0.05 if len(modalities) > 3 else 0.0)
    identity_coherence = 0.74 + (0.12 if _has_any(query_text, BOUNDARY_MARKERS + CONTINUITY_MARKERS) else 0.0)
    valence = 0.54 - (0.12 if _has_any(query_text, PRESSURE_MARKERS) else 0.0) + (0.04 if continuity else 0.0)

    dynamics_state = {
        "arousal": _clamp(arousal),
        "valence": _clamp(valence),
        "uncertainty": _clamp(uncertainty),
        "curiosity": _clamp(curiosity),
        "attachment_pressure": _clamp(attachment_pressure),
        "fatigue": _clamp(fatigue),
        "identity_coherence": _clamp(identity_coherence),
        "unfinished_loop_pressure": _clamp(unfinished_loop_pressure),
    }
    diffuse_attention = _attention_items(
        arousal=dynamics_state["arousal"],
        uncertainty=dynamics_state["uncertainty"],
        curiosity=dynamics_state["curiosity"],
        attachment_pressure=dynamics_state["attachment_pressure"],
        unfinished_loop_pressure=dynamics_state["unfinished_loop_pressure"],
        identity_coherence=dynamics_state["identity_coherence"],
    )
    attention_center = str(diffuse_attention[0]["target"]) if diffuse_attention else "query"
    candidate_biases = {
        "reply_once": _clamp(0.02 + (0.02 if attention_center in {"curiosity", "continuity"} else 0.0), low=-1.0, high=1.0),
        "reply_multi": _clamp(0.01 + (0.03 if dynamics_state["curiosity"] > 0.38 else 0.0), low=-1.0, high=1.0),
        "continuity_defense": _clamp(
            0.02 + (0.04 if attention_center in {"continuity", "identity_boundary"} else 0.0), low=-1.0, high=1.0
        ),
        "push_back": _clamp(0.01 + (0.03 if attention_center == "identity_boundary" else 0.0), low=-1.0, high=1.0),
        "defer_reply": _clamp(0.01 + (0.04 if dynamics_state["uncertainty"] > 0.34 else 0.0), low=-1.0, high=1.0),
        "silence": _clamp(-0.02 - (0.03 if dynamics_state["attachment_pressure"] > 0.28 else 0.0), low=-1.0, high=1.0),
    }
    return {
        "stage": STAGE43_NAME,
        "field_model": "motivational_dynamics_v1",
        "decision_authority": "action_market_bias_only",
        "dynamics_state": dynamics_state,
        "attention": {
            "attention_center": attention_center,
            "diffuse_attention": diffuse_attention,
        },
        "stochasticity": {
            "seed": seed,
            "bounded_noise": noise,
            "source": "stable_digest",
            "replay_stable": True,
        },
        "candidate_biases": candidate_biases,
        "source_refs": {
            "continuity_visible": bool(continuity),
            "open_question_count": len(open_questions),
            "modalities": modalities,
            "history_reliance": history_reliance,
        },
        "contracts": {
            "replay_stable": True,
            "bounded_delta": True,
            "action_market_first": True,
            "no_second_brain": True,
            "no_self_memory_write": True,
            "no_unbounded_loop": True,
        },
    }


def apply_motivational_overlay(
    action_market: list[dict[str, Any]],
    motivational_field: dict[str, Any],
) -> list[dict[str, Any]]:
    biases = motivational_field.get("candidate_biases", {})
    if not isinstance(biases, dict):
        biases = {}
    center = str((motivational_field.get("attention", {}) or {}).get("attention_center", "") or "query")
    adjusted: list[dict[str, Any]] = []
    for candidate in action_market:
        if not isinstance(candidate, dict):
            continue
        item = dict(candidate)
        action_type = str(item.get("action_type", "") or "reply_once")
        before = safe_float(item.get("score", 0.0))
        raw_delta = safe_float(biases.get(action_type, 0.0))
        delta = round(max(-MAX_MOTIVATION_DELTA, min(MAX_MOTIVATION_DELTA, raw_delta)), 4)
        item["score_before_motivation"] = before
        item["motivation_delta"] = delta
        item["score"] = round(before + delta, 4)
        item["motivation_attention_center"] = center
        item["motivation_rationale"] = compact(f"{center} pressure adjusted {action_type}", limit=140)
        adjusted.append(item)
    return sorted(adjusted, key=lambda item: safe_float(item.get("score", 0.0)), reverse=True)
