from __future__ import annotations

import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage14_acceptance
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "stage14"


class Stage14ReplayTests(unittest.TestCase):
    def test_synthetic_replay_is_reproducible_and_does_not_mutate_live_graph(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                before = bridge.graph.list_action_calibration(channel="wechat", thread_key="wechat:ColdWindow", action_type="defer_reply", limit=4)
                first = bridge.run_stage14_replay(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    artifact_dir=str(temp.runtime_dir / "artifacts-first"),
                )
                second = bridge.run_stage14_replay(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    artifact_dir=str(temp.runtime_dir / "artifacts-second"),
                )
                after = bridge.graph.list_action_calibration(channel="wechat", thread_key="wechat:ColdWindow", action_type="defer_reply", limit=4)
            finally:
                bridge.activation.close()
                bridge.graph.close()

            self.assertEqual(first["aggregate_metrics"], second["aggregate_metrics"])
            self.assertIn("raw_aggregate_metrics", first)
            self.assertIn("risk_mae", first["raw_aggregate_metrics"])
            self.assertEqual(len(before), len(after))
            self.assertEqual(first["fixture_count"], 4)
            self.assertGreater(first["aggregate_metrics"]["policy_regret_vs_best_available_action"], 0.0)
            self.assertGreater(first["aggregate_metrics"]["false_initiative_block_rate"], 0.0)
            self.assertGreater(first["aggregate_metrics"]["overlong_reply_rate"], 0.0)
            self.assertGreater(first["aggregate_metrics"]["stiffness_overflow_rate"], 0.0)

    def test_archive_and_calibration_history_sources_run_through_same_harness(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                rm.archive_turn(
                    "I am still here.",
                    "Good, keep the same thread.",
                    source="unit.archive",
                    tags=["wechat", "chat_reply"],
                    metadata={"thread_key": "wechat:Nemoqi", "chat_name": "Nemoqi", "channel": "wechat"},
                )
                bridge.appraise_outcome(
                    channel="wechat",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    action_type="reply_once",
                    action_ref="history-seed",
                    was_rewarding=0.74,
                    was_ignored=0.04,
                    relational_delta=0.18,
                    identity_delta=0.08,
                    future_initiative_bias=0.36,
                    future_resistance_bias=0.06,
                    metadata={
                        "predicted_outcome": {
                            "predicted_relational_delta": 0.14,
                            "predicted_identity_delta": 0.06,
                            "predicted_response_quality": 0.72,
                            "predicted_risk": 0.16,
                        },
                        "reply_latency_seconds": 120.0,
                        "correction_count": 0,
                        "initiative_success": 1.0,
                        "evidence_refs": ["history-seed"],
                    },
                )
                archive_report = bridge.run_stage14_replay(
                    source_type="archive_fixture",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    artifact_dir=str(temp.runtime_dir / "archive-artifacts"),
                )
                history_report = bridge.run_stage14_replay(
                    source_type="calibration_history_fixture",
                    thread_key="wechat:Nemoqi",
                    chat_name="Nemoqi",
                    artifact_dir=str(temp.runtime_dir / "history-artifacts"),
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

            self.assertGreaterEqual(archive_report["fixture_count"], 1)
            self.assertGreaterEqual(history_report["fixture_count"], 1)
            self.assertTrue(all(str(item["thread_key"]).startswith("wechat:") for item in archive_report["fixtures"]))
            self.assertTrue(all(str(item["thread_key"]).startswith("wechat:") for item in history_report["fixtures"]))

    def test_accept_stage14_evaluator_reports_pass(self) -> None:
        report = _evaluate_stage14_acceptance(
            health={"status": "ok"},
            primary_report={
                "fixture_count": 4,
                "aggregate_metrics": {
                    "response_quality_mae": 0.22,
                    "relational_delta_mae": 0.16,
                    "risk_mae": 0.18,
                    "calibration_support_by_action_type": {"defer_reply": 1, "reply_multi": 1},
                    "false_initiative_block_rate": 0.25,
                    "overlong_reply_rate": 0.25,
                    "stiffness_overflow_rate": 0.25,
                    "cost_per_successful_turn": 210.0,
                    "policy_regret_vs_best_available_action": 0.12,
                },
                "fixtures": [
                    {"thread_key": "wechat:Nemoqi"},
                    {"thread_key": "wechat:ColdWindow"},
                ],
                "artifacts": {"summary_json": "x", "summary_md": "y"},
            },
            secondary_report={
                "aggregate_metrics": {
                    "response_quality_mae": 0.22,
                    "relational_delta_mae": 0.16,
                    "risk_mae": 0.18,
                    "calibration_support_by_action_type": {"defer_reply": 1, "reply_multi": 1},
                    "false_initiative_block_rate": 0.25,
                    "overlong_reply_rate": 0.25,
                    "stiffness_overflow_rate": 0.25,
                    "cost_per_successful_turn": 210.0,
                    "policy_regret_vs_best_available_action": 0.12,
                }
            },
            live_before={"wechat:Nemoqi:reply_once": 0},
            live_after={"wechat:Nemoqi:reply_once": 0},
        )

        self.assertEqual(report["status"], "pass")
        self.assertTrue(all(bool(value) for value in report["checks"].values()))


if __name__ == "__main__":
    unittest.main()
