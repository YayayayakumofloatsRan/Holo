from __future__ import annotations

import unittest

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage12_acceptance
from holo_host.daemon import HoloDaemon
from holo_host.mind_graph import MindGraph
from holo_host.models import IncomingMessage
from holo_host.reply_api import ChatTurn, HoloReplyService
from tests.test_rag_memory import TempMemoryRepo


class Stage11CalibrationTests(unittest.TestCase):
    def test_outcome_appraisal_records_state_objects_with_provenance(self) -> None:
        with TempMemoryRepo() as temp:
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            try:
                report = graph.record_outcome_appraisal(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    action_type="reply_once",
                    action_ref="turn-1",
                    was_rewarding=0.72,
                    was_ignored=0.04,
                    relational_delta=0.22,
                    identity_delta=0.11,
                    future_initiative_bias=0.66,
                    future_resistance_bias=0.08,
                    metadata={
                        "reply_latency_seconds": 120.0,
                        "initiative_success": 1.0,
                        "correction_count": 1,
                        "usage_total_tokens": 480,
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.18,
                            "predicted_identity_delta": 0.09,
                            "predicted_response_quality": 0.76,
                            "predicted_risk": 0.18,
                        },
                        "evidence_refs": ["replay:turn-1"],
                    },
                )
                subject = graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                frustration = dict(subject["affect_state"]["frustration"])
                response_expectations = dict(subject["world_state"]["response_expectations"])
                goal_state = graph.goal_state()

                self.assertEqual(report["status"], "ok")
                self.assertEqual(frustration["updated_by"], "outcome_appraisal")
                self.assertIn("replay:turn-1", frustration["evidence_refs"])
                self.assertIn("value", response_expectations["reply_likelihood"])
                self.assertIn("initiative_receptivity", response_expectations)
                self.assertIn("value", goal_state["goal_progress"]["identity_maintenance"])
            finally:
                graph.close()

    def test_replay_fixture_exposes_prediction_vs_realized_outcomes(self) -> None:
        with TempMemoryRepo() as temp:
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            try:
                fixtures = [
                    {
                        "action_ref": "turn-a",
                        "was_rewarding": 0.74,
                        "was_ignored": 0.02,
                        "relational_delta": 0.21,
                        "identity_delta": 0.1,
                        "future_initiative_bias": 0.63,
                        "future_resistance_bias": 0.06,
                        "metadata": {
                            "reply_latency_seconds": 90.0,
                            "initiative_success": 1.0,
                            "correction_count": 0,
                            "predicted_outcome": {
                                "predicted_relational_delta": 0.2,
                                "predicted_identity_delta": 0.08,
                                "predicted_response_quality": 0.78,
                                "predicted_risk": 0.14,
                            },
                            "evidence_refs": ["replay:turn-a"],
                        },
                    },
                    {
                        "action_ref": "turn-b",
                        "was_rewarding": 0.18,
                        "was_ignored": 0.62,
                        "relational_delta": -0.04,
                        "identity_delta": 0.01,
                        "future_initiative_bias": 0.16,
                        "future_resistance_bias": 0.34,
                        "metadata": {
                            "reply_latency_seconds": 5400.0,
                            "initiative_success": 0.0,
                            "correction_count": 2,
                            "predicted_outcome": {
                                "predicted_relational_delta": 0.02,
                                "predicted_identity_delta": 0.03,
                                "predicted_response_quality": 0.31,
                                "predicted_risk": 0.42,
                            },
                            "evidence_refs": ["replay:turn-b"],
                        },
                    },
                ]
                errors: list[float] = []
                for item in fixtures:
                    graph.record_outcome_appraisal(
                        channel="wechat",
                        thread_key="Nemoqi",
                        chat_name="Nemoqi",
                        action_type="reply_once",
                        **item,
                    )
                    calibration = dict(graph.subject_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")["world_state"]["last_post_outcome_calibration"])
                    realized = dict(calibration.get("realized_outcome", {}))
                    predicted = dict(calibration.get("predicted_outcome", {}))
                    prediction_error = dict(calibration.get("prediction_error", {}))

                    self.assertTrue(realized)
                    self.assertTrue(predicted)
                    self.assertIn("response_quality", prediction_error)
                    errors.append(abs(float(prediction_error.get("response_quality", 1.0) or 1.0)))

                self.assertLess(sum(errors) / len(errors), 0.5)
            finally:
                graph.close()

    def test_daemon_derives_outcome_payload_from_runtime_evidence(self) -> None:
        evidence = HoloDaemon._derive_action_outcome_from_evidence(
            sent_at="2026-04-09T00:00:00Z",
            recent_messages=[
                {"direction": "outbound", "created_at": "2026-04-09T00:00:00Z", "body_text": "ping"},
                {"direction": "inbound", "created_at": "2026-04-09T00:05:00Z", "body_text": "在，刚忙完"},
                {"direction": "inbound", "created_at": "2026-04-09T00:06:30Z", "body_text": "别太长，简单说"},
            ],
            predicted_outcome={
                "predicted_relational_delta": 0.14,
                "predicted_identity_delta": 0.06,
                "predicted_response_quality": 0.52,
                "predicted_risk": 0.2,
            },
            usage_total_tokens=220,
        )

        self.assertNotEqual(evidence["was_rewarding"], 0.42)
        self.assertEqual(evidence["was_ignored"], 0.0)
        self.assertGreater(evidence["initiative_success"], 0.0)
        self.assertEqual(evidence["correction_count"], 1)
        self.assertIn("prediction:selected_outcome", evidence["evidence_refs"])

    def test_chat_turn_normalized_thread_key_preserves_wechat_prefix(self) -> None:
        turn = ChatTurn(chat_name="Nemoqi", text="hey", thread_key="Nemoqi", channel="wechat")
        self.assertEqual(turn.normalized_thread_key, "wechat:Nemoqi")
        self.assertEqual(turn.synthetic_contact, "wechat:Nemoqi")

    def test_reply_action_appraisal_uses_action_local_usage_and_provenance(self) -> None:
        captured: dict[str, object] = {}

        class FakeStore:
            def get_event(self, event_row_id: int) -> dict[str, object]:
                return {
                    "id": event_row_id,
                    "created_at": "2026-04-09T00:00:00Z",
                    "updated_at": "2026-04-09T00:01:00Z",
                    "executed_at": "2026-04-09T00:01:30Z",
                }

            def _fetchall(self, query: str, args: tuple[object, ...] = ()) -> list[dict[str, object]]:
                if "processor_usage_ledger" in query:
                    return [
                        {
                            "id": 7,
                            "total_tokens": 120,
                            "event_id": "42",
                            "thread_key": "wechat:Nemoqi",
                        }
                    ]
                return []

            def recent_thread_messages(self, thread_id: int, limit: int = 8) -> list[dict[str, object]]:
                return [
                    {"direction": "outbound", "created_at": "2026-04-09T00:01:30Z", "body_text": "reply"},
                    {"direction": "inbound", "created_at": "2026-04-09T00:03:00Z", "body_text": "thanks"},
                ]

        class FakeMemory:
            def appraise_outcome(self, **kwargs):
                captured.update(kwargs)
                return {
                    "ok": True,
                    "action_ref": kwargs["action_ref"],
                    "metadata": kwargs["metadata"],
                }

        fake_service = type(
            "FakeService",
            (),
            {
                "store": FakeStore(),
                "memory": FakeMemory(),
                "config": type("Cfg", (), {"memory": type("Mem", (), {"history_messages": 8})()})(),
                "_appraisable_actions": HoloReplyService._appraisable_actions,
                "_action_ref_for_outcome": HoloReplyService._action_ref_for_outcome,
                "_action_usage_rows": HoloReplyService._action_usage_rows,
            },
        )()
        turn = ChatTurn(chat_name="Nemoqi", text="continue", thread_key="Nemoqi", channel="wechat")
        incoming = turn.to_incoming_message()
        appraisal = HoloReplyService._appraise_action_outcome(
            fake_service,
            turn=turn,
            incoming=incoming,
            thread={"id": 1},
            event_row_id=42,
            selected_action={"action_type": "reply_once"},
            selected_action_type="reply_once",
            sidecar={"selected_prediction": {"predicted_response_quality": 0.81}},
            result={"action": "reply", "outbound_message_id": "out-1"},
        )

        self.assertTrue(appraisal["ok"])
        self.assertEqual(captured["action_type"], "reply_once")
        self.assertEqual(captured["action_ref"], "out-1")
        self.assertEqual(captured["metadata"]["thread_key"], "wechat:Nemoqi")
        self.assertEqual(captured["metadata"]["usage_total_tokens"], 120)
        self.assertIn("usage:processor_usage:7", captured["metadata"]["usage_evidence_refs"])
        self.assertEqual(captured["metadata"]["source"], "reply_api.reply_once")

    def test_reply_action_appraisal_distinguishes_defer_and_silence_refs(self) -> None:
        calls: list[dict[str, object]] = []

        class FakeStore:
            def get_event(self, event_row_id: int) -> dict[str, object]:
                return {
                    "id": event_row_id,
                    "created_at": "2026-04-09T00:00:00Z",
                    "updated_at": "2026-04-09T00:01:00Z",
                    "executed_at": "2026-04-09T00:01:30Z",
                }

            def _fetchall(self, query: str, args: tuple[object, ...] = ()) -> list[dict[str, object]]:
                return []

            def recent_thread_messages(self, thread_id: int, limit: int = 8) -> list[dict[str, object]]:
                return []

        class FakeMemory:
            def appraise_outcome(self, **kwargs):
                calls.append(kwargs)
                return kwargs

        fake_service = type(
            "FakeService",
            (),
            {
                "store": FakeStore(),
                "memory": FakeMemory(),
                "config": type("Cfg", (), {"memory": type("Mem", (), {"history_messages": 8})()})(),
                "_appraisable_actions": HoloReplyService._appraisable_actions,
                "_action_ref_for_outcome": HoloReplyService._action_ref_for_outcome,
                "_action_usage_rows": HoloReplyService._action_usage_rows,
            },
        )()
        turn = ChatTurn(chat_name="Nemoqi", text="continue", thread_key="Nemoqi", channel="wechat")
        incoming = turn.to_incoming_message()

        HoloReplyService._appraise_action_outcome(
            fake_service,
            turn=turn,
            incoming=incoming,
            thread={"id": 1},
            event_row_id=42,
            selected_action={"action_type": "defer_reply"},
            selected_action_type="defer_reply",
            sidecar={"selected_prediction": {}},
            result={"action": "defer_reply", "job_id": "job-9"},
        )
        HoloReplyService._appraise_action_outcome(
            fake_service,
            turn=turn,
            incoming=incoming,
            thread={"id": 1},
            event_row_id=99,
            selected_action={"action_type": "silence"},
            selected_action_type="silence",
            sidecar={"selected_prediction": {}},
            result={"action": "silence"},
        )

        self.assertEqual(calls[0]["action_ref"], "job-9")
        self.assertEqual(calls[1]["action_ref"], "event:99")
        self.assertNotEqual(calls[0]["action_ref"], calls[1]["action_ref"])

    def test_stage12_acceptance_evaluator_reports_pass(self) -> None:
        report = _evaluate_stage12_acceptance(
            health={"status": "ok"},
            thread_key="wechat:Nemoqi",
            chat_name="Nemoqi",
            reply_result={
                "thread_key": "wechat:Nemoqi",
                "selected_action": {"action_type": "reply_once"},
                "outcome_appraisal": {"ok": True},
            },
            defer_result={"outcome_appraisal": {"ok": True}},
            silence_result={"outcome_appraisal": {"ok": True}},
            thread_row={"thread_key": "wechat:Nemoqi"},
            appraisal_rows=[
                {
                    "action_ref": "out-1",
                    "metadata": {
                        "event_row_id": 42,
                        "message_id": "accept-stage12-reply",
                        "thread_key": "wechat:Nemoqi",
                        "usage_evidence_refs": ["usage:event_id:42"],
                    },
                }
            ],
            usage_rows=[{"id": 7, "total_tokens": 120}],
            subject_after_reload={
                "outcome_memory": {"last_action_ref": "out-1"},
                "world_state": {"last_post_outcome_calibration": {"action_ref": "out-1"}},
            },
            helper_contracts={
                "artifact_path": "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history.md",
                "wsl_fallback_candidates": ["http://127.0.0.1:8000", "http://172.28.44.15:8000"],
            },
            roadmap_registry={},
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(report["checks"]["canonical_wechat_identity"])
        self.assertTrue(report["checks"]["ordinary_reply_appraised"])
        self.assertTrue(report["checks"]["action_local_usage_visible"])


if __name__ == "__main__":
    unittest.main()
