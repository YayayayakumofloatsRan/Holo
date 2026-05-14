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


class Stage71BiomimeticCausalAblationTests(unittest.TestCase):
    def test_estimates_reactivation_and_ignition_counterfactuals(self) -> None:
        from holo_host.biomimetic_causal_ablation import (
            build_biomimetic_causal_ablation_lab,
        )

        lab = build_bionic_simulation_lab(
            [_seed_run("seed-a"), _seed_run("seed-b", score=0.92)],
            scenarios=7,
            turns_per_scenario=84,
        )
        report = build_biomimetic_causal_ablation_lab(lab)
        effects = report["causal_effects"]["effect_index"]
        conditions = report["paired_conditions"]["condition_index"]

        self.assertEqual(report["stage"], "stage71-biomimetic-causal-ablation-lab")
        self.assertEqual(report["source_stage"], "stage61-bionic-simulation-lab")
        self.assertIn("baseline_observed", conditions)
        self.assertIn("correction_reactivation_boost", conditions)
        self.assertIn("global_workspace_ignition_ablation", conditions)
        self.assertGreater(
            effects["hippocampal_reactivation_delta"]["estimate"],
            0.05,
        )
        self.assertGreater(
            effects["correction_survival_proxy_delta"]["estimate"],
            0.03,
        )
        self.assertLess(
            effects["flow_to_reply_coupling_delta"]["estimate"],
            -0.03,
        )
        self.assertLessEqual(
            abs(effects["prompt_cost_delta"]["estimate"]),
            0.06,
        )
        self.assertEqual(effects["boundary_violation_delta"]["estimate"], 0.0)
        self.assertEqual(report["hypothesis_decision"]["target"], "correction_reactivation")
        self.assertIn(report["hypothesis_decision"]["decision"], {"support_surrogate", "needs_real_provider"})
        self.assertTrue(report["evidence_gate"]["surrogate_only"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertTrue(report["evidence_gate"]["causal_language_bounded"])
        self.assertFalse(report["boundary"]["self_memory_write_allowed"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_writes_html_json_and_causal_png(self) -> None:
        from holo_host.biomimetic_causal_ablation import (
            build_biomimetic_causal_ablation_lab,
            write_biomimetic_causal_ablation_artifacts,
        )

        lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=7, turns_per_scenario=64)
        report = build_biomimetic_causal_ablation_lab(lab)

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_biomimetic_causal_ablation_artifacts(
                report,
                Path(tmpdir) / "stage71.html",
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["causal_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage71-biomimetic-causal-ablation-lab")
        self.assertIn("Biomimetic Causal Ablation Lab", html)
        self.assertIn("Paired Conditions", html)
        self.assertIn("Causal Effects", html)
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
api_port = 65531
""".strip(),
                encoding="utf-8",
            )
            load_config(config_path=str(config_path), repo_root=root)
            lab = build_bionic_simulation_lab([_seed_run("seed-a")], scenarios=7, turns_per_scenario=48)
            lab_artifacts = write_bionic_simulation_lab_artifacts(
                lab,
                root / "artifacts" / "stage61" / "lab.html",
            )
            output_path = root / "artifacts" / "stage71" / "causal.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-causal-ablation",
                        "--lab-json",
                        str(lab_artifacts["json"]),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["causal_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage71-biomimetic-causal-ablation-lab")
        self.assertGreater(payload["observatory"]["hippocampal_reactivation_delta"], 0.05)
        self.assertLess(payload["observatory"]["flow_to_reply_coupling_delta"], -0.03)
        self.assertTrue(payload["observatory"]["surrogate_only"])
        self.assertTrue(payload["observatory"]["causal_language_bounded"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
