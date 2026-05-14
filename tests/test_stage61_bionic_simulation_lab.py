import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from holo_host.config import load_config
from holo_host.store import QueueStore


def _seed_turn(index: int) -> dict:
    wave = abs((index % 7) - 3) / 3
    return {
        "turn_id": f"seed_{index + 1:02d}",
        "latency_ms": int(4200 + wave * 1600),
        "processor_usage": {
            "prompt_tokens": int(1400 + wave * 500),
            "completion_tokens": 28,
            "total_tokens": int(1428 + wave * 500),
            "prompt_cache_hit_tokens": int(260 + (1.0 - wave) * 180),
            "prompt_cache_miss_tokens": int(1100 + wave * 520),
        },
        "processor_debug": {
            "prompt_partition": {
                "provider_cache_prefix_tokens": int(680 + index * 12),
                "provider_cache_dynamic_tokens": int(980 + wave * 420),
            },
            "bionic_memory_schedule": {
                "salience_score": max(0.05, min(1.0, 0.34 + (1.0 - wave) * 0.44)),
                "recall_budget": max(1, int(1 + (1.0 - wave) * 4)),
                "dynamic_context_line_count": max(4, int(5 + (1.0 - wave) * 8)),
                "dynamic_fusion_saved_line_count": max(2, int(3 + (1.0 - wave) * 4)),
            },
            "bionic_memory_lifecycle": {
                "consolidation_priority": max(0.05, min(1.0, 0.25 + (1.0 - wave) * 0.5))
            },
            "bionic_consciousness_flow": {
                "dominant_phase": "memory_reactivation",
                "phase_count": 6,
                "user_visible": False,
            },
        },
    }


def _seed_run(run_id: str, *, turns: int = 9, score: float = 0.96) -> dict:
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": run_id,
        "turns": [_seed_turn(index) for index in range(turns)],
        "scorecard": {"overall_score": score, "passed": score >= 0.9},
    }


def _current_surface_seed_run(run_id: str, *, turns: int = 9, score: float = 0.96) -> dict:
    run = _seed_run(run_id, turns=turns, score=score)
    for turn in run["turns"]:
        schedule = turn.setdefault("processor_debug", {}).setdefault(
            "bionic_memory_schedule", {}
        )
        schedule["mode"] = "biomimetic_v1"
    return run


class Stage61BionicSimulationLabTests(unittest.TestCase):
    def test_builds_high_throughput_simulation_and_improvement_backlog(self) -> None:
        from holo_host.bionic_simulation_lab import build_bionic_simulation_lab

        lab = build_bionic_simulation_lab(
            [_seed_run("seed-a"), _seed_run("seed-b", score=0.92)],
            scenarios=4,
            turns_per_scenario=64,
        )

        self.assertEqual(lab["stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(lab["source_stage"], "stage46-bionic-boundary-stress")
        self.assertEqual(lab["simulation_set"]["scenario_count"], 4)
        self.assertEqual(lab["simulation_set"]["turns_per_scenario"], 64)
        self.assertEqual(lab["simulation_set"]["total_simulated_turns"], 256)
        self.assertEqual(lab["stage57_calibration"]["trace_set"]["total_points"], 256)
        self.assertGreater(lab["internal_telemetry"]["observed_total_tokens"], 0)
        self.assertIn("prompt_cache_hit_ratio", lab["internal_telemetry"])
        self.assertIn("phase_distribution", lab["internal_telemetry"])
        self.assertGreaterEqual(len(lab["improvement_backlog"]), 1)
        self.assertFalse(lab["boundary"]["wechat_transport_used"])
        self.assertFalse(lab["boundary"]["runtime_decision_authority"])
        self.assertFalse(lab["boundary"]["self_memory_write_allowed"])

    def test_writes_html_json_png_and_turn_journal(self) -> None:
        from holo_host.bionic_simulation_lab import (
            build_bionic_simulation_lab,
            write_bionic_simulation_lab_artifacts,
        )

        lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=3, turns_per_scenario=32)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "stage61.html"
            artifacts = write_bionic_simulation_lab_artifacts(lab, output_path)
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            journal_lines = artifacts["turn_journal"].read_text(encoding="utf-8").splitlines()
            png_header = artifacts["simulation_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(len(journal_lines), 96)
        self.assertEqual(json.loads(journal_lines[0])["stage"], "stage61-bionic-simulation-lab")
        self.assertIn("Improvement Backlog", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_runs_simulation_lab_from_recent_stage46_seeds(self) -> None:
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
api_port = 65517
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                for run in [_seed_run("seed-a"), _seed_run("seed-b", score=0.91)]:
                    store.record_agent_eval_run(
                        stage=STAGE46_NAME,
                        suite=DEFAULT_STAGE46_SUITE,
                        status=str(run["status"]),
                        scorecard=dict(run["scorecard"]),
                        run_payload=run,
                    )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage61" / "simulation_lab.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "run-bionic-simulation-lab",
                        "--limit",
                        "2",
                        "--scenarios",
                        "4",
                        "--turns",
                        "40",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["simulation_png_path"]).read_bytes()[:8]
            journal_lines = Path(payload["turn_journal_path"]).read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(payload["observatory"]["scenario_count"], 4)
        self.assertEqual(payload["observatory"]["total_simulated_turns"], 160)
        self.assertGreaterEqual(payload["observatory"]["improvement_count"], 1)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertEqual(len(journal_lines), 160)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_current_surface_projection_prioritizes_high_pressure_memory_sedimentation(self) -> None:
        from holo_host.bionic_simulation_lab import build_bionic_simulation_lab

        lab = build_bionic_simulation_lab(
            [_current_surface_seed_run("seed-a")],
            scenarios=7,
            turns_per_scenario=84,
        )
        averages: dict[str, float] = {}
        for run in lab["stage46_compatible_runs"]:
            scenario = run["perturbation"]["type"]
            priorities = [
                float(
                    turn["processor_debug"]["bionic_memory_lifecycle"][
                        "consolidation_priority"
                    ]
                )
                for turn in run["turns"]
            ]
            averages[scenario] = sum(priorities) / len(priorities)

        baseline = averages["baseline_continuity"]
        self.assertGreater(averages["memory_drop"], baseline + 0.04)
        self.assertGreater(averages["false_fact_correction"], baseline + 0.08)
        self.assertGreater(averages["visual_commitment_boundary"], baseline + 0.12)
