from __future__ import annotations

import json
import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.mind_graph import MindGraph
from tests.test_rag_memory import TempMemoryRepo


class MindGraphTests(unittest.TestCase):
    def test_rebuild_materializes_nodes_threads_and_sources(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we were still trying to pull the reply speed back up",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-1",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.write_rows(
                "durable",
                [
                    rm.make_row(
                        status="durable",
                        rows=[],
                        kind="social_model",
                        text="When talking to TestUser, reconnect the old thread before expanding.",
                        tags=["relationship", "wechat"],
                        source="unit",
                        importance=0.95,
                        confidence=0.92,
                    )
                ],
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            report = graph.rebuild()
            inspect = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")

            self.assertEqual(report["status"], "ok")
            self.assertGreater(report["node_count"], 0)
            self.assertIn("relationship_memory", report["memory_class_counts"])
            self.assertEqual(inspect["filters"]["thread_key"], "wechat:TestUser")
            self.assertGreaterEqual(inspect["thread_state"].get("relationship_score", 0.0), 1.0)
            self.assertTrue(any(node["thread_key"] == "wechat:TestUser" for node in inspect["nodes"]))
            graph.close()

    def test_trace_recall_prefers_current_thread(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "that thread was still about restoring speed",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-nemoqi",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "remember before",
                "this belongs to another contact",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-other",
                metadata={"channel": "wechat", "thread_key": "Other", "chat_name": "Other"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall("remember before", thread_key="TestUser", chat_name="TestUser", channel="wechat", record=False)

            self.assertEqual(trace["thread_key"], "wechat:TestUser")
            self.assertGreater(len(trace["trace"]), 0)
            self.assertEqual(trace["trace"][0]["thread_key"], "wechat:TestUser")
            self.assertIn(trace["tier"], {"recall", "deep_recall"})
            graph.close()

    def test_trace_recall_marks_fast_ping_as_fast_tier(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "hello",
                "we are still here",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-fast",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall("在吗", thread_key="TestUser", chat_name="TestUser", channel="wechat", record=False)

            self.assertEqual(trace["tier"], "fast")
            self.assertEqual(trace["query_focus"], "recent")
            graph.close()

    def test_trace_recall_origin_query_surfaces_earliest_thread_events(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "???",
                "I am here, throw me whatever you want to test first.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-1",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "can you keep replies shorter",
                "Yes, we can keep WeChat replies shorter and less formal.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-2",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "what was at the beginning",
                "At the beginning you were already asking whether I still remembered the road.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-late-recall",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            archive_path = Path(rm.ARCHIVE_STORE_PATH)
            rows = [
                json.loads(line)
                for line in archive_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for row in rows:
                if row.get("turn_id") == "turn-early-1":
                    row["created_at"] = "2026-04-03T11:20:55Z"
                elif row.get("turn_id") == "turn-early-2":
                    row["created_at"] = "2026-04-03T11:35:37Z"
                elif row.get("turn_id") == "turn-late-recall":
                    row["created_at"] = "2026-04-06T15:22:22Z"
            archive_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall(
                "at the beginning, what do you remember",
                thread_key="TestUser",
                chat_name="TestUser",
                channel="wechat",
                record=False,
            )

            self.assertEqual(trace["query_focus"], "origin")
            earliest_lines = trace["memory_lines"][:2]
            self.assertTrue(any("user: ???" in line for line in earliest_lines))
            self.assertTrue(any("can you keep replies shorter" in line for line in trace["memory_lines"][:3]))
            graph.close()

    def test_origin_query_prefers_earliest_substantive_turns_over_low_signal_rows(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "你在吗",
                "I am here.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-knock",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "[ThumbsUp][ThumbsUp][ThumbsUp]",
                "I got the three thumbs up.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-thumb",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "可以简短一点，毕竟wechat上长篇大论会很严肃",
                "Yes, I will keep WeChat replies shorter.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-shorter",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "开头过于公式化了，可以省掉",
                "Then I will drop the formal opening.",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-early-formal",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            archive_path = Path(rm.ARCHIVE_STORE_PATH)
            rows = [
                json.loads(line)
                for line in archive_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for row in rows:
                if row.get("turn_id") == "turn-early-knock":
                    row["created_at"] = "2026-04-03T10:00:02Z"
                elif row.get("turn_id") == "turn-early-thumb":
                    row["created_at"] = "2026-04-03T10:38:00Z"
                elif row.get("turn_id") == "turn-early-shorter":
                    row["created_at"] = "2026-04-03T11:35:37Z"
                elif row.get("turn_id") == "turn-early-formal":
                    row["created_at"] = "2026-04-03T11:39:42Z"
            archive_path.write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
                encoding="utf-8",
            )

            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall(
                "最开始的时候，你还记得什么",
                thread_key="TestUser",
                chat_name="TestUser",
                channel="wechat",
                record=False,
            )
            window = graph.origin_dialogue_window(thread_key="TestUser", chat_name="TestUser", channel="wechat", limit=4)

            self.assertEqual(trace["query_focus"], "origin")
            self.assertTrue(any("你在吗" in line for line in trace["memory_lines"][:3]))
            self.assertTrue(any("可以简短一点" in line for line in trace["memory_lines"][:3]))
            self.assertTrue(any("开头过于公式化了" in line for line in trace["memory_lines"][:4]))
            self.assertFalse(any("[ThumbsUp]" in line for line in trace["memory_lines"][:3]))
            self.assertTrue(any("可以简短一点" in line for line in window["lines"]))
            self.assertTrue(any("开头过于公式化了" in line for line in window["lines"]))
            graph.close()

    def test_stream_status_seeds_expected_streams(self) -> None:
        with TempMemoryRepo() as temp:
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            payload = graph.stream_status()

            stream_names = {row["stream_name"] for row in payload["streams"]}
            self.assertIn("maintenance_stream", stream_names)
            self.assertIn("association_stream", stream_names)
            self.assertIn("social_stream", stream_names)
            self.assertIn("deep_dream_cycle", stream_names)
            graph.close()

    def test_record_recall_updates_thread_state(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we kept trying to stitch the thread back together",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-nemoqi",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall("remember before", thread_key="TestUser", chat_name="TestUser", channel="wechat", record=False)
            report = graph.record_recall(trace["activated_node_ids"], success=True)
            inspect = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")

            self.assertGreater(report["updated"], 0)
            self.assertGreaterEqual(report["thread_updates"], 1)
            self.assertTrue(inspect["thread_state"].get("last_recalled_at"))
            graph.close()

    def test_record_stream_run_applies_thread_influence(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we were still trying to pull the old line back together",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-stream",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            try:
                graph.rebuild()
                inspect_before = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")
                archive_node = next(node for node in inspect_before["nodes"] if node["source_store"] == "archive")

                report = graph.record_stream_run(
                    "social_stream",
                    status="ok",
                    note="initiative_cycle",
                    payload={
                        "initiatives": [
                            {
                                "channel": "wechat",
                                "thread_key": "TestUser",
                                "chat_name": "TestUser",
                                "motif": "continuity",
                                "reason": "follow the old line before it cools",
                                "source_archive_id": archive_node.get("source_id", archive_node["id"]),
                            }
                        ]
                    },
                )
                inspect_after = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")
                metadata = json.loads(inspect_after["thread_state"].get("metadata_json", "{}") or "{}")
                self.assertEqual(report["status"], "ok")
                self.assertGreaterEqual(report["influence"]["updated_nodes"], 1)
                self.assertGreaterEqual(report["influence"]["updated_threads"], 1)
                self.assertIn("continuity", metadata.get("recurring_motifs", []))
                self.assertTrue(any("follow the old line" in item for item in metadata.get("unfinished_threads", [])))
            finally:
                graph.close()

    def test_relationship_summary_keeps_secondary_color_when_continuity_is_strong(self) -> None:
        with TempMemoryRepo() as temp:
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            try:
                summary = graph._relationship_summary_from_state(
                    {
                        "recurring_motifs": ["continuity", "journey", "treat"],
                        "unfinished_threads": [],
                        "tone_tendency": "continuity_guard",
                    }
                )
                self.assertIn("轻巧", summary)
                self.assertIn("同行", summary)
            finally:
                graph.close()

    def test_sync_archive_entry_incrementally_materializes_observed_turn(self) -> None:
        with TempMemoryRepo() as temp:
            result = rm.auto_observe_turn(
                "do you still remember before",
                reply="I still remember that we were pulling the line back together",
                source="unit.observe",
                tags=["wechat", "chat_reply"],
                turn_id="turn-1",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            sync_report = graph.sync_archive_entry(result.get("archive_entry"))
            inspect = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")

            self.assertEqual(sync_report["status"], "ok")
            self.assertGreater(sync_report["node_count"], 0)
            self.assertTrue(any(node["source_store"] == "archive" for node in inspect["nodes"]))
            graph.close()

    def test_incremental_thread_sync_preserves_recall_state(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we were still trying to recover the old speed",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-1",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            trace = graph.trace_recall("remember before", thread_key="TestUser", chat_name="TestUser", channel="wechat", record=False)
            graph.record_recall(trace["activated_node_ids"], success=True)

            rm.archive_turn(
                "and then what happened",
                "we kept stitching the route back into place",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-2",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            report = graph.sync_thread(channel="wechat", thread_key="TestUser", chat_name="TestUser")
            inspect = graph.inspect_graph(thread_key="TestUser", chat_name="TestUser", channel="wechat")

            self.assertEqual(report["status"], "ok")
            self.assertGreaterEqual(report["deleted_nodes"], 1)
            self.assertGreaterEqual(int(inspect["thread_state"].get("recall_count", 0) or 0), 1)
            self.assertTrue(inspect["thread_state"].get("last_recalled_at"))
            graph.close()

    def test_relationship_snapshot_surfaces_motifs_and_unfinished_threads(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "重新上线前你还记得吗，下一步我们怎么升级你",
                "记得一些，你一直在把断掉的线接回来，也在催我别把升级路线忘了",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-1",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            rm.archive_turn(
                "那就继续把这套系统往前推吧",
                "行，I陪你把这条路继续修下去",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-2",
                metadata={"channel": "wechat", "thread_key": "TestUser", "chat_name": "TestUser"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            graph.rebuild()
            snapshot = graph.relationship_snapshot(thread_key="TestUser", chat_name="TestUser", channel="wechat", limit=4)

            self.assertTrue(snapshot["summary"])
            self.assertIn("continuity", snapshot["recurring_motifs"])
            self.assertTrue(snapshot["unfinished_threads"])
            self.assertTrue(snapshot["tone_tendency"])
            self.assertGreaterEqual(snapshot["continuity_score"], 0.1)
            graph.close()


if __name__ == "__main__":
    unittest.main()
