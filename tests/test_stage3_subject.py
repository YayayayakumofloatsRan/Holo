from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

import holo_memory_library.rag_memory as rm
from holo_host.cli import _evaluate_stage3_acceptance
from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import ProcessorTaskResult
from holo_host.operator_bus import plan_operator_cycle, refresh_self_model, run_operator_cycle
from holo_host.store import QueueStore
from tests.test_memory_fabric import _FakeVectorMemory
from tests.test_rag_memory import TempMemoryRepo


class _Stage3Runner:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_task(self, request):
        self.calls.append(request.to_dict())
        task_type = str(request.task_type)
        if task_type == "self_model_observe":
            payload = {
                "active_deficits": ["stiffness_drift", "visual_memory_underused"],
                "long_horizon_goals": ["keep continuity alive", "use visual anchors"],
                "relational_commitments": ["Nemoqi: keep the old thread warm"],
                "homeostasis_targets": {"reply_budget_fast_ms": 350},
                "summary": "self model remains coherent and wants richer recall",
            }
        elif task_type == "operator_plan":
            payload = {
                "task_type": "state_self_fix",
                "goal": "loosen persona stiffness without losing continuity",
                "scope": "state_patch",
                "workspace_mode": "shadow_write",
                "target_files": [],
                "checks": ["reply-probe", "trace-hybrid-recall"],
                "read_boundary": {"repo": "allowed_readonly"},
                "write_boundary": {"live_repo": "forbidden", "shadow_workspace": "allowed", "mind_state": "allowed_after_shadow_acceptance"},
            }
        elif task_type == "self_observe":
            payload = {"issues": ["overly_mature", "recall_depth_gap"], "signal_count": 3, "summary": "too stiff"}
        elif task_type == "self_revision_plan":
            payload = {
                "patch": {
                    "persona_blend": {"playfulness": 0.74, "slyness": 0.69},
                    "prompt_composer_bias": {"avoid_counselor_register": 0.82},
                },
                "rationale": "loosen the tone while keeping continuity",
            }
        elif task_type in {"self_revision_review", "operator_review", "operator_execute_shadow"}:
            payload = {"approved": True, "reason": "bounded_patch_within_allowed_fields", "score_delta": 0.12}
        elif task_type == "image_understand":
            payload = {
                "scene_summary": "苹果和酒摆在木桌上，像旅途里能被想起的一幕",
                "objects": ["apple", "wine", "wooden table"],
                "text_ocr": "",
                "mood_imagery": "warm still life",
                "thread_relevance": 0.84,
                "visual_anchors": ["苹果和酒", "木桌上的旅途感"],
            }
        else:
            payload = {"status": "ok"}
        return ProcessorTaskResult(
            task_type=task_type,
            text=json.dumps(payload, ensure_ascii=False),
            session_id="",
            returncode=0,
            output_schema=request.output_schema,
        )


class Stage3SubjectTests(unittest.TestCase):
    def test_evaluate_stage3_acceptance_passes_core_checks(self) -> None:
        report = _evaluate_stage3_acceptance(
            health={"status": "ok"},
            mode_transition={"status": "ok", "mode": "full_brain"},
            brain_status={
                "mode": "full_brain",
                "cache": {"hit_ratio": 0.46},
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
                ],
            },
            before_self_model={
                "identity_continuity": 0.72,
                "active_deficits": ["stiffness_drift"],
                "long_horizon_goals": ["keep continuity alive"],
                "metadata": {"observed_at": "2026-04-07T00:00:00Z"},
            },
            after_self_model={
                "identity_continuity": 0.78,
                "active_deficits": ["stiffness_drift", "visual_memory_underused"],
                "long_horizon_goals": ["keep continuity alive", "use visual anchors"],
                "metadata": {"observed_at": "2026-04-07T00:30:00Z", "summary": "still coherent"},
            },
            operator_probe={
                "goal": "loosen persona stiffness without losing continuity",
                "write_boundary": {"live_repo": "forbidden"},
            },
            operator_cycle={
                "status": "applied",
                "execution": {"scope": "state_patch", "applied_live": True},
            },
            visual_ingest={"status": "ok"},
            visual_state={"scene_summary": "苹果和酒摆在木桌上", "visual_anchors": ["苹果和酒"]},
            visual_trace={"thread_key": "Nemoqi", "hits": [{"thread_key": "Nemoqi", "scene_summary": "苹果和酒摆在木桌上"}]},
            stream_status={"activation_events": [{"id": 1}], "stream_influence": {"motifs": ["continuity"]}},
            initiative_probe={"allowed": True, "game_rationale": {"ok": True}},
            fast_benchmark={"last_tier": "fast", "timings_ms": {"max": 180.0}},
            recall_benchmark={"last_tier": "recall", "timings_ms": {"max": 760.0}},
            deep_benchmark={"last_tier": "deep_recall", "timings_ms": {"max": 1700.0}},
        )
        self.assertEqual(report["status"], "pass")
        self.assertFalse(report["failures"])

    def test_operator_and_visual_memory_round_trip(self) -> None:
        with TempMemoryRepo() as temp:
            rm.archive_turn(
                "别总那么老成",
                "行，咱把那股太端着的劲儿收一收。",
                source="unit.archive",
                tags=["wechat", "chat_reply"],
                turn_id="turn-stage3",
                metadata={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
            )
            config = load_config(repo_root=temp.repo_root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            runner = _Stage3Runner()
            bridge = MemoryBridge(
                temp.repo_root,
                graph_db_path=temp.runtime_dir / "mind_graph.sqlite3",
                vector=_FakeVectorMemory([]),
                rag=rm,
                runner=runner,
            )
            try:
                bridge.backfill_mind_graph()
                refreshed = refresh_self_model(
                    config=config,
                    runner=runner,
                    memory=bridge,
                    store=store,
                    reason="unit-test",
                    source="test",
                )
                self.assertGreaterEqual(float(refreshed.get("identity_continuity", 0.0) or 0.0), 0.55)

                planned = plan_operator_cycle(
                    config=config,
                    runner=runner,
                    memory=bridge,
                    store=store,
                    reason="unit-test",
                )
                self.assertEqual(planned["status"], "planned")

                cycle = run_operator_cycle(
                    config=config,
                    runner=runner,
                    memory=bridge,
                    store=store,
                    reason="unit-test",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                )
                self.assertIn(cycle["status"], {"applied", "reviewed"})

                png = base64.b64decode(
                    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wn0rC8AAAAASUVORK5CYII="
                )
                with tempfile.TemporaryDirectory() as tmpdir:
                    image_path = Path(tmpdir) / "visual.png"
                    image_path.write_bytes(png)
                    visual = bridge.ingest_image(
                        str(image_path),
                        note="苹果和酒摆在木桌上，像旅途里能被想起的一幕",
                        source="unit.visual",
                        tags=["stage3", "visual"],
                        channel="wechat",
                        thread_key="Nemoqi",
                        chat_name="Nemoqi",
                        sync=True,
                    )
                self.assertEqual(visual["status"], "ok")
                trace = bridge.trace_visual_recall(
                    "苹果 酒 木桌",
                    thread_key="Nemoqi",
                    chat_name="Nemoqi",
                    channel="wechat",
                    limit=4,
                )
                packet = bridge.sidecar_packet(
                    "你还记得那张苹果和酒的图吗",
                    context={"channel": "wechat", "thread_key": "Nemoqi", "chat_name": "Nemoqi"},
                )
                self.assertTrue(trace["hits"])
                self.assertIn("visual_memory", packet)
                self.assertTrue(packet["visual_memory"]["scene_summary"])
                self.assertTrue(packet["visual_memory"]["visual_anchors"])
            finally:
                store.close()
                bridge.activation.close()
                bridge.graph.close()


if __name__ == "__main__":
    unittest.main()
