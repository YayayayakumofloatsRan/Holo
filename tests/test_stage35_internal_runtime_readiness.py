from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.config import load_config
from holo_host.runtime_readiness import (
    deepseek_lane_readiness,
    scan_config_for_secret_material,
    wechat_transport_quiescence,
)


def _write_stage35_config(root: Path, *, embedded_secret: bool = False) -> Path:
    config_path = root / ".holo_host.toml"
    fake_secret = "s" + "k-stage35-leaked-secret-value-1234567890"
    secret_line = f'deepseek_api_key = "{fake_secret}"' if embedded_secret else ""
    state_dir = (root / ".holo_runtime").as_posix()
    config_path.write_text(
        f"""
[runtime]
state_dir = "{state_dir}"
db_path = "{state_dir}/holo_host.sqlite3"
log_dir = "{state_dir}/logs"
processor_backend = "deepseek"
api_port = 65500

[autonomy]
stage22_canary_mode = "shadow"

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"
deepseek_model = "deepseek-v4-pro"
deepseek_fast_model = "deepseek-v4-flash"
{secret_line}

[provider_backends.kernel_xhigh]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "xhigh"
max_output_tokens = 1024

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


class Stage35InternalRuntimeReadinessTests(unittest.TestCase):
    def test_config_secret_scan_allows_env_reference_but_rejects_embedded_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            clean_config = _write_stage35_config(Path(tmpdir))
            leaked_root = Path(tmpdir) / "leaked"
            leaked_root.mkdir(exist_ok=True)
            leaked_config = _write_stage35_config(leaked_root, embedded_secret=True)

            clean_scan = scan_config_for_secret_material(clean_config)
            leaked_scan = scan_config_for_secret_material(leaked_config)

        self.assertTrue(clean_scan["ok"], clean_scan)
        self.assertFalse(clean_scan["secret_like_tokens"], clean_scan)
        self.assertTrue(leaked_scan["exists"], leaked_scan)
        self.assertFalse(leaked_scan["ok"], leaked_scan)
        self.assertTrue(leaked_scan["secret_like_tokens"], leaked_scan)

    def test_deepseek_lane_readiness_requires_all_primary_lanes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage35_config(Path(tmpdir))))

        readiness = deepseek_lane_readiness(config)

        self.assertTrue(readiness["ok"], readiness)
        self.assertEqual(readiness["required_lanes"], ["kernel_xhigh", "subject_main", "micro_fast"])
        self.assertEqual(readiness["lanes"]["kernel_xhigh"]["primary_provider"], "deepseek")
        self.assertEqual(readiness["lanes"]["micro_fast"]["model"], "deepseek-v4-flash")

    def test_wechat_quiescence_allows_stopped_runtime_but_blocks_queued_sends(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage35_config(Path(tmpdir))))
            helper_dir = config.runtime.state_dir / "wechat-helper"
            helper_dir.mkdir(parents=True)
            (helper_dir / "transport_state.live.json").write_text('{"status":"stopped"}', encoding="utf-8")

            stopped = wechat_transport_quiescence(config)

            send_queue = helper_dir / "send_queue"
            send_queue.mkdir()
            (send_queue / "pending.json").write_text("{}", encoding="utf-8")
            queued = wechat_transport_quiescence(config)

        self.assertTrue(stopped["ok"], stopped)
        self.assertFalse(queued["ok"], queued)
        self.assertEqual(queued["queued_send_count"], 1)

    def test_accept_stage35_cli_checks_internal_runtime_without_live_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage35_config(Path(tmpdir))
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = "s" + "k-stage35-test-env-only-value-1234567890"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage35",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["accept_stage34_still_passes"])
        self.assertTrue(payload["checks"]["deepseek_primary_lanes"])
        self.assertTrue(payload["checks"]["deepseek_key_env_present"])
        self.assertTrue(payload["checks"]["local_config_secret_free"])
        self.assertTrue(payload["checks"]["wechat_transport_not_started_by_gate"])
        self.assertTrue(payload["hard_boundaries"]["no_live_model_call"])
        self.assertTrue(payload["hard_boundaries"]["no_wechat_transport_start"])


if __name__ == "__main__":
    unittest.main()
