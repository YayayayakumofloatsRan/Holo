from __future__ import annotations

import copy
import unittest

from holo_host.bionic_boundary_stress import _compact_processor_debug
from holo_host.bionic_memory_scheduler import build_bionic_memory_schedule
from holo_host.bionic_simulation_lab import build_bionic_simulation_lab
from holo_host.context_scheduler import plan_processor_context
from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage63CacheInheritanceSpineTests(unittest.TestCase):
    def test_scheduler_builds_stable_cache_spine_before_dynamic_turn_fields(self) -> None:
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "voice_guard": ["stay natural and terse"],
            "reply_constraints": {
                "lines": ["never overclaim vision", "bind commitments before promising"],
                "human_recall_style": "recall like a person, not a log dump",
            },
            "autobiographical_state": {
                "current_chapter": "building Holo as a bionic subject runtime",
                "identity_arc": "continuous but bounded subject loop",
                "stable_traits": ["grounded", "warm", "skeptical of overclaim"],
            },
            "goal_state": {
                "active_goals": [
                    {"goal_type": "preserve_continuity"},
                    {"goal_type": "reduce_latency_without_capability_loss"},
                ]
            },
            "active_thread_state": {
                "summary": "current thread is testing cache inheritance",
                "latest_user_intent": "continue Stage63",
            },
            "activation_state": {"heat": 0.8, "motifs": ["cache", "continuity"]},
            "selected_memory_ids": ["node-cache"],
            "recall_reconstruction": {"summary": "Stage62 ranked cache inheritance first"},
        }
        schedule = build_bionic_memory_schedule(packet, query="continue improving cache inheritance")
        packet["bionic_memory_schedule"] = schedule

        first_prompt = render_chat_prompt(
            self._context(packet, "first cache pressure turn"),
            turn_plan=TurnPlan(route="main", fast_path=False),
        )
        second_prompt = render_chat_prompt(
            self._context(packet, "second cache pressure turn"),
            turn_plan=TurnPlan(route="main", fast_path=False),
        )
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

        self.assertEqual(schedule["cache_inheritance"]["mode"], "stage63_cortical_cache_spine_v1")
        self.assertGreaterEqual(schedule["cache_inheritance"]["cache_spine_line_count"], 6)
        self.assertIn("cache_spine", "\n".join(schedule["provider_prefix_lines"]))
        self.assertLess(first_prompt.index("Cortical Memory Schema:"), first_prompt.index("Current User Turn:"))
        self.assertEqual(first["provider_cache_prefix_digest"], second["provider_cache_prefix_digest"])
        self.assertNotEqual(first["volatile_context_digest"], second["volatile_context_digest"])
        self.assertEqual(first["cache_inheritance_mode"], "stage63_cortical_cache_spine_v1")
        self.assertGreaterEqual(first["cache_inheritance_prefix_share"], 0.25)
        self.assertFalse(schedule["consolidation_targets"]["self_memory_write"])

    def test_stage61_simulation_rewards_larger_stable_prefix_without_changing_seed_scores(self) -> None:
        baseline_seed = _seed_run("baseline")
        stage63_seed = copy.deepcopy(baseline_seed)
        stage63_seed["run_id"] = "stage63-cache-spine"
        for turn in stage63_seed["turns"]:
            debug = turn.setdefault("processor_debug", {})
            partition = debug.setdefault("prompt_partition", {})
            partition["provider_cache_prefix_tokens"] = 1850
            partition["provider_cache_dynamic_tokens"] = 760
            debug.setdefault("bionic_memory_schedule", {})["cache_inheritance_mode"] = (
                "stage63_cortical_cache_spine_v1"
            )

        baseline = build_bionic_simulation_lab(
            [baseline_seed],
            scenarios=4,
            turns_per_scenario=72,
        )
        improved = build_bionic_simulation_lab(
            [stage63_seed],
            scenarios=4,
            turns_per_scenario=72,
        )

        self.assertEqual(
            baseline["generated_runs"][0]["overall_score"],
            improved["generated_runs"][0]["overall_score"],
        )
        self.assertGreater(
            improved["internal_telemetry"]["prompt_cache_hit_ratio"],
            baseline["internal_telemetry"]["prompt_cache_hit_ratio"] + 0.04,
        )
        self.assertGreater(
            improved["internal_telemetry"]["average_provider_cache_prefix_tokens"],
            baseline["internal_telemetry"]["average_provider_cache_prefix_tokens"],
        )

    def test_cache_spine_excludes_salience_specific_values_from_stable_prefix(self) -> None:
        packet = {
            "identity_core": {"lines": ["identity=yes"]},
            "reply_constraints": {"lines": ["never overclaim vision"]},
            "active_thread_state": {"summary": "same stable thread"},
            "activation_state": {"heat": 0.9, "motifs": ["cache"]},
            "recall_reconstruction": {"summary": "same recalled anchor"},
        }

        plain = build_bionic_memory_schedule(packet, query="continue")
        memory_pressure = build_bionic_memory_schedule(packet, query="do you remember earlier?")

        self.assertNotEqual(plain["salience_gate"]["recall_budget"], memory_pressure["salience_gate"]["recall_budget"])
        self.assertEqual(plain["provider_prefix_lines"], memory_pressure["provider_prefix_lines"])
        self.assertNotIn("recall_budget", "\n".join(plain["provider_prefix_lines"]))

    def test_compact_debug_preserves_cache_inheritance_spine_evidence(self) -> None:
        compact = _compact_processor_debug(
            {
                "bionic_memory_schedule": {
                    "mode": "biomimetic_v1",
                    "provider_prefix_lines": ["identity=yes"],
                    "dynamic_context_lines": ["working: active_summary=hot"],
                    "cache_inheritance": {
                        "mode": "stage63_cortical_cache_spine_v1",
                        "cache_spine_line_count": 8,
                        "estimated_stable_prefix_tokens": 1280,
                        "estimated_dynamic_tokens": 820,
                        "prefix_share": 0.61,
                    },
                }
            }
        )

        schedule = compact["bionic_memory_schedule"]
        self.assertEqual(schedule["cache_inheritance_mode"], "stage63_cortical_cache_spine_v1")
        self.assertEqual(schedule["cache_spine_line_count"], 8)
        self.assertEqual(schedule["cache_inheritance_prefix_share"], 0.61)

    @staticmethod
    def _context(packet: dict, user_text: str) -> TurnContext:
        return TurnContext(
            channel="wechat",
            thread_key="cli:stage63-cache",
            chat_name="Stage63Cache",
            sender="Stage63Cache",
            user_text=user_text,
            sidecar=packet,
            mind_packet=packet,
            attention_state=AttentionState(primary_focus="reply", reply_goal="answer"),
            emotion_state={},
            history=[],
        )


if __name__ == "__main__":
    unittest.main()
