from __future__ import annotations

import importlib
import importlib.util

from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack
from holo_host.tool_action_space import build_tool_action_space


SAMPLE_10K_TEXT = """
Item 1. Business
Apple designs, manufactures and markets smartphones, personal computers, tablets, wearables and accessories.

Item 1A. Risk Factors
The Company is exposed to intense competition, supply chain disruption, foreign exchange risk and regulatory risks.

Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations
Net sales were $391.0 billion in 2024 compared to $383.3 billion in 2023. Net income was $93.7 billion in 2024.

Item 8. Financial Statements and Supplementary Data
The consolidated statements include balance sheets, statements of operations, comprehensive income, shareholders' equity and cash flows.
"""


def _stage170():
    assert importlib.util.find_spec("holo_host.stage170_market_research_gate") is not None
    return importlib.import_module("holo_host.stage170_market_research_gate")


def _sec_observation() -> list[dict]:
    return [
        {
            "status": "ok",
            "source_urls": ["https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"],
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                }
            ],
        }
    ]


def _ready_pack() -> dict:
    return build_market_research_pack(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=_sec_observation(),
        filing_text=SAMPLE_10K_TEXT,
    )


def test_detects_market_research_need_from_filing_and_financial_language() -> None:
    stage170 = _stage170()

    report = stage170.detect_market_research_need("Analyze Apple AAPL 2024 10-K net sales and risk factors.")

    assert report["schema"] == "holo.stage170.market_research_need.v1"
    assert report["needs_market_research_pack"] is True
    assert "financial_claim_possible" in report["reason_flags"]
    assert "filing_analysis_possible" in report["reason_flags"]


def test_generic_engineering_request_does_not_require_market_pack() -> None:
    stage170 = _stage170()

    report = stage170.detect_market_research_need("Inspect holo_host/reply_api.py and run pytest.")

    assert report["needs_market_research_pack"] is False
    assert report["confidence"] < 0.5


def test_missing_pack_blocks_financial_claims() -> None:
    stage170 = _stage170()

    report = stage170.evaluate_market_research_answer(
        "Apple net sales were $391.0 billion in 2024.",
        None,
        user_text="Analyze Apple AAPL 2024 10-K.",
    )

    assert report["status"] == "blocked_missing_pack"
    assert report["repair_required"] is True
    assert report["financial_claim_count"] == 1


def test_ready_pack_supports_metric_claims_and_formats_citations() -> None:
    stage170 = _stage170()
    pack = _ready_pack()

    text = "Apple net sales were $391.0 billion in 2024, and net income was $93.7 billion."
    report = stage170.evaluate_market_research_answer(text, pack, user_text="Analyze Apple 2024 10-K.")
    formatted = stage170.repair_market_research_answer(text, report, market_research_pack=pack)

    assert report["status"] == "supported"
    assert report["supported_claim_count"] == 2
    assert report["repair_required"] is False
    assert "[1]" in formatted
    assert "sec.gov" in formatted
    assert "filing_section:" in formatted or "metric:" in formatted


def test_insufficient_pack_blocks_third_party_only_source() -> None:
    stage170 = _stage170()
    pack = build_market_research_pack(
        query="Apple 2024 10-K financial analysis",
        web_observation_ledger=[
            {
                "status": "ok",
                "source_urls": ["https://random.example.com/apple-10k-analysis"],
                "results": [
                    {
                        "title": "Apple 10-K Analysis",
                        "url": "https://random.example.com/apple-10k-analysis",
                        "snippet": "A third-party summary of Apple financials.",
                    }
                ],
            }
        ],
        filing_text=SAMPLE_10K_TEXT,
    )

    report = stage170.evaluate_market_research_answer(
        "Apple net sales were $391.0 billion in 2024.",
        pack,
        user_text="Analyze Apple 2024 10-K.",
    )

    assert report["status"] == "blocked_insufficient_pack"
    assert "source_authority_insufficient" in report["failure_reasons"]
    assert report["repair_required"] is True


def test_incomplete_filing_checklist_blocks_final_financial_analysis() -> None:
    stage170 = _stage170()
    incomplete_text = SAMPLE_10K_TEXT.replace("Item 7.", "Item 6.")
    pack = build_market_research_pack(
        query="Apple AAPL 2024 10-K financial analysis",
        web_observation_ledger=_sec_observation(),
        filing_text=incomplete_text,
    )

    report = stage170.evaluate_market_research_answer(
        "Apple net income was $93.7 billion in 2024.",
        pack,
        user_text="Analyze Apple 2024 10-K.",
    )

    assert report["status"] == "blocked_insufficient_pack"
    assert "filing_checklist_incomplete" in report["failure_reasons"]


def test_metric_conflict_blocks_settled_financial_claims() -> None:
    stage170 = _stage170()
    pack = _ready_pack()
    pack["status"] = "insufficient"
    pack["failure_reasons"] = ["metric_conflict"]
    pack["metric_consistency"] = {
        "schema": "holo.stage169.metric_consistency.v1",
        "status": "conflicted",
        "conflict_count": 1,
        "conflicts": [{"metric_key": "net_sales", "period": "2024"}],
    }

    report = stage170.evaluate_market_research_answer(
        "Apple net sales were $391.0 billion in 2024.",
        pack,
        user_text="Analyze Apple 2024 10-K.",
    )

    assert report["status"] == "blocked_insufficient_pack"
    assert "metric_conflict" in report["failure_reasons"]


def test_unsupported_metric_claim_is_blocked_even_with_ready_pack() -> None:
    stage170 = _stage170()
    pack = _ready_pack()

    report = stage170.evaluate_market_research_answer(
        "Apple operating income was $120.0 billion in 2024.",
        pack,
        user_text="Analyze Apple 2024 10-K.",
    )

    assert report["status"] == "unsupported_financial_claim"
    assert report["unsupported_claim_count"] == 1
    assert "operating_income" in report["claims"][0]["missing_evidence_keys"]


def test_repair_for_missing_pack_is_bounded_and_has_no_internal_labels() -> None:
    stage170 = _stage170()
    text = "Apple net sales were $391.0 billion in 2024."
    report = stage170.evaluate_market_research_answer(text, None, user_text="Analyze Apple 2024 10-K.")

    repaired = stage170.repair_market_research_answer(text, report, channel="holo_cli")

    assert "source-authority-sufficient filing pack" in repaired
    assert "stage170" not in repaired.lower()
    assert "claim_id" not in repaired


def test_action_space_exposes_market_research_pack_affordance() -> None:
    actions = {row["action_type"]: row for row in build_tool_action_space()}

    assert "market_research_pack" in actions
    assert actions["market_research_pack"]["requires_network"] is True
    assert actions["market_research_pack"]["is_readonly"] is True
    assert actions["market_research_pack"]["observation_schema"]["ledger"] == "market_research_pack"


def test_stage135_topology_includes_market_research_gate_node() -> None:
    stage170 = _stage170()
    gate = stage170.evaluate_market_research_answer(
        "Apple net sales were $391.0 billion in 2024.",
        _ready_pack(),
        user_text="Analyze Apple 2024 10-K.",
    )

    topology = build_stage135_i_state_topology(stage170_market_research_gate=gate)

    assert topology["metrics"]["market_research_gate_node_count"] >= 1
    assert topology["metrics"]["market_research_gate_status"] == "supported"
    assert any(node["id"] == "stage170_market_research_gate" for node in topology["nodes"])
