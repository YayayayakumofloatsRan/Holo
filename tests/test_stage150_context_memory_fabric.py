from __future__ import annotations

from holo_host.models import AttentionState, TurnContext, TurnPlan
from holo_host.processors import render_chat_prompt
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage150_context_memory_fabric import (
    STAGE150_SCHEMA,
    build_stage150_context_memory_fabric,
    resolve_instruction_scope,
)


def _base_packet() -> dict:
    stage149 = {
        "schema": "holo.stage149.user_directives.v1",
        "status": "active",
        "core_identity": {
            "mode": "subject_runtime_not_roleplay",
            "summary": "Holo is a local subject runtime.",
            "priority": 0.96,
        },
        "directives": [
            {
                "directive_id": "visible_no_emoji:test",
                "directive_type": "visible_no_emoji",
                "summary": "visible speech must not contain emoji or emoticons",
                "source_family": "archive",
                "source_ids": ["archive:no-emoji"],
                "priority": 1.0,
                "confidence": 0.94,
                "hard": True,
            }
        ],
        "hard_directive_count": 1,
    }
    stage148 = {
        "schema": "holo.stage148.reusable_state_react_loop.v1",
        "event_log": {
            "events": [
                {"event_id": "u1", "direction": "user", "text": "Please avoid emoji.", "source": "message_history"},
                {"event_id": "h1", "direction": "holo", "text": "Understood.", "source": "message_history"},
            ],
            "event_count": 2,
        },
        "reusable_state_memory": {
            "memory_is_not_chat_log": True,
            "slots": [
                {
                    "slot_id": "constraint:no-emoji",
                    "slot_type": "recent_correction",
                    "summary": "avoid emoji in visible speech",
                    "priority": 0.92,
                    "freshness": 0.9,
                    "confidence": 0.86,
                },
                {
                    "slot_id": "loop:stage150",
                    "slot_type": "active_task",
                    "summary": "build a structured working context packet",
                    "priority": 0.85,
                    "freshness": 1.0,
                    "confidence": 0.82,
                },
            ],
            "slot_count": 2,
        },
        "react_loop": {"plan": {"selected_action_hint": "direct_answer"}},
    }
    return {
        "stage149_user_directives": stage149,
        "stage148_react_state": stage148,
        "persona_blend": {"style_memory": "playful persona may use emoji"},
        "project_instruction": {"summary": "Use project evidence before claiming project facts."},
        "domain_instruction": {"summary": "Biomimetic packet policy work should stay deterministic."},
        "module_instruction": {"summary": "Prompt renderer owns visible context organization."},
        "current_task_instruction": {"summary": "Implement Stage150 without widening authority."},
        "recent_dialogue_window": {
            "lines": [
                "session started at 127.0.0.1:8004",
                "user: Please avoid emoji.",
                "environment: WSL health check noise",
                "user: Keep the exact current request.",
            ]
        },
        "tool_observation_ledger": [],
        "memory_observation_ledger": [
            {
                "memory_call_id": "mem:no-emoji",
                "source_family": "durable",
                "status": "grounded",
                "summary": "user preference: no emoji",
                "confidence": 0.9,
            }
        ],
    }


def _context(user_text: str, packet: dict | None = None) -> TurnContext:
    sidecar = packet or _base_packet()
    return TurnContext(
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        sender="Ran",
        user_text=user_text,
        sidecar=sidecar,
        mind_packet=sidecar,
        attention_state=AttentionState(primary_focus="system_design", reply_goal="answer concretely"),
        emotion_state={},
        history=[
            {"direction": "inbound", "body_text": "Please avoid emoji.", "created_at": "2026-05-26T00:00:00Z"},
            {"direction": "outbound", "body_text": "Understood.", "created_at": "2026-05-26T00:01:00Z"},
        ],
        capability_context={"tool_context_lines": ["workspace tools are available but not executed"]},
    )


def test_builds_context_packet_with_separated_sections_and_exact_current_request() -> None:
    report = build_stage150_context_memory_fabric(
        user_text="Completely implement Stage150.",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        history=_context("Completely implement Stage150.").history,
        sidecar=_base_packet(),
    )

    assert report["schema"] == STAGE150_SCHEMA
    packet = report["working_context_packet"]
    assert packet["user_goal"]["current_user_request_exact"] == "Completely implement Stage150."
    for key in (
        "active_task_state",
        "reusable_state_slots",
        "directive_state",
        "project_or_domain_instructions",
        "relevant_recent_events",
        "evidence_ledger_view",
        "tool_memory_visual_observations",
        "open_loops",
        "compact_background_summary",
        "forbidden_visible_claims",
    ):
        assert key in packet


def test_stage149_user_directives_outrank_persona_style_memory() -> None:
    report = build_stage150_context_memory_fabric(
        user_text="Reply naturally.",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        sidecar=_base_packet(),
    )

    scope = report["instruction_scope"]
    assert scope["effective_constraints"]["visible_no_emoji"]["source"] == "user_directive"
    assert "persona" in " ".join(scope["overridden_sources"])


def test_background_compact_filters_environment_noise_and_preserves_open_loops() -> None:
    report = build_stage150_context_memory_fabric(
        user_text="Keep going on Stage150.",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        sidecar=_base_packet(),
    )

    compact = report["background_compact"]
    rendered = " ".join(str(value) for value in compact.values())
    assert "127.0.0.1:8004" not in rendered
    assert "WSL health check noise" not in rendered
    assert "build a structured working context packet" in rendered
    assert compact["user_visible"] is False


def test_instruction_scope_resolves_more_specific_instruction_over_broad() -> None:
    scope = resolve_instruction_scope(
        system_policy=["answer safely"],
        project_instruction=["tone=brief"],
        domain_instruction=["tone=technical"],
        module_instruction=["tone=diagnostic"],
        current_task_instruction=["tone=implementation-focused"],
    )

    assert scope["effective_instructions"]["tone"]["value"] == "implementation-focused"
    assert scope["effective_instructions"]["tone"]["source"] == "current_task_instruction"


def test_evidence_discipline_marks_read_test_patch_claims_unverified_without_ledger() -> None:
    report = build_stage150_context_memory_fabric(
        user_text="Can you verify the repo?",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        sidecar=_base_packet(),
        candidate_visible_text="I read the files, patched the code, and tests passed.",
    )

    evidence = report["evidence_discipline"]
    assert "read" in evidence["unverified_claim_families"]
    assert "patch" in evidence["unverified_claim_families"]
    assert "test" in evidence["unverified_claim_families"]
    assert any("Do not claim" in item for item in evidence["forbidden_visible_claims"])


def test_prompt_renderer_includes_engineering_context_state_block() -> None:
    context = _context("Render the structured context.")
    context.mind_packet["stage150_context_memory_fabric"] = build_stage150_context_memory_fabric(
        user_text=context.user_text,
        channel=context.channel,
        thread_key=context.thread_key,
        chat_name=context.chat_name,
        history=context.history,
        sidecar=context.mind_packet,
    )

    prompt = render_chat_prompt(context, turn_plan=TurnPlan(route="main", bubble_target=1))

    assert "Engineering Context State:" in prompt
    assert "User Goal" in prompt
    assert "Evidence Ledger" in prompt
    assert "Background Compact Summary" in prompt
    assert "Render the structured context." in prompt


def test_stage135_topology_includes_context_memory_fabric_node() -> None:
    fabric = build_stage150_context_memory_fabric(
        user_text="Show topology.",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        sidecar=_base_packet(),
    )

    payload = build_stage135_i_state_topology(
        user_text="Show topology.",
        channel="holo_cli",
        thread_key="holo_cli:stage150",
        chat_name="Stage150",
        stage150_context_memory_fabric=fabric,
    )

    assert payload["metrics"]["context_memory_fabric_node_count"] == 1
    assert payload["metrics"]["context_memory_fabric_slot_count"] >= 2
    assert any(node["id"] == "context_memory_fabric" for node in payload["nodes"])
