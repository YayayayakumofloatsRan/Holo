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
        )
        second = runtime.tick(
            mode="full_brain",
            idle_seconds=13.6,
            latest_activity_at="",
            brain_status={"loops": [{"loop_name": "association_stream", "influence_summary": "motif=continuity"}]},
        )
        third = runtime.tick(
            mode="full_brain",
            idle_seconds=14.9,
            latest_activity_at="",
            brain_status={"loops": [{"loop_name": "homeostasis_tick", "blocked_reason": "not_due"}]},
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

        state = runtime.state()
        self.assertEqual(state["sequence"], 3)
        self.assertEqual([item["sequence"] for item in state["recent_ticks"]], [2, 3])
        self.assertEqual(state["latest_tick"]["sequence"], 3)


if __name__ == "__main__":
    unittest.main()
