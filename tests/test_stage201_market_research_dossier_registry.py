from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_task_dossier import build_market_research_task_dossier
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _dossier(question: str = "Analyze Apple AAPL 2024 10-K.") -> dict:
    return build_market_research_task_dossier(
        question=question,
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


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage201-mock",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple Inc. Form 10-K fiscal 2024 annual report.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "stage201-mock-page",
        "results": [{"title": "Apple 10-K", "url": url, "snippet": "Item 1. Business. Item 7. MD&A. Item 8. Financial Statements."}],
    }


def test_stage201_records_and_loads_latest_dossier_by_thread(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import load_latest_market_research_dossier, record_market_research_dossier

    first = record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier("Analyze Apple first."),
    )
    second = record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier("Analyze Apple second."),
    )
    lookup = load_latest_market_research_dossier(state_dir=tmp_path, thread_key="holo_cli:research")

    assert first["schema"] == "holo.stage201.market_research_dossier_record.v1"
    assert second["record_index"] == 2
    assert lookup["schema"] == "holo.stage201.market_research_dossier_lookup.v1"
    assert lookup["status"] == "found"
    assert lookup["dossier"]["question"] == "Analyze Apple second."
    assert lookup["record"]["thread_key"] == "holo_cli:research"


def test_stage201_path_keys_are_workspace_safe(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import record_market_research_dossier

    record = record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="../../escape",
        project_key="market/apple",
        dossier=_dossier(),
    )

    path = Path(record["path"]).resolve()
    assert str(path).startswith(str((tmp_path / "market_research_dossiers").resolve()))
    assert ".." not in path.name
    assert path.exists()


def test_stage201_resume_latest_uses_stored_dossier(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import record_market_research_dossier, resume_latest_market_research_dossier

    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier(),
    )
    result = resume_latest_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        question="continue the Apple market research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=1,
    )

    assert result["schema"] == "holo.stage201.market_research_dossier_registry.v1"
    assert result["status"] in {"resumed", "completed"}
    assert result["lookup"]["status"] == "found"
    assert result["stage200_market_research_dossier_resume"]["selected_action"] == "web_search"
    assert any(row["status"] == "ok" for row in result["stage200_market_research_dossier_resume"]["web_observation_ledger"])


def test_stage201_missing_lookup_is_explicit(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import resume_latest_market_research_dossier

    result = resume_latest_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:missing",
        question="continue market research",
        network_enabled=True,
        web_search_fn=_mock_search,
        max_actions=1,
    )

    assert result["status"] == "missing"
    assert result["canonical_stop_reason"] == "needs_user_clarification"
    assert result["stage200_market_research_dossier_resume"] == {}


def test_stage201_writes_cli_artifacts_from_registry(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import record_market_research_dossier, run_market_research_dossier_registry_bundle

    record_market_research_dossier(
        state_dir=tmp_path / ".holo_runtime",
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier(),
    )
    output = tmp_path / "stage201_registry.html"
    bundle = run_market_research_dossier_registry_bundle(
        state_dir=tmp_path / ".holo_runtime",
        thread_key="holo_cli:research",
        output=output,
        dry_run=True,
    )

    assert bundle["schema"] == "holo.stage201.market_research_dossier_registry_bundle.v1"
    assert Path(bundle["artifacts"]["html"]).exists()
    assert Path(bundle["artifacts"]["json"]).exists()
    assert Path(bundle["artifacts"]["jsonl"]).exists()
    assert "Stage201 Market Research Dossier Registry" in Path(bundle["artifacts"]["html"]).read_text(encoding="utf-8")


def test_stage201_event_stream_and_topology_render_registry(tmp_path: Path) -> None:
    from holo_host.market_research_dossier_registry import record_market_research_dossier, resume_latest_market_research_dossier

    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier(),
    )
    report = resume_latest_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=1,
    )
    stream = build_agent_event_stream(
        {"stage201_market_research_dossier_registry": report, "reasoning_content": "hidden private text"},
        user_text="continue Apple research",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    topology = build_stage135_i_state_topology(stage201_market_research_dossier_registry=report)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_registry]" in rendered
    assert "lookup=found" in rendered
    assert "hidden private text" not in blob
    assert "reasoning_content" not in blob
    assert topology["metrics"]["market_research_dossier_registry_node_count"] == 1


def test_stage201_cli_command_prints_summary(tmp_path: Path) -> None:
    from holo_host.cli import command_market_research_dossier_state
    from holo_host.market_research_dossier_registry import record_market_research_dossier

    state_dir = tmp_path / ".holo_runtime"
    record_market_research_dossier(
        state_dir=state_dir,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_dossier(),
    )

    code = command_market_research_dossier_state(
        state_dir=str(state_dir),
        thread_key="holo_cli:research",
        project_key="",
        output="",
        dry_run=True,
    )

    assert code == 0
