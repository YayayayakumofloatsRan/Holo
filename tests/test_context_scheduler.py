from __future__ import annotations

import unittest

from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule
from holo_host.context_scheduler import estimate_tokens, plan_processor_context
from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt


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

    def test_rendered_chat_prompt_exposes_stable_provider_cache_prefix(self) -> None:
        def _context(user_text: str) -> TurnContext:
            packet = {"tier": "unit", "identity_core": {"lines": ["identity=yes"]}}
            return TurnContext(
                channel="wechat",
                thread_key="cli:cache-prefix",
                chat_name="CachePrefix",
                sender="CachePrefix",
                user_text=user_text,
                sidecar=packet,
                mind_packet=packet,
                attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
                emotion_state={},
                history=[],
            )

        first_prompt = render_chat_prompt(_context("first user turn"), turn_plan=TurnPlan(route="main", fast_path=False))
        second_prompt = render_chat_prompt(_context("second user turn"), turn_plan=TurnPlan(route="main", fast_path=False))
        first = plan_processor_context(
            prompt=first_prompt,
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
        )
        second = plan_processor_context(
            prompt=second_prompt,
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
        )

        self.assertGreaterEqual(first["provider_cache_prefix_tokens"], 512)
        self.assertEqual(first["provider_cache_prefix_digest"], second["provider_cache_prefix_digest"])
        self.assertNotEqual(first["volatile_context_digest"], second["volatile_context_digest"])

    def test_bionic_memory_schedule_adds_stable_cortical_prefix_and_dynamic_indices(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "identity_core": {"lines": ["identity=yes"]},
                "reply_constraints": {"lines": ["never overclaim vision"]},
                "active_thread_state": {"summary": "active thread carries the rusted screw symbol"},
                "activation_state": {"heat": 0.8, "motifs": ["rusted_screw"]},
                "selected_memory_ids": ["node-rusted-screw"],
                "episodic_recall": {"lines": ["rusted screw means fear of thread loss"]},
            },
            query="first user turn",
        )

        def _context(user_text: str) -> TurnContext:
            packet = {
                "tier": "unit",
                "identity_core": {"lines": ["identity=yes"]},
                "bionic_memory_schedule": schedule,
            }
            return TurnContext(
                channel="wechat",
                thread_key="cli:bionic-memory",
                chat_name="BionicMemory",
                sender="BionicMemory",
                user_text=user_text,
                sidecar=packet,
                mind_packet=packet,
                attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
                emotion_state={},
                history=[],
            )

        first_prompt = render_chat_prompt(_context("first user turn"), turn_plan=TurnPlan(route="main", fast_path=False))
        second_prompt = render_chat_prompt(_context("second user turn"), turn_plan=TurnPlan(route="main", fast_path=False))
        first = plan_processor_context(
            prompt=first_prompt,
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
            memory_schedule=schedule,
        )
        second = plan_processor_context(
            prompt=second_prompt,
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
            memory_schedule=schedule,
        )

        self.assertIn("Cortical Memory Schema", first_prompt)
        self.assertIn("Working Memory", first_prompt)
        self.assertIn("Hippocampal Index", first_prompt)
        self.assertLess(first_prompt.index("Cortical Memory Schema"), first_prompt.index("Current User Turn"))
        self.assertEqual(first["provider_cache_prefix_digest"], second["provider_cache_prefix_digest"])
        self.assertEqual(first["memory_schedule_mode"], "biomimetic_v1")
        self.assertGreater(first["memory_schedule_stable_tokens"], 0)
        self.assertGreater(first["memory_schedule_dynamic_tokens"], 0)
        self.assertGreater(first["memory_dynamic_pressure"], 0.0)


if __name__ == "__main__":
    unittest.main()
