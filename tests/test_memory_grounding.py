from __future__ import annotations

from holo_host.memory_grounding import (
    MEMORY_GROUNDING_SCHEMA,
    evaluate_memory_grounding,
    normalize_memory_observation_ledger,
    repair_memory_claims,
)


def test_explicit_memory_query_produces_missing_ledger_when_no_source_available() -> None:
    ledger = normalize_memory_observation_ledger(query="\u56de\u5fc6\u4e00\u4e0b\u6700\u65e9\u7684\u8bb0\u5fc6")

    assert len(ledger) == 1
    assert ledger[0]["schema"] == MEMORY_GROUNDING_SCHEMA
    assert ledger[0]["source_family"] == "none"
    assert ledger[0]["status"] == "missing"
    assert ledger[0]["missing_source"] is True


def test_selected_memory_ids_ground_visible_recall_claim() -> None:
    ledger = normalize_memory_observation_ledger(
        sidecar={
            "selected_memory_ids": ["archive:turn-1"],
            "activation_trace_ids": ["mind:node-2"],
            "graph_confidence": 0.81,
            "retrieval_mode": "graph-led",
            "graph_trace_summary": "origin turn and related mind graph node selected",
        },
        query="do you remember the first thread",
    )
    report = evaluate_memory_grounding("I remember the first thread as a repair task.", ledger)

    assert {row["source_family"] for row in ledger} == {"archive"}
    assert ledger[0]["status"] == "grounded"
    assert report["status"] == "grounded"
    assert report["grounded_count"] == 1


def test_ungrounded_memory_claim_is_marked_and_repaired() -> None:
    report = evaluate_memory_grounding("I remember you told me before that blue was preferred.", [])

    assert report["status"] == "ungrounded_memory_claim"
    assert sorted(report["claimed_families"]) == ["memory_recall", "prior_user_statement"]
    repaired = repair_memory_claims(
        "I remember you told me before that blue was preferred.",
        report,
        channel="holo_cli",
    )
    assert "Memory source unavailable" in repaired
    assert "cannot verify" in repaired


def test_weak_memory_source_bounds_confident_recall_language() -> None:
    ledger = normalize_memory_observation_ledger(
        [
            {
                "memory_call_id": "current-context",
                "source_family": "current_context",
                "selected_ids": [],
                "status": "weak",
                "summary": "only current context was available",
                "confidence": 0.32,
                "freshness": "current_context",
                "grounding_tags": ["memory", "current_context"],
            }
        ]
    )
    report = evaluate_memory_grounding("\u6211\u8bb0\u5f97\u4f60\u4e4b\u524d\u8bf4\u8fc7\u8981\u5c11\u7528 emoji", ledger)
    repaired = repair_memory_claims("\u6211\u8bb0\u5f97\u4f60\u4e4b\u524d\u8bf4\u8fc7\u8981\u5c11\u7528 emoji", report)

    assert report["status"] == "weak_memory_source"
    assert "Memory source weak" in repaired
    assert "\u4e0d\u5b8c\u5168\u786e\u5b9a" in repaired


def test_memory_tool_observation_becomes_memory_ledger_source() -> None:
    ledger = normalize_memory_observation_ledger(
        tool_observation_ledger=[
            {
                "provider_call_id": "call_memory",
                "tool": "memory_recall",
                "status": "ok",
                "summary": "found durable preference row",
                "data_keys": ["items"],
                "grounding_tags": ["memory"],
            }
        ],
        query="do you remember my preference",
    )

    assert ledger[0]["memory_call_id"] == "call_memory"
    assert ledger[0]["source_family"] == "durable"
    assert ledger[0]["status"] == "grounded"
