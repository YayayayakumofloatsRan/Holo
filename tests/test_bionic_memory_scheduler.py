from __future__ import annotations

import unittest

from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule


class BionicMemorySchedulerTests(unittest.TestCase):
    def test_scheduler_separates_cortical_schema_from_dynamic_memory(self) -> None:
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "reply_constraints": {"lines": ["never overclaim vision"]},
            "active_thread_state": {
                "summary": "current thread is hot",
                "latest_user_intent": "continue the symbol",
            },
            "stage25": {"used": True, "reentry_hint": "return to symbol"},
            "activation_state": {"heat": 0.72, "motifs": ["symbol", "continuity"]},
            "selected_memory_ids": ["node-a", "node-b"],
            "episodic_recall": {"lines": ["the symbol changed from clip to rusted screw"]},
        }

        schedule = build_bionic_memory_schedule(packet, query="continue the symbol")

        self.assertEqual(schedule["mode"], "biomimetic_v1")
        self.assertTrue(schedule["cortical_schema"]["stable_prefix_lines"])
        self.assertTrue(schedule["working_memory"]["dynamic_lines"])
        self.assertTrue(schedule["hippocampal_index"]["dynamic_lines"])
        self.assertIn("identity=yes", "\n".join(schedule["provider_prefix_lines"]))
        self.assertIn("current thread is hot", "\n".join(schedule["dynamic_context_lines"]))
        self.assertFalse(schedule["consolidation_targets"]["self_memory_write"])

    def test_salience_gate_expands_recall_budget_for_memory_pressure(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "activation_state": {"heat": 0.9, "motifs": ["thread_loss"]},
                "affect_state": {"continuity_anxiety": 0.8, "curiosity": 0.7},
                "drive_state": {"seek_continuity": 0.9},
                "stage20": {"temporal_visible": True, "resume_cue": "do not lose this"},
            },
            query="你还记得刚才那个修正吗？",
        )

        self.assertGreaterEqual(schedule["salience_gate"]["score"], 0.55)
        self.assertGreaterEqual(schedule["salience_gate"]["recall_budget"], 4)
        self.assertIn("memory_request", schedule["salience_gate"]["sources"])
        self.assertTrue(schedule["consolidation_targets"]["targets"])


if __name__ == "__main__":
    unittest.main()
