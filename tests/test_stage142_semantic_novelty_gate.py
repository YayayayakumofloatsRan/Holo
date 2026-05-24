from __future__ import annotations

from holo_host.models import ReplyBubble
from holo_host.stage132_progressive_conscious_stream import merge_stage132_reply_bubbles
from holo_host.stage142_semantic_novelty_gate import (
    STAGE142_SCHEMA,
    apply_stage142_gate,
    evaluate_stage142_bubbles,
)


def _bubbles(first: str, second: str) -> list[ReplyBubble]:
    return [
        ReplyBubble(first, delay_ms=0, purpose="fast_reaction"),
        ReplyBubble(second, delay_ms=520, purpose="deep_continuation"),
    ]


def test_duplicate_second_bubble_is_suppressed() -> None:
    kept, report = apply_stage142_gate(_bubbles("I can do that.", "I can do that."), stream_plan={"expression_budget": 2})

    assert report["schema"] == STAGE142_SCHEMA
    assert report["candidate_count"] == 2
    assert report["emitted_count"] == 1
    assert report["suppressed_count"] == 1
    assert report["status"] == "suppressed_duplicate"
    assert [bubble.text for bubble in kept] == ["I can do that."]


def test_prefix_duplicate_second_bubble_is_trimmed_when_new_content_remains() -> None:
    kept, report = apply_stage142_gate(
        _bubbles("I checked the workspace.", "I checked the workspace. The tests now pass."),
        stream_plan={"expression_budget": 2},
        tool_grounding={"status": "grounded", "observed_families": ["workspace", "tests"]},
    )

    assert report["repaired_count"] == 1
    assert report["suppressed_count"] == 0
    assert [bubble.text for bubble in kept] == ["I checked the workspace.", "The tests now pass."]


def test_valid_tool_feedback_second_bubble_is_allowed() -> None:
    kept, report = apply_stage142_gate(
        _bubbles("I will check the workspace first.", "I checked the workspace and saw docs plus holo_host."),
        tool_grounding={"status": "grounded", "observed_families": ["workspace"]},
    )

    assert report["status"] == "passed"
    assert report["emitted_count"] == 2
    assert report["evaluations"][1]["semantic_role"] == "tool_feedback"
    assert len(kept) == 2


def test_valid_memory_alignment_limitation_second_bubble_is_allowed() -> None:
    kept, report = apply_stage142_gate(
        _bubbles(
            "I have a memory cue.",
            "I have a memory cue, but not enough source support for that exact detail.",
        ),
        memory_grounding={"status": "grounded"},
        memory_alignment={"status": "unsupported_memory_detail", "unsupported_claim_count": 1},
    )

    assert report["status"] == "passed"
    assert report["emitted_count"] == 2
    assert report["evaluations"][1]["should_emit"] is True
    assert len(kept) == 2


def test_second_bubble_with_unsupported_memory_detail_is_blocked() -> None:
    kept, report = apply_stage142_gate(
        _bubbles("Let me answer carefully.", "I remember you prefer fewer emoji."),
        memory_grounding={"status": "grounded"},
        memory_alignment={"status": "unsupported_memory_detail", "unsupported_claim_count": 1},
    )

    assert report["status"] == "blocked_ungrounded_claim"
    assert report["evaluations"][1]["grounding_blocked"] is True
    assert [bubble.text for bubble in kept] == ["Let me answer carefully."]


def test_second_bubble_with_ungrounded_tool_claim_is_blocked() -> None:
    kept, report = apply_stage142_gate(
        _bubbles("I will answer from available context.", "I checked the workspace and saw docs."),
        tool_grounding={"status": "ungrounded_tool_claim", "missing_families": ["workspace"], "observed_families": []},
    )

    assert report["status"] == "blocked_ungrounded_claim"
    assert report["suppressed_count"] == 1
    assert [bubble.text for bubble in kept] == ["I will answer from available context."]


def test_unrepaired_contradiction_between_first_and_second_bubble_is_blocked() -> None:
    kept, report = apply_stage142_gate(_bubbles("I can read that file.", "I cannot read that file."))

    assert report["status"] == "repaired_contradiction"
    assert report["evaluations"][1]["suppression_reason"] == "unrepaired_contradiction"
    assert [bubble.text for bubble in kept] == ["I can read that file."]


def test_user_visible_text_does_not_leak_stage142_debug_labels() -> None:
    kept, report = apply_stage142_gate(_bubbles("I can do that.", "I can do that."))
    visible = " ".join(bubble.text for bubble in kept)

    assert report["schema"] == STAGE142_SCHEMA
    assert "Stage142" not in visible
    assert "semantic_novelty" not in visible
    assert "novelty_score" not in visible


def test_stage132_merge_path_uses_stage142_gate() -> None:
    bubbles, report = merge_stage132_reply_bubbles(
        first_reaction="First I catch the intent.",
        deep_text="First I catch the intent. First I catch the intent.",
        stream_plan={"visible_first_reaction": True, "expression_budget": 2},
        channel="holo_cli",
        return_metadata=True,
    )

    assert [bubble.text for bubble in bubbles] == ["First I catch the intent."]
    assert report["candidate_count"] == 2
    assert report["suppressed_count"] == 1


def test_evaluation_metadata_shape_is_stable() -> None:
    report = evaluate_stage142_bubbles(_bubbles("First.", "Then I add the concrete next step."))

    assert report["schema"] == STAGE142_SCHEMA
    assert report["candidate_count"] == 2
    assert report["emitted_count"] == 2
    assert set(report["evaluations"][0]).issuperset(
        {
            "bubble_index",
            "purpose",
            "semantic_role",
            "novelty_score",
            "overlap_score",
            "contradiction_flags",
            "grounding_blocked",
            "should_emit",
            "suppression_reason",
        }
    )
