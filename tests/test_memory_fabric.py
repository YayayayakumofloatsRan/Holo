from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage1_acceptance
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


class _FakeVectorMemory:
    def __init__(self, hits: list[dict]):
        self._hits = hits
        self.upserts: list[list[dict]] = []

    def search(self, query: str, *, channel: str, thread_key: str, chat_name: str, limit: int = 6) -> dict:
        return {
            "status": "ok",
            "backend": "milvus",
            "available": True,
            "ready": True,
            "collection_name": "test",
            "uri": "memory://test",
            "dimension": 192,
            "last_error": "",
            "hits": list(self._hits)[:limit],
        }

    def upsert_documents(self, documents):
        docs = list(documents)
        self.upserts.append(docs)
        return {"status": "ok", "document_count": len(docs)}

    def health(self) -> dict:
        return {
            "backend": "milvus",
            "available": True,
            "ready": True,
            "collection_name": "test",
            "uri": "memory://test",
            "dimension": 192,
            "last_error": "",
        }


class MemoryFabricTests(unittest.TestCase):
    def test_goal_state_merge_dedupes_by_goal_id(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector_backend="milvus",
                rag=rm,
            )
            initial = {
                "goal_id": "goal-identity-maintenance",
                "goal_type": "identity_maintenance",
                "summary": "stay lively without losing coherence",
                "priority": 0.71,
                "progress": 0.34,
                "target_thread": "Nemoqi",
                "evidence": ["stiffness_drift"],
                "last_moved_at": "2026-04-08T00:00:00Z",
                "stalled_reason": "",
            }
            updated = {
                **initial,
                "priority": 0.89,
                "progress": 0.58,
                "last_moved_at": "2026-04-08T01:00:00Z",
            }

            bridge.graph.update_goal_state({"active_goals": [initial]}, reason="unit:first", source="unit")
            state = bridge.graph.update_goal_state({"active_goals": [updated]}, reason="unit:second", source="unit")

            matching = [goal for goal in state["active_goals"] if dict(goal).get("goal_id") == initial["goal_id"]]
            self.assertEqual(len(matching), 1)
            self.assertEqual(matching[0]["priority"], updated["priority"])
            self.assertEqual(matching[0]["progress"], updated["progress"])
            bridge.activation.close()
            bridge.graph.close()

    def test_sidecar_packet_v11_exposes_autobiography_and_goal_layers(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we were still trying to pull the speed back up",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-1",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector_backend="milvus",
                rag=rm,
            )
            bridge.backfill_mind_graph()
            docs = bridge.graph.export_vector_documents(channel="wechat", thread_key="Nemoqi", chat_name="Nemoqi")
            self.assertTrue(docs)
            first = docs[0]
            bridge.vector = _FakeVectorMemory(
                [
                    {
                        "node_id": first["id"],
                        "score": 0.83,
                        "channel": first["channel"],
                        "thread_key": first["thread_key"],
                        "chat_name": first["chat_name"],
                        "memory_class": first["memory_class"],
                        "source_store": first["source_store"],
                        "source_id": first["source_id"],
                        "text": first["text"],
                        "importance": first["importance"],
                        "confidence": first["confidence"],
                    }
                ]
            )
            bridge.activation.record(
                channel="wechat",
                thread_key="Nemoqi",
                chat_name="Nemoqi",
                contributor="unit_test",
                note="activation",
                node_ids=[first["id"]],
                motifs=["speed"],
                recall_priors={first["id"]: 0.4},
                heat_delta=0.2,
            )

            packet = bridge.sidecar_packet(
                "remember before",
                context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )

            self.assertEqual(packet["mind_packet_version"], "v11")
            self.assertIn(packet["retrieval_mode"], {"hybrid-led", "hybrid-led+fallback", "graph-led"})
            self.assertIn("graph_hits", packet)
            self.assertIn("vector_hits", packet)
            self.assertIn("activation_state", packet)
            self.assertIn("retrieval_trace", packet)
            self.assertIn("memory_route", packet)
            self.assertIn("recall_confidence", packet)
            self.assertIn("persona_blend", packet)
            self.assertIn("brain_state", packet)
            self.assertIn("game_state", packet)
            self.assertIn("stream_influence", packet)
            self.assertIn("self_revision_state", packet)
            self.assertIn("self_model", packet)
            self.assertIn("homeostasis_state", packet)
            self.assertIn("operator_state", packet)
            self.assertIn("visual_memory", packet)
            self.assertIn("affect_state", packet)
            self.assertIn("drive_state", packet)
            self.assertIn("value_state", packet)
            self.assertIn("conflict_state", packet)
            self.assertIn("initiative_candidates", packet)
            self.assertIn("resistance_posture", packet)
            self.assertIn("outcome_memory", packet)
            self.assertIn("world_state", packet)
            self.assertIn("counterfactual_summary", packet)
            self.assertIn("predicted_best_outcome", packet)
            self.assertIn("predicted_worst_outcome", packet)
            self.assertIn("selected_prediction", packet)
            self.assertIn("uncertainty_level", packet)
            self.assertIn("autobiographical_state", packet)
            self.assertIn("goal_state", packet)
            self.assertIn("goal_alignment", packet)
            self.assertIn("identity_consistency", packet)
            self.assertIn("chapter_relevance", packet)
            self.assertIn("self_narrative_hint", packet)
            self.assertIn("intent_state_v4", packet)
            self.assertIn("action_market_v4", packet)
            self.assertIn("expression_budget_v4", packet)
            self.assertIn("intent_state_v3", packet)
            self.assertIn("action_market_v3", packet)
            self.assertIn("expression_budget_v3", packet)
            self.assertTrue(packet["activation_trace_ids"])
            self.assertEqual(packet["memory_route"], "hybrid")
            bridge.activation.close()
            bridge.graph.close()

    def test_backfill_vector_memory_uses_exported_graph_docs(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "you still remember before",
                "we kept pulling the old thread back together",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-2",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector_backend="milvus",
                rag=rm,
            )
            bridge.backfill_mind_graph()
            fake_vector = _FakeVectorMemory([])
            bridge.vector = fake_vector

            report = bridge.backfill_vector_memory(channel="wechat", thread_key="Nemoqi", chat_name="Nemoqi")

            self.assertEqual(report["status"], "ok")
            self.assertTrue(fake_vector.upserts)
            self.assertTrue(fake_vector.upserts[0])
            bridge.activation.close()
            bridge.graph.close()

    def test_fast_ping_sidecar_skips_hybrid_vector_expansion(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "hello",
                "still here",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-fast-path",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector_backend="milvus",
                rag=rm,
            )
            bridge.backfill_mind_graph()
            packet = bridge.sidecar_packet("在吗", context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"})

            self.assertEqual(packet["tier"], "fast")
            self.assertEqual(packet["retrieval_mode"], "graph-led")
            self.assertEqual(packet["memory_route"], "graph")
            self.assertEqual(packet["vector_hits"], [])
            bridge.activation.close()
            bridge.graph.close()

    def test_hybrid_recall_prefers_semantic_topic_hits_over_generic_continuity(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "我们之前一直在修主脑",
                "先把连续性和速度拉回来",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-generic",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.archive_turn(
                "transcendence 超验骇客 电影 德普",
                "那部片子的中文翻译我一直觉得不太对",
                source="unit.archive",
                tags=["wechat", "chat_reply", "movie"],
                turn_id="turn-movie",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector_backend="milvus",
                rag=rm,
            )
            bridge.backfill_mind_graph()
            docs = bridge.graph.export_vector_documents(channel="wechat", thread_key="Nemoqi", chat_name="Nemoqi")
            movie_doc = next(doc for doc in docs if "transcendence" in doc["text"].lower() or "超验骇客" in doc["text"])
            generic_doc = next(doc for doc in docs if "连续性" in doc["text"] or "速度" in doc["text"])
            bridge.vector = _FakeVectorMemory(
                [
                    {
                        "node_id": generic_doc["id"],
                        "score": 0.84,
                        "channel": generic_doc["channel"],
                        "thread_key": generic_doc["thread_key"],
                        "chat_name": generic_doc["chat_name"],
                        "memory_class": generic_doc["memory_class"],
                        "source_store": generic_doc["source_store"],
                        "source_id": generic_doc["source_id"],
                        "text": generic_doc["text"],
                        "importance": generic_doc["importance"],
                        "confidence": generic_doc["confidence"],
                    },
                    {
                        "node_id": movie_doc["id"],
                        "score": 0.79,
                        "channel": movie_doc["channel"],
                        "thread_key": movie_doc["thread_key"],
                        "chat_name": movie_doc["chat_name"],
                        "memory_class": movie_doc["memory_class"],
                        "source_store": movie_doc["source_store"],
                        "source_id": movie_doc["source_id"],
                        "text": movie_doc["text"],
                        "importance": movie_doc["importance"],
                        "confidence": movie_doc["confidence"],
                    },
                ]
            )

            trace = bridge.trace_hybrid_recall(
                "transcendence 超验骇客 电影 德普",
                thread_key="Nemoqi",
                chat_name="Nemoqi",
                channel="wechat",
                limit=4,
                record=False,
            )

            top_text = str(trace["trace"][0]["text"])
            self.assertTrue("transcendence" in top_text.lower() or "超验骇客" in top_text)
            bridge.activation.close()
            bridge.graph.close()

    def test_sync_private_memory_copies_working_store(self) -> None:
        with TempMemoryRepo() as temp, tempfile.TemporaryDirectory() as private_dir:
            rm.write_rows(
                "working",
                [
                    rm.make_row(
                    status="working",
                    rows=[],
                    kind="episodic",
                    text="working memory should be mirrored privately",
                    source="unit",
                    tags=["unit"],
                    importance=0.7,
                    confidence=0.8,
                )
            ],
        )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                private_memory_sync_enabled=True,
                private_memory_repo_path=private_dir,
                rag=rm,
            )
            report = bridge.sync_private_memory(label="stage1")

            self.assertEqual(report["status"], "ok")
            snapshot_dir = Path(report["snapshot_dir"])
            self.assertTrue((snapshot_dir / "working_store.jsonl").exists())
            self.assertTrue((snapshot_dir / "mind_graph_export.json").exists())
            bridge.activation.close()
            bridge.graph.close()

    def test_evaluate_stage1_acceptance_passes_core_checks(self) -> None:
        report = _evaluate_stage1_acceptance(
            transport="live_http",
            health={
                "status": "ok",
                "repo_root": "/home/holo/holo",
                "graph_led_reply_enabled": True,
                "fallback_enabled": True,
                "activation_cache_enabled": True,
            },
            vector_health={"backend": "milvus", "available": True, "ready": True},
            explicit_trace={
                "retrieval_mode": "hybrid-led",
                "memory_route": "hybrid",
                "vector_hits": [{"text": "old anchor"}],
                "activation_trace_ids": ["node-1"],
            },
            origin_trace={
                "query_focus": "origin",
                "graph_hits": [{"text": "最开始你要我先分清是谁在说话"}],
                "vector_hits": [],
            },
            reply_probe={
                "hybrid": {
                    "recall_reconstruction": {
                        "summary": "咱还记得那会儿先在把微信语气和身份线理顺。",
                        "anchors": ["先分清是谁在说话", "微信里简短一点"],
                    }
                }
            },
            activation_state={"active_node_ids": ["node-1"]},
            stream_ticks=[
                {
                    "record": {
                        "influence": {
                            "updated_nodes": 1,
                            "updated_threads": 1,
                            "motifs": ["continuity"],
                            "unfinished_threads": ["keep going"],
                        }
                    }
                }
            ],
            stream_status={"recent_runs": [{"run_type": "stream:association_stream"}]},
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 120.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 420.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1600.0}},
            private_sync=None,
            require_private_sync=False,
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["failures"])
        self.assertFalse(report["blockers"])

    def test_evaluate_stage1_acceptance_reports_private_sync_blocker(self) -> None:
        report = _evaluate_stage1_acceptance(
            transport="live_http",
            health={
                "status": "ok",
                "repo_root": "/home/holo/holo",
                "graph_led_reply_enabled": True,
                "fallback_enabled": True,
                "activation_cache_enabled": True,
            },
            vector_health={"backend": "milvus", "available": True, "ready": True},
            explicit_trace={
                "retrieval_mode": "hybrid-led",
                "memory_route": "hybrid",
                "vector_hits": [{"text": "old anchor"}],
                "activation_trace_ids": ["node-1"],
            },
            origin_trace={
                "query_focus": "origin",
                "graph_hits": [{"text": "最开始你要我先分清是谁在说话"}],
                "vector_hits": [],
            },
            reply_probe={"hybrid": {"recall_reconstruction": {"summary": "记得", "anchors": ["线头"]}}},
            activation_state={"active_node_ids": ["node-1"]},
            stream_ticks=[
                {"record": {"influence": {"updated_nodes": 1, "updated_threads": 1, "motifs": ["continuity"], "unfinished_threads": []}}}
            ],
            stream_status={"recent_runs": [{"run_type": "stream:association_stream"}]},
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 120.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 420.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1600.0}},
            private_sync={"status": "skipped", "reason": "private_memory_sync_disabled"},
            require_private_sync=True,
        )
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(report["blockers"])


if __name__ == "__main__":
    unittest.main()
