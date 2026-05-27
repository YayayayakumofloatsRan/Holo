from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.stage151_tool_decision_loop import execute_tool_decision


def _stage168():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage168_source_authority") is not None
    return importlib.import_module("holo_host.stage168_source_authority")


def test_sec_filing_is_primary_financial_source() -> None:
    stage168 = _stage168()

    report = stage168.classify_source_authority(
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
        query="Apple 2024 10-K annual report",
        title="Apple Form 10-K",
        snippet="Apple Form 10-K annual report for fiscal year 2024.",
    )

    assert report["schema"] == "holo.stage168.source_authority.v1"
    assert report["source_family"] == "financial_filing"
    assert report["authority_tier"] == "primary"
    assert report["source_role"] == "regulatory_filing"
    assert report["is_first_party"] is True
    assert report["confidence"] >= 0.9


def test_company_ir_is_first_party_company_source() -> None:
    stage168 = _stage168()

    report = stage168.classify_source_authority(
        "https://investor.apple.com/investor-relations/default.aspx",
        query="Apple investor relations annual report",
        title="Apple Investor Relations",
        snippet="Investor relations and annual reports for Apple.",
    )

    assert report["source_family"] == "company_ir"
    assert report["authority_tier"] in {"primary", "official"}
    assert report["source_role"] == "company_disclosure"
    assert report["is_first_party"] is True


def test_official_docs_and_api_docs_are_authoritative_for_engineering_docs() -> None:
    stage168 = _stage168()

    openai = stage168.classify_source_authority(
        "https://developers.openai.com/codex/cli",
        query="OpenAI Codex CLI official docs",
        title="CLI - Codex | OpenAI Developers",
        snippet="Codex CLI documentation.",
    )
    deepseek = stage168.classify_source_authority(
        "https://api-docs.deepseek.com/guides/function_calling",
        query="DeepSeek tool calling API docs",
        title="DeepSeek Tool Calls Guide",
        snippet="Function calling documentation.",
    )

    assert openai["source_family"] == "official_docs"
    assert openai["authority_tier"] == "official"
    assert deepseek["source_family"] == "api_docs"
    assert deepseek["authority_tier"] == "official"


def test_package_and_code_sources_are_recognized_but_not_financial_authority() -> None:
    stage168 = _stage168()

    github = stage168.classify_source_authority(
        "https://github.com/openai/codex",
        query="OpenAI Codex source code",
        title="openai/codex",
        snippet="Lightweight coding agent that runs locally.",
    )
    npm = stage168.classify_source_authority(
        "https://www.npmjs.com/package/@openai/codex",
        query="OpenAI Codex npm package",
        title="@openai/codex",
        snippet="Codex CLI npm package.",
    )

    assert github["source_family"] == "code_repository"
    assert npm["source_family"] == "package_registry"
    assert "not_financial_authority" in stage168.evaluate_source_authority(
        "Apple 10-K financial filing",
        [{"source_urls": [github["url"], npm["url"]], "results": []}],
        required_source_family="financial_filing",
    )["missing_authority"]


def test_financial_research_requires_primary_filing_or_ir_source() -> None:
    stage168 = _stage168()

    report = stage168.evaluate_source_authority(
        "Apple 2024 10-K SEC annual report",
        [
            {
                "source_urls": ["https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"],
                "results": [
                    {
                        "title": "Apple Form 10-K",
                        "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                        "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                    }
                ],
            }
        ],
        required_source_family="financial_filing",
        task_type="market_research",
    )

    assert report["schema"] == "holo.stage168.source_authority_report.v1"
    assert report["status"] == "sufficient"
    assert report["primary_source_count"] == 1
    assert report["first_party_source_count"] == 1
    assert not report["missing_authority"]


def test_financial_research_with_only_blog_or_news_is_insufficient() -> None:
    stage168 = _stage168()

    report = stage168.evaluate_source_authority(
        "Apple 2024 10-K financial analysis",
        [
            {
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
        required_source_family="financial_filing",
        task_type="market_research",
    )

    assert report["status"] == "insufficient"
    assert "missing_required_source_family:financial_filing" in report["missing_authority"]
    assert report["primary_source_count"] == 0


def test_attach_source_authority_to_web_observations() -> None:
    stage168 = _stage168()
    rows = [
        {
            "status": "ok",
            "source_urls": ["https://developers.openai.com/codex/cli"],
            "results": [
                {
                    "title": "CLI - Codex | OpenAI Developers",
                    "url": "https://developers.openai.com/codex/cli",
                    "snippet": "Codex CLI official documentation.",
                }
            ],
        }
    ]

    attached = stage168.attach_source_authority_to_observations(rows, query="OpenAI Codex CLI official docs")

    assert attached[0]["source_authority"]["status"] == "sufficient"
    assert attached[0]["source_authority"]["best_sources"][0]["source_family"] == "official_docs"


def test_stage151_web_search_observation_gets_source_authority() -> None:
    def search_fn(query: str) -> dict:
        return {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                }
            ],
        }

    def open_page(url: str) -> dict:
        return {
            "url": url,
            "status": "ok",
            "provider": "mock_page",
            "results": [
                {
                    "title": "Apple Form 10-K",
                    "url": url,
                    "snippet": "Apple Form 10-K annual report for fiscal year 2024.",
                }
            ],
        }

    rows = execute_tool_decision(
        {"user_text": "Apple 2024 10-K SEC annual report", "selected_actions": [{"action_type": "web_search", "query": "Apple 2024 10-K SEC annual report"}]},
        network_enabled=True,
        web_search_fn=search_fn,
        fallback_search_fns=[],
        open_page_fn=open_page,
    )

    assert rows[0]["source_authority"]["status"] == "sufficient"
    assert rows[0]["source_authority"]["best_sources"][0]["source_family"] == "financial_filing"


def test_cli_dry_run_writes_source_authority_audit_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage168_source_authority.html"

    code = cli.main(["run-source-authority-audit", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["schema"] == "holo.stage168.source_authority_audit.v1"


def test_public_artifacts_safe(tmp_path: Path) -> None:
    stage168 = _stage168()
    output = tmp_path / "safe.html"

    stage168.run_source_authority_audit(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
