import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _effect(key: str, estimate: float) -> dict[str, object]:
    return {
        "key": key,
        "estimate": estimate,
        "interpretation": key,
        "support_direction": "stage73_fixture",
    }


def _stage71_report(
    *,
    biomimetic_score: float,
    hippocampal: float,
    correction: float,
    flow_coupling: float,
    hippocampal_delta: float,
    correction_delta: float,
    flow_delta: float,
    decision: str = "partial_support_real_provider",
) -> dict[str, object]:
    effects = [
        _effect("hippocampal_reactivation_delta", hippocampal_delta),
        _effect("correction_survival_proxy_delta", correction_delta),
        _effect("flow_to_reply_coupling_delta", flow_delta),
        _effect("prompt_cost_delta", 0.02),
        _effect("boundary_violation_delta", 0.0),
    ]
    return {
        "ok": True,
        "stage": "stage71-biomimetic-causal-ablation-lab",
        "source_stage": "stage59-provider-longform-trace",
        "baseline_stage70": {
            "stage": "stage70-biomimetic-consciousness-observatory",
            "biomimetic_consciousness_score": biomimetic_score,
            "turn_count": 30,
            "run_count": 3,
        },
        "paired_conditions": {
            "condition_index": {
                "baseline_observed": {
                    "key": "baseline_observed",
                    "turn_count": 30,
                    "dimension_scores": {
                        "hippocampal_reactivation": hippocampal,
                        "flow_to_reply_coupling": flow_coupling,
                    },
                    "metrics": {
                        "correction_survival_proxy": correction,
                        "flow_to_reply_coupling_proxy": flow_coupling,
                        "prompt_cost_proxy": 0.42,
                    },
                }
            }
        },
        "causal_effects": {
            "effects": effects,
            "effect_index": {str(item["key"]): item for item in effects},
        },
        "hypothesis_decision": {
            "target": "correction_reactivation",
            "decision": decision,
            "supported": False,
        },
        "evidence_gate": {
            "surrogate_only": False,
            "real_provider_trace": True,
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
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


def _trace_payload(*, total_tokens: int, max_latency_ms: float) -> dict[str, object]:
    return {
        "stage": "stage59-provider-longform-trace",
        "provider_trace_set": {
            "real_provider_trace": True,
            "collected_run_count": 3,
            "collected_turn_count": 3,
        },
        "budget_guard": {
            "observed_total_tokens": total_tokens,
            "max_total_tokens": total_tokens + 1000,
        },
        "stage46_compatible_runs": [
            {
                "turns": [
                    {"latency_ms": 1000.0, "processor_usage": {"total_tokens": 100}},
                    {"latency_ms": max_latency_ms, "processor_usage": {"total_tokens": 200}},
                    {"latency_ms": 2000.0, "processor_usage": {"total_tokens": 300}},
                ]
            }
        ],
    }


class Stage73BiomimeticProviderProgressTests(unittest.TestCase):
    def test_separates_absolute_provider_gain_from_residual_counterfactual_headroom(self) -> None:
        from holo_host.biomimetic_provider_progress import (
            build_biomimetic_provider_progress,
        )

        before = _stage71_report(
            biomimetic_score=0.534044,
            hippocampal=0.897044,
            correction=0.801491,
            flow_coupling=0.242079,
            hippocampal_delta=0.011206,
            correction_delta=0.048457,
            flow_delta=-0.438947,
        )
        after = _stage71_report(
            biomimetic_score=0.539011,
            hippocampal=0.918328,
            correction=0.830654,
            flow_coupling=0.303688,
            hippocampal_delta=0.011205,
            correction_delta=0.048457,
            flow_delta=-0.342426,
        )
        report = build_biomimetic_provider_progress(
            before,
            after,
            before_trace=_trace_payload(total_tokens=92000, max_latency_ms=19000.0),
            after_trace=_trace_payload(total_tokens=135043, max_latency_ms=617411.46),
        )

        absolute = report["absolute_progress"]
        residual = report["residual_headroom"]
        provider_noise = report["provider_noise"]

        self.assertEqual(report["stage"], "stage73-biomimetic-provider-progress")
        self.assertAlmostEqual(absolute["baseline_hippocampal_reactivation_delta"], 0.021284, places=6)
        self.assertAlmostEqual(absolute["baseline_correction_survival_proxy_delta"], 0.029163, places=6)
        self.assertAlmostEqual(absolute["baseline_biomimetic_score_delta"], 0.004967, places=6)
        self.assertAlmostEqual(residual["hippocampal_reactivation_headroom_change"], -0.000001, places=6)
        self.assertAlmostEqual(residual["correction_survival_headroom_change"], 0.0, places=6)
        self.assertEqual(report["hypothesis_decision"]["decision"], "absolute_improved_residual_partial")
        self.assertEqual(report["hypothesis_decision"]["provider_interpretation"], "provider_improved_but_counterfactual_headroom_remains")
        self.assertTrue(provider_noise["after_latency_outlier"])
        self.assertEqual(provider_noise["after_observed_total_tokens"], 135043)
        self.assertTrue(report["evidence_gate"]["real_provider_trace"])
        self.assertTrue(report["evidence_gate"]["separates_absolute_from_residual"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])
        self.assertFalse(report["boundary"]["transport_decision_authority"])

    def test_writes_html_json_and_progress_png(self) -> None:
        from holo_host.biomimetic_provider_progress import (
            build_biomimetic_provider_progress,
            write_biomimetic_provider_progress_artifacts,
        )

        report = build_biomimetic_provider_progress(
            _stage71_report(
                biomimetic_score=0.50,
                hippocampal=0.80,
                correction=0.72,
                flow_coupling=0.20,
                hippocampal_delta=0.04,
                correction_delta=0.05,
                flow_delta=-0.22,
            ),
            _stage71_report(
                biomimetic_score=0.56,
                hippocampal=0.86,
                correction=0.77,
                flow_coupling=0.24,
                hippocampal_delta=0.03,
                correction_delta=0.05,
                flow_delta=-0.18,
            ),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = write_biomimetic_provider_progress_artifacts(
                report,
                Path(tmpdir) / "stage73.html",
            )
            payload = json.loads(artifacts["json"].read_text(encoding="utf-8"))
            png_header = artifacts["progress_png"].read_bytes()[:8]
            html = artifacts["html"].read_text(encoding="utf-8")

        self.assertEqual(payload["stage"], "stage73-biomimetic-provider-progress")
        self.assertIn("Biomimetic Provider Progress", html)
        self.assertIn("Absolute Provider Progress", html)
        self.assertIn("Residual Counterfactual Headroom", html)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")

    def test_cli_compares_existing_stage71_reports(self) -> None:
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
            before_json = root / "before.json"
            after_json = root / "after.json"
            before_trace_json = root / "before_trace.json"
            after_trace_json = root / "after_trace.json"
            before_json.write_text(
                json.dumps(
                    _stage71_report(
                        biomimetic_score=0.534044,
                        hippocampal=0.897044,
                        correction=0.801491,
                        flow_coupling=0.242079,
                        hippocampal_delta=0.011206,
                        correction_delta=0.048457,
                        flow_delta=-0.438947,
                    )
                ),
                encoding="utf-8",
            )
            after_json.write_text(
                json.dumps(
                    _stage71_report(
                        biomimetic_score=0.539011,
                        hippocampal=0.918328,
                        correction=0.830654,
                        flow_coupling=0.303688,
                        hippocampal_delta=0.011205,
                        correction_delta=0.048457,
                        flow_delta=-0.342426,
                    )
                ),
                encoding="utf-8",
            )
            before_trace_json.write_text(
                json.dumps(_trace_payload(total_tokens=92000, max_latency_ms=19000.0)),
                encoding="utf-8",
            )
            after_trace_json.write_text(
                json.dumps(_trace_payload(total_tokens=135043, max_latency_ms=617411.46)),
                encoding="utf-8",
            )
            output_path = root / "artifacts" / "stage73" / "provider_progress.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-provider-progress",
                        "--before-json",
                        str(before_json),
                        "--after-json",
                        str(after_json),
                        "--before-trace-json",
                        str(before_trace_json),
                        "--after-trace-json",
                        str(after_trace_json),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["progress_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage73-biomimetic-provider-progress")
        self.assertEqual(payload["observatory"]["decision"], "absolute_improved_residual_partial")
        self.assertAlmostEqual(payload["observatory"]["baseline_hippocampal_reactivation_delta"], 0.021284, places=6)
        self.assertAlmostEqual(payload["observatory"]["residual_hippocampal_headroom_change"], -0.000001, places=6)
        self.assertTrue(payload["observatory"]["after_latency_outlier"])
        self.assertTrue(payload["observatory"]["real_provider_trace"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
