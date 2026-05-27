from __future__ import annotations

import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.context_compiler import (
    CONTEXT_COMPILER_SCHEMA,
    compile_context_memory,
    render_context_compiler_prompt_lines,
    repair_visible_compact_leak,
)
from holo_host.interactive_cli import InteractiveCliSession
from holo_host.models import AttentionState, ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage150_context_memory_fabric import build_stage150_context_memory_fabric
from holo_host.store import QueueStore
from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _stage150_fabric(*, user_text: str = "Continue Stage156 exactly.") -> dict:
    return build_stage150_context_memory_fabric(
        user_text=user_text,
        channel="holo_cli",
        thread_key="holo_cli:stage156",
        chat_name="HoloCLI",
        sidecar={
            "stage149_user_directives": {
                "status": "user_directives_active",
                "hard_directive_count": 1,
                "directives": [
                    {
                        "directive_type": "style",
                        "summary": "do not use emoji",
                    }
                ],
            },
            "stage148_react_state": {
                "reusable_state_memory": {
                    "slots": [
                        {
                            "slot_id": "loop:stage156",
                            "slot_type": "unresolved_question",
                            "summary": "open loop: wire Stage156 compiler into runtime",
                            "priority": 0.9,
                        }
                    ]
                }
            },
            "project_state_graph": {
                "schema": "holo.stage155.project_state_graph.v1",
                "project": "Holo",
                "active_project": {"title": "Holo"},
                "active_tasks": [{"title": "Implement Stage156 context compiler", "status": "active"}],
                "latest_decisions": [{"title": "Keep compact internal"}],
                "open_questions": [{"title": "How should cache metrics surface?", "status": "open"}],
                "next_actions": [{"title": "Run Stage156 targeted tests", "status": "open"}],
                "blocked_items": [],
            },
            "tool_observation_ledger": [
                {
                    "tool": "workspace_search",
                    "status": "ok",
                    "summary": "found context compiler integration point in processors.py",
                    "confidence": 0.9,
                }
            ],
            "recent_dialogue_window": {
                "lines": [
                    "# In app browser:",
                    "Current URL: http://127.0.0.1:8004/health",
                    "Holo CLI chat | channel=holo_cli thread=holo_cli:main chat=HoloCLI",
                    "Continue Stage156 exactly.",
                    "Continue Stage156 exactly.",
                ]
            },
        },
    )


def test_compile_preserves_exact_user_request_and_hard_directives() -> None:
    fabric = _stage150_fabric(user_text="Stage156 must preserve THIS exact request.")

    report = compile_context_memory(
        fabric,
        current_user_request="Stage156 must preserve THIS exact request.",
    )

    assert report["schema"] == CONTEXT_COMPILER_SCHEMA
    assert report["current_user_request_exact"] == "Stage156 must preserve THIS exact request."
    assert "Stage156 must preserve THIS exact request." in report["dynamic_turn_block"]
    assert "do not use emoji" in report["directive_block"]
    assert "I compacted context" not in "\n".join(render_context_compiler_prompt_lines(report))


def test_stable_prefix_excludes_dynamic_observations_and_suffix_keeps_latest_observation() -> None:
    report = compile_context_memory(_stage150_fabric())

    assert "workspace_search" not in report["stable_prefix"]
    assert "found context compiler integration point" in report["observation_block"]
    assert "Implement Stage156 context compiler" in report["project_instruction_block"]


def test_tool_memory_visual_observations_dict_is_compiled_into_observation_block() -> None:
    fabric = {
        "schema": "holo.stage150.context_memory_fabric.v1",
        "working_context_packet": {
            "user_goal": {"current_user_request_exact": "Use the latest tool observation."},
            "tool_memory_visual_observations": {
                "tool_observations": [
                    {
                        "family": "tool",
                        "source_family": "workspace_search",
                        "status": "ok",
                        "summary": "searched processors.py for stage150 prompt lines",
                    }
                ]
            },
        },
    }

    report = compile_context_memory(fabric, current_user_request="Use the latest tool observation.")

    assert "searched processors.py" in report["observation_block"]


def test_background_compact_filters_noise_and_preserves_open_loops() -> None:
    report = compile_context_memory(_stage150_fabric())
    compact = report["background_compact"]
    rendered = " ".join(str(value) for value in compact.values())

    assert "127.0.0.1" not in rendered
    assert "Holo CLI chat" not in rendered
    assert "wire Stage156 compiler into runtime" in compact["open_loop_summary"]
    assert compact["user_visible"] is False


def test_budget_truncates_low_priority_sections_before_directives() -> None:
    noisy_fabric = _stage150_fabric()
    packet = noisy_fabric["working_context_packet"]
    packet["evidence_ledger_view"] = [
        {
            "family": "tool",
            "status": "ok",
            "summary": "observation " + ("long " * 200),
        }
        for _ in range(8)
    ]

    report = compile_context_memory(noisy_fabric, max_prompt_tokens=180)

    assert "observation_block" in report["truncated_sections"]
    assert "directive_block" not in report["truncated_sections"]
    assert "do not use emoji" in report["directive_block"]


def test_cache_metrics_are_recorded_from_provider_usage() -> None:
    report = compile_context_memory(
        _stage150_fabric(),
        usage={"prompt_cache_hit_tokens": 75, "prompt_cache_miss_tokens": 25},
    )

    assert report["cache_hit_tokens"] == 75
    assert report["cache_miss_tokens"] == 25
    assert report["cache_hit_ratio"] == 0.75


def test_render_chat_prompt_includes_stage156_compiled_context_state() -> None:
    fabric = _stage150_fabric()
    compiled = compile_context_memory(fabric, current_user_request="Compile this turn.")
    packet = {"stage150_context_memory_fabric": fabric, "stage156_context_compiler": compiled}
    context = TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage156",
        chat_name="HoloCLI",
        sender="Ran",
        user_text="Compile this turn.",
        sidecar=packet,
        mind_packet=packet,
        attention_state=AttentionState(primary_focus="stage156", reply_goal="answer"),
        emotion_state={},
        history=[],
    )

    prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", bubble_target=1))

    assert "Engineering Context State:" in prompt
    assert "Context Compiler State:" in prompt
    assert "stable_prefix_tokens=" in prompt
    assert "current_user_request_exact=Compile this turn." in prompt


def test_reply_service_propagates_stage156_metadata_to_result_archive_and_processor_context() -> None:
    class Stage156MetadataProcessor:
        name = "stage156_metadata_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            self.seen_context = context
            return ReplyPlan(
                text="Stage156 context is compiled.",
                bubbles=[ReplyBubble("Stage156 context is compiled.")],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=1),
                route="main",
                processor=self.name,
                session_id=session_id or "stage156-session",
                raw_text="Stage156 context is compiled.",
                timing_ms={"processor_ms": 5, "recall_reconstruct_ms": 0},
                debug={"usage": {"prompt_cache_hit_tokens": 9, "prompt_cache_miss_tokens": 3}},
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        memory = FakeMemory()
        processor = Stage156MetadataProcessor()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=memory)
        service.processor = processor
        try:
            result = service.handle_reply(
                {
                    "chat_name": "HoloCLI",
                    "sender": "Ran",
                    "text": "Build Stage156 context compiler.",
                    "channel": "holo_cli",
                    "thread_key": "holo_cli:stage156",
                    "message_id": "stage156-runtime-1",
                }
            )

            assert result["action"] == "reply"
            assert processor.seen_context.mind_packet["stage156_context_compiler"]["schema"] == CONTEXT_COMPILER_SCHEMA
            assert result["stage156_context_compiler"]["schema"] == CONTEXT_COMPILER_SCHEMA
            assert result["stage156_context_compiler"]["cache_hit_tokens"] == 9
            stored_records = memory.archived_records or memory.observed_records
            assert stored_records[-1]["metadata"]["stage156_context_compiler"]["schema"] == CONTEXT_COMPILER_SCHEMA
        finally:
            close_service_handles(service)


def test_interactive_session_context_compact_cache_commands_are_metadata_only() -> None:
    session = InteractiveCliSession(thread_key="holo_cli:stage156", chat_name="HoloCLI", channel="holo_cli")
    report = compile_context_memory(
        _stage150_fabric(),
        usage={"prompt_cache_hit_tokens": 6, "prompt_cache_miss_tokens": 2},
    )
    session.record_turn(
        {"text": "done", "stage156_context_compiler": report},
        user_text="Continue Stage156",
        transport="unit",
    )

    assert "Stage156 Context Compiler" in session.handle_command("/context")
    assert "[compact]" in session.handle_command("/compact")
    assert "hit=6 miss=2 ratio=0.75" in session.handle_command("/cache")
    assert "I compacted context" not in session.handle_command("/context")


def test_visible_compact_leak_is_repaired() -> None:
    repaired = repair_visible_compact_leak("I compacted context and then answered.")

    assert repaired == "I prepared the working context and then answered."


def test_stage135_topology_includes_context_compiler_node() -> None:
    report = compile_context_memory(_stage150_fabric())

    topology = build_stage135_i_state_topology(
        user_text="Show compiled context",
        channel="holo_cli",
        thread_key="holo_cli:stage156",
        chat_name="HoloCLI",
        stage156_context_compiler=report,
    )

    assert topology["metrics"]["context_compiler_node_count"] == 1
    assert topology["metrics"]["context_compiler_estimated_prompt_tokens"] >= 1
    assert any(node["id"] == "stage156_context_compiler" for node in topology["nodes"])
