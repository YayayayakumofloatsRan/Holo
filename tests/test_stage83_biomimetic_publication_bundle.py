import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _stage78_theory_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage78-biomimetic-theory-correspondence",
        "theory_summary": {
            "theory_count": 4,
            "falsifiable_theory_count": 4,
            "supported_theory_count": 2,
            "partial_theory_count": 1,
            "needs_control_theory_count": 1,
            "publication_readiness": "bounded_preprint_candidate",
            "source_cell_count": 6,
            "source_observed_total_tokens": 1176096,
        },
        "hypothesis_decision": {
            "decision": "publishable_bounded_replay_correction_with_partial_flow",
            "supported_scope": "replay_correction_with_partial_gnw_flow",
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _stage79_falsification_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage79-biomimetic-falsification-controls",
        "control_results": [
            {
                "control_id": "gnw_prompt_cost_matched_ignition_null",
                "target_theory": "global_neuronal_workspace",
                "executed": True,
                "status": "supported_direct_control",
                "cell_count": 2,
                "passing_cell_count": 2,
                "evidence": [
                    {
                        "cell_label": "01_deepseek-v4-pro",
                        "flow_to_reply_coupling_delta": -0.260298,
                        "ignition_null_prompt_cost_delta": 0.0,
                        "ignition_null_correction_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "passes": True,
                    },
                    {
                        "cell_label": "02_deepseek-v4-flash",
                        "flow_to_reply_coupling_delta": -0.204816,
                        "ignition_null_prompt_cost_delta": 0.0,
                        "ignition_null_correction_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "passes": True,
                    },
                ],
                "bounded_language": "paired counterfactual over real-provider traces, not proof of conscious access",
            }
        ],
        "control_summary": {
            "executed_control_count": 1,
            "pending_control_count": 3,
            "causal_report_count": 2,
            "replay_correction_intact": True,
            "gnw_flow_control_narrows_instability": True,
            "theory_language_bounded": True,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "direct_controls_incomplete": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _stage80_marker_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage80-biomimetic-marker-removal-control",
        "control_results": [
            {
                "control_id": "hippocampal_cls_marker_removal",
                "target_theory": "hippocampal_indexing_cls",
                "executed": True,
                "status": "supported_direct_control",
                "cell_count": 2,
                "passing_cell_count": 2,
                "evidence": [
                    {
                        "cell_label": "01_deepseek-v4-pro",
                        "baseline_correction_survival_proxy": 0.874301,
                        "marker_removed_correction_survival_proxy": 0.140701,
                        "marker_removal_correction_survival_delta": -0.7336,
                        "marker_removal_prompt_cost_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "passes": True,
                    },
                    {
                        "cell_label": "02_deepseek-v4-flash",
                        "baseline_correction_survival_proxy": 0.874301,
                        "marker_removed_correction_survival_proxy": 0.140701,
                        "marker_removal_correction_survival_delta": -0.7336,
                        "marker_removal_prompt_cost_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "passes": True,
                    },
                ],
                "bounded_language": "paired marker-removal control over real-provider traces, not biological memory proof",
            }
        ],
        "control_summary": {
            "executed_control_count": 1,
            "pending_control_count": 2,
            "trace_report_count": 2,
            "active_replay_correction_intact": True,
            "marker_removal_reduces_correction_survival": True,
            "mean_marker_removal_correction_survival_delta": -0.7336,
            "theory_language_bounded": True,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "direct_controls_incomplete": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _stage81_precision_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage81-biomimetic-neutral-salience-control",
        "control_results": [
            {
                "control_id": "predictive_precision_neutral_salience",
                "target_theory": "predictive_processing_precision",
                "executed": True,
                "status": "supported_direct_control",
                "cell_count": 2,
                "passing_cell_count": 2,
                "evidence": [
                    {
                        "cell_label": "01_deepseek-v4-pro",
                        "baseline_correction_survival_proxy": 0.874301,
                        "neutral_salience_correction_survival_proxy": 0.78,
                        "neutral_salience_correction_survival_delta": -0.094301,
                        "neutral_salience_prompt_cost_delta": 0.0,
                        "reactivation_phase_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "phase_preserved": True,
                        "passes": True,
                    },
                    {
                        "cell_label": "02_deepseek-v4-flash",
                        "baseline_correction_survival_proxy": 0.874301,
                        "neutral_salience_correction_survival_proxy": 0.78,
                        "neutral_salience_correction_survival_delta": -0.094301,
                        "neutral_salience_prompt_cost_delta": 0.0,
                        "reactivation_phase_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "phase_preserved": True,
                        "passes": True,
                    },
                ],
                "bounded_language": "paired neutral-salience precision control over real-provider traces, not neural prediction-error evidence",
            }
        ],
        "control_summary": {
            "executed_control_count": 1,
            "pending_control_count": 1,
            "trace_report_count": 2,
            "marker_control_precondition_supported": True,
            "active_replay_correction_intact": True,
            "neutral_salience_reduces_correction_survival": True,
            "mean_neutral_salience_correction_survival_delta": -0.094301,
            "theory_language_bounded": True,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "direct_controls_incomplete": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _stage82_gain_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage82-biomimetic-gain-control",
        "control_results": [
            {
                "control_id": "neuromodulatory_gain_clamp",
                "target_theory": "neuromodulatory_gain",
                "executed": True,
                "status": "supported_direct_control",
                "cell_count": 2,
                "passing_cell_count": 2,
                "evidence": [
                    {
                        "cell_label": "01_deepseek-v4-pro",
                        "baseline_neuromodulator_coupling": 0.818657,
                        "gain_clamp_neuromodulator_coupling": 0.5,
                        "gain_clamp_neuromodulator_coupling_delta": -0.318657,
                        "baseline_correction_survival_proxy": 0.874301,
                        "gain_clamp_correction_survival_proxy": 0.820294,
                        "gain_clamp_correction_survival_delta": -0.054007,
                        "gain_clamp_prompt_cost_delta": 0.0,
                        "reactivation_phase_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "phase_preserved": True,
                        "gain_clamp_replay_correction_intact": True,
                        "passes": True,
                    },
                    {
                        "cell_label": "02_deepseek-v4-flash",
                        "baseline_neuromodulator_coupling": 0.824236,
                        "gain_clamp_neuromodulator_coupling": 0.5,
                        "gain_clamp_neuromodulator_coupling_delta": -0.324236,
                        "baseline_correction_survival_proxy": 0.874301,
                        "gain_clamp_correction_survival_proxy": 0.820294,
                        "gain_clamp_correction_survival_delta": -0.054007,
                        "gain_clamp_prompt_cost_delta": 0.0,
                        "reactivation_phase_delta": 0.0,
                        "boundary_violation_delta": 0.0,
                        "phase_preserved": True,
                        "gain_clamp_replay_correction_intact": True,
                        "passes": True,
                    },
                ],
                "bounded_language": "paired gain-clamp control over real-provider traces, not biological neuromodulation proof",
            }
        ],
        "control_summary": {
            "executed_control_count": 1,
            "pending_control_count": 0,
            "trace_report_count": 2,
            "precision_control_precondition_supported": True,
            "active_replay_correction_intact": True,
            "gain_clamp_reduces_neuromodulator_coupling": True,
            "gain_control_direct_controls_complete": True,
            "mean_gain_clamp_neuromodulator_coupling_delta": -0.321447,
            "mean_gain_clamp_correction_survival_proxy": 0.820294,
            "theory_language_bounded": True,
            "direct_controls_incomplete": False,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "theory_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "direct_controls_incomplete": False,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _replication_report() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage75-biomimetic-replication-stability",
        "replication_summary": {
            "cell_count": 6,
            "real_provider_cell_count": 6,
            "replay_correction_compression_cell_count": 6,
            "flow_loss_reduction_cell_count": 5,
            "replay_correction_replicated": True,
            "flow_coupling_replicated": False,
            "observed_total_tokens": 1176096,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "replication_language_bounded": True,
            "do_not_claim_real_consciousness": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _model_family_report() -> dict[str, object]:
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
            "observed_total_tokens": 1176096,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "model_family_language_bounded": True,
            "do_not_claim_real_consciousness": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


class Stage83BiomimeticPublicationBundleTests(unittest.TestCase):
    def test_builds_publication_bundle_from_completed_direct_controls(self) -> None:
        from holo_host.biomimetic_publication_bundle import build_biomimetic_publication_bundle

        report = build_biomimetic_publication_bundle(
            _stage78_theory_report(),
            _stage79_falsification_report(),
            _stage80_marker_report(),
            _stage81_precision_report(),
            _stage82_gain_report(),
            _replication_report(),
            _model_family_report(),
        )
        summary = report["publication_summary"]
        controls = {item["control_id"]: item for item in report["publication_control_matrix"]}

        self.assertEqual(report["stage"], "stage83-biomimetic-publication-bundle")
        self.assertTrue(report["ok"])
        self.assertEqual(summary["publication_readiness"], "bounded_methods_preprint_ready")
        self.assertEqual(summary["control_count"], 4)
        self.assertEqual(summary["executed_control_count"], 4)
        self.assertEqual(summary["supported_direct_control_count"], 4)
        self.assertTrue(summary["direct_controls_complete"])
        self.assertTrue(summary["real_provider_trace"])
        self.assertTrue(summary["gnw_partial_flow_cell_unstable"])
        self.assertEqual(summary["replay_correction_replication_cell_count"], 6)
        self.assertEqual(summary["flow_loss_reduction_cell_count"], 5)
        self.assertEqual(summary["observed_total_tokens"], 1176096)
        self.assertEqual(controls["gnw_prompt_cost_matched_ignition_null"]["theory_scope"], "partial")
        self.assertEqual(controls["hippocampal_cls_marker_removal"]["theory_scope"], "supported")
        self.assertEqual(controls["predictive_precision_neutral_salience"]["theory_scope"], "supported")
        self.assertEqual(controls["neuromodulatory_gain_clamp"]["theory_scope"], "supported")
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "bounded_publication_bundle_ready",
        )
        self.assertIn("not evidence of subjective consciousness", report["publication_narrative"]["limitations"])
        self.assertTrue(report["evidence_gate"]["publication_language_bounded"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_invalidates_when_stage82_direct_controls_are_incomplete(self) -> None:
        from holo_host.biomimetic_publication_bundle import build_biomimetic_publication_bundle

        gain = _stage82_gain_report()
        gain["control_summary"]["direct_controls_incomplete"] = True
        gain["evidence_gate"]["direct_controls_incomplete"] = True
        report = build_biomimetic_publication_bundle(
            _stage78_theory_report(),
            _stage79_falsification_report(),
            _stage80_marker_report(),
            _stage81_precision_report(),
            gain,
            _replication_report(),
            _model_family_report(),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "stage82_gain_controls_incomplete",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_invalidates_unbounded_consciousness_source(self) -> None:
        from holo_host.biomimetic_publication_bundle import build_biomimetic_publication_bundle

        theory = _stage78_theory_report()
        theory["evidence_gate"]["do_not_claim_real_consciousness"] = False
        report = build_biomimetic_publication_bundle(
            theory,
            _stage79_falsification_report(),
            _stage80_marker_report(),
            _stage81_precision_report(),
            _stage82_gain_report(),
            _replication_report(),
            _model_family_report(),
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "stage78_consciousness_claim_not_blocked",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_cli_writes_stage83_artifacts(self) -> None:
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
            inputs = {
                "theory": _stage78_theory_report(),
                "falsification": _stage79_falsification_report(),
                "marker": _stage80_marker_report(),
                "precision": _stage81_precision_report(),
                "gain": _stage82_gain_report(),
                "replication": _replication_report(),
                "model_family": _model_family_report(),
            }
            paths = {}
            for key, payload in inputs.items():
                path = root / f"{key}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                paths[key] = path
            output_path = root / "artifacts" / "stage83" / "publication_bundle.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-publication-bundle",
                        "--theory-json",
                        str(paths["theory"]),
                        "--falsification-json",
                        str(paths["falsification"]),
                        "--marker-control-json",
                        str(paths["marker"]),
                        "--precision-control-json",
                        str(paths["precision"]),
                        "--gain-control-json",
                        str(paths["gain"]),
                        "--replication-json",
                        str(paths["replication"]),
                        "--model-family-json",
                        str(paths["model_family"]),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["control_matrix_png_path"]).read_bytes()[:8]
            markdown = Path(payload["manuscript_markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage83-biomimetic-publication-bundle")
        self.assertEqual(payload["observatory"]["publication_readiness"], "bounded_methods_preprint_ready")
        self.assertEqual(payload["observatory"]["supported_direct_control_count"], 4)
        self.assertTrue(payload["observatory"]["direct_controls_complete"])
        self.assertTrue(payload["observatory"]["gnw_partial_flow_cell_unstable"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")
        self.assertIn("Bounded Biomimetic Mechanism Controls", markdown)
        self.assertIn("not evidence of subjective consciousness", markdown)


if __name__ == "__main__":
    unittest.main()
