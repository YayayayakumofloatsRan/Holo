from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import TurnContext
from holo_host.processors import build_attention_state, build_turn_plan, render_chat_prompt
from tests.test_rag_memory import TempMemoryRepo


class Stage17RealtimeRuntimeTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def test_active_thread_state_persists_across_bridge_reload(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            state = bridge.update_active_thread_state(
                channel="wechat",
                thread_key="wechat:Nemoqi",
                chat_name="Nemoqi",
                direction="inbound",
                text="在吗",
                message_id="msg-stage17-1",
                event_row_id=1701,
            )
            self.assertEqual(state["status"], "ok")
            bridge.activation.close()
            bridge.graph.close()

            reloaded = self._bridge(temp)
            try:
                state = reloaded.active_thread_state(channel="wechat", thread_key="wechat:Nemoqi", chat_name="Nemoqi")
                self.assertTrue(state["present"])
                self.assertEqual(state["thread_key"], "wechat:Nemoqi")
                self.assertIn("msg-stage17-1", state["recent_turn_ids"])
            finally:
                reloaded.activation.close()
                reloaded.graph.close()

    def test_ordinary_short_wechat_turn_uses_active_fast_lane_without_hybrid_recall(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                active = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    direction="inbound",
                    text="在吗",
                    message_id="msg-stage17-2",
                    event_row_id=1702,
                )
                context = {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "active_thread_state": active,
                    "attachments": [],
                }
                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("hybrid recall should not run")):
                    packet = bridge.sidecar_packet("在吗", context=context)

                self.assertEqual(packet["tier"], "fast")
                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertEqual(packet["retrieval_mode"], "active-thread-fast")
                self.assertTrue(packet["stage17"]["fast_lane"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_fast_lane_prompt_prefers_active_summary_over_recent_history_window(self) -> None:
        config = load_config(config_path=Path(__file__).resolve().parents[1] / ".holo_host.example.toml")
        packet = {
            "tier": "fast",
            "memory_route": "active_thread",
            "active_thread_state": {
                "continuity_summary": "user: 在吗",
                "last_outbound_action": {"action_type": "reply_once"},
                "unresolved_references": [],
            },
            "recent_dialogue_window": {
                "lines": ["old line one", "old line two", "old line three", "old line four"],
            },
            "selected_action": {"action_type": "reply_once"},
            "action_market": [{"action_type": "reply_once", "score": 0.4}],
            "state": {"emotion_state": {}},
        }
        context = TurnContext(
            channel="wechat",
            thread_key="wechat:Nemoqi",
            chat_name="Nemoqi",
            sender="Nemoqi",
            user_text="在吗",
            sidecar=packet,
            mind_packet=packet,
            attention_state=build_attention_state("在吗", channel="wechat"),
            emotion_state={},
            history=[
                {"direction": "inbound", "body_text": "old line one"},
                {"direction": "outbound", "body_text": "old line two"},
                {"direction": "inbound", "body_text": "old line three"},
                {"direction": "outbound", "body_text": "old line four"},
            ],
            metadata={},
            capability_context={},
        )
        turn_plan = build_turn_plan(context, config)
        prompt = render_chat_prompt(context, turn_plan=turn_plan)

        self.assertTrue(turn_plan.fast_path)
        self.assertEqual(turn_plan.history_window, 1)
        self.assertLessEqual(int(context.metadata.get("history_lines_in_prompt", 0)), 1)
        self.assertIn("continuity_summary", prompt)
        self.assertNotIn("old line two", prompt)
        self.assertNotIn("old line three", prompt)

    def test_explicit_memory_query_escalates_instead_of_active_fast_lane(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                active = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    direction="inbound",
                    text="在吗",
                    message_id="msg-stage17-3",
                    event_row_id=1703,
                )
                packet = bridge.sidecar_packet(
                    "remember before our launch thread",
                    context={
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                        "active_thread_state": active,
                        "attachments": [],
                    },
                )

                self.assertIn(packet["tier"], {"recall", "deep_recall"})
                self.assertEqual(packet["recall_reason"], "stage17:explicit_memory_query")
                self.assertNotEqual(packet["memory_route"], "active_thread")
            finally:
                bridge.activation.close()
                bridge.graph.close()


if __name__ == "__main__":
    unittest.main()
