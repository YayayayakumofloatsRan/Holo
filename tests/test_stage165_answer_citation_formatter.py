from __future__ import annotations

import importlib
import importlib.util

from holo_host.stage135_i_state_topology import build_stage135_i_state_topology
from holo_host.stage151_tool_decision_loop import build_grounded_web_observation_answer, build_time_observation


def _stage165():
    assert importlib.util.find_spec("holo_host.stage165_answer_citation_formatter") is not None
    return importlib.import_module("holo_host.stage165_answer_citation_formatter")


def _row_with_synthesis(status: str = "supported") -> dict:
    citations = [
        {
            "url": "https://developers.openai.com/codex/cli",
            "status": "supported",
            "snippet": "Codex CLI is OpenAI's terminal coding agent.",
        },
        {
            "url": "https://github.com/openai/codex",
            "status": "supported",
            "snippet": "The openai/codex repository contains the Codex CLI source code.",
        },
    ]
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:codex",
        "action_type": "web_search",
        "query": "OpenAI Codex CLI docs",
        "status": "ok",
        "provider": "mock",
        "results": [
            {
                "title": "Codex CLI",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "official documentation",
            }
        ],
        "source_urls": ["https://developers.openai.com/codex/cli"],
        "source_synthesis": {
            "schema": "holo.stage164.source_synthesis.v1",
            "status": status,
            "query": "OpenAI Codex CLI docs",
            "source_count": 2,
            "supported_source_count": 2 if status == "supported" else 0,
            "weak_source_count": 0 if status == "supported" else 2,
            "conflict_count": 1 if status == "conflicted" else 0,
            "risk_flags": ["source_conflict"] if status == "conflicted" else [],
            "confidence": 0.86 if status == "supported" else 0.38,
            "citations": citations if status != "unsupported" else [],
            "synthesized_summary": "Codex CLI is an OpenAI terminal coding agent with official documentation and source code references.",
            "created_at": "2026-05-27T00:00:00Z",
        },
    }


def test_citation_report_prefers_source_synthesis_citations() -> None:
    stage165 = _stage165()

    report = stage165.build_answer_citation_report(
        [_row_with_synthesis()],
        user_text="search OpenAI Codex CLI docs",
        time_observation={"local_time": "2026-05-27 10:00:00"},
    )

    assert report["schema"] == "holo.stage165.answer_citation_formatter.v1"
    assert report["status"] == "supported"
    assert report["citation_count"] == 2
    assert report["citations"][0]["url"] == "https://developers.openai.com/codex/cli"
    assert report["answer_summary"].startswith("Codex CLI is an OpenAI")


def test_supported_answer_renders_summary_freshness_and_numbered_urls() -> None:
    stage165 = _stage165()
    report = stage165.build_answer_citation_report(
        [_row_with_synthesis()],
        user_text="search OpenAI Codex CLI docs",
        time_observation={"local_time": "2026-05-27 10:00:00"},
    )

    answer = stage165.render_cited_web_answer(report, channel="holo_cli")

    assert "completed the web search" in answer
    assert "verified source pages" in answer
    assert "2026-05-27 10:00:00" in answer
    assert "Codex CLI is an OpenAI terminal coding agent" in answer
    assert "[1] https://developers.openai.com/codex/cli" in answer
    assert "[2] https://github.com/openai/codex" in answer


def test_conflicted_synthesis_renders_bounded_conflict_language() -> None:
    stage165 = _stage165()
    report = stage165.build_answer_citation_report([_row_with_synthesis("conflicted")], user_text="search Codex CLI")

    answer = stage165.render_cited_web_answer(report, channel="holo_cli")

    assert report["status"] == "conflicted"
    assert "conflict" in answer.lower()
    assert "cannot state it as settled" in answer
    assert "confirmed" not in answer.lower()


def test_unsupported_synthesis_renders_no_supported_page_evidence() -> None:
    stage165 = _stage165()
    report = stage165.build_answer_citation_report([_row_with_synthesis("unsupported")], user_text="search Codex CLI")

    answer = stage165.render_cited_web_answer(report, channel="holo_cli")

    assert report["status"] == "unsupported"
    assert "no supported page evidence" in answer.lower()
    assert report["citation_count"] == 0


def test_stage151_grounded_answer_uses_stage165_formatter_when_synthesis_exists() -> None:
    answer = build_grounded_web_observation_answer(
        user_text="search OpenAI Codex CLI docs",
        web_observation_ledger=[_row_with_synthesis()],
        time_observation=build_time_observation(),
    )

    assert "verified source pages" in answer
    assert "Codex CLI is an OpenAI terminal coding agent" in answer
    assert "[1] https://developers.openai.com/codex/cli" in answer
    assert "鎴戝凡瀹屾垚" not in answer


def test_no_internal_stage165_labels_leak_to_visible_answer() -> None:
    stage165 = _stage165()
    answer = stage165.maybe_format_cited_web_answer(
        user_text="search OpenAI Codex CLI docs",
        web_observation_ledger=[_row_with_synthesis()],
        time_observation=build_time_observation(),
        channel="holo_cli",
    )

    forbidden = ("Stage165", "holo.stage165", "source_synthesis", "risk_flags", "schema")
    assert all(item not in answer for item in forbidden)


def test_citation_formatter_deduplicates_urls() -> None:
    stage165 = _stage165()
    row = _row_with_synthesis()
    row["source_synthesis"]["citations"].append(
        {
            "url": "https://developers.openai.com/codex/cli",
            "status": "supported",
            "snippet": "Duplicate citation should not render twice.",
        }
    )

    report = stage165.build_answer_citation_report([row], user_text="search OpenAI Codex CLI docs")

    assert report["citation_count"] == 2


def test_formatter_cleans_css_noise_from_visible_snippets() -> None:
    stage165 = _stage165()
    row = _row_with_synthesis()
    noisy = (
        "CLI - Codex | OpenAI Developers @layer theme, base, components, utilities; "
        ".page-copy-action:where(.astro-y3m22efp){display:inline} "
        "Codex CLI is OpenAI's terminal coding agent."
    )
    row["source_synthesis"]["synthesized_summary"] = noisy
    row["source_synthesis"]["citations"][0]["snippet"] = noisy
    row["results"][0]["snippet"] = "Codex CLI is OpenAI's terminal coding agent."

    answer = stage165.maybe_format_cited_web_answer(web_observation_ledger=[row], user_text="search Codex")

    assert "Codex CLI is OpenAI's terminal coding agent" in answer
    assert "@layer" not in answer
    assert ".page-copy-action" not in answer
    assert "{display:inline}" not in answer


def test_low_information_page_snippet_falls_back_to_search_result_snippet() -> None:
    stage165 = _stage165()
    row = _row_with_synthesis()
    row["source_synthesis"]["synthesized_summary"] = "CLI - Codex | OpenAI Developers CLI - Codex | OpenAI Developers"
    row["source_synthesis"]["citations"][0]["snippet"] = "CLI - Codex | OpenAI Developers CLI - Codex | OpenAI Developers"
    row["results"][0]["snippet"] = "Codex CLI is OpenAI's coding agent that can read, change, and run code locally from the terminal."

    answer = stage165.maybe_format_cited_web_answer(web_observation_ledger=[row], user_text="search Codex")

    assert "read, change, and run code locally" in answer


def test_stage135_topology_includes_answer_citation_formatter_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="search OpenAI Codex CLI docs",
        channel="holo_cli",
        thread_key="holo_cli:stage165",
        chat_name="HoloCLI",
        web_observation_ledger=[_row_with_synthesis()],
    )

    assert topology["metrics"]["answer_citation_formatter_node_count"] == 1
    assert topology["metrics"]["answer_citation_formatter_citation_count"] == 2
    assert any(node["id"] == "stage165_answer_citation_formatter" for node in topology["nodes"])
