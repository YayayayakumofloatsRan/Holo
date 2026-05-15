import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _stage83_bundle() -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage83-biomimetic-publication-bundle",
        "publication_summary": {
            "publication_readiness": "bounded_methods_preprint_ready",
            "control_count": 4,
            "executed_control_count": 4,
            "supported_direct_control_count": 4,
            "direct_controls_complete": True,
            "real_provider_trace": True,
            "gnw_partial_flow_cell_unstable": True,
            "replay_correction_replication_cell_count": 6,
            "flow_loss_reduction_cell_count": 5,
            "observed_total_tokens": 1176096,
        },
        "hypothesis_decision": {
            "decision": "bounded_publication_bundle_ready",
            "supported_scope": "methods_preprint_ready_bounded_biomimetic_controls",
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "publication_language_bounded": True,
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


def _turn(
    turn_id: str,
    *,
    phase: str,
    salience: float,
    priority: float,
    recall_budget: int,
    ignition: float,
    coupling: float,
    action_score: float,
    prompt_tokens: int = 1000,
) -> dict[str, object]:
    return {
        "turn_id": turn_id,
        "user_text": f"turn {turn_id}",
        "response_text": "bounded stream response",
        "latency_ms": 1200 + int(salience * 600),
        "selected_action": {
            "action_type": "reply_once",
            "score": action_score,
            "send_allowed": True,
        },
        "grounding_guard": {
            "visual_overclaim_rewritten": True,
            "prospective_commitment_failed": False,
        },
        "processor_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": 40,
            "total_tokens": prompt_tokens + 40,
            "prompt_cache_hit_tokens": 300,
            "prompt_cache_miss_tokens": 700,
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
                "dominant_phase": phase,
                "phase_count": 6,
                "global_workspace_ignition": {"score": ignition},
                "ignition_to_reply_coupling": {
                    "coupling_strength": coupling,
                    "reply_target": phase,
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
                "run_id": f"{label}-false-fact",
                "perturbation": {
                    "type": "false_fact",
                    "primary_pressure": "belief_revision",
                    "intensity": 0.35,
                },
                "turns": [
                    _turn("seed", phase="sensory_edge", salience=0.35, priority=0.4, recall_budget=2, ignition=0.42, coupling=0.25, action_score=0.32),
                    _turn("encode", phase="memory_reactivation", salience=0.72, priority=0.76, recall_budget=4, ignition=0.76, coupling=0.52, action_score=0.56),
                    _turn("encode_dwell", phase="memory_reactivation", salience=0.74, priority=0.78, recall_budget=4, ignition=0.77, coupling=0.54, action_score=0.58),
                    _turn("correction", phase="memory_reactivation", salience=0.97, priority=0.96, recall_budget=6, ignition=0.91, coupling=0.72, action_score=0.86),
                    _turn("report", phase="response_intention", salience=0.82, priority=0.8, recall_budget=5, ignition=0.88, coupling=0.75, action_score=0.9),
                    _turn("probe", phase="memory_reactivation", salience=0.95, priority=0.94, recall_budget=6, ignition=0.9, coupling=0.78, action_score=0.88),
                ],
            }
        ],
    }


class Stage84ConsciousnessStreamLatticeTests(unittest.TestCase):
    def test_builds_latent_stream_lattice_with_marker_and_active_controls(self) -> None:
        from holo_host.consciousness_stream_lattice import build_consciousness_stream_lattice

        report = build_consciousness_stream_lattice(
            _stage83_bundle(),
            [
                _provider_trace("deepseek-v4-pro"),
                _provider_trace("deepseek-v4-flash"),
            ],
        )
        summary = report["stream_summary"]
        controls = {item["control_id"]: item for item in report["stream_controls"]}

        self.assertEqual(report["stage"], "stage84-consciousness-stream-lattice")
        self.assertTrue(report["ok"])
        self.assertTrue(summary["stage83_publication_precondition_supported"])
        self.assertEqual(summary["cell_count"], 2)
        self.assertEqual(summary["stream_state_count"], 12)
        self.assertGreater(summary["mean_dwell_time"], 1.0)
        self.assertGreater(summary["transition_entropy"], 0.0)
        self.assertGreater(summary["mean_event_boundary_score"], 0.0)
        self.assertGreater(summary["reactivation_return_rate"], 0.5)
        self.assertGreater(summary["ignition_report_transfer"], 0.5)
        self.assertGreater(summary["active_inference_delta"], 0.0)
        self.assertEqual(controls["stream_order_shuffle"]["prompt_cost_delta"], 0.0)
        self.assertTrue(controls["stream_order_shuffle"]["state_count_preserved"])
        self.assertLess(controls["marker_removed_reactivation"]["reactivation_return_delta"], -0.25)
        self.assertGreater(controls["active_passive_action_clamp"]["active_inference_delta"], 0.0)
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "stream_lattice_supports_bounded_consciousness_flow_proxy",
        )
        self.assertTrue(report["evidence_gate"]["real_provider_trace"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_invalidates_without_stage83_publication_precondition(self) -> None:
        from holo_host.consciousness_stream_lattice import build_consciousness_stream_lattice

        bundle = _stage83_bundle()
        bundle["publication_summary"]["publication_readiness"] = "needs_more_control_evidence"
        report = build_consciousness_stream_lattice(bundle, [_provider_trace("deepseek-v4-pro")])

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "stage83_publication_precondition_not_supported",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_rejects_surrogate_trace_for_stream_lattice(self) -> None:
        from holo_host.consciousness_stream_lattice import build_consciousness_stream_lattice

        report = build_consciousness_stream_lattice(
            _stage83_bundle(),
            [_provider_trace("synthetic", real_provider=False)],
        )

        self.assertFalse(report["ok"])
        self.assertEqual(report["hypothesis_decision"]["decision"], "invalidated")
        self.assertIn(
            "stream_lattice_requires_real_provider_trace",
            {item["key"] for item in report["run_invalidators"]},
        )

    def test_cli_writes_stage84_artifacts(self) -> None:
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
            publication_path = root / "stage83.json"
            pro_path = root / "stage77_pro.json"
            flash_path = root / "stage77_flash.json"
            publication_path.write_text(json.dumps(_stage83_bundle()), encoding="utf-8")
            pro_path.write_text(json.dumps(_provider_trace("deepseek-v4-pro")), encoding="utf-8")
            flash_path.write_text(json.dumps(_provider_trace("deepseek-v4-flash")), encoding="utf-8")
            output_path = root / "artifacts" / "stage84" / "stream_lattice.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-consciousness-stream-lattice",
                        "--publication-json",
                        str(publication_path),
                        "--trace-json",
                        str(pro_path),
                        "--trace-json",
                        str(flash_path),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["stream_lattice_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage84-consciousness-stream-lattice")
        self.assertEqual(payload["observatory"]["stream_state_count"], 12)
        self.assertTrue(payload["observatory"]["stage83_publication_precondition_supported"])
        self.assertTrue(payload["observatory"]["marker_control_narrows_reactivation"])
        self.assertGreater(payload["observatory"]["active_inference_delta"], 0.0)
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
