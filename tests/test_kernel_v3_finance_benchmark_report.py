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


def test_finance_benchmark_report_includes_processor_breakdown(tmp_path: Path) -> None:
    results = tmp_path / "processor_results.jsonl"
    rows = [
        _row(
            item_id="Q-proc-1",
            status="passed",
            reason="numeric_within_tolerance",
            citation_present=True,
            numeric_passed=True,
            tokens=1000,
            retrieval_runs=1,
            fetches=2,
            repetition=0.0,
            answer_chars=800,
        ),
        _row(
            item_id="Q-proc-2",
            status="failed",
            reason="processor_failed",
            citation_present=False,
            numeric_passed=False,
            tokens=1400,
            retrieval_runs=2,
            fetches=3,
            repetition=0.1,
            answer_chars=250,
            failure_mode="processor_failed",
        ),
    ]
    rows[0]["trace_metrics"].update(
        {
            "processor_call_count": 2,
            "processor_prompt_cache_hit_tokens": 40,
            "processor_prompt_cache_miss_tokens": 10,
            "context_record_count": 2,
            "context_dynamic_state_present_count": 1,
            "context_toolchain_state_present_count": 1,
            "context_toolchain_state_empty_count": 1,
            "context_finance_working_state_present_count": 1,
            "context_finance_working_state_empty_count": 1,
            "processor_usage_by_task_type": {
                "task.compile": {
                    "call_count": 1,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 10,
                    "total_tokens": 100,
                },
                "synthesizer.answer": {
                    "call_count": 1,
                    "prompt_cache_hit_tokens": 35,
                    "prompt_cache_miss_tokens": 5,
                    "total_tokens": 90,
                },
            },
            "processor_usage_by_provider_model": {"deepseek/deepseek-chat": {"call_count": 2}},
            "processor_status_counts": {"ok": 2},
            "processor_error_counts": {},
            "agent_loop_stage_counts": {
                "Intake": 1,
                "Plan": 2,
                "Policy": 1,
                "Tools": 2,
                "Search": 1,
                "Evidence": 3,
                "Verify": 2,
                "Answer": 1,
            },
            "agent_loop_stage_coverage_rate": 1.0,
            "agent_loop_terminal": True,
            "agent_loop_tool_stage_present": True,
            "agent_loop_search_stage_present": True,
            "agent_loop_verify_stage_present": True,
            "agent_loop_delta_count": 13,
            "agent_loop_transition_count": 8,
            "toolchain_depth": 3,
            "retrieval_calculator_verifier_chain_present": True,
            "tool_observation_error_rate": 0.0,
            "tool_action_repetition_rate": 0.25,
            "tool_action_payload_repetition_rate": 0.2,
            "tool_action_payload_repeated_group_count": 1,
            "tool_action_payload_max_repeat_count": 2,
            "tool_action_payload_repeated_tool_counts": {"calculator.compute": 1},
            "tool_observation_source_counts": {
                "tool:retrieval.run": 1,
                "tool:calculator.compute": 2,
                "tool:finance.verify_numeric": 2,
            },
            "tool_observation_count": 5,
            "tool_observation_diagnostics_count": 2,
            "tool_observation_repair_guidance_count": 1,
            "tool_observation_diagnostic_issue_code_counts": {"unsupported_answer_number": 1},
            "post_final_record_count": 0,
            "post_final_record_kind_counts": {},
            "finance_verify_numeric_tool_call_count": 2,
            "finance_verify_numeric_tool_error_count": 0,
            "task_compile_retry_count": 1,
            "task_compile_retry_success_count": 1,
            "synthesizer_json_repair_attempt_count": 1,
            "synthesizer_json_repair_success_count": 1,
            "structured_repair_attempt_count": 2,
            "structured_repair_success_count": 2,
            "formula_trace_support_count": 2,
            "formula_trace_fact_linked_count": 2,
            "formula_trace_citation_linked_count": 1,
            "formula_trace_evidence_linked_count": 2,
        }
    )
    rows[1]["trace_metrics"].update(
        {
            "processor_call_count": 2,
            "processor_error_count": 1,
            "processor_prompt_cache_hit_tokens": 10,
            "processor_prompt_cache_miss_tokens": 40,
            "context_record_count": 1,
            "context_dynamic_state_present_count": 0,
            "context_toolchain_state_present_count": 0,
            "context_toolchain_state_empty_count": 1,
            "context_toolchain_observation_diagnostics_present_count": 1,
            "context_finance_working_state_present_count": 0,
            "context_finance_working_state_empty_count": 1,
            "processor_usage_by_task_type": {
                "task.compile": {
                    "call_count": 1,
                    "prompt_cache_hit_tokens": 10,
                    "prompt_cache_miss_tokens": 20,
                    "total_tokens": 70,
                },
                "finance.slot_bind": {
                    "call_count": 1,
                    "prompt_cache_hit_tokens": 0,
                    "prompt_cache_miss_tokens": 40,
                    "total_tokens": 80,
                },
            },
            "processor_usage_by_provider_model": {"deepseek/deepseek-chat": {"call_count": 2}},
            "processor_status_counts": {"ok": 1, "failed": 1},
            "processor_error_counts": {"json_invalid": 1},
            "agent_loop_stage_counts": {
                "Intake": 1,
                "Plan": 2,
                "Policy": 1,
                "Tools": 1,
                "Search": 0,
                "Evidence": 1,
                "Verify": 0,
                "Answer": 1,
            },
            "agent_loop_stage_coverage_rate": 0.625,
            "agent_loop_terminal": True,
            "agent_loop_tool_stage_present": True,
            "agent_loop_search_stage_present": False,
            "agent_loop_verify_stage_present": False,
            "agent_loop_delta_count": 7,
            "agent_loop_transition_count": 5,
            "toolchain_depth": 1,
            "retrieval_calculator_verifier_chain_present": False,
            "tool_observation_error_rate": 0.5,
            "tool_action_repetition_rate": 0.0,
            "tool_action_payload_repetition_rate": 0.0,
            "tool_action_payload_repeated_group_count": 0,
            "tool_action_payload_max_repeat_count": 0,
            "tool_action_payload_repeated_tool_counts": {},
            "tool_observation_source_counts": {
                "tool:retrieval.run": 1,
                "tool:workspace.search": 1,
            },
            "tool_observation_count": 2,
            "tool_observation_diagnostics_count": 1,
            "tool_observation_repair_guidance_count": 0,
            "tool_observation_diagnostic_issue_code_counts": {"network_failed": 1},
            "post_final_record_count": 2,
            "post_final_record_kind_counts": {"memory_proposal": 1, "processor_result": 1},
            "finance_verify_numeric_tool_call_count": 1,
            "finance_verify_numeric_tool_error_count": 1,
            "finance_slot_bind_repair_attempt_count": 1,
            "finance_slot_bind_repair_success_count": 0,
            "structured_repair_attempt_count": 1,
            "structured_repair_success_count": 0,
            "formula_trace_support_count": 1,
            "formula_trace_fact_linked_count": 0,
            "formula_trace_citation_linked_count": 0,
            "formula_trace_evidence_linked_count": 0,
            "formula_trace_fact_link_rate": 0.0,
            "formula_trace_citation_link_rate": 0.0,
            "formula_trace_evidence_link_rate": 0.0,
        }
    )
    results.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    report = build_finance_benchmark_report_from_path(results, benchmark_id="finance-processors")
    markdown = render_finance_benchmark_report(report, output_format="markdown")

    assert report.summary["processor_call_count"] == 4
    assert report.summary["processor_error_count"] == 1
    assert report.summary["processor_prompt_cache_hit_tokens"] == 50
    assert report.summary["processor_prompt_cache_miss_tokens"] == 50
    assert report.summary["processor_prompt_cache_hit_ratio"] == 0.5
    assert report.summary["context_record_count"] == 3
    assert report.summary["average_context_record_count"] == 1.5
    assert report.summary["context_dynamic_state_present_count"] == 1
    assert report.summary["context_dynamic_state_present_rate"] == 0.333333
    assert report.summary["context_dynamic_state_item_rate"] == 0.5
    assert report.summary["context_toolchain_state_present_count"] == 1
    assert report.summary["context_toolchain_state_empty_count"] == 2
    assert report.summary["context_toolchain_state_prompt_eligible_rate"] == 0.333333
    assert report.summary["context_toolchain_observation_diagnostics_present_count"] == 1
    assert report.summary["context_toolchain_observation_diagnostics_prompt_eligible_rate"] == 0.333333
    assert report.summary["context_finance_working_state_present_count"] == 1
    assert report.summary["context_finance_working_state_empty_count"] == 2
    assert report.summary["context_finance_working_state_prompt_eligible_rate"] == 0.333333
    assert report.summary["processor_task_type_counts"] == {
        "finance.slot_bind": 1,
        "synthesizer.answer": 1,
        "task.compile": 2,
    }
    assert report.summary["processor_cache_by_task_type"]["task.compile"]["prompt_cache_hit_tokens"] == 50
    assert report.summary["processor_cache_by_task_type"]["task.compile"]["prompt_cache_miss_tokens"] == 30
    assert report.summary["processor_cache_by_task_type"]["finance.slot_bind"]["prompt_cache_hit_ratio"] == 0.0
    assert report.summary["processor_provider_model_counts"] == {"deepseek/deepseek-chat": 4}
    assert report.summary["processor_status_counts"] == {"failed": 1, "ok": 3}
    assert report.summary["processor_error_counts"] == {"json_invalid": 1}
    assert report.summary["average_agent_loop_stage_coverage_rate"] == 0.8125
    assert report.summary["agent_loop_terminal_rate"] == 1.0
    assert report.summary["agent_loop_tool_stage_rate"] == 1.0
    assert report.summary["agent_loop_search_stage_rate"] == 0.5
    assert report.summary["agent_loop_verify_stage_rate"] == 0.5
    assert report.summary["average_agent_loop_delta_count"] == 10.0
    assert report.summary["average_agent_loop_transition_count"] == 6.5
    assert report.summary["agent_loop_stage_counts"]["Plan"] == 4
    assert report.summary["agent_loop_stage_counts"]["Verify"] == 2
    assert report.summary["average_toolchain_depth"] == 2.0
    assert report.summary["retrieval_calculator_verifier_chain_rate"] == 0.5
    assert report.summary["average_tool_observation_error_rate"] == 0.25
    assert report.summary["average_tool_action_repetition_rate"] == 0.125
    assert report.summary["average_tool_action_payload_repetition_rate"] == 0.1
    assert report.summary["tool_action_payload_repeated_group_count"] == 1
    assert report.summary["max_tool_action_payload_repeat_count"] == 2
    assert report.summary["tool_action_payload_repeated_tool_counts"] == {"calculator.compute": 1}
    assert report.summary["post_final_clean_rate"] == 0.5
    assert report.summary["average_post_final_record_count"] == 1.0
    assert report.summary["tool_observation_source_counts"]["tool:retrieval.run"] == 2
    assert report.summary["tool_observation_source_counts"]["tool:calculator.compute"] == 2
    assert report.summary["tool_observation_source_counts"]["tool:finance.verify_numeric"] == 2
    assert report.summary["tool_observation_diagnostics_count"] == 3
    assert report.summary["tool_observation_repair_guidance_count"] == 1
    assert report.summary["tool_observation_diagnostics_rate"] == 0.428571
    assert report.summary["tool_observation_repair_guidance_rate"] == 0.142857
    assert report.summary["tool_observation_diagnostic_issue_code_counts"] == {
        "network_failed": 1,
        "unsupported_answer_number": 1,
    }
    assert report.summary["post_final_record_kind_counts"] == {"memory_proposal": 1, "processor_result": 1}
    assert report.summary["finance_verify_numeric_tool_call_count"] == 3
    assert report.summary["finance_verify_numeric_tool_error_count"] == 1
    assert report.summary["finance_verify_numeric_tool_used_rate"] == 1.0
    assert report.summary["finance_verify_numeric_tool_error_rate"] == 0.333333
    assert report.summary["task_compile_retry_count"] == 1
    assert report.summary["task_compile_retry_success_count"] == 1
    assert report.summary["finance_slot_bind_repair_attempt_count"] == 1
    assert report.summary["finance_slot_bind_repair_success_count"] == 0
    assert report.summary["synthesizer_json_repair_attempt_count"] == 1
    assert report.summary["synthesizer_json_repair_success_count"] == 1
    assert report.summary["structured_repair_attempt_count"] == 3
    assert report.summary["structured_repair_success_count"] == 2
    assert report.summary["structured_repair_success_rate"] == 0.666667
    assert report.summary["average_formula_trace_support_count"] == 1.5
    assert report.summary["formula_trace_fact_link_rate"] == 0.666667
    assert report.summary["formula_trace_citation_link_rate"] == 0.333333
    assert report.summary["formula_trace_evidence_link_rate"] == 0.666667
    assert "| Processor cache hit ratio | 50.0% |" in markdown
    assert "| Context records | 3 |" in markdown
    assert "| Context dynamic-state item rate | 50.0% |" in markdown
    assert "| Toolchain state prompt-eligible rate | 33.3% |" in markdown
    assert "| Finance working-state prompt-eligible rate | 33.3% |" in markdown
    assert "| Agent loop terminal rate | 100.0% |" in markdown
    assert "| Avg agent-loop stage coverage | 81.2% |" in markdown
    assert "| Agent loop search-stage rate | 50.0% |" in markdown
    assert "| Agent loop verify-stage rate | 50.0% |" in markdown
    assert "| Avg agent-loop deltas | 10 |" in markdown
    assert "| Avg agent-loop transitions | 6.5 |" in markdown
    assert "| Avg toolchain depth | 2 |" in markdown
    assert "| Retrieval-calculator-verifier chain rate | 50.0% |" in markdown
    assert "| Avg tool observation error rate | 25.0% |" in markdown
    assert "| Tool observation diagnostics rate | 42.9% |" in markdown
    assert "| Tool observation repair-guidance rate | 14.3% |" in markdown
    assert "| Avg tool action repetition rate | 12.5% |" in markdown
    assert "| Avg tool payload repetition rate | 10.0% |" in markdown
    assert "| Repeated payload groups | 1 |" in markdown
    assert "| Max payload repeat count | 2 |" in markdown
    assert "| Post-final clean rate | 50.0% |" in markdown
    assert "## Tool Payload Repetition" in markdown
    assert "| calculator.compute | 1 |" in markdown
    assert "| Avg post-final records | 1 |" in markdown
    assert "| Finance verifier tool calls | 3 |" in markdown
    assert "| Finance verifier tool used rate | 100.0% |" in markdown
    assert "| Finance verifier tool error rate | 33.3% |" in markdown
    assert "| Structured repair success rate | 66.7% |" in markdown
    assert "| Task compile retries | 1 |" in markdown
    assert "| Finance slot-bind repair attempts | 1 |" in markdown
    assert "| Synthesizer JSON repair attempts | 1 |" in markdown
    assert "| Formula trace fact-link rate | 66.7% |" in markdown
    assert "| Formula trace citation-link rate | 33.3% |" in markdown
    assert "## Processor Task Types" in markdown
    assert "| task.compile | 2 |" in markdown
    assert "## Processor Cache By Task Type" in markdown
    assert "| finance.slot_bind | 1 | 0 | 40 | 0.0% | 80 |" in markdown
    assert "Trace link" in markdown
    assert "Trace cite" in markdown
    assert "Internal support" in markdown
    assert "## Failure Layers" in markdown
    assert "| processor_failure | 1 |" in markdown
    assert "| Q-proc-2 | failed | processor_failure | processor_failed | processor_failed | no | - | - | 0.0% | 0.0% | 0.0%" in markdown
    assert "## Processor Errors" in markdown
    assert "| json_invalid | 1 |" in markdown
    assert "## Context Hygiene" in markdown
    assert "| Toolchain state empty | 2 |" in markdown
    assert "| Toolchain observation diagnostics prompt-eligible rate | 33.3% |" in markdown
    assert "| Finance working-state present | 1 |" in markdown
    assert "## Agent Loop Stage Counts" in markdown
    assert "| Plan | 4 |" in markdown
    assert "| Verify | 2 |" in markdown
    assert "## Tool Observation Sources" in markdown
    assert "| tool:calculator.compute | 2 |" in markdown
    assert "| tool:finance.verify_numeric | 2 |" in markdown
    assert "## Tool Observation Diagnostic Issue Codes" in markdown
    assert "| network_failed | 1 |" in markdown
    assert "| unsupported_answer_number | 1 |" in markdown
    assert "## Post-Final Record Kinds" in markdown
    assert "| memory_proposal | 1 |" in markdown
    assert "Inspect processor error cluster `json_invalid`" in markdown
    assert "Inspect structured-output repair prompts" in markdown
    assert "Inspect FormulaTrace input_fact_ids versus finance_fact_ledger ids" in markdown
    assert "Improve FormulaTrace citation provenance" in markdown
    assert "Improve FormulaTrace evidence provenance" in markdown


def test_finance_benchmark_report_flags_strict_failures_with_internal_verifier_support(tmp_path: Path) -> None:
    results = tmp_path / "supported_failed_results.jsonl"
    rows = [
        _row(
            item_id="Q-supported-fail",
            status="failed",
            reason="numeric_outside_tolerance",
            citation_present=True,
            numeric_passed=False,
            tokens=1200,
            retrieval_runs=1,
            fetches=2,
            repetition=0.0,
            answer_chars=500,
        ),
        _row(
            item_id="Q-real-fail",
            status="failed",
            reason="numeric_outside_tolerance",
            citation_present=True,
            numeric_passed=False,
            tokens=1500,
            retrieval_runs=2,
            fetches=3,
            repetition=0.1,
            answer_chars=500,
        ),
    ]
    rows[0]["trace_metrics"].update(
        {
            "numeric_verifier_status": "passed",
            "verifier_gate_status": "passed",
        }
    )
    rows[1]["trace_metrics"].update(
        {
            "calculator_call_count": 1,
            "numeric_verifier_status": "failed",
            "verifier_gate_status": "failed",
        }
    )
    results.write_text("\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n", encoding="utf-8")

    report = build_finance_benchmark_report_from_path(results, benchmark_id="finance-supported-fails")
    markdown = render_finance_benchmark_report(report, output_format="markdown")

    assert report.summary["strict_failed_internal_verifier_passed_count"] == 1
    assert report.summary["strict_failed_internal_verifier_passed_rate"] == 0.5
    assert report.summary["failure_layer_counts"] == {
        "numeric_verifier": 1,
        "scoring_alignment_review": 1,
    }
    assert "| Strict-failed internal verifier passed | 1 |" in markdown
    assert "| Strict-failed internal verifier passed rate | 50.0% |" in markdown
    assert "| scoring_alignment_review | 1 |" in markdown
    assert "| numeric_verifier | 1 |" in markdown
    assert "| Q-supported-fail | failed | scoring_alignment_review | numeric_outside_tolerance |" in markdown
    assert "| passed | passed | yes |" in markdown
    assert "Review strict-failed items whose internal verifier passed" in markdown
    assert "Prioritize the largest failed-run diagnostic layer" in markdown


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
