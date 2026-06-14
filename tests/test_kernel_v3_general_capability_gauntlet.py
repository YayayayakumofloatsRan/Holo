import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.bench.general import (
    GENERAL_CAPABILITY_GAUNTLET_SCHEMA,
    GeneralCapabilityResult,
    default_general_capability_cases,
    run_general_capability_gauntlet,
    summarize_general_capability_results,
    write_general_capability_gauntlet_outputs,
)


def test_general_capability_gauntlet_covers_kernel_v3_core_surfaces() -> None:
    report = run_general_capability_gauntlet()

    assert report["schema"] == GENERAL_CAPABILITY_GAUNTLET_SCHEMA
    assert report["status"] == "passed"
    categories = {case["category"] for case in report["cases"]}
    assert {
        "direct_chat",
        "roleplay_writing",
        "technical_research",
        "academic_research",
        "workspace_read",
        "memory",
        "system",
        "math_compute",
        "resident",
    }.issubset(categories)
    assert report["summary"]["pass_rate"] == 1.0


def test_general_capability_gauntlet_preserves_expected_tool_surfaces() -> None:
    report = run_general_capability_gauntlet()
    by_id = {case["case_id"]: case for case in report["cases"]}

    assert by_id["general-direct-chat"]["observed_tools"] == []
    assert by_id["general-technical-docs-research"]["observed_tools"] == ["retrieval.run"]
    assert by_id["general-academic-frontier"]["observed_tools"] == ["retrieval.run"]
    assert by_id["general-workspace-read"]["observed_tools"] == ["workspace.search,file.read"]
    assert by_id["general-memory-recall"]["observed_tools"] == ["memory.recall"]
    assert by_id["general-system-time"]["observed_tools"] == ["system.time"]
    assert by_id["general-math-compute"]["observed_tools"] == ["calculator.compute"]


def test_general_capability_summary_accumulates_cache_usage() -> None:
    result = GeneralCapabilityResult(
        case_id="cache-case",
        category="direct_chat",
        status="passed",
        prompt="hi",
        expected_mode="semantic_answer",
        selected_mode="semantic_answer",
        expected_tools=[],
        observed_tools=[],
        missing_tools=[],
        forbidden_tools_seen=[],
        expected_domains=["conversation"],
        observed_domains=["conversation"],
        score=1.0,
        checks={"mode": True},
        usage={
            "total_tokens": 120,
            "prompt_cache_hit_tokens": 80,
            "prompt_cache_miss_tokens": 20,
        },
    )

    summary = summarize_general_capability_results([result], started_at_ms=1)

    assert summary["total_tokens"] == 120
    assert summary["prompt_cache_hit_tokens"] == 80
    assert summary["prompt_cache_miss_tokens"] == 20
    assert summary["prompt_cache_hit_ratio"] == 0.8


def test_general_capability_outputs_write_report_summary_and_jsonl(tmp_path: Path) -> None:
    report = run_general_capability_gauntlet(cases=default_general_capability_cases()[:2])

    outputs = write_general_capability_gauntlet_outputs(
        report,
        output_path=tmp_path / "general.json",
        summary_path=tmp_path / "general.summary.json",
        jsonl_path=tmp_path / "general.jsonl",
    )

    assert set(outputs) == {"output", "summary_output", "jsonl_output"}
    payload = json.loads((tmp_path / "general.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "general.summary.json").read_text(encoding="utf-8"))
    rows = [json.loads(line) for line in (tmp_path / "general.jsonl").read_text(encoding="utf-8").splitlines()]
    assert payload["schema"] == GENERAL_CAPABILITY_GAUNTLET_SCHEMA
    assert summary["case_count"] == 2
    assert len(rows) == 2


def test_cli_bench_general_writes_default_contract_gauntlet_outputs(tmp_path: Path) -> None:
    output = tmp_path / "general.json"
    summary = tmp_path / "general.summary.json"
    jsonl = tmp_path / "general.jsonl"

    code = cli.main(
        [
            "bench",
            "general",
            "--output",
            str(output),
            "--summary-output",
            str(summary),
            "--jsonl-output",
            str(jsonl),
        ]
    )

    assert code == 0
    assert output.exists()
    assert summary.exists()
    assert jsonl.exists()
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "passed"
