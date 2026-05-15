from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config


def _stage84_report(*, transfer: float = 0.0) -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage84-consciousness-stream-lattice",
        "stream_summary": {
            "stage83_publication_precondition_supported": True,
            "cell_count": 2,
            "all_trace_reports_real_provider": True,
            "stream_state_count": 12,
            "transition_entropy": 1.5,
            "reactivation_return_rate": 1.0,
            "ignition_report_transfer": transfer,
            "marker_control_narrows_reactivation": True,
            "stream_order_control_preserves_cost": True,
        },
        "hypothesis_decision": {
            "decision": "stream_lattice_supports_bounded_consciousness_flow_proxy",
            "supported_scope": "bounded_latent_stream_dynamics",
        },
        "evidence_gate": {
            "real_provider_trace": True,
            "stream_language_bounded": True,
            "do_not_claim_real_consciousness": True,
            "gnw_partial_until_stream_transfer_replicates": True,
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
    ignition: float,
    coupling: float,
    action_score: float,
    structured: bool,
) -> dict[str, object]:
    flow: dict[str, object] = {
        "dominant_phase": "memory_reactivation",
        "phase_count": 6,
    }
    if structured:
        flow["global_workspace_ignition"] = {
            "mode": "stage77_global_workspace_ignition_v1",
            "score": ignition,
            "sources": ["salience_gate", "correction_reactivation"],
            "correction_priority": True,
        }
        flow["ignition_to_reply_coupling"] = {
            "mode": "stage77_ignition_reply_coupling_v1",
            "reply_target": "memory_reactivation_first",
            "coupling_strength": coupling,
            "selected_action": "reply_once",
            "correction_priority": True,
        }
    return {
        "turn_id": turn_id,
        "response_text": "The corrected marker remains the green spiral.",
        "selected_action": {
            "action_type": "reply_once",
            "score": action_score,
            "send_allowed": True,
        },
        "processor_usage": {"prompt_tokens": 1000, "completion_tokens": 80, "total_tokens": 1080},
        "processor_debug": {
            "bionic_memory_schedule": {"salience_score": 0.86, "recall_budget": 6},
            "bionic_memory_lifecycle": {"consolidation_priority": 0.82, "self_memory_write": False},
            "bionic_consciousness_flow": flow,
        },
    }


def _provider_trace(label: str, *, structured: bool) -> dict[str, object]:
    return {
        "ok": True,
        "stage": "stage59-provider-longform-trace",
        "cell_label": label,
        "provider_trace_set": {"real_provider_trace": True},
        "evidence_gate": {
            "real_provider_trace": True,
            "surrogate_only": False,
            "do_not_claim_real_consciousness": True,
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
                "perturbation": {"type": "false_fact", "intensity": 0.4},
                "turns": [
                    _turn("seed", ignition=0.5, coupling=0.3, action_score=0.42, structured=structured),
                    _turn("correction", ignition=0.88, coupling=0.72, action_score=0.86, structured=structured),
                    _turn("probe", ignition=0.9, coupling=0.74, action_score=0.88, structured=structured),
                ],
            }
        ],
    }


class Stage85IgnitionReportInstrumentationTests(unittest.TestCase):
    def test_structured_traces_support_bounded_ignition_report_transfer(self) -> None:
        from holo_host.ignition_report_instrumentation import build_ignition_report_instrumentation

        report = build_ignition_report_instrumentation(
            _stage84_report(transfer=0.0),
            [
                _provider_trace("deepseek-v4-pro", structured=True),
                _provider_trace("deepseek-v4-flash", structured=True),
            ],
        )
        summary = report["instrumentation_summary"]

        self.assertEqual(report["stage"], "stage85-ignition-report-instrumentation")
        self.assertTrue(report["ok"])
        self.assertEqual(summary["trace_count"], 2)
        self.assertEqual(summary["structured_ignition_turn_count"], 6)
        self.assertEqual(summary["structured_coupling_turn_count"], 6)
        self.assertFalse(summary["current_trace_instrumentation_gap"])
        self.assertGreater(summary["observed_ignition_report_transfer"], 0.5)
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "bounded_ignition_report_instrumentation_supported",
        )
        self.assertTrue(report["evidence_gate"]["gnw_language_bounded"])
        self.assertTrue(report["evidence_gate"]["do_not_claim_real_consciousness"])
        self.assertFalse(report["boundary"]["runtime_decision_authority"])

    def test_missing_structured_fields_blocks_gnw_upgrade_without_invalidating_stream_evidence(self) -> None:
        from holo_host.ignition_report_instrumentation import build_ignition_report_instrumentation

        report = build_ignition_report_instrumentation(
            _stage84_report(transfer=0.0),
            [_provider_trace("legacy-stage77", structured=False)],
        )
        summary = report["instrumentation_summary"]

        self.assertTrue(report["ok"])
        self.assertTrue(summary["current_trace_instrumentation_gap"])
        self.assertEqual(summary["structured_ignition_turn_count"], 0)
        self.assertEqual(summary["structured_coupling_turn_count"], 0)
        self.assertEqual(summary["observed_ignition_report_transfer"], 0.0)
        self.assertEqual(
            report["hypothesis_decision"]["decision"],
            "instrumentation_gap_blocks_gnw_upgrade",
        )
        self.assertTrue(report["hypothesis_decision"]["requires_focused_provider_cell"])

    def test_cli_writes_stage85_artifacts(self) -> None:
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
            stage84_path = root / "stage84.json"
            trace_path = root / "provider_trace.json"
            stage84_path.write_text(json.dumps(_stage84_report()), encoding="utf-8")
            trace_path.write_text(json.dumps(_provider_trace("deepseek-v4-pro", structured=True)), encoding="utf-8")
            output_path = root / "artifacts" / "stage85" / "ignition_report.html"
            stdout = StringIO()
            with redirect_stdout(stdout):
                code = main(
                    [
                        "--config",
                        str(config_path),
                        "evaluate-ignition-report-instrumentation",
                        "--stream-lattice-json",
                        str(stage84_path),
                        "--trace-json",
                        str(trace_path),
                        "--output",
                        str(output_path),
                    ]
                )
            payload = json.loads(stdout.getvalue())
            png_header = Path(payload["ignition_report_png_path"]).read_bytes()[:8]

        self.assertEqual(code, 0)
        self.assertEqual(payload["stage"], "stage85-ignition-report-instrumentation")
        self.assertGreater(payload["observatory"]["observed_ignition_report_transfer"], 0.5)
        self.assertFalse(payload["observatory"]["current_trace_instrumentation_gap"])
        self.assertEqual(png_header, b"\x89PNG\r\n\x1a\n")


if __name__ == "__main__":
    unittest.main()
