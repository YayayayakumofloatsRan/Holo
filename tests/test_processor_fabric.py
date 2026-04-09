from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from holo_host.config import load_config
from holo_host.codex_runner import CodexRunner
from holo_host.models import ProcessorTaskRequest, ProcessorUsageRecord
from holo_host.store import QueueStore


class ProcessorFabricConfigTests(unittest.TestCase):
    def test_load_config_supports_processor_fabric_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
codex_model = "gpt-5.4"
fast_model = "gpt-5.4-mini"

[processor_fabric]
openai_compatible_base_url = "http://localhost:1234/v1"
openai_compatible_api_key_env = "TEST_COMPAT_KEY"

[provider_backends.micro_fast]
primary_provider = "openai_compatible"
backup_provider = "responses"
model = "gpt-5.4-mini"
reasoning_effort = "low"
max_output_tokens = 512

[processor_routing.reply]
lane = "kernel_xhigh"
fallback_lane = "subject_main"
budget_tag = "reply_override"
upgrade_to_lane = "kernel_xhigh"
uncertainty_threshold = 0.9
high_conflict_actions = ["push_back"]
""".strip(),
                encoding="utf-8",
            )

            config = load_config(str(config_path), repo_root=root)

            self.assertEqual(config.processor_fabric.openai_compatible_base_url, "http://localhost:1234/v1")
            self.assertEqual(config.processor_fabric.provider_backends["micro_fast"].primary_provider, "openai_compatible")
            self.assertEqual(config.processor_fabric.provider_backends["micro_fast"].max_output_tokens, 512)
            self.assertEqual(config.processor_fabric.processor_routing["reply"].lane, "kernel_xhigh")
            self.assertEqual(config.processor_fabric.processor_routing["reply"].budget_tag, "reply_override")


class ProcessorUsageLedgerTests(unittest.TestCase):
    def test_queue_store_round_trips_processor_usage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = QueueStore(Path(tmpdir) / "holo_host.sqlite3")
            store.initialize()
            try:
                record = store.record_processor_usage(
                    ProcessorUsageRecord(
                        task_type="reply",
                        lane="subject_main",
                        provider="codex_cli",
                        model="gpt-5.4",
                        reasoning_effort="medium",
                        thread_key="Nemoqi",
                        event_id="evt-1",
                        duration_ms=321,
                        prompt_tokens=100,
                        completion_tokens=25,
                        total_tokens=125,
                        estimated=False,
                        status="ok",
                        metadata={"budget_tag": "chat_reply"},
                    )
                )
                self.assertEqual(record["task_type"], "reply")
                rows = store.list_processor_usage(limit=5, lane="subject_main")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["provider"], "codex_cli")
                self.assertEqual(rows[0]["total_tokens"], 125)
                self.assertEqual(json.loads(rows[0]["metadata_json"])["budget_tag"], "chat_reply")
            finally:
                store.close()


class CodexRunnerRoutingTests(unittest.TestCase):
    def test_describe_task_dispatch_uses_expected_default_lanes(self) -> None:
        config = load_config(repo_root=Path(__file__).resolve().parents[1])
        runner = CodexRunner(config)

        reply_dispatch = runner.describe_task_dispatch(
            ProcessorTaskRequest(
                task_type="reply",
                prompt="hello",
                metadata={"selected_action_type": "reply_once", "uncertainty_level": 0.12},
            )
        )
        probe_dispatch = runner.describe_task_dispatch(
            ProcessorTaskRequest(task_type="initiative_probe", prompt="probe")
        )
        deep_dispatch = runner.describe_task_dispatch(
            ProcessorTaskRequest(task_type="deep_simulation", prompt="simulate")
        )

        self.assertEqual(reply_dispatch["lane"], "subject_main")
        self.assertEqual(probe_dispatch["lane"], "micro_fast")
        self.assertEqual(deep_dispatch["lane"], "kernel_xhigh")

    def test_reply_dispatch_upgrades_high_conflict_to_kernel_lane(self) -> None:
        config = load_config(repo_root=Path(__file__).resolve().parents[1])
        runner = CodexRunner(config)

        dispatch = runner.describe_task_dispatch(
            ProcessorTaskRequest(
                task_type="reply",
                prompt="push back",
                metadata={"selected_action_type": "push_back", "uncertainty_level": 0.88},
            )
        )

        self.assertEqual(dispatch["lane"], "kernel_xhigh")
        self.assertIn("codex_cli", dispatch["providers"])
