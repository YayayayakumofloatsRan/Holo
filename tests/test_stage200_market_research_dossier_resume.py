from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_task_dossier import build_market_research_task_dossier
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"


def _needs_evidence_dossier() -> dict:
    return build_market_research_task_dossier(
        question="Analyze Apple AAPL 2024 10-K.",
        stage197_market_research_report_assembly={
            "schema": "holo.stage197.market_research_report_assembly.v1",
            "status": "needs_report",
            "missing_requirements": ["financial_filing_source"],
        },
        stage198_market_research_finalization_gate={
            "schema": "holo.stage198.market_research_finalization_gate.v1",
            "status": "blocked",
            "final_visible_text_ready": False,
            "canonical_stop_reason": "evidence_exhausted",
        },
    )


def _ready_dossier() -> dict:
    return {
        "schema": "holo.stage199.market_research_task_dossier.v1",
        "dossier_id": "stage199_market_dossier:ready",
        "question": "Analyze Apple AAPL 2024 10-K.",
        "status": "report_ready",
        "source_count": 1,
        "metric_count": 2,
        "next_actions": [],
        "final_answer": {"status": "finalized", "visible_text": "ready report"},
        "resume_state": {"can_resume": True, "next_action_count": 0},
    }


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "mock-sec",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": SEC_URL,
                "snippet": "Apple Inc. Form 10-K fiscal 2024 annual report.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "mock-page",
        "results": [
            {
                "title": "Apple Form 10-K",
                "url": url,
                "snippet": "Item 1. Business. Item 1A. Risk Factors. Item 7. MD&A. Item 8. Financial Statements.",
            }
        ],
    }


def test_stage200_ready_dossier_stops_without_action() -> None:
    from holo_host.market_research_dossier_resume import resume_market_research_from_dossier

    report = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_ready_dossier(),
        network_enabled=True,
        max_actions=1,
    )

    assert report["schema"] == "holo.stage200.market_research_dossier_resume.v1"
    assert report["status"] == "already_complete"
    assert report["selected_action"] == ""
    assert report["stage194_market_research_plan_execution"]["executed_count"] == 0
    assert report["canonical_stop_reason"] == "final_answer_ready"


def test_stage200_selects_next_action_from_dossier() -> None:
    from holo_host.market_research_dossier_resume import resume_market_research_from_dossier

    report = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_needs_evidence_dossier(),
        network_enabled=True,
        max_actions=0,
    )

    assert report["status"] == "planned"
    assert report["selected_action"] == "web_search"
    assert "SEC Form 10-K" in report["selected_action_query"]
    assert report["stage193_market_research_action_plan"]["next_action"] == "web_search"


def test_stage200_executes_mocked_web_search_and_records_observation() -> None:
    from holo_host.market_research_dossier_resume import resume_market_research_from_dossier

    report = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_needs_evidence_dossier(),
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=1,
    )

    assert report["status"] in {"resumed", "completed"}
    assert report["selected_action"] == "web_search"
    assert report["stage194_market_research_plan_execution"]["executed_count"] == 1
    assert any(row["status"] == "ok" for row in report["web_observation_ledger"])
    assert SEC_URL in json.dumps(report, ensure_ascii=False)
    assert report["updated_stage199_market_research_task_dossier"]["resume_state"]["can_resume"] is True


def test_stage200_network_disabled_records_rejected_web_action() -> None:
    from holo_host.market_research_dossier_resume import resume_market_research_from_dossier

    report = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_needs_evidence_dossier(),
        network_enabled=False,
        web_search_fn=_mock_search,
        max_actions=1,
    )

    assert report["status"] == "blocked"
    assert report["canonical_stop_reason"] == "boundary_or_permission"
    assert report["stage194_market_research_plan_execution"]["rejected_count"] == 1
    assert any(row["status"] == "rejected_network_disabled" for row in report["web_observation_ledger"])


def test_stage200_writes_html_json_jsonl_artifacts(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_resume import run_market_research_dossier_resume_bundle

    output = tmp_path / "stage200_resume.html"
    bundle = run_market_research_dossier_resume_bundle(output=output, dry_run=True)

    assert bundle["schema"] == "holo.stage200.market_research_dossier_resume_bundle.v1"
    assert Path(bundle["artifacts"]["html"]).exists()
    assert Path(bundle["artifacts"]["json"]).exists()
    assert Path(bundle["artifacts"]["jsonl"]).exists()
    assert "Stage200 Market Research Dossier Resume" in Path(bundle["artifacts"]["html"]).read_text(encoding="utf-8")


def test_stage200_event_stream_and_topology_render_resume() -> None:
    from holo_host.market_research_dossier_resume import resume_market_research_from_dossier

    report = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_needs_evidence_dossier(),
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=1,
    )
    stream = build_agent_event_stream(
        {"stage200_market_research_dossier_resume": report, "reasoning_content": "hidden private text"},
        user_text="continue Apple research",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    topology = build_stage135_i_state_topology(stage200_market_research_dossier_resume=report)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_resume]" in rendered
    assert "action=web_search" in rendered
    assert "hidden private text" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_dossier_resume_node_count"] == 1


def test_stage200_cli_command_writes_resume(tmp_path: Path) -> None:
    from holo_host.cli import command_run_market_research_dossier_resume

    output = tmp_path / "cli_resume.html"
    code = command_run_market_research_dossier_resume(output=str(output), dry_run=True, fail_under=None)

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
