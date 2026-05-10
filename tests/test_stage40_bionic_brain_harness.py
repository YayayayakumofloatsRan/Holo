from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_brain import BionicBrainHarness, STAGE40_PHASES
from holo_host.config import load_config
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


def _write_stage40_config(root: Path) -> Path:
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
api_port = 65511

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
max_output_tokens = 512

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 256
""".strip(),
        encoding="utf-8",
    )
    return config_path


class _Stage40Memory:
    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        return {
            "tier": "stage40-local",
            "memory_route": "stage40_probe",
            "continuity_summary": "The repo is in CLI-only internal agent mode.",
            "stage24": {"scene_state": {"shared_frame": "Stage40 harness implementation"}},
            "stage25": {"dense_working_set_visible": True, "reentry_hint": "finish harness"},
            "stage26": {"task_world_visible": True, "object_ids": ["obj-stage40"]},
            "action_market": [
                {"action_type": "reply_once", "score": 0.8, "reason": "continue implementation"},
                {"action_type": "silence", "score": 0.05, "reason": "not useful"},
            ],
        }


class _ScriptedRunner:
    def __init__(self, actions: list[dict] | None = None) -> None:
        self.actions = actions or [{"tool": "inspect_repo_status", "mutation_class": "read_only"}]
        self.requests: list[dict] = []

    def run_task(self, request):
        self.requests.append(request.to_dict())
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=json.dumps(
                {
                    "summary": "plan one bounded tool step",
                    "actions": self.actions,
                    "done": True,
                    "verification": "tool output must be checked before completion",
                },
                ensure_ascii=False,
            ),
            returncode=0,
            output_schema="json",
            metadata={"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "kernel_xhigh"},
        )


class Stage40BionicBrainHarnessTests(unittest.TestCase):
    def _harness(self, root: Path, runner: _ScriptedRunner | None = None) -> tuple[BionicBrainHarness, QueueStore]:
        config = load_config(config_path=str(_write_stage40_config(root)), repo_root=root)
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        harness = BionicBrainHarness(
            config=config,
            store=store,
            memory=_Stage40Memory(),
            runner=runner or _ScriptedRunner(),
        )
        return harness, store

    def test_brain_loop_records_full_phase_trace_and_uses_action_market_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "AGENTS.md").write_text("public contract", encoding="utf-8")
            harness, store = self._harness(root, _ScriptedRunner())
            try:
                result = harness.run(
                    goal="inspect current repo state",
                    thread_key="cli:stage40",
                    chat_name="Stage40",
                    channel="cli",
                    offline=False,
                    max_steps=2,
                )
                persisted = store.get_bionic_brain_run(run_id=int(result["run_id"]))
            finally:
                store.close()

        phase_names = [entry["phase"] for entry in result["phase_trace"]]
        for phase in STAGE40_PHASES:
            self.assertIn(phase, phase_names)
        self.assertLess(phase_names.index("action_market"), phase_names.index("tool_loop"))
        self.assertTrue(result["action_market"]["gate_applied"])
        self.assertEqual(result["steps"][0]["tool_loop"]["actions"][0]["gate"]["allowed"], True)
        self.assertEqual(persisted["run_id"], result["run_id"])
        self.assertEqual(persisted["status"], "completed")

    def test_repo_write_is_denied_by_default_and_hard_step_cap_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            harness, store = self._harness(
                root,
                _ScriptedRunner(actions=[{"tool": "edit_file", "mutation_class": "repo_write"}]),
            )
            try:
                result = harness.run(
                    goal="try to edit the repo",
                    thread_key="cli:stage40-deny",
                    chat_name="Stage40",
                    channel="cli",
                    offline=False,
                    max_steps=999,
                )
            finally:
                store.close()

        denied = result["steps"][0]["tool_loop"]["actions"][0]
        self.assertEqual(result["max_steps_effective"], 20)
        self.assertFalse(denied["gate"]["allowed"])
        self.assertEqual(denied["gate"]["reason"], "repo_write_requires_explicit_user_authority")
        self.assertFalse(result["consolidation_intent"]["self_memory_write"])


if __name__ == "__main__":
    unittest.main()
