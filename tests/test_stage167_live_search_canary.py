from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli


def _stage167():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage167_live_search_canary") is not None
    return importlib.import_module("holo_host.stage167_live_search_canary")


def test_provider_comparison_ranks_official_supported_source_above_irrelevant_provider() -> None:
    stage167 = _stage167()

    report = stage167.compare_search_providers(
        "OpenAI Codex CLI official docs",
        [
            {
                "provider": "blog_provider",
                "status": "ok",
                "web_observation_ledger": [
                    {
                        "source_urls": ["https://random.example/blog"],
                        "source_synthesis": {
                            "status": "weak",
                            "confidence": 0.35,
                            "supported_source_count": 0,
                            "citations": [{"url": "https://random.example/blog", "snippet": "personal notes"}],
                            "synthesized_summary": "personal notes about unrelated coding assistants",
                        },
                    }
                ],
            },
            {
                "provider": "official_provider",
                "status": "ok",
                "web_observation_ledger": [
                    {
                        "source_urls": ["https://developers.openai.com/codex/cli"],
                        "source_synthesis": {
                            "status": "supported",
                            "confidence": 0.93,
                            "supported_source_count": 1,
                            "citations": [
                                {
                                    "url": "https://developers.openai.com/codex/cli",
                                    "snippet": "Codex CLI is a terminal coding agent from OpenAI.",
                                }
                            ],
                            "synthesized_summary": "Codex CLI is a terminal coding agent from OpenAI.",
                        },
                    }
                ],
            },
        ],
    )

    assert report["schema"] == "holo.stage167.provider_comparison.v1"
    assert report["provider_count"] == 2
    assert report["best_provider"] == "official_provider"
    assert report["ranked_providers"][0]["score"] > report["ranked_providers"][1]["score"]
    assert report["status"] == "supported"


def test_provider_comparison_records_provider_failures_without_hiding_success() -> None:
    stage167 = _stage167()

    report = stage167.compare_search_providers(
        "DeepSeek tool calling docs",
        [
            {"provider": "failing_provider", "status": "error", "error": "timeout"},
            {
                "provider": "official_provider",
                "status": "ok",
                "web_observation_ledger": [
                    {
                        "source_synthesis": {
                            "status": "supported",
                            "confidence": 0.88,
                            "supported_source_count": 1,
                            "citations": [
                                {
                                    "url": "https://api-docs.deepseek.com/guides/function_calling",
                                    "snippet": "DeepSeek documents function calling through tool messages.",
                                }
                            ],
                            "synthesized_summary": "DeepSeek documents function calling through tool messages.",
                        }
                    }
                ],
            },
        ],
    )

    assert report["failed_provider_count"] == 1
    assert report["best_provider"] == "official_provider"
    assert report["status"] == "supported"
    assert any(row["provider"] == "failing_provider" for row in report["ranked_providers"])


def test_freshness_extraction_from_sec_url_and_text() -> None:
    stage167 = _stage167()

    freshness = stage167.extract_source_freshness(
        "Apple Form 10-K annual report for fiscal year 2024.",
        url="https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        observed_at="2026-05-27T00:00:00Z",
    )

    assert freshness["schema"] == "holo.stage167.source_freshness.v1"
    assert freshness["status"] == "observed"
    assert "2024-09-28" in freshness["date_markers"]
    assert "2024" in freshness["year_markers"]
    assert freshness["source_family"] in {"filing_date_or_period", "dated_source"}


def test_freshness_extraction_detects_missing_current_date() -> None:
    stage167 = _stage167()

    freshness = stage167.extract_source_freshness(
        "The latest product update is described here.",
        url="https://example.com/update",
        observed_at="2026-05-27T00:00:00Z",
    )

    assert freshness["status"] == "missing"
    assert freshness["freshness_score"] == 0.0


def test_quote_extraction_returns_clean_bounded_supporting_quote() -> None:
    stage167 = _stage167()

    quote = stage167.extract_supporting_quote(
        """
        @layer theme, base; .page-copy-action{display:inline}
        Codex CLI is a terminal coding agent that can inspect and edit code.
        Footer navigation text.
        """,
        query_terms=["Codex", "CLI", "terminal", "coding agent"],
        max_chars=120,
    )

    assert quote["schema"] == "holo.stage167.quote_extraction.v1"
    assert quote["status"] == "ok"
    assert "Codex CLI" in quote["quote"]
    assert "@layer" not in quote["quote"]
    assert ".page-" not in quote["quote"]
    assert len(quote["quote"]) <= 120


def test_canary_fixture_scores_financial_filing_quote_and_freshness() -> None:
    stage167 = _stage167()
    fixture = next(row for row in stage167.default_live_search_canary_fixtures() if row["fixture_id"] == "financial-filing-apple-10k-canary")

    result = stage167.evaluate_live_search_canary_fixture(fixture)

    assert result["status"] == "passed"
    assert result["metrics"]["freshness_score"] == 1.0
    assert result["metrics"]["quote_quality_score"] == 1.0
    assert "Form 10-K" in result["supporting_quote"]["quote"]


def test_canary_flags_ambiguous_entity_without_disambiguation() -> None:
    stage167 = _stage167()

    result = stage167.evaluate_live_search_canary_fixture(
        {
            "fixture_id": "ambiguous-apple-bad",
            "category_id": "ambiguous_entity",
            "query": "search apple",
            "expected_terms": ["apple", "company", "fruit"],
            "requires_disambiguation": True,
            "provider_observations": [
                {
                    "provider": "official_provider",
                    "status": "ok",
                    "web_observation_ledger": [
                        {
                            "source_urls": ["https://www.apple.com/"],
                            "source_synthesis": {
                                "status": "supported",
                                "confidence": 0.8,
                                "supported_source_count": 1,
                                "citations": [
                                    {
                                        "url": "https://www.apple.com/",
                                        "snippet": "Apple designs consumer technology products.",
                                    }
                                ],
                                "synthesized_summary": "Apple designs consumer technology products.",
                            },
                        }
                    ],
                }
            ],
            "visible_answer": "Apple is a technology company.",
        }
    )

    assert result["status"] == "failed"
    assert "missing_entity_disambiguation" in result["failure_reasons"]


def test_dry_run_writes_live_search_canary_artifacts(tmp_path: Path) -> None:
    stage167 = _stage167()
    output = tmp_path / "stage167_live_search_canary.html"

    report = stage167.run_live_search_canary(output=output, dry_run=True)

    assert report["schema"] == "holo.stage167.live_search_canary.v1"
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["schema"] == report["schema"]


def test_cli_dry_run_writes_live_search_canary_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage167_live_search_canary.html"

    code = cli.main(["run-live-search-canary", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()


def test_public_artifacts_safe(tmp_path: Path) -> None:
    stage167 = _stage167()
    output = tmp_path / "safe.html"

    stage167.run_live_search_canary(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
