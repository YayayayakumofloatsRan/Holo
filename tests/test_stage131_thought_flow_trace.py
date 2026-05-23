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
from holo_host.stage131_thought_flow_trace import (
    build_stage131_thought_flow_trace,
    render_stage131_cli_ct,
)


def _packet(lines: list[str]) -> dict:
    return {
        "tier": "fast",
        "memory_route": "active_thread",
        "recent_dialogue_window": {"lines": lines},
        "active_thread_state": {
            "continuity_summary": "user and Holo are debugging the internal thought flow.",
            "scene_state": {
                "shared_frame": "stage131 live CLI diagnosis",
                "response_sketch": "continue the flow explanation when the user confirms",
                "predicted_branches": ["user gives a short acknowledgement"],
            },
            "last_outbound_action": {"action_type": "reply_once"},
            "predictive_continuity": {
                "predicted_next_user_act": "short acknowledgement to continue",
                "likely_reference_targets": ["previous_open_loop"],
            },
        },
        "selected_action": {"action_type": "reply_once"},
        "state": {"emotion_state": {}},
    }


def _context(user_text: str, lines: list[str]) -> TurnContext:
    packet = _packet(lines)
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage131",
        chat_name="HoloCLIStage131",
        sender="Operator",
        user_text=user_text,
        sidecar=packet,
        mind_packet=packet,
        attention_state=build_attention_state(user_text, channel="holo_cli"),
        emotion_state={},
        history=[],
        metadata={},
        capability_context={},
    )


def test_stage131_chinese_reference_question_is_not_silenced() -> None:
    signal = MemoryBridge._query_signal("什么流程")

    assert signal["question_like"] is True
    assert signal["low_signal"] is False


def test_stage131_short_ack_after_open_loop_requires_reply() -> None:
    context = _context(
        "行",
        [
            "user: 没关系，这个过程完全是可以弥补的",
            "holo: 你这么说我就放心多了。那我们现在继续把刚才的流程走完？",
        ],
    )

    assert MemoryBridge.stage131_short_turn_requires_reply("行", context.mind_packet) is True
    lines = build_short_term_working_memory_lines(context)
    prompt = render_chat_prompt(context, turn_plan=build_turn_plan(context, load_config(repo_root=Path.cwd())))

    assert any("pending_open_loop" in line for line in lines)
    assert "the user accepted a previous open continuation" in prompt


def test_stage131_plain_ack_without_open_loop_can_stay_low_signal() -> None:
    assert MemoryBridge.stage131_short_turn_requires_reply("行", {"recent_dialogue_window": {"lines": []}}) is False


def test_stage131_contextual_gate_reads_packet_when_runtime_context_is_thin() -> None:
    packet = {"recent_dialogue_window": {"lines": ["holo: 好，继续。"]}}

    assert MemoryBridge.stage131_contextual_reply_required("行", {"channel": "holo_cli"}, packet) is True


def test_stage131_active_fast_packet_keeps_minimal_recent_dialogue_for_gate() -> None:
    class Graph:
        def recent_dialogue_window(self, **_: object) -> dict:
            return {
                "lines": ["user: 请只回复这一句：好，继续。", "holo: 好，继续。"],
                "messages": [],
                "window_size": 2,
                "source": "test",
            }

    bridge = object.__new__(MemoryBridge)
    bridge.graph = Graph()
    bridge._finalize_stage2_packet = lambda packet, **_: packet
    packet = bridge._active_thread_fast_packet(
        "行",
        context={"channel": "holo_cli", "thread_key": "holo_cli:stage131", "chat_name": "HoloCLIStage131"},
        active_state={
            "present": True,
            "continuity_summary": "stage131 continuation",
            "last_user_intent": "continue",
            "last_outbound_action": {"action_type": "reply_once"},
            "predictive_continuity": {"reflex_eligibility": True, "active_prediction_confidence": 0.7},
        },
        signal=MemoryBridge._query_signal("行"),
    )

    assert packet["recent_dialogue_window"]["lines"] == ["user: 请只回复这一句：好，继续。", "holo: 好，继续。"]
    assert MemoryBridge.stage131_short_turn_requires_reply("行", packet) is True


def test_stage131_emoji_preference_is_hard_scrubbed_from_chinese_visible_reply() -> None:
    context = _context(
        "说了不要用emoji了",
        [
            "user: 你可以试着不要再用这么多emoji，可以吗？",
            "holo: 可以。刚才那串确实撒多了，收住。",
        ],
    )

    normalized = normalize_external_speech_for_context(context, "记住了，之后尽量不用 😏")

    assert "😏" not in normalized
    assert normalized == "记住了，之后尽量不用"


def test_stage131_cli_ct_renders_packet_flow_and_background_usage() -> None:
    trace = build_stage131_thought_flow_trace(
        usage_payload={
            "summary": {"total_tokens": 450, "by_lane": {"micro_fast": 120, "deep": 330}},
            "items": [
                {
                    "task_type": "reply",
                    "lane": "micro_fast",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "prompt_tokens": 80,
                    "completion_tokens": 40,
                    "total_tokens": 120,
                    "duration_ms": 610,
                    "thread_key": "holo_cli:stage131",
                    "created_at": "2026-05-23T10:00:00Z",
                    "metadata": {"selected_action_type": "reply_once"},
                },
                {
                    "task_type": "reflect",
                    "lane": "background",
                    "provider": "deepseek",
                    "model": "deepseek-chat",
                    "prompt_tokens": 200,
                    "completion_tokens": 130,
                    "total_tokens": 330,
                    "duration_ms": 1500,
                    "thread_key": "",
                    "created_at": "2026-05-23T10:01:00Z",
                    "metadata": {},
                },
            ],
        },
        deliberation_payload={
            "thread_key": "holo_cli:stage131",
            "channel": "holo_cli",
            "entries": [
                {
                    "entry_type": "stage124_thought_loop",
                    "selected_action": "reply_once",
                    "payload": {
                        "selected_action": {"action_type": "reply_once"},
                        "stage124": {"fast_packet_needed": True, "deep_packet_needed": True},
                        "action_market": [{"action_type": "reply_once", "score": 0.81}],
                    },
                    "created_at": "2026-05-23T10:00:01Z",
                }
            ],
        },
        thread_key="holo_cli:stage131",
        channel="holo_cli",
        chat_name="HoloCLIStage131",
        limit=6,
    )
    rendered = render_stage131_cli_ct(trace)

    assert "STAGE131 BIOMIMETIC CT" in rendered
    assert "FAST packet" in rendered
    assert "DEEP packet" in rendered
    assert "ACTION reply_once" in rendered
    assert "USAGE total_tokens=450" in rendered
    assert "BACKGROUND reflect tokens=330" in rendered


def test_stage131_cli_ct_renders_stage132_progressive_rounds() -> None:
    trace = build_stage131_thought_flow_trace(
        usage_payload={
            "summary": {"total_tokens": 520, "by_lane": {"micro_fast": 140, "subject_main": 380}},
            "items": [
                {
                    "task_type": "reply",
                    "lane": "micro_fast",
                    "provider": "deepseek",
                    "model": "deepseek-v4-flash",
                    "total_tokens": 140,
                    "duration_ms": 430,
                    "thread_key": "holo_cli:stage132",
                    "metadata": {"budget_tag": "stage124_fast_packet"},
                },
                {
                    "task_type": "reply",
                    "lane": "subject_main",
                    "provider": "deepseek",
                    "model": "deepseek-v4",
                    "total_tokens": 380,
                    "duration_ms": 1680,
                    "thread_key": "holo_cli:stage132",
                    "metadata": {"budget_tag": "chat_reply"},
                },
            ],
        },
        deliberation_payload={
            "entries": [
                {
                    "entry_type": "execute_action",
                    "payload": {
                        "result": {
                            "stage132_progressive_stream": {
                                "round_count": 2,
                                "cache_hint": "stage132:abc123",
                                "fast_context_lines": 8,
                                "rounds": [
                                    {"index": 0, "lane": "micro_fast", "purpose": "fast_reaction", "visible": True},
                                    {"index": 1, "lane": "subject_main", "purpose": "deep_continuation", "visible": True},
                                ],
                            }
                        }
                    },
                    "created_at": "2026-05-23T10:10:00Z",
                    "thread_key": "holo_cli:stage132",
                }
            ],
        },
        thread_key="holo_cli:stage132",
        channel="holo_cli",
        chat_name="HoloCLIStage132",
        limit=6,
    )

    rendered = render_stage131_cli_ct(trace)

    assert "STAGE132 STREAM rounds=2 cache=stage132:abc123 context_lines=8" in rendered
    assert "ROUND 0 lane=micro_fast purpose=fast_reaction visible=yes" in rendered
    assert "ROUND 1 lane=subject_main purpose=deep_continuation visible=yes" in rendered
