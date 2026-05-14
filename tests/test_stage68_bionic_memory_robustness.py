import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config
from holo_host.bionic_simulation_lab import (
    build_bionic_simulation_lab,
    write_bionic_simulation_lab_artifacts,
)
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage68BionicMemoryRobustnessTests(unittest.TestCase):
    def test_builds_memory_growth_and_priority_scorecard_from_stage61_lab(self) -> None:
        from holo_host.bionic_memory_robustness import (
            build_bionic_memory_robustness_observatory,
        )

        lab = build_bionic_simulation_lab(
            [_seed_run("seed-a"), _seed_run("seed-b", score=0.91)],
            scenarios=7,
            turns_per_scenario=96,
        )
        report = build_bionic_memory_robustness_observatory(lab)
        dimensions = report["memory_scorecard"]["dimension_index"]

        self.assertEqual(report["stage"], "stage68-bionic-memory-robustness")
        self.assertEqual(report["source_stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(report["memory_scorecard"]["turn_count"], 672)
        self.assertIn("memory_survival", dimensions)
        self.assertIn("self_growth_safety", dimensions)
        self.assertIn("priority_extraction", dimensions)
        self.assertGreaterEqual(
            report["self_growth"]["self_memory_write_violation_count"],
            0,
        )
        self.assertFalse(report["boundary"]["self_memory_write_allowed"])
        self.assertTrue(report["evidence_gate"]["surrogate_only"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_manifold"])
        self.assertGreaterEqual(len(report["memory_pressure_observations"]), 7)
        self.assertGreaterEqual(len(report["intervention_plan"]), 1)
        self.assertFalse(report["intervention_plan"][0]["auto_apply"])

    def test_writes_memory_robustness_html_json_and_png(self) -> None:
        from holo_host.bionic_memory_robustness import (
            build_bionic_memory_robustness_observatory,
            write_bionic_memory_robustness_artifacts,
        )

        lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=5, turns_per_scenario=48)
        report = build_bionic_memory_robustness_observatory(lab)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_bionic_memory_robustness_artifacts(
                report,
                Path(tmpdir) / "stage68.html",
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["memory_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage68-bionic-memory-robustness")
        self.assertIn("Memory Robustness", html)
        self.assertIn("Priority Extraction", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_can_evaluate_existing_stage61_lab_json_without_rerun(self) -> None:
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
api_port = 65519
""".strip(),
                encoding="utf-8",
            )
            load_config(config_path=str(config_path), repo_root=root)
            lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=4, turns_per_scenario=40)
            lab_artifacts = write_bionic_simulation_lab_artifacts(
                lab,
                root / "artifacts" / "stage61" / "lab.html",
            )
            output_path = root / "artifacts" / "stage68" / "memory.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-bionic-memory-robustness",
                        "--lab-json",
                        str(lab_artifacts["json"]),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["memory_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage68-bionic-memory-robustness")
        self.assertEqual(payload["observatory"]["turn_count"], 160)
        self.assertGreater(payload["observatory"]["aggregate_score"], 0.0)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertTrue(payload["observatory"]["do_not_claim_real_manifold"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
