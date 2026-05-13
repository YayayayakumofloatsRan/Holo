import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from holo_host.config import load_config
from holo_host.store import QueueStore
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage62BionicCapabilityObservatoryTests(unittest.TestCase):
    def test_builds_forward_and_reverse_capability_explainability(self) -> None:
        from holo_host.bionic_capability_observatory import (
            build_bionic_capability_observatory,
        )
        from holo_host.bionic_simulation_lab import build_bionic_simulation_lab

        lab = build_bionic_simulation_lab(
            [_seed_run("seed-a"), _seed_run("seed-b", score=0.91)],
            scenarios=7,
            turns_per_scenario=64,
        )
        report = build_bionic_capability_observatory(lab)

        self.assertEqual(report["stage"], "stage62-bionic-capability-observatory")
        self.assertEqual(report["source_stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(report["capability_scorecard"]["scenario_count"], 7)
        self.assertGreater(report["capability_scorecard"]["aggregate_score"], 0.0)
        self.assertLessEqual(report["capability_scorecard"]["aggregate_score"], 1.0)
        self.assertEqual(report["forward_explainability"]["scenario_count"], 7)
        self.assertGreaterEqual(len(report["forward_explainability"]["scenario_chains"]), 7)
        self.assertGreaterEqual(len(report["reverse_engineering"]["ranked_bottlenecks"]), 1)
        self.assertEqual(
            report["reverse_engineering"]["ranked_bottlenecks"][0]["key"],
            report["intervention_plan"][0]["bottleneck_key"],
        )
        self.assertFalse(report["intervention_plan"][0]["auto_apply"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])
        self.assertFalse(report["boundary"]["self_memory_write_allowed"])

    def test_writes_observatory_html_json_and_png(self) -> None:
        from holo_host.bionic_capability_observatory import (
            build_bionic_capability_observatory,
            write_bionic_capability_observatory_artifacts,
        )
        from holo_host.bionic_simulation_lab import build_bionic_simulation_lab

        lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=5, turns_per_scenario=40)
        report = build_bionic_capability_observatory(lab)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_bionic_capability_observatory_artifacts(
                report, Path(tmpdir) / "stage62.html"
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["capability_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage62-bionic-capability-observatory")
        self.assertIn("Forward Explainability", html)
        self.assertIn("Reverse Engineering", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_runs_observatory_from_stage46_seeds(self) -> None:
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
api_port = 65518
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                for run in [_seed_run("seed-a"), _seed_run("seed-b", score=0.9)]:
                    store.record_agent_eval_run(
                        stage=STAGE46_NAME,
                        suite=DEFAULT_STAGE46_SUITE,
                        status=str(run["status"]),
                        scorecard=dict(run["scorecard"]),
                        run_payload=run,
                    )
            finally:
                store.close()

            output_path = root / "artifacts" / "stage62" / "observatory.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-bionic-capability-observatory",
                        "--limit",
                        "2",
                        "--scenarios",
                        "6",
                        "--turns",
                        "36",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["capability_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage62-bionic-capability-observatory")
        self.assertEqual(payload["observatory"]["scenario_count"], 6)
        self.assertGreaterEqual(payload["observatory"]["bottleneck_count"], 1)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertTrue(payload["observatory"]["do_not_claim_real_manifold"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
