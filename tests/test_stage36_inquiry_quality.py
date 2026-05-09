from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel
from holo_host.config import load_config


class _InquiryMemory:
    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "active_thread",
            "continuity_summary": "We are closing Holo technical debt in small verified cuts.",
            "situational_field": {
                "modalities": ["text", "scene", "task_world"],
                "grounding_order": ["query", "continuity_summary", "open_questions"],
                "open_questions": ["which remaining debt has the highest offline leverage?"],
                "history_reliance": "low",
                "inquiry_style": "grounded_continuation",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.81,
                    "reason": "continue the debt burn-down without reopening live transport",
                    "why_now": "the user asked to clear remaining debt",
                },
                {"action_type": "silence", "score": 0.04, "reason": "not appropriate here"},
            ],
        }


def _write_stage36_config(root: Path) -> Path:
    state_dir = (root / ".holo_runtime").as_posix()
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        f"""
[runtime]
state_dir = "{state_dir}"
db_path = "{state_dir}/holo_host.sqlite3"
log_dir = "{state_dir}/logs"
processor_backend = "deepseek"
api_port = 65501

[autonomy]
stage22_canary_mode = "shadow"

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"
deepseek_model = "deepseek-v4-pro"
deepseek_fast_model = "deepseek-v4-flash"

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


class Stage36InquiryQualityTests(unittest.TestCase):
    def test_deterministic_inquiry_is_grounded_and_not_label_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage36_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_InquiryMemory(), runner=None)
            result = kernel.run_turn(
                query="clear the remaining debt",
                thread_key="cli:stage36",
                chat_name="Stage36",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        generation = capsule["generation"]
        text = generation["text"]

        self.assertEqual(generation["mode"], "deterministic_fallback")
        self.assertNotIn("Next:", text)
        self.assertNotIn("Basis:", text)
        self.assertNotIn("Open:", text)
        self.assertNotIn("Context:", text)
        self.assertLessEqual(text.count("?"), 1)
        self.assertIn("clear the remaining debt", text)
        self.assertIn("which remaining debt", text)
        self.assertEqual(generation["inquiry_quality"]["question_count"], 1)
        self.assertEqual(generation["inquiry_quality"]["label_marker_count"], 0)
        self.assertGreaterEqual(capsule["metrics"]["inquiry_quality_score"], 0.75)
        self.assertEqual(capsule["metrics"]["formatting_pressure_score"], 0.0)

    def test_accept_stage36_cli_closes_autonomous_inquiry_debt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage36_config(Path(tmpdir))
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = "s" + "k-stage36-test-env-only-value-1234567890"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage36",
                    "--thread-key",
                    "cli:stage36",
                    "--chat-name",
                    "Stage36",
                    "--channel",
                    "cli",
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
        self.assertTrue(payload["checks"]["stage35_gate_passed"])
        self.assertTrue(payload["checks"]["inquiry_quality_metric_visible"])
        self.assertTrue(payload["checks"]["label_template_removed"])
        self.assertTrue(payload["checks"]["single_grounded_question"])
        self.assertTrue(payload["checks"]["action_market_first_preserved"])


if __name__ == "__main__":
    unittest.main()
