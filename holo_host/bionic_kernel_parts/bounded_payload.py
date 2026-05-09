from __future__ import annotations

import math
from typing import Any

from ..common import compact_text


BOUNDED_CANDIDATE_KEYS = (
    "action_type",
    "score",
    "reason",
    "why_now",
    "send_allowed",
    "stage28_delta",
    "stage28_rationale",
    "scene_delta",
    "scene_rationale",
    "policy_scenario_bucket",
    "goal_alignment_score",
    "identity_consistency_score",
    "selection_adjustment",
    "original_top_action",
)
BOUNDED_PREDICTION_KEYS = (
    "predicted_risk",
    "predicted_regret",
    "confidence",
)


def clip_list(values: Any, *, limit: int = 8) -> list[Any]:
    if not isinstance(values, list):
        return []
    return values[: max(0, int(limit))]


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def compact(value: Any, *, limit: int = 320) -> str:
    return compact_text(str(value or ""), limit=limit)


def safe_float(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def bounded_value(
    value: Any,
    *,
    depth: int = 2,
    str_limit: int = 360,
    list_limit: int = 12,
    dict_limit: int = 32,
) -> Any:
    if isinstance(value, str):
        return compact(value, limit=str_limit)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else 0.0
    if depth <= 0:
        return compact(value, limit=str_limit)
    if isinstance(value, dict):
        bounded: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= dict_limit:
                bounded["_truncated_keys"] = max(0, len(value) - dict_limit)
                break
            bounded[compact(key, limit=96)] = bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
        return bounded
    if isinstance(value, (list, tuple)):
        return [
            bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in value[:list_limit]
        ]
    if isinstance(value, set):
        return [
            bounded_value(
                item,
                depth=depth - 1,
                str_limit=str_limit,
                list_limit=list_limit,
                dict_limit=dict_limit,
            )
            for item in sorted(value, key=lambda item: str(item))[:list_limit]
        ]
    return compact(value, limit=str_limit)


def bounded_dict(value: Any, *, depth: int = 2) -> dict[str, Any]:
    bounded = bounded_value(value, depth=depth)
    return bounded if isinstance(bounded, dict) else {}


def bounded_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    bounded: dict[str, Any] = {}
    for key in BOUNDED_CANDIDATE_KEYS:
        if key not in candidate:
            continue
        value = candidate.get(key)
        if isinstance(value, str):
            bounded[key] = compact(value, limit=220)
        else:
            bounded[key] = value
    bounded["action_type"] = str(bounded.get("action_type", "") or "reply_once")
    bounded["score"] = safe_float(bounded.get("score", 0.0))
    grounding_order = candidate.get("stage28_grounding_order", [])
    if isinstance(grounding_order, list):
        bounded["stage28_grounding_order"] = [str(item)[:80] for item in grounding_order[:6]]
    prediction = candidate.get("predicted_outcome", {})
    if isinstance(prediction, dict):
        bounded_prediction = {
            key: prediction.get(key)
            for key in BOUNDED_PREDICTION_KEYS
            if key in prediction
        }
        if bounded_prediction:
            bounded["predicted_outcome"] = bounded_prediction
    return bounded
