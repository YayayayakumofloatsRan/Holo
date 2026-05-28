from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

from holo_host.agent_event_stream import render_agent_event_stream
from holo_host.agent_loop_fsm import run_agent_loop_fsm
from holo_host.config import load_config
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.model_tool_arbitration import derive_arbitration_from_stage152
from holo_host.models import ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.store import QueueStore

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage218_mock_search",
        "results": [
            {
                "title": "OpenAI Codex CLI documentation",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation for a terminal coding agent.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "stage218_mock_open",
        "html": (
            "<html><title>Codex CLI</title><body>"
            "Codex CLI official documentation describes an agent that can search code, edit files, "
            "run commands, and show auditable progress."
            "</body></html>"
        ),
    }


def _web_operator_decision() -> dict:
    return {
        "schema": "holo.stage161.model_tool_arbitration.v1",
        "decision_id": "stage218:test-decision",
        "source": "model_arbitration",
        "goal_summary": "research Codex CLI official documentation",
        "intent_type": "web_lookup",
        "selected_action": "web_research_operator_run",
        "action_arguments": {"query": "OpenAI Codex CLI official documentation", "max_queries": 2},
        "why_this_action": "model selected the web research operator",
        "required_observations": ["stage218_web_research_operator_run"],
        "can_answer_without_tool": False,
        "confidence": 0.91,
        "stop_if_observed": "final_answer_ready",
        "fallback_if_failed": "report web research failure",
    }


def test_operator_registry_exposes_web_research_operator() -> None:
    from holo_host.operator_registry import get_operator_definition, operator_action_space_entries

    definition = get_operator_definition("web_research_operator_run")
    entries = {item["action_type"]: item for item in operator_action_space_entries()}

    assert definition["schema"] == "holo.stage217.operator_registry.v1"
    assert definition["operator_id"] == "web_research_operator_run"
    assert definition["required_observation"] == "stage218_web_research_operator_run"
    assert definition["implements_live_work"] is True
    assert entries["web_research_operator_run"]["observation_schema"]["ledger"] == "stage218_web_research_operator_run"


def test_dispatch_web_research_operator_runs_crawler_and_journal() -> None:
    from holo_host.operator_registry import dispatch_operator_action

    dispatch = dispatch_operator_action(
        _web_operator_decision(),
        user_text="Search the official Codex CLI docs and summarize sources.",
        metadata={},
        channel="holo_cli",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
    )

    assert dispatch["schema"] == "holo.stage217.operator_dispatch.v1"
    assert dispatch["status"] == "executed"
    updates = dispatch["capability_context_updates"]
    run = updates["stage218_web_research_operator_run"]
    assert run["schema"] == "holo.stage218.web_research_operator_run.v1"
    assert run["status"] == "ready"
    assert run["stage186_live_crawler_search"]["status"] == "sufficient"
    assert run["stage212_action_journal"]["status"] == "recorded"
    assert run["source_urls"] == ["https://developers.openai.com/codex/cli"]
    assert dispatch["final_visible_text"].startswith("Web research brief:")


def test_dispatch_web_research_operator_network_disabled_records_rejection() -> None:
    from holo_host.operator_registry import dispatch_operator_action

    dispatch = dispatch_operator_action(
        _web_operator_decision(),
        user_text="Search the official Codex CLI docs.",
        metadata={},
        channel="holo_cli",
        network_enabled=False,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
    )

    run = dispatch["capability_context_updates"]["stage218_web_research_operator_run"]
    assert dispatch["status"] == "failed"
    assert dispatch["canonical_stop_reason"] == "boundary_or_permission"
    assert run["status"] == "rejected"
    assert run["web_observation_ledger"][0]["status"] == "rejected_network_disabled"
    assert "network_disabled" in dispatch["final_visible_text"]


def test_stage152_arbitration_maps_web_research_operator_required_observation() -> None:
    decision = derive_arbitration_from_stage152(
        {
            "tool_calls": [
                {
                    "name": "web_research_operator_run",
                    "arguments": {"query": "Codex CLI official docs"},
                }
            ]
        },
        user_text="Search Codex CLI official docs.",
    )

    assert decision["selected_action"] == "web_research_operator_run"
    assert decision["required_observations"] == ["stage218_web_research_operator_run"]


def test_fsm_closes_ready_web_research_operator() -> None:
    report = run_agent_loop_fsm(
        intent_frame={
            "goal_id": "stage218-goal",
            "raw_user_text_exact": "Search Codex CLI official docs.",
            "intent_type": "web_lookup",
            "required_observations": ["stage218_web_research_operator_run"],
        },
        model_arbitration=_web_operator_decision(),
        stage218_web_research_operator_run={
            "operator_run_id": "stage218:ready",
            "status": "ready",
            "operator_trajectory": [{"phase": "finalize", "status": "ready"}],
            "final_visible_text": "Web research brief: Codex CLI official docs.",
        },
        final_text="Web research brief: Codex CLI official docs.",
    )

    assert report["selected_action"] == "web_research_operator_run"
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert any(step["selected_action"] == "web_research_operator_run" for step in report["steps"])
    assert report["stage218_web_research_operator_run"]["status"] == "ready"


def test_reply_path_dispatches_web_research_operator_and_renders_trace() -> None:
    class Stage218Processor:
        name = "stage218_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            return ReplyPlan(
                text="I will run the web research operator.",
                bubbles=[ReplyBubble("I will run the web research operator.")],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=1),
                emotion_state=dict(context.emotion_state),
                route="main",
                processor=self.name,
                session_id=session_id or "stage218-session",
                raw_text="I will run the web research operator.",
                timing_ms={"processor_ms": 5, "recall_reconstruct_ms": 0},
                debug={"stage161_model_tool_arbitration": _web_operator_decision()},
            )

    fake_dispatch = {
        "schema": "holo.stage217.operator_dispatch.v1",
        "status": "executed",
        "operator_id": "web_research_operator_run",
        "selected_action": "web_research_operator_run",
        "required_observation": "stage218_web_research_operator_run",
        "capability_context_updates": {
            "stage218_web_research_operator_run": {
                "schema": "holo.stage218.web_research_operator_run.v1",
                "operator_run_id": "stage218:fake",
                "status": "ready",
                "operator_trajectory": [
                    {"phase": "crawl", "status": "sufficient", "source_count": 1},
                    {"phase": "finalize", "status": "ready", "source_count": 1},
                ],
                "source_urls": ["https://developers.openai.com/codex/cli"],
                "final_visible_text": "Web research brief: fake registry result.",
            }
        },
        "final_visible_text": "Web research brief: fake registry result.",
        "canonical_stop_reason": "final_answer_ready",
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        config.runtime.network_enabled = True
        store = QueueStore(config.runtime.db_path)
        store.initialize()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=FakeMemory())
        service.processor = Stage218Processor()
        try:
            with mock.patch("holo_host.reply_api.dispatch_operator_action", return_value=fake_dispatch) as dispatcher:
                result = service.handle_reply(
                    {
                        "chat_name": "HoloCLI",
                        "sender": "Operator",
                        "text": "Search Codex CLI official docs.",
                        "channel": "holo_cli",
                        "thread_key": "holo_cli:stage218",
                        "message_id": "stage218-web-operator-1",
                        "metadata": {},
                    }
                )
        finally:
            close_service_handles(service)

    dispatcher.assert_called_once()
    assert result["stage217_operator_dispatch"]["operator_id"] == "web_research_operator_run"
    assert result["stage218_web_research_operator_run"]["status"] == "ready"
    assert result["stage160r_agent_loop_fsm"]["canonical_stop_reason"] == "final_answer_ready"
    assert result["text"] == "Web research brief: fake registry result."
    rendered = render_agent_event_stream(result["stage153_agent_event_stream"])
    assert "[model_decide] selected=web_research_operator_run" in rendered
    assert "[operator_dispatch] id=web_research_operator_run status=executed" in rendered
    assert "[web_research_operator] phase=finalize status=ready sources=1 stop=final_answer_ready" in rendered


def test_web_research_operator_payload_has_no_private_reasoning() -> None:
    from holo_host.operator_registry import dispatch_operator_action

    dispatch = dispatch_operator_action(
        _web_operator_decision(),
        user_text="Search Codex CLI official docs.",
        metadata={"reasoning_content": "private scratchpad"},
        channel="holo_cli",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
    )
    blob = json.dumps(dispatch, ensure_ascii=False)
    ok, paths = assert_no_private_reasoning(dispatch)

    assert ok, paths
    assert "private scratchpad" not in blob
    assert "reasoning_content" not in blob


def test_stage135_topology_includes_web_research_operator_node() -> None:
    from holo_host.stage135_i_state_topology import build_stage135_i_state_topology

    payload = build_stage135_i_state_topology(
        user_text="Search Codex CLI official docs.",
        stage218_web_research_operator_run={
            "schema": "holo.stage218.web_research_operator_run.v1",
            "status": "ready",
            "operator_trajectory": [
                {"phase": "plan", "status": "planned"},
                {"phase": "finalize", "status": "ready"},
            ],
            "source_urls": ["https://developers.openai.com/codex/cli"],
            "canonical_stop_reason": "final_answer_ready",
        },
    )

    assert payload["metrics"]["web_research_operator_node_count"] == 1
    assert payload["metrics"]["web_research_operator_status"] == "ready"
    assert payload["metrics"]["web_research_operator_source_count"] == 1
