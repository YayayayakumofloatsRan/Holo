from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli


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


def _stage169():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage169_market_research_pack") is not None
    return importlib.import_module("holo_host.stage169_market_research_pack")


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


def test_entity_normalization_resolves_apple_aapl_and_cik() -> None:
    stage169 = _stage169()

    entity = stage169.normalize_market_entity("Analyze Apple AAPL 2024 10-K")

    assert entity["schema"] == "holo.stage169.market_entity.v1"
    assert entity["canonical_name"] == "Apple Inc."
    assert entity["ticker"] == "AAPL"
    assert entity["cik"] == "0000320193"
    assert entity["confidence"] >= 0.9


def test_extract_filing_sections_finds_business_risk_mda_and_financials() -> None:
    stage169 = _stage169()

    report = stage169.extract_filing_sections(
        SAMPLE_10K_TEXT,
        source_url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
    )

    section_ids = {row["section_id"] for row in report["sections"]}
    assert {"business", "risk_factors", "mda", "financial_statements"}.issubset(section_ids)
    assert report["section_count"] >= 4
    assert all(row["source_url"].startswith("https://www.sec.gov/") for row in report["sections"])


def test_filing_checklist_marks_missing_mda_incomplete() -> None:
    stage169 = _stage169()
    sections = stage169.extract_filing_sections(SAMPLE_10K_TEXT.replace("Item 7.", "Item 6."))["sections"]

    checklist = stage169.evaluate_filing_checklist(sections, filing_type="10-K")

    assert checklist["schema"] == "holo.stage169.filing_checklist.v1"
    assert checklist["status"] == "incomplete"
    assert "mda" in checklist["missing_sections"]
    assert checklist["coverage_score"] < 1.0


def test_market_research_pack_requires_primary_filing_source() -> None:
    stage169 = _stage169()

    pack = stage169.build_market_research_pack(
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

    assert pack["status"] == "insufficient"
    assert "source_authority_insufficient" in pack["failure_reasons"]


def test_market_research_pack_ready_with_sec_source_and_required_sections() -> None:
    stage169 = _stage169()

    pack = stage169.build_market_research_pack(
        query="Apple 2024 10-K financial analysis",
        web_observation_ledger=_sec_observation(),
        filing_text=SAMPLE_10K_TEXT,
    )

    assert pack["schema"] == "holo.stage169.market_research_pack.v1"
    assert pack["status"] == "ready"
    assert pack["filing_checklist"]["coverage_score"] == 1.0
    assert pack["source_authority"]["status"] == "sufficient"
    assert pack["evidence_item_count"] >= 4


def test_financial_metric_extraction_returns_revenue_and_net_income() -> None:
    stage169 = _stage169()

    metrics = stage169.extract_financial_metrics(SAMPLE_10K_TEXT)

    metric_keys = {row["metric_key"] for row in metrics["metrics"]}
    assert "net_sales" in metric_keys
    assert "net_income" in metric_keys
    assert any(row["value"] == 391.0 and row["unit"] == "billion_usd" for row in metrics["metrics"])


def test_metric_consistency_flags_conflicting_values() -> None:
    stage169 = _stage169()

    report = stage169.evaluate_metric_consistency(
        [
            {"metric_key": "net_sales", "period": "2024", "value": 391.0, "unit": "billion_usd", "source_url": "sec"},
            {"metric_key": "net_sales", "period": "2024", "value": 410.0, "unit": "billion_usd", "source_url": "blog"},
        ]
    )

    assert report["status"] == "conflicted"
    assert report["conflict_count"] == 1
    assert report["conflicts"][0]["metric_key"] == "net_sales"


def test_metric_consistency_accepts_equivalent_values() -> None:
    stage169 = _stage169()

    report = stage169.evaluate_metric_consistency(
        [
            {"metric_key": "net_sales", "period": "2024", "value": 391.0, "unit": "billion_usd", "source_url": "sec"},
            {"metric_key": "net_sales", "period": "2024", "value": 391.04, "unit": "billion_usd", "source_url": "ir"},
        ]
    )

    assert report["status"] == "consistent"
    assert report["conflict_count"] == 0


def test_cli_dry_run_writes_market_research_pack_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage169_market_research_pack.html"

    code = cli.main(["run-market-research-pack", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["schema"] == "holo.stage169.market_research_pack_bundle.v1"


def test_public_artifacts_safe(tmp_path: Path) -> None:
    stage169 = _stage169()
    output = tmp_path / "safe.html"

    stage169.run_market_research_pack_bundle(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
