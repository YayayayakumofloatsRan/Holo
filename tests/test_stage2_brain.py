from __future__ import annotations

import unittest

import holo_memory_library.rag_memory as rm
from holo_host.brain_ops import effective_initiative_cooldown_hours, filter_self_revision_patch
from holo_host.cli import _evaluate_stage2_acceptance
from holo_host.mind_graph import MindGraph
from tests.test_rag_memory import TempMemoryRepo


class Stage2BrainTests(unittest.TestCase):
    def test_evaluate_stage2_acceptance_passes_core_checks(self) -> None:
        report = _evaluate_stage2_acceptance(
            transport="live_http",
            health={"status": "ok"},
            brain_status={
                "mode": "companion",
                "loops": [
                    {"loop_name": "heartbeat"},
                    {"loop_name": "attention_tick"},
                    {"loop_name": "maintenance_stream"},
                    {"loop_name": "association_stream"},
                    {"loop_name": "social_stream"},
                    {"loop_name": "deep_dream_cycle"},
                ],
                "cache": {"hit_ratio": 0.42},
            },
            mode_transitions=[
                {"mode": "silent", "status": "ok"},
                {"mode": "companion", "status": "ok"},
                {"mode": "dream_only", "status": "ok"},
                {"mode": "full_brain", "status": "ok"},
            ],
            persona_probes={
                "playful": {
                    "persona_blend": {"playfulness": 0.7, "slyness": 0.66},
                    "reply_plan": {"text": "少来，咱先逗你一句。"},
                },
                "serious": {
                    "persona_blend": {"wisdom": 0.78, "playfulness": 0.6},
                    "reply_plan": {"text": "咱接得住，但先别把自己逼太紧。"},
                },
                "appetite": {
                    "persona_blend": {"sensuality_appetite": 0.56},
                    "reply_plan": {"text": "苹果酒香一飘，咱尾巴都要先动一下。"},
                },
                "correction": {
                    "game_state": {"correction_sensitivity": 0.48},
                    "reply_plan": {"text": "行，咱把那股太老成的劲儿收一收。"},
                },
            },
            stream_status_before={"activation_events": [], "recent_runs": []},
            stream_ticks=[
                {
                    "record": {
                        "influence": {
                            "updated_threads": 1,
                            "motifs": ["continuity", "playfulness"],
                        }
                    }
                }
            ],
            stream_status_after={"activation_events": [{"id": 1}], "recent_runs": [{"run_type": "stream:association_stream"}]},
            initiative_probe={
                "allowed": True,
                "game_rationale": {"ok": True},
                "policy_rationale": {"allowed": True},
                "cooldown_rationale": {"ready": True},
            },
            self_revision={
                "status": "applied",
                "evidence": [{"kind": "explicit_correction", "text": "别总这么老成"}],
                "patch": {
                    "persona_blend": {"playfulness": 0.73},
                    "prompt_composer_bias": {"avoid_counselor_register": 0.82},
                },
            },
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 180.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 640.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1480.0}},
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["failures"])

    def test_filter_self_revision_patch_keeps_only_allowed_fields(self) -> None:
        filtered = filter_self_revision_patch(
            {
                "persona_blend": {"playfulness": 0.7},
                "prompt_composer_bias": {"avoid_counselor_register": 0.8},
                "policy_gate": {"should_not": "pass"},
            }
        )
        self.assertEqual(set(filtered), {"persona_blend", "prompt_composer_bias"})

    def test_initiative_cooldown_accepts_stage11_state_objects(self) -> None:
        class Autonomy:
            initiative_cooldown_hours = 48

        class Config:
            autonomy = Autonomy()

        cooldown = effective_initiative_cooldown_hours(
            config=Config(),
            game_state={
                "trust_score": {"value": 0.74, "confidence": 0.8},
                "initiative_window": {"value": 0.7, "confidence": 0.7},
                "teasing_tolerance": {"value": 0.62, "confidence": 0.6},
                "pressure_level": {"value": 0.2, "confidence": 0.7},
            },
            mode="companion",
        )
        self.assertGreaterEqual(cooldown, 2)
        self.assertLessEqual(cooldown, 48)

    def test_mind_graph_brain_mode_revision_and_game_state_round_trip(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "remember before",
                "we kept the old thread alive",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-stage2",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            graph = MindGraph(temp.repo_root, rag=rm, db_path=temp.runtime_dir / "mind_graph.sqlite3")
            try:
                graph.rebuild()
                graph.set_brain_mode("full_brain", note="unit-test")
                graph.update_game_state(
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    absolute={"trust_score": 0.74, "teasing_tolerance": 0.68},
                    source="unit_test",
                    note="bump",
                )
                run = graph.record_self_revision_run(
                    status="reviewed",
                    evidence=[{"kind": "explicit_correction", "text": "别总这么老成"}],
                    observe={"issues": ["overly_mature"]},
                    plan={"patch": {"persona_blend": {"playfulness": 0.73}}},
                    review={"approved": True},
                    patch={"persona_blend": {"playfulness": 0.73}},
                )
                graph.apply_self_revision_patch(run_id=int(run["id"]), patch={"persona_blend": {"playfulness": 0.73}}, note="unit-test")

                brain_state = graph.brain_state()
                game_state = graph.game_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                self_revision_state = graph.latest_self_revision_state()

                self.assertEqual(brain_state["mode"], "full_brain")
                self.assertAlmostEqual(game_state["trust_score"], 0.74, places=2)
                self.assertAlmostEqual(game_state["teasing_tolerance"], 0.68, places=2)
                self.assertIn(self_revision_state["latest_status"], {"reviewed", "applied"})
                self.assertIn("persona_blend", self_revision_state["applied_patch"])

                rollback = graph.rollback_self_revision()
                self.assertEqual(rollback["status"], "ok")
            finally:
                graph.close()


if __name__ == "__main__":
    unittest.main()
