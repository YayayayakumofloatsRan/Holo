import json
import os
from pathlib import Path

import pytest

from kernel_v3 import cli
from kernel_v3.journal import JournalStore
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID


def test_phase101_deepseek_live_finance_retrieval_uses_sec_structured_sources(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    if os.environ.get("HOLO_V3_LIVE_FINANCE") != "1":
        pytest.skip("set HOLO_V3_LIVE_FINANCE=1 for live finance retrieval smoke")
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live model smoke")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live DeepSeek smoke")

    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL", "1")
    monkeypatch.setenv("HOLO_V3_LIVE_FETCH_ALLOWED_HOSTS", "data.sec.gov,www.sec.gov,sec.gov")
    monkeypatch.setenv("HOLO_V3_LIVE_RETRIEVAL_MAX_BYTES", "4000000")
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    assert (
        cli.main(
            [
                "--journal",
                str(journal_path),
                "--index",
                str(index_path),
                "agent",
                "Research AAPL CIK0000320193 SEC submissions and companyfacts from official SEC sources. Answer in Chinese with citations.",
                "--mode",
                "retrieval",
                "--online",
                "--research-profile",
                FINANCE_FUNDAMENTALS_PROFILE_ID,
                "--research-depth",
                "balanced",
                "--live-retrieval",
                "--live-max-network-fetches",
                "8",
                "--profile",
                "balanced",
                "--thinking",
                "enabled",
                "--reasoning-effort",
                "high",
                "--temperature",
                "0.2",
                "--max-output-tokens",
                "provider",
                "--response-language",
                "zh",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    journal = JournalStore(journal_path, index_path=index_path)
    raw_journal = journal_path.read_text(encoding="utf-8")

    assert payload["status"] == "completed", payload
    assert payload["final_answer"]["citation_refs"]
    reports = journal.records(task_id=payload["task_id"], kind="retrieval_report")
    assert reports and reports[-1].data["status"] == "sufficient"
    fetched = [
        record.data
        for record in journal.records(task_id=payload["task_id"], kind="retrieval_fetch_attempt")
    ]
    assert any("sec.gov" in str(item.get("uri", "")) for item in fetched)
    assert journal.records(task_id=payload["task_id"], kind="processor_request")
    assert journal.records(task_id=payload["task_id"], kind="processor_result")
    assert os.environ["DEEPSEEK_API_KEY"] not in raw_journal
    assert "DEEPSEEK_API_KEY" not in raw_journal
