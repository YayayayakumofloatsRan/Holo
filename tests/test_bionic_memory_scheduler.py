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

    def test_scheduler_drops_empty_slots_from_prompt_surfaces(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "identity_core": {"lines": ["identity=yes"]},
                "reply_constraints": {"lines": ["never overclaim vision"]},
                "active_thread_state": {"summary": "current thread is hot"},
            },
            query="plain continuation",
        )

        rendered = "\n".join(
            [
                *schedule["cortical_schema"]["stable_prefix_lines"],
                *schedule["working_memory"]["dynamic_lines"],
                *schedule["dynamic_context_lines"],
            ]
        )

        self.assertIn("current thread is hot", rendered)
        self.assertNotIn("memory_route=", rendered)
        self.assertNotIn("tier=", rendered)
        self.assertNotIn("latest_user_intent=", rendered)
        self.assertNotIn("activation_heat=0.0", rendered)
        self.assertNotIn("current_chapter=", rendered)
        self.assertNotIn("identity_arc=", rendered)

    def test_scheduler_preserves_voice_guard_when_identity_lines_are_absent(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "voice_guard": ["voice must stay concise and familiar"],
                "reply_constraints": {"lines": ["never overclaim vision"]},
            },
            query="plain continuation",
        )

        rendered = "\n".join(schedule["cortical_schema"]["stable_prefix_lines"])

        self.assertIn("voice must stay concise and familiar", rendered)
        self.assertIn("never overclaim vision", rendered)

    def test_hippocampal_budget_prioritizes_reconstruction_over_generic_activation(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "activation_state": {"heat": 0.9, "motifs": ["old_blue_clip", "rusted_screw"]},
                "selected_memory_ids": ["node-blue-clip", "node-rusted-screw"],
                "episodic_recall": {"lines": ["blue clip was replaced by rusted screw"]},
                "recall_reconstruction": {
                    "summary": "final symbol is rusted screw, not blue clip",
                    "anchors": ["rusted screw means fear of thread loss"],
                },
                "affect_state": {"continuity_anxiety": 0.8},
                "drive_state": {"seek_continuity": 0.9},
            },
            query="刚才那个符号最后改成什么了？",
        )

        lines = schedule["hippocampal_index"]["dynamic_lines"]
        rendered = "\n".join(lines)

        self.assertGreaterEqual(schedule["salience_gate"]["recall_budget"], 4)
        self.assertIn("reconstruction_summary=final symbol is rusted screw, not blue clip", rendered)
        self.assertIn("anchor=rusted screw means fear of thread loss", rendered)
        self.assertLess(
            lines.index("reconstruction_summary=final symbol is rusted screw, not blue clip"),
            lines.index("motif=old_blue_clip"),
        )

    def test_working_memory_budget_prioritizes_state_over_route_metadata(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "memory_route": "active_thread",
                "tier": "fast",
                "active_thread_state": {
                    "summary": "current thread carries the corrected symbol",
                    "latest_user_intent": "ask what survived compression",
                },
                "selected_action": {"action_type": "reply_once"},
                "stage20": {"resume_cue": "do not lose the corrected symbol"},
                "stage24": {"response_sketch": "answer the correction first"},
                "stage25": {"reentry_hint": "return through current symbol"},
            },
            query="plain continuation",
        )

        lines = schedule["working_memory"]["dynamic_lines"]
        rendered = "\n".join(lines)

        self.assertEqual(len(lines), 4)
        self.assertIn("active_summary=current thread carries the corrected symbol", rendered)
        self.assertIn("latest_user_intent=ask what survived compression", rendered)
        self.assertIn("selected_action=reply_once", rendered)
        self.assertIn("temporal_resume_cue=do not lose the corrected symbol", rendered)
        self.assertNotIn("memory_route=active_thread", rendered)
        self.assertNotIn("tier=fast", rendered)

    def test_scheduler_exposes_dynamic_compression_audit(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
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
            },
            query="plain continuation",
        )

        audit = schedule["dynamic_compression_audit"]

        self.assertEqual(audit["mode"], "scheduler_owned_dynamic_v1")
        self.assertGreater(audit["raw_dynamic_line_count"], audit["prompt_dynamic_line_count"])
        self.assertGreater(audit["dropped_dynamic_line_count"], 0)
        self.assertFalse(audit["protected_line_dropped"])
        self.assertIn("reconstruction_summary", audit["protected_labels"])
        self.assertEqual(audit["prompt_dynamic_line_count"], len(schedule["prompt_dynamic_lines"]))


if __name__ == "__main__":
    unittest.main()
