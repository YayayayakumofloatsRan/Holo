from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.codex_runner import CodexRunner
from holo_host.config import load_config


def _write_stage34_config(root: Path) -> Path:
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "codex_cli"

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
max_output_tokens = 256
""".strip(),
        encoding="utf-8",
    )
    return config_path


class Stage34DebtClosureTests(unittest.TestCase):
    def test_debt_registry_classifies_current_weak_spots(self) -> None:
        from holo_host.debt_registry import current_debt_registry

        registry = current_debt_registry()
        items = {item["debt_id"]: item for item in registry["items"]}

        required_ids = {
            "reply-api-facade-size",
            "live-wechat-hardening",
            "visual-provider-readiness",
            "autonomous-inquiry-quality",
            "provider-contract-drift",
            "template-pressure",
        }
        self.assertTrue(registry["ok"], registry)
        self.assertTrue(required_ids.issubset(items), items.keys())
        self.assertFalse(registry["unclassified"], registry)
        self.assertEqual(items["provider-contract-drift"]["status"], "resolved")
        self.assertEqual(items["template-pressure"]["status"], "resolved")
        self.assertIn(items["live-wechat-hardening"]["status"], {"external_precondition", "planned"})

    def test_visual_provider_readiness_is_bounded_and_non_overclaiming(self) -> None:
        config = load_config(repo_root=Path(__file__).resolve().parents[1])
        readiness = CodexRunner(config).visual_provider_readiness()
        providers = readiness["providers"]

        self.assertEqual(readiness["stage"], "stage34-debt-registry-and-visual-readiness")
        self.assertTrue(readiness["hard_boundaries"]["no_live_call_required"])
        self.assertTrue(readiness["checks"]["text_api_providers_reject_image_requests"])
        self.assertFalse(providers["deepseek"]["image_request_supported"])
        self.assertFalse(providers["openai_compatible"]["image_request_supported"])
        self.assertTrue(providers["codex_cli"]["image_request_supported"])
        self.assertIn("image_understand", readiness["routing"])

    def test_show_debt_registry_cli(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "holo_host",
                "--config",
                ".holo_host.example.toml",
                "show-debt-registry",
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
        self.assertFalse(payload["unclassified"], payload)

    def test_accept_stage34_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage34_config(Path(tmpdir))
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage34",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["debt_registry_classified"])
        self.assertTrue(payload["checks"]["visual_provider_non_overclaiming"])
        self.assertTrue(payload["checks"]["accept_stage33_still_passes"])


if __name__ == "__main__":
    unittest.main()
