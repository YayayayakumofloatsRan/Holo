from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from holo_host.config import load_config
from holo_host.models import TurnContext
from holo_host.processors import CodexCliProcessor, build_attention_state
from holo_host.stage132_progressive_conscious_stream import (
    build_stage132_fast_context_frame,
    merge_stage132_reply_bubbles,
    plan_stage132_progressive_stream,
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


class _ProgressiveRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run(self, prompt: str, **kwargs: object) -> SimpleNamespace:
        self.calls.append({"prompt": prompt, **kwargs})
        if str(kwargs.get("budget_tag", "")) == "stage124_fast_packet":
            return SimpleNamespace(
                reply_text=(
                    '{"intent":"progressive_packet_design","scene":"stage132 cli diagnosis",'
                    '"deep_packet_needed":true,"shallow_reply":"I will first catch the intent, then continue with a deeper packet.",'
                    '"speak_now":true,"continue_until":"the packet schedule and visible stream are explained"}'
                ),
                session_id="stage132-fast",
                returncode=0,
                stdout="",
                stderr="",
                metadata={"provider": "fake", "lane": "micro_fast", "model": "fake-flash", "usage": {}},
            )
        return SimpleNamespace(
            reply_text="The deeper packet should now explain the scheduler, tool loop, and stop condition.",
            session_id="stage132-deep",
            returncode=0,
            stdout="",
            stderr="",
            metadata={"provider": "fake", "lane": "subject_main", "model": "fake-pro", "usage": {}},
        )


def _context(text: str) -> TurnContext:
    packet = {
        "selected_action": {"action_type": "reply_once", "score": 0.88},
        "recent_dialogue_window": {
            "lines": [
                "user: fast replies should not terminate the thought flow",
                "holo: I need a first reaction and then a deeper continuation",
            ]
        },
        "active_thread_state": {
            "continuity_summary": "debugging Holo's progressive provider packet stream",
            "scene_state": {"shared_frame": "Stage132 fast/deep scheduling"},
        },
    }
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage132",
        chat_name="Stage132",
        sender="Operator",
        user_text=text,
        sidecar=packet,
        mind_packet=packet,
        attention_state=build_attention_state(text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={
            "tool_requests": [
                {"name": "workspace_inspect", "reason": "read local runtime state", "payload": {"mode": "readonly"}},
            ],
            "tool_permission_grants": [{"tool": "workspace_inspect", "mode": "readonly"}],
        },
        uncertainty_level=0.74,
    )


def test_stage132_fast_context_frame_is_rich_bounded_and_cacheable() -> None:
    context = _context("Design the fast answer, deep continuation, and CT visualization.")
    frame = build_stage132_fast_context_frame(
        context,
        short_term_lines=[
            "tone_constraint: avoid frequent emoji",
            "pending_task: expose the internal provider packet flow",
        ],
    )

    assert frame["schema"] == "holo.stage132.progressive_conscious_stream.v1"
    assert frame["cache_hint"].startswith("stage132:")
    assert frame["line_count"] >= 7
    assert frame["char_count"] <= 2800
    rendered = "\n".join(frame["lines"])
    assert "selected_action=reply_once" in rendered
    assert "short_term: tone_constraint" in rendered
    assert "tool_request: workspace_inspect" in rendered


def test_stage132_plan_marks_fast_reaction_before_deep_continuation() -> None:
    plan = plan_stage132_progressive_stream(
        fast_packet={
            "intent": "runtime_debug",
            "scene": "cli",
            "deep_packet_needed": True,
            "shallow_reply": "First I catch the intent.",
            "speak_now": True,
            "continue_until": "deep answer explains the packet schedule",
        },
        continuation_lane="subject_main",
        continuation_lane_reason="high_uncertainty",
        selected_action_type="reply_once",
        uncertainty_level=0.7,
        channel="holo_cli",
        expression_budget=3,
        agent_tool_requests=[{"name": "workspace_inspect", "reason": "state", "payload": {}}],
        fast_context_frame={"cache_hint": "stage132:abc", "line_count": 9, "char_count": 1200},
    )

    assert plan["deep_packet_needed"] is True
    assert plan["visible_first_reaction"] is True
    assert [item["purpose"] for item in plan["rounds"]] == ["fast_reaction", "deep_continuation"]
    assert plan["rounds"][0]["lane"] == "micro_fast"
    assert plan["rounds"][1]["lane"] == "subject_main"
    assert plan["tool_loop_expected"] is True


def test_stage132_merge_preserves_first_reaction_and_deep_cli_bubbles() -> None:
    stream = plan_stage132_progressive_stream(
        fast_packet={"deep_packet_needed": True, "shallow_reply": "First.", "speak_now": True},
        continuation_lane="subject_main",
        continuation_lane_reason="test",
        selected_action_type="reply_once",
        uncertainty_level=0.4,
        channel="holo_cli",
        expression_budget=2,
        agent_tool_requests=[],
        fast_context_frame={"cache_hint": "stage132:abc", "line_count": 3, "char_count": 200},
    )

    bubbles = merge_stage132_reply_bubbles(
        first_reaction="First.",
        deep_text="Then the deeper packet explains the answer.",
        stream_plan=stream,
        channel="holo_cli",
    )

    assert [bubble.purpose for bubble in bubbles] == ["fast_reaction", "deep_continuation"]
    assert [bubble.text for bubble in bubbles] == ["First.", "Then the deeper packet explains the answer."]
    assert bubbles[1].delay_ms > bubbles[0].delay_ms


def test_stage132_processor_returns_visible_progressive_cli_bubbles(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = _ProgressiveRunner()
    processor = CodexCliProcessor(config, runner)  # type: ignore[arg-type]
    plan = processor.generate(_context("Make the fast/deep thought stream visible."), session_id="stage132")

    assert [call["budget_tag"] for call in runner.calls] == ["stage124_fast_packet", "chat_reply"]
    assert "Stage132 Fast Context Frame" in str(runner.calls[0]["prompt"])
    assert len(plan.bubbles) == 2
    assert [bubble.purpose for bubble in plan.bubbles] == ["fast_reaction", "deep_continuation"]
    assert plan.bubbles[0].text.startswith("I will first catch the intent")
    assert plan.debug["stage132_progressive_stream"]["round_count"] == 2
    assert plan.debug["stage132_progressive_stream"]["rounds"][0]["lane"] == "micro_fast"
    assert plan.debug["stage132_progressive_stream"]["rounds"][1]["lane"] in {"subject_main", "kernel_xhigh"}
