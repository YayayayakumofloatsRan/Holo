from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

import holo_memory_library.rag_memory as rm
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import CodexResult, IncomingMessage
from holo_host.reply_api import ChatTurn, HoloReplyService
from holo_host.store import QueueStore
from tests.test_rag_memory import TempMemoryRepo


class _FakeRunner:
    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        return CodexResult(reply_text="noted", session_id=session_id or "stage20-session", returncode=0)


class Stage20TemporalCommitmentsTests(unittest.TestCase):
    def _bridge(self, temp: TempMemoryRepo) -> MemoryBridge:
        return MemoryBridge(
            temp.repo_root,
            graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
            vector_backend="milvus",
            rag=rm,
        )

    def _config(self, temp: TempMemoryRepo):
        return load_config(repo_root=temp.repo_root)

    def _close_bridge(self, bridge: MemoryBridge) -> None:
        bridge.activation.close()
        bridge.graph.close()

    def _close_service(self, service: HoloReplyService) -> None:
        for handler in list(service.logger.handlers):
            handler.close()
            service.logger.removeHandler(handler)

    def _seed_resume(
        self,
        bridge: MemoryBridge,
        *,
        thread_key: str = "Nemoqi",
        chat_name: str = "Nemoqi",
        dedupe_key: str = "stage20-resume",
        status: str = "scheduled",
        revisit_before: str = "",
        source_action_type: str = "history_refresh",
    ) -> dict:
        return bridge.graph.upsert_temporal_item(
            item_type="resume_candidate",
            channel="wechat",
            thread_key=thread_key,
            chat_name=chat_name,
            confidence=0.74,
            source_event_id=f"event:{dedupe_key}",
            source_action_ref=f"action:{dedupe_key}",
            source_action_type=source_action_type,
            due_at="2000-01-01T00:00:00Z",
            revisit_after="2000-01-01T00:00:00Z",
            revisit_before=revisit_before,
            resume_cue="we were talking about the postponed line",
            dedupe_key=dedupe_key,
            status=status,
            metadata={"source": "unit.stage20", "evidence_refs": [f"unit:{dedupe_key}"]},
        )

    def test_interleaved_multi_thread_interruptions_are_isolated_by_canonical_key(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                first = bridge.graph.upsert_temporal_item(
                    item_type="interruption_marker",
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    confidence=0.7,
                    source_event_id="stage20-interrupt-a",
                    source_action_ref="lookup-a",
                    source_action_type="external_lookup",
                    due_at="2000-01-01T00:00:00Z",
                    revisit_after="2000-01-01T00:00:00Z",
                    resume_cue="resume Nemoqi lookup",
                    dedupe_key="stage20-interrupt-a",
                    status="scheduled",
                    metadata={"evidence_refs": ["unit:a"]},
                )
                second = bridge.graph.upsert_temporal_item(
                    item_type="interruption_marker",
                    channel="wechat",
                    thread_key="Mika",
                    chat_name="Mika",
                    confidence=0.7,
                    source_event_id="stage20-interrupt-b",
                    source_action_ref="lookup-b",
                    source_action_type="external_lookup",
                    due_at="2000-01-01T00:00:00Z",
                    revisit_after="2000-01-01T00:00:00Z",
                    resume_cue="resume Mika lookup",
                    dedupe_key="stage20-interrupt-b",
                    status="scheduled",
                    metadata={"evidence_refs": ["unit:b"]},
                )

                nemoqi = bridge.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                mika = bridge.temporal_state(thread_key="Mika", chat_name="Mika", channel="wechat")

                self.assertEqual(first["thread_key"], "wechat:Nemoqi")
                self.assertEqual(second["thread_key"], "wechat:Mika")
                self.assertEqual({item["thread_key"] for item in nemoqi["items"]}, {"wechat:Nemoqi"})
                self.assertEqual({item["thread_key"] for item in mika["items"]}, {"wechat:Mika"})
                self.assertIn("stage20-interrupt-a", nemoqi["due_followup_keys"])
                self.assertIn("stage20-interrupt-b", mika["due_followup_keys"])
            finally:
                self._close_bridge(bridge)

    def test_deferred_reply_creates_one_queue_job_and_deduped_temporal_items(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            store = QueueStore(temp.runtime_dir / "queue.sqlite3")
            service = HoloReplyService(self._config(temp), store=store, runner=_FakeRunner(), memory=bridge)
            try:
                contact = store.ensure_contact("wechat:Nemoqi", "Nemoqi")
                thread, _created = store.ensure_thread(
                    channel="wechat",
                    contact_id=int(contact["id"]),
                    thread_key="Nemoqi",
                    subject="Nemoqi",
                )
                incoming = IncomingMessage(
                    message_id="stage20-defer-message",
                    thread_key="Nemoqi",
                    subject="Nemoqi",
                    sender_email="wechat:Nemoqi",
                    sender_name="Nemoqi",
                    body_text="reply later",
                    channel="wechat",
                )
                stored = store.record_inbound(incoming)["message"]
                turn = ChatTurn(
                    chat_name="Nemoqi",
                    text="reply later",
                    sender="Nemoqi",
                    channel="wechat",
                    thread_key="Nemoqi",
                    message_id="stage20-defer-message",
                )
                selected = {"action_type": "defer_reply", "score": 0.9}

                first_job = service._schedule_deferred_reply(
                    thread=thread,
                    contact=contact,
                    stored_message=stored,
                    turn=turn,
                    selected_action=selected,
                    defer_reason="stage20 unit deferred reply",
                    event_row_id=2201,
                )
                second_job = service._schedule_deferred_reply(
                    thread=thread,
                    contact=contact,
                    stored_message=stored,
                    turn=turn,
                    selected_action=selected,
                    defer_reason="stage20 unit deferred reply",
                    event_row_id=2201,
                )

                jobs = [row for row in store.list_jobs() if row["task_type"] == "deferred_reply"]
                temporal = bridge.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", include_inactive=True)

                self.assertEqual(first_job, second_job)
                self.assertEqual(len(jobs), 1)
                payload = json.loads(jobs[0]["payload_json"])
                self.assertTrue(payload["dedupe_key"].startswith("deferred_reply:wechat:wechat:Nemoqi:"))
                self.assertEqual(len(temporal["deferred_intentions"]), 1)
                self.assertEqual(len(temporal["commitments"]), 1)
                self.assertEqual({item["queue_job_id"] for item in temporal["deferred_intentions"] + temporal["commitments"]}, {first_job})
            finally:
                self._close_service(service)
                store.close()
                self._close_bridge(bridge)

    def test_reload_preserves_open_loops_commitments_resume_candidates_and_due_keys(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                bridge.graph.upsert_temporal_item(
                    item_type="open_loop",
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    confidence=0.63,
                    source_event_id="stage20-open-loop",
                    source_action_ref="reply-a",
                    source_action_type="reply_once",
                    due_at="2000-01-01T00:00:00Z",
                    revisit_after="2000-01-01T00:00:00Z",
                    resume_cue="answer the open loop",
                    dedupe_key="stage20-open-loop",
                    status="open",
                )
                bridge.graph.upsert_temporal_item(
                    item_type="commitment",
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    confidence=0.7,
                    source_event_id="stage20-commitment",
                    source_action_ref="commit-a",
                    source_action_type="defer_reply",
                    due_at="2000-01-01T00:00:00Z",
                    revisit_after="2000-01-01T00:00:00Z",
                    resume_cue="keep the promise",
                    dedupe_key="stage20-commitment",
                    status="scheduled",
                )
                self._seed_resume(bridge, dedupe_key="stage20-reload-resume")
            finally:
                self._close_bridge(bridge)

            reopened = self._bridge(temp)
            try:
                state = reopened.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")

                self.assertEqual(state["thread_key"], "wechat:Nemoqi")
                self.assertEqual(len(state["open_loops"]), 1)
                self.assertEqual(len(state["commitments"]), 1)
                self.assertEqual(len(state["resume_candidates"]), 1)
                self.assertIn("stage20-open-loop", state["due_followup_keys"])
                self.assertIn("stage20-commitment", state["due_followup_keys"])
                self.assertIn("stage20-reload-resume", state["due_followup_keys"])
            finally:
                self._close_bridge(reopened)

    def test_day_gap_followup_does_not_duplicate_jobs_or_resume_candidates(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            store = QueueStore(temp.runtime_dir / "queue.sqlite3")
            try:
                store.initialize()
                incoming = IncomingMessage(
                    message_id="stage20-old-inbound",
                    thread_key="Nemoqi",
                    subject="Nemoqi",
                    sender_email="wechat:Nemoqi",
                    sender_name="Nemoqi",
                    body_text="old pending line",
                    channel="wechat",
                    received_at="2000-01-01T00:00:00Z",
                )
                record = store.record_inbound(incoming)
                store.conn.execute(
                    "UPDATE threads SET last_message_at = ?, last_direction = 'inbound' WHERE id = ?",
                    ("2000-01-01T00:00:00Z", int(record["thread"]["id"])),
                )
                store.conn.commit()

                first = store.schedule_due_followups(after_hours=24, limit=10)
                second = store.schedule_due_followups(after_hours=24, limit=10)
                self._seed_resume(bridge, dedupe_key="stage20-day-gap")
                self._seed_resume(bridge, dedupe_key="stage20-day-gap")
                temporal = bridge.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")

                self.assertEqual(len(first), 1)
                self.assertEqual(second, [])
                self.assertEqual(len([row for row in store.list_jobs() if row["task_type"] == "proactive_followup"]), 1)
                self.assertEqual(len([item for item in temporal["resume_candidates"] if item["dedupe_key"] == "stage20-day-gap"]), 1)
            finally:
                store.close()
                self._close_bridge(bridge)

    def test_reentry_hydrates_temporal_state_before_heavy_recall_when_safe(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                self._seed_resume(bridge, dedupe_key="stage20-reentry")
                bridge.update_active_thread_state(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    direction="inbound",
                    text="we were talking about the postponed line",
                    message_id="stage20-reentry-message",
                    event_row_id=2202,
                )

                with mock.patch.object(bridge, "_hybrid_trace", side_effect=AssertionError("heavy recall should not run")):
                    packet = bridge.sidecar_packet(
                        "we were talking about the postponed line",
                        context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "attachments": []},
                    )

                temporal_contexts = [dict(item.get("temporal_context", {})) for item in packet["action_market"]]
                self.assertEqual(packet["memory_route"], "active_thread")
                self.assertTrue(packet["stage20"]["temporal_visible"])
                self.assertTrue(packet["stage20"]["temporal_used_for_thread"])
                self.assertTrue(packet["stage20"]["commitment_due"])
                self.assertTrue(any(context.get("due") for context in temporal_contexts))
            finally:
                self._close_bridge(bridge)

    def test_terminal_and_expired_items_are_inspectable_but_ignored_for_resumption(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                self._seed_resume(bridge, dedupe_key="stage20-fulfilled", status="fulfilled")
                bridge.graph.upsert_temporal_item(
                    item_type="interruption_marker",
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    confidence=0.66,
                    source_event_id="stage20-canceled",
                    source_action_ref="stage20-canceled-action",
                    source_action_type="external_lookup",
                    due_at="2000-01-01T00:00:00Z",
                    revisit_after="2000-01-01T00:00:00Z",
                    resume_cue="canceled interruption",
                    dedupe_key="stage20-canceled",
                    status="canceled",
                )
                bridge.graph.upsert_temporal_item(
                    item_type="open_loop",
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    confidence=0.66,
                    source_event_id="stage20-expired",
                    source_action_ref="stage20-expired-action",
                    source_action_type="reply_once",
                    due_at="1999-01-01T00:00:00Z",
                    revisit_after="1999-01-01T00:00:00Z",
                    revisit_before="2000-01-01T00:00:00Z",
                    resume_cue="expired open loop",
                    dedupe_key="stage20-expired",
                    status="open",
                )

                inactive = bridge.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", include_inactive=True)
                active = bridge.temporal_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                packet = bridge.sidecar_packet(
                    "still here?",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "attachments": []},
                )

                self.assertEqual({item["dedupe_key"] for item in inactive["items"]}, {"stage20-fulfilled", "stage20-canceled", "stage20-expired"})
                self.assertEqual(active["items"], [])
                self.assertFalse(packet["stage20"]["temporal_visible"])
            finally:
                self._close_bridge(bridge)

    def test_explicit_memory_query_still_escalates_with_temporal_state(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = self._bridge(temp)
            try:
                self._seed_resume(bridge, dedupe_key="stage20-explicit-memory")
                packet = bridge.sidecar_packet(
                    "remember previous history",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "attachments": []},
                )

                self.assertTrue(packet["stage20"]["temporal_visible"])
                self.assertIn(packet["tier"], {"recall", "deep_recall"})
                self.assertEqual(packet["recall_reason"], "stage17:explicit_memory_query")
                self.assertNotEqual(packet["memory_route"], "active_thread")
            finally:
                self._close_bridge(bridge)


if __name__ == "__main__":
    unittest.main()
