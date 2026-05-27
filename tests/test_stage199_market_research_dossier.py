from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_finalization_gate import build_market_research_finalization_gate
from holo_host.market_research_report_assembly import assemble_market_research_report
from holo_host.market_research_source_promotion import promote_market_research_sources
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage169_market_research_pack import build_market_research_pack, default_market_research_pack_fixtures
from holo_host.stage173_market_research_report import build_market_research_report


SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


def _ready_pack() -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return build_market_research_pack(
        query=fixture["query"],
        web_observation_ledger=fixture["web_observation_ledger"],
        filing_text=fixture["filing_text"],
    )


def _ready_report() -> dict:
    return build_market_research_report(market_research_pack=_ready_pack(), question="Analyze Apple AAPL 2024 10-K.")


def _promoted_source() -> dict:
    return promote_market_research_sources(
        question="Analyze Apple AAPL 2024 10-K.",
        web_observation_ledger=[
            {
                "schema": "holo.web_observation.v1",
                "observation_id": "web:sec",
                "action_type": "web_search",
                "query": "Apple AAPL 2024 10-K",
                "status": "ok",
                "provider": "mock",
                "results": [{"title": "Apple Form 10-K", "url": SEC_URL, "snippet": "Apple annual report."}],
                "source_urls": [SEC_URL],
                "page_evidence": {
                    "schema": "holo.stage163.page_evidence.v1",
                    "status": "supported",
                    "selected_url": SEC_URL,
                    "opened_count": 1,
                    "page_observations": [{"url": SEC_URL, "status": "ok", "text": "Item 1. Business Item 7. MD&A Item 8. Financial Statements"}],
                },
            }
        ],
        network_enabled=False,
    )


def _assembled_stack() -> tuple[dict, dict, dict, dict]:
    report = _ready_report()
    promotion = _promoted_source()
    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=promotion,
        stage173_market_research_report=report,
    )
    finalization = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=assembly,
        candidate_visible_text="draft",
    )
    return promotion, report, assembly, finalization


def test_stage199_builds_resume_ready_dossier_from_final_report() -> None:
    from holo_host.market_research_task_dossier import (
        STAGE199_MARKET_RESEARCH_TASK_DOSSIER_SCHEMA,
        build_market_research_task_dossier,
    )

    promotion, report, assembly, finalization = _assembled_stack()
    dossier = build_market_research_task_dossier(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=promotion,
        stage173_market_research_report=report,
        stage197_market_research_report_assembly=assembly,
        stage198_market_research_finalization_gate=finalization,
    )

    assert dossier["schema"] == STAGE199_MARKET_RESEARCH_TASK_DOSSIER_SCHEMA
    assert dossier["status"] == "report_ready"
    assert dossier["resume_state"]["can_resume"] is True
    assert dossier["source_count"] >= 1
    assert SEC_URL in dossier["source_urls"]
    assert dossier["metric_count"] >= 1
    assert dossier["next_actions"] == []
    assert dossier["final_answer"]["status"] == "finalized"


def test_stage199_dossier_preserves_open_items_for_insufficient_evidence() -> None:
    from holo_host.market_research_task_dossier import build_market_research_task_dossier

    assembly = assemble_market_research_report(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion={
            "status": "weak",
            "authority_status": "insufficient",
            "source_family": "third_party_summary",
            "selected_url": "https://example.com/apple",
            "missing_authority": ["financial_filing"],
            "canonical_stop_reason": "evidence_exhausted",
        },
        stage173_market_research_report={},
    )
    finalization = build_market_research_finalization_gate(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=assembly,
        candidate_visible_text="draft",
    )
    dossier = build_market_research_task_dossier(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly=assembly,
        stage198_market_research_finalization_gate=finalization,
    )

    assert dossier["status"] == "needs_evidence"
    assert dossier["resume_state"]["can_resume"] is True
    assert dossier["open_items"]
    assert any("financial_filing" in item for item in dossier["open_items"])
    assert any(action["action_type"] == "web_search" for action in dossier["next_actions"])


def test_stage199_writes_html_json_jsonl_artifacts(tmp_path: Path) -> None:
    from holo_host.market_research_task_dossier import run_market_research_dossier_bundle

    output = tmp_path / "stage199_dossier.html"
    bundle = run_market_research_dossier_bundle(output=output, dry_run=True)

    assert bundle["schema"] == "holo.stage199.market_research_dossier_bundle.v1"
    assert bundle["status"] == "passed"
    assert Path(bundle["artifacts"]["html"]).exists()
    assert Path(bundle["artifacts"]["json"]).exists()
    assert Path(bundle["artifacts"]["jsonl"]).exists()
    assert "Stage199 Market Research Task Dossier" in Path(bundle["artifacts"]["html"]).read_text(encoding="utf-8")
    assert json.loads(Path(bundle["artifacts"]["json"]).read_text(encoding="utf-8"))["dossier_count"] >= 1


def test_stage199_event_stream_and_topology_render_dossier() -> None:
    from holo_host.market_research_task_dossier import build_market_research_task_dossier

    promotion, report, assembly, finalization = _assembled_stack()
    dossier = build_market_research_task_dossier(
        question="Analyze Apple AAPL 2024 10-K.",
        stage196_market_research_source_promotion=promotion,
        stage173_market_research_report=report,
        stage197_market_research_report_assembly=assembly,
        stage198_market_research_finalization_gate=finalization,
    )
    stream = build_agent_event_stream(
        {"stage199_market_research_task_dossier": dossier, "reasoning_content": "hidden private text"},
        user_text="Analyze Apple",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    topology = build_stage135_i_state_topology(stage199_market_research_task_dossier=dossier)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_dossier]" in rendered
    assert "status=report_ready" in rendered
    assert "hidden private text" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_dossier_node_count"] == 1
    assert topology["metrics"]["market_research_dossier_status"] == "report_ready"


def test_stage199_cli_command_writes_dossier(tmp_path: Path) -> None:
    from holo_host.cli import command_run_market_research_dossier

    output = tmp_path / "cli_dossier.html"
    code = command_run_market_research_dossier(output=str(output), dry_run=True, fail_under=None)

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
