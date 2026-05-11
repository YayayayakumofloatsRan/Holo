from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
response_cache_enabled = true
response_cache_ttl_seconds = 120
response_cache_max_entries = 12

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
            self.assertTrue(config.processor_fabric.response_cache_enabled)
            self.assertEqual(config.processor_fabric.response_cache_ttl_seconds, 120)
            self.assertEqual(config.processor_fabric.response_cache_max_entries, 12)
            self.assertEqual(config.processor_fabric.provider_backends["micro_fast"].primary_provider, "openai_compatible")
            self.assertEqual(config.processor_fabric.provider_backends["micro_fast"].max_output_tokens, 512)
            self.assertEqual(config.processor_fabric.processor_routing["reply"].lane, "kernel_xhigh")
            self.assertEqual(config.processor_fabric.processor_routing["reply"].budget_tag, "reply_override")

    def test_load_config_supports_deepseek_provider_defaults(self) -> None:
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
deepseek_api_key_env = "TEST_DEEPSEEK_KEY"
deepseek_model = "deepseek-v4-pro"
deepseek_fast_model = "deepseek-v4-flash"
""".strip(),
                encoding="utf-8",
            )

            config = load_config(str(config_path), repo_root=root)

            self.assertEqual(config.processor_fabric.deepseek_base_url, "https://api.deepseek.com")
            self.assertEqual(config.processor_fabric.deepseek_api_key_env, "TEST_DEEPSEEK_KEY")
            self.assertEqual(config.processor_fabric.deepseek_model, "deepseek-v4-pro")
            self.assertEqual(config.processor_fabric.deepseek_fast_model, "deepseek-v4-flash")
            self.assertEqual(config.processor_fabric.provider_backends["subject_main"].primary_provider, "deepseek")
            self.assertEqual(config.processor_fabric.provider_backends["micro_fast"].model, "deepseek-v4-flash")


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

    def test_queue_store_round_trips_processor_response_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            store = QueueStore(Path(tmpdir) / "holo_host.sqlite3")
            store.initialize()
            try:
                store.put_processor_response_cache(
                    cache_key="cache-key-1",
                    payload={
                        "task_type": "reply",
                        "text": "cached reply",
                        "metadata": {"provider": "deepseek", "usage": {"total_tokens": 10}},
                    },
                    provider="deepseek",
                    task_type="reply",
                    lane="subject_main",
                    model="deepseek-v4-pro",
                    reasoning_effort="",
                    ttl_seconds=3600,
                )

                cached = store.get_processor_response_cache("cache-key-1")
                self.assertIsNotNone(cached)
                self.assertEqual(cached["payload"]["text"], "cached reply")
                self.assertEqual(cached["hit_count"], 1)
                stats = store.processor_response_cache_stats()
                self.assertEqual(stats["entries"], 1)
                self.assertEqual(stats["hits"], 1)
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

    def test_deepseek_provider_returns_standardized_result(self) -> None:
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
deepseek_api_key_env = "TEST_DEEPSEEK_KEY"
deepseek_model = "deepseek-v4-pro"
deepseek_fast_model = "deepseek-v4-flash"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)

            class _FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps(
                        {
                            "choices": [{"message": {"content": "agent reply"}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                        }
                    ).encode("utf-8")

            with patch.dict(os.environ, {"TEST_DEEPSEEK_KEY": "unit-key"}), patch(
                "holo_host.codex_runner.urlopen",
                return_value=_FakeResponse(),
            ) as fake_urlopen:
                result = runner.run_task(
                    ProcessorTaskRequest(task_type="reply", prompt="hello", provider_hint="deepseek")
                )

            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.text, "agent reply")
            self.assertEqual(result.metadata["provider"], "deepseek")
            self.assertEqual(result.metadata["model"], "deepseek-v4-pro")
            self.assertEqual(result.metadata["usage"]["total_tokens"], 10)
            self.assertEqual(result.metadata["capabilities"]["thinking_mode"], True)
            request = fake_urlopen.call_args.args[0]
            self.assertTrue(request.full_url.endswith("/chat/completions"))
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["thinking"], {"type": "disabled"})
            self.assertNotIn("reasoning_effort", body)

    def test_deepseek_provider_enables_thinking_only_for_high_effort(self) -> None:
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
deepseek_api_key_env = "TEST_DEEPSEEK_KEY"
deepseek_model = "deepseek-v4-pro"
deepseek_fast_model = "deepseek-v4-flash"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)

            class _FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps(
                        {
                            "choices": [{"message": {"content": "deep plan"}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                        }
                    ).encode("utf-8")

            with patch.dict(os.environ, {"TEST_DEEPSEEK_KEY": "unit-key"}), patch(
                "holo_host.codex_runner.urlopen",
                return_value=_FakeResponse(),
            ) as fake_urlopen:
                result = runner.run_task(
                    ProcessorTaskRequest(task_type="deep_simulation", prompt="simulate", provider_hint="deepseek")
                )

            self.assertEqual(result.returncode, 0)
            request = fake_urlopen.call_args.args[0]
            body = json.loads(request.data.decode("utf-8"))
            self.assertEqual(body["thinking"], {"type": "enabled"})
            self.assertEqual(body["reasoning_effort"], "max")

    def test_deepseek_provider_reuses_cached_response_without_second_http_call(self) -> None:
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
deepseek_api_key_env = "TEST_DEEPSEEK_KEY"
deepseek_model = "deepseek-v4-pro"
response_cache_enabled = true
response_cache_ttl_seconds = 3600
""".strip(),
                encoding="utf-8",
            )
            config = load_config(str(config_path), repo_root=root)
            store = QueueStore(root / ".holo_runtime" / "holo_host.sqlite3")
            store.initialize()
            runner = CodexRunner(
                config,
                usage_recorder=store.record_processor_usage,
                response_cache_store=store,
            )

            class _FakeResponse:
                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def read(self):
                    return json.dumps(
                        {
                            "choices": [{"message": {"content": "cached agent reply"}}],
                            "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10},
                        }
                    ).encode("utf-8")

            try:
                request = ProcessorTaskRequest(
                    task_type="reply",
                    prompt="same expensive prompt",
                    provider_hint="deepseek",
                    metadata={"thread_key": "cli:CacheProbe"},
                )
                with patch.dict(os.environ, {"TEST_DEEPSEEK_KEY": "unit-key"}), patch(
                    "holo_host.codex_runner.urlopen",
                    return_value=_FakeResponse(),
                ) as fake_urlopen:
                    first = runner.run_task(request)
                    second = runner.run_task(request)

                self.assertEqual(first.text, "cached agent reply")
                self.assertEqual(second.text, "cached agent reply")
                self.assertEqual(fake_urlopen.call_count, 1)
                self.assertFalse(first.metadata["cache"]["hit"])
                self.assertTrue(second.metadata["cache"]["hit"])
                self.assertEqual(second.metadata["cache"]["source"], "processor_response_cache")

                rows = store.list_processor_usage(limit=5, provider="deepseek")
                self.assertEqual([row["status"] for row in rows[:2]], ["cache_hit", "ok"])
                self.assertEqual(rows[0]["total_tokens"], 0)
                cache_stats = store.processor_response_cache_stats()
                self.assertEqual(cache_stats["entries"], 1)
                self.assertEqual(cache_stats["hits"], 1)
                self.assertEqual(cache_stats["misses"], 1)
            finally:
                store.close()
