from __future__ import annotations

import unittest

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage13_acceptance
from holo_host.memory_bridge import MemoryBridge
from holo_host.mind_graph import MindGraph
from tests.test_rag_memory import TempMemoryRepo


class Stage13CalibrationTests(unittest.TestCase):
    def test_action_calibration_persists_and_confidence_can_drop(self) -> None:
        with TempMemoryRepo() as temp:
            db_path = temp.runtime_dir / "mind_graph.sqlite3"
            graph = MindGraph(temp.repo_root, rag=rm, db_path=db_path)
            try:
                graph.record_outcome_appraisal(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    action_type="reply_once",
                    action_ref="good-1",
                    was_rewarding=0.82,
                    was_ignored=0.02,
                    relational_delta=0.22,
                    identity_delta=0.08,
                    future_initiative_bias=0.66,
                    future_resistance_bias=0.04,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.2,
                            "predicted_identity_delta": 0.07,
                            "predicted_response_quality": 0.8,
                            "predicted_risk": 0.12,
                        },
                        "reply_latency_seconds": 90.0,
                        "initiative_success": 1.0,
                        "correction_count": 0,
                        "evidence_refs": ["stage13:good-1"],
                    },
                )
                good_row = graph.list_action_calibration(channel="wechat", thread_key="wechat:Nemoqi", action_type="reply_once", limit=1)[0]

                graph.record_outcome_appraisal(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    action_type="reply_once",
                    action_ref="bad-1",
                    was_rewarding=0.14,
                    was_ignored=0.88,
                    relational_delta=-0.28,
                    identity_delta=-0.12,
                    future_initiative_bias=0.0,
                    future_resistance_bias=0.7,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.18,
                            "predicted_identity_delta": 0.05,
                            "predicted_response_quality": 0.74,
                            "predicted_risk": 0.16,
                        },
                        "reply_latency_seconds": 7200.0,
                        "initiative_success": 0.0,
                        "correction_count": 2,
                        "evidence_refs": ["stage13:bad-1"],
                    },
                )
                after_row = graph.list_action_calibration(channel="wechat", thread_key="wechat:Nemoqi", action_type="reply_once", limit=1)[0]
                history = graph.trace_outcome_history(channel="wechat", thread_key="wechat:Nemoqi", action_type="reply_once")
            finally:
                graph.close()

            reopened = MindGraph(temp.repo_root, rag=rm, db_path=db_path)
            try:
                persisted_row = reopened.list_action_calibration(channel="wechat", thread_key="wechat:Nemoqi", action_type="reply_once", limit=1)[0]
                self.assertEqual(int(after_row["support_count"]), 2)
                self.assertGreater(float(after_row["recent_support_count"]), 0.0)
                self.assertGreater(float(after_row["response_quality_mae"]), 0.0)
                self.assertLess(float(after_row["confidence"]), float(good_row["confidence"]))
                self.assertEqual(str(persisted_row["thread_key_bucket"]), "wechat:Nemoqi")
                self.assertLess(float(history["history"][0]["relational_delta"]), 0.0)
                self.assertLess(float(history["history"][0]["identity_delta"]), 0.0)
            finally:
                reopened.close()

    def test_empirical_overlay_can_change_action_ranking(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                subject = bridge.graph.subject_state(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat")
                context = {"channel": "wechat", "thread_key": "wechat:Nemoqi", "chat_name": "Nemoqi"}
                intent_state = {
                    "reply_pull": 0.7,
                    "resistance_pull": 0.15,
                    "continuity_pull": 0.35,
                    "internal_pressure": 0.2,
                    "low_signal": False,
                }
                relationship_state = {"continuity_score": 0.6}
                game_state = {"pressure_level": 0.2}
                before_reply = bridge._simulate_action_candidate(
                    action={"action_type": "reply_once"},
                    query="continue building this",
                    intent_state=intent_state,
                    relationship_state=relationship_state,
                    game_state=game_state,
                    affect_state=subject["affect_state"],
                    drive_state=subject["drive_state"],
                    value_state=subject["value_state"],
                    conflict_state=subject["conflict_state"],
                    world_state=subject["world_state"],
                    context=context,
                )
                before_defer = bridge._simulate_action_candidate(
                    action={"action_type": "defer_reply"},
                    query="continue building this",
                    intent_state=intent_state,
                    relationship_state=relationship_state,
                    game_state=game_state,
                    affect_state=subject["affect_state"],
                    drive_state=subject["drive_state"],
                    value_state=subject["value_state"],
                    conflict_state=subject["conflict_state"],
                    world_state=subject["world_state"],
                    context=context,
                )

                for index in range(6):
                    bridge.appraise_outcome(
                        channel="wechat",
                        thread_key="wechat:Nemoqi",
                        chat_name="Nemoqi",
                        action_type="reply_once",
                        action_ref=f"reply-bad-{index}",
                        was_rewarding=0.12,
                        was_ignored=0.9,
                        relational_delta=-0.24,
                        identity_delta=-0.08,
                        future_initiative_bias=0.0,
                        future_resistance_bias=0.72,
                        metadata={
                            "predicted_outcome": {
                                "predicted_relational_delta": 0.16,
                                "predicted_identity_delta": 0.06,
                                "predicted_response_quality": 0.76,
                                "predicted_risk": 0.18,
                            },
                            "reply_latency_seconds": 6400.0,
                            "initiative_success": 0.0,
                            "correction_count": 2,
                            "evidence_refs": [f"stage13:reply-bad:{index}"],
                        },
                    )
                    bridge.appraise_outcome(
                        channel="wechat",
                        thread_key="wechat:Nemoqi",
                        chat_name="Nemoqi",
                        action_type="defer_reply",
                        action_ref=f"defer-good-{index}",
                        was_rewarding=0.72,
                        was_ignored=0.04,
                        relational_delta=0.1,
                        identity_delta=0.12,
                        future_initiative_bias=0.52,
                        future_resistance_bias=0.08,
                        metadata={
                            "predicted_outcome": {
                                "predicted_relational_delta": 0.08,
                                "predicted_identity_delta": 0.1,
                                "predicted_response_quality": 0.58,
                                "predicted_risk": 0.14,
                            },
                            "reply_latency_seconds": 220.0,
                            "initiative_success": 1.0,
                            "correction_count": 0,
                            "evidence_refs": [f"stage13:defer-good:{index}"],
                        },
                    )
                bridge.clear_packet_cache()
                after_subject = bridge.graph.subject_state(thread_key="wechat:Nemoqi", chat_name="Nemoqi", channel="wechat")
                after_reply = bridge._simulate_action_candidate(
                    action={"action_type": "reply_once"},
                    query="continue building this",
                    intent_state=intent_state,
                    relationship_state=relationship_state,
                    game_state=game_state,
                    affect_state=after_subject["affect_state"],
                    drive_state=after_subject["drive_state"],
                    value_state=after_subject["value_state"],
                    conflict_state=after_subject["conflict_state"],
                    world_state=after_subject["world_state"],
                    context=context,
                )
                after_defer = bridge._simulate_action_candidate(
                    action={"action_type": "defer_reply"},
                    query="continue building this",
                    intent_state=intent_state,
                    relationship_state=relationship_state,
                    game_state=game_state,
                    affect_state=after_subject["affect_state"],
                    drive_state=after_subject["drive_state"],
                    value_state=after_subject["value_state"],
                    conflict_state=after_subject["conflict_state"],
                    world_state=after_subject["world_state"],
                    context=context,
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

            self.assertGreater(float(before_reply["recommended_bias"]), float(before_defer["recommended_bias"]))
            self.assertLess(float(after_reply["recommended_bias"]), float(after_defer["recommended_bias"]))
            self.assertLess(float(after_reply["empirical_overlay_delta"]), 0.0)
            self.assertGreater(float(after_defer["empirical_overlay_delta"]), 0.0)
            self.assertTrue(after_reply["empirical_calibration"])
            self.assertTrue(after_defer["empirical_calibration"])

    def test_accept_stage13_evaluator_reports_pass(self) -> None:
        report = _evaluate_stage13_acceptance(
            health={"status": "ok"},
            thread_key="wechat:Nemoqi",
            chat_name="Nemoqi",
            calibration_rows=[
                {
                    "action_type": "defer_reply",
                    "scenario_bucket": "hold:ordinary",
                    "support_count": 4,
                    "recent_support_count": 2.6,
                    "confidence": 0.44,
                    "last_updated_at": "2026-04-09T12:00:00Z",
                    "metadata": {
                        "recent_errors": [
                            {"response_quality": 0.08},
                            {"response_quality": 0.32},
                        ]
                    },
                }
            ],
            before_rows=[
                {
                    "action_type": "defer_reply",
                    "scenario_bucket": "hold:ordinary",
                    "support_count": 3,
                    "confidence": 0.62,
                }
            ],
            outcome_history=[
                {
                    "action_ref": "turn-bad",
                    "relational_delta": -0.22,
                    "identity_delta": -0.08,
                }
            ],
            prediction_trace={
                "comparisons": [{"action_ref": "turn-bad"}],
                "summary": {"response_quality_mae": 0.28, "relational_delta_mae": 0.16, "risk_mae": 0.2},
            },
            subject_after_reload={
                "world_state": {
                    "recent_outcome_history": [{"action_ref": "turn-bad"}],
                    "recent_prediction_errors": [{"action_ref": "turn-bad"}],
                    "action_calibration_summary": {"strongest_actions": [{"action_type": "defer_reply"}]},
                }
            },
            ranking_fixture={
                "before_top_action": "reply_once",
                "after_top_action": "defer_reply",
                "after_market": [{"action_type": "defer_reply", "empirical_overlay_delta": 0.08}],
            },
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(bool(value) for value in report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
