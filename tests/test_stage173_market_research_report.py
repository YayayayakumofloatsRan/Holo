from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import (
    build_market_research_pack,
    default_market_research_pack_fixtures,
)


def _ready_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def _third_party_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[1]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def test_build_market_research_report_from_ready_pack_has_sections_metrics_and_citations() -> None:
    from holo_host.stage173_market_research_report import build_market_research_report

    report = build_market_research_report(
        market_research_pack=_ready_pack(),
        question="Analyze Apple using its 2024 10-K.",
    )

    assert report["schema"] == "holo.stage173.market_research_report.v1"
    assert report["status"] == "evidence_ready"
    assert report["entity"]["ticker"] == "AAPL"
    assert report["section_count"] >= 4
    assert report["metric_count"] >= 2
    section_ids = {section["section_id"] for section in report["sections"]}
    assert {"business", "risk_factors", "mda", "financial_statements"}.issubset(section_ids)
    assert report["citation_count"] >= 1
    assert all(citation["url"].startswith("https://www.sec.gov/") for citation in report["citations"])


def test_report_marks_third_party_source_as_insufficient() -> None:
    from holo_host.stage173_market_research_report import build_market_research_report

    report = build_market_research_report(market_research_pack=_third_party_pack())

    assert report["status"] == "evidence_insufficient"
    assert "source_authority_insufficient" in report["unsupported_claims"]
    assert report["analyst_conclusion"]["status"] == "evidence_insufficient"


def test_report_tracks_missing_sections_and_metric_limitations() -> None:
    from holo_host.stage173_market_research_report import build_market_research_report

    fixture = default_market_research_pack_fixtures()[0]
    pack = build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"].replace("Item 7.", "Item 6.").replace("Net sales", "Sales figure"),
    )

    report = build_market_research_report(market_research_pack=pack)

    assert report["status"] == "evidence_insufficient"
    assert "filing_checklist_incomplete" in report["unsupported_claims"]
    assert any("mda" in item for item in report["limitations"])


def test_report_does_not_emit_investment_recommendation_or_target_price() -> None:
    from holo_host.stage173_market_research_report import build_market_research_report

    report = build_market_research_report(market_research_pack=_ready_pack())
    blob = json.dumps(report, ensure_ascii=False).lower()

    assert "buy" not in blob
    assert "sell" not in blob
    assert "target price" not in blob
    assert report["analyst_conclusion"]["investment_recommendation"] == "not_provided"


def test_baseline_comparison_scores_full_stack_above_weak_web_baseline() -> None:
    from holo_host.stage173_market_research_report import (
        build_market_research_report,
        compare_market_research_baselines,
    )

    report = build_market_research_report(market_research_pack=_ready_pack())
    comparison = compare_market_research_baselines(report=report)

    assert comparison["schema"] == "holo.stage173.market_research_baseline_comparison.v1"
    assert comparison["full_stack_score"] > comparison["weak_web_baseline_score"]
    assert comparison["verdict"] == "full_stack_stronger"


def test_cli_dry_run_writes_market_research_report_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage173_market_research_report.html"

    code = cli.main(["run-market-research-report", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage173.market_research_report_bundle.v1"
    assert payload["summary"]["ready_report_rate"] > 0.0


def test_stage135_topology_includes_market_research_report_node() -> None:
    from holo_host.stage173_market_research_report import build_market_research_report

    report = build_market_research_report(market_research_pack=_ready_pack())

    topology = build_stage135_i_state_topology(stage173_market_research_report=report)

    assert topology["metrics"]["market_research_report_node_count"] == 1
    assert topology["metrics"]["market_research_report_status"] == "evidence_ready"
    assert any(node["id"] == "stage173_market_research_report" for node in topology["nodes"])


def test_public_artifacts_are_release_safe(tmp_path: Path) -> None:
    from holo_host.stage173_market_research_report import run_market_research_report_bundle

    output = tmp_path / "safe.html"
    bundle = run_market_research_report_bundle(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert bundle["authority_boundary"]["provider_model_calls"] is False
    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
