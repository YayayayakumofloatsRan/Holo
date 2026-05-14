from __future__ import annotations

import unittest

from holo_host.inner_stream import INNER_STREAM_PHASES, InnerStreamRuntime


class Stage69InnerStreamTests(unittest.TestCase):
    def test_tick_advances_without_external_input_and_stays_volatile(self) -> None:
        runtime = InnerStreamRuntime(max_ticks=2)

        first = runtime.tick(
            mode="full_brain",
            idle_seconds=12.4,
            latest_activity_at="",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"baseline thought","attention_focus":"baseline","memory_echo":"none","goal_pressure":"continuity","inhibition_gate":"volatile_only","candidate_action":"continue"}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-flash"},
            },
        )
        second = runtime.tick(
            mode="full_brain",
            idle_seconds=13.6,
            latest_activity_at="",
            brain_status={"loops": [{"loop_name": "association_stream", "influence_summary": "motif=continuity"}]},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"continuity remains active","attention_focus":"association","memory_echo":"motif=continuity","goal_pressure":"preserve_continuity","inhibition_gate":"volatile_only","candidate_action":"continue_inner_flow"}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-flash"},
            },
        )
        third = runtime.tick(
            mode="full_brain",
            idle_seconds=14.9,
            latest_activity_at="",
            brain_status={"loops": [{"loop_name": "homeostasis_tick", "blocked_reason": "not_due"}]},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"hold the line without acting","attention_focus":"homeostasis","memory_echo":"not_due","goal_pressure":"maintain continuity","inhibition_gate":"volatile_only:no_transport","candidate_action":"wait"}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-flash"},
            },
        )

        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(third["sequence"], 3)
        self.assertEqual(third["phase_order"], list(INNER_STREAM_PHASES))
        self.assertEqual(third["status"], "flowing")
        self.assertEqual(third["authority"]["memory_write"], "volatile_ring_only")
        self.assertFalse(third["authority"]["self_memory_write"])
        self.assertFalse(third["authority"]["policy_write"])
        self.assertFalse(third["authority"]["transport_write"])
        self.assertIn("no external activity recorded", third["sensory_edge"])
        self.assertEqual(third["affective_tension"], 0.08)
        self.assertTrue(third["processor_invoked"])
        self.assertEqual(third["micro_thought"], "hold the line without acting")
        self.assertEqual(third["processor"]["provider"], "deepseek")

        state = runtime.state()
        self.assertEqual(state["sequence"], 3)
        self.assertEqual([item["sequence"] for item in state["recent_ticks"]], [2, 3])
        self.assertEqual(state["latest_tick"]["sequence"], 3)


if __name__ == "__main__":
    unittest.main()
