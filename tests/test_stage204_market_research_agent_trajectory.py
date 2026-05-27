from __future__ import annotations

import json
from pathlib import Path

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.market_research_dossier_registry import record_market_research_dossier
from holo_host.market_research_task_dossier import build_market_research_task_dossier
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage152_deepseek_tool_loop import execute_deepseek_native_tool_call
from holo_host.stage169_market_research_pack import default_market_research_pack_fixtures


def _weak_dossier() -> dict:
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


def _mock_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "stage204-sec-search",
        "results": [
            {
                "title": "Apple Form 10-K 2024",
                "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                "snippet": "Apple annual report on Form 10-K.",
            }
        ],
    }


def _mock_open_page(url: str) -> dict:
    fixture = default_market_research_pack_fixtures()[0]
    return {
        "url": url,
        "status": "ok",
        "provider": "stage204-sec-page",
        "html": fixture["filing_text"],
    }


def _record_weak_dossier(tmp_path: Path) -> None:
    record_market_research_dossier(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        dossier=_weak_dossier(),
    )


def test_stage204_resume_runs_bounded_market_research_trajectory(tmp_path: Path) -> None:
    from holo_host.market_research_agent_trajectory import run_market_research_dossier_agent_trajectory

    _record_weak_dossier(tmp_path)
    report = run_market_research_dossier_agent_trajectory(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        question="continue Apple research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=4,
    )

    assert report["schema"] == "holo.stage204.market_research_agent_trajectory.v1"
    assert report["status"] == "ready"
    assert report["stage195_market_research_continuation_loop"]["status"] == "ready"
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert report["action_sequence"] == ["web_search", "market_research_pack", "market_research_report"]
    assert [row["action_type"] for row in report["trajectory_rows"] if row["action_type"]] == [
        "web_search",
        "market_research_pack",
        "market_research_report",
    ]
    assert report["trajectory_round_count"] >= 3


def test_stage204_single_action_does_not_force_continuation(tmp_path: Path) -> None:
    from holo_host.market_research_agent_trajectory import run_market_research_dossier_agent_trajectory

    _record_weak_dossier(tmp_path)
    report = run_market_research_dossier_agent_trajectory(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        question="continue Apple research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=1,
    )

    assert report.get("stage195_market_research_continuation_loop", {}) == {}
    assert report["action_sequence"] == ["web_search"]
    assert report["status"] in {"resumed", "partial"}


def test_stage204_deepseek_resume_tool_returns_trajectory(tmp_path: Path) -> None:
    _record_weak_dossier(tmp_path)

    result = execute_deepseek_native_tool_call(
        {
            "id": "call_resume",
            "name": "market_research_dossier_resume",
            "arguments": {
                "thread_key": "holo_cli:research",
                "project_key": "market:apple",
                "query": "continue Apple research",
                "max_actions": 4,
            },
            "allowed": True,
        },
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        state_dir=str(tmp_path),
    )

    assert result["stage204_market_research_agent_trajectory"]["status"] == "ready"
    assert result["stage195_market_research_continuation_loop"]["status"] == "ready"
    assert result["stage204_market_research_agent_trajectory"]["action_sequence"] == [
        "web_search",
        "market_research_pack",
        "market_research_report",
    ]


def test_stage204_event_stream_renders_multi_action_trajectory(tmp_path: Path) -> None:
    from holo_host.market_research_agent_trajectory import run_market_research_dossier_agent_trajectory

    _record_weak_dossier(tmp_path)
    report = run_market_research_dossier_agent_trajectory(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        question="continue Apple research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=4,
    )
    stream = build_agent_event_stream(
        {
            "text": "trajectory ready",
            "stage204_market_research_agent_trajectory": report,
            "stage201_market_research_dossier_registry": report["stage201_market_research_dossier_registry"],
            "stage195_market_research_continuation_loop": report["stage195_market_research_continuation_loop"],
            "reasoning_content": "raw hidden reasoning",
        },
        user_text="continue Apple research",
        channel="holo_cli",
    )
    rendered = render_agent_event_stream(stream)
    blob = json.dumps(stream, ensure_ascii=False) + rendered

    assert "[market_trajectory] step=1 action=web_search" in rendered
    assert "[market_trajectory] step=2 action=market_research_pack" in rendered
    assert "[market_trajectory] step=3 action=market_research_report" in rendered
    assert "raw hidden reasoning" not in blob
    assert "reasoning_content" not in blob


def test_stage204_topology_counts_market_research_trajectory(tmp_path: Path) -> None:
    from holo_host.market_research_agent_trajectory import run_market_research_dossier_agent_trajectory

    _record_weak_dossier(tmp_path)
    report = run_market_research_dossier_agent_trajectory(
        state_dir=tmp_path,
        thread_key="holo_cli:research",
        project_key="market:apple",
        question="continue Apple research",
        network_enabled=True,
        web_search_fn=_mock_search,
        open_page_fn=_mock_open_page,
        max_actions=4,
    )
    topology = build_stage135_i_state_topology(stage204_market_research_agent_trajectory=report)

    assert topology["metrics"]["market_research_agent_trajectory_node_count"] == 1
    assert topology["metrics"]["market_research_agent_trajectory_step_count"] >= 3
    assert topology["metrics"]["market_research_agent_trajectory_status"] == "ready"
