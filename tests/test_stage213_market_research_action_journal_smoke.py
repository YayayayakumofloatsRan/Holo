from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning


def _stage213():
    import importlib
    import importlib.util

    assert importlib.util.find_spec("holo_host.market_research_action_journal_smoke") is not None
    return importlib.import_module("holo_host.market_research_action_journal_smoke")


def test_stage213_market_research_smoke_requires_crawl_and_action_journal(tmp_path: Path) -> None:
    stage213 = _stage213()

    bundle = stage213.run_market_research_action_journal_smoke(
        output=tmp_path / "stage213_market_research_action_journal.html",
        dry_run=True,
    )
    result = bundle["results"][0]
    crawler = result["stage186_live_crawler_search"]
    journal = result["stage212_action_journal"]
    rendered = result["rendered_action_journal"]

    assert bundle["schema"] == "holo.stage213.market_research_action_journal_smoke.v1"
    assert bundle["status"] == "passed"
    assert result["status"] == "passed"
    assert crawler["status"] == "sufficient"
    assert crawler["query_count"] >= 2
    assert result["scorecard"]["checks"]["authority_source_promoted"]["passed"] is True
    assert result["scorecard"]["checks"]["weak_source_not_promoted"]["passed"] is True
    assert journal["entry_count"] == 1
    assert "[action:1] web_search status=sufficient" in rendered
    assert "[crawl:query]" in rendered
    assert "[crawl:open]" in rendered
    assert "[feedback]" in rendered
    assert any(url.startswith("https://www.sec.gov/") for url in result["market_research_report"]["source_urls"])
    assert "https://example.com/ai-capex-hot-take" not in crawler["source_urls"]
    ok, paths = assert_no_private_reasoning(result)
    assert ok, paths


def test_stage213_market_research_report_is_grounded_and_cli_writes_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage213_market_research_action_journal.html"

    code = cli.main(
        [
            "run-market-research-action-journal-smoke",
            "--output",
            str(output),
            "--dry-run",
        ]
    )

    assert code == 0
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    row = payload["results"][0]
    assert payload["schema"] == "holo.stage213.market_research_action_journal_smoke.v1"
    assert payload["status"] == "passed"
    assert row["market_research_report"]["status"] == "grounded"
    assert row["market_research_report"]["unsupported_claim_count"] == 0
    assert "stage213-ai-capex-market-research" in output.with_suffix(".jsonl").read_text(encoding="utf-8")
