import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _progress_report(
    *,
    hippocampal_abs_delta: float = 0.018,
    correction_abs_delta: float = 0.043,
    score_delta: float = 0.012,
    hippocampal_headroom_change: float = -0.0008,
    correction_headroom_change: float = -0.0062,
    flow_loss_reduction: float = 0.03,
    tokens: int = 196000,
) -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage73-biomimetic-provider-progress",
        "absolute_progress": {
            "baseline_hippocampal_reactivation_delta": hippocampal_abs_delta,
            "baseline_correction_survival_proxy_delta": correction_abs_delta,
            "baseline_biomimetic_score_delta": score_delta,
        },
        "residual_headroom": {
            "hippocampal_reactivation_headroom_change": hippocampal_headroom_change,
            "correction_survival_headroom_change": correction_headroom_change,
            "flow_to_reply_coupling_loss_reduction": flow_loss_reduction,
            "residual_counterfactual_headroom_present": True,
        },
        "provider_noise": {
            "after_observed_total_tokens": tokens,
            "after_latency_outlier": False,
            "real_provider_trace": True,
        },
        "hypothesis_decision": {
            "decision": "absolute_improved_residual_partial",
            "provider_interpretation": "provider_improved_but_counterfactual_headroom_remains",
        },
        "evidence_gate": {
            "surrogate_only": False,
            "real_provider_trace": True,
            "do_not_claim_real_consciousness": True,
            "causal_language_bounded": True,
            "separates_absolute_from_residual": True,
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


class Stage76BiomimeticModelFamilyStabilityTests(unittest.TestCase):
    def test_classifies_flow_as_within_model_unstable_not_model_specific(self) -> None:
        from holo_host.biomimetic_model_family_stability import (
            build_biomimetic_model_family_stability,
        )

        report = build_biomimetic_model_family_stability(
            [
                ("deepseek-v4-pro", _progress_report(flow_loss_reduction=0.028034)),
                ("deepseek-v4-pro", _progress_report(flow_loss_reduction=-0.037211)),
                ("deepseek-v4-pro", _progress_report(flow_loss_reduction=0.034111)),
                ("deepseek-v4-flash", _progress_report(flow_loss_reduction=0.205578)),
            ]
        )
        summary = report["model_family_summary"]
        decision = report["hypothesis_decision"]

        self.assertEqual(report["stage"], "stage76-biomimetic-model-family-stability")
        self.assertEqual(summary["model_count"], 2)
        self.assertEqual(summary["cell_count"], 4)
        self.assertEqual(summary["replay_correction_compression_cell_count"], 4)
        self.assertEqual(summary["flow_loss_reduction_cell_count"], 3)
        self.assertTrue(summary["replay_correction_survives_model_variation"])
        self.assertFalse(summary["flow_coupling_survives_all_cells"])
        self.assertEqual(
            summary["flow_instability_assessment"],
            "within_model_replication_unstable_not_model_specific",
        )
        self.assertEqual(
            decision["decision"],
            "model_family_replay_correction_supported_flow_cell_unstable",
        )
        self.assertTrue(report["evidence_gate"]["real_provider_trace"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_marks_flow_model_specific_when_one_model_never_reduces_loss(self) -> None:
        from holo_host.biomimetic_model_family_stability import (
            build_biomimetic_model_family_stability,
        )

        report = build_biomimetic_model_family_stability(
            [
                ("deepseek-v4-pro", _progress_report(flow_loss_reduction=0.02)),
                ("deepseek-v4-flash", _progress_report(flow_loss_reduction=-0.01)),
            ]
        )

        self.assertEqual(
            report["model_family_summary"]["flow_instability_assessment"],
            "model_specific",
        )

    def test_cli_accepts_model_labeled_progress_jsons(self) -> None:
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
            pro_a = root / "pro_a.json"
            pro_b = root / "pro_b.json"
            flash = root / "flash.json"
            pro_a.write_text(json.dumps(_progress_report(flow_loss_reduction=0.02)), encoding="utf-8")
            pro_b.write_text(json.dumps(_progress_report(flow_loss_reduction=-0.01)), encoding="utf-8")
            flash.write_text(json.dumps(_progress_report(flow_loss_reduction=0.08)), encoding="utf-8")
            output_path = root / "artifacts" / "stage76" / "model_family.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-model-family-stability",
                        "--model-progress",
                        f"deepseek-v4-pro={pro_a}",
                        "--model-progress",
                        f"deepseek-v4-pro={pro_b}",
                        "--model-progress",
                        f"deepseek-v4-flash={flash}",
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["model_family_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage76-biomimetic-model-family-stability")
        self.assertEqual(payload["observatory"]["model_count"], 2)
        self.assertEqual(payload["observatory"]["cell_count"], 3)
        self.assertEqual(
            payload["observatory"]["flow_instability_assessment"],
            "within_model_replication_unstable_not_model_specific",
        )
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
