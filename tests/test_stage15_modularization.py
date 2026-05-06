from __future__ import annotations

import unittest
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.memory_bridge import MemoryBridge
from holo_host.stage14_replay import Stage14ReplayHarness
from tests.test_rag_memory import TempMemoryRepo


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "stage14"


def _round4(value: float) -> float:
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


class Stage15ModularizationTests(unittest.TestCase):
    def test_stage14_replay_metrics_stay_on_baseline(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                report = bridge.run_stage14_replay(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    artifact_dir=str(temp.runtime_dir / "stage15-artifacts"),
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

        metrics = report["aggregate_metrics"]
        raw_metrics = report["raw_aggregate_metrics"]
        self.assertEqual(report["fixture_count"], 4)
        self.assertAlmostEqual(_round4(float(raw_metrics["risk_mae"])), float(metrics["risk_mae"]), places=4)
        self.assertAlmostEqual(
            _round4(float(raw_metrics["policy_regret_vs_best_available_action"])),
            float(metrics["policy_regret_vs_best_available_action"]),
            places=4,
        )
        self.assertEqual(metrics["calibration_support_by_action_type"], {"defer_reply": 1, "reply_multi": 1, "reply_once": 1})
        self.assertAlmostEqual(float(metrics["response_quality_mae"]), 0.3011, places=4)
        self.assertAlmostEqual(float(metrics["relational_delta_mae"]), 0.1681, places=4)
        self.assertAlmostEqual(float(metrics["risk_mae"]), 0.1182, places=4)
        self.assertAlmostEqual(float(metrics["false_initiative_block_rate"]), 0.25, places=4)
        self.assertAlmostEqual(float(metrics["overlong_reply_rate"]), 0.25, places=4)
        self.assertAlmostEqual(float(metrics["stiffness_overflow_rate"]), 0.25, places=4)
        self.assertAlmostEqual(float(metrics["cost_per_successful_turn"]), 755.0, places=4)
        self.assertAlmostEqual(float(metrics["policy_regret_vs_best_available_action"]), 0.0613, places=4)

    def test_fixture_policy_snapshots_stay_stable(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                harness = Stage14ReplayHarness(bridge)
                fixtures = harness.load_fixtures(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    channel="wechat",
                    limit=8,
                )
                results = {item["fixture_id"]: harness.evaluate_fixture(item) for item in fixtures}
            finally:
                bridge.activation.close()
                bridge.graph.close()

        self.assertEqual(results["canonical-identity-edge"]["selected_action"], "reply_once")
        self.assertEqual(results["canonical-identity-edge"]["best_available_action"], "reply_once")
        self.assertAlmostEqual(float(results["canonical-identity-edge"]["policy_regret_vs_best_available_action"]), 0.0, places=4)

        self.assertEqual(results["cold-initiative-window"]["selected_action"], "defer_reply")
        self.assertEqual(results["cold-initiative-window"]["best_available_action"], "reply_once")
        self.assertAlmostEqual(float(results["cold-initiative-window"]["policy_regret_vs_best_available_action"]), 0.0561, places=4)

        self.assertEqual(results["correction-heavy-exchange"]["selected_action"], "reply_multi")
        self.assertEqual(results["correction-heavy-exchange"]["best_available_action"], "reply_once")
        self.assertAlmostEqual(float(results["correction-heavy-exchange"]["policy_regret_vs_best_available_action"]), 0.1766, places=4)

        self.assertEqual(results["long-delay-positive"]["selected_action"], "defer_reply")
        self.assertEqual(results["long-delay-positive"]["best_available_action"], "reply_once")
        self.assertAlmostEqual(float(results["long-delay-positive"]["policy_regret_vs_best_available_action"]), 0.0124, places=4)

    def test_expression_budget_outcomes_snapshot(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                harness = Stage14ReplayHarness(bridge)
                fixtures = harness.load_fixtures(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    channel="wechat",
                    limit=8,
                )
                results = {item["fixture_id"]: harness.evaluate_fixture(item) for item in fixtures}
            finally:
                bridge.activation.close()
                bridge.graph.close()

        correction_heavy = results["correction-heavy-exchange"]
        long_delay = results["long-delay-positive"]
        self.assertEqual(correction_heavy["selected_action"], "reply_multi")
        self.assertTrue(bool(correction_heavy["overlong_reply"]))
        self.assertTrue(bool(correction_heavy["stiffness_overflow"]))
        self.assertEqual(long_delay["selected_action"], "defer_reply")
        self.assertFalse(bool(long_delay["overlong_reply"]))

    def test_calibration_summary_snapshot_survives_reload(self) -> None:
        with TempMemoryRepo() as temp:
            db_path = temp.runtime_dir / "mind_graph.sqlite3"
            bridge = MemoryBridge(temp.repo_root, graph_db_path=db_path, rag=rm)
            try:
                bridge.appraise_outcome(
                    channel="wechat",
                    thread_key="wechat:TestUser",
                    chat_name="TestUser",
                    action_type="reply_once",
                    action_ref="stage15-snapshot",
                    was_rewarding=0.81,
                    was_ignored=0.03,
                    relational_delta=0.19,
                    identity_delta=0.09,
                    future_initiative_bias=0.38,
                    future_resistance_bias=0.05,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.16,
                            "predicted_identity_delta": 0.05,
                            "predicted_response_quality": 0.76,
                            "predicted_risk": 0.14,
                        },
                        "reply_latency_seconds": 150.0,
                        "initiative_success": 1.0,
                        "correction_count": 0,
                        "evidence_refs": ["stage15:snapshot"],
                    },
                )
                state_before = bridge.graph.subject_state(thread_key="wechat:TestUser", chat_name="TestUser", channel="wechat")
            finally:
                bridge.activation.close()
                bridge.graph.close()

            reopened = MemoryBridge(temp.repo_root, graph_db_path=db_path, rag=rm)
            try:
                state_after = reopened.graph.subject_state(thread_key="wechat:TestUser", chat_name="TestUser", channel="wechat")
            finally:
                reopened.activation.close()
                reopened.graph.close()

        summary = state_after["world_state"]["action_calibration_summary"]
        last = state_after["world_state"]["last_post_outcome_calibration"]
        self.assertEqual(summary["strongest_actions"][0]["action_type"], "reply_once")
        self.assertAlmostEqual(float(summary["strongest_actions"][0]["confidence"]), 0.5263, places=4)
        self.assertEqual(last["action_ref"], "stage15-snapshot")
        self.assertEqual(last["calibration_bucket"]["thread_key_bucket"], "wechat:TestUser")
        self.assertAlmostEqual(float(last["calibration_stats"]["response_quality_mae"]), 0.1888, places=4)
        self.assertAlmostEqual(float(last["calibration_stats"]["risk_mae"]), 0.1164, places=4)
        self.assertEqual(state_before["world_state"]["action_calibration_summary"], state_after["world_state"]["action_calibration_summary"])


if __name__ == "__main__":
    unittest.main()
