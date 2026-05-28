from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from holo_host.agent_event_stream import render_agent_event_stream
from holo_host.agent_intent_frame import build_intent_frame
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.config import load_config
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from holo_host.model_tool_arbitration import derive_arbitration_from_stage152
from holo_host.models import ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore
from holo_host.tool_action_space import build_tool_action_space

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _operator_decision() -> dict:
    return {
        "schema": "holo.stage161.model_tool_arbitration.v1",
        "decision_id": "stage216:test-decision",
        "source": "model_arbitration",
        "goal_summary": "run a complete filing-grounded market research operator trajectory",
        "intent_type": "market_research",
        "selected_action": "market_research_operator_run",
        "action_arguments": {"query": "NVIDIA AI infrastructure official SEC 10-K filing"},
        "why_this_action": "the model selected the full market research operator from the action space",
        "required_observations": ["stage214_market_research_operator_run"],
        "can_answer_without_tool": False,
        "confidence": 0.91,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "report attempted operator failure",
    }


def test_action_space_exposes_market_research_operator_run() -> None:
    actions = {item["action_type"]: item for item in build_tool_action_space()}

    action = actions["market_research_operator_run"]

    assert action["requires_network"] is True
    assert action["is_readonly"] is True
    assert action["observation_schema"]["ledger"] == "stage214_market_research_operator_run"
    assert "operator" in action["description"].lower()


def test_stage152_tool_call_derives_operator_action_requirement() -> None:
    decision = derive_arbitration_from_stage152(
        {
            "tool_calls": [
                {
                    "name": "market_research_operator_run",
                    "arguments": {"query": "NVIDIA AI infrastructure official SEC 10-K filing"},
                }
            ]
        },
        user_text="Do the full research.",
    )

    assert decision["selected_action"] == "market_research_operator_run"
    assert decision["required_observations"] == ["stage214_market_research_operator_run"]
    assert decision["can_answer_without_tool"] is False


def test_fsm_marks_operator_run_executed_when_stage214_ready() -> None:
    frame = build_intent_frame("Do the full research.", channel="holo_cli")

    report = run_agent_loop_fsm(
        intent_frame=frame,
        model_arbitration=_operator_decision(),
        stage215_market_research_operator_action={
            "status": "executed",
            "selected_action": "market_research_operator_run",
            "operator_run_id": "stage214:ready",
            "canonical_stop_reason": "final_answer_ready",
        },
        stage214_market_research_operator_run={
            "operator_run_id": "stage214:ready",
            "status": "ready",
            "final_visible_text": "Market research report: NVIDIA.",
            "failure_reasons": [],
        },
        final_text="Market research report: NVIDIA.",
    )

    assert report["selected_action"] == "market_research_operator_run"
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert any(
        step["phase"] == "act_or_skip"
        and step["selected_action"] == "market_research_operator_run"
        and step["action_status"] == "executed"
        for step in report["steps"]
    )
    assert report["stage214_market_research_operator_run"]["status"] == "ready"


def test_reply_path_executes_model_selected_operator_action() -> None:
    class Stage216ModelOperatorProcessor:
        name = "stage216_model_operator_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            return ReplyPlan(
                text="I will prepare the research.",
                bubbles=[ReplyBubble("I will prepare the research.")],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=1),
                emotion_state=dict(context.emotion_state),
                route="main",
                processor=self.name,
                session_id=session_id or "stage216-session",
                raw_text="I will prepare the research.",
                timing_ms={"processor_ms": 5, "recall_reconstruct_ms": 0},
                debug={"stage161_model_tool_arbitration": _operator_decision()},
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        config.runtime.network_enabled = True
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=FakeMemory())
        service.processor = Stage216ModelOperatorProcessor()
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Operator",
                    "text": "Please handle this research task.",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:stage216",
                    "message_id": "stage216-model-operator-1",
                    "metadata": {"stage216_market_research_operator_dry_run": True},
                }
            )
        finally:
            close_service_handles(service)

    action = result["stage215_market_research_operator_action"]
    run = result["stage214_market_research_operator_run"]
    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])

    assert action["status"] == "executed"
    assert action["selected_action"] == "market_research_operator_run"
    assert run["status"] == "ready"
    assert result["stage160r_agent_loop_fsm"]["selected_action"] == "market_research_operator_run"
    assert result["stage160r_agent_loop_fsm"]["canonical_stop_reason"] == "final_answer_ready"
    assert result["text"].startswith("Market research report:")
    assert "[model_decide] selected=market_research_operator_run" in rendered
    assert "[market_operator] phase=finalize status=finalized" in rendered


def test_no_private_reasoning_in_stage216_operator_payload() -> None:
    payload = {
        "stage161_model_tool_arbitration": {
            **_operator_decision(),
            "reasoning_content": "private internal scratchpad",
        },
        "stage215_market_research_operator_action": {
            "status": "executed",
            "selected_action": "market_research_operator_run",
        },
    }

    clean = sanitize_public_metadata(payload)
    blob = json.dumps(clean, ensure_ascii=False)
    ok, paths = assert_no_private_reasoning(clean)

    assert ok, paths
    assert "private internal scratchpad" not in blob
    assert "reasoning_content" not in blob
