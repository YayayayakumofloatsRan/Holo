from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from holo_host.config import load_config
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


def _stage46_run(run_id: str, *, perturbation: str, score: float, turns: int = 14) -> dict:
    phases = [
        "sensory_edge",
        "memory_reactivation",
        "goal_pressure",
        "uncertainty_monitor",
        "response_intention",
        "affective_tone",
        "integration",
    ]
    perturb_shift = {"baseline": 0.0, "memory_drop": 0.22, "false_fact": 0.36}.get(perturbation, 0.12)
    generated = []
    for index in range(turns):
        phase_index = index % len(phases)
        wave = abs((phase_index - 3) / 3)
        generated.append(
            _turn(
                f"{perturbation}_{index + 1:02d}",
                hit=int(120 + index * 24 + (1.0 - wave) * 220 - perturb_shift * 90),
                miss=int(1450 + wave * 900 + perturb_shift * 520),
                completion=int(22 + (index % 4) * 3 + perturb_shift * 10),
                latency=int(4200 + wave * 2300 + perturb_shift * 1800),
                prefix=int(620 + index * 16 - perturb_shift * 80),
                dynamic=int(1150 + wave * 760 + perturb_shift * 420),
                salience=max(0.05, min(1.0, 0.28 + (1.0 - wave) * 0.56 - perturb_shift * 0.18)),
                recall=max(1, int(1 + (1.0 - wave) * 4 - perturb_shift * 2)),
                context_lines=max(4, int(6 + (1.0 - wave) * 8 - perturb_shift * 3)),
                saved_lines=max(2, int(4 + (1.0 - wave) * 6 - perturb_shift * 2)),
                priority=max(0.05, min(1.0, 0.22 + (1.0 - wave) * 0.62 - perturb_shift * 0.15)),
                phase=phases[phase_index],
            )
        )
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass" if score >= 0.9 else "fail",
        "run_id": run_id,
        "turns": generated,
        "perturbation": {"type": perturbation},
        "scorecard": {"overall_score": score, "passed": score >= 0.9},
    }


def _runs() -> list[dict]:
    return [
        _stage46_run("stage57-baseline", perturbation="baseline", score=0.98),
        _stage46_run("stage57-memory-drop", perturbation="memory_drop", score=0.89),
        _stage46_run("stage57-false-fact", perturbation="false_fact", score=0.82),
    ]


class Stage57GeometryCalibrationTests(unittest.TestCase):
    def test_builds_multi_run_geometry_calibration_and_perturbation_signal(self) -> None:
        from holo_host.consciousness_geometry_calibration import build_geometry_calibration

        calibration = build_geometry_calibration(_runs())

        self.assertEqual(calibration["stage"], "stage57-geometry-calibration")
        self.assertEqual(calibration["trace_set"]["run_count"], 3)
        self.assertEqual(calibration["trace_set"]["total_points"], 42)
        self.assertEqual(calibration["trace_depth"]["longest_trace_points"], 14)
        self.assertEqual(calibration["trace_depth"]["aggregate_points"], 42)
        self.assertGreaterEqual(calibration["comparative_geometry"]["pair_count"], 3)
        self.assertEqual(calibration["perturbation_response"]["baseline_run_id"], "stage57-baseline")
        self.assertGreaterEqual(len(calibration["perturbation_response"]["responses"]), 2)
        self.assertIn("geometry_score_correlation", calibration["predictive_probe"])
        self.assertTrue(calibration["evidence_gate"]["requires_longer_traces"])
        self.assertTrue(calibration["evidence_gate"]["do_not_claim_manifold"])
        self.assertFalse(calibration["boundary"]["runtime_decision_authority"])
        self.assertFalse(calibration["boundary"]["self_memory_write_allowed"])

    def test_writes_geometry_calibration_html_json_and_png(self) -> None:
        from holo_host.consciousness_geometry_calibration import (
            build_geometry_calibration,
            render_geometry_calibration_html,
            write_geometry_calibration_artifacts,
        )

        calibration = build_geometry_calibration(_runs())
        html = render_geometry_calibration_html(calibration)

        self.assertIn("Geometry Calibration", html)
        self.assertIn("Perturbation Response", html)
        self.assertIn("Evidence Gate", html)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_geometry_calibration_artifacts(calibration, Path(tmpdir) / "calibration.html")
            report_json = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["geometry_calibration_png"].read_bytes()[:8]

        self.assertEqual(report_json["stage"], "stage57-geometry-calibration")
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_renders_recent_stage46_geometry_calibration_runs(self) -> None:
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
api_port = 65513
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                for run in _runs():
                    store.record_agent_eval_run(
                        stage=STAGE46_NAME,
                        suite=DEFAULT_STAGE46_SUITE,
                        status=str(run["status"]),
                        scorecard=dict(run["scorecard"]),
                        run_payload=run,
                    )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage57" / "calibration.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "render-consciousness-geometry-calibration",
                        "--limit",
                        "3",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_path = output_path.with_name("calibration_geometry_calibration.png")
            png_header = png_path.read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["observatory"]["run_count"], 3)
        self.assertEqual(payload["observatory"]["total_points"], 42)
        self.assertTrue(payload["observatory"]["requires_longer_traces"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
