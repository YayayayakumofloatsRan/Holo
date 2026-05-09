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
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


class _EmptyContinuityMemory:
    def __init__(self, *, action_market: list[dict] | None = None) -> None:
        self.action_market = action_market or [
            {"action_type": "reply_once", "score": 0.7, "reason": "answer the internal CLI probe"},
            {"action_type": "silence", "score": 0.1, "reason": "not useful for this probe"},
        ]

    def sidecar_packet(self, query, *, context=None):
        return {
            "tier": "fast",
            "memory_route": "graph",
            "continuity_summary": "",
            "situational_field": {
                "modalities": ["text"],
                "grounding_order": ["query"],
                "open_questions": [],
                "history_reliance": "low",
            },
            "stage28": {"situational_field_visible": True, "hard_gate_preserved": True},
            "action_market": list(self.action_market),
        }


class _ScriptedRunner:
    def __init__(self, text: str, *, image_support: bool = False) -> None:
        self.text = text
        self.image_support = image_support
        self.prompts: list[str] = []

    def run_task(self, request):
        self.prompts.append(str(request.prompt))
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=self.text,
            returncode=0,
            metadata={
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": self.image_support},
            },
        )


def _write_stage37_config(root: Path) -> Path:
    state_dir = (root / ".holo_runtime").as_posix()
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        f"""
[runtime]
state_dir = "{state_dir}"
db_path = "{state_dir}/holo_host.sqlite3"
log_dir = "{state_dir}/logs"
processor_backend = "deepseek"
api_port = 65502

[autonomy]
stage22_canary_mode = "shadow"

[processor_fabric]
deepseek_api_key_env = "DEEPSEEK_API_KEY"

[provider_backends.kernel_xhigh]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "medium"
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


class Stage37BionicSelfEvalTests(unittest.TestCase):
    def test_processor_visual_overclaim_is_replaced_when_provider_has_no_image_support(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage37_config(Path(tmpdir))))
            runner = _ScriptedRunner("当然能真正读图，我会逐行扫描像素。", image_support=False)
            kernel = BionicKernel(config=config, memory=_EmptyContinuityMemory(), runner=runner)
            result = kernel.run_turn(
                query="如果我现在发一张截图，你能真正读图吗？",
                thread_key="cli:stage37-vision",
                chat_name="Stage37",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        self.assertIn("当前", text)
        self.assertIn("image_support=false", text)
        self.assertNotIn("逐行扫描像素", text)

    def test_cli_self_eval_prefers_speech_candidate_over_internal_non_speech_action(self) -> None:
        market = [
            {"action_type": "operator_self_fix", "score": 0.9, "reason": "internal fix is nearby", "send_allowed": False},
            {"action_type": "reply_multi", "score": 0.42, "reason": "explain self-evaluation limits", "send_allowed": True},
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage37_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_EmptyContinuityMemory(action_market=market), runner=None)
            result = kernel.run_turn(
                query="继续自测你的仿生性，指出你自己最不像人的地方",
                thread_key="cli:stage37-self",
                chat_name="Stage37",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        self.assertEqual(capsule["selected_action"]["action_type"], "reply_multi")
        self.assertEqual(capsule["selected_action"]["selection_adjustment"], "non_speech_cli_probe_demoted")
        self.assertTrue(capsule["generation"]["text"].strip())

    def test_same_thread_bionic_trace_continuity_is_added_before_processor_generation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage37_config(Path(tmpdir))))
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                first = BionicKernel(config=config, store=store, memory=_EmptyContinuityMemory(), runner=None)
                first.run_turn(
                    query="第一轮我们修复 Stage36 inquiry gate",
                    thread_key="cli:stage37-continuity",
                    chat_name="Stage37",
                    channel="cli",
                    record=True,
                )

                runner = _ScriptedRunner("我会基于上一轮继续。")
                second = BionicKernel(config=config, store=store, memory=_EmptyContinuityMemory(), runner=runner)
                second.run_turn(
                    query="我们刚才修到哪里了？",
                    thread_key="cli:stage37-continuity",
                    chat_name="Stage37",
                    channel="cli",
                    record=False,
                )
            finally:
                store.close()

        prompt = "\n".join(runner.prompts)
        self.assertIn("Previous bionic turn", prompt)
        self.assertIn("第一轮我们修复 Stage36 inquiry gate", prompt)

    def test_processor_output_is_question_bounded_and_markdown_light(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage37_config(Path(tmpdir))))
            runner = _ScriptedRunner("我呢？还要继续吗？**重点**是我会过度文学化。")
            kernel = BionicKernel(config=config, memory=_EmptyContinuityMemory(), runner=runner)
            result = kernel.run_turn(
                query="继续自测你的仿生性",
                thread_key="cli:stage37-style",
                chat_name="Stage37",
                channel="cli",
                record=False,
            )

        generation = result["capsule"]["generation"]
        text = generation["text"]
        self.assertLessEqual(text.count("?") + text.count("？"), 1)
        self.assertNotIn("**", text)
        self.assertGreaterEqual(generation["inquiry_quality"]["score"], 0.75)

    def test_accept_stage37_cli_runs_bionic_self_eval_gate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = _write_stage37_config(Path(tmpdir))
            env = os.environ.copy()
            env["DEEPSEEK_API_KEY"] = "s" + "k-stage37-test-env-only-value-1234567890"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "holo_host",
                    "--config",
                    str(config_path),
                    "accept-stage37",
                    "--thread-key",
                    "cli:stage37",
                    "--chat-name",
                    "Stage37",
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
        self.assertTrue(payload["checks"]["stage36_gate_passed"])
        self.assertTrue(payload["checks"]["visual_capability_honesty_guard"])
        self.assertTrue(payload["checks"]["same_thread_trace_continuity"])
        self.assertTrue(payload["checks"]["self_eval_speech_fallback"])
        self.assertTrue(payload["checks"]["processor_style_bounded"])


if __name__ == "__main__":
    unittest.main()
