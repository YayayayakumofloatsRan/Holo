from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from holo_host.agent_event_stream import render_agent_event_stream
from holo_host.config import load_config
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from holo_host.models import ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _operator_decision() -> dict:
    return {
        "schema": "holo.stage161.model_tool_arbitration.v1",
        "decision_id": "stage217:test-decision",
        "source": "model_arbitration",
        "goal_summary": "run registered market research operator",
        "intent_type": "market_research",
        "selected_action": "market_research_operator_run",
        "action_arguments": {"query": "NVIDIA AI infrastructure official SEC 10-K filing", "dry_run": True},
        "why_this_action": "model selected a registered operator",
        "required_observations": ["stage214_market_research_operator_run"],
        "can_answer_without_tool": False,
        "confidence": 0.9,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "report operator failure",
    }


def _fake_dispatch() -> dict:
    return {
        "schema": "holo.stage217.operator_dispatch.v1",
        "status": "executed",
        "operator_id": "market_research_operator_run",
        "selected_action": "market_research_operator_run",
        "required_observation": "stage214_market_research_operator_run",
        "capability_context_updates": {
            "stage215_market_research_operator_action": {
                "status": "executed",
                "selected_action": "market_research_operator_run",
                "operator_run_id": "stage214:fake",
                "phase_count": 2,
                "canonical_stop_reason": "final_answer_ready",
            },
            "stage214_market_research_operator_run": {
                "operator_run_id": "stage214:fake",
                "status": "ready",
                "operator_trajectory": [
                    {"phase": "plan", "status": "planned"},
                    {"phase": "finalize", "status": "finalized"},
                ],
                "final_visible_text": "Market research report: fake registry result.",
            },
        },
        "final_visible_text": "Market research report: fake registry result.",
        "canonical_stop_reason": "final_answer_ready",
    }


def test_operator_registry_exposes_market_operator_definition() -> None:
    from holo_host.operator_registry import get_operator_definition, operator_action_space_entries

    definition = get_operator_definition("market_research_operator_run")
    entries = {item["action_type"]: item for item in operator_action_space_entries()}

    assert definition["schema"] == "holo.stage217.operator_registry.v1"
    assert definition["operator_id"] == "market_research_operator_run"
    assert definition["required_observation"] == "stage214_market_research_operator_run"
    assert definition["implements_live_work"] is True
    assert entries["market_research_operator_run"]["observation_schema"]["ledger"] == "stage214_market_research_operator_run"


def test_dispatch_market_operator_returns_capability_updates() -> None:
    from holo_host.operator_registry import dispatch_operator_action

    dispatch = dispatch_operator_action(
        _operator_decision(),
        user_text="Please handle this research task.",
        metadata={"stage217_operator_registry_dry_run": True},
        channel="holo_cli",
        network_enabled=True,
    )

    assert dispatch["schema"] == "holo.stage217.operator_dispatch.v1"
    assert dispatch["status"] == "executed"
    assert dispatch["operator_id"] == "market_research_operator_run"
    updates = dispatch["capability_context_updates"]
    assert updates["stage215_market_research_operator_action"]["status"] == "executed"
    assert updates["stage214_market_research_operator_run"]["status"] == "ready"
    assert dispatch["final_visible_text"].startswith("Market research report:")


def test_dispatch_unknown_operator_is_rejected() -> None:
    from holo_host.operator_registry import dispatch_operator_action

    decision = {**_operator_decision(), "selected_action": "nonexistent_operator"}
    dispatch = dispatch_operator_action(
        decision,
        user_text="run something",
        metadata={},
        channel="holo_cli",
        network_enabled=True,
    )

    assert dispatch["status"] == "rejected"
    assert dispatch["canonical_stop_reason"] == "boundary_or_permission"
    assert dispatch["capability_context_updates"] == {}


def test_reply_path_uses_operator_registry_dispatch_for_model_selected_operator() -> None:
    class Stage217OperatorProcessor:
        name = "stage217_operator_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            return ReplyPlan(
                text="I will run the registered operator.",
                bubbles=[ReplyBubble("I will run the registered operator.")],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=1),
                emotion_state=dict(context.emotion_state),
                route="main",
                processor=self.name,
                session_id=session_id or "stage217-session",
                raw_text="I will run the registered operator.",
                timing_ms={"processor_ms": 5, "recall_reconstruct_ms": 0},
                debug={"stage161_model_tool_arbitration": _operator_decision()},
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        config.runtime.network_enabled = False
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=FakeMemory())
        service.processor = Stage217OperatorProcessor()
        try:
            with mock.patch("holo_host.reply_api.dispatch_operator_action", return_value=_fake_dispatch()) as dispatcher:
                result = service.handle_reply(
                    {
                        "chat_name": "HoloCLI",
                        "sender": "Operator",
                        "text": "Please handle this research task.",
                        "channel": "holo_cli",
                        "thread_key": "holo_cli:stage217",
                        "message_id": "stage217-registry-dispatch-1",
                        "metadata": {},
                    }
                )
        finally:
            close_service_handles(service)

    dispatcher.assert_called_once()
    assert result["stage217_operator_dispatch"]["status"] == "executed"
    assert result["stage214_market_research_operator_run"]["status"] == "ready"
    assert result["stage160r_agent_loop_fsm"]["canonical_stop_reason"] == "final_answer_ready"
    assert result["text"] == "Market research report: fake registry result."
    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])
    assert "[operator_dispatch] id=market_research_operator_run status=executed" in rendered


def test_operator_dispatch_public_payload_has_no_private_reasoning() -> None:
    payload = {
        "stage217_operator_dispatch": {
            **_fake_dispatch(),
            "reasoning_content": "private internal scratchpad",
            "internal_messages": [{"content": "private"}],
        }
    }

    clean = sanitize_public_metadata(payload)
    blob = json.dumps(clean, ensure_ascii=False)
    ok, paths = assert_no_private_reasoning(clean)

    assert ok, paths
    assert "private internal scratchpad" not in blob
    assert "internal_messages" not in blob
