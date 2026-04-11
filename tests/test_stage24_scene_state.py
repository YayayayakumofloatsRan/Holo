from __future__ import annotations

import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.reply_api import ChatTurn, HoloReplyService
from holo_host.store import QueueStore
from tests.test_rag_memory import TempMemoryRepo


class _NoTaskRunner:
    def run(self, prompt: str, **kwargs: object):  # pragma: no cover - Stage24 only calls run_task here
        raise AssertionError("run() should not be used in the Stage24 scene compression fallback test")


class Stage24SceneStateTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def test_scene_state_persists_across_reload_and_exposes_diagnostics(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                state = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    direction="inbound",
                    text="Can we keep lunch simple tomorrow and maybe continue after that?",
                    message_id="msg-stage24-1",
                    event_row_id=2401,
                )
                self.assertEqual(state["status"], "ok")
                scene = bridge.scene_state(channel="wechat", thread_key="wechat:Nemoqi", chat_name="Nemoqi")
                branches = bridge.trace_predicted_branches(channel="wechat", thread_key="wechat:Nemoqi", chat_name="Nemoqi")
                compression = bridge.trace_scene_compression(channel="wechat", thread_key="wechat:Nemoqi", chat_name="Nemoqi")
                scene_state = dict(scene["scene_state"])
                for key in (
                    "shared_frame",
                    "topic_stack",
                    "salient_objects",
                    "latent_questions",
                    "predicted_branches",
                    "relationship_trajectory",
                    "response_sketch",
                    "scene_confidence",
                    "freshness_at",
                ):
                    self.assertIn(key, scene_state)
                self.assertTrue(scene["stage24"]["scene_visible"])
                self.assertEqual(branches["predicted_branches"], scene_state["predicted_branches"][:3])
                self.assertEqual(compression["compression_mode"], "heuristic")
                self.assertTrue(compression["last_reducer_at"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

            reloaded = self._bridge(temp)
            try:
                persisted = reloaded.active_thread_state(channel="wechat", thread_key="wechat:Nemoqi", chat_name="Nemoqi")
                persisted_scene = dict(persisted.get("scene_state", {}))
                self.assertTrue(persisted["present"])
                self.assertEqual(persisted_scene["shared_frame"], scene_state["shared_frame"])
                self.assertEqual(persisted_scene["topic_stack"], scene_state["topic_stack"])
                self.assertEqual(persisted_scene["predicted_branches"], scene_state["predicted_branches"])
            finally:
                reloaded.activation.close()
                reloaded.graph.close()

    def test_scene_state_stays_bounded_and_action_market_overlay_is_inspectable(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                state = bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    direction="inbound",
                    text=(
                        "Can we keep lunch simple tomorrow, maybe talk after the movie, "
                        "and maybe also sort the gift, the ride, and the timing after that?"
                    ),
                    message_id="msg-stage24-2",
                    event_row_id=2402,
                )
                scene = dict(state.get("scene_state", {}))
                self.assertLessEqual(len(scene.get("topic_stack", [])), 4)
                self.assertLessEqual(len(scene.get("salient_objects", [])), 4)
                self.assertLessEqual(len(scene.get("latent_questions", [])), 3)
                self.assertLessEqual(len(scene.get("predicted_branches", [])), 3)

                market = bridge.action_market(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    query="still here about lunch tomorrow?",
                    limit=8,
                )
                candidates = list(market["action_market"])
                self.assertTrue(candidates)
                self.assertTrue(all("scene_delta" in item and "scene_rationale" in item for item in candidates))
                self.assertTrue(any(float(item.get("scene_delta", 0.0) or 0.0) != 0.0 for item in candidates))

                recall_packet = bridge.sidecar_packet(
                    "remember previous history",
                    context={
                        "channel": "wechat",
                        "thread_key": "wechat:Nemoqi",
                        "chat_name": "Nemoqi",
                        "active_thread_state": state,
                        "attachments": [],
                    },
                )
                self.assertIn(recall_packet["tier"], {"recall", "deep_recall"})
                self.assertEqual(recall_packet["recall_reason"], "stage17:explicit_memory_query")
                self.assertNotEqual(recall_packet["memory_route"], "active_thread")
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_scene_compression_falls_back_deterministically_when_processor_path_is_unavailable(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            config = load_config(repo_root=temp.repo_root)
            store = QueueStore(temp.runtime_dir / "queue.sqlite3")
            service = HoloReplyService(config, store=store, runner=_NoTaskRunner(), memory=bridge)
            long_text = (
                "Can we keep lunch simple tomorrow while also thinking about the movie, the gift, the ride home, "
                "and the timing after that? I want to stay in the same thread without losing the plan, and I also "
                "want to know whether we should reply now or later if the thread keeps unfolding with more details?"
            )
            try:
                turn = ChatTurn(
                    chat_name="Nemoqi",
                    text=long_text,
                    sender="Nemoqi",
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    message_id="msg-stage24-3",
                )
                incoming = turn.to_incoming_message()
                first = service._update_active_thread_state(
                    turn=turn,
                    incoming=incoming,
                    direction="inbound",
                    event_row_id=2403,
                    text=long_text,
                    metadata={},
                )
                second = service._update_active_thread_state(
                    turn=turn,
                    incoming=incoming,
                    direction="inbound",
                    event_row_id=2404,
                    text=long_text,
                    metadata={},
                )
                compression = service.trace_scene_compression(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat")
            finally:
                for handler in list(service.logger.handlers):
                    handler.close()
                    service.logger.removeHandler(handler)
                store.close()
                bridge.activation.close()
                bridge.graph.close()

            self.assertEqual(compression["compression_mode"], "heuristic_fallback")
            self.assertEqual(compression["compression_reason"], "processor_unavailable")
            self.assertEqual(first["scene_state"]["shared_frame"], second["scene_state"]["shared_frame"])
            self.assertEqual(first["scene_state"]["topic_stack"], second["scene_state"]["topic_stack"])
            self.assertEqual(first["scene_state"]["predicted_branches"], second["scene_state"]["predicted_branches"])


if __name__ == "__main__":
    unittest.main()
