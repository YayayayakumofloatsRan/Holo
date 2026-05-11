from __future__ import annotations

import unittest

from holo_host.context_scheduler import estimate_tokens, plan_processor_context


class ContextSchedulerTests(unittest.TestCase):
    def test_flash_budget_starts_new_session_near_context_limit(self) -> None:
        prompt = "x" * 27_000

        plan = plan_processor_context(
            prompt=prompt,
            lane_name="micro_fast",
            model="deepseek-v4-flash",
            current_session_id="old-session",
            history_messages=8,
        )

        self.assertEqual(plan["context_window_class"], "8k")
        self.assertTrue(plan["start_new_session"])
        self.assertEqual(plan["effective_session_id"], "")
        self.assertLessEqual(plan["max_history_messages"], 2)
        self.assertEqual(plan["reason"], "context_pressure")

    def test_cjk_prompt_pressure_is_not_underestimated_as_ascii(self) -> None:
        prompt = "\u4f60" * 6_000

        plan = plan_processor_context(
            prompt=prompt,
            lane_name="micro_fast",
            model="deepseek-v4-flash",
            current_session_id="old-session",
            history_messages=8,
        )

        self.assertEqual(estimate_tokens(prompt), 6_000)
        self.assertTrue(plan["start_new_session"])
        self.assertLessEqual(plan["max_history_messages"], 2)

    def test_subject_main_preserves_session_and_splits_stable_from_volatile_context(self) -> None:
        stable = "Identity Guard:\n- keep boundaries\n\nVisual Memory:\n- none\n\n"
        first = plan_processor_context(
            prompt=stable + "Current User Turn:\nhello",
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
        )
        second = plan_processor_context(
            prompt=stable + "Current User Turn:\nnew message",
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
        )

        self.assertEqual(first["context_window_class"], "128k")
        self.assertFalse(first["start_new_session"])
        self.assertEqual(first["effective_session_id"], "thread-123")
        self.assertEqual(first["stable_context_digest"], second["stable_context_digest"])
        self.assertNotEqual(first["volatile_context_digest"], second["volatile_context_digest"])


if __name__ == "__main__":
    unittest.main()
