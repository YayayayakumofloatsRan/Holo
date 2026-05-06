from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state, build_turn_plan, render_chat_prompt
from tests.test_rag_memory import TempMemoryRepo


class _LaneRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        metadata = dict(kwargs.get("metadata", {}) if isinstance(kwargs.get("metadata", {}), dict) else {})
        lane = str(kwargs.get("lane", "") or "")
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="still here",
            session_id="stage18-session",
            returncode=0,
            stdout="",
            stderr="",
            metadata={
                "lane": lane,
                "provider": "fake",
                "model": "gpt-5.4-mini" if lane == "micro_fast" else "gpt-5.4",
                "reasoning_effort": "low" if lane == "micro_fast" else "medium",
                "reply_lane_reason": metadata.get("reply_lane_reason", ""),
                "reflex_micro_fast_candidate": metadata.get("reflex_micro_fast_candidate", False),
                "usage": {},
            },
        )


class Stage18DualSpeedReflexTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _config(self):
        return load_config(config_path=Path(__file__).resolve().parents[1] / ".holo_host.example.toml")

    def test_ordinary_short_turn_can_route_generation_to_micro_fast(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                active = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    direction="inbound",
                    text="ping",
                    message_id="stage18-fast-1",
                    event_row_id=1801,
                )
                packet = bridge.sidecar_packet(
                    "ping",
                    context={
                        "channel": "wechat",
                        "thread_key": "wechat:TestUser",
                        "chat_name": "TestUser",
                        "active_thread_state": active,
                        "attachments": [],
                    },
                )
                packet["selected_action"] = {"action_type": "reply_once", "score": 0.9}
                packet["action_market"] = [{"action_type": "reply_once", "score": 0.9}]
                packet["uncertainty_level"] = 0.12
                runner = _LaneRecordingRunner()
                processor = CodexCliProcessor(self._config(), runner)  # type: ignore[arg-type]
                context = TurnContext(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    sender="TestUser",
                    user_text="ping",
                    sidecar=packet,
                    mind_packet=packet,
                    attention_state=build_attention_state("ping", channel="wechat"),
                    emotion_state={},
                    history=[{"direction": "inbound", "body_text": "ping"}],
                    metadata={},
                    capability_context={},
                )
                reply = processor.generate(context)

                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertEqual(runner.calls[-1]["lane"], "micro_fast")
                self.assertEqual(reply.debug["lane"], "micro_fast")
                self.assertEqual(reply.debug["reply_lane_reason"], "stage18_reflex_micro_fast")
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_explicit_memory_query_still_escalates_and_avoids_micro_fast(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                active = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    direction="inbound",
                    text="ping",
                    message_id="stage18-recall-1",
                    event_row_id=1802,
                )
                packet = bridge.sidecar_packet(
                    "remember previous history",
                    context={
                        "channel": "wechat",
                        "thread_key": "wechat:TestUser",
                        "chat_name": "TestUser",
                        "active_thread_state": active,
                        "attachments": [],
                    },
                )
                packet["selected_action"] = {"action_type": "reply_once", "score": 0.9}
                packet["action_market"] = [{"action_type": "reply_once", "score": 0.9}]
                context = TurnContext(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    sender="TestUser",
                    user_text="remember previous history",
                    sidecar=packet,
                    mind_packet=packet,
                    attention_state=build_attention_state("remember previous history", channel="wechat"),
                    emotion_state={},
                    history=[],
                    metadata={},
                    capability_context={},
                )
                turn_plan = build_turn_plan(context, self._config())

                self.assertIn(packet["tier"], {"recall", "deep_recall"})
                self.assertNotEqual(packet["memory_route"], "active_thread")
                self.assertEqual(turn_plan.route, "deep_recall")
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_low_confidence_alone_does_not_trigger_deep_recall(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                active = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    direction="inbound",
                    text="ping",
                    message_id="stage18-low-confidence-1",
                    event_row_id=1803,
                )
                predictive = dict(active.get("predictive_continuity", {}))
                predictive["active_prediction_confidence"] = 0.1
                predictive["reflex_eligibility"] = False
                active["predictive_continuity"] = predictive
                packet = bridge.sidecar_packet(
                    "ping",
                    context={
                        "channel": "wechat",
                        "thread_key": "wechat:TestUser",
                        "chat_name": "TestUser",
                        "active_thread_state": active,
                        "attachments": [],
                    },
                )

                self.assertNotEqual(packet["tier"], "deep_recall")
                self.assertNotEqual(packet["recall_reason"], "stage17:explicit_memory_query")
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_predictive_continuity_fields_persist_across_reload(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            state = bridge.update_active_thread_state(
                channel="wechat",
                thread_key="wechat:TestUser",
                chat_name="TestUser",
                direction="inbound",
                text="ping",
                message_id="stage18-persist-1",
                event_row_id=1804,
            )
            self.assertEqual(state["status"], "ok")
            bridge.activation.close()
            bridge.graph.close()

            reloaded = self._bridge(temp)
            try:
                state = reloaded.active_thread_state(channel="wechat", thread_key="wechat:TestUser", chat_name="TestUser")
                predictive = dict(state.get("predictive_continuity", {}))
                for key in (
                    "predicted_next_user_act",
                    "predicted_reply_pressure",
                    "likely_reference_targets",
                    "expected_social_valence",
                    "reflex_eligibility",
                    "turn_rhythm",
                    "freshness_at",
                    "active_prediction_confidence",
                ):
                    self.assertIn(key, predictive)
                    self.assertIn(key, state)
                self.assertTrue(predictive["freshness_at"])
            finally:
                reloaded.activation.close()
                reloaded.graph.close()

    def test_fast_prompt_uses_predictive_continuity_before_optional_history(self) -> None:
        config = self._config()
        packet = {
            "tier": "fast",
            "memory_route": "active_thread",
            "active_thread_state": {
                "continuity_summary": "user: ping",
                "last_outbound_action": {"action_type": "reply_once"},
                "unresolved_references": ["that thread"],
                "predictive_continuity": {
                    "predicted_next_user_act": "reference_followup",
                    "predicted_reply_pressure": 0.2,
                    "likely_reference_targets": ["last_outbound_action:reply_once"],
                    "expected_social_valence": "neutral",
                    "reflex_eligibility": True,
                    "turn_rhythm": {"short_turn": True},
                    "freshness_at": "2026-04-10T00:00:00Z",
                    "active_prediction_confidence": 0.72,
                },
            },
            "recent_dialogue_window": {"lines": ["old line one", "old line two"]},
            "selected_action": {"action_type": "reply_once"},
            "action_market": [{"action_type": "reply_once", "score": 0.9}],
            "state": {"emotion_state": {}},
        }
        context = TurnContext(
            channel="wechat",
            thread_key="wechat:TestUser",
            chat_name="TestUser",
            sender="TestUser",
            user_text="ping",
            sidecar=packet,
            mind_packet=packet,
            attention_state=build_attention_state("ping", channel="wechat"),
            emotion_state={},
            history=[],
            metadata={},
            capability_context={},
        )
        turn_plan = build_turn_plan(context, config)
        prompt = render_chat_prompt(context, turn_plan=turn_plan)

        self.assertIn("predictive_continuity", prompt)
        self.assertIn("last_exchange", prompt)
        self.assertLess(prompt.index("predictive_continuity"), prompt.index("last_exchange"))
        self.assertLessEqual(int(context.metadata.get("history_lines_in_prompt", 0)), 1)
        self.assertEqual(int(context.metadata.get("predictive_lines_in_prompt", 0)), 1)


if __name__ == "__main__":
    unittest.main()
