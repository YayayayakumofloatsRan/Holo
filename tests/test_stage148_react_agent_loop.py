from __future__ import annotations

import json
import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import AttentionState, ReplyPlan, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage148_react_agent_loop import (
    STAGE148_SCHEMA,
    build_stage148_react_state,
    stage148_prompt_lines,
)
from holo_host.store import QueueStore
from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _history() -> list[dict[str, object]]:
    return [
        {"direction": "inbound", "body_text": "我们之前说过些什么？", "created_at": "2026-05-26T06:00:01Z"},
        {"direction": "outbound", "body_text": "我需要先看最近上下文。", "created_at": "2026-05-26T06:00:02Z"},
        {"direction": "inbound", "body_text": "我跟你反复说过了，不要用emoji", "created_at": "2026-05-26T06:00:03Z"},
        {"direction": "outbound", "body_text": "明白，之后不用。", "created_at": "2026-05-26T06:00:04Z"},
    ]


def test_stage148_separates_raw_events_from_reusable_state_memory() -> None:
    report = build_stage148_react_state(
        user_text="三句以前，我说了什么？",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )

    assert report["schema"] == STAGE148_SCHEMA
    assert report["event_log"]["event_count"] >= 5
    assert report["event_log"]["retention"] == "raw_recent_turns"
    assert report["reusable_state_memory"]["memory_is_not_chat_log"] is True
    slot_types = {slot["slot_type"] for slot in report["reusable_state_memory"]["slots"]}
    assert "current_user_turn" in slot_types
    assert "recent_correction" in slot_types
    assert "unresolved_question" in slot_types
    assert "action_space" in slot_types


def test_stage148_extracts_corrections_as_reusable_constraints() -> None:
    report = build_stage148_react_state(
        user_text="我们继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )

    constraints = [
        slot["summary"]
        for slot in report["reusable_state_memory"]["slots"]
        if slot["slot_type"] == "recent_correction"
    ]
    assert any("emoji" in item.lower() and "avoid" in item.lower() for item in constraints)
    assert report["react_loop"]["observe"]["status"] == "perceived"
    assert report["react_loop"]["plan"]["selected_action_hint"] in {"direct_answer", "memory_recall", "clarify", "tool_first"}


def test_stage148_react_loop_prefers_memory_recall_when_current_turn_asks_prior_context() -> None:
    report = build_stage148_react_state(
        user_text="三句以前，我说了什么？",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )

    plan = report["react_loop"]["plan"]
    assert plan["selected_action_hint"] == "memory_recall"
    assert "memory_recall" in plan["action_space"]
    assert "recent_event_log" in plan["required_observations"]
    assert report["react_loop"]["act"]["authority"] == "host_gated"


def test_stage148_prompt_lines_are_structured_not_debug_labels_for_visible_reply() -> None:
    report = build_stage148_react_state(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )

    lines = stage148_prompt_lines(report)
    joined = "\n".join(lines)
    assert "memory_is_state_not_chat_log" in joined
    assert "react_plan=" in joined
    assert "holo.stage148" not in joined


def test_render_chat_prompt_includes_stage148_reusable_state() -> None:
    report = build_stage148_react_state(
        user_text="继续",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )
    context = TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        user_text="继续",
        sidecar={"stage148_react_state": report, "selected_action": {"action_type": "reply_once"}},
        mind_packet={"stage148_react_state": report, "selected_action": {"action_type": "reply_once"}},
        attention_state=AttentionState(primary_focus="direct_answer", reply_goal="answer"),
        emotion_state={},
        history=_history(),
    )

    prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", fast_path=False, history_window=4))

    assert "Reusable State Memory:" in prompt
    assert "ReAct State:" in prompt
    assert "memory_is_state_not_chat_log" in prompt


def test_reply_api_propagates_stage148_metadata_to_reply_and_archive() -> None:
    class CapturingProcessor:
        name = "capturing_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            stage148 = dict(context.mind_packet.get("stage148_react_state", {}))
            return ReplyPlan(
                text="收到，我会基于当前状态继续。",
                raw_text="收到，我会基于当前状态继续。",
                bubbles=[],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=1),
                emotion_state={},
                route="main",
                processor=self.name,
                session_id=session_id,
                debug={"stage148_react_state": stage148},
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=FakeMemory())
        service.processor = CapturingProcessor()
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "HoloCLI",
                    "text": "我跟你反复说过了，不要用emoji",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage148-1",
                }
            )
            second = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "HoloCLI",
                    "text": "三句以前，我说了什么？",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:main",
                    "message_id": "stage148-2",
                }
            )

            assert result["action"] == "reply"
            assert second["action"] == "reply"
            assert second["stage148_react_state"]["schema"] == STAGE148_SCHEMA
            assert second["stage148_react_plan_action"] == "memory_recall"
            outbound = store.recent_thread_messages(int(store.find_thread(channel="holo_cli", thread_key="holo_cli:main")["id"]), 1)[0]
            metadata = json.loads(outbound["payload_json"])["metadata"]
            assert metadata["stage148_react_state"]["schema"] == STAGE148_SCHEMA
            assert metadata["stage148_react_plan_action"] == "memory_recall"
        finally:
            close_service_handles(service)


def test_stage135_topology_exposes_stage148_react_loop_node() -> None:
    report = build_stage148_react_state(
        user_text="三句以前，我说了什么？",
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        history=_history(),
        sidecar={"selected_action": {"action_type": "reply_once"}},
    )
    context = TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:main",
        chat_name="HoloCLI",
        sender="HoloCLI",
        user_text="三句以前，我说了什么？",
        sidecar={"stage148_react_state": report},
        mind_packet={"stage148_react_state": report},
        attention_state=AttentionState(primary_focus="direct_answer", reply_goal="answer"),
        emotion_state={},
        history=_history(),
    )

    topology = build_stage135_i_state_topology(context=context)

    assert topology["metrics"]["react_loop_node_count"] == 1
    assert topology["metrics"]["react_loop_plan_action"] == "memory_recall"
    assert topology["metrics"]["reusable_state_slot_count"] >= 3
