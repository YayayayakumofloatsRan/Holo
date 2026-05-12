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


def _turn(turn_id: str, index: int) -> dict:
    phase = [
        "sensory_edge",
        "memory_reactivation",
        "goal_pressure",
        "uncertainty_monitor",
        "response_intention",
        "affective_tone",
        "integration",
    ][index % 7]
    wave = abs((index % 7) - 3) / 3
    return {
        "turn_id": turn_id,
        "latency_ms": int(4200 + wave * 2200),
        "processor_usage": {
            "prompt_tokens": int(1600 + wave * 800),
            "completion_tokens": int(22 + (index % 4) * 3),
            "total_tokens": int(1622 + wave * 800 + (index % 4) * 3),
            "prompt_cache_hit_tokens": int(120 + index * 18 + (1.0 - wave) * 180),
            "prompt_cache_miss_tokens": int(1450 + wave * 750),
        },
        "processor_debug": {
            "prompt_partition": {
                "provider_cache_prefix_tokens": int(620 + index * 10),
                "provider_cache_dynamic_tokens": int(1100 + wave * 620),
            },
            "bionic_memory_schedule": {
                "salience_score": max(0.05, min(1.0, 0.28 + (1.0 - wave) * 0.54)),
                "recall_budget": max(1, int(1 + (1.0 - wave) * 4)),
                "dynamic_context_line_count": max(4, int(6 + (1.0 - wave) * 8)),
                "dynamic_fusion_saved_line_count": max(2, int(4 + (1.0 - wave) * 5)),
            },
            "bionic_memory_lifecycle": {
                "consolidation_priority": max(0.05, min(1.0, 0.22 + (1.0 - wave) * 0.62))
            },
            "bionic_consciousness_flow": {
                "dominant_phase": phase,
                "phase_count": 6,
                "user_visible": False,
            },
        },
    }


def _seed_run(run_id: str, *, score: float = 0.98, turns: int = 9) -> dict:
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": run_id,
        "turns": [_turn(f"{run_id}_{index + 1:02d}", index) for index in range(turns)],
        "scorecard": {"overall_score": score, "passed": score >= 0.9},
    }


class Stage58LongformGeometryLabTests(unittest.TestCase):
    def test_builds_bounded_surrogate_longform_traces_and_calibration(self) -> None:
        from holo_host.consciousness_longform_lab import build_longform_geometry_lab

        lab = build_longform_geometry_lab([_seed_run("seed-a"), _seed_run("seed-b", score=0.94)], turns=48)

        self.assertEqual(lab["stage"], "stage58-longform-geometry-lab")
        self.assertEqual(lab["source_stage"], "stage46-bionic-boundary-stress")
        self.assertEqual(lab["longform_trace_set"]["generated_trace_count"], 5)
        self.assertEqual(lab["longform_trace_set"]["turns_per_trace"], 48)
        self.assertEqual(lab["stage57_calibration"]["trace_set"]["run_count"], 5)
        self.assertEqual(lab["stage57_calibration"]["trace_set"]["total_points"], 240)
        self.assertFalse(lab["surrogate_evidence_gate"]["real_provider_trace"])
        self.assertTrue(lab["surrogate_evidence_gate"]["do_not_claim_real_manifold"])
        self.assertTrue(lab["tool_readiness"]["longform_generation_ready"])
        self.assertFalse(lab["boundary"]["runtime_decision_authority"])
        self.assertFalse(lab["boundary"]["self_memory_write_allowed"])

    def test_writes_longform_lab_html_json_and_png(self) -> None:
        from holo_host.consciousness_longform_lab import (
            build_longform_geometry_lab,
            render_longform_geometry_lab_html,
            write_longform_geometry_lab_artifacts,
        )

        lab = build_longform_geometry_lab([_seed_run("seed-a")], turns=36)
        html = render_longform_geometry_lab_html(lab)

        self.assertIn("Long-Form Geometry Lab", html)
        self.assertIn("Surrogate Evidence Gate", html)
        self.assertIn("Stage57 Calibration", html)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_longform_geometry_lab_artifacts(lab, Path(tmpdir) / "longform.html")
            report_json = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["longform_lab_png"].read_bytes()[:8]

        self.assertEqual(report_json["stage"], "stage58-longform-geometry-lab")
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_renders_longform_lab_from_recent_stage46_runs(self) -> None:
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
api_port = 65514
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                for run in [_seed_run("seed-a"), _seed_run("seed-b", score=0.94)]:
                    store.record_agent_eval_run(
                        stage=STAGE46_NAME,
                        suite=DEFAULT_STAGE46_SUITE,
                        status=str(run["status"]),
                        scorecard=dict(run["scorecard"]),
                        run_payload=run,
                    )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage58" / "longform.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "render-consciousness-longform-lab",
                        "--limit",
                        "2",
                        "--turns",
                        "48",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_path = output_path.with_name("longform_longform_lab.png")
            png_header = png_path.read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["output_path"], str(output_path))
        self.assertEqual(payload["observatory"]["generated_trace_count"], 5)
        self.assertEqual(payload["observatory"]["turns_per_trace"], 48)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertTrue(payload["observatory"]["do_not_claim_real_manifold"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
