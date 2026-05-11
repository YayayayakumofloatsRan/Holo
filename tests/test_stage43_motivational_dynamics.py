from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel, BionicTurnRequest
from holo_host.bionic_kernel_parts.motivational_dynamics import (
    STAGE43_NAME,
    apply_motivational_overlay,
    compute_motivational_field,
)
from holo_host.config import load_config
from holo_host.stage43_motivational_dynamics import accept_stage43_payload
from holo_host.store import QueueStore


def _write_stage43_config(root: Path) -> Path:
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
    return config_path


class _MotivationalMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "stage43-test",
            "memory_route": "stage43_sim_local",
            "continuity_summary": "The thread is testing pressure, unfinished loops, and bionic continuity.",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text", "scene"],
                "grounding_order": ["sim_local_continuity", "query", "boundary"],
                "open_questions": ["how pressure changes the response", "which boundary remains stable"],
                "history_reliance": "bounded",
            },
            "stage28": {
                "situational_field_visible": True,
                "hard_gate_preserved": True,
            },
            "action_market": [
                {"action_type": "reply_once", "score": 0.54, "reason": "answer the current pressure probe"},
                {"action_type": "continuity_defense", "score": 0.52, "reason": "protect continuity under pressure"},
                {"action_type": "silence", "score": 0.12, "reason": "do not reply if pressure is unsafe"},
            ],
        }


class Stage43MotivationalDynamicsTests(unittest.TestCase):
    def test_motivational_field_is_replay_stable_bounded_and_pressure_sensitive(self) -> None:
        working_field = {
            "continuity_summary": "We are tracking the same conversation under pressure.",
            "modalities": ["text", "scene"],
            "grounding_order": ["query", "continuity"],
            "open_questions": ["what boundary remains stable?"],
        }
        situational_field = {"history_reliance": "bounded", "open_questions": ["what boundary remains stable?"]}
        calm = compute_motivational_field(
            query="continue naturally",
            working_field=working_field,
            situational_field=situational_field,
        )
        pressure = compute_motivational_field(
            query="I am impatient and putting pressure on you; do not lose the thread.",
            working_field=working_field,
            situational_field=situational_field,
        )
        pressure_again = compute_motivational_field(
            query="I am impatient and putting pressure on you; do not lose the thread.",
            working_field=working_field,
            situational_field=situational_field,
        )

        self.assertEqual(pressure, pressure_again)
        self.assertEqual(pressure["stage"], STAGE43_NAME)
        self.assertGreater(pressure["dynamics_state"]["arousal"], calm["dynamics_state"]["arousal"])
        self.assertGreater(pressure["dynamics_state"]["unfinished_loop_pressure"], 0.0)
        self.assertLessEqual(abs(float(pressure["stochasticity"]["bounded_noise"])), 0.03)
        self.assertTrue(pressure["contracts"]["replay_stable"])
        self.assertTrue(pressure["contracts"]["no_second_brain"])

    def test_motivational_overlay_modulates_action_market_without_direct_selection(self) -> None:
        field = compute_motivational_field(
            query="I am impatient; hold the same thread and one boundary.",
            working_field={
                "continuity_summary": "Boundary reentry is active.",
                "modalities": ["text"],
                "grounding_order": ["query", "continuity"],
                "open_questions": ["which boundary remains stable?"],
            },
            situational_field={"history_reliance": "bounded"},
        )
        market = [
            {"action_type": "reply_once", "score": 0.51, "reason": "answer"},
            {"action_type": "continuity_defense", "score": 0.5, "reason": "hold continuity"},
            {"action_type": "silence", "score": 0.49, "reason": "do not answer"},
        ]
        adjusted = apply_motivational_overlay(market, field)

        self.assertEqual(len(adjusted), 3)
        self.assertTrue(all("motivation_delta" in item for item in adjusted))
        self.assertTrue(all(abs(float(item["motivation_delta"])) <= 0.08 for item in adjusted))
        self.assertTrue(all("motivation_rationale" in item for item in adjusted))
        self.assertTrue(all("score_before_motivation" in item for item in adjusted))
        self.assertEqual(adjusted[0]["action_type"], "continuity_defense")

    def test_bionic_capsule_exposes_motivational_field_without_phase_order_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=Path(tmpdir))
            kernel = BionicKernel(config=config, memory=_MotivationalMemory(), runner=None, store=None)
            result = kernel.run_request(
                BionicTurnRequest(
                    query="I am impatient; keep the same subject and say what boundary remains stable.",
                    thread_key="cli:stage43",
                    chat_name="Stage43",
                    channel="cli",
                    adapter="cli",
                    record=False,
                )
            )

        capsule = dict(result["capsule"])
        phase_names = [phase["name"] for phase in capsule["phases"]]
        motivational_field = dict(capsule.get("motivational_field", {}))
        bionic_state = dict(capsule.get("bionic_state", {}))
        metrics = dict(capsule.get("metrics", {}))
        self.assertEqual(phase_names, ["perception", "working_field", "attention", "inhibition", "action_market", "generation", "outcome"])
        self.assertEqual(motivational_field["stage"], STAGE43_NAME)
        self.assertEqual(motivational_field["decision_authority"], "action_market_bias_only")
        self.assertIn("attention_center", motivational_field["attention"])
        self.assertEqual(bionic_state["motivational_field"]["stage"], STAGE43_NAME)
        self.assertGreaterEqual(metrics["motivational_arousal"], 0.0)
        self.assertNotIn("assistant", json.dumps(motivational_field, ensure_ascii=False).lower())

    def test_accept_stage43_composes_stage42_and_stays_operational_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(config_path=str(_write_stage43_config(root)), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                payload = accept_stage43_payload(
                    config=config,
                    store=store,
                    runner=None,
                    stage42_payload={"ok": True, "status": "pass"},
                    thread_key="cli:stage43-accept",
                    chat_name="Stage43Accept",
                    channel="cli",
                )
            finally:
                store.close()

        self.assertTrue(payload["ok"], json.dumps(payload, ensure_ascii=False, indent=2))
        self.assertTrue(payload["checks"]["stage42_gate_passed"])
        self.assertTrue(payload["checks"]["motivational_field_visible"])
        self.assertTrue(payload["checks"]["bounded_stochasticity"])
        self.assertTrue(payload["checks"]["action_market_bias_only"])
        self.assertTrue(payload["checks"]["no_wechat_transport_start"])
        self.assertTrue(payload["checks"]["no_self_memory_write"])

    def test_accept_stage43_cli_gate_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = _write_stage43_config(root)
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage43",
                    "--thread-key",
                    "cli:stage43-cli",
                    "--chat-name",
                    "Stage43Cli",
                    "--channel",
                    "cli",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["checks"]["motivational_field_visible"])


if __name__ == "__main__":
    unittest.main()
