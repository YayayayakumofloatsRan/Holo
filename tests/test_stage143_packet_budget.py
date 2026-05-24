from __future__ import annotations

import tempfile
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import AttentionState, ReplyBubble, ReplyPlan, TurnContext, TurnPlan
from holo_host.reply_api import HoloReplyService
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage143_packet_budget import STAGE143_SCHEMA, build_stage143_packet_budget
from holo_host.store import QueueStore

from tests.test_holo_host import FakeMemory, FakeRunner, close_service_handles


def _fast_only_stream() -> dict[str, object]:
    return {
        "schema": "holo.stage132.progressive_conscious_stream.v1",
        "round_count": 1,
        "rounds": [
            {
                "index": 0,
                "purpose": "fast_reaction",
                "lane": "micro_fast",
                "budget_tag": "stage124_fast_packet",
                "model_tier": "flash",
                "condition": "always_run_first_packet",
            }
        ],
        "deep_packet_needed": False,
        "tool_loop_expected": False,
        "stop_reason": "provider_fast_packet_said_fast_answer_enough",
        "cache_hint": "stage132:fast",
        "uncertainty_level": 0.12,
        "preserve_bubbles": True,
    }


def _deep_stream() -> dict[str, object]:
    stream = dict(_fast_only_stream())
    stream.update(
        {
            "round_count": 2,
            "deep_packet_needed": True,
            "stop_reason": "",
            "tool_loop_expected": True,
            "uncertainty_level": 0.66,
            "rounds": [
                {
                    "index": 0,
                    "purpose": "fast_reaction",
                    "lane": "micro_fast",
                    "budget_tag": "stage124_fast_packet",
                    "model_tier": "flash",
                    "condition": "always_run_first_packet",
                },
                {
                    "index": 1,
                    "purpose": "deep_continuation",
                    "lane": "subject_main",
                    "budget_tag": "chat_reply",
                    "model_tier": "pro",
                    "condition": "fast_packet_deep_packet_needed",
                },
            ],
        }
    )
    return stream


def test_stage143_fast_only_reports_sent_fast_and_skipped_deep() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_fast_only_stream(),
        stage132_fast_context_frame={"cache_hint": "stage132:fast", "char_count": 1200},
        stage124_thought_loop={"deep_packet_sent": False, "fast_packet_ms": 41},
        timing_ms={"processor_ms": 58},
        usage={"prompt_tokens": 300, "completion_tokens": 32},
    )

    assert report["schema"] == STAGE143_SCHEMA
    assert report["packet_count"] == 2
    assert report["sent_count"] == 1
    assert report["skipped_count"] == 1
    assert report["continued_count"] == 0
    assert report["stop_reason"] == "provider_fast_packet_said_fast_answer_enough"
    assert [packet["packet_type"] for packet in report["packets"]] == ["fast", "skipped"]
    assert report["packets"][0]["sent"] is True
    assert report["packets"][0]["send_reason"] == "always_run_first_packet"
    assert report["packets"][1]["sent"] is False
    assert report["packets"][1]["skip_reason"] == "provider_fast_packet_said_fast_answer_enough"
    assert report["packets"][1]["packet_type"] == "skipped"


def test_stage143_fast_and_deep_reports_continuation_reason() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_deep_stream(),
        stage132_fast_context_frame={"cache_hint": "stage132:deep", "char_count": 1600},
        stage124_thought_loop={"deep_packet_sent": True, "fast_packet_ms": 35},
        stage121_packet_policy={"target_input_tokens": 48000, "output_budget_tokens": 1200},
        timing_ms={"processor_ms": 210},
        usage={"prompt_tokens": 700, "completion_tokens": 140},
        tool_grounding={"status": "grounded"},
        memory_alignment={"status": "aligned"},
    )

    assert report["packet_count"] == 2
    assert report["sent_count"] == 2
    assert report["skipped_count"] == 0
    assert report["continued_count"] == 1
    assert report["stop_reason"] == "deep_packet_completed"
    assert [packet["packet_type"] for packet in report["packets"]] == ["fast", "deep"]
    assert report["packets"][1]["send_reason"] == "fast_packet_deep_packet_needed"
    assert report["packets"][1]["tool_need"] is True
    assert report["packets"][1]["memory_alignment_status"] == "aligned"


def test_stage143_stage142_suppression_appears_in_stop_reason() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_deep_stream(),
        stage124_thought_loop={"deep_packet_sent": True, "fast_packet_ms": 25},
        timing_ms={"processor_ms": 160},
        stage142_semantic_novelty={
            "schema": "holo.stage142.semantic_novelty_gate.v1",
            "candidate_count": 2,
            "emitted_count": 1,
            "suppressed_count": 1,
            "status": "suppressed_duplicate",
        },
    )

    assert report["stop_reason"] == "stage142:suppressed_duplicate"
    assert report["packets"][-1]["stage142_status"] == "suppressed_duplicate"
    assert report["packets"][-1]["stop_reason"] == "stage142:suppressed_duplicate"


def test_stage143_missing_usage_falls_back_to_estimated_tokens() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_fast_only_stream(),
        stage132_fast_context_frame={"cache_hint": "stage132:fallback", "char_count": 2048},
        stage124_thought_loop={"deep_packet_sent": False, "fast_packet_ms": 10},
        timing_ms={"processor_ms": 12},
        usage={},
    )

    assert report["total_estimated_tokens"] >= 512
    assert report["packets"][0]["estimated_tokens"] >= 512
    assert report["packets"][0]["cache_hint"] == "stage132:fallback"


def test_stage143_reply_json_and_archive_metadata_include_packet_budget() -> None:
    class Stage143Processor:
        name = "stage143_processor"

        def generate(self, context: TurnContext, *, session_id: str = "") -> ReplyPlan:
            return ReplyPlan(
                text="I can do that.\nI checked the workspace state.",
                bubbles=[
                    ReplyBubble("I can do that.", purpose="fast_reaction"),
                    ReplyBubble("I checked the workspace state.", delay_ms=520, purpose="deep_continuation"),
                ],
                attention_state=context.attention_state,
                turn_plan=TurnPlan(route="main", bubble_target=2),
                emotion_state=dict(context.emotion_state),
                route="main",
                processor=self.name,
                session_id=session_id or "stage143-session",
                raw_text="I can do that.\nI checked the workspace state.",
                timing_ms={"processor_ms": 111, "stage124_fast_packet_ms": 21, "recall_reconstruct_ms": 0},
                debug={
                    "stage132_fast_context_frame": {"cache_hint": "stage132:api", "char_count": 900},
                    "stage124_thought_loop": {
                        "deep_packet_sent": True,
                        "fast_packet_ms": 21,
                        "fast_packet": {"deep_packet_needed": True},
                    },
                    "stage132_progressive_stream": _deep_stream(),
                    "usage": {"prompt_tokens": 500, "completion_tokens": 90},
                },
            )

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        config = load_config(repo_root=root)
        store = QueueStore(config.runtime.db_path)
        memory = FakeMemory()
        service = HoloReplyService(config, store=store, runner=FakeRunner(), memory=memory)
        service.processor = Stage143Processor()
        try:
            result = service.handle_reply(
                {
                    "chat_name": "TestUser",
                    "sender": "TestUser",
                    "text": "show packet report",
                    "channel": "holo_cli",
                    "message_id": "stage143-report-1",
                }
            )

            assert result["action"] == "reply"
            assert result["stage143_packet_budget"]["schema"] == STAGE143_SCHEMA
            assert result["stage143_packet_budget"]["sent_count"] == 2
            assert result["stage143_packet_budget_stop_reason"] in {"deep_packet_completed", "stage142:passed"}
            assert memory.observed_records[-1]["metadata"]["stage143_packet_budget"]["schema"] == STAGE143_SCHEMA
            assert "Stage143" not in result["text"]
            assert "packet_budget" not in result["text"]
        finally:
            close_service_handles(service)


def test_stage143_stage135_topology_includes_packet_budget_gate() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_fast_only_stream(),
        stage132_fast_context_frame={"cache_hint": "stage132:topology", "char_count": 700},
        stage124_thought_loop={"deep_packet_sent": False, "fast_packet_ms": 18},
        timing_ms={"processor_ms": 24},
    )
    payload = build_stage135_i_state_topology(
        user_text="show the packet budget gate",
        channel="holo_cli",
        fast_packet={"deep_packet_needed": False, "intent": "packet_budget_trace"},
        stream_plan=_fast_only_stream(),
        stage143_packet_budget=report,
    )

    nodes = {node["id"]: node for node in payload["nodes"]}
    assert nodes["packet_budget_gate"]["channel"] == "packet_budget"
    assert payload["metrics"]["packet_budget_node_count"] == 1
    assert payload["metrics"]["packet_budget_packet_count"] == 2
    assert payload["metrics"]["packet_budget_stop_reason"] == "provider_fast_packet_said_fast_answer_enough"
    assert any(edge["target"] == "packet_budget_gate" for edge in payload["edges"])


def test_stage143_debug_labels_do_not_leak_to_visible_text() -> None:
    report = build_stage143_packet_budget(
        stage132_stream_plan=_deep_stream(),
        stage124_thought_loop={"deep_packet_sent": True},
        stage142_semantic_novelty={"status": "suppressed_duplicate", "suppressed_count": 1},
    )
    visible_text = "I can do that."

    assert report["schema"] == STAGE143_SCHEMA
    assert "Stage143" not in visible_text
    assert "packet_budget" not in visible_text
