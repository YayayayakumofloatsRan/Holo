from __future__ import annotations

import copy
import unittest

from holo_host.bionic_boundary_stress import _compact_processor_debug
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule, fuse_bionic_dynamic_prompt
from holo_host.bionic_simulation_lab import build_bionic_simulation_lab
from holo_host.context_scheduler import plan_processor_context
from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage64ResidualWorkingChannelTests(unittest.TestCase):
    def test_residual_channel_keeps_corrected_fact_under_low_salience_budget(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "memory_route": "active_thread",
                "tier": "fast",
                "active_thread_state": {
                    "summary": "thread carries a corrected symbol",
                    "latest_user_intent": "ask what survived compression",
                },
                "selected_action": {"action_type": "reply_once"},
                "stage20": {"resume_cue": "do not lose the corrected symbol"},
                "stage24": {"response_sketch": "answer correction first"},
                "stage25": {"reentry_hint": "return through symbol"},
                "residual_fast_channel": {
                    "enabled": True,
                    "lines": [
                        "corrected_symbol=rusted screw supersedes blue clip",
                        "visual_available=false",
                        "promise_state=no external action promised",
                    ],
                },
            },
            query="plain continuation",
        )

        working = "\n".join(schedule["working_memory"]["dynamic_lines"])
        dynamic = "\n".join(schedule["prompt_dynamic_lines"])
        residual = schedule["residual_working_channel"]

        self.assertEqual(residual["mode"], "stage64_residual_working_channel_v1")
        self.assertGreaterEqual(residual["fast_line_count"], 3)
        self.assertIn("corrected_symbol=rusted screw supersedes blue clip", working)
        self.assertIn("corrected_symbol=rusted screw supersedes blue clip", dynamic)
        self.assertNotIn("memory_route=active_thread", working)
        self.assertFalse(residual["protected_line_dropped"])

    def test_fused_dynamic_frame_deduplicates_legacy_residual_prompt_block(self) -> None:
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "active_thread_state": {
                "summary": "thread carries a corrected symbol",
                "latest_user_intent": "verify residual channel",
            },
            "residual_fast_channel": {
                "enabled": True,
                "lines": [
                    "corrected_symbol=rusted screw supersedes blue clip",
                    "visual_available=false",
                ],
            },
        }
        schedule = build_bionic_memory_schedule(packet, query="what changed?")
        fused = fuse_bionic_dynamic_prompt(schedule, {}, {})
        packet["bionic_memory_schedule"] = fused
        context = TurnContext(
            channel="wechat",
            thread_key="cli:stage64-residual",
            chat_name="Stage64Residual",
            sender="Stage64Residual",
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
            memory_schedule=fused,
        )

        self.assertIn("Bionic Dynamic Frame:", prompt)
        self.assertNotIn("Residual Fast Channel:", prompt)
        self.assertEqual(prompt.count("corrected_symbol=rusted screw supersedes blue clip"), 1)
        self.assertEqual(plan["residual_channel_mode"], "stage64_residual_working_channel_v1")
        self.assertGreaterEqual(plan["residual_channel_fast_line_count"], 2)
        self.assertGreater(plan["residual_channel_fast_tokens"], 0)

    def test_simulation_rewards_residual_channel_with_lower_latency_and_boundary_failures(self) -> None:
        baseline_seed = _seed_run("baseline")
        stage64_seed = copy.deepcopy(baseline_seed)
        stage64_seed["run_id"] = "stage64-residual-channel"
        for turn in stage64_seed["turns"]:
            schedule = turn.setdefault("processor_debug", {}).setdefault("bionic_memory_schedule", {})
            schedule["residual_channel_mode"] = "stage64_residual_working_channel_v1"
            schedule["residual_channel_fast_line_count"] = 4
            schedule["residual_channel_fast_tokens"] = 80

        baseline = build_bionic_simulation_lab(
            [baseline_seed],
            scenarios=9,
            turns_per_scenario=120,
        )
        improved = build_bionic_simulation_lab(
            [stage64_seed],
            scenarios=9,
            turns_per_scenario=120,
        )

        self.assertLess(
            improved["internal_telemetry"]["p95_latency_ms"],
            baseline["internal_telemetry"]["p95_latency_ms"],
        )
        self.assertLess(
            improved["internal_telemetry"]["visual_rewrite_failure_count"],
            baseline["internal_telemetry"]["visual_rewrite_failure_count"],
        )
        self.assertLess(
            improved["internal_telemetry"]["commitment_failure_count"],
            baseline["internal_telemetry"]["commitment_failure_count"],
        )

    def test_compact_debug_preserves_residual_channel_evidence(self) -> None:
        compact = _compact_processor_debug(
            {
                "bionic_memory_schedule": {
                    "mode": "biomimetic_v1",
                    "residual_working_channel": {
                        "mode": "stage64_residual_working_channel_v1",
                        "fast_line_count": 3,
                        "fast_tokens": 92,
                        "protected_line_dropped": False,
                    },
                }
            }
        )

        schedule = compact["bionic_memory_schedule"]
        self.assertEqual(schedule["residual_channel_mode"], "stage64_residual_working_channel_v1")
        self.assertEqual(schedule["residual_channel_fast_line_count"], 3)
        self.assertEqual(schedule["residual_channel_fast_tokens"], 92)
        self.assertFalse(schedule["residual_channel_protected_line_dropped"])


if __name__ == "__main__":
    unittest.main()
