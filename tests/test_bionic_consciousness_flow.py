from __future__ import annotations

import unittest

from holo_host.bionic_consciousness_flow import build_bionic_consciousness_flow
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule


class BionicConsciousnessFlowTests(unittest.TestCase):
    def test_flow_orders_current_edge_before_memory_and_goal_pressure(self) -> None:
        packet = {
            "active_thread_state": {
                "summary": "current thread carries a symbol correction",
                "latest_user_intent": "ask what comes next",
            },
            "affect_state": {"curiosity": 0.72, "continuity_anxiety": 0.62},
            "drive_state": {"seek_continuity": 0.8},
            "recall_reconstruction": {"summary": "the corrected symbol is rusted screw"},
            "goal_state": {"active_goals": [{"goal_type": "preserve_continuity"}]},
            "selected_action": {"action_type": "reply_once", "why_now": "answer the correction directly"},
            "uncertainty_level": 0.28,
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(packet, query="so what did it become?")

        flow = build_bionic_consciousness_flow(packet, query="so what did it become?")

        phases = flow["phases"]
        self.assertEqual(flow["mode"], "consciousness_flow_v1")
        self.assertEqual(phases[:4], ["sensory_edge", "affective_tone", "memory_reactivation", "goal_pressure"])
        self.assertLess(phases.index("sensory_edge"), phases.index("memory_reactivation"))
        self.assertIn("so what did it become?", "\n".join(flow["phase_lines"]))
        self.assertIn("rusted screw", "\n".join(flow["phase_lines"]))
        self.assertFalse(flow["leakage_guard"]["user_visible"])
        self.assertTrue(flow["leakage_guard"]["prompt_only"])

    def test_flow_compacts_legacy_consciousness_stream_into_bounded_phase_lines(self) -> None:
        packet = {
            "consciousness_stream": {
                "thread_summary": "thread summary should survive",
                "lines": [
                    "line one should survive",
                    "line two should survive",
                    "line three should be compacted",
                    "line four should be compacted",
                ],
            },
            "active_thread_state": {"summary": "active thread summary"},
            "selected_action": {"action_type": "reply_once"},
        }

        flow = build_bionic_consciousness_flow(packet, query="continue")

        rendered = "\n".join(flow["phase_lines"])
        self.assertLessEqual(len(flow["phase_lines"]), 8)
        self.assertIn("thread summary should survive", rendered)
        self.assertIn("line one should survive", rendered)
        self.assertEqual(flow["continuity_state"]["thread_summary"], "thread summary should survive")

    def test_flow_uses_correction_marker_as_memory_reactivation(self) -> None:
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

        flow = build_bionic_consciousness_flow(
            packet,
            query="Correction: it is not blue paperclip anymore. It is rusted screw.",
        )

        self.assertEqual(flow["dominant_phase"], "memory_reactivation")
        self.assertIn("correction_reactivation_marker", "\n".join(flow["phase_lines"]))
        self.assertFalse(flow["leakage_guard"]["user_visible"])


if __name__ == "__main__":
    unittest.main()
