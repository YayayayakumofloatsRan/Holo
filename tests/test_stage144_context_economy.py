from __future__ import annotations

import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage143_packet_budget import build_stage143_packet_budget
from holo_host.stage144_context_economy import STAGE144_SCHEMA, build_stage144_context_economy
from holo_host.store import QueueStore

from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _stage143_report(*, stop_reason: str = "deep_packet_completed", sent_count: int = 2) -> dict[str, object]:
    return {
        "schema": "holo.stage143.packet_budget.v1",
        "packet_count": 2,
        "sent_count": sent_count,
        "skipped_count": 0 if sent_count > 1 else 1,
        "continued_count": 1 if sent_count > 1 else 0,
        "stop_reason": stop_reason,
        "total_estimated_tokens": 820,
        "total_elapsed_ms": 210,
        "packets": [
            {
                "packet_id": "packet_0_fast",
                "packet_type": "fast",
                "lane": "micro_fast",
                "budget_tag": "stage124_fast_packet",
                "sent": True,
                "send_reason": "always_run_first_packet",
                "skip_reason": "",
                "cache_hint": "stage132:test",
                "estimated_tokens": 300,
                "elapsed_ms": 35,
                "tool_need": False,
                "memory_need": False,
                "uncertainty": 0.42,
                "grounding_status": "",
                "memory_alignment_status": "",
                "stage142_status": "",
                "stop_reason": "",
            },
            {
                "packet_id": "packet_1_deep",
                "packet_type": "deep" if sent_count > 1 else "skipped",
                "lane": "subject_main",
                "budget_tag": "chat_reply",
                "sent": sent_count > 1,
                "send_reason": "fast_packet_deep_packet_needed" if sent_count > 1 else "",
                "skip_reason": "" if sent_count > 1 else "provider_fast_packet_said_fast_answer_enough",
                "cache_hint": "stage132:test",
                "estimated_tokens": 520 if sent_count > 1 else 0,
                "elapsed_ms": 175 if sent_count > 1 else 0,
                "tool_need": False,
                "memory_need": False,
                "uncertainty": 0.42,
                "grounding_status": "",
                "memory_alignment_status": "",
                "stage142_status": "",
                "stop_reason": stop_reason,
            },
        ],
    }


def test_stage144_builds_bounded_slots_from_tool_memory_and_packet_metadata() -> None:
    report = build_stage144_context_economy(
        user_text="Please check the repo and remember my fewer emoji preference.",
        selected_action={"action_type": "reply_once", "score": 0.82},
        active_thread_state={"continuity_summary": "Stage144 calibrates context economy."},
        tool_observation_ledger=[
            {"provider_call_id": "call_workspace", "tool": "workspace_inspect", "status": "ok", "summary": "workspace contains docs and holo_host"}
        ],
        memory_observation_ledger=[
            {
                "memory_call_id": "pref_emoji",
                "source_family": "durable",
                "status": "grounded",
                "summary": "user preference: fewer emoji",
                "confidence": 0.9,
            }
        ],
        memory_alignment={"status": "aligned", "claim_count": 1, "unsupported_claim_count": 0},
        stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "suppressed_count": 0},
        stage143_packet_budget=_stage143_report(),
        visual_memory={"summary": "camera unavailable in this turn"},
        risk_permission={"approved_tool_permissions": ["workspace_inspect:readonly"]},
    )

    assert report["schema"] == STAGE144_SCHEMA
    assert report["shadow_only"] is True
    assert 0.0 <= report["context_sufficiency_score"] <= 1.0
    assert 0.0 <= report["context_waste_score"] <= 1.0
    slot_types = {slot["slot_type"] for slot in report["working_set_slots"]}
    assert {
        "current_user_constraint",
        "active_task",
        "tool_observation",
        "memory_anchor",
        "packet_budget",
        "novelty_gate",
        "visual_observation",
        "risk_permission",
    } <= slot_types
    assert len(report["working_set_slots"]) <= 12


def test_stage144_high_waste_when_deep_ran_but_stage142_suppressed_duplicate() -> None:
    report = build_stage144_context_economy(
        user_text="answer briefly",
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "emitted_count": 1, "suppressed_count": 1},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:suppressed_duplicate"),
    )

    assert report["context_waste_score"] >= 0.65
    assert report["recommended_deep_policy"] in {"skip", "defer"}
    assert "low-novelty" in report["reason"] or "duplicate" in report["reason"]


def test_stage144_recommends_memory_first_for_unsupported_memory_detail() -> None:
    report = build_stage144_context_economy(
        user_text="what do you remember about my preference?",
        memory_alignment={"status": "unsupported_memory_detail", "claim_count": 1, "unsupported_claim_count": 1},
        memory_observation_ledger=[{"memory_call_id": "wrong_topic", "source_family": "archive", "status": "grounded", "summary": "discussed git diff"}],
        stage143_packet_budget=_stage143_report(),
    )

    assert report["recommended_deep_policy"] == "memory_first"
    assert report["context_sufficiency_score"] < 0.7
    assert "memory" in report["packet_policy_recommendation"]


def test_stage144_recommends_tool_first_for_ungrounded_tool_claim() -> None:
    report = build_stage144_context_economy(
        user_text="check the directory",
        tool_grounding={"status": "ungrounded_tool_claim", "missing_families": ["workspace"]},
        stage143_packet_budget=_stage143_report(),
    )

    assert report["recommended_deep_policy"] == "tool_first"
    assert "tool" in report["packet_policy_recommendation"]


def test_stage144_recommends_keep_for_useful_non_suppressed_deep_continuation() -> None:
    report = build_stage144_context_economy(
        user_text="explain the implementation",
        stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "emitted_count": 2, "suppressed_count": 0},
        stage143_packet_budget=_stage143_report(),
        memory_alignment={"status": "aligned"},
        tool_grounding={"status": "grounded"},
    )

    assert report["recommended_deep_policy"] == "keep"
    assert report["context_waste_score"] < 0.55
    assert report["confidence"] >= 0.55


def test_stage144_reply_json_and_archive_metadata_include_context_economy() -> None:
    class Stage144Processor:
        name = "stage144_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            packet_budget = build_stage143_packet_budget(
                stage132_stream_plan={"round_count": 2, "deep_packet_needed": True, "preserve_bubbles": True},
                stage124_thought_loop={"deep_packet_sent": True, "fast_packet_ms": 20, "fast_packet": {"deep_packet_needed": True}},
                timing_ms={"processor_ms": 100, "stage124_fast_packet_ms": 20},
                stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "suppressed_count": 0},
            )
            return ReplyPlan(
                text="I can do that.\nThe deeper packet adds concrete state.",
                bubbles=[
                    ReplyBubble("I can do that.", purpose="fast_reaction"),
                    ReplyBubble("The deeper packet adds concrete state.", delay_ms=520, purpose="deep_continuation"),
                ],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=2),
                emotion_state=dict(context.emotion_state),
                route="main",
                processor=self.name,
                session_id=session_id or "stage144-session",
                raw_text="I can do that.\nThe deeper packet adds concrete state.",
                timing_ms={"processor_ms": 100, "stage124_fast_packet_ms": 20, "recall_reconstruct_ms": 0},
                debug={
                    "stage132_progressive_stream": {"round_count": 2, "deep_packet_needed": True, "preserve_bubbles": True},
                    "stage142_semantic_novelty": {"status": "passed", "candidate_count": 2, "emitted_count": 2, "suppressed_count": 0},
                    "stage143_packet_budget": packet_budget,
                    "memory_observation_ledger": [
                        {
                            "memory_call_id": "pref",
                            "source_family": "durable",
                            "status": "grounded",
                            "summary": "user preference: concise replies",
                            "confidence": 0.8,
                        }
                    ],
                },
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        memory = FakeMemory()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=memory)
        service.processor = Stage144Processor()
        try:
            result = service.handle_reply(
                {
                    "chat_name": "TestUser",
                    "sender": "TestUser",
                    "text": "show context economy",
                    "channel": "holo_cli",
                    "message_id": "stage144-context-1",
                }
            )

            assert result["action"] == "reply"
            assert result["stage144_context_economy"]["schema"] == STAGE144_SCHEMA
            assert result["stage144_context_economy"]["shadow_only"] is True
            assert result["stage144_context_economy_shadow_only"] is True
            assert memory.observed_records[-1]["metadata"]["stage144_context_economy"]["schema"] == STAGE144_SCHEMA
            assert "Stage144" not in result["text"]
            assert "context_economy" not in result["text"]
        finally:
            close_service_handles(service)


def test_stage144_stage135_topology_includes_context_economy_node() -> None:
    report = build_stage144_context_economy(
        user_text="show context economy topology",
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:suppressed_duplicate"),
    )
    payload = build_stage135_i_state_topology(
        user_text="show context economy topology",
        channel="holo_cli",
        fast_packet={"deep_packet_needed": True, "intent": "context_economy_trace"},
        stream_plan={"deep_packet_needed": True},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:suppressed_duplicate"),
        stage144_context_economy=report,
    )

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["context_economy_gate"]["channel"] == "context_economy"
    assert payload["metrics"]["context_economy_node_count"] == 1
    assert payload["metrics"]["context_economy_recommended_deep_policy"] == report["recommended_deep_policy"]
    assert any(edge["target"] == "context_economy_gate" for edge in payload["edges"])


def test_stage144_shadow_only_remains_true() -> None:
    report = build_stage144_context_economy(user_text="diagnose only")

    assert report["shadow_only"] is True
    assert report["packet_policy_recommendation"]
