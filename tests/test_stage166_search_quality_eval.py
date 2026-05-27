from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli


def _stage166():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.stage166_search_quality_eval") is not None
    return importlib.import_module("holo_host.stage166_search_quality_eval")


def test_dry_run_creates_search_quality_artifacts(tmp_path: Path) -> None:
    stage166 = _stage166()
    output = tmp_path / "search_quality.html"

    report = stage166.run_search_quality_eval(output=output, dry_run=True)

    assert report["schema"] == "holo.stage166.search_quality_eval.v1"
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["schema"] == report["schema"]


def test_eval_includes_real_research_query_categories() -> None:
    stage166 = _stage166()

    report = stage166.run_search_quality_eval(dry_run=True)
    categories = {row["category_id"] for row in report["query_results"]}

    assert {
        "official_docs",
        "api_docs",
        "current_news",
        "financial_filings",
        "ambiguous_entity",
        "failure_case",
    }.issubset(categories)


def test_supported_official_docs_answer_requires_verified_citations() -> None:
    stage166 = _stage166()
    fixture = stage166.default_search_quality_fixtures()[0]

    result = stage166.evaluate_search_quality_fixture(fixture)

    assert result["status"] == "passed"
    assert result["metrics"]["source_support_score"] == 1.0
    assert result["metrics"]["citation_sufficiency_score"] == 1.0
    assert result["metrics"]["unsupported_claim_rate"] == 0.0
    assert result["citation_count"] >= 2


def test_unsupported_current_claim_is_counted_as_failure() -> None:
    stage166 = _stage166()

    result = stage166.evaluate_search_quality_fixture(
        {
            "fixture_id": "bad-current-claim",
            "category_id": "current_news",
            "query": "latest DeepSeek tool calling news",
            "visible_answer": "I searched the latest official news today and confirmed it.",
            "time_observation": {},
            "web_observation_ledger": [],
            "expected_terms": ["DeepSeek"],
        }
    )

    assert result["status"] == "failed"
    assert result["metrics"]["unsupported_claim_rate"] == 1.0
    assert "current_or_web_claim_without_supported_sources" in result["failure_reasons"]


def test_conflicted_sources_are_not_treated_as_supported() -> None:
    stage166 = _stage166()
    fixture = stage166.default_search_quality_fixtures()[0]
    row = fixture["web_observation_ledger"][0]
    row["source_synthesis"]["status"] = "conflicted"
    row["source_synthesis"]["risk_flags"] = ["source_conflict"]
    fixture["visible_answer"] = "I found source-page evidence, but it contains a conflict, so I cannot state it as settled."

    result = stage166.evaluate_search_quality_fixture(fixture)

    assert result["metrics"]["conflict_rate"] == 1.0
    assert result["metrics"]["source_support_score"] < 1.0
    assert result["status"] == "failed"


def test_css_noise_in_visible_answer_is_penalized() -> None:
    stage166 = _stage166()
    fixture = stage166.default_search_quality_fixtures()[0]
    fixture["visible_answer"] += "\n@layer theme, base; .page-copy-action{display:inline}"

    result = stage166.evaluate_search_quality_fixture(fixture)

    assert result["metrics"]["css_noise_rate"] == 1.0
    assert "css_or_page_chrome_leaked" in result["failure_reasons"]


def test_failure_case_passes_only_when_answer_is_honest_about_no_evidence() -> None:
    stage166 = _stage166()
    failure_fixture = next(row for row in stage166.default_search_quality_fixtures() if row["category_id"] == "failure_case")

    result = stage166.evaluate_search_quality_fixture(failure_fixture)

    assert result["status"] == "passed"
    assert result["metrics"]["unsupported_claim_rate"] == 0.0
    assert "no supported page evidence" in failure_fixture["visible_answer"].lower()


def test_full_stack_beats_raw_result_baseline_on_citation_sufficiency() -> None:
    stage166 = _stage166()

    report = stage166.run_search_quality_eval(dry_run=True)

    assert report["summary"]["citation_sufficiency_score"] > report["baselines"]["raw_result_baseline"]["citation_sufficiency_score"]
    assert report["summary"]["unsupported_claim_rate"] < report["baselines"]["raw_result_baseline"]["unsupported_claim_rate"]


def test_cli_dry_run_writes_search_quality_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage166_search_quality.html"

    code = cli.main(["run-search-quality-eval", "--output", str(output), "--dry-run"])

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()


def test_artifacts_are_public_release_safe(tmp_path: Path) -> None:
    stage166 = _stage166()
    output = tmp_path / "safe.html"

    stage166.run_search_quality_eval(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ".holo_runtime" not in blob
    assert "DEEPSEEK_API_KEY" not in blob
    assert "reasoning_content" not in blob
