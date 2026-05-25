from __future__ import annotations

import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage143_packet_budget import build_stage143_packet_budget
from holo_host.stage144_context_economy import build_stage144_context_economy
from holo_host.stage145_reaction_kernel import (
    OUTCOME_APPRAISAL_SCHEMA,
    REACTION_KERNEL_SHADOW_SCHEMA,
    build_stage145_shadow_reports,
)
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
                "sent": True,
                "uncertainty": 0.38,
                "grounding_status": "grounded",
                "memory_alignment_status": "aligned",
                "stage142_status": "",
                "stop_reason": "",
            },
            {
                "packet_id": "packet_1_deep",
                "packet_type": "deep" if sent_count > 1 else "skipped",
                "sent": sent_count > 1,
                "uncertainty": 0.38,
                "grounding_status": "grounded",
                "memory_alignment_status": "aligned",
                "stage142_status": "",
                "stop_reason": stop_reason,
            },
        ],
    }


def _stage144_report(
    *,
    recommended: str = "keep",
    sufficiency: float = 0.82,
    waste: float = 0.18,
) -> dict[str, object]:
    return {
        "schema": "holo.stage144.context_economy.v1",
        "working_set_slots": [{"slot_id": "current:test", "slot_type": "current_user_constraint", "summary": "current turn", "priority": 0.9}],
        "context_sufficiency_score": sufficiency,
        "context_waste_score": waste,
        "packet_policy_recommendation": f"{recommended}: synthetic test recommendation",
        "recommended_deep_policy": recommended,
        "confidence": 0.8,
        "reason": "synthetic test recommendation",
        "shadow_only": True,
    }


def _delta_map(kernel: dict[str, object]) -> dict[str, dict[str, object]]:
    return {str(item["parameter"]): dict(item) for item in kernel["kernel_delta_candidates"]}  # type: ignore[index]


def test_stage145_unsupported_memory_detail_creates_memory_trust_and_correction_delta() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="what do you remember about my preference?",
        memory_alignment={"status": "unsupported_memory_detail", "claim_count": 1, "unsupported_claim_count": 1},
        memory_grounding={"status": "grounded"},
        tool_grounding={"status": "grounded"},
        stage142_semantic_novelty={"status": "passed", "candidate_count": 1, "suppressed_count": 0},
        stage143_packet_budget=_stage143_report(),
        stage144_context_economy=_stage144_report(recommended="memory_first", sufficiency=0.46, waste=0.35),
    )

    deltas = _delta_map(kernel)
    assert appraisal["schema"] == OUTCOME_APPRAISAL_SCHEMA
    assert kernel["schema"] == REACTION_KERNEL_SHADOW_SCHEMA
    assert appraisal["prediction_error"] >= 0.45
    assert deltas["memory_trust"]["delta"] < 0
    assert deltas["correction_sensitivity"]["delta"] > 0
    assert deltas["caution"]["delta"] > 0


def test_stage145_duplicate_suppression_creates_novelty_and_continuation_delta() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="answer briefly",
        tool_grounding={"status": "grounded"},
        memory_grounding={"status": "no_memory_claim"},
        memory_alignment={"status": "no_memory_claim"},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "emitted_count": 1, "suppressed_count": 1},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:suppressed_duplicate"),
        stage144_context_economy=_stage144_report(recommended="skip", sufficiency=0.54, waste=0.78),
    )

    deltas = _delta_map(kernel)
    assert appraisal["observed_stage142_status"] == "suppressed_duplicate"
    assert appraisal["observed_packet_waste"] >= 0.7
    assert deltas["novelty_threshold"]["delta"] > 0
    assert deltas["continuation_threshold"]["delta"] > 0


def test_stage145_ungrounded_tool_claim_creates_tool_preference_and_risk_delta() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="check the directory",
        tool_grounding={"status": "ungrounded_tool_claim", "missing_families": ["workspace"]},
        memory_grounding={"status": "no_memory_claim"},
        memory_alignment={"status": "no_memory_claim"},
        stage142_semantic_novelty={"status": "blocked_ungrounded_claim", "candidate_count": 2, "suppressed_count": 1},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:blocked_ungrounded_claim"),
        stage144_context_economy=_stage144_report(recommended="tool_first", sufficiency=0.5, waste=0.42),
    )

    deltas = _delta_map(kernel)
    assert appraisal["observed_grounding_status"] == "ungrounded_tool_claim"
    assert appraisal["prediction_error"] >= 0.5
    assert deltas["tool_preference"]["delta"] > 0
    assert deltas["risk_aversion"]["delta"] > 0


def test_stage145_clean_grounded_answer_has_low_prediction_error_and_no_strong_delta() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="explain the implementation",
        tool_grounding={"status": "grounded"},
        memory_grounding={"status": "grounded"},
        memory_alignment={"status": "aligned"},
        stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "emitted_count": 2, "suppressed_count": 0},
        stage143_packet_budget=_stage143_report(),
        stage144_context_economy=_stage144_report(recommended="keep", sufficiency=0.86, waste=0.16),
    )

    assert appraisal["prediction_error"] <= 0.25
    assert kernel["kernel_delta_candidates"] == []


def test_stage145_deltas_are_shadow_only_and_not_applied() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="you said you checked it",
        tool_grounding={"status": "ungrounded_tool_claim"},
        memory_grounding={"status": "weak_memory_source"},
        memory_alignment={"status": "unsupported_memory_detail", "unsupported_claim_count": 1},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "candidate_count": 2, "suppressed_count": 1},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:suppressed_duplicate"),
        stage144_context_economy=_stage144_report(recommended="memory_first", sufficiency=0.3, waste=0.84),
    )

    assert appraisal["shadow_only"] is True
    assert kernel["shadow_only"] is True
    assert kernel["applied"] is False
    assert kernel["kernel_delta_candidates"]
    for item in kernel["kernel_delta_candidates"]:
        assert item["applied"] is False
        assert item["rollback_id"]


def test_stage145_reply_json_and_archive_metadata_include_shadow_reports() -> None:
    class Stage145Processor:
        name = "stage145_processor"

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
                session_id=session_id or "stage145-session",
                raw_text="I can do that.\nThe deeper packet adds concrete state.",
                timing_ms={"processor_ms": 100, "stage124_fast_packet_ms": 20, "recall_reconstruct_ms": 0},
                debug={
                    "stage132_progressive_stream": {"round_count": 2, "deep_packet_needed": True, "preserve_bubbles": True},
                    "stage142_semantic_novelty": {"status": "passed", "candidate_count": 2, "emitted_count": 2, "suppressed_count": 0},
                    "stage143_packet_budget": packet_budget,
                    "stage144_context_economy": build_stage144_context_economy(
                        user_text=context.user_text,
                        stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "suppressed_count": 0},
                        stage143_packet_budget=packet_budget,
                    ),
                },
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        memory = FakeMemory()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=memory)
        service.processor = Stage145Processor()
        try:
            result = service.handle_reply(
                {
                    "chat_name": "TestUser",
                    "sender": "TestUser",
                    "text": "show reaction kernel shadow",
                    "channel": "holo_cli",
                    "message_id": "stage145-shadow-1",
                }
            )

            assert result["action"] == "reply"
            assert result["stage145_outcome_appraisal"]["schema"] == OUTCOME_APPRAISAL_SCHEMA
            assert result["stage145_reaction_kernel_shadow"]["schema"] == REACTION_KERNEL_SHADOW_SCHEMA
            assert result["stage145_reaction_kernel_shadow"]["shadow_only"] is True
            metadata = memory.observed_records[-1]["metadata"]
            assert metadata["stage145_outcome_appraisal"]["schema"] == OUTCOME_APPRAISAL_SCHEMA
            assert metadata["stage145_reaction_kernel_shadow"]["schema"] == REACTION_KERNEL_SHADOW_SCHEMA
            assert len(memory.observed_records) == 1
            assert all("stage145_reaction_kernel_shadow" not in dict(item.get("metadata", {})) for item in memory.outcome_appraisals)
            assert "Stage145" not in result["text"]
            assert "reaction_kernel" not in result["text"]
        finally:
            close_service_handles(service)


def test_stage145_stage135_topology_includes_reaction_kernel_node() -> None:
    appraisal, kernel = build_stage145_shadow_reports(
        user_text="show reaction kernel topology",
        tool_grounding={"status": "grounded"},
        memory_grounding={"status": "grounded"},
        memory_alignment={"status": "aligned"},
        stage142_semantic_novelty={"status": "passed", "candidate_count": 2, "suppressed_count": 0},
        stage143_packet_budget=_stage143_report(),
        stage144_context_economy=_stage144_report(recommended="keep", sufficiency=0.84, waste=0.2),
    )
    payload = build_stage135_i_state_topology(
        user_text="show reaction kernel topology",
        channel="holo_cli",
        fast_packet={"deep_packet_needed": True, "intent": "reaction_kernel_trace"},
        stream_plan={"deep_packet_needed": True},
        stage143_packet_budget=_stage143_report(),
        stage144_context_economy=_stage144_report(recommended="keep", sufficiency=0.84, waste=0.2),
        stage145_outcome_appraisal=appraisal,
        stage145_reaction_kernel_shadow=kernel,
    )

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["reaction_kernel_shadow"]["channel"] == "reaction_kernel"
    assert payload["metrics"]["reaction_kernel_node_count"] == 1
    assert payload["metrics"]["reaction_kernel_shadow_only"] is True


def test_stage145_direct_builder_does_not_write_private_memory() -> None:
    memory = FakeMemory()
    build_stage145_shadow_reports(
        user_text="diagnose only",
        tool_grounding={"status": "ungrounded_tool_claim"},
        memory_grounding={"status": "no_memory_claim"},
        memory_alignment={"status": "no_memory_claim"},
        stage142_semantic_novelty={"status": "blocked_ungrounded_claim"},
        stage143_packet_budget=_stage143_report(stop_reason="stage142:blocked_ungrounded_claim"),
        stage144_context_economy=_stage144_report(recommended="tool_first", sufficiency=0.42, waste=0.35),
    )

    assert memory.observed_records == []
    assert memory.archived_records == []
    assert memory.outcome_appraisals == []
