from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state, build_turn_plan, render_chat_prompt
from holo_host.stage124_fast_deep_thought_loop import stage124_deep_packet_guard


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


class _ShallowThenDeepRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        if str(kwargs.get("budget_tag", "")) == "stage124_fast_packet":
            return SimpleNamespace(
                reply_text=(
                    '{"intent":"brief_ack","scene":"memory probe",'
                    '"deep_packet_needed":false,"shallow_reply":"明白，先按事实回答。",'
                    '"speak_now":true,"continue_until":"ack enough"}'
                ),
                session_id="stage128-fast",
                returncode=0,
                stdout="",
                stderr="",
                metadata={"provider": "fake", "usage": {}},
            )
        return SimpleNamespace(
            reply_text="事实回答：当前最深的可检索记忆来自 archive 和 mind_graph，而不是一个单字隐喻。",
            session_id="stage128-deep",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "usage": {}},
        )


def _context(text: str, *, tier: str = "deep_recall") -> TurnContext:
    packet = {
        "tier": tier,
        "query_focus": "memory",
        "selected_action": {"action_type": "reply_multi", "score": 0.9},
        "identity_core": {"lines": ["Holo is a single continuous agent subject over local memory and provider packets."]},
        "self_model": {"metadata": {"summary": "single subject, local memory, provider-mediated language"}},
        "reply_constraints": {"lines": []},
    }
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage128",
        chat_name="Stage128",
        sender="User",
        user_text=text,
        sidecar=packet,
        mind_packet=dict(packet),
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={},
        uncertainty_level=0.12,
    )


def test_stage128_memory_probe_forces_deep_packet_but_keeps_first_reaction(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _ShallowThenDeepRunner()
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]

    plan = processor.generate(_context("回忆一下，记忆最深处是些什么，什么时候的"), session_id="stage128")

    assert [call["budget_tag"] for call in runner.calls] == ["stage124_fast_packet", "chat_reply"]
    assert runner.calls[1]["metadata"]["stage124_fast_packet"]["deep_packet_needed"] is True
    assert runner.calls[1]["metadata"]["stage124_fast_packet"]["deep_packet_forced"] is True
    assert "明白，先按事实回答。" in plan.text
    assert "事实回答：当前最深的可检索记忆" in plan.text
    assert plan.debug["stage124_thought_loop"]["deep_packet_sent"] is True


def test_stage128_short_contextual_followup_cannot_end_at_shallow_answer() -> None:
    guard = stage124_deep_packet_guard(
        "所以 答案是？",
        {"deep_packet_needed": False, "shallow_reply": "答案是档。", "speak_now": True},
    )

    assert guard["required"] is True
    assert guard["reason"] == "short_contextual_followup"


def test_stage128_factual_correction_cannot_end_at_ack() -> None:
    guard = stage124_deep_packet_guard(
        "可能还不够，如实回答，不必多言",
        {"deep_packet_needed": False, "shallow_reply": "明白，保持简洁如实。", "speak_now": True},
    )

    assert guard["required"] is True
    assert guard["reason"] == "factual_answer_requested"


def test_stage128_self_memory_prompt_uses_fact_grounded_contract(tmp_path: Path) -> None:
    config = _config(tmp_path)
    context = _context("如实回答，你是什么，记忆系统最深处是什么")
    turn_plan = build_turn_plan(context, config)

    prompt = render_chat_prompt(context, turn_plan=turn_plan)

    assert "Fact Grounded Self Report:" in prompt
    assert "single-subject agent runtime" in prompt
    assert "memory answers must name concrete stores" in prompt
    assert "shallow first reaction cannot replace the deeper packet" in prompt
