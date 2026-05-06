from __future__ import annotations

import unittest
from unittest import mock

import holo_memory_library.rag_memory as rm
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


class Stage25DenseContinuityTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _seed_dense_thread(self, bridge: MemoryBridge, *, suffix: str = "dense") -> dict[str, str]:
        thread_key = f"wechat:TestUser-{suffix}"
        chat_name = f"TestUser-{suffix}"
        rm.archive_turn(
            f"stage25 seed {suffix}",
            "keep this thread warm through bounded dense continuity",
            source="unit.stage25",
            tags=["wechat", "stage25"],
            turn_id=f"stage25-seed-{suffix}",
            metadata={"channel": "wechat", "thread_key": thread_key, "chat_name": chat_name},
        )
        bridge.graph.sync_thread(channel="wechat", thread_key=thread_key, chat_name=chat_name)
        bridge.update_active_thread_state(
            channel="wechat",
            thread_key=thread_key,
            chat_name=chat_name,
            direction="inbound",
            text="we can keep this thread warm after a short pause",
            message_id=f"stage25-message-{suffix}",
            event_row_id=2501,
        )
        inspect = bridge.graph.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel="wechat", limit=6)
        archive_node = next(node for node in inspect["nodes"] if node["source_store"] == "archive")
        bridge.record_stream_run(
            "association_stream",
            status="ok",
            note="stage25_unit",
            payload={
                "thoughts": [
                    {
                        "channel": "wechat",
                        "thread_key": thread_key,
                        "chat_name": chat_name,
                        "motif": "stage25_dense",
                        "source_archive_id": archive_node.get("source_id", archive_node["id"]),
                    }
                ],
                "selected_memory_ids": [archive_node.get("source_id", archive_node["id"])],
            },
        )
        return {"thread_key": thread_key, "chat_name": chat_name}

    def test_dense_working_set_persists_across_restart(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_dense_thread(bridge, suffix="persist")
                dense = bridge.show_dense_working_set(channel="wechat")
                self.assertTrue(dense["present"])
                self.assertLessEqual(dense["entry_count"], 8)
                self.assertIn("budget", dense["dense_working_set"])
                self.assertTrue(any(item["thread_key"] == seeded["thread_key"] for item in dense["dense_working_set"]["top_hot_threads"]))
            finally:
                bridge.activation.close()
                bridge.graph.close()

            reopened = self._bridge(temp)
            try:
                dense = reopened.show_dense_working_set(channel="wechat")
                self.assertTrue(dense["present"])
                self.assertTrue(any(item["thread_key"] == seeded["thread_key"] for item in dense["dense_working_set"]["top_hot_threads"]))
            finally:
                reopened.activation.close()
                reopened.graph.close()

    def test_dense_continuity_rehydrates_hot_thread_before_hybrid_recall(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_dense_thread(bridge, suffix="rehydrate")
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

                context = {
                    "channel": "wechat",
                    "thread_key": seeded["thread_key"],
                    "chat_name": seeded["chat_name"],
                    "attachments": [],
                }
                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("hybrid recall should not run")):
                    packet = bridge.sidecar_packet("still here?", context=context)

                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertEqual(packet["retrieval_mode"], "active-thread-fast")
                self.assertTrue(packet["stage25"]["working_set_used_for_thread"])
                self.assertFalse(packet["stage19"]["frontier_used_for_thread"])
                self.assertTrue(packet["active_thread_state"]["scene_state"]["shared_frame"])
            finally:
                bridge.activation.close()
                bridge.graph.close()

    def test_background_pulses_do_not_trigger_heavy_recall_and_trace_is_bounded(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                seeded = self._seed_dense_thread(bridge, suffix="pulse")
                inspect = bridge.graph.inspect_graph(thread_key=seeded["thread_key"], chat_name=seeded["chat_name"], channel="wechat", limit=6)
                archive_node = next(node for node in inspect["nodes"] if node["source_store"] == "archive")
                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("background pulses should not trigger recall")):
                    bridge.record_stream_run(
                        "association_stream",
                        status="ok",
                        note="stage25_pulse_a",
                        payload={
                            "thoughts": [
                                {
                                    "channel": "wechat",
                                    "thread_key": seeded["thread_key"],
                                    "chat_name": seeded["chat_name"],
                                    "motif": "pulse-a",
                                    "source_archive_id": archive_node.get("source_id", archive_node["id"]),
                                }
                            ],
                            "selected_memory_ids": [archive_node.get("source_id", archive_node["id"])],
                        },
                    )
                trace = bridge.trace_thread_pulse(thread_key=seeded["thread_key"], chat_name=seeded["chat_name"], channel="wechat", limit=12)
                dense = bridge.show_dense_working_set(channel="wechat")

                self.assertTrue(trace["thread_pulse_trace"])
                self.assertLessEqual(trace["trace_count"], 12)
                self.assertTrue(any(item["pulse_verdict"] in {"pulsed", "skipped_cooldown", "carryover_budget_full"} for item in trace["thread_pulse_trace"]))
                self.assertTrue(any(item["thread_key"] == seeded["thread_key"] for item in dense["dense_working_set"]["top_hot_threads"]))
            finally:
                bridge.activation.close()
                bridge.graph.close()


if __name__ == "__main__":
    unittest.main()
