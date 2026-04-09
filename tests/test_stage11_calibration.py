from __future__ import annotations

import unittest

import holo_memory_library.rag_memory as rm
from holo_host.daemon import HoloDaemon
from holo_host.mind_graph import MindGraph
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


if __name__ == "__main__":
    unittest.main()
