from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

import holo_memory_library.rag_memory as rm
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


class Stage26TaskWorldStateTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _close_bridge(self, bridge: MemoryBridge) -> None:
        bridge.activation.close()
        bridge.graph.close()

    def test_task_world_persists_across_restart_and_normalizes_families(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                artifact_path = Path(temp.runtime_dir / "stage26-file.txt")
                artifact_path.write_text("stage26 file object\n", encoding="utf-8")
                bridge.ingest_artifact(
                    str(artifact_path),
                    note="stage26 file object",
                    source="unit.stage26.file",
                    tags=["stage26", "file"],
                    dry_run=False,
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    world_cue_type="file_artifact",
                )
                bridge.ingest_artifact(
                    str(artifact_path),
                    note="stage26 schedule object",
                    source="unit.stage26.schedule",
                    tags=["stage26", "schedule"],
                    dry_run=False,
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    world_cue_type="schedule_cue",
                    due_at="2099-01-01T00:00:00Z",
                )
                bridge.upsert_task_world_object(
                    object_type="task",
                    summary="send the bounded task-world update",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="unit.stage26.task",
                )
                bridge.upsert_task_world_object(
                    object_type="image_summary",
                    summary="screenshot summary shows the draft title",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="unit.stage26.image",
                )
                bridge.upsert_task_world_object(
                    object_type="person",
                    summary="Mika is the external reviewer",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="unit.stage26.person",
                )
                task_world = bridge.show_task_world(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", include_inactive=True)
            finally:
                self._close_bridge(bridge)

            reopened = self._bridge(temp)
            try:
                reloaded = reopened.show_task_world(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", include_inactive=True)
                object_types = {str(item.get("object_type", "") or "") for item in reloaded["objects"]}
                self.assertTrue(reloaded["present"])
                self.assertTrue(task_world["present"])
                self.assertTrue({"file", "task", "schedule", "image_summary", "person"}.issubset(object_types))
            finally:
                self._close_bridge(reopened)

    def test_task_world_rehydrates_same_thread_before_hybrid_recall(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                bridge.upsert_task_world_object(
                    object_type="task",
                    summary="finish the same-thread handoff note",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="unit.stage26.rehydrate",
                )
                with bridge.graph._lock:
                    bridge.graph.conn.execute(
                        "DELETE FROM active_thread_state WHERE channel = ? AND thread_key = ?",
                        ("wechat", "wechat:Nemoqi"),
                    )
                    bridge.graph.conn.execute(
                        "UPDATE attention_frontier SET stale_after = ? WHERE channel = ? AND canonical_thread_key = ?",
                        ("2000-01-01T00:00:00Z", "wechat", "wechat:Nemoqi"),
                    )
                    bridge.graph.conn.commit()
                context = {
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                    "chat_name": "Nemoqi",
                    "attachments": [],
                    "recent_history": [
                        {"direction": "inbound", "body_text": "old line one"},
                        {"direction": "outbound", "body_text": "old line two"},
                    ],
                }
                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("hybrid recall should not run")):
                    packet = bridge.sidecar_packet("still here?", context=context)
            finally:
                self._close_bridge(bridge)

        self.assertEqual(packet["memory_route"], "active_thread")
        self.assertEqual(packet["retrieval_mode"], "active-thread-fast")
        self.assertTrue(packet["stage26"]["task_world_used_for_thread"])
        self.assertTrue(packet["stage26"]["summary"])
        self.assertNotEqual(packet["tier"], "deep_recall")

    def test_cross_thread_links_are_explicit_but_not_implicitly_prompt_visible(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                shared_a = bridge.upsert_task_world_object(
                    object_type="task",
                    summary="shared deliverable across two explicit threads",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="unit.stage26.shared",
                )
                shared_b = bridge.upsert_task_world_object(
                    object_type="task",
                    summary="shared deliverable across two explicit threads",
                    thread_key="Mika",
                    chat_name="Mika",
                    channel="wechat",
                    source_ref="unit.stage26.shared",
                )
                link_trace = bridge.trace_thread_object_links(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", limit=8)
                packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "attachments": []},
                )
                other_packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": "Other", "chat_name": "Other", "attachments": []},
                )
            finally:
                self._close_bridge(bridge)

        self.assertTrue(shared_a["present"])
        self.assertEqual(shared_a["object_id"], shared_b["object_id"])
        self.assertGreaterEqual(int(link_trace["cross_thread_object_count"]), 1)
        self.assertTrue(packet["stage26"]["cross_thread_links_visible"])
        self.assertTrue(packet["stage26"]["task_world_visible"])
        self.assertFalse(other_packet["stage26"]["task_world_visible"])


if __name__ == "__main__":
    unittest.main()
