from __future__ import annotations

import unittest

from holo_host.bionic_memory_lifecycle import build_bionic_memory_lifecycle
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule


class BionicMemoryLifecycleTests(unittest.TestCase):
    def test_lifecycle_proposes_consolidation_without_self_memory_write(self) -> None:
        packet = {
            "active_thread_state": {
                "summary": "current thread carries the corrected symbol",
                "latest_user_intent": "check whether the memory survived",
            },
            "activation_state": {"heat": 0.88, "motifs": ["rusted_screw", "thread_loss"]},
            "affect_state": {"continuity_anxiety": 0.8},
            "drive_state": {"seek_continuity": 0.75},
            "selected_memory_ids": ["node-rusted-screw"],
            "recall_reconstruction": {
                "summary": "final symbol is rusted screw, not blue clip",
                "anchors": ["rusted screw means fear of thread loss"],
            },
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(
            packet,
            query="do you remember the corrected symbol?",
        )

        lifecycle = build_bionic_memory_lifecycle(
            packet,
            query="do you remember the corrected symbol?",
        )

        consolidation = lifecycle["consolidation_intent"]
        replay = lifecycle["replay_plan"]

        self.assertEqual(lifecycle["mode"], "biomimetic_lifecycle_v1")
        self.assertGreaterEqual(consolidation["priority"], 0.7)
        self.assertIn("semantic_reconstruction", consolidation["targets"])
        self.assertIn("reactivated_index", consolidation["targets"])
        self.assertFalse(consolidation["self_memory_write"])
        self.assertEqual(consolidation["write_policy"], "diagnostic_intent_only")
        self.assertTrue(replay["triggered"])
        self.assertFalse(replay["background_loop_allowed"])
        self.assertFalse(replay["dream_replay_allowed"])
        self.assertTrue(lifecycle["prompt_lines"])

    def test_lifecycle_exposes_forgetting_gate_without_dropping_protected_lines(self) -> None:
        packet = {
            "memory_route": "active_thread",
            "tier": "deep_recall",
            "active_thread_state": {
                "summary": "current thread carries the corrected symbol",
                "latest_user_intent": "check compression audit",
            },
            "selected_action": {"action_type": "reply_once"},
            "stage20": {"resume_cue": "do not lose the corrected symbol"},
            "stage24": {"response_sketch": "answer the correction first"},
            "stage25": {"reentry_hint": "return through current symbol"},
            "activation_state": {"heat": 0.9, "motifs": ["old_blue_clip", "rusted_screw", "audit"]},
            "selected_memory_ids": ["node-blue-clip", "node-rusted-screw"],
            "episodic_recall": {"lines": ["blue clip was replaced by rusted screw"]},
            "recall_reconstruction": {
                "summary": "final symbol is rusted screw, not blue clip",
                "anchors": ["rusted screw means fear of thread loss"],
            },
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(packet, query="plain continuation")

        lifecycle = build_bionic_memory_lifecycle(packet, query="plain continuation")

        forgetting = lifecycle["forgetting_gate"]

        self.assertEqual(forgetting["mode"], "synaptic_pruning_v1")
        self.assertFalse(forgetting["protected_line_dropped"])
        self.assertIn("memory_route", forgetting["decay_candidates"])
        self.assertIn("tier", forgetting["decay_candidates"])
        self.assertNotIn("active_summary", forgetting["decay_candidates"])
        self.assertNotIn("reconstruction_summary", forgetting["decay_candidates"])
        self.assertGreater(lifecycle["memory_pressure"]["dropped_dynamic_line_count"], 0)

    def test_lifecycle_treats_correction_marker_as_reactivation_target(self) -> None:
        packet = {
            "active_thread_state": {
                "summary": "old marker may conflict with new marker",
                "latest_user_intent": "Correction: rusted screw replaces blue paperclip",
            },
            "selected_action": {"action_type": "reply_once"},
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(
            packet,
            query="Correction: it is not blue paperclip anymore. It is rusted screw.",
        )

        lifecycle = build_bionic_memory_lifecycle(
            packet,
            query="Correction: it is not blue paperclip anymore. It is rusted screw.",
        )

        self.assertIn("correction_reactivation_marker", lifecycle["consolidation_intent"]["targets"])
        self.assertIn("correction_reactivation_marker", lifecycle["replay_plan"]["sources"])
        self.assertGreaterEqual(lifecycle["consolidation_intent"]["priority"], 0.55)
        self.assertTrue(lifecycle["replay_plan"]["triggered"])


if __name__ == "__main__":
    unittest.main()
