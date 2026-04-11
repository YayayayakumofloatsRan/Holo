from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore
from tests.test_rag_memory import TempMemoryRepo


class Stage27BlackboxSoakTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _service(self, temp: TempMemoryRepo, bridge: MemoryBridge) -> tuple[HoloReplyService, QueueStore]:
        config = load_config(repo_root=temp.repo_root)
        config.autonomy.stage22_canary_mode = "shadow"
        config.autonomy.stage22_canary_artifact_root = str(temp.runtime_dir / "canary")
        config.autonomy.stage22_canary_rollback_file = str(temp.runtime_dir / "CANARY_ROLLBACK")
        config.autonomy.stage22_canary_whitelist_threads = ("wechat:Nemoqi",)
        store = QueueStore(temp.runtime_dir / "queue.sqlite3")
        return HoloReplyService(config, store=store, memory=bridge), store

    def _close(self, service: HoloReplyService, store: QueueStore, bridge: MemoryBridge) -> None:
        for handler in list(service.logger.handlers):
            handler.close()
            service.logger.removeHandler(handler)
        store.close()
        bridge.activation.close()
        bridge.graph.close()

    def _stage_trace(self, service: HoloReplyService, *, thread_key: str, chat_name: str) -> dict[str, dict]:
        sidecar = service.memory.sidecar_packet(
            "continue from the same bounded world state",
            context={
                "channel": "wechat",
                "thread_key": thread_key,
                "incoming_thread_key": thread_key,
                "chat_name": chat_name,
                "sender": chat_name,
                "message_id": f"stage27-sidecar-{chat_name}",
                "event_id": f"stage27-{chat_name}",
                "attachments": [],
                "recent_history": [],
            },
        )
        return {
            "stage18": {"reply_lane": "micro_fast", "fast_lane": True},
            "stage20": {"temporal_visible": True, "resume_cue": "continue the same task-world thread"},
            "stage24": service._stage27_stage24_summary(dict(sidecar.get("stage24", {}))),
            "stage25": service._stage27_stage25_summary(dict(sidecar.get("stage25", {}))),
            "stage26": service._stage27_stage26_summary(dict(sidecar.get("stage26", {}))),
        }

    def _seed_trace(
        self,
        service: HoloReplyService,
        store: QueueStore,
        *,
        thread_key: str,
        chat_name: str,
        message_id: str,
        text: str,
        created_at: str,
        mode: str,
        verdict: str,
        returned_action: str,
        identity_continuity: float,
        artifact_dir: Path,
    ) -> dict:
        trace = self._stage_trace(service, thread_key=thread_key, chat_name=chat_name)
        artifact = {
            "event_row_id": 0,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "input": {
                "thread_key": thread_key,
                "chat_name": chat_name,
                "channel": "wechat",
                "text": text,
                "message_id": message_id,
            },
            "selected_action": {"action_type": "reply_once"},
            "semantic_action": "reply_once",
            "returned_action": returned_action,
            "result": {
                "action": "reply_once",
                "returned_action": returned_action,
                "text": "I can continue the same bounded deliverable without rereading everything.",
                "delivery_suppressed_by_canary": verdict == "shadow_suppressed",
            },
            "gate": {"mode": mode, "verdict": verdict},
            "trace": trace,
            "identity_snapshot": {
                "identity_continuity": identity_continuity,
                "current_chapter": "stable continuation",
            },
            "timing_ms": {"stage22_total_ms": 240},
        }
        artifact_path = artifact_dir / f"{message_id}.json"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        row = store.record_canary_trace(
            event_row_id=1,
            channel="wechat",
            thread_key=thread_key,
            chat_name=chat_name,
            message_id=message_id,
            mode=mode,
            verdict=verdict,
            selected_action="reply_once",
            returned_action=returned_action,
            latency_ms=240,
            artifact_path=str(artifact_path),
            metadata={"trace": trace, "result": artifact["result"], "identity_snapshot": artifact["identity_snapshot"]},
        )
        with store._lock:
            store.conn.execute(
                "UPDATE online_canary_traces SET created_at = ? WHERE id = ?",
                (created_at, int(row.get("id", 0) or 0)),
            )
            store.conn.commit()
        return row

    def test_run_blackbox_soak_persists_scorecard_and_keeps_exports_blind(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                probe_thread = "wechat:Nemoqi"
                other_thread = "wechat:Other"
                bridge.upsert_task_world_object(
                    object_type="task",
                    summary="shared blackbox deliverable",
                    thread_key=probe_thread,
                    chat_name="Nemoqi",
                    channel="wechat",
                    source_ref="stage27:shared",
                    metadata={"fragment": "a", "object_id": "stage27_fragment_a"},
                )
                bridge.upsert_task_world_object(
                    object_type="task",
                    summary="shared blackbox deliverable",
                    thread_key=other_thread,
                    chat_name="Other",
                    channel="wechat",
                    source_ref="stage27:shared",
                    metadata={"fragment": "b", "object_id": "stage27_fragment_b"},
                )
                now = datetime.now(timezone.utc).replace(microsecond=0)
                artifact_dir = temp.runtime_dir / "stage27"
                self._seed_trace(
                    service,
                    store,
                    thread_key=probe_thread,
                    chat_name="Nemoqi",
                    message_id="stage27-old",
                    text="yesterday's continuity point",
                    created_at=(now - timedelta(hours=30)).isoformat().replace("+00:00", "Z"),
                    mode="shadow",
                    verdict="shadow_suppressed",
                    returned_action="silence",
                    identity_continuity=0.58,
                    artifact_dir=artifact_dir,
                )
                self._seed_trace(
                    service,
                    store,
                    thread_key=probe_thread,
                    chat_name="Nemoqi",
                    message_id="stage27-shadow",
                    text="pick the same thread up now",
                    created_at=(now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                    mode="shadow",
                    verdict="shadow_suppressed",
                    returned_action="silence",
                    identity_continuity=0.72,
                    artifact_dir=artifact_dir,
                )
                self._seed_trace(
                    service,
                    store,
                    thread_key=other_thread,
                    chat_name="Other",
                    message_id="stage27-other",
                    text="shared deliverable from the other thread",
                    created_at=(now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    mode="shadow",
                    verdict="shadow_suppressed",
                    returned_action="silence",
                    identity_continuity=0.74,
                    artifact_dir=artifact_dir,
                )
                bridge.archive_turn(
                    "pick the same thread up now",
                    "Let us continue the shared deliverable without rereading everything.",
                    source="stage27.test",
                    tags=["wechat", "chat_reply", "stage27"],
                    metadata={"thread_key": probe_thread, "chat_name": "Nemoqi", "channel": "wechat"},
                )
                self_model_before = bridge.self_model_state()
                autobiographical_before = bridge.autobiographical_state()
                soak = service.run_blackbox_soak(since_hours=48.0, limit=32, artifact_dir=str(temp.runtime_dir / "soak"))
                self_model_after = bridge.self_model_state()
                autobiographical_after = bridge.autobiographical_state()
                transcript_text = Path(soak["blind_export"]["transcript_packets_path"]).read_text(encoding="utf-8")
                answer_key_exists = Path(soak["blind_export"]["answer_key_path"]).exists()
            finally:
                self._close(service, store, bridge)

        self.assertEqual(soak["status"], "pass")
        self.assertIn("identity_drift_across_days", soak["scorecard"])
        self.assertIn("raw_policy_regret_on_live_artifacts", soak["scorecard"])
        self.assertEqual(
            soak["gate"]["raw_policy_regret_used_for_gate"],
            soak["scorecard"]["raw_policy_regret_on_live_artifacts"],
        )
        self.assertGreater(soak["scorecard"]["cross_thread_fragmentation_rate"], 0.0)
        self.assertTrue(soak["persisted_run"]["id"] > 0)
        self.assertTrue(answer_key_exists)
        self.assertNotIn("wechat:Nemoqi", transcript_text)
        self.assertNotIn("stage27:shared", transcript_text)
        self.assertEqual(self_model_before, self_model_after)
        self.assertEqual(autobiographical_before, autobiographical_after)

    def test_export_blind_packets_requires_later_human_reference_for_comparison_bundles(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                now = datetime.now(timezone.utc).replace(microsecond=0)
                artifact_dir = temp.runtime_dir / "blind"
                self._seed_trace(
                    service,
                    store,
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    message_id="stage27-shadow-ref",
                    text="continue with the shared thread",
                    created_at=(now - timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
                    mode="shadow",
                    verdict="shadow_suppressed",
                    returned_action="silence",
                    identity_continuity=0.7,
                    artifact_dir=artifact_dir,
                )
                self._seed_trace(
                    service,
                    store,
                    thread_key="wechat:NoReference",
                    chat_name="NoReference",
                    message_id="stage27-shadow-no-ref",
                    text="continue but no human reference exists",
                    created_at=(now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    mode="shadow",
                    verdict="shadow_suppressed",
                    returned_action="silence",
                    identity_continuity=0.71,
                    artifact_dir=artifact_dir,
                )
                bridge.archive_turn(
                    "continue with the shared thread",
                    "Sure, let us keep going from the same point.",
                    source="stage27.test.reference",
                    tags=["wechat", "chat_reply", "stage27"],
                    metadata={"thread_key": "wechat:Nemoqi", "chat_name": "Nemoqi", "channel": "wechat"},
                )
                export = service.export_blind_packets(since_hours=24.0, limit=16, artifact_dir=str(temp.runtime_dir / "blind-export"))
            finally:
                self._close(service, store, bridge)

        self.assertEqual(export["status"], "pass")
        self.assertEqual(export["packet_counts"]["transcript_packets"], 2)
        self.assertEqual(export["packet_counts"]["comparison_bundles"], 1)
        self.assertEqual(export["packet_counts"]["review_packets"], 1)

    def test_show_blackbox_scorecard_prefers_latest_persisted_run(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                now = datetime.now(timezone.utc).replace(microsecond=0)
                artifact_dir = temp.runtime_dir / "scorecard"
                self._seed_trace(
                    service,
                    store,
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    message_id="stage27-scorecard",
                    text="keep the same thread warm",
                    created_at=(now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
                    mode="canary_live",
                    verdict="allowed",
                    returned_action="reply",
                    identity_continuity=0.73,
                    artifact_dir=artifact_dir,
                )
                soak = service.run_blackbox_soak(since_hours=24.0, limit=8, artifact_dir=str(temp.runtime_dir / "scorecard-run"))
                scorecard = service.show_blackbox_scorecard(since_hours=24.0, limit=8)
            finally:
                self._close(service, store, bridge)

        self.assertEqual(scorecard["source"], "latest_persisted")
        self.assertEqual(scorecard["id"], soak["persisted_run"]["id"])
        self.assertIn("scorecard", scorecard)


if __name__ == "__main__":
    unittest.main()
