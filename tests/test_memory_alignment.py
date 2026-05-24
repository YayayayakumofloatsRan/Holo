from __future__ import annotations

from holo_host.memory_alignment import (
    MEMORY_ALIGNMENT_SCHEMA,
    build_memory_evidence_texts,
    evaluate_memory_alignment,
    extract_memory_claims,
    repair_memory_alignment,
)


def _ledger(
    *,
    summary: str,
    source_family: str = "durable",
    status: str = "grounded",
    confidence: float = 0.9,
    selected_ids: list[str] | None = None,
    contradiction_flags: list[str] | None = None,
) -> list[dict]:
    return [
        {
            "schema": "holo.memory_grounding.v1",
            "memory_call_id": "memory:test",
            "source_family": source_family,
            "selected_ids": selected_ids or [],
            "status": status,
            "summary": summary,
            "confidence": confidence,
            "freshness": "test",
            "grounding_tags": ["memory", source_family],
            "contradiction_flags": contradiction_flags or [],
            "missing_source": status == "missing",
        }
    ]


def test_extract_memory_claims_collapses_nested_wrappers() -> None:
    claims = extract_memory_claims("I remember you prefer fewer emoji.")

    assert len(claims) == 1
    assert claims[0]["claim_family"] == "preference"
    assert {"preference", "fewer", "emoji"}.issubset(set(claims[0]["key_terms"]))


def test_missing_source_remains_unsupported() -> None:
    report = evaluate_memory_alignment(
        "I remember you prefer fewer emoji.",
        _ledger(summary="memory requested but no selected source was available", source_family="none", status="missing", confidence=0.0),
    )

    assert report["schema"] == MEMORY_ALIGNMENT_SCHEMA
    assert report["status"] == "unsupported_memory_detail"
    assert report["aligned_claim_count"] == 0
    assert report["repair_required"] is True


def test_matching_grounded_source_aligns_claim() -> None:
    report = evaluate_memory_alignment(
        "I remember you prefer fewer emoji.",
        _ledger(summary="user preference: fewer emoji", source_family="durable", status="grounded", confidence=0.9),
    )

    assert report["status"] == "aligned"
    assert report["aligned_claim_count"] == 1
    assert report["repair_required"] is False


def test_source_exists_but_wrong_topic_is_unsupported() -> None:
    report = evaluate_memory_alignment(
        "I remember you prefer fewer emoji.",
        _ledger(summary="discussed git diff and tests", source_family="archive", status="grounded", confidence=0.9),
    )

    claim = report["claims"][0]
    assert report["status"] == "unsupported_memory_detail"
    assert claim["status"] == "unsupported"
    assert "emoji" in claim["missing_terms"]
    assert "preference" in claim["missing_terms"]
    assert report["repair_required"] is True


def test_date_claim_requires_date_support() -> None:
    report = evaluate_memory_alignment(
        "I remember you told me yesterday that you prefer fewer emoji.",
        _ledger(summary="user preference: fewer emoji", source_family="durable", status="grounded", confidence=0.9),
    )

    assert report["status"] in {"weakly_aligned", "unsupported_memory_detail"}
    assert report["status"] != "aligned"
    assert "yesterday" in report["claims"][0]["missing_terms"]


def test_preference_claim_requires_preference_marker_and_object_marker() -> None:
    report = evaluate_memory_alignment(
        "I remember you prefer fewer emoji.",
        _ledger(summary="we discussed emoji", source_family="archive", status="grounded", confidence=0.9),
    )

    assert report["status"] in {"weakly_aligned", "unsupported_memory_detail"}
    assert report["status"] != "aligned"
    assert report["claims"][0]["status"] in {"weak", "unsupported"}


def test_current_context_cannot_fully_ground_old_memory_claim() -> None:
    report = evaluate_memory_alignment(
        "You told me before that you prefer fewer emoji.",
        _ledger(
            summary="current context lines mention emoji",
            source_family="current_context",
            status="weak",
            confidence=0.38,
            selected_ids=[],
        ),
    )

    assert report["status"] in {"weakly_aligned", "unsupported_memory_detail"}
    assert report["aligned_claim_count"] == 0


def test_contradiction_flag_dominates_alignment() -> None:
    report = evaluate_memory_alignment(
        "I remember you prefer fewer emoji.",
        _ledger(
            summary="user preference: fewer emoji",
            source_family="durable",
            status="contradicted",
            confidence=0.9,
            contradiction_flags=["preference_conflict"],
        ),
    )

    assert report["status"] == "contradicted_memory_detail"
    assert report["contradicted_claim_count"] == 1
    assert report["repair_required"] is True


def test_repair_unsupported_detail_does_not_leak_internal_labels() -> None:
    original = "I remember you told me before that you prefer fewer emoji."
    report = evaluate_memory_alignment(
        original,
        _ledger(summary="discussed git diff and tests", source_family="archive", status="grounded", confidence=0.9),
    )
    repaired = repair_memory_alignment(original, report, channel="holo_cli")

    assert "does not clearly support that exact detail" in repaired
    assert "alignment_score" not in repaired
    assert "Stage141" not in repaired


def test_evidence_texts_can_use_sidecar_and_debug_metadata() -> None:
    evidence = build_memory_evidence_texts(
        [],
        sidecar={
            "graph_trace_summary": "user preference: fewer emoji",
            "graph_confidence": 0.83,
            "recent_dialogue_window": {"lines": ["user: please use fewer emoji"]},
        },
        reply_debug={"recall_reconstruction": {"summary": "preference anchor: fewer emoji", "anchors": ["emoji"]}},
    )

    assert any(item["source_family"] == "mind_graph" for item in evidence)
    assert any("fewer emoji" in item["text"] for item in evidence)
