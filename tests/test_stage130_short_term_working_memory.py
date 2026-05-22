from __future__ import annotations

from pathlib import Path

from holo_host.config import load_config
from holo_host.memory_bridge import MemoryBridge
from holo_host.models import TurnContext
from holo_host.processors import (
    build_attention_state,
    build_short_term_working_memory_lines,
    build_turn_plan,
    normalize_external_speech_for_context,
    render_chat_prompt,
)
from holo_host.stage124_fast_deep_thought_loop import (
    build_stage124_fast_packet_prompt,
    stage124_deep_packet_guard,
)


def _packet(lines: list[str]) -> dict:
    return {
        "tier": "fast",
        "memory_route": "active_thread",
        "active_thread_state": {
            "continuity_summary": "user and Holo are discussing provider packets and short-term memory.",
            "scene_state": {
                "shared_frame": "live CLI diagnosis",
                "response_sketch": "continue the current debugging thread",
                "predicted_branches": ["user asks for continuation"],
            },
            "last_outbound_action": {"action_type": "reply_once"},
            "predictive_continuity": {
                "predicted_next_user_act": "continuation_or_correction",
                "likely_reference_targets": ["previous_task"],
            },
        },
        "recent_dialogue_window": {"lines": lines},
        "selected_action": {"action_type": "reply_once"},
        "state": {"emotion_state": {}},
    }


def _context(user_text: str, lines: list[str], *, channel: str = "holo_cli") -> TurnContext:
    packet = _packet(lines)
    return TurnContext(
        channel=channel,
        thread_key=f"{channel}:main",
        chat_name="HoloCLI",
        sender="Operator",
        user_text=user_text,
        sidecar=packet,
        mind_packet=packet,
        attention_state=build_attention_state(user_text, channel=channel),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={},
    )


def test_stage130_short_term_memory_keeps_recent_style_constraint() -> None:
    context = _context(
        "\u6700\u597d\u518d\u7ed9\u4f60\u505a\u4e00\u4e2a\u89c6\u89c9\u63a5\u53e3",
        [
            "user: \u4f60\u53ef\u4ee5\u8bd5\u7740\u4e0d\u8981\u518d\u7528\u8fd9\u4e48\u591aemoji\uff0c\u53ef\u4ee5\u5417\uff1f",
            "holo: \u53ef\u4ee5\u3002\u521a\u624d\u90a3\u4e32\u786e\u5b9e\u6492\u591a\u4e86\uff0c\u6536\u4f4f\u3002",
        ],
    )

    lines = build_short_term_working_memory_lines(context)
    prompt = render_chat_prompt(context, turn_plan=build_turn_plan(context, load_config(repo_root=Path.cwd())))

    assert any("tone_constraint: avoid frequent emoji" in line for line in lines)
    assert any("do not start with English 'I'" in line for line in lines)
    assert "Short Term Working Memory:" in prompt
    assert "tone_constraint: avoid frequent emoji" in prompt
    assert "do not start with English 'I'" in prompt


def test_stage130_short_followup_keeps_pending_research_task() -> None:
    context = _context(
        "\u770b\u4e00\u770b",
        [
            "user: \u6211\u4e0d\u6e05\u695a\uff0c\u4e16\u754c\u6a21\u578b\u8fd9\u4e2a\u6982\u5ff5\u4e5f\u624d\u63d0\u51fa\u6ca1\u591a\u4e45\uff0c\u53ef\u4ee5\u641c\u4e00\u641c\u8bba\u6587",
            "holo: \u6211\u53bb\u7ffb\u7ffb\u6700\u8fd1\u7684\u4e16\u754c\u6a21\u578b+\u5b9e\u65f6\u4ea4\u4e92\u65b9\u5411\u3002",
        ],
    )

    lines = build_short_term_working_memory_lines(context)
    prompt = render_chat_prompt(context, turn_plan=build_turn_plan(context, load_config(repo_root=Path.cwd())))

    assert any("pending_task: continue world-model paper/search thread" in line for line in lines)
    assert "pending_task: continue world-model paper/search thread" in prompt
    assert "do not answer as a fresh greeting" in prompt


def test_stage130_confused_followup_marks_previous_answer_as_misaligned() -> None:
    context = _context(
        "\uff1f\uff1f\uff1f",
        [
            "user: minecraft\u7b97\u4ec0\u4e48\u5440\uff0c\u8fd9\u4e2a\u6211\u53ef\u662f\u8001\u73a9\u5bb6\u4e86\uff0c\u4f60\u53ef\u9a97\u4e0d\u4e86\u6211",
            "holo: \u65e2\u7136\u4f60\u662f\u8001\u73a9\u5bb6\uff0c\u90a3\u6211\u8003\u8003\u4f60\u3002",
        ],
    )

    lines = build_short_term_working_memory_lines(context)

    assert any("repair_focus: previous reply likely missed the user's correction" in line for line in lines)
    assert any("do not quiz the user" in line for line in lines)


def test_stage130_fast_packet_prompt_includes_short_term_frame() -> None:
    prompt = build_stage124_fast_packet_prompt(
        user_text="\u600e\u4e48\u6837",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        short_term_lines=[
            "pending_task: continue world-model paper/search thread; do not answer as a fresh greeting.",
            "tone_constraint: avoid frequent emoji.",
        ],
    )

    assert "Short Term Working Memory:" in prompt
    assert "pending_task: continue world-model paper/search thread" in prompt
    assert "tone_constraint: avoid frequent emoji" in prompt


def test_stage130_deep_guard_for_contextual_continuation_without_shallow_reply() -> None:
    guard = stage124_deep_packet_guard("\u770b\u4e00\u770b", {"shallow_reply": ""})

    assert guard["required"] is True
    assert guard["reason"] == "short_contextual_followup"


def test_stage130_external_speech_normalizes_english_i_in_chinese_thread() -> None:
    context = _context(
        "\u4f60\u53ef\u4ee5\u4e0d\u8981\u4e2d\u82f1\u6df7\u7528\u5417\uff1f",
        ["user: \u4f60\u53ef\u4ee5\u8bd5\u7740\u4e0d\u8981\u518d\u7528\u8fd9\u4e48\u591aemoji\uff0c\u53ef\u4ee5\u5417\uff1f"],
    )

    normalized = normalize_external_speech_for_context(context, "I\u77e5\u9053\u4e86\uff0cI\u4ee5\u540e\u4f1a\u5c11\u7528\u3002")

    assert normalized == "\u6211\u77e5\u9053\u4e86\uff0c\u6211\u4ee5\u540e\u4f1a\u5c11\u7528\u3002"


def test_stage130_contextual_followups_are_not_silenced_as_fast_pings() -> None:
    assert MemoryBridge._query_signal("\u770b\u4e00\u770b")["low_signal"] is False
    assert MemoryBridge._query_signal("\u600e\u4e48\u6837")["low_signal"] is False
    assert MemoryBridge._query_signal("\u7ee7\u7eed")["low_signal"] is False
