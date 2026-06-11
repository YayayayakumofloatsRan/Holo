import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.bench import build_finance_benchmark_report_from_path, render_finance_benchmark_report


def test_finance_benchmark_report_renders_markdown_summary_and_recommendations(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    _write_results(results)

    report = build_finance_benchmark_report_from_path(results, benchmark_id="finance-smoke")
    markdown = render_finance_benchmark_report(report, output_format="markdown")

    assert report.schema == "holo.kernel_v3.finance_benchmark_report.v1"
    assert report.summary["item_count"] == 3
    assert report.summary["passed_count"] == 1
    assert report.summary["pass_rate"] == 0.3333
    assert len(report.weak_items) == 2
    assert "# Holo Kernel v3 Finance Benchmark Report: finance-smoke" in markdown
    assert "| Pass rate | 33.3% |" in markdown
    assert "fetch_failed" in markdown
    assert "Recommended Next Experiments" in markdown
    assert "gold answers" in markdown


def test_finance_benchmark_report_includes_repeatability_metrics(tmp_path: Path) -> None:
    results = tmp_path / "repeat_results.jsonl"
    rows = [
        _row(
            item_id="Q-repeat",
            status="passed",
            reason="numeric_within_tolerance",
            citation_present=True,
            numeric_passed=True,
            tokens=1000,
            retrieval_runs=1,
            fetches=3,
            repetition=0.0,
            answer_chars=900,
        ),
        _row(
            item_id="Q-repeat",
            status="passed",
            reason="numeric_within_tolerance",
            citation_present=True,
            numeric_passed=True,
            tokens=1100,
            retrieval_runs=1,
            fetches=3,
            repetition=0.0,
            answer_chars=920,
        ),
        _row(
            item_id="Q-other",
            status="failed",
            reason="missing_source",
            citation_present=False,
            numeric_passed=False,
            tokens=1500,
            retrieval_runs=2,
            fetches=4,
            repetition=0.0,
            answer_chars=200,
        ),
    ]
    results.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    report = build_finance_benchmark_report_from_path(results, benchmark_id="finance-repeat")
    markdown = render_finance_benchmark_report(report, output_format="markdown")

    assert report.summary["repeated_item_count"] == 1
    assert report.summary["repeatability_score"] == 1.0
    assert "| Repeated item count | 1 |" in markdown
    assert "| Repeatability score | 100.0% |" in markdown


def test_finance_benchmark_report_renders_html(tmp_path: Path) -> None:
    results = tmp_path / "results.jsonl"
    _write_results(results)

    report = build_finance_benchmark_report_from_path(results, benchmark_id="finance-smoke")
    html = render_finance_benchmark_report(report, output_format="html")

    assert "<!doctype html>" in html
    assert "<h1>Holo Kernel v3 Finance Benchmark Report: finance-smoke</h1>" in html
    assert "<table>" in html
    assert "fetch_failed" in html


def test_finance_benchmark_report_cli_writes_markdown(tmp_path: Path, capsys) -> None:
    results = tmp_path / "results.jsonl"
    output = tmp_path / "report.md"
    _write_results(results)

    code = cli.main(
        [
            "bench",
            "finance-report",
            "--results",
            str(results),
            "--benchmark-id",
            "finance-smoke",
            "--output",
            str(output),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["mode"] == "finance_report"
    text = output.read_text(encoding="utf-8")
    assert "Score Summary" in text
    assert "Weak Items" in text


def test_finance_benchmark_report_cli_stdout_json(tmp_path: Path, capsys) -> None:
    results = tmp_path / "results.jsonl"
    _write_results(results)

    code = cli.main(
        [
            "bench",
            "finance-report",
            "--results",
            str(results),
            "--format",
            "json",
            "--max-weak-items",
            "1",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "holo.kernel_v3.finance_benchmark_report.v1"
    assert len(payload["weak_items"]) == 1


def _write_results(path: Path) -> None:
    rows = [
        _row(
            item_id="Q1",
            status="passed",
            reason="numeric_within_tolerance",
            citation_present=True,
            numeric_passed=True,
            tokens=1000,
            retrieval_runs=2,
            fetches=4,
            repetition=0.0,
            answer_chars=900,
        ),
        _row(
            item_id="Q2",
            status="failed",
            reason="numeric_outside_tolerance",
            citation_present=False,
            numeric_passed=False,
            tokens=3200,
            retrieval_runs=5,
            fetches=12,
            repetition=0.45,
            answer_chars=180,
            failure_mode="fetch_failed",
        ),
        _row(
            item_id="Q3",
            status="failed",
            reason="gold_text_not_matched",
            citation_present=True,
            numeric_passed=None,
            tokens=2400,
            retrieval_runs=4,
            fetches=9,
            repetition=0.2,
            answer_chars=500,
            failure_mode="missing_citation_refs",
        ),
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _row(
    *,
    item_id: str,
    status: str,
    reason: str,
    citation_present: bool,
    numeric_passed: bool | None,
    tokens: int,
    retrieval_runs: int,
    fetches: int,
    repetition: float,
    answer_chars: int,
    failure_mode: str | None = None,
) -> dict:
    numeric = {"scored": numeric_passed is not None, "passed": numeric_passed}
    return {
        "item_id": item_id,
        "status": status,
        "question": f"{item_id} finance question",
        "answer": "Benchmark answer text.",
        "scorecard": {
            "status": status,
            "scored": True,
            "reason": reason,
            "answer_present": True,
            "citation_present": citation_present,
            "numeric": numeric,
        },
        "trace_metrics": {
            "total_tokens": tokens,
            "retrieval_run_count": retrieval_runs,
            "fetch_attempt_count": fetches,
            "downloaded_bytes": 10_000,
            "query_repetition_rate": repetition,
            "final_answer_chars": answer_chars,
            "latest_failure_mode": failure_mode,
        },
        "metadata": {"category": "fact_extraction", "source": "finance_agent_benchmark"},
    }
