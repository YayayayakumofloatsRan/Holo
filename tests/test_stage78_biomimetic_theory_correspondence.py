import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _stage77_model_family_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage76-biomimetic-model-family-stability",
        "model_family_summary": {
            "model_count": 2,
            "cell_count": 6,
            "real_provider_cell_count": 6,
            "replay_correction_compression_cell_count": 6,
            "flow_loss_reduction_cell_count": 5,
            "all_real_provider_cells": True,
            "replay_correction_survives_model_variation": True,
            "flow_coupling_survives_all_cells": False,
            "flow_instability_assessment": "within_model_replication_unstable_not_model_specific",
            "mean_hippocampal_reactivation_headroom_change": -0.000696,
            "mean_correction_survival_headroom_change": -0.005373,
            "mean_flow_to_reply_coupling_loss_reduction": 0.075042,
            "observed_total_tokens": 1176096,
        },
        "hypothesis_decision": {
            "decision": "model_family_replay_correction_supported_flow_cell_unstable",
            "supported_scope": "replay_correction_with_flow_cell_instability",
        },
        "evidence_gate": {
            "surrogate_only": False,
            "real_provider_trace": True,
            "do_not_claim_real_consciousness": True,
            "causal_language_bounded": True,
            "model_family_language_bounded": True,
        },
        "boundary": {
            "observational_only": True,
            "source_trace_only": True,
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


class Stage78BiomimeticTheoryCorrespondenceTests(unittest.TestCase):
    def test_builds_falsifiable_theory_matrix_from_stage77_evidence(self) -> None:
        from holo_host.biomimetic_theory_correspondence import (
            build_biomimetic_theory_correspondence,
        )

        report = build_biomimetic_theory_correspondence(_stage77_model_family_report())
        matrix = report["theory_correspondence_matrix"]
        summary = report["theory_summary"]
        decisions = {item["theory_id"]: item for item in matrix}

        self.assertEqual(report["stage"], "stage78-biomimetic-theory-correspondence")
        self.assertEqual(summary["theory_count"], 4)
        self.assertEqual(summary["falsifiable_theory_count"], 4)
        self.assertEqual(summary["supported_theory_count"], 2)
        self.assertEqual(summary["partial_theory_count"], 1)
        self.assertEqual(summary["needs_control_theory_count"], 1)
        self.assertEqual(summary["publication_readiness"], "bounded_preprint_candidate")
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "publishable_bounded_replay_correction_with_partial_flow",
        )
        self.assertEqual(
            decisions["global_neuronal_workspace"]["support_status"],
            "partial_support_flow_unstable",
        )
        self.assertEqual(
            decisions["hippocampal_indexing_cls"]["support_status"],
            "supported_real_provider",
        )
        self.assertEqual(
            decisions["predictive_processing_precision"]["support_status"],
            "supported_real_provider",
        )
        self.assertEqual(
            decisions["neuromodulatory_gain"]["support_status"],
            "mapped_needs_targeted_control",
        )
        for row in matrix:
            self.assertGreaterEqual(len(row["holo_variables"]), 3)
            self.assertGreaterEqual(len(row["measurable_predictions"]), 2)
            self.assertGreaterEqual(len(row["disconfirming_controls"]), 2)
            self.assertTrue(row["falsifiable"])
        self.assertTrue(report["evidence_gate"]["theory_language_bounded"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_invalidates_unbounded_source_claims(self) -> None:
        from holo_host.biomimetic_theory_correspondence import (
            build_biomimetic_theory_correspondence,
        )

        source = _stage77_model_family_report()
        source["evidence_gate"]["do_not_claim_real_consciousness"] = False

        report = build_biomimetic_theory_correspondence(source)

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "source_consciousness_claim_not_blocked",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_cli_writes_theory_artifacts(self) -> None:
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
            source_path = root / "stage77_model_family.json"
            source_path.write_text(json.dumps(_stage77_model_family_report()), encoding="utf-8")
            output_path = root / "artifacts" / "stage78" / "theory.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-theory-correspondence",
                        "--model-family-json",
                        str(source_path),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["theory_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage78-biomimetic-theory-correspondence")
        self.assertEqual(payload["observatory"]["theory_count"], 4)
        self.assertEqual(payload["observatory"]["falsifiable_theory_count"], 4)
        self.assertEqual(payload["observatory"]["publication_readiness"], "bounded_preprint_candidate")
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
