from __future__ import annotations

import copy
import unittest

from holo_host.bionic_boundary_stress import _compact_processor_debug
from holo_host.bionic_capability_observatory import build_bionic_capability_observatory
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule, fuse_bionic_dynamic_prompt
from holo_host.bionic_simulation_lab import build_bionic_simulation_lab
from holo_host.context_scheduler import plan_processor_context
from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage65BoundedToolObservationTests(unittest.TestCase):
    def test_scheduler_builds_bounded_tool_observation_frame_without_authority(self) -> None:
        schedule = build_bionic_memory_schedule(
            {
                "capability_context": {
                    "tool_requests": [
                        {
                            "name": "external_lookup",
                            "reason": "turn requests external lookup",
                            "payload": {"query": "DeepSeek current model docs"},
                        }
                    ],
                    "tool_context_lines": [
                        "lookup planned: DeepSeek current model docs",
                        "external lookup: DeepSeek docs | title: API reference",
                    ],
                },
            },
            query="look up the current DeepSeek model docs",
        )

        scheduler = schedule["tool_observation_scheduler"]
        dynamic = "\n".join(schedule["prompt_dynamic_lines"])

        self.assertEqual(scheduler["mode"], "stage65_bounded_tool_observation_v1")
        self.assertTrue(scheduler["needed"])
        self.assertEqual(scheduler["requested_tool_count"], 1)
        self.assertEqual(scheduler["context_line_count"], 2)
        self.assertGreaterEqual(scheduler["observation_budget"], 1)
        self.assertIn("external_lookup", scheduler["request_names"])
        self.assertIn("tool_observation=", dynamic)
        self.assertIn("bounded_observation_only=true", dynamic)
        self.assertFalse(scheduler["runtime_decision_authority"])
        self.assertFalse(scheduler["transport_decision_authority"])
        self.assertFalse(scheduler["self_memory_write"])

    def test_prompt_fusion_owns_tool_context_without_duplicate_raw_tool_block(self) -> None:
        capability_context = {
            "tool_requests": [
                {
                    "name": "external_lookup",
                    "reason": "turn requests external lookup",
                    "payload": {"query": "DeepSeek current model docs"},
                }
            ],
            "tool_context_lines": ["lookup planned: DeepSeek current model docs"],
        }
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "capability_context": capability_context,
        }
        schedule = build_bionic_memory_schedule(packet, query="look this up")
        fused = fuse_bionic_dynamic_prompt(schedule, {}, {})
        packet["bionic_memory_schedule"] = fused
        context = TurnContext(
            channel="wechat",
            thread_key="cli:stage65-tool",
            chat_name="Stage65Tool",
            sender="Stage65Tool",
            user_text="look this up",
            sidecar=packet,
            mind_packet=packet,
            attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
            emotion_state={},
            history=[],
            capability_context=capability_context,
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
        self.assertEqual(prompt.count("lookup planned: DeepSeek current model docs"), 1)
        self.assertIn("bounded tool observations are in the bionic dynamic frame", prompt)
        self.assertEqual(plan["tool_observation_scheduler_mode"], "stage65_bounded_tool_observation_v1")
        self.assertTrue(plan["tool_observation_needed"])
        self.assertEqual(plan["tool_observation_requested_tool_count"], 1)
        self.assertFalse(plan["tool_observation_runtime_decision_authority"])

    def test_simulation_rewards_bounded_tool_scheduler_with_higher_tool_coverage(self) -> None:
        baseline_seed = _seed_run("baseline")
        stage65_seed = copy.deepcopy(baseline_seed)
        stage65_seed["run_id"] = "stage65-bounded-tool-observation"
        for turn in stage65_seed["turns"]:
            schedule = turn.setdefault("processor_debug", {}).setdefault("bionic_memory_schedule", {})
            schedule["tool_observation_scheduler_mode"] = "stage65_bounded_tool_observation_v1"
            schedule["tool_observation_needed"] = True
            schedule["tool_observation_budget"] = 2

        baseline = build_bionic_simulation_lab(
            [baseline_seed],
            scenarios=9,
            turns_per_scenario=120,
        )
        improved = build_bionic_simulation_lab(
            [stage65_seed],
            scenarios=9,
            turns_per_scenario=120,
        )
        report = build_bionic_capability_observatory(improved)

        self.assertGreater(
            improved["internal_telemetry"]["tool_observation_coverage"],
            baseline["internal_telemetry"]["tool_observation_coverage"] + 0.3,
        )
        self.assertGreaterEqual(
            report["capability_scorecard"]["dimension_index"]["tool_observation"]["score"],
            0.7,
        )

    def test_compact_debug_preserves_tool_observation_scheduler_evidence(self) -> None:
        compact = _compact_processor_debug(
            {
                "bionic_memory_schedule": {
                    "mode": "biomimetic_v1",
                    "tool_observation_scheduler": {
                        "mode": "stage65_bounded_tool_observation_v1",
                        "needed": True,
                        "requested_tool_count": 2,
                        "observation_budget": 2,
                        "runtime_decision_authority": False,
                        "transport_decision_authority": False,
                    },
                }
            }
        )

        schedule = compact["bionic_memory_schedule"]
        self.assertEqual(schedule["tool_observation_scheduler_mode"], "stage65_bounded_tool_observation_v1")
        self.assertTrue(schedule["tool_observation_needed"])
        self.assertEqual(schedule["tool_observation_requested_tool_count"], 2)
        self.assertEqual(schedule["tool_observation_budget"], 2)
        self.assertFalse(schedule["tool_observation_runtime_decision_authority"])
        self.assertFalse(schedule["tool_observation_transport_decision_authority"])


if __name__ == "__main__":
    unittest.main()
