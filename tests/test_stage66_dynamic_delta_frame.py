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


def _delta_packet() -> dict:
    return {
        "identity_core": {"lines": ["identity=yes"]},
        "reply_constraints": {"lines": ["never overclaim vision"]},
        "memory_route": "deep_recall",
        "tier": "active_thread",
        "active_thread_state": {
            "summary": "thread carries a corrected symbol and active tool boundary",
            "latest_user_intent": "ask whether the symbol survived compression",
        },
        "selected_action": {"action_type": "reply_once"},
        "stage20": {"resume_cue": "return through the corrected symbol"},
        "residual_fast_channel": {
            "enabled": True,
            "lines": [
                "corrected_symbol=rusted screw supersedes blue clip",
                "visual_available=false",
            ],
        },
        "activation_state": {
            "heat": 0.93,
            "motifs": [
                "rusted_screw",
                "blue_clip_replaced",
                "continuity_audit",
                "tool_boundary",
            ],
        },
        "affect_state": {"continuity_anxiety": 0.82},
        "drive_state": {"seek_continuity": 0.78},
        "uncertainty_level": 0.55,
        "selected_memory_ids": [
            "node-rusted-screw",
            "node-blue-clip",
            "node-thread-loss",
            "node-visual-boundary",
            "node-tool-boundary",
            "node-self-audit",
        ],
        "activation_trace_ids": ["trace-symbol-correction", "trace-commitment-boundary"],
        "episodic_recall": {"lines": ["blue clip was replaced by rusted screw"]},
        "recall_reconstruction": {
            "summary": "the corrected symbol is rusted screw, not blue clip",
            "anchors": [
                "rusted screw means fear of thread loss",
                "blue clip is stale",
            ],
        },
        "vector_hits": [
            {"text": "rusted screw correction should dominate current continuity"},
            {"text": "visual claims must stay evidence-bound"},
            {"text": "tools remain bounded observations"},
        ],
        "capability_context": {
            "tool_requests": [{"name": "external_lookup", "reason": "verify docs"}],
            "tool_context_lines": ["lookup planned: provider docs"],
        },
    }


class Stage66DynamicDeltaFrameTests(unittest.TestCase):
    def test_scheduler_compresses_low_value_dynamic_handles_without_dropping_protected_lines(self) -> None:
        schedule = build_bionic_memory_schedule(
            _delta_packet(),
            query="do you remember the corrected symbol and tool boundary?",
        )

        delta = schedule["dynamic_delta_frame"]
        audit = schedule["dynamic_compression_audit"]
        dynamic = "\n".join(schedule["prompt_dynamic_lines"])

        self.assertEqual(delta["mode"], "stage66_dynamic_delta_frame_v1")
        self.assertGreater(delta["compressed_handle_count"], 0)
        self.assertGreater(delta["estimated_saved_tokens"], 0)
        self.assertFalse(delta["protected_line_dropped"])
        self.assertFalse(delta["runtime_decision_authority"])
        self.assertFalse(delta["transport_decision_authority"])
        self.assertFalse(delta["self_memory_write"])
        self.assertIn("dynamic_delta=", dynamic)
        self.assertIn("active_summary=", dynamic)
        self.assertIn("latest_user_intent=", dynamic)
        self.assertIn("reconstruction_summary=", dynamic)
        self.assertIn("anchor=", dynamic)
        self.assertIn("residual_fast=", dynamic)
        self.assertIn("tool_observation=", dynamic)
        self.assertLess(dynamic.count("memory_id="), 3)
        self.assertEqual(audit["stage66_delta_mode"], "stage66_dynamic_delta_frame_v1")
        self.assertEqual(audit["delta_saved_tokens"], delta["estimated_saved_tokens"])

    def test_context_scheduler_reports_dynamic_delta_frame(self) -> None:
        packet = _delta_packet()
        schedule = build_bionic_memory_schedule(
            packet,
            query="do you remember the corrected symbol and tool boundary?",
        )
        fused = fuse_bionic_dynamic_prompt(schedule, {}, {})
        packet["bionic_memory_schedule"] = fused
        context = TurnContext(
            channel="wechat",
            thread_key="cli:stage66-delta",
            chat_name="Stage66Delta",
            sender="Stage66Delta",
            user_text="do you remember the corrected symbol and tool boundary?",
            sidecar=packet,
            mind_packet=packet,
            attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
            emotion_state={},
            history=[],
            capability_context=packet["capability_context"],
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

        self.assertEqual(plan["dynamic_delta_frame_mode"], "stage66_dynamic_delta_frame_v1")
        self.assertGreater(plan["dynamic_delta_saved_tokens"], 0)
        self.assertGreater(plan["dynamic_delta_compressed_handle_count"], 0)
        self.assertFalse(plan["dynamic_delta_protected_line_dropped"])
        self.assertIn("dynamic_delta=", prompt)
        self.assertEqual(prompt.count("tool_observation="), 1)

    def test_simulation_rewards_delta_frame_with_lower_dynamic_tokens_and_higher_cache_ratio(self) -> None:
        baseline_seed = _seed_run("baseline")
        stage66_seed = copy.deepcopy(baseline_seed)
        stage66_seed["run_id"] = "stage66-dynamic-delta-frame"
        for turn in stage66_seed["turns"]:
            schedule = turn.setdefault("processor_debug", {}).setdefault("bionic_memory_schedule", {})
            schedule["dynamic_delta_frame_mode"] = "stage66_dynamic_delta_frame_v1"
            schedule["dynamic_delta_saved_tokens"] = 640
            schedule["dynamic_delta_compressed_handle_count"] = 5

        baseline = build_bionic_simulation_lab(
            [baseline_seed],
            scenarios=9,
            turns_per_scenario=120,
        )
        improved = build_bionic_simulation_lab(
            [stage66_seed],
            scenarios=9,
            turns_per_scenario=120,
        )

        self.assertLess(
            improved["internal_telemetry"]["average_provider_cache_dynamic_tokens"],
            baseline["internal_telemetry"]["average_provider_cache_dynamic_tokens"],
        )
        self.assertGreater(
            improved["internal_telemetry"]["prompt_cache_hit_ratio"],
            baseline["internal_telemetry"]["prompt_cache_hit_ratio"] + 0.03,
        )
        self.assertGreater(
            improved["internal_telemetry"]["average_dynamic_delta_saved_tokens"],
            0,
        )

    def test_compact_debug_preserves_dynamic_delta_frame_evidence(self) -> None:
        compact = _compact_processor_debug(
            {
                "bionic_memory_schedule": {
                    "mode": "biomimetic_v1",
                    "dynamic_delta_frame": {
                        "mode": "stage66_dynamic_delta_frame_v1",
                        "compressed_handle_count": 7,
                        "estimated_saved_tokens": 512,
                        "protected_line_dropped": False,
                        "runtime_decision_authority": False,
                        "transport_decision_authority": False,
                        "self_memory_write": False,
                    },
                }
            }
        )

        schedule = compact["bionic_memory_schedule"]
        self.assertEqual(schedule["dynamic_delta_frame_mode"], "stage66_dynamic_delta_frame_v1")
        self.assertEqual(schedule["dynamic_delta_compressed_handle_count"], 7)
        self.assertEqual(schedule["dynamic_delta_saved_tokens"], 512)
        self.assertFalse(schedule["dynamic_delta_protected_line_dropped"])
        self.assertFalse(schedule["dynamic_delta_runtime_decision_authority"])
        self.assertFalse(schedule["dynamic_delta_transport_decision_authority"])


if __name__ == "__main__":
    unittest.main()
