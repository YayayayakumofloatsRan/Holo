import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.bionic_simulation_lab import (
    build_bionic_simulation_lab,
    write_bionic_simulation_lab_artifacts,
)
from holo_host.config import load_config
from tests.test_stage61_bionic_simulation_lab import _seed_run


class Stage70BiomimeticConsciousnessObservatoryTests(unittest.TestCase):
    def test_scores_biomimetic_consciousness_flow_from_stage61_lab(self) -> None:
        from holo_host.biomimetic_consciousness_observatory import (
            build_biomimetic_consciousness_observatory,
        )

        lab = build_bionic_simulation_lab(
            [_seed_run("seed-a"), _seed_run("seed-b", score=0.91)],
            scenarios=6,
            turns_per_scenario=72,
        )
        report = build_biomimetic_consciousness_observatory(lab)
        dimensions = report["scorecard"]["dimension_index"]

        self.assertEqual(report["stage"], "stage70-biomimetic-consciousness-observatory")
        self.assertEqual(report["source_stage"], "stage61-bionic-simulation-lab")
        self.assertEqual(report["scorecard"]["turn_count"], 432)
        self.assertIn("endogenous_flow", dimensions)
        self.assertIn("recurrent_continuity", dimensions)
        self.assertIn("attractor_dynamics", dimensions)
        self.assertIn("neuromodulator_coupling", dimensions)
        self.assertIn("hippocampal_reactivation", dimensions)
        self.assertIn("global_workspace_ignition", dimensions)
        self.assertIn("flow_to_reply_coupling", dimensions)
        self.assertIn("geometry_observability", dimensions)
        self.assertGreater(report["scorecard"]["biomimetic_consciousness_score"], 0.0)
        self.assertGreaterEqual(report["trajectory"]["tick_count"], 432)
        self.assertTrue(report["trajectory"]["attractor_sequence"])
        self.assertTrue(report["trajectory"]["neuromodulator_heatmap"])
        self.assertEqual(report["hypothesis_updates"][0]["target"], "correction_reactivation")
        self.assertFalse(report["boundary"]["self_memory_write_allowed"])
        self.assertTrue(report["evidence_gate"]["surrogate_only"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_manifold"])

    def test_writes_html_json_and_biomimetic_png(self) -> None:
        from holo_host.biomimetic_consciousness_observatory import (
            build_biomimetic_consciousness_observatory,
            write_biomimetic_consciousness_artifacts,
        )

        lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=4, turns_per_scenario=48)
        report = build_biomimetic_consciousness_observatory(lab)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_biomimetic_consciousness_artifacts(
                report,
                Path(tmpdir) / "stage70.html",
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["consciousness_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage70-biomimetic-consciousness-observatory")
        self.assertIn("Biomimetic Consciousness Observatory", html)
        self.assertIn("Neuromodulator Heatmap", html)
        self.assertIn("Attractor Trajectory", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_evaluates_existing_stage61_lab_json(self) -> None:
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
api_port = 65529
""".strip(),
                encoding="utf-8",
            )
            load_config(config_path=str(config_path), repo_root=root)
            lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=3, turns_per_scenario=40)
            lab_artifacts = write_bionic_simulation_lab_artifacts(
                lab,
                root / "artifacts" / "stage61" / "lab.html",
            )
            output_path = root / "artifacts" / "stage70" / "biomimetic.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-consciousness",
                        "--lab-json",
                        str(lab_artifacts["json"]),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["consciousness_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage70-biomimetic-consciousness-observatory")
        self.assertGreater(payload["observatory"]["biomimetic_consciousness_score"], 0.0)
        self.assertEqual(payload["observatory"]["dimension_count"], 8)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertTrue(payload["observatory"]["do_not_claim_real_consciousness"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
