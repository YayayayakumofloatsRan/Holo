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
        self.assertEqual(third["field_state"]["dominant_attractor"], "homeostasis")
        self.assertGreater(third["field_state"]["activation_energy"], 0.0)
        self.assertGreater(third["field_state"]["prediction_error"], 0.0)
        self.assertIn("hold the line without acting", third["plasticity_trace"]["recent_micro_thoughts"])

        state = runtime.state()
        self.assertEqual(state["sequence"], 3)
        self.assertEqual([item["sequence"] for item in state["recent_ticks"]], [2, 3])
        self.assertEqual(state["latest_tick"]["sequence"], 3)
        self.assertEqual(state["field_state"]["dominant_attractor"], "homeostasis")
        self.assertEqual(state["plasticity_trace"]["recent_micro_thoughts"][-1], "hold the line without acting")

    def test_recurrent_field_carries_prior_micro_thought_into_next_tick(self) -> None:
        runtime = InnerStreamRuntime(max_ticks=4)

        first = runtime.tick(
            mode="full_brain",
            idle_seconds=2.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"first internal edge","attention_focus":"symbolic edge","memory_echo":"blue thread","goal_pressure":"continuity","inhibition_gate":"wait","candidate_action":"observe","prediction_error":0.62,"salience_delta":0.34,"affective_tension":0.41}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "subject_main"},
            },
        )
        second = runtime.tick(
            mode="full_brain",
            idle_seconds=3.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"second internal edge","attention_focus":"symbolic edge","memory_echo":"blue thread returns","goal_pressure":"continuity","inhibition_gate":"wait","candidate_action":"observe","prediction_error":0.24,"salience_delta":0.18,"affective_tension":0.2}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "subject_main"},
            },
        )

        self.assertEqual(first["field_state"]["dominant_attractor"], "symbolic edge")
        self.assertEqual(second["recurrent_context"]["previous_micro_thought"], "first internal edge")
        self.assertIn("first internal edge", second["plasticity_trace"]["recent_micro_thoughts"])
        self.assertEqual(second["field_state"]["dominant_attractor"], "symbolic edge")
        self.assertGreater(second["field_state"]["activation_energy"], first["field_state"]["activation_energy"])

    def test_neuromodulators_neural_field_and_synaptic_trace_are_updated(self) -> None:
        runtime = InnerStreamRuntime(max_ticks=4)

        tick = runtime.tick(
            mode="full_brain",
            idle_seconds=4.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"novel conflict forms","attention_focus":"novel conflict","memory_echo":"edge A","goal_pressure":"resolve","inhibition_gate":"hold","candidate_action":"observe","prediction_error":0.75,"salience_delta":0.55,"affective_tension":0.66}',
                "metadata": {"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "subject_main"},
            },
        )

        neuromodulators = tick["field_state"]["neuromodulators"]
        neural_field = tick["field_state"]["neural_field"]
        synaptic_trace = tick["plasticity_trace"]["synaptic_trace"]

        self.assertGreater(neuromodulators["dopamine"], 0.2)
        self.assertGreater(neuromodulators["norepinephrine"], 0.1)
        self.assertGreater(neuromodulators["acetylcholine"], 0.1)
        self.assertLess(neuromodulators["serotonin"], 0.5)
        self.assertGreater(neural_field["excitatory_tone"], 0.0)
        self.assertGreater(neural_field["inhibitory_tone"], 0.0)
        self.assertIn("e_i_balance", neural_field)
        self.assertGreater(neural_field["global_workspace_ignition"], 0.0)
        self.assertEqual(synaptic_trace["potentiated_attractor"], "novel conflict")
        self.assertGreater(synaptic_trace["ltp"], 0.0)
        self.assertEqual(synaptic_trace["attractor_transition"], "baseline -> novel conflict")

    def test_homeostatic_inhibition_rises_under_repeated_high_energy_ticks(self) -> None:
        runtime = InnerStreamRuntime(max_ticks=6)

        first = runtime.tick(
            mode="full_brain",
            idle_seconds=2.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"pressure one","attention_focus":"sustained pressure","memory_echo":"edge","goal_pressure":"resolve","inhibition_gate":"hold","candidate_action":"observe","prediction_error":0.88,"salience_delta":0.72,"affective_tension":0.8}',
            },
        )
        runtime.tick(
            mode="full_brain",
            idle_seconds=3.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"pressure two","attention_focus":"sustained pressure","memory_echo":"edge","goal_pressure":"resolve","inhibition_gate":"hold","candidate_action":"observe","prediction_error":0.82,"salience_delta":0.68,"affective_tension":0.76}',
            },
        )
        third = runtime.tick(
            mode="full_brain",
            idle_seconds=4.0,
            latest_activity_at="2026-05-14T10:00:00Z",
            brain_status={"loops": []},
            processor_result={
                "status": "ok",
                "text": '{"micro_thought":"pressure three","attention_focus":"sustained pressure","memory_echo":"edge","goal_pressure":"resolve","inhibition_gate":"hold","candidate_action":"observe","prediction_error":0.78,"salience_delta":0.61,"affective_tension":0.72}',
            },
        )

        first_neural = first["field_state"]["neural_field"]
        third_neural = third["field_state"]["neural_field"]
        third_synaptic = third["plasticity_trace"]["synaptic_trace"]

        self.assertGreater(third_neural["inhibitory_tone"], first_neural["inhibitory_tone"])
        self.assertGreater(third_neural["thalamic_gain"], first_neural["thalamic_gain"])
        self.assertEqual(third_synaptic["homeostatic_response"], "increase_inhibition")
        self.assertGreater(third_synaptic["ltd"], 0.0)


if __name__ == "__main__":
    unittest.main()
