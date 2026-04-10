from __future__ import annotations

import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import CodexResult
from holo_host.reply_api import ChatTurn, HoloReplyService
from holo_host.store import QueueStore
from tests.test_rag_memory import TempMemoryRepo


class _CountingRunner:
    def __init__(self) -> None:
        self.calls = 0

    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        self.calls += 1
        return CodexResult(reply_text="stage22 live reply", session_id=session_id or "stage22-session", returncode=0)


class Stage22OnlineCanaryTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _service(self, temp: TempMemoryRepo, bridge: MemoryBridge, runner: _CountingRunner | None = None) -> tuple[HoloReplyService, QueueStore]:
        config = load_config(repo_root=temp.repo_root)
        config.autonomy.stage22_canary_mode = "shadow"
        config.autonomy.stage22_canary_artifact_root = str(temp.runtime_dir / "canary")
        config.autonomy.stage22_canary_rollback_file = str(temp.runtime_dir / "CANARY_ROLLBACK")
        config.autonomy.stage22_canary_whitelist_threads = ("wechat:Nemoqi",)
        store = QueueStore(temp.runtime_dir / "queue.sqlite3")
        return HoloReplyService(config, store=store, runner=runner or _CountingRunner(), memory=bridge), store

    def _close(self, service: HoloReplyService, store: QueueStore, bridge: MemoryBridge) -> None:
        for handler in list(service.logger.handlers):
            handler.close()
            service.logger.removeHandler(handler)
        store.close()
        bridge.activation.close()
        bridge.graph.close()

    def test_shadow_mode_captures_artifacts_metrics_and_suppresses_live_reply(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            runner = _CountingRunner()
            service, store = self._service(temp, bridge, runner=runner)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "thread_key": "wechat:Nemoqi",
                        "channel": "wechat",
                        "sender": "Nemoqi",
                        "text": "still here?",
                        "message_id": "stage22-shadow-message",
                    }
                )
                metrics = service.show_blackbox_metrics(window_hours=24, thread_key="wechat:Nemoqi", channel="wechat")
                traces = store.list_canary_traces(channel="wechat", thread_key="wechat:Nemoqi", limit=4)
                artifact_exists = Path(result["stage22"]["artifact_path"]).exists()
            finally:
                self._close(service, store, bridge)

        self.assertEqual(result["action"], "silence")
        self.assertTrue(result["stage22_shadow"])
        self.assertEqual(result["stage22"]["mode"], "shadow")
        self.assertEqual(runner.calls, 0)
        self.assertTrue(artifact_exists)
        self.assertEqual(len(traces), 1)
        self.assertGreaterEqual(metrics["total_traces"], 1)
        self.assertIn("reflex_hit_rate", metrics)
        self.assertIn("latency_buckets_by_action_type", metrics)

    def test_canary_live_requires_whitelist_rate_limit_and_clear_rollback(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                service.config.autonomy.stage22_canary_mode = "canary_live"
                service.config.autonomy.stage22_canary_whitelist_threads = ("wechat:Nemoqi",)
                turn = ChatTurn(chat_name="Nemoqi", text="hi", sender="Nemoqi", channel="wechat", thread_key="wechat:Nemoqi")
                incoming = turn.to_incoming_message()
                sidecar = {"stage18": {}, "stage19": {}, "stage20": {}, "stage21": {}, "stage22": {}, "action_market": []}
                allowed = service._stage22_canary_gate(turn=turn, incoming=incoming, selected_action={"action_type": "reply_once"}, sidecar=sidecar)
                service.config.autonomy.stage22_canary_whitelist_threads = ("wechat:Other",)
                blocked_whitelist = service._stage22_canary_gate(turn=turn, incoming=incoming, selected_action={"action_type": "reply_once"}, sidecar=sidecar)
                service.config.autonomy.stage22_canary_whitelist_threads = ("wechat:Nemoqi",)
                rollback_on = service.set_canary_rollback(enabled=True, reason="unit")
                blocked_rollback = service._stage22_canary_gate(turn=turn, incoming=incoming, selected_action={"action_type": "reply_once"}, sidecar=sidecar)
                rollback_off = service.set_canary_rollback(enabled=False, reason="unit")
                service.config.autonomy.stage22_canary_max_replies_per_thread_per_hour = 0
                blocked_rate = service._stage22_canary_gate(turn=turn, incoming=incoming, selected_action={"action_type": "reply_once"}, sidecar=sidecar)
            finally:
                self._close(service, store, bridge)

        self.assertTrue(allowed["allowed"])
        self.assertEqual(blocked_whitelist["verdict"], "not_whitelisted")
        self.assertTrue(rollback_on["rollback_enabled"])
        self.assertEqual(blocked_rollback["verdict"], "rollback_enabled")
        self.assertFalse(rollback_off["rollback_enabled"])
        self.assertEqual(blocked_rate["verdict"], "thread_rate_limited")
        self.assertEqual(blocked_rate["selected_action"], "reply_once")

    def test_live_artifacts_feed_stage14_replay(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "thread_key": "wechat:Nemoqi",
                        "channel": "wechat",
                        "sender": "Nemoqi",
                        "text": "stage22 replay artifact",
                        "message_id": "stage22-replay-message",
                    }
                )
                replay = service.replay_live_artifacts(since_hours=24, limit=4, artifact_dir=str(temp.runtime_dir / "live-replay"))
                fixture_dir_exists = Path(replay["fixture_dir"]).exists()
            finally:
                self._close(service, store, bridge)

        self.assertGreaterEqual(int(replay["fixture_count"]), 1)
        self.assertTrue(fixture_dir_exists)
        self.assertIn(str(replay["status"]), {"pass", "warn"})

    def test_blackbox_metrics_compute_deterministically(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            service, store = self._service(temp, bridge)
            try:
                store.record_canary_trace(
                    event_row_id=1,
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    message_id="stage22-metric-a",
                    mode="canary_live",
                    verdict="allowed",
                    selected_action="history_refresh",
                    returned_action="reply",
                    latency_ms=80,
                    metadata={"trace": {"stage18": {"reply_lane": "micro_fast"}, "stage20": {"temporal_visible": True}}},
                )
                store.record_canary_trace(
                    event_row_id=2,
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    message_id="stage22-metric-b",
                    mode="shadow",
                    verdict="shadow_suppressed",
                    selected_action="counter_offer",
                    returned_action="silence",
                    latency_ms=2800,
                    metadata={"trace": {"stage20": {"duplicate_recovery_blocked": True}}},
                )
                metrics = service.show_blackbox_metrics(window_hours=24, thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
            finally:
                self._close(service, store, bridge)

        self.assertEqual(metrics["total_traces"], 2)
        self.assertEqual(metrics["reflex_hit_rate"], 0.5)
        self.assertEqual(metrics["reread_history_rate"], 0.5)
        self.assertEqual(metrics["clarification_thrash_rate"], 0.5)
        self.assertEqual(metrics["duplicate_followup_rate"], 0.5)
        self.assertEqual(metrics["resume_success_after_interruption"], 1.0)
        self.assertEqual(metrics["latency_buckets_by_action_type"]["history_refresh"]["<2s"], 1)

    def test_world_coupling_hydrates_without_heavy_recall_or_cross_thread_leakage(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                signal = bridge.record_world_coupling_signal(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    cue_type="task_cue",
                    summary="bounded task cue for the same live thread",
                    source_ref="unit:stage22:cue",
                    confidence=0.72,
                    evidence_refs=["unit:stage22:cue"],
                )
                packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "message_id": "stage22-cue-a"},
                )
                other_packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": "Other", "chat_name": "Other", "message_id": "stage22-cue-b"},
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

        self.assertTrue(signal["present"])
        self.assertTrue(packet["stage22"]["world_coupling_visible"])
        self.assertTrue(packet["stage22"]["world_coupling_used_for_thread"])
        self.assertNotEqual(packet["tier"], "deep_recall")
        self.assertFalse(other_packet["stage22"]["world_coupling_visible"])


if __name__ == "__main__":
    unittest.main()
