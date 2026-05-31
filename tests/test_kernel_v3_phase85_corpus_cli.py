import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID


RAW_ONLY_SENTINEL = "RAW_PHASE85_CORPUS_CLI_BODY_ONLY_SECRET"


def test_phase85_cli_indexes_searches_and_reuses_corpus_without_network(tmp_path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    artifact_path = tmp_path / "artifacts.jsonl"
    corpus_path = tmp_path / "corpus.jsonl"
    corpus_index = tmp_path / "corpus.sqlite"
    base_args = [
        "--journal",
        str(journal_path),
        "--index",
        str(index_path),
        "--artifact-log",
        str(artifact_path),
        "--corpus-log",
        str(corpus_path),
        "--corpus-index",
        str(corpus_index),
    ]
    body = "AAPL 2024 10-K revenue from annual report. " + ("x" * 320) + RAW_ONLY_SENTINEL

    indexed = _run_cli(
        *base_args,
        "retrieve",
        "AAPL 2024 revenue",
        "--body",
        body,
        "--uri",
        "https://www.sec.gov/Archives/edgar/data/320193/filing.htm",
        "--title",
        "Apple Form 10-K",
        "--profile",
        FINANCE_FUNDAMENTALS_PROFILE_ID,
        "--index-corpus",
    )
    indexed_payload = json.loads(indexed.stdout)
    document_id = indexed_payload["corpus_documents"][0]["document_id"]

    assert indexed_payload["network_access"] is False
    assert indexed_payload["provider_capabilities"][0]["provider_id"] == "fake_search"
    assert indexed_payload["provider_capabilities"][1]["provider_id"] == "fake_fetch"
    assert indexed_payload["report"]["status"] == "sufficient"
    assert RAW_ONLY_SENTINEL not in indexed.stdout

    search = _run_cli(
        *base_args,
        "corpus",
        "search",
        "AAPL revenue",
        "--profile",
        FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    search_payload = json.loads(search.stdout)
    assert search_payload["result"]["total"] == 1
    assert search_payload["result"]["documents"][0]["document_id"] == document_id
    assert RAW_ONLY_SENTINEL not in search.stdout

    reused = _run_cli(
        *base_args,
        "retrieve",
        "AAPL 2024 revenue",
        "--from-corpus",
        "--profile",
        FINANCE_FUNDAMENTALS_PROFILE_ID,
    )
    reused_payload = json.loads(reused.stdout)
    assert reused_payload["mode"] == "corpus"
    assert reused_payload["network_access"] is False
    assert reused_payload["provider_capabilities"][0]["provider_id"] == "research_corpus"
    assert reused_payload["provider_capabilities"][0]["profile_aware"] is True
    assert reused_payload["report"]["status"] == "sufficient"
    assert RAW_ONLY_SENTINEL not in reused.stdout

    inspected = _run_cli(*base_args, "corpus", "inspect", document_id)
    assert json.loads(inspected.stdout)["document"]["document_id"] == document_id
    assert RAW_ONLY_SENTINEL not in inspected.stdout

    status = _run_cli(*base_args, "corpus", "status")
    status_payload = json.loads(status.stdout)
    assert status_payload["corpus"]["document_count"] == 1
    assert status_payload["corpus"]["primary_usable_count"] == 1
    assert status_payload["corpus"]["profile_counts"][FINANCE_FUNDAMENTALS_PROFILE_ID] == 1
    assert RAW_ONLY_SENTINEL not in status.stdout

    store_inspection = _run_cli(*base_args, "corpus", "inspect-store", "--sample-limit", "1")
    inspection_payload = json.loads(store_inspection.stdout)
    assert inspection_payload["status"] == "ok"
    assert inspection_payload["inspection"]["samples"]["documents"][0]["document_id"] == document_id
    assert inspection_payload["inspection"]["artifact_consistency"]["checked"] is True
    assert inspection_payload["inspection"]["artifact_consistency"]["missing_artifact_blob_count"] == 0
    assert RAW_ONLY_SENTINEL not in store_inspection.stdout

    assert RAW_ONLY_SENTINEL not in corpus_path.read_text(encoding="utf-8")
    assert RAW_ONLY_SENTINEL not in journal_path.read_text(encoding="utf-8")
    assert RAW_ONLY_SENTINEL in artifact_path.read_text(encoding="utf-8")


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "holo-v3", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
