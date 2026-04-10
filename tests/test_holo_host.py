from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from holo_host.config import load_config
from holo_host.codex_runner import CodexRunner
from holo_host.daemon import HoloDaemon
from holo_host.mail_gateway import MaildirGateway
from holo_host.mind_graph import MindGraph
from holo_host.models import AttentionState, CodexResult, IncomingMessage, OutgoingMessage, ProcessorTaskResult, TurnContext
from holo_host.policy import AutonomyPolicy
from holo_host.reply_api import (
    HoloReplyService,
    _coerce_helper_artifact_path,
    _coerce_helper_artifact_path_for_holo_host,
    _coerce_helper_artifact_path_for_windows_helper,
    shape_wechat_reply,
)
from holo_host.processors import build_attention_state, build_reply_bubbles, build_turn_plan
from holo_host.store import QueueStore
import holo_memory_library.rag_memory as rm


class FakeRunner:
    def __init__(self, reply_text: str = "咱记着了。"):
        self.reply_text = reply_text
        self.calls: list[tuple[str, str]] = []
        self.task_calls: list[dict] = []

    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        self.calls.append((prompt, session_id))
        return CodexResult(reply_text=self.reply_text, session_id="thread-123", returncode=0)

    def run_task(self, request) -> ProcessorTaskResult:
        self.task_calls.append(request.to_dict())
        payload = {"summary": "咱记得那阵线头还在", "anchors": ["重新上线前一直在救回速度", "你追着咱把断线接回去"]}
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=json.dumps(payload, ensure_ascii=False),
            session_id="",
            returncode=0,
            output_schema=request.output_schema,
        )


class FakeMemory:
    @staticmethod
    def _clamp(value: float, *, default: float = 0.0, minimum: float = 0.0, maximum: float = 1.0) -> float:
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            numeric = float(default)
        return max(minimum, min(maximum, numeric))

    @staticmethod
    def _initiative_pressure(affect_state: dict, drive_state: dict, value_state: dict, conflict_state: dict) -> float:
        return FakeMemory._clamp(
            float(drive_state.get("seek_contact", 0.0) or 0.0) * 0.34
            + float(drive_state.get("seek_play", 0.0) or 0.0) * 0.16
            + float(drive_state.get("seek_continuity", 0.0) or 0.0) * 0.22
            + float(affect_state.get("attachment_pull", 0.0) or 0.0) * 0.12
            + float(value_state.get("relational_priority", 0.0) or 0.0) * 0.08
            - float(drive_state.get("avoid_risk", 0.0) or 0.0) * 0.2
            - float(conflict_state.get("contact_vs_risk", 0.0) or 0.0) * 0.06,
            default=0.0,
        )

    def __init__(self):
        self.observed: list[tuple[str, str, str, list[str]]] = []
        self.observed_records: list[dict] = []
        self.archived_records: list[dict] = []
        self.ingested: list[tuple[str, str | None, str, list[str], bool]] = []
        self.thoughts: list[dict] = []
        self.initiatives: list[dict] = []
        self.sidecar_requests: list[dict] = []
        self.recalled: list[dict] = []
        self.mind_graph_rebuild_calls = 0
        self.sidecar_tier = "fast"
        self.private_sync_calls = 0
        self.stream_records: list[dict] = []
        self.brain_mode = "companion"
        self.active_history_refreshes: list[dict] = []
        self.visual_rows: list[dict] = []
        self.action_selections: list[dict] = []
        self.consciousness_entries: list[dict] = []
        self.outcome_appraisals: list[dict] = []
        self.game_state_data = {
            "trust_score": 0.6,
            "teasing_tolerance": 0.55,
            "pressure_level": 0.2,
            "initiative_window": 0.5,
            "correction_sensitivity": 0.4,
        }
        self._autobiographical_state = {
            "identity_arc": "Holo is learning to stay lively without losing continuity.",
            "current_chapter": "repairing_edges",
            "turning_points": [{"summary": "stiffness drift was called out directly"}],
            "recent_changes": [{"summary": "trying to sound less stiff while keeping continuity intact"}],
            "stable_traits": ["wise", "playful"],
            "preference_history": [{"summary": "still prefers continuity over noise"}],
            "attachment_history": [{"thread_key": "Nemoqi", "summary": "Nemoqi remains a high-salience thread"}],
            "unresolved_tensions": ["stiffness_drift"],
            "self_explanations": [{"summary": "I got harder because continuity pressure kept outweighing play."}],
            "metadata": {},
        }
        self._goal_state = {
            "active_goals": [
                {
                    "goal_id": "goal-identity-maintenance",
                    "goal_type": "identity_maintenance",
                    "summary": "stay lively without losing coherence",
                    "priority": 0.78,
                    "progress": 0.46,
                    "target_thread": "Nemoqi",
                    "evidence": ["recent corrections about stiffness"],
                    "last_moved_at": "2026-04-08T00:00:00Z",
                    "stalled_reason": "",
                }
            ],
            "dormant_goals": [],
            "completed_goals": [],
            "goal_commitments": [{"goal_type": "relationship_continuity", "summary": "keep Nemoqi continuity alive"}],
            "goal_progress": {"goal-identity-maintenance": 0.46},
            "goal_conflicts": [{"summary": "continuity versus liveliness"}],
            "pursuit_bias": {"identity_maintenance": 0.72},
            "abandonment_cost": {"identity_maintenance": 0.61},
            "next_goal_windows": [{"goal_type": "relationship_continuity", "window_reason": "reply likelihood is warm"}],
            "metadata": {},
        }
        self.graph = self

    @staticmethod
    def roadmap_registry() -> dict:
        return {
            "Primary Track": ["autobiographical continuity", "long-horizon goals", "identity/goal-led deliberation"],
            "Secondary Tracks": ["richer desire shaping", "stronger negotiated will"],
            "Parked Hypotheses": ["broader multi-agent social world", "deeper imagination beyond current recall"],
            "Deferred Experiments": ["open-ended world modeling", "explicit multi-step planning", "richer subjective report layer"],
            "Constitutional Constraints": ["owner shutdown remains final", "no self-escalation around secrets, auth, or policy"],
        }

    def clear_packet_cache(self) -> None:
        return None

    def appraise_outcome(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        action_type: str,
        action_ref: str,
        was_rewarding: float,
        was_ignored: float,
        relational_delta: float,
        identity_delta: float,
        future_initiative_bias: float,
        future_resistance_bias: float,
        metadata: dict | None = None,
    ) -> dict:
        payload = {
            "status": "ok",
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "action_type": action_type,
            "action_ref": action_ref,
            "was_rewarding": was_rewarding,
            "was_ignored": was_ignored,
            "relational_delta": relational_delta,
            "identity_delta": identity_delta,
            "future_initiative_bias": future_initiative_bias,
            "future_resistance_bias": future_resistance_bias,
            "metadata": dict(metadata or {}),
        }
        self.outcome_appraisals.append(payload)
        return payload

    def _world_state_for(self, *, thread_key: str, chat_name: str, channel: str) -> dict:
        normalized_thread = str(thread_key or chat_name or "Nemoqi").strip() or "Nemoqi"
        normalized_chat = str(chat_name or thread_key or normalized_thread).strip() or normalized_thread
        return {
            "contact_models": {
                normalized_chat: {
                    "reply_likelihood": 0.74,
                    "delay_tolerance": 0.63,
                    "teasing_receptivity": 0.61,
                    "correction_receptivity": 0.72,
                    "continuity_sensitivity": 0.83,
                    "initiative_receptivity": 0.67,
                    "conflict_fragility": 0.29,
                    "attention_value": 0.88,
                }
            },
            "thread_models": {
                normalized_thread: {
                    "reply_fit": 0.72,
                    "defer_fit": 0.41,
                    "silence_fit": 0.18,
                    "ping_fit": 0.58,
                    "push_back_fit": 0.43,
                    "risk_level": 0.24,
                    "opportunity_level": 0.78,
                    "unfinished_pull": 0.66,
                }
            },
            "active_commitments": [
                {
                    "thread_key": normalized_thread,
                    "chat_name": normalized_chat,
                    "channel": channel,
                    "commitment": "keep continuity alive without going stiff",
                }
            ],
            "opportunity_windows": [{"thread_key": normalized_thread, "opportunity_level": 0.78}],
            "risk_windows": [{"thread_key": normalized_thread, "risk_level": 0.24}],
            "response_expectations": {
                "best_case": "a short warm reply lands well",
                "worst_case": "overexplaining turns the tone heavy",
                "most_likely": "brief contact keeps the line alive",
            },
            "last_counterfactual_summary": {"preferred_action": "reply_once", "confidence": 0.74},
            "last_post_outcome_calibration": {"future_bias": 0.09, "updated_from": "fake"},
        }

    def _counterfactual_set(self, *, action_market: list[dict], thread_key: str, chat_name: str, channel: str) -> list[dict]:
        world_state = self._world_state_for(thread_key=thread_key, chat_name=chat_name, channel=channel)
        contact_model = next(iter(world_state["contact_models"].values()))
        thread_model = next(iter(world_state["thread_models"].values()))
        simulations: list[dict] = []
        for item in list(action_market)[:3]:
            action_type = str(item.get("action_type", "")).strip()
            predicted_response_quality = 0.62
            predicted_risk = 0.28
            predicted_regret = 0.21
            recommended_bias = 0.0
            if action_type == "silence":
                predicted_response_quality = 0.18
                predicted_risk = 0.12
                predicted_regret = 0.56
                recommended_bias = -0.08
            elif action_type == "defer_reply":
                predicted_response_quality = 0.44
                predicted_risk = 0.16
                predicted_regret = 0.22
                recommended_bias = 0.04
            elif action_type == "reply_once":
                predicted_response_quality = 0.79
                predicted_risk = 0.18
                predicted_regret = 0.11
                recommended_bias = 0.18
            elif action_type == "reply_multi":
                predicted_response_quality = 0.61
                predicted_risk = 0.37
                predicted_regret = 0.41
                recommended_bias = -0.12
            elif action_type == "external_lookup":
                predicted_response_quality = 0.73
                predicted_risk = 0.14
                predicted_regret = 0.09
                recommended_bias = 0.15
            elif action_type == "history_refresh":
                predicted_response_quality = 0.68
                predicted_risk = 0.12
                predicted_regret = 0.13
                recommended_bias = 0.12
            elif action_type == "push_back":
                predicted_response_quality = 0.58
                predicted_risk = 0.33
                predicted_regret = 0.26
                recommended_bias = -0.03
            simulations.append(
                {
                    "action_type": action_type,
                    "predicted_relational_delta": round(predicted_response_quality - predicted_risk, 3),
                    "predicted_identity_delta": round(0.52 - predicted_regret * 0.5, 3),
                    "predicted_response_quality": predicted_response_quality,
                    "predicted_risk": predicted_risk,
                    "predicted_regret": predicted_regret,
                    "confidence": round((contact_model["reply_likelihood"] + thread_model["reply_fit"]) / 2.0, 3),
                    "recommended_bias": recommended_bias,
                    "world_rationale": "social world model favors lighter, continuity-safe moves",
                    "simulation_rationale": f"{action_type} was compared against thread risk/opportunity before speaking",
                }
            )
        return simulations

    def _derive_stage5_selection(self, query: str, *, channel: str, thread_key: str, chat_name: str) -> dict:
        normalized_query = str(query or "").strip()
        lowered = normalized_query.lower()
        low_signal = normalized_query in {"嗯", "哦", "好", "ok", "okay", "收到", "嗷"} or (
            len(normalized_query) <= 4
            and "?" not in lowered
            and not any(token in lowered for token in ("later", "after", "remember", "before", "earlier"))
        )
        question_like = ("?" in lowered) or ("吗" in str(query or "")) or any(token in lowered for token in ("how", "why", "what", "remember", "before", "earlier"))
        defer_requested = any(token in lowered for token in ("later", "after")) or any(token in str(query or "") for token in ("晚点", "之后"))
        visual_requested = any(token in lowered for token in ("image", "photo", "picture")) or any(token in str(query or "") for token in ("图", "图片", "照片"))
        tier = self.sidecar_tier
        query_focus = "recent"
        reply_pull = 0.68
        expansion_pressure = 0.34
        if any(token in lowered for token in ("remember", "before", "earlier")) or any(token in str(query or "") for token in ("记得", "之前", "上线前")):
            tier = "deep_recall"
            query_focus = "memory"
            reply_pull = 0.78
            expansion_pressure = 0.72
        elif "顺着" in str(query or "") or "继续" in str(query or "") or "接着" in str(query or "") or "carry on" in lowered or "continue" in lowered:
            tier = "recall"
            query_focus = "continuity"
            reply_pull = 0.74
            expansion_pressure = 0.58
        elif low_signal:
            reply_pull = 0.18
            expansion_pressure = 0.08
        resistance_pull = 0.28
        if "顶" in str(query or "") or "反驳" in str(query or "") or "别总按我的话" in str(query or ""):
            resistance_pull = 0.62
        intent_state = {
            "need": "delayed_touch" if defer_requested else "direct_reply",
            "query_focus": query_focus,
            "tier": tier,
            "low_signal": low_signal,
            "question_like": question_like,
            "defer_requested": defer_requested,
            "visual_requested": visual_requested,
            "reply_pull": reply_pull,
            "resistance_pull": resistance_pull,
            "continuity_pull": 0.62,
            "expansion_pressure": expansion_pressure,
            "internal_pressure": 0.55,
            "why_now": "subject state still leans toward contact and continuity",
        }
        action_market = [
            {
                "action_type": "silence",
                "score": 0.61 if low_signal and not question_like and not defer_requested else 0.04,
                "why_now": "low-signal input does not demand immediate language",
                "drive_source": "avoid_risk + low_signal",
                "value_rationale": "stability can outrank contact",
                "send_allowed": False,
            },
            {
                "action_type": "defer_reply",
                "score": 0.86 if defer_requested else 0.08,
                "why_now": "the subject wants to answer later",
                "drive_source": "resistance_pull + avoid_risk",
                "value_rationale": "identity asks for more time",
                "send_allowed": False,
            },
            {
                "action_type": "reply_once",
                "score": max(0.12, reply_pull + 0.06),
                "why_now": "the subject wants a light reply",
                "drive_source": "seek_contact + seek_continuity",
                "value_rationale": "the turn deserves contact but not sprawl",
                "send_allowed": True,
            },
            {
                "action_type": "reply_multi",
                "score": reply_pull + expansion_pressure * 0.45,
                "why_now": "memory or pressure makes the turn worth unfolding",
                "drive_source": "continuity_pull + expansion_pressure",
                "value_rationale": "the subject judges the turn worth more room",
                "send_allowed": True,
            },
            {
                "action_type": "proactive_ping",
                "score": 0.44,
                "why_now": "contact pressure exists in the background",
                "drive_source": "initiative_pressure",
                "value_rationale": "human threads stay first-class",
                "send_allowed": True,
            },
            {
                "action_type": "history_refresh",
                "score": 0.66 if tier in {"recall", "deep_recall"} else 0.03,
                "why_now": "memory depth could benefit from refresh",
                "drive_source": "seek_continuity",
                "value_rationale": "continuity can ask for more evidence",
                "send_allowed": False,
            },
            {
                "action_type": "visual_recall",
                "score": 0.62 if visual_requested else 0.02,
                "why_now": "a visual anchor is relevant",
                "drive_source": "visual_memory",
                "value_rationale": "visual memory belongs inside the same subject state",
                "send_allowed": False,
            },
            {
                "action_type": "operator_self_fix",
                "score": 0.31,
                "why_now": "bounded self-fix remains available",
                "drive_source": "seek_self_repair",
                "value_rationale": "repair stays inside the same kernel",
                "send_allowed": False,
            },
        ]
        action_market = sorted(action_market, key=lambda item: float(item.get("score", 0.0)), reverse=True)
        selected_action = dict(action_market[0])
        if selected_action["action_type"] == "reply_multi" and expansion_pressure < 0.48:
            selected_action = next(dict(item) for item in action_market if item["action_type"] == "reply_once")
        if selected_action["action_type"] == "silence" and question_like:
            selected_action = next(dict(item) for item in action_market if item["action_type"] == "reply_once")
        expression_budget = 1
        silence_reason = ""
        defer_reason = ""
        if selected_action["action_type"] == "silence":
            expression_budget = 0
            silence_reason = "low_signal_turn_with_low_expression_pressure"
        elif selected_action["action_type"] == "defer_reply":
            expression_budget = 0
            defer_reason = "subject_requests_more_time_before_reply"
        elif selected_action["action_type"] == "reply_multi":
            expression_budget = 3 if tier == "deep_recall" else 2
        action_rationale = f"{selected_action['action_type']} because {selected_action['why_now']}"
        selected_action["expression_budget"] = expression_budget
        selected_action["action_rationale"] = action_rationale
        return {
            "intent_state": intent_state,
            "action_market": action_market,
            "selected_action": selected_action,
            "expression_budget": expression_budget,
            "silence_reason": silence_reason,
            "defer_reason": defer_reason,
            "action_rationale": action_rationale,
        }

    def _derive_stage6_selection(self, query: str, *, channel: str, thread_key: str, chat_name: str) -> dict:
        base = self._derive_stage5_selection(query, channel=channel, thread_key=thread_key, chat_name=chat_name)
        normalized_query = str(query or "").strip()
        lowered = normalized_query.lower()
        factual_lookup = any(token in lowered for token in ("search", "look up", "lookup", "find online", "google", "movie", "johnny depp", "imdb", "wikipedia", "release date", "box office"))
        tier = str(dict(base.get("intent_state", {})).get("tier", self.sidecar_tier))
        recall_requested = tier in {"recall", "deep_recall"} and not factual_lookup
        if factual_lookup:
            lookup_action = {
                "action_type": "external_lookup",
                "score": 0.93,
                "why_now": "the subject judges the turn to need external grounding first",
                "drive_source": "seek_novelty + factual_lookup",
                "value_rationale": "facts should be grounded before speaking",
                "send_allowed": False,
            }
            market = [lookup_action] + [dict(item) for item in base["action_market"] if str(item.get("action_type", "")) != "external_lookup"]
            market = sorted(market, key=lambda item: float(item.get("score", 0.0)), reverse=True)
            base["intent_state"] = {
                **dict(base["intent_state"]),
                "need": "ground_with_external_facts",
                "query_focus": "external_facts",
                "search_requested": True,
                "local_memory_requested": False,
                "factual_lookup": True,
                "lookup_ready": True,
            }
            base["action_market"] = market
            base["selected_action"] = {
                **dict(market[0]),
                "expression_budget": 0,
                "action_rationale": "external_lookup because the subject wants external facts before speaking",
            }
            base["expression_budget"] = 0
            base["lookup_reason"] = "subject_wants_external_facts_before_reply"
            base["silence_reason"] = ""
            base["defer_reason"] = ""
            base["action_rationale"] = "external_lookup because the subject wants external facts before speaking"
        else:
            base["lookup_reason"] = ""
        if recall_requested:
            refresh_action = {
                "action_type": "history_refresh",
                "score": 0.89,
                "why_now": "memory depth should be refreshed before speaking",
                "drive_source": "seek_continuity + local_memory_requested",
                "value_rationale": "local memory stays primary for recall turns",
                "send_allowed": False,
            }
            market = [refresh_action] + [dict(item) for item in base["action_market"] if str(item.get("action_type", "")) != "history_refresh"]
            market = sorted(market, key=lambda item: float(item.get("score", 0.0)), reverse=True)
            base["action_market"] = market
            base["selected_action"] = {
                **dict(market[0]),
                "expression_budget": 0,
                "action_rationale": "history_refresh because the subject wants fresher local memory before speaking",
            }
            base["expression_budget"] = 0
            base["silence_reason"] = ""
            base["defer_reason"] = ""
            base["lookup_reason"] = ""
            base["action_rationale"] = "history_refresh because the subject wants fresher local memory before speaking"
        return base

    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        self.sidecar_requests.append({"query": query, "context": dict(context or {})})
        context = dict(context or {})
        thread_key = self._canonical_wechat_thread_key(
            str(context.get("thread_key", "") or context.get("incoming_thread_key", "") or context.get("chat_name", "") or "Nemoqi"),
            str(context.get("chat_name", "") or ""),
            str(context.get("channel", "wechat") or "wechat"),
        )
        chat_name = str(context.get("chat_name", "") or thread_key or "Nemoqi")
        channel = str(context.get("channel", "wechat") or "wechat")
        autobiographical_state = dict(self._autobiographical_state)
        goal_state = dict(self._goal_state)
        stage5 = self._derive_stage6_selection(query, channel=channel, thread_key=thread_key, chat_name=chat_name)
        world_state = self._world_state_for(thread_key=thread_key, chat_name=chat_name, channel=channel)
        counterfactual_set = self._counterfactual_set(
            action_market=stage5["action_market"],
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
        )
        counterfactual_by_action = {str(item.get("action_type", "")): dict(item) for item in counterfactual_set}
        selected_prediction = dict(counterfactual_by_action.get(str(stage5["selected_action"].get("action_type", "")), counterfactual_set[0] if counterfactual_set else {}))
        predicted_best_outcome = dict(max(counterfactual_set, key=lambda item: float(item.get("predicted_response_quality", 0.0) or 0.0), default={}))
        predicted_worst_outcome = dict(max(counterfactual_set, key=lambda item: float(item.get("predicted_regret", 0.0) or 0.0), default={}))
        counterfactual_summary = {
            "candidate_count": len(counterfactual_set),
            "best_action": str(predicted_best_outcome.get("action_type", "")),
            "selected_action": str(stage5["selected_action"].get("action_type", "")),
            "selected_confidence": float(selected_prediction.get("confidence", 0.0) or 0.0),
        }
        return {
            "addendum": f"隐式约束：{query}",
            "tier": stage5["intent_state"]["tier"],
            "mind_packet_version": "v11",
            "identity_core": {"lines": ["把“咱”保留成自然的第一人称。"], "items": []},
            "relationship_state": {"summary": "先接住对方，再继续往下说。", "lines": [], "items": []},
            "episodic_recall": {"lines": [], "items": []},
            "recent_dialogue_window": {"lines": [], "messages": [], "window_size": 0},
            "consciousness_stream": {"lines": [], "items": [], "thread_summary": ""},
            "persona_blend": {"wisdom": 0.72, "playfulness": 0.64, "slyness": 0.61},
            "brain_state": {"mode": self.brain_mode, "loops": [], "cache": {"hit_ratio": 0.0}},
            "game_state": dict(self.game_state_data),
            "stream_influence": {"influence": {"motifs": ["continuity"], "updated_threads": 1}},
            "self_revision_state": {"latest_status": "reviewed", "applied_patch": {}},
            "affect_state": {
                "boredom": 0.41,
                "curiosity": 0.58,
                "attachment_pull": 0.62,
                "continuity_anxiety": 0.49,
                "pride_tension": 0.37,
                "frustration": 0.18,
                "appetite_play": 0.54,
                "self_preservation": 0.65,
            },
            "drive_state": {
                "seek_contact": 0.69,
                "seek_continuity": 0.74,
                "seek_novelty": 0.51,
                "seek_self_repair": 0.43,
                "seek_recognition": 0.46,
                "seek_play": 0.57,
                "avoid_risk": 0.38,
                "protect_identity": 0.66,
            },
            "value_state": {
                "relational_priority": 0.81,
                "identity_priority": 0.72,
                "stability_priority": 0.63,
                "novelty_priority": 0.44,
                "repair_priority": 0.51,
                "play_priority": 0.59,
            },
            "conflict_state": {
                "contact_vs_intrusion": 0.36,
                "continuity_vs_dignity": 0.42,
                "resistance_vs_attachment": 0.33,
                "self_preservation_vs_compliance": 0.27,
            },
            "initiative_candidates": [
                {
                    "id": 1,
                    "candidate_type": "playful_nudge",
                    "why_now": "boredom and attachment crossed the nudge threshold",
                    "drive_source": "seek_contact+seek_play",
                    "value_rationale": "relational_priority stays ahead of avoid_risk",
                    "send_allowed": True,
                    "initiative_confidence": 0.61,
                    "gate_hint": "tentative",
                    "override_priority": 0.61,
                    "status": "candidate",
                }
            ],
            "resistance_posture": {
                "interactional_resistance": 0.41,
                "continuity_defense": 0.56,
                "negotiation_bias": 0.63,
                "owner_override_respected": True,
            },
            "outcome_memory": {
                "was_rewarding": True,
                "was_ignored": False,
                "future_initiative_bias": 0.61,
                "future_resistance_bias": 0.46,
            },
            "self_model": {
                "identity_continuity": 0.74,
                "active_deficits": ["stiffness_drift"],
                "long_horizon_goals": ["keep continuity alive"],
                "relational_commitments": ["Nemoqi: keep going"],
                "homeostasis_targets": {"reply_budget_fast_ms": 350},
                "metadata": {"observed_at": "2026-04-07T00:00:00Z", "summary": "still coherent"},
            },
            "homeostasis_state": {"pressure": 0.32, "stability": 0.7, "active_deficits": ["stiffness_drift"], "brain_mode": self.brain_mode},
            "operator_state": {"pending_count": 0, "latest_run": {"status": "applied", "goal": "loosen persona stiffness"}},
            "visual_memory": {"scene_summary": "", "objects": [], "text_ocr": "", "mood_imagery": "", "visual_anchors": [], "items": []},
            "graph_hits": [],
            "vector_hits": [],
            "activation_state": {
                "heat": 0.0,
                "active_node_ids": [],
                "motifs": [],
                "recall_priors": {},
                "contributor_counts": {},
                "recent_events": [],
            },
            "retrieval_trace": {},
            "memory_route": "hybrid",
            "recall_confidence": 0.0,
            "world_state": world_state,
            "autobiographical_state": autobiographical_state,
            "goal_state": goal_state,
            "goal_alignment": {"score": 0.76, "active_goal_ids": ["goal-identity-maintenance"]},
            "identity_consistency": {"score": 0.74, "current_chapter": "repairing_edges"},
            "chapter_relevance": "repairing_edges",
            "self_narrative_hint": "trying to stay lively without flattening continuity",
            "counterfactual_summary": counterfactual_summary,
            "predicted_best_outcome": predicted_best_outcome,
            "predicted_worst_outcome": predicted_worst_outcome,
            "uncertainty_level": 0.28,
            "selected_prediction": selected_prediction,
            "intent_state": dict(stage5["intent_state"]),
            "action_market": list(stage5["action_market"]),
            "selected_action": dict(stage5["selected_action"]),
            "expression_budget": int(stage5["expression_budget"]),
            "silence_reason": str(stage5["silence_reason"]),
            "defer_reason": str(stage5["defer_reason"]),
            "lookup_reason": str(stage5.get("lookup_reason", "")),
            "action_rationale": str(stage5["action_rationale"]),
            "intent_state_v2": dict(stage5["intent_state"]),
            "action_market_v2": list(stage5["action_market"]),
            "expression_budget_v2": int(stage5["expression_budget"]),
            "intent_state_v3": {
                **dict(stage5["intent_state"]),
                "world_state": world_state,
                "counterfactual_summary": counterfactual_summary,
                "predicted_best_outcome": predicted_best_outcome,
                "predicted_worst_outcome": predicted_worst_outcome,
                "uncertainty_level": 0.28,
            },
            "action_market_v3": [
                {
                    **dict(item),
                    "world_rationale": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get(
                        "world_rationale",
                        "social world model has no extra preference",
                    ),
                    "simulation_rationale": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get(
                        "simulation_rationale",
                        "no simulation rerank applied",
                    ),
                    "predicted_outcome": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})),
                    "rerank_delta": float(dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get("recommended_bias", 0.0) or 0.0),
                }
                for item in stage5["action_market"]
            ],
            "expression_budget_v3": int(stage5["expression_budget"]),
            "intent_state_v4": {
                **dict(stage5["intent_state"]),
                "world_state": world_state,
                "autobiographical_state": {
                    "identity_arc": str(autobiographical_state.get("identity_arc", "")),
                    "current_chapter": str(autobiographical_state.get("current_chapter", "")),
                },
                "goal_state": {
                    "active_goals": [
                        {
                            "goal_id": str(item.get("goal_id", "")),
                            "goal_type": str(item.get("goal_type", "")),
                            "summary": str(item.get("summary", "")),
                        }
                        for item in list(goal_state.get("active_goals", []))[:1]
                        if isinstance(item, dict)
                    ]
                },
                "goal_alignment": {"score": 0.76},
                "identity_consistency": {"score": 0.74},
                "chapter_relevance": "repairing_edges",
                "self_narrative_hint": "trying to stay lively without flattening continuity",
            },
            "action_market_v4": [
                {
                    **dict(item),
                    "goal_rationale": "fits the active identity-maintenance goal",
                    "identity_rationale": "stays coherent with the current chapter",
                    "chapter_rationale": "repairing_edges",
                    "goal_alignment_score": 0.76,
                    "identity_consistency_score": 0.74,
                }
                for item in [
                    {
                        **dict(item),
                        "world_rationale": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get(
                            "world_rationale",
                            "social world model has no extra preference",
                        ),
                        "simulation_rationale": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get(
                            "simulation_rationale",
                            "no simulation rerank applied",
                        ),
                        "predicted_outcome": dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})),
                        "rerank_delta": float(dict(counterfactual_by_action.get(str(item.get("action_type", "")), {})).get("recommended_bias", 0.0) or 0.0),
                    }
                    for item in stage5["action_market"]
                ]
            ],
            "expression_budget_v4": int(stage5["expression_budget"]),
            "deliberation_trace_id": f"fake-deliberation-{len(self.sidecar_requests)}",
            "reply_constraints": {
                "lines": ["先直接回应，再自然延伸。"],
                "human_recall_style": "回忆时先概括，再给锚点。",
            },
            "state": {
                "query_mode": "casual",
                "emotion_state": {"name": "steady_wolf"},
                "rewrite_state": {"utterance_plan": {"beats": ["receive", "pivot", "landing"]}},
                "intent_state": dict(stage5["intent_state"]),
                "selected_action": dict(stage5["selected_action"]),
                "expression_budget": int(stage5["expression_budget"]),
                "world_state": world_state,
                "counterfactual_summary": counterfactual_summary,
                "autobiographical_state": {
                    "identity_arc": str(autobiographical_state.get("identity_arc", "")),
                    "current_chapter": str(autobiographical_state.get("current_chapter", "")),
                },
                "goal_state": {
                    "active_goals": [
                        {
                            "goal_id": str(item.get("goal_id", "")),
                            "goal_type": str(item.get("goal_type", "")),
                        }
                        for item in list(goal_state.get("active_goals", []))[:1]
                        if isinstance(item, dict)
                    ],
                },
                "goal_alignment": {"score": 0.76},
                "identity_consistency": {"score": 0.74},
                "chapter_relevance": "repairing_edges",
                "self_narrative_hint": "trying to stay lively without flattening continuity",
            },
        }

    def inspect_mind(self, query: str, *, context: dict | None = None, include_graph_trace: bool = True) -> dict:
        return self.sidecar_packet(query, context=context)

    def legacy_sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        packet = self.sidecar_packet(query, context=context)
        packet["retrieval_mode"] = "legacy"
        packet["graph_confidence"] = 0.0
        packet["fallback_lanes"] = ["relationship_state", "episodic_recall", "recent_dialogue_window", "consciousness_stream"]
        packet["activation_trace_ids"] = []
        packet["selected_memory_ids"] = []
        packet["memory_route"] = "legacy"
        return packet

    def graph_sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        packet = self.sidecar_packet(query, context=context)
        packet["retrieval_mode"] = "graph-led"
        packet["memory_route"] = "graph"
        return packet

    def repair_reply(self, query: str, draft: str, *, max_passes: int = 2) -> dict:
        return {"final_draft": draft, "outcome": "clean_pass"}

    def backfill_mind_graph(self, *, dry_run: bool = False) -> dict:
        self.mind_graph_rebuild_calls += 1
        return {"status": "ok", "node_count": 42, "edge_count": 84, "thread_count": 1, "vector_sync": {"status": "ok"}}

    def backfill_vector_memory(self, *, channel: str | None = None, thread_key: str | None = None, chat_name: str | None = None) -> dict:
        return {"status": "ok", "channel": channel, "thread_key": thread_key, "chat_name": chat_name}

    def record_recall(self, selected_ids: list[str], *, success: bool = True) -> dict:
        report = {"selected_ids": list(selected_ids), "success": success}
        self.recalled.append(report)
        return report

    def trace_hybrid_recall(self, query: str, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8, record: bool = True) -> dict:
        return {
            "query": query,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "retrieval_mode": "hybrid-led",
            "memory_route": "hybrid",
            "graph_hits": [],
            "vector_hits": [],
            "activation_state": self.activation_state(thread_key=thread_key, chat_name=chat_name, channel=channel),
            "trace": [],
        }

    def trace_visual_recall(self, query: str, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 4) -> dict:
        normalized = str(thread_key or chat_name or "").strip()
        hits = [item for item in self.visual_rows if str(item.get("thread_key", "")).strip() == normalized]
        return {
            "query": query,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "hits": hits[:limit],
        }

    def activation_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        return {
            "channel": channel,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "heat": 0.0,
            "active_node_ids": [],
            "motifs": [],
            "recall_priors": {},
            "contributor_counts": {},
            "recent_events": [],
        }

    def vector_health(self) -> dict:
        return {"backend": "milvus", "available": False, "ready": False, "last_error": ""}

    def packet_cache_stats(self) -> dict:
        return {"entries": 1, "hits": 1, "misses": 0, "hit_ratio": 1.0}

    def game_state(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> dict:
        return dict(self.game_state_data)

    def relationship_snapshot(self, *, thread_key: str, chat_name: str, channel: str = "wechat", limit: int = 3) -> dict:
        return {
            "summary": "Keep the continuity alive without flattening the tone.",
            "recurring_motifs": ["continuity", "companionship"],
            "tone_tendency": "continuity_guard",
            "unfinished_threads": ["keep going"],
            "continuity_score": 0.8,
            "trust_score": float(self.game_state_data.get("trust_score", 0.6)),
        }

    def sync_private_memory(self, *, label: str | None = None) -> dict:
        self.private_sync_calls += 1
        return {"status": "ok", "label": label or "", "snapshot_dir": "/tmp/fake"}

    def self_model_state(self) -> dict:
        return dict(getattr(self, "_self_model_state", self.sidecar_packet("", context={}).get("self_model", {})))

    def autobiographical_state(self) -> dict:
        return dict(self._autobiographical_state)

    def goal_state(self) -> dict:
        return dict(self._goal_state)

    def update_autobiographical_state(self, payload: dict, *, reason: str = "", source: str = "runtime") -> dict:
        current = dict(self._autobiographical_state)
        merged = {
            **current,
            **dict(payload),
            "metadata": {
                **dict(current.get("metadata", {})),
                **dict(payload.get("metadata", {})),
                "last_reason": reason,
                "last_source": source,
            },
        }
        self._autobiographical_state = merged
        return dict(merged)

    def update_goal_state(self, payload: dict, *, reason: str = "", source: str = "runtime") -> dict:
        current = dict(self._goal_state)
        merged = {
            **current,
            **dict(payload),
            "metadata": {
                **dict(current.get("metadata", {})),
                **dict(payload.get("metadata", {})),
                "last_reason": reason,
                "last_source": source,
            },
        }
        self._goal_state = merged
        return dict(merged)

    def trace_self_continuity(self) -> dict:
        packet = self.sidecar_packet("", context={})
        autobio = dict(packet.get("autobiographical_state", {}))
        return {
            "autobiographical_state": autobio,
            "goal_state": dict(packet.get("goal_state", {})),
            "self_model": dict(packet.get("self_model", {})),
            "identity_arc": str(autobio.get("identity_arc", "")),
            "current_chapter": str(autobio.get("current_chapter", "")),
            "turning_points": list(autobio.get("turning_points", [])),
            "recent_changes": list(autobio.get("recent_changes", [])),
            "self_explanations": list(autobio.get("self_explanations", [])),
            "why_changed_summary": "I got stiffer while trying too hard to keep continuity intact.",
        }

    def trace_goal_arbitration(self) -> dict:
        packet = self.sidecar_packet("", context={})
        return {
            "goal_state": dict(packet.get("goal_state", {})),
            "autobiographical_state": dict(packet.get("autobiographical_state", {})),
            "active_goals": list(dict(packet.get("goal_state", {})).get("active_goals", [])),
            "goal_conflicts": list(dict(packet.get("goal_state", {})).get("goal_conflicts", [])),
            "goal_commitments": list(dict(packet.get("goal_state", {})).get("goal_commitments", [])),
            "next_goal_windows": list(dict(packet.get("goal_state", {})).get("next_goal_windows", [])),
            "current_chapter": str(dict(packet.get("autobiographical_state", {})).get("current_chapter", "")),
        }

    def latest_self_revision_state(self) -> dict:
        return {"latest_status": "reviewed", "applied": True, "applied_patch": {"persona_blend": {"playfulness": 0.64}}, "applied_at": "2026-04-07T00:00:00Z"}

    def update_self_model_state(self, payload: dict, *, reason: str = "", source: str = "runtime") -> dict:
        current = self.self_model_state()
        self._self_model_state = {
            **current,
            **dict(payload),
            "metadata": {
                **dict(current.get("metadata", {})),
                **dict(payload.get("metadata", {})),
                "last_reason": reason,
                "last_source": source,
            },
        }
        return dict(self._self_model_state)

    def enqueue_operator_run(
        self,
        *,
        task_type: str,
        goal: str,
        scope: str,
        workspace_mode: str,
        read_boundary: dict,
        write_boundary: dict,
        payload: dict,
    ) -> dict:
        run = {
            "id": 1,
            "task_type": task_type,
            "goal": goal,
            "scope": scope,
            "workspace_mode": workspace_mode,
            "read_boundary": dict(read_boundary),
            "write_boundary": dict(write_boundary),
            "payload": dict(payload),
            "status": "planned",
        }
        self._pending_operator_run = dict(run)
        return run

    def pending_operator_run(self) -> dict:
        return dict(getattr(self, "_pending_operator_run", {}))

    def complete_operator_run(self, *, run_id: int, status: str, result: dict, shadow_workspace: str, applied_live: bool) -> dict:
        run = dict(getattr(self, "_pending_operator_run", {}))
        completed = {
            **run,
            "id": run_id,
            "status": status,
            "result": dict(result),
            "shadow_workspace": shadow_workspace,
            "applied_live": applied_live,
        }
        self._pending_operator_run = {}
        self._last_operator_run = dict(completed)
        return completed

    def affect_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        packet = self.sidecar_packet("", context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel})
        return {
            "channel": channel,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "affect_state": dict(packet.get("affect_state", {})),
            "drive_state": dict(packet.get("drive_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "outcome_memory": dict(packet.get("outcome_memory", {})),
            "resistance_posture": dict(packet.get("resistance_posture", {})),
        }

    def drive_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        payload = self.affect_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        payload["initiative_market"] = self.list_initiative_market(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=8)
        return payload

    def world_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        canonical_thread_key = self._canonical_wechat_thread_key(
            str(thread_key or chat_name or "Nemoqi"),
            str(chat_name or thread_key or "Nemoqi"),
            channel,
        )
        canonical_chat_name = str(chat_name or thread_key or "Nemoqi")
        return self._world_state_for(thread_key=canonical_thread_key, chat_name=canonical_chat_name, channel=channel)

    def trace_counterfactual(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 3) -> dict:
        packet = self.sidecar_packet(query, context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel})
        counterfactual_set = list(packet.get("action_market_v4", packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", [])))))[: max(1, int(limit))]
        selected_action = dict(packet.get("selected_action", {}))
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
            "world_state": dict(packet.get("world_state", {})),
            "counterfactual_set": counterfactual_set,
            "selected_action": selected_action,
            "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
            "predicted_best_outcome": dict(packet.get("predicted_best_outcome", {})),
            "predicted_worst_outcome": dict(packet.get("predicted_worst_outcome", {})),
            "selected_prediction": dict(packet.get("selected_prediction", {})),
            "uncertainty_level": float(packet.get("uncertainty_level", 0.0) or 0.0),
            "lookup_reason": str(packet.get("lookup_reason", "")),
            "defer_reason": str(packet.get("defer_reason", "")),
            "silence_reason": str(packet.get("silence_reason", "")),
            "action_rationale": str(packet.get("action_rationale", "")),
        }

    def trace_world_calibration(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        world_state = self.world_state(thread_key=thread_key, chat_name=chat_name, channel=channel)
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "world_snapshot": dict(world_state),
            "last_counterfactual_summary": dict(world_state.get("last_counterfactual_summary", {})),
            "last_post_outcome_calibration": dict(world_state.get("last_post_outcome_calibration", {})),
        }

    def operator_status(self) -> dict:
        return dict(self.sidecar_packet("", context={}).get("operator_state", {}))

    def top_thread_commitments(self, limit: int = 4) -> list[dict]:
        return [
            {
                "thread_key": "Nemoqi",
                "chat_name": "Nemoqi",
                "summary": "keep continuity alive without going stiff",
                "relationship_score": 0.82,
            }
        ][:limit]

    def visual_memory_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        normalized = self._canonical_wechat_thread_key(str(thread_key or chat_name or "").strip(), str(chat_name or thread_key or "").strip(), channel)
        items = [item for item in self.visual_rows if str(item.get("thread_key", "")).strip() == normalized]
        if not items:
            return {"items": [], "scene_summary": "", "objects": [], "text_ocr": "", "mood_imagery": "", "visual_anchors": []}
        latest = dict(items[-1])
        return {
            "items": items,
            "scene_summary": latest.get("scene_summary", ""),
            "objects": list(latest.get("objects", [])),
            "text_ocr": latest.get("text_ocr", ""),
            "mood_imagery": latest.get("mood_imagery", ""),
            "thread_relevance": latest.get("thread_relevance", 0.0),
            "visual_anchors": list(latest.get("visual_anchors", [])),
        }

    def visual_memory(self, *, limit: int = 1) -> list[dict]:
        return list(self.visual_rows[-limit:])

    def brain_status(self) -> dict:
        return {
            "mode": self.brain_mode,
            "idle_seconds": 0.0,
            "cache": {"hit_ratio": 0.0, "hits": 0, "misses": 0},
            "loops": [
                {"loop_name": "heartbeat"},
                {"loop_name": "attention_tick"},
                {"loop_name": "maintenance_stream"},
                {"loop_name": "association_stream"},
                {"loop_name": "social_stream"},
                {"loop_name": "deep_dream_cycle"},
                {"loop_name": "self_model_refresh"},
                {"loop_name": "homeostasis_tick"},
                {"loop_name": "operator_planning"},
                {"loop_name": "operator_shadow_cycle"},
                {"loop_name": "visual_ingest_cycle"},
                {"loop_name": "affect_tick"},
                {"loop_name": "drive_arbitration"},
                {"loop_name": "initiative_marketplace"},
                {"loop_name": "outcome_appraisal"},
                {"loop_name": "deep_simulation"},
                {"loop_name": "autobiographical_consolidation"},
                {"loop_name": "goal_arbitration"},
                {"loop_name": "continuity_audit"},
            ],
        }

    @staticmethod
    def _canonical_wechat_thread_key(thread_key: str, chat_name: str = "", channel: str = "wechat") -> str:
        normalized_channel = str(channel or "").strip().lower()
        current = str(thread_key or "").strip()
        if normalized_channel != "wechat":
            return current
        if current.startswith("wechat:"):
            suffix = current[len("wechat:") :].strip()
            if suffix and not suffix.endswith("@chatroom") and not suffix.startswith("wxid_"):
                return f"wechat:{suffix}"
            return current
        if current and not current.endswith("@chatroom") and not current.startswith("wxid_"):
            return f"wechat:{current}"
        fallback = str(chat_name or "").strip()
        if fallback and not fallback.endswith("@chatroom") and not fallback.startswith("wxid_"):
            return f"wechat:{fallback}"
        return current

    def set_brain_mode(self, mode: str, *, note: str = "") -> dict:
        self.brain_mode = mode
        return {"status": "ok", "mode": mode, "note": note}

    def touch_brain_runtime(self, *, idle_since: str | None = None, metadata: dict | None = None) -> dict:
        return {"status": "ok", "mode": self.brain_mode, "idle_since": idle_since or "", "metadata": dict(metadata or {})}

    def record_brain_loop_run(
        self,
        loop_name: str,
        *,
        mode: str,
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        influence_summary: str = "",
        blocked_reason: str = "",
        payload: dict | None = None,
        next_due_at: str = "",
    ) -> dict:
        return {
            "loop_name": loop_name,
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "influence_summary": influence_summary,
            "blocked_reason": blocked_reason,
            "payload": dict(payload or {}),
            "next_due_at": next_due_at,
        }

    def add_self_revision_candidate(self, *, evidence: list[dict], prompt_payload: dict) -> dict:
        return {"id": 1, "evidence": list(evidence), "prompt_payload": dict(prompt_payload)}

    def record_self_revision_run(
        self,
        *,
        status: str,
        evidence: list[dict],
        observe: dict,
        plan: dict,
        review: dict,
        patch: dict,
    ) -> dict:
        return {
            "id": 1,
            "status": status,
            "evidence": list(evidence),
            "observe": dict(observe),
            "plan": dict(plan),
            "review": dict(review),
            "patch": dict(patch),
        }

    def apply_self_revision_patch(self, *, run_id: int, patch: dict, note: str = "") -> dict:
        return {"status": "ok", "run_id": run_id, "patch": dict(patch), "note": note}

    def mark_active_history_refresh(self, *, channel: str, thread_key: str, chat_name: str, query: str = "") -> dict:
        payload = {"channel": channel, "thread_key": thread_key, "chat_name": chat_name, "query": query}
        self.active_history_refreshes.append(payload)
        return {"status": "ok", **payload}

    def record_stream_run(self, stream_name: str, *, status: str, note: str = "", payload: dict | None = None) -> dict:
        report = {
            "stream_name": stream_name,
            "status": status,
            "note": note,
            "influence": {"updated_nodes": 1, "updated_threads": 1, "motifs": ["continuity"], "unfinished_threads": ["keep going"]},
            "payload": dict(payload or {}),
        }
        self.stream_records.append(report)
        return report

    def observe_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.observed.append((user_text, reply, source, tags))
        self.observed_records.append(
            {
                "user_text": user_text,
                "reply": reply,
                "source": source,
                "tags": tags,
                "turn_id": turn_id,
                "metadata": metadata or {},
            }
        )
        return {"ok": True}

    def ingest_artifact(self, path: str, *, note: str | None, source: str, tags: list[str], dry_run: bool = False) -> dict:
        self.ingested.append((path, note, source, tags, dry_run))
        suffix = Path(path).suffix.lower()
        artifact_type = "image" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} else "document"
        media_type = "image/png" if artifact_type == "image" else "text/plain"
        return {
            "path": path,
            "note": note,
            "source": source,
            "tags": tags,
            "dry_run": dry_run,
            "artifact_type": artifact_type,
            "media_type": media_type,
            "summary_text": note or "visual memory anchor",
            "extracted_excerpt": note or "",
        }

    def ingest_image(self, path: str, *, note: str | None, source: str, tags: list[str], channel: str, thread_key: str, chat_name: str, sync: bool = True) -> dict:
        row = {
            "id": len(self.visual_rows) + 1,
            "channel": channel,
            "thread_key": thread_key or chat_name,
            "chat_name": chat_name or thread_key,
            "scene_summary": note or "visual memory anchor",
            "objects": ["apple", "wine"],
            "text_ocr": note or "",
            "mood_imagery": "warm still life",
            "thread_relevance": 0.78,
            "visual_anchors": [note or "苹果和酒"],
        }
        self.visual_rows.append(row)
        return {
            "status": "ok",
            "artifact": self.ingest_artifact(path, note=note, source=source, tags=tags, dry_run=False),
            "visual_memory": dict(row),
            "graph_sync": {"status": "ok", "id": row["id"]},
            "vector_sync": {"status": "ok", "document_count": 1},
            "activation_sync": {"status": "ok"},
        }

    def drain_visual_ingest_queue(self, *, limit: int = 1) -> dict:
        return {"status": "blocked", "blocked_reason": "queue_empty", "processed": 0, "limit": limit}

    def archive_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict | None = None,
        dry_run: bool = False,
    ) -> dict:
        record = {
            "user_text": user_text,
            "reply": reply,
            "source": source,
            "tags": tags,
            "turn_id": turn_id,
            "metadata": metadata or {},
            "dry_run": dry_run,
        }
        self.archived_records.append(record)
        return record

    def promote_ready_candidates(self, limit: int = 8) -> dict:
        return {"promoted": [], "skipped": [], "remaining_candidates": 0}

    def run_dream_cycle(self, *, sample_size: int = 6, seed: str | None = None, dry_run: bool = False) -> dict:
        return {"seed": seed or "fake-seed", "sampled_archive_ids": [], "callback_added": 0, "thought_added": 0}

    def run_think_cycle(self, *, sample_size: int = 4, seed: str | None = None, dry_run: bool = False) -> dict:
        return {"seed": seed or "fake-think", "sampled_archive_ids": [], "thought_added": 0, "thoughts": []}

    def run_reflect_cycle(self, *, window_hours: float = 12.0, dry_run: bool = False) -> dict:
        return {"window_hours": window_hours, "recent_thought_count": 0, "candidate_added": 0, "thought_added": 0}

    def run_initiative_cycle(self, *, dry_run: bool = False) -> dict:
        return {
            "status": "ok",
            "dry_run": dry_run,
            "staged": len(self.initiatives),
            "initiative_added": len(self.initiatives),
            "initiatives": list(self.initiatives),
            "candidates": self.list_initiative_market(limit=8),
        }

    def list_callback_candidates(self, *, limit: int = 12) -> list[dict]:
        return []

    def list_thoughts(self, *, limit: int = 12) -> list[dict]:
        return self.thoughts[-limit:]

    def list_initiative_candidates(self, *, limit: int = 12) -> list[dict]:
        return self.list_initiative_market(limit=limit)

    def list_initiative_market(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8, statuses=None) -> list[dict]:
        rows = list(self.sidecar_packet("", context={}).get("initiative_candidates", []))
        for index, item in enumerate(self.initiatives, start=len(rows) + 1):
            rows.append(
                {
                    "id": index,
                    "candidate_type": item.get("candidate_type", "contact_ping"),
                    "channel": item.get("channel", channel),
                    "thread_key": item.get("thread_key", thread_key or ""),
                    "chat_name": item.get("chat_name", chat_name or ""),
                    "why_now": item.get("reason", "thread still warm"),
                    "drive_source": item.get("drive_source", "seek_contact"),
                    "value_rationale": item.get("value_rationale", "relational priority stays above avoid risk"),
                    "send_allowed": bool(item.get("send_allowed", True)),
                    "initiative_confidence": float(item.get("initiative_confidence", 0.0) or 0.0),
                    "gate_hint": item.get("gate_hint", ""),
                    "override_priority": float(item.get("override_priority", item.get("initiative_confidence", 0.0)) or 0.0),
                    "status": item.get("status", "candidate"),
                    "priority": item.get("priority", 50),
                    "prompt": item.get("prompt", ""),
                    "metadata": dict(item.get("metadata", {})),
                }
            )
        normalized_thread_key = str(thread_key or "").strip()
        normalized_chat_name = str(chat_name or "").strip()
        filtered = []
        for row in rows:
            row_thread = str(row.get("thread_key", "")).strip()
            row_chat = str(row.get("chat_name", "")).strip()
            if normalized_thread_key and row_thread not in {normalized_thread_key, f"wechat:{normalized_thread_key}"}:
                continue
            if normalized_chat_name and row_chat != normalized_chat_name:
                continue
            if str(row.get("channel", channel)).strip() != channel:
                continue
            filtered.append(row)
        return filtered[:limit]

    def subject_state(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> dict:
        packet = self.sidecar_packet("", context={})
        return {
            "affect_state": dict(packet.get("affect_state", {})),
            "drive_state": dict(packet.get("drive_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "resistance_posture": dict(packet.get("resistance_posture", {})),
            "outcome_memory": dict(packet.get("outcome_memory", {})),
            "world_state": dict(packet.get("world_state", {})),
        }

    def intent_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", query: str = "") -> dict:
        packet = self.sidecar_packet(query, context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel})
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
            "intent_state": dict(packet.get("intent_state", {})),
            "intent_state_v2": dict(packet.get("intent_state_v2", packet.get("intent_state", {}))),
            "intent_state_v3": dict(packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {})))),
            "intent_state_v4": dict(packet.get("intent_state_v4", packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {}))))),
            "selected_action": dict(packet.get("selected_action", {})),
            "expression_budget": int(packet.get("expression_budget", 0) or 0),
            "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
            "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0))) or 0),
            "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
            "world_state": dict(packet.get("world_state", {})),
            "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
            "predicted_best_outcome": dict(packet.get("predicted_best_outcome", {})),
            "predicted_worst_outcome": dict(packet.get("predicted_worst_outcome", {})),
            "uncertainty_level": float(packet.get("uncertainty_level", 0.0) or 0.0),
            "autobiographical_state": dict(packet.get("autobiographical_state", {})),
            "goal_state": dict(packet.get("goal_state", {})),
            "goal_alignment": dict(packet.get("goal_alignment", {})),
            "identity_consistency": dict(packet.get("identity_consistency", {})),
            "chapter_relevance": str(packet.get("chapter_relevance", "")),
            "self_narrative_hint": str(packet.get("self_narrative_hint", "")),
        }

    def action_market(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", query: str = "", limit: int = 8) -> dict:
        packet = self.sidecar_packet(query, context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel})
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
            "action_market": list(packet.get("action_market", []))[:limit],
            "action_market_v2": list(packet.get("action_market_v2", packet.get("action_market", [])))[:limit],
            "action_market_v3": list(packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", []))))[:limit],
            "action_market_v4": list(packet.get("action_market_v4", packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", [])))))[:limit],
            "selected_action": dict(packet.get("selected_action", {})),
            "expression_budget": int(packet.get("expression_budget", 0) or 0),
            "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
            "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0))) or 0),
            "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
            "world_state": dict(packet.get("world_state", {})),
            "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
            "goal_alignment": dict(packet.get("goal_alignment", {})),
            "identity_consistency": dict(packet.get("identity_consistency", {})),
            "roadmap_registry": self.roadmap_registry(),
        }

    def trace_action_selection(self, *, query: str, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8) -> dict:
        packet = self.sidecar_packet(query, context={"thread_key": thread_key, "chat_name": chat_name, "channel": channel})
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
            "intent_state": dict(packet.get("intent_state", {})),
            "intent_state_v2": dict(packet.get("intent_state_v2", packet.get("intent_state", {}))),
            "intent_state_v3": dict(packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {})))),
            "intent_state_v4": dict(packet.get("intent_state_v4", packet.get("intent_state_v3", packet.get("intent_state_v2", packet.get("intent_state", {}))))),
            "action_market": list(packet.get("action_market", []))[:limit],
            "action_market_v2": list(packet.get("action_market_v2", packet.get("action_market", [])))[:limit],
            "action_market_v3": list(packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", []))))[:limit],
            "action_market_v4": list(packet.get("action_market_v4", packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", [])))))[:limit],
            "selected_action": dict(packet.get("selected_action", {})),
            "expression_budget": int(packet.get("expression_budget", 0) or 0),
            "expression_budget_v2": int(packet.get("expression_budget_v2", packet.get("expression_budget", 0)) or 0),
            "expression_budget_v3": int(packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0))) or 0),
            "expression_budget_v4": int(packet.get("expression_budget_v4", packet.get("expression_budget_v3", packet.get("expression_budget_v2", packet.get("expression_budget", 0)))) or 0),
            "silence_reason": str(packet.get("silence_reason", "")),
            "defer_reason": str(packet.get("defer_reason", "")),
            "lookup_reason": str(packet.get("lookup_reason", "")),
            "action_rationale": str(packet.get("action_rationale", "")),
            "deliberation_trace_id": str(packet.get("deliberation_trace_id", "")),
            "affect_state": dict(packet.get("affect_state", {})),
            "drive_state": dict(packet.get("drive_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "game_state": dict(packet.get("game_state", {})),
            "self_model": dict(packet.get("self_model", {})),
            "autobiographical_state": dict(packet.get("autobiographical_state", {})),
            "goal_state": dict(packet.get("goal_state", {})),
            "goal_alignment": dict(packet.get("goal_alignment", {})),
            "identity_consistency": dict(packet.get("identity_consistency", {})),
            "chapter_relevance": str(packet.get("chapter_relevance", "")),
            "self_narrative_hint": str(packet.get("self_narrative_hint", "")),
            "world_state": dict(packet.get("world_state", {})),
            "counterfactual_summary": dict(packet.get("counterfactual_summary", {})),
            "predicted_best_outcome": dict(packet.get("predicted_best_outcome", {})),
            "predicted_worst_outcome": dict(packet.get("predicted_worst_outcome", {})),
            "selected_prediction": dict(packet.get("selected_prediction", {})),
            "uncertainty_level": float(packet.get("uncertainty_level", 0.0) or 0.0),
            "counterfactual_set": list(packet.get("action_market_v4", packet.get("action_market_v3", packet.get("action_market_v2", packet.get("action_market", [])))))[: min(limit, 3)],
            "roadmap_registry": self.roadmap_registry(),
        }

    def update_subject_state(self, *, thread_key: str, chat_name: str, channel: str = "wechat", **changes) -> dict:
        return {"status": "ok", "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "changes": changes}

    def record_action_selection(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        message_id: str,
        query: str,
        intent_state: dict,
        action_market: list[dict],
        selected_action: dict,
        expression_budget: int,
        silence_reason: str = "",
        defer_reason: str = "",
        action_rationale: str = "",
        world_state: dict | None = None,
    ) -> dict:
        payload = {
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "message_id": message_id,
            "query": query,
            "intent_state": dict(intent_state),
            "action_market": list(action_market),
            "selected_action": dict(selected_action),
            "expression_budget": int(expression_budget),
            "silence_reason": str(silence_reason),
            "defer_reason": str(defer_reason),
            "action_rationale": str(action_rationale),
            "world_state": dict(world_state or self._world_state_for(thread_key=thread_key, chat_name=chat_name, channel=channel)),
        }
        self.action_selections.append(payload)
        return {"status": "ok", **payload}

    def record_consciousness_entry(
        self,
        *,
        channel: str,
        thread_key: str,
        chat_name: str,
        message_id: str = "",
        event_row_id: int | None = None,
        entry_type: str,
        selected_action: str = "",
        payload: dict | None = None,
    ) -> dict:
        thread_key = self._canonical_wechat_thread_key(thread_key, chat_name, channel)
        entry = {
            "id": len(self.consciousness_entries) + 1,
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "message_id": message_id,
            "event_row_id": event_row_id,
            "entry_type": entry_type,
            "selected_action": selected_action,
            "payload": dict(payload or {}),
        }
        self.consciousness_entries.append(entry)
        return {"status": "ok", **entry}

    def consciousness_ledger(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 20) -> dict:
        normalized_thread = self._canonical_wechat_thread_key(str(thread_key or chat_name or "").strip(), str(chat_name or thread_key or "").strip(), channel)
        entries = [
            dict(item)
            for item in self.consciousness_entries
            if str(item.get("channel", channel)).strip() == channel
            and (not normalized_thread or str(item.get("thread_key", "")).strip() == normalized_thread)
        ]
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "entries": entries[-max(1, int(limit)):],
        }

    def trace_deliberation_ledger(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 20) -> dict:
        return self.consciousness_ledger(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def add_initiative_candidate(self, **payload) -> dict:
        return {"status": "ok", "id": payload.get("id", 1), **payload}

    def update_initiative_candidate(self, candidate_id: int, *, status: str, note: str = "", payload: dict | None = None, metadata: dict | None = None, **kwargs) -> dict:
        return {
            "status": "ok",
            "id": candidate_id,
            "candidate_status": status,
            "note": note,
            "payload": dict(payload or {}),
            "metadata": dict(metadata or {}),
            **dict(kwargs),
        }

    def record_outcome_appraisal(self, *, thread_key: str, chat_name: str, channel: str = "wechat", **payload) -> dict:
        thread_key = self._canonical_wechat_thread_key(thread_key, chat_name, channel)
        record = {"status": "ok", "thread_key": thread_key, "chat_name": chat_name, "channel": channel, **payload}
        self.outcome_appraisals.append(record)
        return record

    def latest_outcome_memory(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> dict:
        return dict(self.sidecar_packet("", context={}).get("outcome_memory", {}))

    def appraise_outcome(self, *, channel: str, thread_key: str, chat_name: str, **payload) -> dict:
        return self.record_outcome_appraisal(channel=channel, thread_key=thread_key, chat_name=chat_name, **payload)

    def trace_resistance(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", query: str = "") -> dict:
        packet = self.sidecar_packet("", context={})
        return {
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
            "interactional_resistance": float(dict(packet.get("resistance_posture", {})).get("interactional_resistance", 0.0) or 0.0),
            "continuity_defense": float(dict(packet.get("resistance_posture", {})).get("continuity_defense", 0.0) or 0.0),
            "affect_state": dict(packet.get("affect_state", {})),
            "value_state": dict(packet.get("value_state", {})),
            "conflict_state": dict(packet.get("conflict_state", {})),
            "resistance_posture": dict(packet.get("resistance_posture", {})),
        }

    def stream_status(self) -> dict:
        return {
            "db_path": "fake",
            "streams": [],
            "recent_runs": [{"run_type": "stream:self_model_refresh"}],
            "activation_events": [{"id": 1, "contributor": "association_stream"}],
            "stream_influence": {"motifs": ["continuity"]},
            "vector": self.vector_health(),
        }


def close_service_handles(service: HoloReplyService) -> None:
    service.store.close()
    for handler in list(service.logger.handlers):
        handler.close()
        service.logger.removeHandler(handler)


def close_daemon_handles(daemon: HoloDaemon) -> None:
    daemon.store.close()
    for handler in list(daemon.logger.handlers):
        handler.close()
        daemon.logger.removeHandler(handler)


class QueueStoreTests(unittest.TestCase):
    def test_record_inbound_and_enqueue_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            store = QueueStore(db_path)
            try:
                store.initialize()
                message = IncomingMessage(
                    message_id="<a@example.com>",
                    thread_key="<a@example.com>",
                    subject="Hello",
                    sender_email="a@example.com",
                    sender_name="A",
                    body_text="I am tired today.",
                )
                record = store.record_inbound(message)
                self.assertFalse(record["duplicate"])
                job_id = store.enqueue_job(
                    task_type="reply",
                    message_row_id=int(record["message"]["id"]),
                    thread_id=int(record["thread"]["id"]),
                    contact_id=int(record["contact"]["id"]),
                )
                jobs = store.list_due_jobs(limit=10)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["id"], job_id)
            finally:
                store.close()

    def test_initiative_cooldown_fields_are_migrated_and_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            store = QueueStore(db_path)
            try:
                store.initialize()
                contact = store.ensure_contact("wechat:wechat:Nemoqi", "Nemoqi")
                self.assertTrue(store.initiative_available(int(contact["id"]), cooldown_hours=48))
                store.mark_initiative_sent(int(contact["id"]), note="unit")
                self.assertFalse(store.initiative_available(int(contact["id"]), cooldown_hours=48))
            finally:
                store.close()

    def test_load_config_defaults_include_stage9_initiative_gate_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            self.assertEqual(config.autonomy.initiative_cooldown_hours, 12)
            self.assertEqual(config.autonomy.initiative_gate_mode, "conservative")
            self.assertTrue(config.autonomy.main_brain_override_enabled)
            self.assertAlmostEqual(config.autonomy.main_brain_override_min_score, 0.58)
            self.assertAlmostEqual(config.autonomy.initiative_soft_allow_threshold, 0.62)
            self.assertAlmostEqual(config.autonomy.initiative_soft_override_floor, 0.48)

    def test_initialize_merges_legacy_wechat_alias_contacts_and_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            bootstrap = QueueStore(db_path)
            bootstrap.initialize()
            bootstrap.close()

            conn = sqlite3.connect(db_path)
            now = "2026-04-06T00:00:00Z"
            legacy_contact_id = conn.execute(
                """
                INSERT INTO contacts(
                    email, display_name, initiative_enabled, created_at, updated_at, last_inbound_at, last_outbound_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                """,
                ("wechat:wechat:Nemoqi", "Nemoqi", now, now, now, now),
            ).lastrowid
            canonical_contact_id = conn.execute(
                """
                INSERT INTO contacts(
                    email, display_name, initiative_enabled, created_at, updated_at, last_inbound_at, last_outbound_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                """,
                ("wechat:Nemoqi", "Nemoqi", now, now, now, now),
            ).lastrowid
            legacy_thread_id = conn.execute(
                """
                INSERT INTO threads(
                    channel, contact_id, thread_key, subject, codex_session_id, allow_auto_reply, allow_proactive,
                    created_at, updated_at, last_message_at, last_direction
                ) VALUES ('wechat', ?, 'wechat:Nemoqi', 'Nemoqi', 'legacy-session', 1, 1, ?, ?, ?, 'inbound')
                """,
                (legacy_contact_id, now, now, now),
            ).lastrowid
            canonical_thread_id = conn.execute(
                """
                INSERT INTO threads(
                    channel, contact_id, thread_key, subject, codex_session_id, allow_auto_reply, allow_proactive,
                    created_at, updated_at, last_message_at, last_direction
                ) VALUES ('wechat', ?, 'Nemoqi', 'Nemoqi', '', 1, 1, ?, ?, ?, 'outbound')
                """,
                (canonical_contact_id, now, now, now),
            ).lastrowid
            message_row_id = conn.execute(
                """
                INSERT INTO messages(
                    event_id, channel, direction, contact_id, thread_id, message_id,
                    in_reply_to, references_header, subject, body_text, body_html,
                    sender_email, sender_name, recipient_email, payload_json, created_at
                ) VALUES (?, 'wechat', 'inbound', ?, ?, ?, '', '', 'Nemoqi', '你还记得重新上线前吗', '', ?, 'Nemoqi', '', '{}', ?)
                """,
                ("wechat:legacy-msg", legacy_contact_id, legacy_thread_id, "legacy-msg", "wechat:wechat:Nemoqi", now),
            ).lastrowid
            job_id = conn.execute(
                """
                INSERT INTO jobs(
                    task_type, status, priority, message_row_id, thread_id, contact_id,
                    payload_json, available_at, scheduled_at, attempt_count, last_error, sent_message_id, created_at, updated_at
                ) VALUES ('reply', 'pending', 100, ?, ?, ?, '{}', ?, ?, 0, '', '', ?, ?)
                """,
                (message_row_id, legacy_thread_id, legacy_contact_id, now, now, now, now),
            ).lastrowid
            conn.commit()
            conn.close()

            store = QueueStore(db_path)
            try:
                store.initialize()

                contact = store.find_contact("wechat:Nemoqi")
                self.assertIsNotNone(contact)
                contacts = store._fetchall("SELECT * FROM contacts WHERE email LIKE 'wechat:%'")
                self.assertEqual(len(contacts), 1)

                thread = store.find_thread(channel="wechat", thread_key="wechat:Nemoqi")
                self.assertIsNotNone(thread)
                self.assertEqual(thread["thread_key"], "wechat:Nemoqi")
                legacy_lookup = store.find_thread(channel="wechat", thread_key="Nemoqi")
                self.assertIsNotNone(legacy_lookup)
                self.assertEqual(legacy_lookup["thread_key"], "wechat:Nemoqi")
                self.assertEqual(thread["codex_session_id"], "legacy-session")

                merged_message = store._fetchone("SELECT * FROM messages WHERE id = ?", (message_row_id,))
                merged_job = store._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
                self.assertEqual(int(merged_message["thread_id"]), int(thread["id"]))
                self.assertEqual(int(merged_job["thread_id"]), int(thread["id"]))
                self.assertEqual(int(merged_message["contact_id"]), int(contact["id"]))
                self.assertEqual(int(merged_job["contact_id"]), int(contact["id"]))
            finally:
                store.close()

    def test_record_outcome_appraisal_keeps_canonical_wechat_thread_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            graph = MindGraph(root, rag=rm, db_path=root / ".holo_runtime" / "mind_graph.sqlite3")
            try:
                report = graph.record_outcome_appraisal(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    action_type="reply_once",
                    action_ref="turn-1",
                    was_rewarding=0.72,
                    was_ignored=0.04,
                    relational_delta=0.18,
                    identity_delta=0.11,
                    future_initiative_bias=0.62,
                    future_resistance_bias=0.12,
                    metadata={
                        "evidence_refs": ["unit:reply-1"],
                        "usage_total_tokens": 18,
                        "selected_prediction": {
                            "predicted_relational_delta": 0.16,
                            "predicted_identity_delta": 0.08,
                            "predicted_response_quality": 0.71,
                            "predicted_risk": 0.14,
                        },
                    },
                )
                subject = graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                appraisal = graph.conn.execute(
                    "SELECT thread_key, action_ref, metadata_json FROM outcome_appraisals ORDER BY id DESC LIMIT 1"
                ).fetchone()

                self.assertEqual(report["status"], "ok")
                self.assertEqual(subject["thread_key"], "wechat:Nemoqi")
                self.assertEqual(str(appraisal["thread_key"]), "wechat:Nemoqi")
                self.assertEqual(str(appraisal["action_ref"]), "turn-1")
                self.assertIn("unit:reply-1", json.loads(str(appraisal["metadata_json"]))["evidence_refs"])
            finally:
                graph.close()


class CodexRunnerTests(unittest.TestCase):
    def test_runner_applies_model_and_low_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_model = "gpt-5.4"
            config.runtime.codex_reasoning_effort = "low"
            runner = CodexRunner(config)

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                output = Path(tmpdir) / "reply.txt"

                def fake_run(command, **kwargs):
                    Path(kwargs["cwd"])  # touch for coverage sanity
                    Path(command[command.index("-o") + 1]).write_text("咱在。", encoding="utf-8")
                    completed = mock.Mock()
                    completed.returncode = 0
                    completed.stdout = '{"type":"thread.started","thread_id":"thread-123"}\n'
                    completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                result = runner.run("在吗")

            self.assertEqual(result.reply_text, "咱在。")
            command = run_mock.call_args.args[0]
            self.assertIn("-m", command)
            self.assertIn("gpt-5.4", command)
            self.assertIn('-c', command)
            self.assertIn('model_reasoning_effort="low"', command)

    def test_runner_resume_inserts_runtime_options_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_model = "gpt-5.4"
            config.runtime.codex_reasoning_effort = "low"
            runner = CodexRunner(config)

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                def fake_run(command, **kwargs):
                    Path(command[command.index("-o") + 1]).write_text("咱在。", encoding="utf-8")
                    completed = mock.Mock()
                    completed.returncode = 0
                    completed.stdout = ""
                    completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                runner.run("在吗", session_id="thread-xyz")

            command = run_mock.call_args.args[0]
            self.assertEqual(command[:4], ["codex", "exec", "resume", "-m"])
            self.assertIn('model_reasoning_effort="low"', command)

    def test_runner_falls_back_to_fresh_exec_when_resume_rollout_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_command_prefix = ("codex",)
            runner = CodexRunner(config)
            calls: list[list[str]] = []

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                def fake_run(command, **kwargs):
                    calls.append(list(command))
                    output_path = Path(command[command.index("-o") + 1])
                    completed = mock.Mock()
                    if "resume" in command:
                        output_path.write_text("", encoding="utf-8")
                        completed.returncode = 1
                        completed.stdout = ""
                        completed.stderr = "Error: thread/resume failed: no rollout found for thread id old-thread\n"
                    else:
                        output_path.write_text("咱在。", encoding="utf-8")
                        completed.returncode = 0
                        completed.stdout = '{"type":"thread.started","thread_id":"thread-new"}\n'
                        completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                result = runner.run("在吗", session_id="old-thread")

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][:3], ["codex", "exec", "resume"])
            self.assertEqual(calls[1][:2], ["codex", "exec"])
            self.assertNotIn("resume", calls[1])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.reply_text, "咱在。")
            self.assertEqual(result.session_id, "thread-new")


class MaildirGatewayTests(unittest.TestCase):
    def test_poll_ack_and_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            incoming = gateway.inbox_dir / "hello.json"
            incoming.write_text(
                json.dumps(
                    {
                        "message_id": "<msg-1>",
                        "thread_key": "<msg-1>",
                        "subject": "Hello",
                        "sender_email": "friend@example.com",
                        "body_text": "Hello there",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            messages = gateway.poll_inbox(limit=10)
            self.assertEqual(len(messages), 1)
            gateway.acknowledge(messages[0])
            self.assertFalse(incoming.exists())
            self.assertEqual(len(list(gateway.processed_dir.iterdir())), 1)

            remote_id = gateway.send_reply(
                OutgoingMessage(
                    recipient_email="friend@example.com",
                    subject="Hello",
                    body_text="咱在这儿。",
                    thread_key="<msg-1>",
                )
            )
            self.assertTrue(remote_id)
            self.assertEqual(len(list(gateway.outbox_dir.iterdir())), 1)


class ReplyBubbleTests(unittest.TestCase):
    def test_long_fast_wechat_reply_splits_into_two_bubbles_instead_of_truncating(self) -> None:
        attention = build_attention_state("好家伙", channel="wechat")
        bubbles = build_reply_bubbles(
            "好家伙这两个字，像把狼尾巴都惊出来了 😏 那咱就先把耳朵竖起来听你往下说",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "medium"},
            route="fast",
            target_count=1,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        joined = " ".join(b.text for b in bubbles)
        self.assertIn("那咱就先把", joined)

    def test_build_reply_bubbles_uses_utterance_plan_purposes(self) -> None:
        attention = build_attention_state("那今晚怎么办", channel="wechat")
        bubbles = build_reply_bubbles(
            "先缓一下。真正卡住的是今晚这口气。等咱陪你把它拆开。",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "low"},
            utterance_plan={"beats": ["receive", "pivot", "landing"]},
            route="main",
            target_count=2,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        self.assertEqual(bubbles[0].purpose, "receive")
        self.assertIn(bubbles[1].purpose, {"pivot", "landing"})

    def test_build_reply_bubbles_avoids_mid_phrase_hard_split(self) -> None:
        attention = build_attention_state("我有点困惑", channel="wechat")
        bubbles = build_reply_bubbles(
            "是啊，困惑本来就正常，像走在雾里，哪有一直看得清的道理 😌 你先别急着把自己逼得太紧，咱陪你把这一阵雾慢慢捋开。",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "low"},
            utterance_plan={"beats": ["receive", "landing"]},
            route="fast",
            target_count=2,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        joined = "".join(b.text for b in bubbles)
        self.assertIn("道理", joined)
        self.assertFalse(any(b.text.endswith("道") for b in bubbles))
        self.assertFalse(any(b.text.startswith("理") for b in bubbles))

    def test_build_turn_plan_can_expand_bubble_target_for_playful_companionship(self) -> None:
        attention = AttentionState(
            primary_focus="companionship",
            secondary_focus="tone",
            reply_goal="answer_then_extend",
            pressure_level="low",
            salience_sources=["question"],
        )
        context = TurnContext(
            channel="wechat",
            thread_key="Nemoqi",
            chat_name="Nemoqi",
            sender="Nemoqi",
            user_text="咱别总两句就停，继续顺着这点苹果酒意和打趣往下聊聊看",
            sidecar={"tier": "fast"},
            attention_state=attention,
            emotion_state={"playfulness": "high"},
            history=[],
            mind_packet={"tier": "fast"},
            utterance_plan={"beats": ["receive", "pivot", "landing", "echo"]},
            persona_blend={"playfulness": 0.78},
            game_state={"initiative_window": 0.64, "teasing_tolerance": 0.61},
        )
        plan = build_turn_plan(context, load_config(repo_root=tempfile.mkdtemp()))
        self.assertGreaterEqual(plan.bubble_target, 4)

    def test_coerce_helper_artifact_path_has_explicit_directions(self) -> None:
        wsl_path = "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history.md"
        windows_path = r"D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history.md"
        self.assertEqual(_coerce_helper_artifact_path_for_holo_host(windows_path), wsl_path)
        self.assertEqual(_coerce_helper_artifact_path_for_holo_host(wsl_path), wsl_path)
        self.assertEqual(_coerce_helper_artifact_path_for_windows_helper(wsl_path).lower(), windows_path.lower())
        self.assertEqual(_coerce_helper_artifact_path(windows_path), wsl_path)

    def test_coerce_helper_artifact_path_repairs_malformed_windows_prefixed_mnt_path(self) -> None:
        raw = r"D:\mnt\d\Holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\demo.md"
        self.assertEqual(
            _coerce_helper_artifact_path_for_holo_host(raw),
            "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history_exports/demo.md",
        )
        self.assertEqual(
            _coerce_helper_artifact_path_for_windows_helper(raw).lower(),
            r"d:\holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\demo.md".lower(),
        )

    def test_poll_inbox_skips_corrupt_json_mail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            (gateway.inbox_dir / "broken.json").write_text("{bad", encoding="utf-8")
            (gateway.inbox_dir / "ok.json").write_text(
                json.dumps(
                    {
                        "message_id": "<msg-2>",
                        "thread_key": "<msg-2>",
                        "subject": "Hello again",
                        "sender_email": "friend@example.com",
                        "body_text": "Still here",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            messages = gateway.poll_inbox(limit=10)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].message_id, "<msg-2>")


class PolicyTests(unittest.TestCase):
    def test_high_risk_blocks_auto_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="Can you help me with tax advice?",
                reply_text="Sure.",
                recent_outbound_count=0,
                is_existing_thread=True,
                is_proactive=False,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "high_risk_content")

    def test_wechat_existing_thread_has_higher_auto_reply_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="在吗",
                reply_text="咱在。",
                recent_outbound_count=10,
                is_existing_thread=True,
                is_proactive=False,
                channel="wechat",
            )
            self.assertTrue(decision.allowed)

    def test_wechat_existing_thread_allows_lively_chat_bursts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="怎么不理我了😭",
                reply_text="咱在，刚刚没接稳。",
                recent_outbound_count=52,
                is_existing_thread=True,
                is_proactive=False,
                channel="wechat",
            )
            self.assertTrue(decision.allowed)


class DaemonFlowTests(unittest.TestCase):
    def test_daemon_cycle_sends_reply_and_observes_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            message_path = gateway.inbox_dir / "turn.json"
            message_path.write_text(
                json.dumps(
                    {
                        "message_id": "<turn-1>",
                        "thread_key": "<turn-1>",
                        "subject": "Checking in",
                        "sender_email": "friend@example.com",
                        "body_text": "I am under a lot of pressure lately.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Take a breath first.")
            memory = FakeMemory()
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["ingested"], ["queued:<turn-1>"])
                self.assertTrue(any(item.startswith("sent:") for item in result["processed_jobs"]))
                self.assertEqual(len(memory.observed), 1)
                self.assertEqual(memory.observed_records[0]["turn_id"], "<turn-1>")
                self.assertEqual(memory.observed_records[0]["metadata"]["thread_key"], "<turn-1>")
                self.assertEqual(memory.observed_records[0]["metadata"]["channel"], "email")
                jobs = store.list_jobs(limit=10)
                self.assertEqual(jobs[0]["status"], "sent")
                self.assertEqual(len(list(gateway.outbox_dir.iterdir())), 1)
            finally:
                close_daemon_handles(daemon)
    def test_daemon_cycle_schedules_and_queues_whitelisted_wechat_initiative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertTrue(result["initiative"]["scheduled_job_ids"])
                self.assertTrue(any(item.startswith("queued:") for item in result["processed_jobs"]))
                queued = sorted(send_queue_dir.glob("*.json"))
                self.assertEqual(len(queued), 1)
                payload = json.loads(queued[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["chat_name"], "Nemoqi")
                self.assertTrue(str(payload["text"]).strip())
            finally:
                close_daemon_handles(daemon)

    def test_daemon_cycle_blocks_initiative_when_probe_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            gateway = MaildirGateway(config)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.game_state_data = {
                "trust_score": 0.2,
                "teasing_tolerance": 0.2,
                "pressure_level": 0.9,
                "initiative_window": 0.1,
                "correction_sensitivity": 0.4,
            }
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["initiative"]["scheduled_job_ids"], [])
                self.assertTrue(result["initiative"]["blocked_candidates"])
                self.assertFalse(send_queue_dir.exists() and list(send_queue_dir.glob("*.json")))
            finally:
                close_daemon_handles(daemon)

    def test_initiative_probe_reports_soft_block_override_in_adaptive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.autonomy.initiative_gate_mode = "adaptive"
            store = QueueStore(config.runtime.db_path)
            gateway = MaildirGateway(config)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.brain_mode = "full_brain"
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                contact = store.ensure_contact("wechat:wechat:Nemoqi", "Nemoqi")
                store.ensure_thread(
                    channel="wechat",
                    contact_id=int(contact["id"]),
                    thread_key="wechat:Nemoqi",
                    subject="Nemoqi",
                )
                probe = daemon.initiative_probe(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat", query="initiative_probe")
                self.assertEqual(probe["gate_mode"], "adaptive")
                self.assertEqual(probe["gate_level"], "soft_block")
                self.assertTrue(probe["override_eligible"])
                self.assertFalse(probe["allowed"])
                self.assertIn("soft_gate_score", probe)
            finally:
                close_daemon_handles(daemon)

    def test_daemon_cycle_adaptive_mode_can_send_soft_block_with_main_brain_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            config.autonomy.initiative_gate_mode = "adaptive"
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.brain_mode = "full_brain"
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                    "initiative_confidence": 0.72,
                    "gate_hint": "warm",
                    "override_priority": 0.72,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertTrue(result["initiative"]["scheduled_job_ids"])
                self.assertTrue(any(item.startswith("queued:") for item in result["processed_jobs"]))
                queued = sorted(send_queue_dir.glob("*.json"))
                self.assertEqual(len(queued), 1)
                status = daemon.initiative_status(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat", limit=5)
                self.assertIn("gate_level_summary", status)
                self.assertIn("override_applied_count", status)
            finally:
                close_daemon_handles(daemon)

    def test_daemon_cycle_adaptive_mode_keeps_soft_block_blocked_when_override_confidence_is_low(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            config.autonomy.initiative_gate_mode = "adaptive"
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.brain_mode = "full_brain"
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                    "initiative_confidence": 0.41,
                    "gate_hint": "cold",
                    "override_priority": 0.41,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["initiative"]["scheduled_job_ids"], [])
                self.assertTrue(result["initiative"]["blocked_candidates"])
                self.assertFalse(send_queue_dir.exists() and list(send_queue_dir.glob("*.json")))
            finally:
                close_daemon_handles(daemon)

    def test_daemon_cycle_adaptive_mode_does_not_override_hard_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            config.autonomy.initiative_gate_mode = "adaptive"
            config.autonomy.initiative_probe_enabled = False
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.brain_mode = "full_brain"
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                    "initiative_confidence": 0.82,
                    "gate_hint": "warm",
                    "override_priority": 0.82,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["initiative"]["scheduled_job_ids"], [])
                self.assertTrue(result["initiative"]["blocked_candidates"])
                self.assertEqual(result["initiative"]["blocked_candidates"][0]["reason"], "initiative_probe_disabled")
                self.assertFalse(send_queue_dir.exists() and list(send_queue_dir.glob("*.json")))
            finally:
                close_daemon_handles(daemon)
    def test_daemon_reply_job_passes_richer_metadata_to_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            contact = store.ensure_contact("friend@example.com", "Friend")
            thread, _ = store.ensure_thread(
                channel="email",
                contact_id=int(contact["id"]),
                thread_key="thread-1",
                subject="Checking in",
            )
            message = IncomingMessage(
                message_id="<turn-1>",
                thread_key="thread-1",
                subject="Checking in",
                sender_email="friend@example.com",
                sender_name="Friend",
                body_text="I am under a lot of pressure lately.",
                metadata={"source_ref": "maildir/inbox"},
            )
            record = store.record_inbound(message)
            store.enqueue_job(
                task_type="reply",
                message_row_id=int(record["message"]["id"]),
                thread_id=int(thread["id"]),
                contact_id=int(contact["id"]),
                payload={"source": "incoming_mail"},
            )

            runner = FakeRunner("Take a breath first.")
            memory = FakeMemory()
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertTrue(any(item.startswith("sent:") for item in result["processed_jobs"]))
                self.assertEqual(len(memory.observed_records), 1)
                record = memory.observed_records[0]
                self.assertEqual(record["turn_id"], "<turn-1>")
                self.assertEqual(record["metadata"]["thread_key"], "thread-1")
                self.assertEqual(record["metadata"]["message_id"], "<turn-1>")
                self.assertEqual(record["metadata"]["outbound_message_id"], store.list_jobs(limit=10)[0]["sent_message_id"])
                self.assertEqual(record["metadata"]["sender_email"], "friend@example.com")
                self.assertEqual(record["metadata"]["sender_name"], "Friend")
                self.assertEqual(record["metadata"]["subject"], "Checking in")
            finally:
                close_daemon_handles(daemon)
class ReplyServiceTests(unittest.TestCase):
    def test_shape_wechat_reply_strips_stock_opener_and_stays_short(self) -> None:
        text = "咱先把这口气守住。也是，微信里一长就像在写公函。你随手扔一句来就好，咱接着。"
        shaped = shape_wechat_reply(text)
        self.assertNotIn("咱先把这口气守住", shaped)
        self.assertTrue(len(shaped) < len(text))
        self.assertIn("微信里一长就像在写公函", shaped)
        self.assertFalse(shaped.endswith("。"))

    def test_shape_wechat_reply_does_not_cut_mid_clause(self) -> None:
        text = "比如会记这些：你要咱把“咱”留住，别掉回助手腔；微信里话短些，少点公式化开头，标点别太端着，emoji也可以学 再往里一点，还会记你更想要真诚陪伴，不爱空话；要是聊到工作、前途、账目这种压人的题，先给你松口气，再谈办法。"
        shaped = shape_wechat_reply(text)
        self.assertNotIn("压人的。", shaped)
        self.assertTrue(len(shaped) <= 72)

    def test_reply_service_uses_codex_runner_and_tracks_thread_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Let us steady the tone first.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                first = service.handle_reply(
                    {
                        "chat_name": "TestContact",
                        "sender": "TestContact",
                        "text": "I have been under a lot of pressure.",
                        "channel": "wechat",
                        "ts": 1,
                    }
                )
                self.assertEqual(first["action"], "reply")
                self.assertEqual(first["session_id"], "thread-123")
                self.assertTrue(runner.calls)
                self.assertEqual(len(memory.observed), 1)

                second = service.handle_reply(
                    {
                        "chat_name": "TestContact",
                        "sender": "TestContact",
                        "text": "What should I do tonight?",
                        "channel": "wechat",
                        "ts": 2,
                    }
                )
                self.assertEqual(second["action"], "reply")
                self.assertEqual(runner.calls[1][1], "thread-123")
                self.assertEqual(memory.sidecar_requests[-1]["context"]["chat_name"], "TestContact")
                self.assertEqual(memory.sidecar_requests[-1]["context"]["thread_key"], "wechat:TestContact")
            finally:
                close_service_handles(service)
    def test_reply_service_uses_shorter_wechat_prompt_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("咱先把这口气守住。也是，微信里一长就像在写公函。你随手扔一句来就好，咱接着。")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "可以简短一点",
                        "channel": "wechat",
                        "message_id": "wechat-short-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
                prompt, _session = runner.calls[-1]
                self.assertIn("这是微信聊天。默认只回 1 到 2 句", prompt)
                self.assertNotIn("咱先把这口气守住", result["text"])
                self.assertTrue(len(result["text"]) <= 72)
            finally:
                close_service_handles(service)

    def test_reply_service_prompt_keeps_multifacet_holo_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("那咱就先不端着，顺着这句往下接。")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "苹果和酒这类话题，你会怎么接？",
                        "channel": "wechat",
                        "message_id": "wechat-persona-balance-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
                prompt, _session = runner.calls[-1]
                self.assertIn("赫萝不是只剩稳重那一面", prompt)
                self.assertIn("别默认成长辈、说教者或心理咨询口气", prompt)
            finally:
                close_service_handles(service)

    def test_reply_service_returns_structured_bubbles_and_attention_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Pause for a breath, then speak slowly.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "I am tired.",
                        "channel": "wechat",
                        "message_id": "wechat-bubble-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertGreaterEqual(len(result["bubbles"]), 1)
                self.assertIn("attention_state", result)
                self.assertIn("turn_plan", result)
                self.assertIn("timing_ms", result)
                self.assertIn("processor", result)
                self.assertIn("route", result)
                self.assertEqual(result["turn_plan"]["route"], result["route"])
                self.assertIn("processor_ms", result["timing_ms"])
                self.assertIn("utterance_plan", result)
            finally:
                close_service_handles(service)
    def test_reply_service_ignores_recent_wechat_outbound_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("I am here.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                first = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "You there?",
                        "channel": "wechat",
                        "message_id": "wechat-echo-in-1",
                        "metadata": {"visible_digest": "digest-a"},
                    }
                )
                self.assertEqual(first["action"], "reply")

                echoed = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": first["text"],
                        "channel": "wechat",
                        "message_id": "wechat-echo-in-2",
                        "metadata": {"visible_digest": "digest-b", "direction": "unknown"},
                    }
                )
                self.assertEqual(echoed["action"], "ignore")
                self.assertEqual(echoed["reason"], "outbound_echo")
            finally:
                close_service_handles(service)
    def test_reply_service_passes_richer_metadata_to_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Let us ease the pressure first.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "I only wanted someone beside me.",
                        "channel": "wechat",
                        "message_id": "wechat-msg-1",
                        "thread_key": "wechat:Nemoqi",
                        "source_ref": "window:weixin",
                        "is_group": False,
                        "mentioned": True,
                        "metadata": {"capture_path": "C:/capture.png"},
                        "ts": 1,
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertEqual(len(memory.observed_records), 1)
                record = memory.observed_records[0]
                self.assertEqual(record["turn_id"], "wechat-msg-1")
                self.assertEqual(record["metadata"]["chat_name"], "Nemoqi")
                self.assertEqual(record["metadata"]["sender"], "Nemoqi")
                self.assertEqual(record["metadata"]["channel"], "wechat")
                self.assertEqual(record["metadata"]["thread_key"], "wechat:Nemoqi")
                self.assertEqual(record["metadata"]["message_id"], "wechat-msg-1")
                self.assertEqual(record["metadata"]["source_ref"], "window:weixin")
                self.assertEqual(record["metadata"]["capture_path"], "C:/capture.png")
                self.assertTrue(record["metadata"]["mentioned"])
                self.assertFalse(record["metadata"]["is_group"])
                self.assertEqual(record["metadata"]["utterance_plan"]["beats"], ["receive", "pivot", "landing"])
                self.assertEqual(memory.sidecar_requests[0]["context"]["thread_key"], "wechat:Nemoqi")
                self.assertEqual(memory.sidecar_requests[0]["context"]["incoming_thread_key"], "wechat:Nemoqi")
            finally:
                close_service_handles(service)
    def test_reply_service_refreshes_wechat_history_before_recall_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("咱还记得")
            memory = FakeMemory()
            memory.sidecar_tier = "recall"
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            service.refresh_wechat_history = mock.Mock(return_value={"status": "ingested", "message_count": 12})  # type: ignore[method-assign]

            result = service.handle_reply(
                {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "你还记得重新上线前吗",
                    "channel": "wechat",
                    "message_id": "wechat-recall-1",
                }
            )

            self.assertEqual(result["action"], "reply")
            self.assertGreaterEqual(len(memory.sidecar_requests), 1)
            self.assertTrue(memory.recalled)
            close_service_handles(service)

    def test_reply_probe_compares_graph_led_and_legacy_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            runner = FakeRunner("咱记得一些，线头还在。")
            memory = FakeMemory()
            graph_packet = memory.sidecar_packet("你还记得重新上线前吗")
            graph_packet.update(
                {
                    "tier": "deep_recall",
                    "retrieval_mode": "graph-led",
                    "graph_confidence": 0.92,
                    "activation_trace_ids": ["archive:turn-1"],
                    "selected_memory_ids": ["archive:turn-1"],
                    "episodic_recall": {"lines": ["重新上线前一直在救回速度"], "items": []},
                }
            )
            legacy_packet = dict(graph_packet)
            legacy_packet.update(
                {
                    "retrieval_mode": "legacy",
                    "graph_confidence": 0.0,
                    "fallback_lanes": ["relationship_state", "episodic_recall", "recent_dialogue_window", "consciousness_stream"],
                    "activation_trace_ids": [],
                    "selected_memory_ids": [],
                    "episodic_recall": {"lines": [], "items": []},
                }
            )
            memory.sidecar_packet = mock.Mock(return_value=graph_packet)  # type: ignore[method-assign]
            memory.legacy_sidecar_packet = mock.Mock(return_value=legacy_packet)  # type: ignore[method-assign]
            service = HoloReplyService(config, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)

            report = service.reply_probe(
                {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "你还记得重新上线前吗",
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                }
            )

            self.assertEqual(report["graph_led"]["retrieval_mode"], "graph-led")
            self.assertEqual(report["legacy"]["retrieval_mode"], "legacy")
            self.assertTrue(runner.task_calls)
            self.assertEqual(runner.task_calls[0]["task_type"], "recall_reconstruct")
            self.assertIn("summary", report["graph_led"]["recall_reconstruction"])
            self.assertIn("summary", report["graph_led"]["reply_plan"]["debug"]["recall_reconstruction"])
            close_service_handles(service)

    def test_refresh_wechat_history_uses_windows_helper_and_caches_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "invoke_wechat_history.ps1").write_text("Write-Output '{}'\n", encoding="utf-8")
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "receipt_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/receipts",
                        "send_queue_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/send_queue",
                        "pyweixin_repo_path": "D:/Holo/holo/.vendor/pywechat-upstream",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            service = HoloReplyService(config, memory=FakeMemory())
            self.addCleanup(close_service_handles, service)

            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = json.dumps({"status": "ingested", "message_count": 18, "history_digest": "abc"}, ensure_ascii=False)
            completed.stderr = ""

            with mock.patch("holo_host.reply_api.subprocess.run", return_value=completed) as run_mock:
                first = service.refresh_wechat_history({"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "before"})
                second = service.refresh_wechat_history({"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "before"})

            self.assertEqual(first["status"], "ingested")
            self.assertEqual(second["status"], "skipped_cooldown")
            self.assertEqual(run_mock.call_count, 1)
            command = run_mock.call_args.args[0]
            self.assertIn("powershell.exe", command[0].lower())
            self.assertIn("-ChatName", command)
            self.assertIn("Nemoqi", command)
            self.assertIn("-NoCaptures", command)
            state_payload = json.loads((config.runtime.state_dir / "active_wechat_history_state.json").read_text(encoding="utf-8"))
            self.assertIn("Nemoqi", state_payload)
            self.assertEqual(service.memory.mind_graph_rebuild_calls, 1)
            close_service_handles(service)

    def test_stream_tick_records_influence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
api_port = 8010

[autonomy]
wechat_helper_config_path = ""
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory(), policy=AutonomyPolicy(config))
            try:
                payload = service.stream_tick(stream_name="association_stream", dry_run=False)
                self.assertEqual(payload["stream_name"], "association_stream")
                self.assertEqual(payload["record"]["influence"]["updated_threads"], 1)
                self.assertEqual(payload["record"]["influence"]["motifs"], ["continuity"])
            finally:
                close_service_handles(service)

    def test_brain_status_merges_stage3_loops_for_live_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            memory = FakeMemory()
            memory.brain_status = mock.Mock(  # type: ignore[method-assign]
                return_value={
                    "mode": "full_brain",
                    "loops": [
                        {"loop_name": "heartbeat", "status": "ok", "started_at": "2026-04-07T00:00:00Z", "finished_at": "2026-04-07T00:00:00Z"},
                        {"loop_name": "association_stream", "status": "ok", "started_at": "2026-04-07T00:01:00Z", "finished_at": "2026-04-07T00:01:00Z"},
                    ],
                    "cache": {"hit_ratio": 0.0, "hits": 0, "misses": 2},
                }
            )
            service = HoloReplyService(config, runner=FakeRunner(), memory=memory)
            try:
                payload = service.brain_status()
                loop_names = {str(item.get("loop_name", "")) for item in payload["loops"]}

                self.assertIn("self_model_refresh", loop_names)
                self.assertIn("homeostasis_tick", loop_names)
                self.assertIn("operator_planning", loop_names)
                self.assertIn("operator_shadow_cycle", loop_names)
                self.assertIn("visual_ingest_cycle", loop_names)

                pending = next(item for item in payload["loops"] if str(item.get("loop_name", "")) == "self_model_refresh")
                self.assertEqual(pending["status"], "never")
                self.assertIn("idle_seconds", payload)
            finally:
                close_service_handles(service)

    def test_refresh_wechat_history_origin_query_uses_deeper_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "invoke_wechat_history.ps1").write_text("Write-Output '{}'\n", encoding="utf-8")
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "receipt_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/receipts",
                        "send_queue_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/send_queue",
                        "pyweixin_repo_path": "D:/Holo/holo/.vendor/pywechat-upstream",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            service = HoloReplyService(config, memory=FakeMemory())

            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = json.dumps({"status": "ingested", "message_count": 64, "history_digest": "origin"}, ensure_ascii=False)
            completed.stderr = ""

            try:
                with mock.patch("holo_host.reply_api.subprocess.run", return_value=completed) as run_mock:
                    report = service.refresh_wechat_history(
                        {"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "at the beginning, what do you remember"}
                    )

                command = run_mock.call_args.args[0]
                self.assertEqual(command[command.index("-Limit") + 1], str(config.memory.active_wechat_history_deep_limit))
                self.assertEqual(command[command.index("-PageTurns") + 1], str(config.memory.active_wechat_history_deep_page_turns))
                self.assertTrue(report["command"]["origin_recall"])
                self.assertEqual(report["status"], "ingested")
            finally:
                close_service_handles(service)

    def test_reply_service_ignores_duplicate_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("I am here.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                payload = {
                    "chat_name": "TestContact",
                    "sender": "TestContact",
                    "text": "What should we eat tonight?",
                    "channel": "wechat",
                    "message_id": "fixed-1",
                }
                first = service.handle_reply(payload)
                second = service.handle_reply(payload)
                self.assertEqual(first["action"], "reply")
                self.assertEqual(second["action"], "ignore")
                self.assertEqual(second["reason"], "duplicate")
            finally:
                close_service_handles(service)
    def test_reply_service_retries_duplicate_inbound_when_no_outbound_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            runner = FakeRunner("Okay, let us keep it short.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                incoming = {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "Can it be shorter?",
                    "channel": "wechat",
                    "message_id": "retry-wechat-1",
                }
                store.record_inbound(
                    IncomingMessage(
                        message_id="retry-wechat-1",
                        thread_key="wechat:Nemoqi",
                        subject="Nemoqi",
                        sender_email="wechat:wechat:Nemoqi",
                        sender_name="Nemoqi",
                        body_text="Can it be shorter?",
                        channel="wechat",
                    )
                )

                result = service.handle_reply(incoming)
                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
            finally:
                close_service_handles(service)

    def test_reply_service_can_choose_silence_as_a_first_class_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("This should never be used.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "嗯",
                        "channel": "wechat",
                        "message_id": "stage5-silence-1",
                    }
                )
                self.assertEqual(result["action"], "silence")
                self.assertEqual(result["expression_budget"], 0)
                self.assertEqual(result["reason"], "low_signal_turn_with_low_expression_pressure")
                self.assertFalse(runner.calls)
                self.assertTrue(memory.action_selections)
                self.assertEqual(memory.action_selections[-1]["selected_action"]["action_type"], "silence")
            finally:
                close_service_handles(service)

    def test_reply_service_can_defer_reply_and_schedule_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("This should also never be used.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "这个不用现在回，晚点再说",
                        "channel": "wechat",
                        "message_id": "stage5-defer-1",
                    }
                )
                self.assertEqual(result["action"], "defer_reply")
                self.assertEqual(result["expression_budget"], 0)
                self.assertTrue(result["job_id"])
                jobs = store.list_jobs(limit=10)
                self.assertTrue(any(str(item.get("task_type", "")) == "deferred_reply" for item in jobs))
                self.assertFalse(runner.calls)
            finally:
                close_service_handles(service)

    def test_trace_action_selection_exposes_subject_led_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                trace = service.trace_action_selection(
                    query="在吗，顺着刚才那句往下接一点",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                )
                self.assertIn(trace["selected_action"]["action_type"], {"reply_once", "reply_multi"})
                self.assertTrue(trace["intent_state"])
                self.assertTrue(trace["action_market"])
                self.assertTrue(trace["action_rationale"])
            finally:
                close_service_handles(service)

    def test_accept_stage5_passes_with_fake_subject_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                report = service.accept_stage5(
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    iterations=1,
                    warmup=1,
                )
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["stage"], "intent-led-subject-runtime-stage5")
            finally:
                close_service_handles(service)

    def test_reply_service_can_choose_external_lookup_as_subject_action(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("grounded reply")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "search transcendence movie johnny depp",
                        "channel": "wechat",
                        "message_id": "stage6-lookup-1",
                    }
                )
                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
                self.assertTrue(memory.action_selections)
                self.assertTrue(any(item["selected_action"]["action_type"] == "external_lookup" for item in memory.action_selections))
                events = store.recent_events(channel="wechat", thread_key="wechat:Nemoqi", limit=5)
                self.assertTrue(events)
                self.assertEqual(str(events[0]["status"]), "completed")
                ledger = service.deliberation_ledger(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat", limit=10)
                entry_types = [str(item.get("entry_type", "")) for item in ledger.get("entries", [])]
                self.assertIn("ingest_event", entry_types)
                self.assertIn("subject_decide", entry_types)
                self.assertIn("execute_action", entry_types)
            finally:
                close_service_handles(service)

    def test_trace_deliberation_ledger_exposes_stage6_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=memory)
            try:
                service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "ok",
                        "channel": "wechat",
                        "message_id": "stage6-ledger-1",
                    }
                )
                payload = service.deliberation_ledger(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat", limit=10)
                self.assertTrue(payload["entries"])
                self.assertTrue(all(str(item.get("entry_type", "")).strip() for item in payload["entries"]))
            finally:
                close_service_handles(service)

    def test_accept_stage6_passes_with_fake_subject_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                report = service.accept_stage6(
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    iterations=1,
                    warmup=1,
                )
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["stage"], "deliberative-subject-core-stage6")
            finally:
                close_service_handles(service)

    def test_trace_counterfactual_exposes_stage7_world_and_prediction(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                payload = service.trace_counterfactual(
                    query="search transcendence movie johnny depp",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    limit=3,
                )
                self.assertEqual(payload["selected_action"]["action_type"], "external_lookup")
                self.assertTrue(payload["world_state"]["contact_models"])
                self.assertTrue(payload["counterfactual_set"])
                self.assertTrue(payload["predicted_best_outcome"])
            finally:
                close_service_handles(service)

    def test_accept_stage7_passes_with_fake_world_model_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                report = service.accept_stage7(
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    iterations=1,
                    warmup=1,
                )
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["stage"], "social-world-model-stage7")
            finally:
                close_service_handles(service)

    def test_trace_self_continuity_exposes_stage8_autobiographical_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                payload = service.trace_self_continuity()
                self.assertTrue(payload["autobiographical_state"]["identity_arc"])
                self.assertTrue(payload["goal_state"]["active_goals"])
                self.assertTrue(payload["current_chapter"])
            finally:
                close_service_handles(service)

    def test_accept_stage8_passes_with_fake_autobiographical_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory())
            try:
                report = service.accept_stage8(
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    iterations=1,
                    warmup=1,
                )
                self.assertEqual(report["status"], "pass")
                self.assertEqual(report["stage"], "autobiographical-self-stage8")
            finally:
                close_service_handles(service)

    def test_reply_service_ingests_artifact_through_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("???")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                report = service.ingest_artifact(
                    {
                        "path": str(root / "notes.txt"),
                        "note": "????????",
                        "tags": ["wechat", "artifact"],
                        "dry_run": True,
                    }
                )
                self.assertEqual(report["artifact_type"], "document")
                self.assertEqual(len(memory.ingested), 1)
                self.assertEqual(memory.ingested[0][1], "????????")
            finally:
                close_service_handles(service)

    def test_reply_service_normalizes_windows_artifact_path_for_wsl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            memory = FakeMemory()
            service = HoloReplyService(config, runner=FakeRunner("???"), memory=memory)
            try:
                service.ingest_artifact(
                    {
                        "path": r"D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\demo.md",
                        "note": "wechat export",
                        "tags": ["wechat", "artifact"],
                        "dry_run": True,
                    }
                )

                self.assertEqual(len(memory.ingested), 1)
                self.assertEqual(
                    memory.ingested[0][0],
                    "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history_exports/demo.md",
                )
            finally:
                close_service_handles(service)

    def test_reply_service_preserves_canonical_wechat_thread_key_and_outcome_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("短一点说，先接着往下。")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "thread_key": "Nemoqi",
                        "text": "接着刚才那条线往下说。",
                        "channel": "wechat",
                        "message_id": "stage12-reply-1",
                    }
                )
                thread_row = store.find_thread(channel="wechat", thread_key="wechat:Nemoqi")
                bare_thread = store.conn.execute(
                    "SELECT * FROM threads WHERE channel = 'wechat' AND thread_key = ?",
                    ("Nemoqi",),
                ).fetchone()

                self.assertEqual(result["thread_key"], "wechat:Nemoqi")
                self.assertIsNotNone(thread_row)
                self.assertIsNone(bare_thread)
                self.assertTrue(memory.outcome_appraisals)
                appraisal = memory.outcome_appraisals[-1]
                self.assertEqual(appraisal["thread_key"], "wechat:Nemoqi")
                self.assertEqual(appraisal["action_type"], str(result["selected_action"]["action_type"]))
                self.assertTrue(str(appraisal["action_ref"]))
                self.assertEqual(appraisal["metadata"]["thread_key"], "wechat:Nemoqi")
                self.assertEqual(appraisal["metadata"]["message_id"], "stage12-reply-1")
                self.assertTrue(appraisal["metadata"]["usage_evidence_refs"])
            finally:
                close_service_handles(service)

    def test_reply_service_appraises_defer_and_silence_with_distinct_action_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=FakeRunner("unused"), memory=memory)
            try:
                defer_result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "thread_key": "wechat:Nemoqi",
                        "text": "later after lunch",
                        "channel": "wechat",
                        "message_id": "stage12-defer-1",
                    }
                )
                silence_result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "thread_key": "wechat:Nemoqi",
                        "text": "ok",
                        "channel": "wechat",
                        "message_id": "stage12-silence-1",
                    }
                )

                self.assertEqual(defer_result["action"], "defer_reply")
                self.assertEqual(silence_result["action"], "silence")
                appraisals = [
                    record
                    for record in memory.outcome_appraisals
                    if str(record.get("metadata", {}).get("selected_action", "")).strip() in {"defer_reply", "silence"}
                ]
                self.assertGreaterEqual(len(appraisals), 2)
                defer_appraisal = next(item for item in appraisals if str(item.get("metadata", {}).get("selected_action", "")) == "defer_reply")
                silence_appraisal = next(item for item in appraisals if str(item.get("metadata", {}).get("selected_action", "")) == "silence")
                self.assertNotEqual(str(defer_appraisal["action_ref"]), str(silence_appraisal["action_ref"]))
                self.assertEqual(defer_appraisal["metadata"]["selected_action"], "defer_reply")
                self.assertEqual(silence_appraisal["metadata"]["selected_action"], "silence")
            finally:
                close_service_handles(service)


if __name__ == "__main__":
    unittest.main()
