from __future__ import annotations

import re
from typing import Any

from .common import stable_digest, utc_now

INTENT_FRAME_SCHEMA = "holo.stage160r.intent_frame.v1"

MEMORY_RE = re.compile(
    r"(remember|recall|memory|\u56de\u5fc6|\u8bb0\u5f97|\u8bb0\u5fc6|\u4e0a\u6b21|\u4e0a\u56de|\u4e0a\u4e00\u8f6e|\u521a\u624d|\u4e4b\u524d|\u4ee5\u524d|\u6211\u4eec\u804a\u8fc7)",
    re.IGNORECASE,
)
FOLLOWUP_RE = re.compile(
    r"^(?:\s*(?:\u8fd8\u6709\u5462|\u7ee7\u7eed|\u7136\u540e\u5462)(?:\?|\uff1f)?\s*|\s*(?:\?|\uff1f|\?\?|\uff1f\uff1f)\s*)$"
)
WEB_RE = re.compile(
    r"(search|look up|latest|current|official|homepage|docs|documentation|\u8054\u7f51|\u641c\u7d22|\u641c\u4e00\u4e0b|\u67e5\u4e00\u4e0b|\u67e5\u4e00\u67e5|\u6700\u65b0|\u5b98\u65b9|\u5b98\u7f51|\u4e3b\u9875)",
    re.IGNORECASE,
)
ENGINEERING_RE = re.compile(r"(file|test|patch|git|repo|workspace|pytest|\u6587\u4ef6|\u6d4b\u8bd5|\u4ed3\u5e93|\u76ee\u5f55)")
PROJECT_RE = re.compile(r"(stage\s*\d+|project status|completion|roadmap|\u9879\u76ee|\u72b6\u6001|\u5b8c\u6210)")


def _previous_goal(previous_goal_state: Any) -> dict[str, Any]:
    return dict(previous_goal_state) if isinstance(previous_goal_state, dict) else {}


def _goal_id(text: str, inherited: str = "") -> str:
    if inherited:
        return inherited
    return "goal:" + stable_digest(text, utc_now(), limit=12)


def _required_for_intent(intent_type: str, previous: dict[str, Any]) -> tuple[list[str], list[str]]:
    if intent_type == "memory_recall":
        return ["memory_recall"], ["memory_observation_ledger"]
    if intent_type == "web_lookup":
        return ["web_search"], ["web_observation_ledger"]
    if intent_type == "engineering_task":
        return ["engineering_hint"], ["engineering_action_ledger"]
    if intent_type == "project_state":
        return ["answer_direct"], ["project_state_graph"]
    if intent_type == "followup":
        actions = [str(item) for item in list(previous.get("last_required_actions", []) or []) if str(item).strip()]
        observations = [str(item) for item in list(previous.get("last_required_observations", []) or []) if str(item).strip()]
        if not actions and str(previous.get("last_intent_type", "")) == "memory_recall":
            actions = ["memory_recall"]
            observations = ["memory_observation_ledger"]
        return actions or ["answer_direct"], observations
    return [], []


def build_intent_frame(
    raw_user_text: str,
    *,
    previous_goal_state: dict[str, Any] | None = None,
    channel: str = "",
) -> dict[str, Any]:
    text = str(raw_user_text or "")
    stripped = text.strip()
    previous = _previous_goal(previous_goal_state)
    inherited_id = ""
    inherited_goal_text = ""
    intent_type = "answer"
    confidence = 0.62

    if FOLLOWUP_RE.match(stripped):
        intent_type = "followup"
        confidence = 0.78
        inherited_id = str(previous.get("last_goal_id", "") or "")
        inherited_goal_text = str(previous.get("last_goal_text", "") or "")
        if stripped in {"?", "\uff1f", "??", "\uff1f\uff1f"} and str(previous.get("last_stop_reason", "")) not in {
            "",
            "final_answer_ready",
            "goal_complete",
        }:
            confidence = 0.86
    elif MEMORY_RE.search(text):
        intent_type = "memory_recall"
        confidence = 0.86
    elif WEB_RE.search(text):
        intent_type = "web_lookup"
        confidence = 0.84
    elif ENGINEERING_RE.search(text.lower()):
        intent_type = "engineering_task"
        confidence = 0.8
    elif PROJECT_RE.search(text.lower()):
        intent_type = "project_state"
        confidence = 0.72
    elif not stripped:
        intent_type = "clarification"
        confidence = 0.7
    elif len(stripped) <= 3 and any(mark in stripped for mark in ("?", "\uff1f")):
        intent_type = "clarification"
        confidence = 0.64

    mandatory_actions, required_observations = _required_for_intent(intent_type, previous)
    normalized_goal = inherited_goal_text if intent_type == "followup" and inherited_goal_text else stripped
    if not normalized_goal and intent_type == "followup":
        normalized_goal = "follow up on previous unresolved goal"
    optional_actions = []
    if intent_type not in {"web_lookup", "memory_recall"}:
        optional_actions.append("answer_direct")
    success = ["produce a grounded final answer"]
    if required_observations:
        success.append("satisfy required observations: " + ",".join(required_observations))
    return {
        "schema": INTENT_FRAME_SCHEMA,
        "goal_id": _goal_id(normalized_goal or stripped, inherited_id if intent_type == "followup" else ""),
        "raw_user_text_exact": text,
        "normalized_goal": normalized_goal,
        "intent_type": intent_type,
        "confidence": round(confidence, 4),
        "mandatory_actions": mandatory_actions,
        "optional_actions": optional_actions,
        "required_observations": required_observations,
        "success_criteria": success,
        "inherited_from_goal_id": inherited_id,
        "channel": str(channel or ""),
        "created_at": utc_now(),
    }
