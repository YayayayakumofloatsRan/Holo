from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from holo_host.config import load_config
from holo_host.consciousness_manifold import build_consciousness_manifold_observatory
from holo_host.consciousness_visualization import build_consciousness_visualization
from holo_host.store import QueueStore


def _turn(
    turn_id: str,
    *,
    hit: int,
    miss: int,
    completion: int,
    latency: int,
    prefix: int,
    dynamic: int,
    salience: float,
    recall: int,
    context_lines: int,
    saved_lines: int,
    priority: float,
    phase: str,
) -> dict:
    return {
        "turn_id": turn_id,
        "latency_ms": latency,
        "processor_usage": {
            "prompt_tokens": hit + miss,
            "completion_tokens": completion,
            "total_tokens": hit + miss + completion,
            "prompt_cache_hit_tokens": hit,
            "prompt_cache_miss_tokens": miss,
        },
        "processor_debug": {
            "prompt_partition": {
                "provider_cache_prefix_tokens": prefix,
                "provider_cache_dynamic_tokens": dynamic,
            },
            "bionic_memory_schedule": {
                "salience_score": salience,
                "recall_budget": recall,
                "dynamic_context_line_count": context_lines,
                "dynamic_fusion_saved_line_count": saved_lines,
            },
            "bionic_memory_lifecycle": {"consolidation_priority": priority},
            "bionic_consciousness_flow": {
                "dominant_phase": phase,
                "phase_count": 6,
                "user_visible": False,
            },
        },
    }


def _stage46_run() -> dict:
    turns = [
        _turn(
            "sensory_entry",
            hit=80,
            miss=2400,
            completion=26,
            latency=8200,
            prefix=620,
            dynamic=2200,
            salience=0.20,
            recall=1,
            context_lines=6,
            saved_lines=4,
            priority=0.20,
            phase="sensory_edge",
        ),
        _turn(
            "memory_pull",
            hit=240,
            miss=1900,
            completion=22,
            latency=6500,
            prefix=700,
            dynamic=1800,
            salience=0.62,
            recall=3,
            context_lines=10,
            saved_lines=7,
            priority=0.55,
            phase="memory_reactivation",
        ),
        _turn(
            "goal_pressure",
            hit=420,
            miss=1500,
            completion=28,
            latency=5400,
            prefix=780,
            dynamic=1500,
            salience=0.72,
            recall=3,
            context_lines=11,
            saved_lines=8,
            priority=0.68,
            phase="goal_pressure",
        ),
        _turn(
            "self_correction",
            hit=680,
            miss=1200,
            completion=34,
            latency=4300,
            prefix=900,
            dynamic=1200,
            salience=0.84,
            recall=4,
            context_lines=12,
            saved_lines=9,
            priority=0.80,
            phase="uncertainty_monitor",
        ),
        _turn(
            "output_gate",
            hit=520,
            miss=1550,
            completion=18,
            latency=5100,
            prefix=820,
            dynamic=1450,
            salience=0.58,
            recall=2,
            context_lines=9,
            saved_lines=8,
            priority=0.62,
            phase="response_intention",
        ),
        _turn(
            "return_arc",
            hit=260,
            miss=2050,
            completion=24,
            latency=6700,
            prefix=700,
            dynamic=1850,
            salience=0.35,
            recall=2,
            context_lines=7,
            saved_lines=6,
            priority=0.38,
            phase="affective_tone",
        ),
        _turn(
            "sensory_return",
            hit=80,
            miss=2400,
            completion=26,
            latency=8200,
            prefix=620,
            dynamic=2200,
            salience=0.20,
            recall=1,
            context_lines=6,
            saved_lines=4,
            priority=0.20,
            phase="sensory_edge",
        ),
    ]
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": "stage56-dimensional-lift-sample",
        "turns": turns,
        "scorecard": {"overall_score": 0.97, "passed": True},
    }


def _stage55() -> dict:
    stage54 = build_consciousness_visualization(_stage46_run())
    return build_consciousness_manifold_observatory(stage54)


class Stage56DimensionalLiftObservatoryTests(unittest.TestCase):
    def test_lifts_stage55_vectors_into_higher_dimensional_residual_space(self) -> None:
        from holo_host.consciousness_dimensional_lift import build_dimensional_lift_observatory

        observatory = build_dimensional_lift_observatory(_stage55())

        self.assertEqual(observatory["stage"], "stage56-dimensional-lift-observatory")
        self.assertEqual(observatory["source_stage"], "stage55-consciousness-manifold-observatory")
        self.assertEqual(observatory["lifted_vector_space"]["base_dimension"], 12)
        self.assertGreaterEqual(observatory["lifted_vector_space"]["lifted_dimension"], 96)
        self.assertEqual(observatory["lifted_vector_space"]["point_count"], 7)
        self.assertEqual(
            len(observatory["lifted_vector_space"]["feature_labels"]),
            observatory["lifted_vector_space"]["lifted_dimension"],
        )
        self.assertTrue(observatory["residual_fast_channels"]["base_vector_preserved"])
        self.assertTrue(observatory["sample_adequacy"]["limited_by_trace_length"])
        self.assertLessEqual(observatory["intrinsic_dimension_probe"]["rank_bounds"]["max_observable_rank"], 6)
        self.assertGreaterEqual(len(observatory["projection_family"]), 4)
        self.assertFalse(observatory["boundary"]["runtime_decision_authority"])
        self.assertFalse(observatory["boundary"]["self_memory_write_allowed"])

    def test_writes_dimensional_lift_html_json_and_png(self) -> None:
        from holo_host.consciousness_dimensional_lift import (
            build_dimensional_lift_observatory,
            render_dimensional_lift_html,
            write_dimensional_lift_artifacts,
        )

        observatory = build_dimensional_lift_observatory(_stage55())
        html = render_dimensional_lift_html(observatory)

        self.assertIn("Dimensional Lift Observatory", html)
        self.assertIn("Intrinsic Dimension Probe", html)
        self.assertIn("Projection Family", html)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_dimensional_lift_artifacts(observatory, Path(tmpdir) / "lift.html")
            report_json = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["dimensional_lift_png"].read_bytes()[:8]

        self.assertEqual(report_json["stage"], "stage56-dimensional-lift-observatory")
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_renders_latest_stage46_dimensional_lift_artifacts(self) -> None:
        from holo_host.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[runtime]
state_dir = "{(root / ".holo_runtime").as_posix()}"
db_path = "{(root / ".holo_runtime" / "holo_host.sqlite3").as_posix()}"
log_dir = "{(root / ".holo_runtime" / "logs").as_posix()}"
api_port = 65512
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                store.record_agent_eval_run(
                    stage=STAGE46_NAME,
                    suite=DEFAULT_STAGE46_SUITE,
                    status="pass",
                    scorecard={"overall_score": 0.97, "passed": True},
                    run_payload=_stage46_run(),
                )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage56" / "lift.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(["--config", str(config_path), "render-consciousness-dimensional-lift", "--output", str(output_path)])
            payload = json.loads(stdout.getvalue())
            json_path = output_path.with_suffix(".json")
            png_path = output_path.with_name("lift_dimensional_lift.png")
            png_header = png_path.read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["json_path"], str(json_path))
        self.assertEqual(payload["dimensional_lift_png_path"], str(png_path))
        self.assertGreaterEqual(payload["observatory"]["lifted_dimension"], 96)
        self.assertTrue(payload["observatory"]["limited_by_trace_length"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
