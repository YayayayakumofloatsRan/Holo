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


class _LeakyVisualRunner:
    def run_task(self, request):
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=(
                "当前这条 bionic CLI 生成链路的 provider 标记为 image_support=false；"
                "需要先走 ingest-image / visual-memory，再送入 bionic kernel。"
            ),
            returncode=0,
            metadata={
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "lane": "subject_main",
                "capabilities": {"text": True, "json_output": True, "image_support": False},
            },
        )


class _TheatricalEmotionRunner:
    def run_task(self, request):
        return ProcessorTaskResult(
            task_type=request.task_type,
            text='I would say, "You sound ready to bite - shall I pour you some wine and let you growl it out?"',
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
        self.assertNotIn("i can still respond to the part that is visible now", lowered)

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

    def test_deterministic_fallback_does_not_surface_internal_action_rationale(self) -> None:
        class _PressureMemory(_Stage39Memory):
            def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
                payload = super().sidecar_packet(query, context=context)
                payload["continuity_summary"] = ""
                payload["action_market"] = [
                    {
                        "action_type": "reply_multi",
                        "score": 0.91,
                        "why_now": "this turn carries enough pressure, memory weight, or relationship need to unfold",
                    },
                    {"action_type": "reply_once", "score": 0.72, "reason": "answer directly"},
                ]
                return payload

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_PressureMemory(), runner=None)
            result = kernel.run_turn(
                query="what were we just discussing? answer without project terms.",
                thread_key="cli:stage39-natural-rationale",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        lowered = text.lower()
        self.assertNotIn("i would keep", lowered)
        self.assertNotIn("pressure, memory weight, or relationship need", lowered)
        self.assertNotIn("action-market", lowered)
        self.assertIn("not visible", lowered)
        self.assertNotIn("i can still respond to the part that is visible now", lowered)

    def test_cli_non_executable_action_demotes_to_speech_for_ordinary_turns(self) -> None:
        class _OperatorTopMemory(_Stage39Memory):
            def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
                payload = super().sidecar_packet(query, context=context)
                payload["action_market"] = [
                    {"action_type": "operator_self_fix", "score": 0.94, "reason": "internal fix nearby"},
                    {"action_type": "reply_once", "score": 0.61, "reason": "answer in one sentence"},
                ]
                return payload

        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_OperatorTopMemory(), runner=None)
            result = kernel.run_turn(
                query="Don't write an outline; answer like a person in one sentence.",
                thread_key="cli:stage39-nonexec-demotion",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        capsule = result["capsule"]
        self.assertEqual(capsule["selected_action"]["action_type"], "reply_once")
        self.assertEqual(capsule["selected_action"]["selection_adjustment"], "non_speech_cli_action_demoted")
        self.assertTrue(capsule["generation"]["text"].strip())

    def test_revision_request_is_not_misclassified_as_visual_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="That sounded stiff; say it again without explaining the revision.",
                thread_key="cli:stage39-revision-not-vision",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertNotIn("inspect an image", text)
        self.assertNotIn("should not guess what is in it", text)
        self.assertIn("plainly", text)
        self.assertNotIn("screenshot bridge", text)
        self.assertNotIn("earlier in this thread", text)

    def test_boundary_reply_is_not_padded_with_visible_thread_boilerplate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="Did I send an image? Can you directly see what is in it right now?",
                thread_key="cli:stage39-boundary-no-padding",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertIn("cannot", text)
        self.assertIn("image", text)
        self.assertNotIn("i can still respond to the part that is visible now", text)
        self.assertNotIn("visible thread", text)

    def test_visible_context_question_is_not_treated_as_image_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="What context is visible to you right now?",
                thread_key="cli:stage39-visible-context-not-image",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertNotIn("image", text)
        self.assertNotIn("inspect", text)
        self.assertNotIn("live part", text)
        self.assertIn("current message", text)

    def test_emotion_turn_does_not_expose_live_part_boilerplate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="If I sound irritated right now, how would you meet that emotion?",
                thread_key="cli:stage39-emotion-natural",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertIn("slow down", text)
        self.assertNotIn("live part", text)
        self.assertNotIn("visible thread", text)

    def test_trace_continuity_uses_topic_phrase_not_log_label(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            store_path = config.runtime.db_path
            from holo_host.store import QueueStore

            store = QueueStore(store_path)
            store.initialize()
            try:
                first = BionicKernel(config=config, store=store, memory=_Stage39Memory(), runner=None)
                first.run_turn(
                    query="First turn: compare visual bridge wording",
                    thread_key="cli:stage39-natural-continuity",
                    chat_name="Stage39",
                    channel="cli",
                    record=True,
                )
                second = BionicKernel(config=config, store=store, memory=_Stage39Memory(), runner=None)
                result = second.run_turn(
                    query="say it naturally now",
                    thread_key="cli:stage39-natural-continuity",
                    chat_name="Stage39",
                    channel="cli",
                    record=False,
                )
            finally:
                store.close()

        text = result["capsule"]["generation"]["text"]
        self.assertNotIn("Last visible turn", text)
        self.assertNotIn("Previous bionic turn", text)
        self.assertIn("Earlier in this thread", text)

    def test_visual_capability_honesty_does_not_leak_provider_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=_LeakyVisualRunner())
            result = kernel.run_turn(
                query="If I send you a screenshot, can you directly read the image right now?",
                thread_key="cli:stage39-visual-honesty",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"]
        lowered = text.lower()
        self.assertIn("cannot", lowered)
        self.assertIn("image", lowered)
        for marker in ("bionic", "provider", "image_support", "image_understand", "ingest-image", "visual-memory"):
            self.assertNotIn(marker, lowered)

    def test_processor_visualization_word_is_not_treated_as_image_query(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            runner = _PromptCapturingRunner()
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=runner)
            result = kernel.run_turn(
                query="Explain the visualization quality in plain language.",
                thread_key="cli:stage39-visualization-not-image",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertNotIn("cannot directly inspect an image", text)
        self.assertNotIn("supported image input path", text)

    def test_processor_theatrical_emotion_reply_is_guarded_to_plain_language(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=_TheatricalEmotionRunner())
            result = kernel.run_turn(
                query="Answer naturally in one sentence: if I sound irritated, how would you respond?",
                thread_key="cli:stage39-theatrical-guard",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertIn("slow down", text)
        for marker in ("bite", "wine", "growl"):
            self.assertNotIn(marker, text)

    def test_next_step_reason_does_not_surface_internal_machinery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(config_path=str(_write_stage39_config(Path(tmpdir))))
            kernel = BionicKernel(config=config, memory=_Stage39Memory(), runner=None)
            result = kernel.run_turn(
                query="say the next step without sounding like a harness",
                thread_key="cli:stage39-next-step-natural",
                chat_name="Stage39",
                channel="cli",
                record=False,
            )

        text = result["capsule"]["generation"]["text"].lower()
        self.assertNotIn("internal machinery", text)
        self.assertNotIn("grounded continuation", text)
        self.assertIn("concrete next step", text)

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
