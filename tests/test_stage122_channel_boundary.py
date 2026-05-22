from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage121_conscious_packet_scheduler import build_stage121_packet_policy
from holo_host.stage122_internal_external_channel_boundary import (
    append_stage122_channel_contract,
    build_stage122_channel_frame,
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
max_output_tokens = 2048

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


class _RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="外部可见回复",
            session_id="stage122",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def _context(text: str, *, uncertainty: float = 0.0) -> TurnContext:
    payload = {"selected_action": {"action_type": "reply_once", "score": 0.9}}
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
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
                {"name": "memory_recall", "reason": "ground continuity", "payload": {"query": text}},
                {"name": "tool_registry", "reason": "inspect available actions", "payload": {}},
            ]
        },
        uncertainty_level=uncertainty,
    )


def test_stage122_frame_separates_internal_intent_processing_and_external_speech() -> None:
    policy = build_stage121_packet_policy(
        prompt="continuous thought prompt\n" * 90,
        query="继续推进连续的思考流，它需要知道内部想做什么以及外部说了什么",
        tool_requests=[
            {"name": "memory_recall", "reason": "continuity", "payload": {}},
            {"name": "tool_registry", "reason": "tools", "payload": {}},
            {"name": "test_runner", "reason": "verify", "payload": {}},
        ],
        uncertainty_level=0.84,
        selected_action_type="reply_once",
        lane_name="subject_main",
        lane_max_output_tokens=4096,
    )

    frame = build_stage122_channel_frame(
        user_text="继续推进连续的思考流，它需要知道内部想做什么以及外部说了什么",
        selected_action_type="reply_once",
        stage121_packet_policy=policy,
        tool_requests=[
            {"name": "memory_recall", "reason": "continuity", "payload": {}},
            {"name": "tool_registry", "reason": "tools", "payload": {}},
            {"name": "test_runner", "reason": "verify", "payload": {}},
        ],
        uncertainty_level=0.84,
    )

    assert frame["stage"] == 122
    assert frame["schema"] == "holo.stage122.internal_external_channel_boundary.v1"
    assert frame["internal_intent"]["visible_to_user"] is False
    assert frame["internal_processing"]["visible_to_user"] is False
    assert frame["internal_processing"]["summary_only"] is True
    assert frame["internal_processing"]["raw_hidden_reasoning_disallowed"] is True
    assert frame["external_speech"]["visible_to_user"] is True
    assert frame["external_speech"]["external_speech_only"] is True
    assert frame["external_speech"]["may_include_internal_processing"] is False
    assert frame["internal_intent"]["mode"] == "continue_internal_deliberation"
    assert "external_speech_only" in frame["provider_contract_text"]


def test_stage122_contract_is_appended_once_and_is_cacheable() -> None:
    frame = build_stage122_channel_frame(
        user_text="hello",
        selected_action_type="reply_once",
        stage121_packet_policy={"continuity": {"stream_mode": "compact_reply_packet", "phases": ["context_seed", "expression_commit"]}},
        tool_requests=[],
        uncertainty_level=0.0,
    )

    prompt = append_stage122_channel_contract("base prompt", frame)
    prompt_again = append_stage122_channel_contract(prompt, frame)

    assert prompt.count("Stage122 Channel Boundary") == 1
    assert prompt_again == prompt
    assert "external_speech_only" in prompt
    assert "raw hidden reasoning" in prompt


def test_stage122_processor_attaches_channel_frame_to_provider_metadata_and_debug(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _RecordingRunner()
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    context = _context(
        "继续推进连续的思考流，区分内部意向、内部处理和外部表达，并使用记忆与工具",
        uncertainty=0.86,
    )

    plan = processor.generate(context, session_id="stage122")

    call = runner.calls[-1]
    metadata = dict(call["metadata"])
    frame = metadata["stage122_channel_frame"]
    assert frame["stage"] == 122
    assert metadata["stage121_packet_policy"]["continuity"]["stream_mode"] == "continuous_thought"
    assert "Stage122 Channel Boundary" in str(call["prompt"])
    assert "external_speech_only" in str(call["prompt"])
    assert plan.debug["stage122_channel_frame"]["external_speech"]["external_speech_only"] is True
    assert plan.text == "外部可见回复"


def test_stage122_cli_reports_channel_contract(capsys) -> None:
    result = cli.main(
        [
            "stage122-channel-boundary",
            "--query",
            "连续思考流要知道内部想做什么，也要知道外部说了什么",
            "--uncertainty",
            "0.8",
            "--tool",
            "memory_recall",
            "--tool",
            "tool_registry",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 122
    assert payload["internal_processing"]["summary_only"] is True
    assert payload["external_speech"]["external_speech_only"] is True
