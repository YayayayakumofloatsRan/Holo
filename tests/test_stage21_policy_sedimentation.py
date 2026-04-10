from __future__ import annotations

import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.memory_bridge import MemoryBridge
from tests.test_rag_memory import TempMemoryRepo


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "stage14"


def _seed_policy_evidence(
    bridge: MemoryBridge,
    *,
    thread_key: str = "Nemoqi",
    chat_name: str = "Nemoqi",
    action_type: str = "defer_reply",
    prefix: str = "policy",
    count: int = 6,
) -> dict:
    for index in range(count):
        bridge.appraise_outcome(
            channel="wechat",
            thread_key=thread_key,
            chat_name=chat_name,
            action_type=action_type,
            action_ref=f"{prefix}-{action_type}-{index}",
            was_rewarding=0.86,
            was_ignored=0.02,
            relational_delta=0.11,
            identity_delta=0.12,
            future_initiative_bias=0.48,
            future_resistance_bias=0.05,
            metadata={
                "predicted_outcome": {
                    "predicted_relational_delta": 0.1,
                    "predicted_identity_delta": 0.11,
                    "predicted_response_quality": 0.84,
                    "predicted_risk": 0.08,
                },
                "reply_latency_seconds": 90.0,
                "initiative_success": 1.0,
                "correction_count": 0,
                "query": "continue this carefully",
                "evidence_refs": [f"stage21:{prefix}:{action_type}:{index}"],
            },
        )
    candidates = bridge.show_policy_candidates(thread_key=thread_key, chat_name=chat_name, channel="wechat")
    return next((dict(item) for item in candidates.get("candidates", []) if str(item.get("action_type", "")) == action_type), {})


def _action_row(packet: dict, action_type: str) -> dict:
    return next((dict(item) for item in list(packet.get("action_market", [])) if str(item.get("action_type", "")) == action_type), {})


class Stage21PolicySedimentationTests(unittest.TestCase):
    def test_policy_candidates_are_created_from_repeated_evidence(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                candidate = _seed_policy_evidence(bridge)
            finally:
                bridge.activation.close()
                bridge.graph.close()

        self.assertEqual(candidate["status"], "candidate")
        self.assertEqual(candidate["replay_approval_status"], "pending")
        self.assertEqual(candidate["thread_key"], "wechat:Nemoqi")
        self.assertGreaterEqual(int(candidate["support_count"]), 3)
        self.assertGreater(float(candidate["action_preference_shift"]), 0.0)
        self.assertIn("correction_pattern", candidate["scenario_features"])
        self.assertTrue(candidate["evidence_refs"])

    def test_replay_gate_can_approve_or_reject_candidates(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                defer_candidate = _seed_policy_evidence(bridge, prefix="approve")
                counter_candidate = _seed_policy_evidence(bridge, action_type="counter_offer", prefix="reject")
                replay_report = {"fixture_count": 1, "aggregate_metrics": {"policy_regret_vs_best_available_action": 0.0}}
                approved = bridge.graph.review_policy_candidate(
                    policy_id=str(defer_candidate["policy_id"]),
                    approved=True,
                    replay_report=replay_report,
                    reason="unit_approve",
                )
                rejected = bridge.graph.review_policy_candidate(
                    policy_id=str(counter_candidate["policy_id"]),
                    approved=False,
                    replay_report=replay_report,
                    reason="unit_reject",
                )
                promoted = bridge.show_promoted_policies(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
            finally:
                bridge.activation.close()
                bridge.graph.close()

        self.assertEqual(approved["status"], "promoted")
        self.assertEqual(approved["replay_approval_status"], "approved")
        self.assertEqual(rejected["status"], "rejected")
        self.assertEqual(rejected["replay_approval_status"], "rejected")
        self.assertTrue(any(item["policy_id"] == approved["policy_id"] for item in promoted["promoted_policies"]))

    def test_promoted_policy_changes_ranking_and_rollback_restores_overlay(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                candidate = _seed_policy_evidence(bridge, prefix="ranking")
                query = "continue this carefully"
                context = {"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "message_id": "stage21-before"}
                before = bridge.sidecar_packet(query, context=context)
                approved = bridge.graph.review_policy_candidate(
                    policy_id=str(candidate["policy_id"]),
                    approved=True,
                    replay_report={"fixture_count": 1, "aggregate_metrics": {"policy_regret_vs_best_available_action": 0.0}},
                    reason="unit_ranking",
                )
                bridge.clear_packet_cache()
                after = bridge.sidecar_packet(query, context={**context, "message_id": "stage21-after"})
                rollback = bridge.rollback_policy(policy_id=str(approved["policy_id"]), reason="unit_rollback")
                bridge.clear_packet_cache()
                restored = bridge.sidecar_packet(query, context={**context, "message_id": "stage21-restored"})
            finally:
                bridge.activation.close()
                bridge.graph.close()

        before_defer = _action_row(before, "defer_reply")
        after_defer = _action_row(after, "defer_reply")
        restored_defer = _action_row(restored, "defer_reply")
        self.assertGreater(float(after_defer["policy_sedimentation_delta"]), 0.0)
        self.assertGreater(float(after_defer["score"]), float(before_defer["score"]))
        self.assertTrue(after["stage21"]["sediment_bias_applied"])
        self.assertEqual(rollback["status"], "rolled_back")
        self.assertEqual(float(restored_defer.get("policy_sedimentation_delta", 0.0)), 0.0)
        self.assertFalse(restored["stage21"]["sediment_bias_applied"])

    def test_policy_sedimentation_does_not_worsen_replay_regret_fixture(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                before = bridge.replay_policy_regret(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    artifact_dir=str(temp.runtime_dir / "replay-before"),
                )
                candidate = _seed_policy_evidence(bridge, prefix="regret")
                bridge.graph.review_policy_candidate(
                    policy_id=str(candidate["policy_id"]),
                    approved=True,
                    replay_report=before,
                    reason="unit_regret",
                )
                after = bridge.replay_policy_regret(
                    source_type="synthetic_fixture",
                    fixture_path=str(FIXTURE_DIR),
                    artifact_dir=str(temp.runtime_dir / "replay-after"),
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

        before_regret = float(before["aggregate_metrics"]["policy_regret_vs_best_available_action"])
        after_regret = float(after["aggregate_metrics"]["policy_regret_vs_best_available_action"])
        self.assertLessEqual(after_regret, before_regret + 0.001)

    def test_policy_scope_is_canonical_thread_local_and_does_not_grant_send(self) -> None:
        with TempMemoryRepo() as temp:
            bridge = MemoryBridge(temp.repo_root, graph_db_path=temp.runtime_dir / "mind_graph.sqlite3", rag=rm)
            try:
                candidate = _seed_policy_evidence(bridge, prefix="scope")
                bridge.graph.review_policy_candidate(
                    policy_id=str(candidate["policy_id"]),
                    approved=True,
                    replay_report={"fixture_count": 1, "aggregate_metrics": {"policy_regret_vs_best_available_action": 0.0}},
                    reason="unit_scope",
                )
                bridge.clear_packet_cache()
                nemoqi_packet = bridge.sidecar_packet(
                    "continue this carefully",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi", "message_id": "stage21-nemoqi"},
                )
                other_packet = bridge.sidecar_packet(
                    "continue this carefully",
                    context={"channel": "wechat", "thread_key": "Other", "chat_name": "Other", "message_id": "stage21-other"},
                )
            finally:
                bridge.activation.close()
                bridge.graph.close()

        nemoqi_defer = _action_row(nemoqi_packet, "defer_reply")
        other_defer = _action_row(other_packet, "defer_reply")
        self.assertEqual(candidate["thread_key"], "wechat:Nemoqi")
        self.assertGreater(float(nemoqi_defer.get("policy_sedimentation_delta", 0.0)), 0.0)
        self.assertEqual(float(other_defer.get("policy_sedimentation_delta", 0.0)), 0.0)
        self.assertFalse(bool(nemoqi_defer.get("send_allowed", True)))
        self.assertTrue(nemoqi_packet["stage21"]["hard_gate_preserved"])


if __name__ == "__main__":
    unittest.main()
