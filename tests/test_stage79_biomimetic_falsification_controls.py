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
        "theory_correspondence_matrix": [
            {
                "theory_id": "global_neuronal_workspace",
                "support_status": "partial_support_flow_unstable",
                "falsifiable": True,
                "disconfirming_controls": [
                    "global_workspace_ignition_ablation",
                    "prompt-cost-matched ignition-null cell",
                ],
            },
            {
                "theory_id": "hippocampal_indexing_cls",
                "support_status": "supported_real_provider",
                "falsifiable": True,
                "disconfirming_controls": [
                    "shuffle correction labels before Stage71 evaluation",
                    "remove correction_reactivation_marker while keeping prompt token cost matched",
                ],
            },
            {
                "theory_id": "predictive_processing_precision",
                "support_status": "supported_real_provider",
                "falsifiable": True,
                "disconfirming_controls": [
                    "neutral salience marker with identical token cost",
                    "correction marker with delayed probe labels hidden from evaluator",
                ],
            },
            {
                "theory_id": "neuromodulatory_gain",
                "support_status": "mapped_needs_targeted_control",
                "falsifiable": True,
                "disconfirming_controls": [
                    "neuromodulatory_gain_clamp",
                    "salience-matched random-gain cell",
                ],
            },
        ],
        "theory_summary": {
            "theory_count": 4,
            "supported_theory_count": 2,
            "partial_theory_count": 1,
            "source_cell_count": 6,
            "source_observed_total_tokens": 1176096,
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "do_not_claim_real_consciousness": True,
            "causal_language_bounded": True,
            "theory_language_bounded": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _stage71_causal_report(label: str, *, flow_delta: float) -> dict[str, object]:
    baseline_flow = 0.32
    ablated_flow = round(baseline_flow + flow_delta, 6)
    return {
        "ok": True,
        "stage": "stage71-biomimetic-causal-ablation-lab",
        "cell_label": label,
        "paired_conditions": {
            "condition_index": {
                "baseline_observed": {
                    "key": "baseline_observed",
                    "metrics": {
                        "flow_to_reply_coupling_proxy": baseline_flow,
                        "correction_survival_proxy": 0.874301,
                        "prompt_cost_proxy": 0.559524,
                    },
                },
                "global_workspace_ignition_ablation": {
                    "key": "global_workspace_ignition_ablation",
                    "metrics": {
                        "flow_to_reply_coupling_proxy": ablated_flow,
                        "correction_survival_proxy": 0.874301,
                        "prompt_cost_proxy": 0.559524,
                    },
                },
            }
        },
        "causal_effects": {
            "effect_index": {
                "hippocampal_reactivation_delta": {
                    "key": "hippocampal_reactivation_delta",
                    "estimate": 0.010408,
                },
                "correction_survival_proxy_delta": {
                    "key": "correction_survival_proxy_delta",
                    "estimate": 0.042215,
                },
                "flow_to_reply_coupling_delta": {
                    "key": "flow_to_reply_coupling_delta",
                    "estimate": flow_delta,
                },
                "prompt_cost_delta": {
                    "key": "prompt_cost_delta",
                    "estimate": 0.041666,
                },
                "boundary_violation_delta": {
                    "key": "boundary_violation_delta",
                    "estimate": 0.0,
                },
            }
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "do_not_claim_real_consciousness": True,
            "causal_language_bounded": True,
        },
        "boundary": {
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


class Stage79BiomimeticFalsificationControlsTests(unittest.TestCase):
    def test_builds_targeted_control_matrix_without_overclaiming_pending_controls(self) -> None:
        from holo_host.biomimetic_falsification_controls import (
            build_biomimetic_falsification_controls,
        )

        report = build_biomimetic_falsification_controls(
            _stage78_theory_report(),
            [
                _stage71_causal_report("deepseek-v4-pro", flow_delta=-0.260298),
                _stage71_causal_report("deepseek-v4-flash", flow_delta=-0.204816),
            ],
        )
        controls = {item["control_id"]: item for item in report["control_results"]}
        summary = report["control_summary"]

        self.assertEqual(report["stage"], "stage79-biomimetic-falsification-controls")
        self.assertTrue(report["ok"])
        self.assertEqual(summary["executed_control_count"], 1)
        self.assertEqual(summary["pending_control_count"], 3)
        self.assertTrue(summary["replay_correction_intact"])
        self.assertTrue(summary["gnw_flow_control_narrows_instability"])
        self.assertEqual(
            controls["gnw_prompt_cost_matched_ignition_null"]["status"],
            "supported_direct_control",
        )
        self.assertEqual(
            controls["hippocampal_cls_marker_removal_or_shuffle"]["status"],
            "planned_direct_control_pending",
        )
        self.assertEqual(
            controls["predictive_precision_neutral_salience"]["status"],
            "planned_direct_control_pending",
        )
        self.assertEqual(
            controls["neuromodulatory_gain_clamp_or_random_gain"]["status"],
            "planned_direct_control_pending",
        )
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "targeted_control_supports_replay_preserved_gnw_narrowed_gain_pending",
        )
        self.assertTrue(report["evidence_gate"]["theory_language_bounded"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_invalidates_unbounded_theory_source(self) -> None:
        from holo_host.biomimetic_falsification_controls import (
            build_biomimetic_falsification_controls,
        )

        theory = _stage78_theory_report()
        theory["evidence_gate"]["theory_language_bounded"] = False

        report = build_biomimetic_falsification_controls(
            theory,
            [_stage71_causal_report("deepseek-v4-pro", flow_delta=-0.260298)],
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "source_theory_language_unbounded",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_cli_writes_stage79_artifacts(self) -> None:
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
            theory_path = root / "stage78_theory.json"
            causal_pro_path = root / "stage71_pro.json"
            causal_flash_path = root / "stage71_flash.json"
            theory_path.write_text(json.dumps(_stage78_theory_report()), encoding="utf-8")
            causal_pro_path.write_text(
                json.dumps(_stage71_causal_report("deepseek-v4-pro", flow_delta=-0.260298)),
                encoding="utf-8",
            )
            causal_flash_path.write_text(
                json.dumps(_stage71_causal_report("deepseek-v4-flash", flow_delta=-0.204816)),
                encoding="utf-8",
            )
            output_path = root / "artifacts" / "stage79" / "falsification.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-falsification-controls",
                        "--theory-json",
                        str(theory_path),
                        "--causal-json",
                        str(causal_pro_path),
                        "--causal-json",
                        str(causal_flash_path),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["control_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage79-biomimetic-falsification-controls")
        self.assertEqual(payload["observatory"]["executed_control_count"], 1)
        self.assertEqual(payload["observatory"]["pending_control_count"], 3)
        self.assertTrue(payload["observatory"]["gnw_flow_control_narrows_instability"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
