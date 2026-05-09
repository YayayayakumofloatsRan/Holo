from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel, BionicTurnRequest
from holo_host.config import load_config


class _LoopMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "active_thread",
            "continuity_summary": "The subject is validating a unified bionic loop.",
            "situational_field": {
                "modalities": ["text", "scene"],
                "grounding_order": ["query", "scene_state", "action_market"],
                "open_questions": ["does the loop close cleanly?"],
                "history_reliance": "low",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {"action_type": "reply_once", "score": 0.8, "reason": "answer the loop probe"},
                {"action_type": "silence", "score": 0.1, "reason": "weak non-reply pressure"},
            ],
        }


class Stage30SubjectLoopTests(unittest.TestCase):
    def test_bionic_capsule_contains_unified_subject_loop_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_LoopMemory(), runner=None)

            result = kernel.run_request(
                BionicTurnRequest(
                    query="validate the subject loop",
                    thread_key="cli:stage30",
                    chat_name="Stage30",
                    channel="cli",
                    adapter="cli",
                    record=False,
                )
            )

        subject_loop = result["capsule"]["subject_loop"]
        self.assertEqual(subject_loop["stage"], "stage30-unified-subject-loop")
        self.assertEqual(subject_loop["loop_name"], "unified_bionic_subject_loop")
        self.assertEqual(
            subject_loop["phase_order"],
            [
                "perception",
                "working_field",
                "attention",
                "inhibition",
                "action_market",
                "generation",
                "outcome_appraisal",
                "state_update",
            ],
        )
        self.assertTrue(all(subject_loop["invariants"].values()))
        self.assertEqual(subject_loop["outcome_appraisal"]["selected_action"], "reply_once")
        self.assertEqual(subject_loop["outcome_appraisal"]["transport_side_effect"], False)
        self.assertEqual(subject_loop["state_update"]["self_memory_write"], False)
        self.assertEqual(subject_loop["state_update"]["policy_write"], False)
        self.assertEqual(subject_loop["state_update"]["mind_graph_write"], False)
        self.assertEqual(subject_loop["state_update"]["allowed_writes"], [])

    def test_recorded_turn_allows_only_operational_trace_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_LoopMemory(), runner=None)

            result = kernel.run_request(
                BionicTurnRequest(
                    query="record but do not mutate self memory",
                    thread_key="cli:stage30-record",
                    chat_name="Stage30",
                    channel="cli",
                    adapter="cli",
                    record=True,
                )
            )

        state_update = result["capsule"]["subject_loop"]["state_update"]
        self.assertEqual(state_update["allowed_writes"], ["operational_trace"])
        self.assertEqual(state_update["operational_storage_only"], True)

    def test_accept_stage30_cli_gate_passes(self) -> None:
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
                    "accept-stage30",
                    "--thread-key",
                    "cli:accept30",
                    "--chat-name",
                    "Accept30",
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
        self.assertTrue(payload["checks"]["stage29_gate_passed"])
        self.assertTrue(payload["checks"]["subject_loop_visible"])
        self.assertTrue(payload["checks"]["hard_invariants_pass"])
        self.assertTrue(payload["checks"]["state_update_bounded"])


if __name__ == "__main__":
    unittest.main()
