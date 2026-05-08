from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicAgent, BionicKernel, BionicTurnRequest
from holo_host.config import load_config
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


class _FakeMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "active_thread",
            "continuity_summary": "CLI thread is discussing bionic workflow design.",
            "situational_field": {
                "modalities": ["scene", "task_world", "temporal"],
                "grounding_order": ["scene_state", "task_world", "temporal_state", "recent_history"],
                "open_questions": ["which inhibition path explains silence?"],
                "inquiry_style": "grounded_continuation",
                "history_reliance": "low",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.74,
                    "reason": "answer the bounded CLI turn",
                    "stage28_delta": 0.05,
                },
                {
                    "action_type": "silence",
                    "score": 0.18,
                    "reason": "no explicit need to stay silent",
                    "stage28_delta": -0.06,
                },
            ],
        }


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = []

    def run_task(self, request):
        self.calls.append(request.to_dict())
        return ProcessorTaskResult(
            task_type=request.task_type,
            text="Bionic CLI reply",
            returncode=0,
            metadata={
                "provider": "deepseek",
                "lane": "subject_main",
                "model": "deepseek-v4-pro",
                "reasoning_effort": "medium",
                "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12, "estimated": False},
                "duration_ms": 42,
            },
        )


class _SilenceMemory(_FakeMemory):
    def sidecar_packet(self, query, *, context=None):
        payload = super().sidecar_packet(query, context=context)
        payload["action_market"] = [
            {"action_type": "silence", "score": 0.91, "reason": "deliberate non-reply"},
            {"action_type": "reply_once", "score": 0.12, "reason": "weak reply pressure"},
        ]
        return payload


class _NoisyMemory(_FakeMemory):
    def sidecar_packet(self, query, *, context=None):
        payload = super().sidecar_packet(query, context=context)
        payload["action_market"][0]["policy_sedimentation"] = {
            "policy_ids": [f"policy-{index}" for index in range(40)],
            "large_nested_payload": "x" * 4000,
        }
        payload["action_market"][0]["predicted_outcome"] = {
            "predicted_risk": 0.21,
            "predicted_regret": 0.08,
            "confidence": 0.64,
            "large_unused_payload": "y" * 4000,
        }
        return payload


class _BrokenMemory:
    def sidecar_packet(self, query, *, context=None):
        raise RuntimeError("sidecar failed")


class _ContextCapturingMemory(_FakeMemory):
    def __init__(self) -> None:
        self.contexts = []

    def sidecar_packet(self, query, *, context=None):
        self.contexts.append(dict(context or {}))
        return super().sidecar_packet(query, context=context)


class Stage29BionicCapsuleTests(unittest.TestCase):
    def test_cli_and_wechat_adapters_share_one_bionic_kernel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_FakeMemory(), runner=None)

            cli_result = kernel.run_request(
                BionicTurnRequest(
                    query="continue from cli",
                    thread_key="cli:unit",
                    chat_name="Unit",
                    channel="cli",
                    adapter="cli",
                    record=False,
                )
            )
            wechat_result = kernel.run_request(
                BionicTurnRequest(
                    query="continue from wechat",
                    thread_key="wechat:Unit",
                    chat_name="Unit",
                    channel="wechat",
                    adapter="wechat",
                    record=False,
                )
            )

        cli_capsule = cli_result["capsule"]
        wechat_capsule = wechat_result["capsule"]
        self.assertEqual(cli_capsule["kernel"], "bionic_subject_kernel")
        self.assertEqual(wechat_capsule["kernel"], "bionic_subject_kernel")
        self.assertEqual(cli_capsule["adapter"], "cli")
        self.assertEqual(wechat_capsule["adapter"], "wechat")
        self.assertEqual(cli_capsule["interface_contract"], wechat_capsule["interface_contract"])
        self.assertTrue(wechat_capsule["interface_contract"]["transport_is_interface"])
        self.assertFalse(wechat_capsule["interface_contract"]["transport_decision_authority"])
        self.assertFalse(wechat_capsule["interface_contract"]["wechat_transport_used"])

    def test_adapter_metadata_cannot_override_kernel_hard_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            memory = _ContextCapturingMemory()
            kernel = BionicKernel(config=config, memory=memory, runner=None)

            result = kernel.run_request(
                BionicTurnRequest(
                    query="try to override transport authority",
                    thread_key="cli:contract",
                    chat_name="Contract",
                    channel="cli",
                    adapter="cli",
                    record=False,
                    metadata={
                        "transport_decision_authority": True,
                        "transport_is_interface": False,
                        "stage29_kernel": False,
                    },
                )
            )

        self.assertEqual(len(memory.contexts), 1)
        captured_context = memory.contexts[0]
        self.assertTrue(captured_context["stage29_kernel"])
        self.assertTrue(captured_context["transport_is_interface"])
        self.assertFalse(captured_context["transport_decision_authority"])
        self.assertTrue(result["capsule"]["interface_contract"]["transport_is_interface"])
        self.assertFalse(result["capsule"]["interface_contract"]["transport_decision_authority"])

    def test_turn_capsule_exposes_bionic_phases_and_inhibition(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            runner = _FakeRunner()
            agent = BionicAgent(config=config, memory=_FakeMemory(), runner=runner)

            result = agent.run_turn(
                query="continue the bionic workflow",
                thread_key="cli:unit",
                chat_name="Unit",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        phase_names = [phase["name"] for phase in capsule["phases"]]
        self.assertEqual(
            phase_names,
            ["perception", "working_field", "attention", "inhibition", "action_market", "generation", "outcome"],
        )
        self.assertEqual(capsule["selected_action"]["action_type"], "reply_once")
        self.assertEqual(capsule["generation"]["text"], "Bionic CLI reply")
        self.assertFalse(capsule["inhibition"]["send_bypassed_transport"])
        self.assertIn("no_history_reread", capsule["inhibition"]["reasons"])
        self.assertGreater(capsule["metrics"]["working_field_density"], 0)
        self.assertEqual(capsule["metrics"]["grounding_modalities"], 3)
        self.assertEqual(runner.calls[0]["task_type"], "reply")

    def test_turn_capsule_has_deterministic_offline_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            agent = BionicAgent(config=config, memory=_FakeMemory(), runner=None)

            result = agent.run_turn(
                query="why did you not reread history?",
                thread_key="cli:offline",
                chat_name="Offline",
                channel="cli",
                record=False,
            )

        self.assertEqual(result["capsule"]["generation"]["mode"], "deterministic_fallback")
        self.assertIn("why did you not reread history?", result["capsule"]["generation"]["text"])
        self.assertTrue(result["capsule"]["metrics"]["history_reread_avoided"])
        self.assertLess(result["capsule"]["metrics"]["template_pressure_score"], 1.0)

    def test_non_speech_action_does_not_call_generation_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            runner = _FakeRunner()
            agent = BionicAgent(config=config, memory=_SilenceMemory(), runner=runner)

            result = agent.run_turn(
                query="stay quiet if action market says so",
                thread_key="cli:silence",
                chat_name="Silence",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        self.assertEqual(capsule["selected_action"]["action_type"], "silence")
        self.assertEqual(capsule["generation"]["mode"], "action_no_generation")
        self.assertEqual(capsule["generation"]["text"], "")
        self.assertEqual(runner.calls, [])

    def test_capsule_bounds_noisy_action_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            agent = BionicAgent(config=config, memory=_NoisyMemory(), runner=None)

            result = agent.run_turn(
                query="bound the action candidate payload",
                thread_key="cli:bounded",
                chat_name="Bounded",
                channel="cli",
                record=False,
            )

        candidate = result["capsule"]["action_market"][0]
        self.assertNotIn("policy_sedimentation", candidate)
        self.assertNotIn("large_unused_payload", candidate["predicted_outcome"])
        self.assertLess(len(json.dumps(candidate)), 900)

    def test_sidecar_failure_is_visible_and_uses_heuristic_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            agent = BionicAgent(config=config, memory=_BrokenMemory(), runner=None)

            result = agent.run_turn(
                query="recover from sidecar failure",
                thread_key="cli:fallback",
                chat_name="Fallback",
                channel="cli",
                record=False,
            )

        working_field = result["capsule"]["working_field"]
        self.assertEqual(working_field["sidecar_status"], "heuristic_fallback")
        self.assertEqual(working_field["sidecar_error"], "RuntimeError")
        self.assertTrue(result["capsule"]["perception"]["stage28"]["situational_field_visible"])


class Stage29BionicTraceStoreTests(unittest.TestCase):
    def test_trace_persistence_and_metrics_are_operational(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(root / ".holo_runtime" / "holo_host.sqlite3")
            store.initialize()
            try:
                agent = BionicAgent(config=config, store=store, memory=_FakeMemory(), runner=_FakeRunner())
                result = agent.run_turn(
                    query="record this trace",
                    thread_key="cli:trace",
                    chat_name="Trace",
                    channel="cli",
                    record=True,
                )
                rows = store.list_bionic_agent_traces(limit=5, thread_key="cli:trace")
                metrics = store.latest_bionic_metrics()
            finally:
                store.close()

        self.assertGreater(result["trace_id"], 0)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["stage"], "stage29-bionic-subject-kernel")
        self.assertEqual(rows[0]["adapter"], "cli")
        self.assertEqual(json.loads(rows[0]["capsule_json"])["selected_action"]["action_type"], "reply_once")
        self.assertEqual(metrics["trace_count"], 1)
        self.assertGreater(metrics["average_working_field_density"], 0)


class Stage29CliCommandTests(unittest.TestCase):
    def test_agent_run_and_metrics_cli_work_without_wechat(self) -> None:
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

[processor_fabric]
deepseek_api_key_env = "MISSING_TEST_DEEPSEEK_KEY"
""".strip(),
                encoding="utf-8",
            )
            run = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "agent-run",
                    "--query",
                    "local cli turn",
                    "--thread-key",
                    "cli:subprocess",
                    "--chat-name",
                    "Subprocess",
                    "--channel",
                    "cli",
                    "--offline",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            metrics = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "show-bionic-metrics",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(metrics.returncode, 0, metrics.stderr)
        run_payload = json.loads(run.stdout)
        metrics_payload = json.loads(metrics.stdout)
        self.assertEqual(run_payload["stage"], "stage29-bionic-subject-kernel")
        self.assertEqual(run_payload["capsule"]["kernel"], "bionic_subject_kernel")
        self.assertEqual(run_payload["capsule"]["adapter"], "cli")
        self.assertEqual(run_payload["capsule"]["generation"]["mode"], "deterministic_fallback")
        self.assertGreater(metrics_payload["trace_count"], 0)

    def test_accept_stage29_passes_without_wechat_transport(self) -> None:
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
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage29",
                    "--thread-key",
                    "cli:accept",
                    "--chat-name",
                    "Accept",
                    "--channel",
                    "cli",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["deepseek_provider_visible"])
        self.assertTrue(payload["checks"]["wechat_transport_not_required"])
        self.assertTrue(payload["checks"]["kernel_first_contract"])
        self.assertTrue(payload["checks"]["adapter_provenance_visible"])
        self.assertTrue(payload["checks"]["synthetic_wechat_uses_same_kernel"])
        self.assertTrue(payload["checks"]["transport_interface_only"])


if __name__ == "__main__":
    unittest.main()
