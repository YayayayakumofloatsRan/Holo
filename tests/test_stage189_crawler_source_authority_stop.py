from __future__ import annotations

from holo_host.agent_event_stream import build_agent_event_stream, render_agent_event_stream
from holo_host.live_crawler_search import run_live_crawler_search


def _financial_search_factory() -> callable:
    calls: list[str] = []

    def search(query: str) -> dict:
        calls.append(query)
        if len(calls) == 1:
            return {
                "query": query,
                "status": "ok",
                "provider": "mock_search",
                "results": [
                    {
                        "title": "Apple 10-K financial analysis",
                        "url": "https://random.example.com/apple-10k-analysis",
                        "snippet": "Apple 2024 10-K annual report financial analysis.",
                    }
                ],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "mock_search",
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                }
            ],
        }

    return search


def _financial_page(url: str) -> dict:
    if "sec.gov" in url:
        return {
            "url": url,
            "status": "ok",
            "provider": "mock_page",
            "html": "<html><title>Apple Form 10-K</title><body>Apple Form 10-K annual report fiscal year 2024 financial filing.</body></html>",
        }
    return {
        "url": url,
        "status": "ok",
        "provider": "mock_page",
        "html": "<html><title>Apple 10-K financial analysis</title><body>Apple 2024 10-K annual report financial analysis by a third party.</body></html>",
    }


def _docs_search(query: str) -> dict:
    return {
        "query": query,
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "CLI - Codex | OpenAI Developers",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation.",
            }
        ],
    }


def _docs_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "mock_page",
        "html": "<html><title>CLI - Codex | OpenAI Developers</title><body>Codex CLI is OpenAI official documentation for a terminal coding agent.</body></html>",
    }


def test_stage189_financial_crawler_does_not_stop_on_wrong_authority() -> None:
    report = run_live_crawler_search(
        user_text="search Apple 2024 10-K annual report financial filing",
        web_search_fn=_financial_search_factory(),
        open_page_fn=_financial_page,
        network_enabled=True,
        max_queries=3,
    )

    assert report["status"] == "sufficient"
    assert report["query_count"] >= 2
    assert report["source_authority_report"]["status"] == "sufficient"
    assert report["source_authority_report"]["best_sources"][0]["source_family"] == "financial_filing"
    assert "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm" in report["source_urls"]
    assert "https://random.example.com/apple-10k-analysis" not in report["source_urls"]


def test_stage189_crawler_records_authority_status_per_evaluation() -> None:
    report = run_live_crawler_search(
        user_text="search Apple 2024 10-K annual report financial filing",
        web_search_fn=_financial_search_factory(),
        open_page_fn=_financial_page,
        network_enabled=True,
        max_queries=3,
    )
    evaluations = [row for row in report["crawler_ledger"] if row["phase"] == "evaluate"]

    assert evaluations[0]["authority_status"] == "insufficient"
    assert evaluations[0]["stop_reason"] == "authority_insufficient"
    assert evaluations[-1]["authority_status"] == "sufficient"


def test_stage189_official_docs_still_stop_when_authority_is_sufficient() -> None:
    report = run_live_crawler_search(
        user_text="search OpenAI Codex CLI official documentation",
        web_search_fn=_docs_search,
        open_page_fn=_docs_page,
        network_enabled=True,
    )

    assert report["status"] == "sufficient"
    assert report["query_count"] == 1
    assert report["source_authority_report"]["status"] == "sufficient"
    assert report["source_authority_report"]["best_sources"][0]["source_family"] == "official_docs"


def test_stage189_event_stream_renders_authority_status() -> None:
    report = run_live_crawler_search(
        user_text="search Apple 2024 10-K annual report financial filing",
        web_search_fn=_financial_search_factory(),
        open_page_fn=_financial_page,
        network_enabled=True,
        max_queries=3,
    )

    rendered = render_agent_event_stream(
        build_agent_event_stream(
            {"text": report["final_summary"], "stage186_live_crawler_search": report},
            user_text="search Apple 2024 10-K annual report financial filing",
            channel="holo_cli",
        )
    )

    assert "authority=sufficient" in rendered
