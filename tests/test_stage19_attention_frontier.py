from __future__ import annotations

import unittest
from unittest import mock

import holo_memory_library.rag_memory as rm
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


class Stage19AttentionFrontierTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _seed_frontier(self, bridge: MemoryBridge, *, suffix: str = "nemoqi") -> dict:
        thread_key = f"wechat:Nemoqi-{suffix}"
        chat_name = f"Nemoqi-{suffix}"
        rm.archive_turn(
            f"stage19 seed {suffix}",
            "keep the bounded continuity frontier warm",
            source="unit.stage19",
            tags=["wechat", "stage19"],
            turn_id=f"stage19-seed-{suffix}",
            metadata={"channel": "wechat", "thread_key": thread_key, "chat_name": chat_name},
        )
        bridge.graph.sync_thread(channel="wechat", thread_key=thread_key, chat_name=chat_name)
        inspect = bridge.graph.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel="wechat")
        archive_node = next(node for node in inspect["nodes"] if node["source_store"] == "archive")
        report = bridge.record_stream_run(
            "association_stream",
            status="ok",
            note="stage19_unit",
            payload={
                "thoughts": [
                    {
                        "channel": "wechat",
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "motif": "continuity",
                        "source_archive_id": archive_node.get("source_id", archive_node["id"]),
                    }
                ],
                "selected_memory_ids": [archive_node.get("source_id", archive_node["id"])],
            },
        )
        return {"thread_key": thread_key, "chat_name": chat_name, "report": report}

    def test_stream_influence_creates_frontier_and_activation_warmth(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge)
                frontier = bridge.attention_frontier(channel="wechat")
                entry = next(item for item in frontier["entries"] if item["canonical_thread_key"] == seeded["thread_key"])
                activation = bridge.activation_state(thread_key=seeded["thread_key"], chat_name=seeded["chat_name"], channel="wechat")

                self.assertEqual(seeded["report"]["status"], "ok")
                self.assertTrue(seeded["report"]["influence"]["frontier_updates"])
                self.assertEqual(entry["channel"], "wechat")
                self.assertGreater(entry["thread_heat"], 0.0)
                self.assertEqual(entry["wake_reason"], "continuity")
                self.assertIn("stream:association_stream", entry["evidence_refs"])
                self.assertGreater(float(activation["heat"]), 0.0)
                self.assertIn("association_stream", activation["contributor_counts"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_warm_reentry_after_idle_can_use_active_reflex_path_without_hybrid_recall(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge, suffix="warm")
                context = {
                    "channel": "wechat",
                    "thread_key": seeded["thread_key"],
                    "chat_name": seeded["chat_name"],
                    "attachments": [],
                }
                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("hybrid recall should not run")):
                    packet = bridge.sidecar_packet("still here?", context=context)

                self.assertEqual(packet["tier"], "fast")
                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertEqual(packet["retrieval_mode"], "active-thread-fast")
                self.assertTrue(packet["stage19"]["frontier_used_for_thread"])
                self.assertTrue(packet["active_thread_state"]["predictive_continuity"]["reflex_eligibility"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_ordinary_short_turn_does_not_run_stream_work_on_hot_path(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge, suffix="hotpath")
                context = {
                    "channel": "wechat",
                    "thread_key": seeded["thread_key"],
                    "chat_name": seeded["chat_name"],
                    "attachments": [],
                }
                with mock.patch.object(bridge.graph, "record_stream_run", side_effect=AssertionError("stream work should not run")):
                    packet = bridge.sidecar_packet("still here?", context=context)

                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertTrue(packet["stage19"]["frontier_used_for_thread"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_expired_frontier_decays_to_cold_and_is_ignored(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge, suffix="stale")
                with bridge.graph._lock:
                    bridge.graph.conn.execute(
                        "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                        ("2000-01-01T00:00:00Z", "wechat", seeded["thread_key"]),
                    )
                    bridge.graph.conn.commit()

                warmth = bridge.thread_warmth(thread_key=seeded["thread_key"], chat_name=seeded["chat_name"], channel="wechat")
                packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": seeded["thread_key"], "chat_name": seeded["chat_name"], "attachments": []},
                )

                self.assertEqual(warmth["thread_warmth"], "cold")
                self.assertTrue(warmth["stale"])
                self.assertFalse(packet["stage19"]["frontier_used_for_thread"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_explicit_memory_query_still_escalates_with_warm_frontier(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge, suffix="recall")
                packet = bridge.sidecar_packet(
                    "remember previous history",
                    context={"channel": "wechat", "thread_key": seeded["thread_key"], "chat_name": seeded["chat_name"], "attachments": []},
                )

                self.assertIn(packet["tier"], {"recall", "deep_recall"})
                self.assertEqual(packet["recall_reason"], "stage17:explicit_memory_query")
                self.assertNotEqual(packet["memory_route"], "active_thread")
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_dense_continuity_keeps_hot_thread_available_after_frontier_decay(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_frontier(bridge, suffix="dense")
                bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key=seeded["thread_key"],
                    chat_name=seeded["chat_name"],
                    direction="inbound",
                    text="keep the thread warm after the pause",
                    message_id="stage19-dense-message",
                    event_row_id=1902,
                )
                with bridge.graph._lock:
                    bridge.graph.conn.execute(
                        "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                        ("2000-01-01T00:00:00Z", "wechat", seeded["thread_key"]),
                    )
                    bridge.graph.conn.execute(
                        "DELETE FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                        ("wechat", seeded["thread_key"]),
                    )
                    bridge.graph.conn.commit()

                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("hybrid recall should not run")):
                    packet = bridge.sidecar_packet(
                        "still here?",
                        context={"channel": "wechat", "thread_key": seeded["thread_key"], "chat_name": seeded["chat_name"], "attachments": []},
                    )

                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertTrue(packet["stage25"]["working_set_used_for_thread"])
                self.assertFalse(packet["stage19"]["frontier_used_for_thread"])
            finally:
                bridge.activation.close()
                bridge.graph.close()


if __name__ == "__main__":
    unittest.main()
