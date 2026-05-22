from __future__ import annotations

import json
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from holo_host.config import load_config
from holo_host.codex_runner import CodexRunner, DeepSeekProvider, ProcessorProvider
from holo_host.models import ProcessorTaskRequest, ProcessorTaskResult, ProcessorUsageRecord
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
                        thread_key="TestUser",
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
    def test_failed_provider_result_keeps_primary_and_fallback_errors(self) -> None:
        class FailingProvider(ProcessorProvider):
            name = "deepseek"

            def run_task(self, *args, **kwargs) -> ProcessorTaskResult:  # type: ignore[no-untyped-def]
                raise RuntimeError("DeepSeek HTTP 400: reasoning_content missing")

        class UnavailableProvider(ProcessorProvider):
            name = "openai_compatible"

            def availability(self) -> dict[str, object]:
                return {"available": False, "reason": "openai package not installed"}

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.processor_backend = "deepseek"
            config.processor_fabric.provider_backends["micro_fast"].primary_provider = "deepseek"
            config.processor_fabric.provider_backends["micro_fast"].backup_provider = "openai_compatible"
            runner = CodexRunner(config)
            runner._providers = {"deepseek": FailingProvider(), "openai_compatible": UnavailableProvider()}

            result = runner.run_task(ProcessorTaskRequest(task_type="reply", prompt="hello", lane="micro_fast"))

            self.assertEqual(result.returncode, 1)
            self.assertIn("deepseek: DeepSeek HTTP 400: reasoning_content missing", result.stderr)
            self.assertIn("openai_compatible: openai package not installed", result.stderr)

    def test_deepseek_backend_dispatch_does_not_append_codex_tail(self) -> None:
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
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)

            dispatch = runner.describe_task_dispatch(
                ProcessorTaskRequest(
                    task_type="reply",
                    prompt="hello",
                    metadata={"selected_action_type": "reply_once", "uncertainty_level": 0.12},
                )
            )

            self.assertEqual(dispatch["providers"][0], "deepseek")
            self.assertNotIn("codex_cli", dispatch["providers"])

    def test_deepseek_provider_uses_chat_completions_payload(self) -> None:
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
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 128
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)
            provider = DeepSeekProvider()

            captured: dict[str, object] = {}

            def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
                captured["url"] = url
                captured["api_key"] = api_key
                captured["payload"] = payload
                captured["timeout_seconds"] = timeout_seconds
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "holo reply",
                                "reasoning_content": "internal trace",
                            }
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 2,
                        "total_tokens": 12,
                    },
                }

            with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
                with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                    result = provider.run_task(
                        runner,
                        ProcessorTaskRequest(
                            task_type="reply",
                            prompt="say hello",
                            lane="micro_fast",
                            timeout_seconds=9,
                        ),
                        spec={"output_schema": "plain_text"},
                        lane_name="micro_fast",
                        lane_config=config.processor_fabric.provider_backends["micro_fast"],
                    )

            self.assertEqual(result.text, "holo reply")
            self.assertEqual(captured["url"], "https://api.deepseek.com/chat/completions")
            self.assertEqual(captured["api_key"], "test-key")
            self.assertEqual(captured["timeout_seconds"], 9)
            payload = captured["payload"]
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload["model"], "deepseek-v4-flash")
            self.assertEqual(payload["thinking"], {"type": "disabled"})
            self.assertEqual(payload["messages"], [{"role": "user", "content": "say hello"}])
            self.assertEqual(result.metadata["reasoning_content_present"], True)

    def test_legacy_run_uses_lane_model_for_deepseek_backend(self) -> None:
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
codex_model = "gpt-5.4"
codex_reasoning_effort = "low"

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)
            provider = runner._providers["deepseek"]
            captured: dict[str, object] = {}

            def fake_post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: int) -> dict[str, object]:
                captured["payload"] = payload
                return {
                    "choices": [{"message": {"content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }

            with mock.patch.dict("os.environ", {"TEST_DEEPSEEK_API_KEY": "test-key"}):
                with mock.patch.object(provider, "_post_json", side_effect=fake_post_json):
                    result = runner.run("legacy call without lane")

            payload = captured["payload"]
            self.assertIsInstance(payload, dict)
            self.assertEqual(result.reply_text, "ok")
            self.assertEqual(payload["model"], "deepseek-v4-pro")
            self.assertEqual(payload["thinking"], {"type": "enabled", "reasoning_effort": "high"})

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
        self.assertIn(dispatch["providers"][0], {"deepseek", "codex_cli"})
