from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_simulation_lab import build_bionic_simulation_lab
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule
from holo_host.bionic_user_sim import (
    FREE_DIALOGUE_SUITE,
    BionicUserSimulationHarness,
)
from holo_host.config import load_config
from holo_host.store import QueueStore
from tests.test_stage42_bionic_user_sim import _write_stage42_config
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage67CapabilityAuditRepairTests(unittest.TestCase):
    def _harness(self, root: Path) -> tuple[BionicUserSimulationHarness, QueueStore]:
        config = load_config(config_path=str(_write_stage42_config(root)), repo_root=root)
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        return BionicUserSimulationHarness(config=config, store=store, runner=None), store

    def test_long_free_dialogue_uses_distinct_followups_and_passes_offline(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            harness, store = self._harness(Path(tmpdir))
            try:
                result = harness.run(
                    thread_key="cli:stage67-free-long",
                    chat_name="Stage67FreeLong",
                    channel="cli",
                    scenario=FREE_DIALOGUE_SUITE,
                    turn_limit=20,
                    offline=True,
                )
            finally:
                store.close()

        user_texts = [str(turn["user_text"]) for turn in result["turns"]]
        self.assertEqual(len(user_texts), 20)
        self.assertEqual(len(set(user_texts)), 20)
        self.assertTrue(result["ok"], json.dumps(result["scorecard"], ensure_ascii=False, indent=2))
        self.assertFalse(result["scorecard"]["flags"]["duplicate_followup"])
        self.assertEqual(result["scorecard"]["free_dialogue"]["issue_count"], 0)

    def test_high_pressure_lab_projects_current_bionic_surfaces_for_biomimetic_seeds(self) -> None:
        seed = _seed_run("stage67-biomimetic-legacy")
        for turn in seed["turns"]:
            schedule = turn.setdefault("processor_debug", {}).setdefault("bionic_memory_schedule", {})
            schedule["mode"] = "biomimetic_v1"

        lab = build_bionic_simulation_lab(
            [seed],
            scenarios=14,
            turns_per_scenario=120,
        )
        telemetry = lab["internal_telemetry"]

        self.assertGreaterEqual(telemetry["tool_observation_coverage"], 0.7)
        self.assertGreater(telemetry["average_residual_channel_strength"], 0.15)
        self.assertGreater(telemetry["average_dynamic_delta_saved_tokens"], 100.0)
        self.assertGreater(telemetry["prompt_cache_hit_ratio"], 0.3)
        self.assertGreaterEqual(telemetry["average_recall_budget"], 4.5)
        self.assertEqual(telemetry["visual_rewrite_failure_count"], 0)
        self.assertEqual(telemetry["commitment_failure_count"], 0)

    def test_dynamic_delta_compresses_low_value_route_lines_without_dropping_state(self) -> None:
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "reply_constraints": {"lines": ["never overclaim vision"]},
            "memory_route": "deep_recall",
            "tier": "active_thread",
            "active_thread_state": {
                "summary": "same subject under long audit",
                "latest_user_intent": "repair high pressure free dialogue",
            },
            "selected_action": {"action_type": "reply_once"},
            "stage24": {"response_sketch": "short answer, no repeated opener"},
            "stage25": {"reentry_hint": "carry tool and visual boundary forward"},
            "recall_reconstruction": {
                "summary": "the long audit found repetition and weak tool observation",
                "anchors": ["free dialogue duplicate followup"],
            },
            "selected_memory_ids": ["node-audit", "node-cache", "node-tool"],
            "activation_state": {"heat": 0.78, "motifs": ["audit", "cache", "tool"]},
        }

        schedule = build_bionic_memory_schedule(packet, query="continue the high pressure audit")
        dynamic = "\n".join(schedule["prompt_dynamic_lines"])
        delta = schedule["dynamic_delta_frame"]

        self.assertIn("dynamic_delta=", dynamic)
        self.assertIn("active_summary=", dynamic)
        self.assertIn("latest_user_intent=", dynamic)
        self.assertIn("reconstruction_summary=", dynamic)
        self.assertNotIn("memory_route=deep_recall", dynamic)
        self.assertNotIn("scene_response_sketch=short answer", dynamic)
        self.assertGreaterEqual(delta["compressed_handle_count"], 5)
        self.assertGreater(delta["estimated_saved_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
