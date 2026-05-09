from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel, BionicTurnRequest
from holo_host.config import load_config
from holo_host.store import QueueStore


class _DebtMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "active_thread",
            "continuity_summary": "Debt burn-down probe is using the unified subject loop.",
            "situational_field": {
                "modalities": ["text"],
                "grounding_order": ["query", "subject_loop"],
                "open_questions": [],
                "history_reliance": "low",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "action_market": [
                {"action_type": "reply_once", "score": 0.7, "reason": "answer the debt probe"},
                {"action_type": "silence", "score": 0.1, "reason": "not enough silence pressure"},
            ],
        }


class Stage31DebtBurndownTests(unittest.TestCase):
    def test_adapter_registry_contract_is_visible_and_interface_only(self) -> None:
        from holo_host.adapter_registry import adapter_registry

        cli = adapter_registry.resolve(adapter="cli", channel="cli")
        wechat = adapter_registry.resolve(adapter="wechat", channel="wechat")

        self.assertEqual(cli.name, "cli")
        self.assertEqual(wechat.name, "wechat")
        self.assertTrue(cli.transport_is_interface)
        self.assertTrue(wechat.transport_is_interface)
        self.assertFalse(cli.transport_decision_authority)
        self.assertFalse(wechat.transport_decision_authority)
        self.assertFalse(cli.uses_live_transport)
        self.assertFalse(wechat.uses_live_transport)

    def test_capsule_records_adapter_contract_and_state_gate_decision(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_DebtMemory(), runner=None)
            result = kernel.run_request(
                BionicTurnRequest(
                    query="show controlled state gate",
                    thread_key="cli:debt",
                    chat_name="Debt",
                    channel="cli",
                    adapter="cli",
                    record=True,
                )
            )

        capsule = result["capsule"]
        self.assertEqual(capsule["adapter_contract"]["adapter"], "cli")
        self.assertFalse(capsule["adapter_contract"]["transport_decision_authority"])
        state_update = capsule["subject_loop"]["state_update"]
        self.assertEqual(state_update["gate"], "controlled_state_update_gate")
        self.assertEqual(state_update["allowed_writes"], ["operational_trace"])
        self.assertEqual(state_update["rejected_writes"], [])
        self.assertTrue(state_update["rollback_supported"])

    def test_state_update_gate_rejects_forbidden_self_memory_write(self) -> None:
        from holo_host.subject_loop.state_update_gate import StateUpdateProposal, controlled_state_update_gate

        decision = controlled_state_update_gate.evaluate(
            record_requested=False,
            proposals=[
                StateUpdateProposal(
                    write_type="self_memory",
                    target="mind_graph",
                    reason="forbidden direct write",
                    payload={"unsafe": True},
                )
            ],
        )

        self.assertEqual(decision.allowed_writes, [])
        self.assertEqual(decision.rejected_writes, ["self_memory"])
        self.assertFalse(decision.self_memory_write)
        self.assertIn("self_memory", decision.rejection_reasons)

    def test_subject_loop_diagnostics_work_from_operational_traces(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(root / ".holo_runtime" / "holo_host.sqlite3")
            store.initialize()
            try:
                kernel = BionicKernel(config=config, store=store, memory=_DebtMemory(), runner=None)
                result = kernel.run_request(
                    BionicTurnRequest(
                        query="record trace for subject loop diagnostics",
                        thread_key="cli:diag",
                        chat_name="Diag",
                        channel="cli",
                        adapter="cli",
                        record=True,
                    )
                )
                trace_id = int(result["trace_id"])
                trace = store.trace_subject_loop(trace_id=trace_id)
                metrics = store.latest_subject_loop_metrics()
            finally:
                store.close()

        self.assertTrue(trace["ok"])
        self.assertEqual(trace["subject_loop"]["stage"], "stage30-unified-subject-loop")
        self.assertEqual(metrics["stage"], "stage31-debt-burndown")
        self.assertEqual(metrics["trace_count"], 1)
        self.assertEqual(metrics["invariant_pass_rate"], 1.0)

    def test_stage31_cli_commands_and_extracted_payload_helpers(self) -> None:
        from holo_host.cli_parts.bionic import accept_stage31_payload

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
""".strip(),
                encoding="utf-8",
            )
            payload, _transport = accept_stage31_payload(
                str(config_path),
                thread_key="cli:accept31",
                chat_name="Accept31",
                channel="cli",
            )
            cli_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage31",
                    "--thread-key",
                    "cli:accept31",
                    "--chat-name",
                    "Accept31",
                    "--channel",
                    "cli",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["adapter_registry_visible"])
        self.assertTrue(payload["checks"]["subject_loop_diagnostics_visible"])
        self.assertEqual(cli_result.returncode, 0, cli_result.stderr)
        self.assertTrue(json.loads(cli_result.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
