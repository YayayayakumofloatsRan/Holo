from __future__ import annotations

import unittest

from holo_host.bionic_consciousness_flow import build_bionic_consciousness_flow
from holo_host.bionic_memory_lifecycle import build_bionic_memory_lifecycle
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

    def test_bionic_memory_schedule_replaces_legacy_volatile_memory_blocks(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "identity_core": {"lines": ["identity=yes"]},
                "reply_constraints": {"lines": ["never overclaim vision"], "human_recall_style": "recall naturally"},
                "active_thread_state": {"summary": "current thread is hot"},
                "activation_state": {"heat": 0.8, "motifs": ["rusted_screw"]},
                "selected_memory_ids": ["node-rusted-screw"],
                "episodic_recall": {"lines": ["rusted screw means fear of thread loss"]},
                "recall_reconstruction": {
                    "summary": "the thread symbol was reconstructed",
                    "anchors": ["rusted screw"],
                },
                "vector_hits": [{"text": "vector echo duplicate"}],
            },
            query="do you remember the symbol?",
        )
        packet = {
            "tier": "unit",
            "identity_core": {"lines": ["identity=yes"]},
            "reply_constraints": {"lines": ["never overclaim vision"], "human_recall_style": "recall naturally"},
            "active_thread_state": {"summary": "current thread is hot"},
            "activation_state": {"heat": 0.8, "motifs": ["rusted_screw"], "active_node_ids": ["node-rusted-screw"]},
            "episodic_recall": {"lines": ["rusted screw means fear of thread loss"]},
            "recall_reconstruction": {
                "summary": "the thread symbol was reconstructed",
                "anchors": ["rusted screw"],
            },
            "vector_hits": [{"text": "vector echo duplicate"}],
            "bionic_memory_schedule": schedule,
        }
        context = TurnContext(
            channel="wechat",
            thread_key="cli:bionic-memory",
            chat_name="BionicMemory",
            sender="BionicMemory",
            user_text="what did we keep from last turn?",
            sidecar=packet,
            mind_packet=packet,
            attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
            emotion_state={},
            history=[],
        )

        prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", fast_path=False))

        self.assertIn("Cortical Memory Schema", prompt)
        self.assertIn("Working Memory", prompt)
        self.assertIn("Hippocampal Index", prompt)
        self.assertNotIn("Bionic Memory Dynamic Context:", prompt)
        self.assertEqual(prompt.count("active_summary=current thread is hot"), 1)
        self.assertNotIn("Identity Guard:", prompt)
        self.assertNotIn("Episodic Anchors:", prompt)
        self.assertNotIn("Vector Echoes:", prompt)
        self.assertNotIn("Activation State:", prompt)
        self.assertNotIn("Recall Reconstruction:", prompt)
        self.assertNotIn("Reply Constraints:", prompt)
        self.assertIn("recall naturally", prompt)

    def test_context_schedule_reports_memory_compression_audit(self) -> None:
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

        plan = plan_processor_context(
            prompt="Stable\n\nCurrent User Turn:\nhello",
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
            memory_schedule=schedule,
        )

        self.assertEqual(plan["memory_compression_mode"], "scheduler_owned_dynamic_v1")
        self.assertGreater(plan["memory_dropped_dynamic_lines"], 0)
        self.assertFalse(plan["memory_protected_line_dropped"])
        self.assertEqual(plan["memory_prompt_dynamic_lines"], len(schedule["prompt_dynamic_lines"]))
        self.assertGreater(plan["memory_prompt_dynamic_tokens"], 0)

    def test_bionic_lifecycle_and_flow_render_as_internal_dynamic_surfaces(self) -> None:
        packet = {
            "tier": "unit",
            "identity_core": {"lines": ["identity=yes"]},
            "active_thread_state": {
                "summary": "current thread carries a symbol correction",
                "latest_user_intent": "test biological continuity",
            },
            "affect_state": {"curiosity": 0.7, "continuity_anxiety": 0.6},
            "drive_state": {"seek_continuity": 0.8},
            "activation_state": {"heat": 0.86, "motifs": ["rusted_screw"]},
            "selected_memory_ids": ["node-rusted-screw"],
            "recall_reconstruction": {"summary": "the corrected symbol is rusted screw"},
            "goal_state": {"active_goals": [{"goal_type": "preserve_continuity"}]},
            "selected_action": {"action_type": "reply_once"},
            "consciousness_stream": {
                "thread_summary": "legacy stream summary",
                "lines": ["legacy stream line"],
            },
        }
        packet["bionic_memory_schedule"] = build_bionic_memory_schedule(packet, query="what changed?")
        packet["bionic_memory_lifecycle"] = build_bionic_memory_lifecycle(packet, query="what changed?")
        packet["bionic_consciousness_flow"] = build_bionic_consciousness_flow(packet, query="what changed?")
        context = TurnContext(
            channel="wechat",
            thread_key="cli:bionic-stage51",
            chat_name="BionicStage51",
            sender="BionicStage51",
            user_text="what changed?",
            sidecar=packet,
            mind_packet=packet,
            attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
            emotion_state={},
            history=[],
        )

        prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", fast_path=False))
        plan = plan_processor_context(
            prompt=prompt,
            lane_name="subject_main",
            model="deepseek-v4-pro",
            current_session_id="thread-123",
            history_messages=8,
            memory_schedule=packet["bionic_memory_schedule"],
            memory_lifecycle=packet["bionic_memory_lifecycle"],
            consciousness_flow=packet["bionic_consciousness_flow"],
        )

        self.assertIn("Memory Lifecycle:", prompt)
        self.assertIn("Consciousness Flow:", prompt)
        self.assertIn("self_memory_write=false", prompt)
        self.assertIn("sensory_edge=what changed?", prompt)
        self.assertNotIn("Consciousness Lines:", prompt)
        self.assertEqual(plan["memory_lifecycle_mode"], "biomimetic_lifecycle_v1")
        self.assertEqual(plan["consciousness_flow_mode"], "consciousness_flow_v1")
        self.assertGreater(plan["consciousness_flow_prompt_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
