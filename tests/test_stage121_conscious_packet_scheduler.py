from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from holo_host import cli
from holo_host.codex_runner import _coerce_usage_payload
from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage121_conscious_packet_scheduler import build_stage121_packet_policy


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


class _MetadataRecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        return SimpleNamespace(
            reply_text="stage121",
            session_id="stage121",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def _context(text: str, *, uncertainty: float = 0.0, packet: dict | None = None) -> TurnContext:
    payload = {"selected_action": {"action_type": "reply_once", "score": 0.9}, **dict(packet or {})}
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
        capability_context={},
        uncertainty_level=uncertainty,
    )


def test_stage121_long_complex_packets_get_larger_budget_and_more_tool_rounds() -> None:
    simple = build_stage121_packet_policy(
        prompt="short greeting",
        query="晚上好",
        tool_requests=[{"name": "memory_recall", "reason": "baseline", "payload": {}}],
        uncertainty_level=0.1,
        selected_action_type="reply_once",
        lane_name="micro_fast",
        lane_max_output_tokens=2048,
    )
    complex_policy = build_stage121_packet_policy(
        prompt="long research prompt\n" * 120,
        query="我们要构建理论指导下的连续意识流，检查工具、记忆、缓存和动态发包",
        tool_requests=[
            {"name": "memory_recall", "reason": "baseline", "payload": {}},
            {"name": "workspace_inspect", "reason": "inspect", "payload": {}},
            {"name": "test_runner", "reason": "verify", "payload": {}},
            {"name": "git_diff", "reason": "inspect", "payload": {}},
        ],
        uncertainty_level=0.78,
        selected_action_type="reply_once",
        lane_name="subject_main",
        lane_max_output_tokens=4096,
    )

    assert complex_policy["target_input_tokens"] > simple["target_input_tokens"]
    assert complex_policy["output_budget_tokens"] > simple["output_budget_tokens"]
    assert complex_policy["tool_loop"]["max_rounds"] > simple["tool_loop"]["max_rounds"]
    assert complex_policy["cache"]["stable_prefix_first"] is True
    assert "dynamic_tail_last" in complex_policy["cache"]["ordering_contract"]
    assert complex_policy["continuity"]["stream_mode"] == "continuous_thought"


def test_stage121_processor_attaches_packet_policy_to_provider_metadata(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _MetadataRecordingRunner()
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    context = _context(
        "继续构建理论指导下的连续意识流，尽量长包，考虑缓存、工具和记忆",
        uncertainty=0.82,
        packet={"semantic_attractor_lines": ["provider packet cache", "continuous thought stream"]},
    )

    processor.generate(context, session_id="stage121")

    call = runner.calls[-1]
    metadata = dict(call["metadata"])
    policy = metadata["stage121_packet_policy"]
    assert policy["stage"] == 121
    assert policy["continuity"]["stream_mode"] == "continuous_thought"
    assert metadata["max_provider_tool_rounds"] == policy["tool_loop"]["max_rounds"]
    assert metadata["max_provider_tool_calls"] == policy["tool_loop"]["max_tool_calls"]
    assert call["max_output_tokens"] == policy["output_budget_tokens"]
    assert policy["target_input_tokens"] >= policy["observed_prompt_tokens"]


def test_stage121_usage_preserves_deepseek_cache_counters() -> None:
    usage = _coerce_usage_payload(
        {
            "prompt_tokens": 1200,
            "completion_tokens": 100,
            "total_tokens": 1300,
            "prompt_cache_hit_tokens": 900,
            "prompt_cache_miss_tokens": 300,
        }
    )

    assert usage["prompt_cache_hit_tokens"] == 900
    assert usage["prompt_cache_miss_tokens"] == 300


def test_stage121_cli_reports_dynamic_packet_policy(capsys) -> None:
    result = cli.main(
        [
            "stage121-packet-policy",
            "--query",
            "构建理论指导下的连续意识流，尽可能长包并考虑缓存",
            "--prompt-repeat",
            "80",
            "--uncertainty",
            "0.8",
            "--tool",
            "memory_recall",
            "--tool",
            "test_runner",
        ]
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 121
    assert payload["continuity"]["stream_mode"] == "continuous_thought"
    assert payload["target_input_tokens"] > payload["observed_prompt_tokens"]
