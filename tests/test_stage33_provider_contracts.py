from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from holo_host.codex_runner import CodexRunner
from holo_host.config import load_config
from holo_host.models import ProcessorTaskRequest


def _write_provider_config(root: Path) -> Path:
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "openai_compatible"

[processor_fabric]
openai_compatible_base_url = "http://localhost:1234/v1"
openai_compatible_api_key_env = "TEST_COMPAT_KEY"

[provider_backends.subject_main]
primary_provider = "openai_compatible"
backup_provider = "deepseek"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
max_output_tokens = 256
""".strip(),
        encoding="utf-8",
    )
    return config_path


class Stage33ProviderContractTests(unittest.TestCase):
    def test_openai_compatible_uses_chat_completions_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = _write_provider_config(root)
            config = load_config(str(config_path), repo_root=root)
            runner = CodexRunner(config)

            captured: dict[str, object] = {}

            class _FakeChatCompletions:
                def create(self, **kwargs):
                    captured["payload"] = dict(kwargs)

                    class _Usage:
                        prompt_tokens = 4
                        completion_tokens = 5
                        total_tokens = 9

                    class _Message:
                        content = "compat reply"

                    class _Choice:
                        message = _Message()

                    class _Response:
                        choices = [_Choice()]
                        usage = _Usage()

                    return _Response()

            class _NoResponsesApi:
                def create(self, **_kwargs):
                    raise AssertionError("openai_compatible must not use responses.create")

            class _FakeClient:
                def __init__(self, **kwargs):
                    captured["client_kwargs"] = dict(kwargs)
                    self.chat = types.SimpleNamespace(completions=_FakeChatCompletions())
                    self.responses = _NoResponsesApi()

            fake_openai = types.ModuleType("openai")
            fake_openai.OpenAI = _FakeClient
            original_find_spec = __import__("importlib").util.find_spec

            def _find_spec(name: str, *args, **kwargs):
                if name == "openai":
                    return object()
                return original_find_spec(name, *args, **kwargs)

            with patch.dict(sys.modules, {"openai": fake_openai}), patch(
                "importlib.util.find_spec",
                side_effect=_find_spec,
            ), patch.dict(os.environ, {"TEST_COMPAT_KEY": "compat-key"}):
                result = runner.run_task(
                    ProcessorTaskRequest(
                        task_type="reply",
                        prompt="hello",
                        provider_hint="openai_compatible",
                        output_schema="json",
                    )
                )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.text, "compat reply")
        self.assertEqual(result.metadata["provider"], "openai_compatible")
        self.assertEqual(result.metadata["usage"]["total_tokens"], 9)
        self.assertEqual(captured["client_kwargs"], {"base_url": "http://localhost:1234/v1", "api_key": "compat-key"})
        self.assertEqual(captured["payload"]["response_format"], {"type": "json_object"})

    def test_provider_contracts_show_api_surfaces_without_live_calls(self) -> None:
        config = load_config(repo_root=Path(__file__).resolve().parents[1])
        contracts = CodexRunner(config).provider_contracts()

        self.assertEqual(contracts["stage"], "stage33-provider-api-contracts")
        self.assertEqual(contracts["providers"]["openai_compatible"]["api_surface"], "chat.completions")
        self.assertEqual(contracts["providers"]["deepseek"]["api_surface"], "chat.completions")
        self.assertFalse(contracts["providers"]["deepseek"]["capabilities"]["image_support"])
        self.assertTrue(contracts["hard_boundaries"]["processor_fabric_only"])

    def test_accept_stage33_provider_contracts_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_provider_config(Path(tmpdir))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage33",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["openai_compatible_chat_completions"])
        self.assertTrue(payload["checks"]["deepseek_chat_completions"])
        self.assertTrue(payload["checks"]["no_provider_image_overclaim"])


if __name__ == "__main__":
    unittest.main()
