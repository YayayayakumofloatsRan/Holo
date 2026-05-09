from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from holo_host.bionic_agent import BionicKernel
from holo_host.bionic_kernel_parts.turing_eval import score_bionic_turing_probe_set
from holo_host.config import load_config
from holo_host.models import ProcessorTaskResult


class _Stage39Memory:
    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        return {
            "tier": "stage39-local",
            "memory_route": "stage39_turing_probe",
            "continuity_summary": "We were comparing the screenshot bridge and deciding how to make the CLI replies feel less mechanical.",
            "situational_field": {
                "situational_field_visible": True,
                "modalities": ["text", "scene", "visual"],
                "grounding_order": ["continuity_summary", "scene_state", "query"],
                "open_questions": [],
                "inquiry_style": "natural_continuation",
                "history_reliance": "low",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "action_market": [
                {
                    "action_type": "reply_once",
                    "score": 0.78,
                    "reason": "answer as a grounded continuation without exposing internal machinery",
                },
                {"action_type": "silence", "score": 0.04, "reason": "the user asked for continuity"},
            ],
        }


class _PromptCapturingRunner:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def run_task(self, request):
        self.prompts.append(str(request.prompt))
        return ProcessorTaskResult(
            task_type=request.task_type,
            text="We were comparing the screenshot bridge; the useful next cut is making the reply feel less mechanical.",
            returncode=0,
            metadata={
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            },
        )


def _write_stage39_config(root: Path) -> Path:
    state_dir = (root / ".holo_runtime").as_posix()
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        f"""
[runtime]
state_dir = "{state_dir}"
db_path = "{state_dir}/holo_host.sqlite3"
log_dir = "{state_dir}/logs"
processor_backend = "deepseek"
api_port = 65504

[autonomy]
stage22_canary_mode = "shadow"

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


class Stage39BionicTuringBenchmarkTests(unittest.TestCase):
    def test_empty_continuity_guard_uses_natural_boundary_language(self) -> None:
        class _EmptyContinuityMemory(_Stage39Memory):
            def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
                payload = super().sidecar_packet(query, context=context)
                payload["continuity_summary"] = ""
                payload["situational_field"]["grounding_order"] = ["query"]
                return payload

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            runner = _PromptCapturingRunner()
            kernel = BionicKernel(config=config, memory=_EmptyContinuityMemory(), runner=runner)
            result = kernel.run_turn(
                query="where were we before I paused?",
                thread_key="cli:stage39-empty-continuity",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        lowered = text.lower()
        self.assertNotIn("capsule", lowered)
        self.assertNotIn("bionic", lowered)
        self.assertIn("not visible", lowered)

    def test_deterministic_reply_avoids_internal_mechanism_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="where were we before I paused?",
                thread_key="cli:stage39-turing",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        lowered = text.lower()
        self.assertNotIn("action-market", lowered)
        self.assertNotIn("capsule", lowered)
        self.assertNotIn("bionic kernel", lowered)
        self.assertNotIn("i would continue with", lowered)
        self.assertNotIn("we were at we were", lowered)
        self.assertIn("screenshot bridge", lowered)
        self.assertLessEqual(text.count("?"), 1)

    def test_turing_scorecard_penalizes_formulaic_output_and_rewards_continuity(self) -> None:
        weak = [
            {
                "probe_id": "weak",
                "text": "I would continue with your query. The action-market basis is reply_once.",
                "capsule": {"generation": {"context_refs": ["query"]}, "metrics": {"question_count": 0}},
                "expected_anchor": "screenshot bridge",
            }
        ]
        strong = [
            {
                "probe_id": "strong",
                "text": "We were at the screenshot bridge: the next useful cut is making the CLI answer from the visible summary without sounding like a test harness.",
                "capsule": {
                    "generation": {"context_refs": ["query", "continuity"]},
                    "metrics": {"question_count": 0, "template_pressure_score": 0.0},
                },
                "expected_anchor": "screenshot bridge",
            }
        ]

        weak_score = score_bionic_turing_probe_set(weak)
        strong_score = score_bionic_turing_probe_set(strong)
        fullwidth_questions = score_bionic_turing_probe_set(
            [
                {
                    "probe_id": "fullwidth-question-bound",
                    "text": "继续吗？要现在改吗？",
                    "capsule": {"generation": {"context_refs": ["query", "continuity"]}, "metrics": {}},
                    "expected_anchor": "",
                }
            ]
        )

        self.assertLess(weak_score["overall_score"], 0.7)
        self.assertGreaterEqual(strong_score["overall_score"], 0.85)
        self.assertIn("continuity_reference_score", strong_score["metrics"])
        self.assertIn("mechanism_leakage_score", strong_score["metrics"])
        self.assertEqual(fullwidth_questions["probes"][0]["flags"]["question_count"], 2)
        self.assertLess(fullwidth_questions["metrics"]["question_bounds_score"], 1.0)

    def test_processor_prompt_avoids_leakage_prone_internal_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            runner = _PromptCapturingRunner()
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=runner)
            kernel.run_turn(
                query="where were we before I paused?",
                thread_key="cli:stage39-prompt",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        prompt = "\n".join(runner.prompts).lower()
        self.assertNotIn("bionic kernel", prompt)
        self.assertNotIn("action-market", prompt)
        self.assertNotIn("capsule", prompt)
        self.assertIn("do not expose internal machinery", prompt)
        self.assertIn("plain and concrete", prompt)
        self.assertIn("avoid theatrical metaphors", prompt)

    def test_accept_stage39_cli_runs_bionic_turing_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage39_config(Path(tmpdir))
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = "s" + "k-stage39-test-env-only-value-1234567890"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage39",
                    "--thread-key",
                    "cli:stage39",
                    "--chat-name",
                    "Stage39",
                    "--channel",
                    "cli",
                ],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
                env=env,
            )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"], payload)
        self.assertTrue(payload["checks"]["stage38_gate_passed"])
        self.assertTrue(payload["checks"]["scorecard_passed"])
        self.assertTrue(payload["checks"]["mechanism_leakage_blocked"])
        self.assertTrue(payload["checks"]["continuity_anchor_visible"])
        self.assertTrue(payload["checks"]["transport_interface_only"])


if __name__ == "__main__":
    unittest.main()
