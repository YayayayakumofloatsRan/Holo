import json
from pathlib import Path
from types import SimpleNamespace

from kernel_v3 import cli
from kernel_v3.bench.general import (
    GENERAL_CAPABILITY_GAUNTLET_SCHEMA,
    GeneralCapabilityResult,
    default_general_capability_cases,
    evaluate_general_capability_case,
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


def test_general_capability_gauntlet_can_filter_cases_and_categories() -> None:
    by_case = run_general_capability_gauntlet(case_ids=["general-direct-chat"])
    by_category = run_general_capability_gauntlet(categories=["system", "math_compute"])

    assert [case["case_id"] for case in by_case["cases"]] == ["general-direct-chat"]
    assert {case["category"] for case in by_category["cases"]} == {"system", "math_compute"}
    assert by_category["summary"]["case_count"] == 2


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


def test_general_capability_live_pending_question_counts_as_output() -> None:
    case = [item for item in default_general_capability_cases() if item.case_id == "general-resident-reminder"][0]
    live_result = SimpleNamespace(
        task_id="task-resident",
        run_id="run-resident",
        answer=None,
        final_answer=None,
        pending_question={"question": "When should I remind you?"},
    )

    report = run_general_capability_gauntlet(cases=[case], runtime=None)
    direct_result = report["cases"][0]
    assert direct_result["status"] == "passed"

    live_scored = evaluate_general_capability_case(case, live_result=live_result)

    assert live_scored.status == "passed"
    assert live_scored.pending_question_present is True
    assert live_scored.checks["live_output_present"] is True


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
