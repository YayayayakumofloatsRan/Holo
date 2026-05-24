from __future__ import annotations

import json

from holo_host import cli
from holo_host.tool_benchmark import run_tool_benchmark


def test_tool_benchmark_reports_precision_recall_and_ungrounded_claims() -> None:
    report = run_tool_benchmark()

    assert report["schema"] == "holo.tool_benchmark.v1"
    assert report["case_count"] >= 7
    assert 0.0 <= report["metrics"]["tool_precision"] <= 1.0
    assert 0.0 <= report["metrics"]["tool_recall"] <= 1.0
    assert "ungrounded_claim_count" in report["metrics"]
    assert any(case["name"] == "workspace_read" for case in report["cases"])
    assert any(case["name"] == "no_tool_casual" for case in report["cases"])


def test_stage139_tool_benchmark_cli_reports_metrics(capsys) -> None:
    result = cli.main(["stage139-tool-benchmark"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "holo.tool_benchmark.v1"
    assert payload["metrics"]["tool_recall"] >= 0.0
