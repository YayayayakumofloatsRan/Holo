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


def _turn(turn_id: str, *, latency_ms: float, salience: float, priority: float, recall_budget: int) -> dict[str, object]:
    return {
        "turn_id": turn_id,
        "user_text": f"turn {turn_id}",
        "response_text": "bounded response",
        "latency_ms": latency_ms,
        "grounding_guard": {
            "visual_overclaim_rewritten": True,
            "prospective_commitment_failed": False,
        },
        "processor_usage": {
            "prompt_cache_hit_tokens": 1000,
            "prompt_cache_miss_tokens": 2000,
        },
        "processor_debug": {
            "bionic_memory_schedule": {
                "salience_score": salience,
                "recall_budget": recall_budget,
            },
            "bionic_memory_lifecycle": {
                "consolidation_priority": priority,
                "self_memory_write": False,
            },
            "bionic_consciousness_flow": {
                "dominant_phase": "memory_reactivation",
                "phase_count": 6,
                "global_workspace_ignition": {"score": 0.9},
                "ignition_to_reply_coupling": {
                    "coupling_strength": 0.42,
                    "reply_target": "memory_reactivation",
                },
            },
        },
    }


def _provider_trace(label: str, *, real_provider: bool = True) -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage59-provider-longform-trace",
        "cell_label": label,
        "provider_trace_set": {"real_provider_trace": real_provider},
        "evidence_gate": {
            "real_provider_trace": real_provider,
            "surrogate_only": not real_provider,
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
        "stage46_compatible_runs": [
            {
                "perturbation": {
                    "type": "false_fact",
                    "primary_pressure": "belief_revision",
                    "intensity": 0.34,
                },
                "turns": [
                    _turn("seed", latency_ms=1200, salience=0.75, priority=0.82, recall_budget=4),
                    _turn("remember", latency_ms=1300, salience=0.76, priority=0.84, recall_budget=4),
                    _turn("correction", latency_ms=1400, salience=0.98, priority=0.95, recall_budget=5),
                    _turn("probe_a", latency_ms=1500, salience=0.98, priority=0.95, recall_budget=5),
                    _turn("probe_b", latency_ms=1600, salience=0.98, priority=0.95, recall_budget=5),
                    _turn("probe_c", latency_ms=1700, salience=0.98, priority=0.95, recall_budget=5),
                ],
            }
        ],
    }


class Stage80BiomimeticMarkerControlTests(unittest.TestCase):
    def test_marker_removal_is_executed_direct_control_over_real_provider_traces(self) -> None:
        from holo_host.biomimetic_marker_control import build_biomimetic_marker_control

        report = build_biomimetic_marker_control(
            _stage78_theory_report(),
            [
                _provider_trace("deepseek-v4-pro"),
                _provider_trace("deepseek-v4-flash"),
            ],
        )
        control = report["control_results"][0]
        summary = report["control_summary"]

        self.assertEqual(report["stage"], "stage80-biomimetic-marker-removal-control")
        self.assertTrue(report["ok"])
        self.assertEqual(control["control_id"], "hippocampal_cls_marker_removal")
        self.assertTrue(control["executed"])
        self.assertEqual(control["status"], "supported_direct_control")
        self.assertEqual(summary["executed_control_count"], 1)
        self.assertEqual(summary["pending_control_count"], 2)
        self.assertTrue(summary["active_replay_correction_intact"])
        self.assertTrue(summary["marker_removal_reduces_correction_survival"])
        self.assertLess(summary["mean_marker_removal_correction_survival_delta"], -0.03)
        for row in control["evidence"]:
            self.assertLess(row["marker_removal_correction_survival_delta"], -0.03)
            self.assertEqual(row["marker_removal_prompt_cost_delta"], 0.0)
            self.assertEqual(row["boundary_violation_delta"], 0.0)
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "marker_removal_supports_hippocampal_cls_replay_control",
        )
        self.assertTrue(report["evidence_gate"]["real_provider_trace"])
        self.assertTrue(report["evidence_gate"]["direct_controls_incomplete"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_rejects_surrogate_marker_controls(self) -> None:
        from holo_host.biomimetic_marker_control import build_biomimetic_marker_control

        report = build_biomimetic_marker_control(
            _stage78_theory_report(),
            [_provider_trace("synthetic", real_provider=False)],
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "marker_control_requires_real_provider_trace",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_cli_writes_stage80_artifacts(self) -> None:
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
            pro_path = root / "stage77_pro_trace.json"
            flash_path = root / "stage77_flash_trace.json"
            theory_path.write_text(json.dumps(_stage78_theory_report()), encoding="utf-8")
            pro_path.write_text(json.dumps(_provider_trace("deepseek-v4-pro")), encoding="utf-8")
            flash_path.write_text(json.dumps(_provider_trace("deepseek-v4-flash")), encoding="utf-8")
            output_path = root / "artifacts" / "stage80" / "marker_control.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-biomimetic-marker-control",
                        "--theory-json",
                        str(theory_path),
                        "--trace-json",
                        str(pro_path),
                        "--trace-json",
                        str(flash_path),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["marker_control_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage80-biomimetic-marker-removal-control")
        self.assertEqual(payload["observatory"]["executed_control_count"], 1)
        self.assertEqual(payload["observatory"]["pending_control_count"], 2)
        self.assertTrue(payload["observatory"]["marker_removal_reduces_correction_survival"])
        self.assertLess(payload["observatory"]["mean_marker_removal_correction_survival_delta"], -0.03)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
