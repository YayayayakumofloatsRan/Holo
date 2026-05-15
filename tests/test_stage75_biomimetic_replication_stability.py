import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _progress_report(
    *,
    hippocampal_abs_delta: float,
    correction_abs_delta: float,
    score_delta: float,
    hippocampal_headroom_change: float,
    correction_headroom_change: float,
    flow_loss_reduction: float,
    tokens: int = 190000,
    latency_outlier: bool = False,
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
            "after_latency_outlier": latency_outlier,
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


class Stage75BiomimeticReplicationStabilityTests(unittest.TestCase):
    def test_marks_replay_correction_replication_even_when_flow_does_not_replicate(self) -> None:
        from holo_host.biomimetic_replication_stability import (
            build_biomimetic_replication_stability,
        )

        report = build_biomimetic_replication_stability(
            [
                _progress_report(
                    hippocampal_abs_delta=0.017593,
                    correction_abs_delta=0.043647,
                    score_delta=0.011601,
                    hippocampal_headroom_change=-0.000797,
                    correction_headroom_change=-0.006242,
                    flow_loss_reduction=0.028034,
                ),
                _progress_report(
                    hippocampal_abs_delta=0.01339,
                    correction_abs_delta=0.011948,
                    score_delta=0.0069,
                    hippocampal_headroom_change=-0.00013,
                    correction_headroom_change=-0.001026,
                    flow_loss_reduction=-0.037211,
                    tokens=191768,
                ),
            ]
        )
        summary = report["replication_summary"]
        decision = report["hypothesis_decision"]

        self.assertEqual(report["stage"], "stage75-biomimetic-replication-stability")
        self.assertEqual(summary["cell_count"], 2)
        self.assertEqual(summary["real_provider_cell_count"], 2)
        self.assertEqual(summary["absolute_improved_cell_count"], 2)
        self.assertEqual(summary["replay_correction_compression_cell_count"], 2)
        self.assertEqual(summary["flow_loss_reduction_cell_count"], 1)
        self.assertTrue(summary["replay_correction_replicated"])
        self.assertFalse(summary["flow_coupling_replicated"])
        self.assertEqual(decision["decision"], "replicated_replay_correction_partial_flow")
        self.assertEqual(decision["replicated_scope"], "replay_correction_only")
        self.assertTrue(report["evidence_gate"]["real_provider_trace"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_writes_html_json_and_stability_png(self) -> None:
        from holo_host.biomimetic_replication_stability import (
            build_biomimetic_replication_stability,
            write_biomimetic_replication_stability_artifacts,
        )

        report = build_biomimetic_replication_stability(
            [
                _progress_report(
                    hippocampal_abs_delta=0.02,
                    correction_abs_delta=0.04,
                    score_delta=0.01,
                    hippocampal_headroom_change=-0.001,
                    correction_headroom_change=-0.004,
                    flow_loss_reduction=0.02,
                ),
                _progress_report(
                    hippocampal_abs_delta=0.01,
                    correction_abs_delta=0.02,
                    score_delta=0.005,
                    hippocampal_headroom_change=-0.0005,
                    correction_headroom_change=-0.002,
                    flow_loss_reduction=-0.01,
                ),
            ]
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_biomimetic_replication_stability_artifacts(
                report,
                Path(tmpdir) / "stage75.html",
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["stability_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage75-biomimetic-replication-stability")
        self.assertIn("Biomimetic Replication Stability", html)
        self.assertIn("Cell Results", html)
        self.assertIn("Replication Summary", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_evaluates_repeated_progress_jsons(self) -> None:
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
            progress_a = root / "progress_a.json"
            progress_b = root / "progress_b.json"
            progress_a.write_text(
                json.dumps(
                    _progress_report(
                        hippocampal_abs_delta=0.017593,
                        correction_abs_delta=0.043647,
                        score_delta=0.011601,
                        hippocampal_headroom_change=-0.000797,
                        correction_headroom_change=-0.006242,
                        flow_loss_reduction=0.028034,
                    )
                ),
                encoding="utf-8",
            )
            progress_b.write_text(
                json.dumps(
                    _progress_report(
                        hippocampal_abs_delta=0.01339,
                        correction_abs_delta=0.011948,
                        score_delta=0.0069,
                        hippocampal_headroom_change=-0.00013,
                        correction_headroom_change=-0.001026,
                        flow_loss_reduction=-0.037211,
                    )
                ),
                encoding="utf-8",
            )
            output_path = root / "artifacts" / "stage75" / "replication.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-replication-stability",
                        "--progress-json",
                        str(progress_a),
                        "--progress-json",
                        str(progress_b),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["stability_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage75-biomimetic-replication-stability")
        self.assertEqual(payload["observatory"]["decision"], "replicated_replay_correction_partial_flow")
        self.assertEqual(payload["observatory"]["cell_count"], 2)
        self.assertEqual(payload["observatory"]["replay_correction_compression_cell_count"], 2)
        self.assertEqual(payload["observatory"]["flow_loss_reduction_cell_count"], 1)
        self.assertTrue(payload["observatory"]["real_provider_trace"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
