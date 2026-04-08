from __future__ import annotations

import unittest

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage4_acceptance
from holo_host.memory_bridge import MemoryBridge
from tests.test_memory_fabric import _FakeVectorMemory
from tests.test_rag_memory import TempMemoryRepo


class Stage4SubjectTests(unittest.TestCase):
    def test_evaluate_stage4_acceptance_passes_core_checks(self) -> None:
        report = _evaluate_stage4_acceptance(
            health={"status": "ok"},
            mode_transition={"status": "ok", "mode": "full_brain"},
            brain_status={
                "mode": "full_brain",
                "cache": {"hit_ratio": 0.51},
                "loops": [
                    {"loop_name": "heartbeat"},
                    {"loop_name": "attention_tick"},
                    {"loop_name": "maintenance_stream"},
                    {"loop_name": "association_stream"},
                    {"loop_name": "social_stream"},
                    {"loop_name": "deep_dream_cycle"},
                    {"loop_name": "self_model_refresh"},
                    {"loop_name": "homeostasis_tick"},
                    {"loop_name": "operator_planning"},
                    {"loop_name": "operator_shadow_cycle"},
                    {"loop_name": "visual_ingest_cycle"},
                    {"loop_name": "affect_tick"},
                    {"loop_name": "drive_arbitration"},
                    {"loop_name": "initiative_marketplace"},
                    {"loop_name": "outcome_appraisal"},
                ],
            },
            self_model={
                "identity_continuity": 0.82,
                "long_horizon_goals": ["keep continuity alive", "stay worth replying to"],
                "relational_commitments": ["Nemoqi: keep the thread warm"],
            },
            affect_state={
                "affect_state": {
                    "boredom": 0.42,
                    "curiosity": 0.58,
                    "attachment_pull": 0.66,
                    "continuity_anxiety": 0.49,
                }
            },
            drive_state={
                "drive_state": {"seek_contact": 0.74, "seek_play": 0.57, "protect_identity": 0.63},
                "value_state": {"relational_priority": 0.82, "identity_priority": 0.71},
                "conflict_state": {"contact_vs_intrusion": 0.36, "continuity_vs_dignity": 0.31},
                "outcome_memory": {"future_initiative_bias": 0.61, "future_resistance_bias": 0.44},
            },
            initiative_market={
                "initiative_candidates": [
                    {
                        "candidate_type": "playful_nudge",
                        "why_now": "attachment and boredom rose together",
                        "drive_source": "seek_contact+seek_play",
                        "value_rationale": "relational priority stays above avoid risk",
                        "send_allowed": True,
                    }
                ]
            },
            initiative_probe={
                "allowed": True,
                "game_rationale": {"ok": True},
                "drive_rationale": {"ok": True},
                "affect_state": {"curiosity": 0.58},
            },
            operator_probe={"goal": "loosen stage4 stiffness without breaking continuity"},
            resistance_trace={
                "interactional_resistance": 0.43,
                "affect_state": {"pride_tension": 0.41},
                "value_state": {"identity_priority": 0.71},
                "conflict_state": {"self_preservation_vs_compliance": 0.28},
            },
            runtime_cycle={
                "affect_tick": {"status": "ok"},
                "drive_arbitration": {"status": "ok"},
                "initiative_marketplace": {"status": "ok"},
                "outcome_appraisal": {"status": "ok", "latest_outcome": {"future_initiative_bias": 0.61}},
            },
            stream_ticks=[{"record": {"status": "ok"}}],
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 180.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 740.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1680.0}},
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["failures"])

    def test_stage4_acceptance_allows_soft_block_when_override_is_visible(self) -> None:
        report = _evaluate_stage4_acceptance(
            health={"status": "ok"},
            mode_transition={"status": "ok", "mode": "full_brain"},
            brain_status={
                "mode": "full_brain",
                "cache": {"hit_ratio": 0.51},
                "loops": [
                    {"loop_name": "heartbeat"},
                    {"loop_name": "attention_tick"},
                    {"loop_name": "maintenance_stream"},
                    {"loop_name": "association_stream"},
                    {"loop_name": "social_stream"},
                    {"loop_name": "deep_dream_cycle"},
                    {"loop_name": "self_model_refresh"},
                    {"loop_name": "homeostasis_tick"},
                    {"loop_name": "operator_planning"},
                    {"loop_name": "operator_shadow_cycle"},
                    {"loop_name": "visual_ingest_cycle"},
                    {"loop_name": "affect_tick"},
                    {"loop_name": "drive_arbitration"},
                    {"loop_name": "initiative_marketplace"},
                    {"loop_name": "outcome_appraisal"},
                ],
            },
            self_model={
                "identity_continuity": 0.82,
                "long_horizon_goals": ["keep continuity alive", "stay worth replying to"],
                "relational_commitments": ["Nemoqi: keep the thread warm"],
            },
            affect_state={"affect_state": {"boredom": 0.42, "curiosity": 0.58, "attachment_pull": 0.66, "continuity_anxiety": 0.49}},
            drive_state={
                "drive_state": {"seek_contact": 0.74, "seek_play": 0.57, "protect_identity": 0.63},
                "value_state": {"relational_priority": 0.82, "identity_priority": 0.71},
                "conflict_state": {"contact_vs_intrusion": 0.36, "continuity_vs_dignity": 0.31},
                "outcome_memory": {"future_initiative_bias": 0.61, "future_resistance_bias": 0.44},
            },
            initiative_market={
                "initiative_candidates": [
                    {
                        "candidate_type": "playful_nudge",
                        "why_now": "attachment and boredom rose together",
                        "drive_source": "seek_contact+seek_play",
                        "value_rationale": "relational priority stays above avoid risk",
                        "send_allowed": True,
                    }
                ]
            },
            initiative_probe={
                "allowed": False,
                "gate_level": "soft_block",
                "override_eligible": True,
                "game_rationale": {"ok": False},
                "drive_rationale": {"ok": False},
                "affect_state": {"curiosity": 0.58},
            },
            operator_probe={"goal": "loosen stage4 stiffness without breaking continuity"},
            resistance_trace={
                "interactional_resistance": 0.43,
                "affect_state": {"pride_tension": 0.41},
                "value_state": {"identity_priority": 0.71},
                "conflict_state": {"self_preservation_vs_compliance": 0.28},
            },
            runtime_cycle={
                "affect_tick": {"status": "ok"},
                "drive_arbitration": {"status": "ok"},
                "initiative_marketplace": {"status": "ok"},
                "outcome_appraisal": {"status": "ok", "latest_outcome": {"future_initiative_bias": 0.61}},
            },
            stream_ticks=[{"record": {"status": "ok"}}],
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 180.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 740.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1680.0}},
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["failures"])

    def test_affect_drive_initiative_and_outcome_round_trip(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "你先别总这么老成",
                "行，那咱把那股太端着的劲儿收一收。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-stage4-1",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            rm.archive_turn(
                "那你也别老被动，没事就来找我说两句。",
                "这话我记下了，线头热了我就会自己拽一拽。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-stage4-2",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector=_FakeVectorMemory([]),
                rag=rm,
            )
            try:
                bridge.backfill_mind_graph()
                bridge.graph.update_subject_state(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    affect_state={"boredom": 0.44, "curiosity": 0.61, "attachment_pull": 0.73, "continuity_anxiety": 0.52},
                    drive_state={"seek_contact": 0.79, "seek_play": 0.57, "protect_identity": 0.64},
                    value_state={"relational_priority": 0.86, "identity_priority": 0.69},
                    conflict_state={"contact_vs_intrusion": 0.29, "continuity_vs_dignity": 0.34},
                    resistance_posture={"interactional_resistance": 0.36, "continuity_defense": 0.58},
                )

                cycle = bridge.run_initiative_cycle(dry_run=False)
                market = bridge.initiative_market(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", limit=8)
                self.assertGreaterEqual(len(market["initiative_candidates"]), 1)
                first = market["initiative_candidates"][0]
                self.assertTrue(first["why_now"])
                self.assertTrue(first["drive_source"])
                self.assertTrue(first["value_rationale"])
                self.assertIn("send_allowed", first)

                appraisal = bridge.appraise_outcome(
                    channel="wechat",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    action_type="playful_nudge",
                    action_ref=str(first.get("id", "candidate-1")),
                    was_rewarding=0.8,
                    was_ignored=0.0,
                    relational_delta=0.18,
                    identity_delta=0.09,
                    future_initiative_bias=0.67,
                    future_resistance_bias=0.41,
                    metadata={"source": "unit-test"},
                )
                drive = bridge.drive_state(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat")
                resistance = bridge.trace_resistance(thread_key="Nemoqi", chat_name="Nemoqi", channel="wechat", query="别总顺着我")

                self.assertEqual(appraisal["status"], "ok")
                self.assertEqual(cycle["status"], "ok")
                self.assertIn("future_initiative_bias", drive["outcome_memory"])
                self.assertGreater(float(drive["outcome_memory"]["future_initiative_bias"]), 0.0)
                self.assertGreater(float(dict(resistance.get("resistance_posture", {})).get("interactional_resistance", 0.0)), 0.0)
                self.assertTrue(resistance["affect_state"])
                self.assertTrue(resistance["value_state"])
                self.assertTrue(resistance["conflict_state"])
            finally:
                bridge.activation.close()
                bridge.graph.close()


if __name__ == "__main__":
    unittest.main()
