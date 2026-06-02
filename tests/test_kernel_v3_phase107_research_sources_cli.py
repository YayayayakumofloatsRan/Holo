import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID


def test_phase107_sources_cli_lists_curated_finance_sources(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "sources",
                "list",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--authority",
                "primary",
                "--limit",
                "50",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert payload["returned"] > 0
    assert payload["facets"]["authority_levels"] == {"primary": payload["total"]}
    source_ids = {source["source_id"] for source in payload["sources"]}
    assert "finance-sec-edgar-filings" in source_ids
    assert "finance-us-official-statistics" in source_ids
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase107_sources_cli_filters_by_family_and_outputs_safe_seeds(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "sources",
                "seeds",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--family",
                "treasury_data",
                "--limit",
                "10",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["returned"] >= 2
    assert payload["usage"]["purpose"].startswith("seed or refresh")
    assert {
        seed["url"]
        for seed in payload["seeds"]
    } >= {
        "https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics",
        "https://fiscaldata.treasury.gov/",
    }
    assert all(seed["authority_level"] == "primary" for seed in payload["seeds"])
    assert all(seed["url"].startswith("https://") for seed in payload["seeds"])
    assert "token" not in json.dumps(payload, ensure_ascii=False).lower()
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase107_sources_cli_reports_source_directory_facets(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "sources",
                "families",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["facets"]["source_families"]["regulatory_filing"] >= 1
    assert payload["facets"]["source_families"]["reputable_news"] >= 1
    assert payload["facets"]["authority_levels"]["primary"] > payload["facets"]["authority_levels"]["secondary"]
    assert JournalStore(journal_path, index_path=index_path).records() == []


def test_phase107_sources_cli_plans_finance_research_against_site_index(tmp_path: Path, capsys) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "sources",
                "plan",
                "NVIDIA 10-K fundamentals revenue margin SEC filing",
                "--profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--limit",
                "5",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["status"] == "ok"
    assert payload["strategy"]["primary"].startswith("use ranked trusted sites")
    assert payload["returned"] == 5
    assert payload["query_hash"]
    assert "NVIDIA" not in json.dumps(payload, ensure_ascii=False)
    source_ids = [source["source_id"] for source in payload["sources"]]
    assert source_ids[0] in {
        "finance-sec-edgar-filings",
        "finance-sec-edgar-archives",
        "finance-sec-companyfacts",
        "finance-sec-company-tickers",
    }
    assert "finance-japan-edinet-filings" not in source_ids
    assert any(source["authority_level"] == "primary" for source in payload["sources"])
    assert any(source["seed_urls"] for source in payload["sources"])
    assert JournalStore(journal_path, index_path=index_path).records() == []
