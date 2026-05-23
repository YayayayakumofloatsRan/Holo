from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage124_fast_deep_thought_loop import (
    append_stage124_deep_packet_context,
    build_stage124_fast_packet_prompt,
    parse_stage124_fast_packet,
)


def _config(root: Path):
    config_path = root / ".holo_host.toml"
    config_path.write_text(
        """
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
network_enabled = false

[processor_fabric]
deepseek_base_url = "https://api.deepseek.com"
deepseek_api_key_env = "TEST_DEEPSEEK_API_KEY"

[provider_backends.micro_fast]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4-flash"
reasoning_effort = "low"
max_output_tokens = 900

[provider_backends.subject_main]
primary_provider = "deepseek"
backup_provider = "openai_compatible"
model = "deepseek-v4"
reasoning_effort = "medium"
max_output_tokens = 4096
""".strip(),
        encoding="utf-8",
    )
    return load_config(str(config_path), repo_root=root)


class _FastDeepRunner:
    def __init__(self, *, deep_needed: bool) -> None:
        self.deep_needed = deep_needed
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        if str(kwargs.get("budget_tag", "")) == "stage124_fast_packet":
            if self.deep_needed:
                text = (
                    '{"intent":"tool_grounded_research","scene":"system repair",'
                    '"deep_packet_needed":true,"shallow_reply":"I am checking the live brain first.",'
                    '"speak_now":true,"continue_until":"repo alignment and chain verified"}'
                )
            else:
                text = (
                    '{"intent":"simple_ack","scene":"low pressure",'
                    '"deep_packet_needed":false,"shallow_reply":"Received. I will keep this short.",'
                    '"speak_now":true,"continue_until":"shallow reply enough"}'
                )
            return SimpleNamespace(
                reply_text=text,
                session_id="stage124-fast",
                returncode=0,
                stdout="",
                stderr="",
                metadata={"provider": "fake", "usage": {}},
            )
        return SimpleNamespace(
            reply_text="Deep packet final answer with tool-aware continuity.",
            session_id="stage124-deep",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def _context(text: str, *, uncertainty: float = 0.0) -> TurnContext:
    payload = {"selected_action": {"action_type": "reply_once", "score": 0.9}}
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage124",
        chat_name="Stage124",
        sender="User",
        user_text=text,
        sidecar=payload,
        mind_packet=payload,
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={
            "tool_requests": [
                {"name": "memory_recall", "reason": "continuity", "payload": {"query": text}},
                {"name": "workspace_inspect", "reason": "repo evidence", "payload": {}},
            ]
        },
        uncertainty_level=uncertainty,
    )


def test_stage124_fast_packet_prompt_requires_intent_scene_and_optional_shallow_reply() -> None:
    prompt = build_stage124_fast_packet_prompt(
        user_text="input A",
        channel="holo_cli",
        thread_key="holo_cli:stage124",
        chat_name="Stage124",
    )

    assert "Stage124 Fast Packet" in prompt
    assert "deep_packet_needed" in prompt
    assert "shallow_reply" in prompt
    assert "external_speech" in prompt


def test_stage124_fast_packet_parser_handles_provider_json() -> None:
    parsed = parse_stage124_fast_packet(
        '{"intent":"repair","scene":"single brain","deep_packet_needed":true,'
        '"shallow_reply":"I will check it.","speak_now":true}'
    )

    assert parsed["deep_packet_needed"] is True
    assert parsed["shallow_reply"] == "I will check it."
    assert parsed["intent"] == "repair"


def test_stage124_deep_context_preserves_fast_packet_without_hidden_reasoning() -> None:
    prompt = append_stage124_deep_packet_context(
        "base prompt",
        {
            "intent": "repair",
            "scene": "single brain",
            "deep_packet_needed": True,
            "shallow_reply": "I will check it.",
            "speak_now": True,
        },
    )

    assert "Stage124 Deep Packet Context" in prompt
    assert "intent=repair" in prompt
    assert "shallow_reply=I will check it." in prompt
    assert "raw hidden reasoning" in prompt


def test_stage124_processor_sends_fast_packet_then_deep_packet_when_needed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _FastDeepRunner(deep_needed=True)
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    plan = processor.generate(_context("repair the single brain and continue thinking", uncertainty=0.9), session_id="stage124")

    assert len(runner.calls) == 2
    fast_call, deep_call = runner.calls
    assert fast_call["budget_tag"] == "stage124_fast_packet"
    assert fast_call["lane"] == "micro_fast"
    assert deep_call["budget_tag"] == "chat_reply"
    assert deep_call["lane"] in {"subject_main", "kernel_xhigh"}
    assert "Stage124 Deep Packet Context" in str(deep_call["prompt"])
    assert deep_call["metadata"]["stage124_fast_packet"]["deep_packet_needed"] is True
    assert plan.debug["stage124_thought_loop"]["fast_packet"]["intent"] == "tool_grounded_research"
    assert plan.debug["stage124_thought_loop"]["deep_packet_sent"] is True
    assert plan.bubbles[0].purpose == "fast_reaction"
    assert plan.bubbles[1].purpose == "deep_continuation"
    assert "I am checking the live brain first." in plan.text
    assert "Deep packet final answer with tool-aware continuity." in plan.text
    assert plan.debug["stage132_progressive_stream"]["round_count"] == 2


def test_stage124_processor_can_return_shallow_reply_without_deep_packet(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _FastDeepRunner(deep_needed=False)
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    plan = processor.generate(_context("ack this briefly", uncertainty=0.1), session_id="stage124")

    assert len(runner.calls) == 1
    assert runner.calls[0]["budget_tag"] == "stage124_fast_packet"
    assert plan.text == "Received. I will keep this short."
    assert plan.debug["stage124_thought_loop"]["deep_packet_sent"] is False
