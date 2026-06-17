from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from kernel_v3.benchmark_diagnostics import finance_failure_layer, strict_failed_internal_verifier_passed
from kernel_v3.behavior_graph import build_benchmark_result_graph, load_benchmark_result_records
from kernel_v3.contracts import Contract, JsonObject
from kernel_v3.processors.usage import aggregate_processor_usage_by_task_type


@dataclass(frozen=True, kw_only=True)
class FinanceBenchmarkReport(Contract):
    schema: str
    status: str
    benchmark_id: str
    title: str
    summary: JsonObject
    weak_items: list[JsonObject] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


def build_finance_benchmark_report(
    results: list[JsonObject],
    *,
    benchmark_id: str = "finance",
    title: str | None = None,
    max_weak_items: int = 20,
) -> FinanceBenchmarkReport:
    graph = build_benchmark_result_graph(results, benchmark_id=benchmark_id, max_items=len(results) or 1)
    summary = dict(graph.diagnostics)
    summary.update(_processor_breakdown(results))
    summary.update(_context_hygiene_breakdown(results))
    summary.update(_agent_loop_breakdown(results))
    summary.update(_tool_observation_diagnostics_breakdown(results))
    summary.update(_finance_verify_numeric_tool_breakdown(results))
    summary.update(_formula_trace_support_breakdown(results))
    summary.update(_structured_repair_breakdown(results))
    summary.update(_internal_verifier_support_breakdown(results))
    summary.update(_failure_layer_breakdown(results))
    report_title = title or f"Holo Kernel v3 Finance Benchmark Report: {benchmark_id}"
    weak_items = _weak_items(results, max_items=max_weak_items)
    return FinanceBenchmarkReport(
        schema="holo.kernel_v3.finance_benchmark_report.v1",
        status="ok",
        benchmark_id=benchmark_id,
        title=report_title,
        summary=summary,
        weak_items=weak_items,
        recommendations=_recommendations(summary, weak_items),
    )


def build_finance_benchmark_report_from_path(
    path: Path | str,
    *,
    benchmark_id: str = "finance",
    title: str | None = None,
    max_weak_items: int = 20,
) -> FinanceBenchmarkReport:
    return build_finance_benchmark_report(
        load_benchmark_result_records(path),
        benchmark_id=benchmark_id,
        title=title,
        max_weak_items=max_weak_items,
    )


def render_finance_benchmark_report(report: FinanceBenchmarkReport, *, output_format: str = "markdown") -> str:
    normalized = output_format.strip().lower()
    if normalized in {"json", "jsonl"}:
        return json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    if normalized in {"html", "htm"}:
        return _render_html(report)
    if normalized in {"markdown", "md"}:
        return _render_markdown(report)
    raise ValueError(f"unsupported benchmark report format: {output_format}")


def _render_markdown(report: FinanceBenchmarkReport) -> str:
    summary = report.summary
    lines = [
        f"# {report.title}",
        "",
        "## Score Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Items | {_value(summary.get('item_count'))} |",
        f"| Scored | {_value(summary.get('scored_count'))} |",
        f"| Passed | {_value(summary.get('passed_count'))} |",
        f"| Pass rate | {_percent(summary.get('pass_rate'))} |",
        f"| Citation-present rate | {_percent(summary.get('citation_present_rate'))} |",
        f"| Numeric accuracy | {_percent(summary.get('numeric_accuracy'))} |",
        f"| Avg tokens | {_number(summary.get('average_total_tokens'))} |",
        f"| Processor calls | {_number(summary.get('processor_call_count'))} |",
        f"| Processor errors | {_number(summary.get('processor_error_count'))} |",
        f"| Processor cache hit ratio | {_percent(summary.get('processor_prompt_cache_hit_ratio'))} |",
        f"| Processor cache hit tokens | {_number(summary.get('processor_prompt_cache_hit_tokens'))} |",
        f"| Processor cache miss tokens | {_number(summary.get('processor_prompt_cache_miss_tokens'))} |",
        f"| Context records | {_number(summary.get('context_record_count'))} |",
        f"| Avg context records | {_number(summary.get('average_context_record_count'))} |",
        f"| Context dynamic-state item rate | {_percent(summary.get('context_dynamic_state_item_rate'))} |",
        f"| Toolchain state prompt-eligible rate | {_percent(summary.get('context_toolchain_state_prompt_eligible_rate'))} |",
        f"| Finance working-state prompt-eligible rate | {_percent(summary.get('context_finance_working_state_prompt_eligible_rate'))} |",
        f"| Agent loop terminal rate | {_percent(summary.get('agent_loop_terminal_rate'))} |",
        f"| Avg agent-loop stage coverage | {_percent(summary.get('average_agent_loop_stage_coverage_rate'))} |",
        f"| Agent loop tool-stage rate | {_percent(summary.get('agent_loop_tool_stage_rate'))} |",
        f"| Agent loop search-stage rate | {_percent(summary.get('agent_loop_search_stage_rate'))} |",
        f"| Agent loop verify-stage rate | {_percent(summary.get('agent_loop_verify_stage_rate'))} |",
        f"| Avg agent-loop deltas | {_number(summary.get('average_agent_loop_delta_count'))} |",
        f"| Avg agent-loop transitions | {_number(summary.get('average_agent_loop_transition_count'))} |",
        f"| Avg toolchain depth | {_number(summary.get('average_toolchain_depth'))} |",
        f"| Retrieval-calculator-verifier chain rate | {_percent(summary.get('retrieval_calculator_verifier_chain_rate'))} |",
        f"| Avg tool observation error rate | {_percent(summary.get('average_tool_observation_error_rate'))} |",
        f"| Tool observation diagnostics rate | {_percent(summary.get('tool_observation_diagnostics_rate'))} |",
        f"| Tool observation repair-guidance rate | {_percent(summary.get('tool_observation_repair_guidance_rate'))} |",
        f"| Avg tool action repetition rate | {_percent(summary.get('average_tool_action_repetition_rate'))} |",
        f"| Avg tool payload repetition rate | {_percent(summary.get('average_tool_action_payload_repetition_rate'))} |",
        f"| Repeated payload groups | {_number(summary.get('tool_action_payload_repeated_group_count'))} |",
        f"| Max payload repeat count | {_number(summary.get('max_tool_action_payload_repeat_count'))} |",
        f"| Post-final clean rate | {_percent(summary.get('post_final_clean_rate'))} |",
        f"| Avg post-final records | {_number(summary.get('average_post_final_record_count'))} |",
        f"| Strict-failed internal verifier passed | {_number(summary.get('strict_failed_internal_verifier_passed_count'))} |",
        f"| Strict-failed internal verifier passed rate | {_percent(summary.get('strict_failed_internal_verifier_passed_rate'))} |",
        f"| Structured repair attempts | {_number(summary.get('structured_repair_attempt_count'))} |",
        f"| Structured repair successes | {_number(summary.get('structured_repair_success_count'))} |",
        f"| Structured repair success rate | {_percent(summary.get('structured_repair_success_rate'))} |",
        f"| Task compile retries | {_number(summary.get('task_compile_retry_count'))} |",
        f"| Finance slot-bind repair attempts | {_number(summary.get('finance_slot_bind_repair_attempt_count'))} |",
        f"| Synthesizer JSON repair attempts | {_number(summary.get('synthesizer_json_repair_attempt_count'))} |",
        f"| Avg retrieval runs | {_number(summary.get('average_retrieval_runs'))} |",
        f"| Avg fetches | {_number(summary.get('average_fetches'))} |",
        f"| Avg query repetition | {_percent(summary.get('average_query_repetition_rate'))} |",
        f"| Calculator-used rate | {_percent(summary.get('calculator_used_rate'))} |",
        f"| Finance verifier tool calls | {_number(summary.get('finance_verify_numeric_tool_call_count'))} |",
        f"| Finance verifier tool used rate | {_percent(summary.get('finance_verify_numeric_tool_used_rate'))} |",
        f"| Finance verifier tool errors | {_number(summary.get('finance_verify_numeric_tool_error_count'))} |",
        f"| Finance verifier tool error rate | {_percent(summary.get('finance_verify_numeric_tool_error_rate'))} |",
        f"| Numeric verifier pass rate | {_percent(summary.get('numeric_verifier_pass_rate'))} |",
        f"| Verifier gate pass rate | {_percent(summary.get('verifier_gate_pass_rate'))} |",
        f"| Synthesis gate pass rate | {_percent(summary.get('synthesis_gate_pass_rate'))} |",
        f"| Synthesis gate repair rate | {_percent(summary.get('synthesis_gate_repair_rate'))} |",
        f"| Avg formula traces | {_number(summary.get('average_formula_traces'))} |",
        f"| Avg trace support links | {_number(summary.get('average_formula_trace_support_count'))} |",
        f"| Formula trace fact-link rate | {_percent(summary.get('formula_trace_fact_link_rate'))} |",
        f"| Formula trace citation-link rate | {_percent(summary.get('formula_trace_citation_link_rate'))} |",
        f"| Formula trace evidence-link rate | {_percent(summary.get('formula_trace_evidence_link_rate'))} |",
        f"| Claim-ledger present rate | {_percent(summary.get('claim_ledger_present_rate'))} |",
        f"| Transform-plan present rate | {_percent(summary.get('transform_plan_present_rate'))} |",
        f"| Slot-frame present rate | {_percent(summary.get('slot_frame_present_rate'))} |",
        f"| Avg missing slots | {_number(summary.get('average_missing_slots'))} |",
        f"| Avg claims | {_number(summary.get('average_claims'))} |",
        f"| Avg finance facts | {_number(summary.get('average_finance_facts'))} |",
        f"| Avg answer numeric support | {_percent(summary.get('average_answer_numeric_support_rate'))} |",
        f"| Unsupported numeric claim rate | {_percent(summary.get('unsupported_numeric_claim_rate'))} |",
        f"| Missing-slot recovery rate | {_percent(summary.get('missing_slot_recovery_rate'))} |",
        f"| Repeated item count | {_number(summary.get('repeated_item_count'))} |",
        f"| Repeatability score | {_percent(summary.get('repeatability_score'))} |",
        f"| Avg tokens per passed item | {_number(summary.get('average_total_tokens_per_passed_item'))} |",
        f"| Avg answer chars | {_number(summary.get('average_final_answer_chars'))} |",
        "",
        "## Status Counts",
        "",
        _counts_table(summary.get("status_counts")),
        "",
        "## Processor Task Types",
        "",
        _counts_table(summary.get("processor_task_type_counts")),
        "",
        "## Processor Cache By Task Type",
        "",
        _processor_cache_table(summary.get("processor_cache_by_task_type")),
        "",
        "## Processor Provider/Model",
        "",
        _counts_table(summary.get("processor_provider_model_counts")),
        "",
        "## Processor Statuses",
        "",
        _counts_table(summary.get("processor_status_counts")),
        "",
        "## Processor Errors",
        "",
        _counts_table(summary.get("processor_error_counts")),
        "",
        "## Context Hygiene",
        "",
        _context_hygiene_table(summary),
        "",
        "## Agent Loop Stage Counts",
        "",
        _counts_table(summary.get("agent_loop_stage_counts")),
        "",
        "## Tool Observation Sources",
        "",
        _counts_table(summary.get("tool_observation_source_counts")),
        "",
        "## Tool Observation Diagnostic Issue Codes",
        "",
        _counts_table(summary.get("tool_observation_diagnostic_issue_code_counts")),
        "",
        "## Tool Payload Repetition",
        "",
        _counts_table(summary.get("tool_action_payload_repeated_tool_counts")),
        "",
        "## Post-Final Record Kinds",
        "",
        _counts_table(summary.get("post_final_record_kind_counts")),
        "",
        "## Failure Modes",
        "",
        _counts_table(summary.get("failure_mode_counts")),
        "",
        "## Failure Layers",
        "",
        _counts_table(summary.get("failure_layer_counts")),
        "",
        "## Finance Numeric Failure Reasons",
        "",
        _counts_table(summary.get("finance_numeric_failure_reason_counts")),
        "",
        "## Workflow Types",
        "",
        _counts_table(summary.get("workflow_type_counts")),
        "",
        "## Score Reasons",
        "",
        _counts_table(summary.get("reason_counts")),
        "",
        "## Weak Items",
        "",
        _weak_items_table(report.weak_items),
        "",
        "## Recommended Next Experiments",
        "",
    ]
    lines.extend(f"- {item}" for item in report.recommendations)
    lines.extend(
        [
            "",
            "## Reproducibility Notes",
            "",
            "- Benchmark gold answers, rubrics, and reference reasoning are scoring material and should not enter agent prompts.",
            "- Use `holo-v3 bench finance-import` to normalize public datasets and preserve provenance manifests.",
            "- Use `holo-v3 bench finance-graph` for topology-level diagnostics over the same result file.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_html(report: FinanceBenchmarkReport) -> str:
    markdown = _render_markdown(report)
    sections = []
    in_list = False
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("# "):
            sections.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            if in_list:
                sections.append("</ul>")
                in_list = False
            if in_table:
                sections.append("</tbody></table>")
                in_table = False
            sections.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|") and not line.startswith("|---"):
            if not in_table:
                sections.append("<table><tbody>")
                in_table = True
            cells = [html.escape(cell.strip()) for cell in line.strip("|").split("|")]
            tag = "th" if cells and cells[0] in {"Metric", "Value", "Key", "Count", "Item", "Status"} else "td"
            sections.append("<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("- "):
            if in_table:
                sections.append("</tbody></table>")
                in_table = False
            if not in_list:
                sections.append("<ul>")
                in_list = True
            sections.append(f"<li>{html.escape(line[2:])}</li>")
        elif not line.strip():
            continue
        else:
            if in_list:
                sections.append("</ul>")
                in_list = False
            if in_table:
                sections.append("</tbody></table>")
                in_table = False
            sections.append(f"<p>{html.escape(line)}</p>")
    if in_list:
        sections.append("</ul>")
    if in_table:
        sections.append("</tbody></table>")
    css = """
body { font-family: system-ui, sans-serif; margin: 32px; color: #222; }
h1, h2 { color: #222; }
table { border-collapse: collapse; margin: 12px 0 24px; min-width: 520px; }
th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
th { background: #f2f2f2; }
tr:nth-child(even) td { background: #fafafa; }
li { margin: 4px 0; }
"""
    return "<!doctype html>\n<html><head><meta charset=\"utf-8\"><style>" + css + "</style></head><body>\n" + "\n".join(sections) + "\n</body></html>\n"


def _weak_items(results: list[JsonObject], *, max_items: int) -> list[JsonObject]:
    rows: list[JsonObject] = []
    for result in results:
        scorecard = _dict(result.get("scorecard"))
        metrics = _dict(result.get("trace_metrics"))
        status = _text(result.get("status")) or _text(scorecard.get("status")) or "unknown"
        citation_present = scorecard.get("citation_present")
        processor_errors = _raw_number(metrics.get("processor_error_count"))
        if status == "passed" and citation_present is True and not processor_errors:
            continue
        rows.append(
            {
                "item_id": _text(result.get("item_id")),
                "status": status,
                "reason": _text(scorecard.get("reason")),
                "failure_layer": finance_failure_layer(
                    status=status,
                    scorecard=scorecard,
                    trace_metrics=metrics,
                    failure_report=result.get("failure_report"),
                ),
                "failure_mode": _text(metrics.get("latest_failure_mode")),
                "question_preview": _preview(_text(result.get("question")), 140),
                "citation_present": citation_present,
                "total_tokens": _raw_number(metrics.get("total_tokens")),
                "retrieval_runs": _raw_number(metrics.get("retrieval_run_count")),
                "fetches": _raw_number(metrics.get("fetch_attempt_count")),
                "query_repetition_rate": _raw_number(metrics.get("query_repetition_rate")),
                "calculator_calls": _raw_number(metrics.get("calculator_call_count")),
                "formula_traces": _raw_number(metrics.get("formula_trace_count")),
                "formula_trace_fact_link_rate": _raw_number(metrics.get("formula_trace_fact_link_rate")),
                "formula_trace_citation_link_rate": _raw_number(metrics.get("formula_trace_citation_link_rate")),
                "formula_trace_evidence_link_rate": _raw_number(metrics.get("formula_trace_evidence_link_rate")),
                "claims": _raw_number(metrics.get("claim_count")),
                "missing_slots": _raw_number(metrics.get("missing_slot_count")),
                "transform_plans": _raw_number(metrics.get("transform_plan_count")),
                "finance_facts": _raw_number(metrics.get("finance_fact_count")),
                "numeric_verifier_status": _text(metrics.get("numeric_verifier_status")),
                "verifier_gate_status": _text(metrics.get("verifier_gate_status")),
                "synthesis_gate_status": _text(metrics.get("synthesis_gate_status")),
                "internal_verifier_support": strict_failed_internal_verifier_passed(
                    status=status,
                    scorecard=scorecard,
                    trace_metrics=metrics,
                ),
                "finance_numeric_failure_reason": _text(metrics.get("finance_numeric_failure_reason")),
                "final_answer_chars": _raw_number(metrics.get("final_answer_chars")),
            }
        )
    rows.sort(key=_weak_item_sort_key)
    return rows[: max(0, max_items)]


def _processor_breakdown(results: list[JsonObject]) -> JsonObject:
    task_counts: dict[str, int] = {}
    provider_model_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    error_counts: dict[str, int] = {}
    cache_hit = 0
    cache_miss = 0
    call_count = 0
    error_count = 0
    duration_ms = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        cache_hit += _int(metrics.get("processor_prompt_cache_hit_tokens"))
        cache_miss += _int(metrics.get("processor_prompt_cache_miss_tokens"))
        call_count += _int(metrics.get("processor_call_count"))
        error_count += _int(metrics.get("processor_error_count"))
        duration_ms += _int(metrics.get("processor_duration_ms"))
        _merge_counts(status_counts, _dict(metrics.get("processor_status_counts")))
        _merge_counts(error_counts, _dict(metrics.get("processor_error_counts")))
        _merge_nested_call_counts(task_counts, metrics.get("processor_usage_by_task_type"))
        _merge_nested_call_counts(provider_model_counts, metrics.get("processor_usage_by_provider_model"))
    if not error_count and error_counts:
        error_count = sum(error_counts.values())
    total_cache_tokens = cache_hit + cache_miss
    return {
        "processor_call_count": call_count,
        "processor_error_count": error_count,
        "processor_duration_ms": duration_ms,
        "processor_prompt_cache_hit_tokens": cache_hit,
        "processor_prompt_cache_miss_tokens": cache_miss,
        "processor_prompt_cache_hit_ratio": round(cache_hit / total_cache_tokens, 6) if total_cache_tokens else None,
        "processor_task_type_counts": task_counts,
        "processor_cache_by_task_type": aggregate_processor_usage_by_task_type([_dict(result.get("trace_metrics")) for result in results]),
        "processor_provider_model_counts": provider_model_counts,
        "processor_status_counts": status_counts,
        "processor_error_counts": error_counts,
    }


def _context_hygiene_breakdown(results: list[JsonObject]) -> JsonObject:
    context_count = 0
    dynamic_context_count = 0
    dynamic_item_count = 0
    toolchain_present = 0
    toolchain_empty = 0
    finance_present = 0
    finance_empty = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        context_count += _int(metrics.get("context_record_count"))
        dynamic_context_count += _int(metrics.get("context_dynamic_state_present_count"))
        toolchain_present += _int(metrics.get("context_toolchain_state_present_count"))
        toolchain_empty += _int(metrics.get("context_toolchain_state_empty_count"))
        finance_present += _int(metrics.get("context_finance_working_state_present_count"))
        finance_empty += _int(metrics.get("context_finance_working_state_empty_count"))
        if _int(metrics.get("context_dynamic_state_present_count")) > 0:
            dynamic_item_count += 1
    return {
        "context_record_count": context_count,
        "average_context_record_count": round(context_count / len(results), 6) if results else 0.0,
        "context_dynamic_state_present_count": dynamic_context_count,
        "context_dynamic_state_present_rate": round(dynamic_context_count / context_count, 6) if context_count else None,
        "context_dynamic_state_item_rate": round(dynamic_item_count / len(results), 6) if results else 0.0,
        "context_toolchain_state_present_count": toolchain_present,
        "context_toolchain_state_empty_count": toolchain_empty,
        "context_toolchain_state_prompt_eligible_rate": round(toolchain_present / context_count, 6)
        if context_count
        else None,
        "context_finance_working_state_present_count": finance_present,
        "context_finance_working_state_empty_count": finance_empty,
        "context_finance_working_state_prompt_eligible_rate": round(finance_present / context_count, 6)
        if context_count
        else None,
    }


def _formula_trace_support_breakdown(results: list[JsonObject]) -> JsonObject:
    support_count = 0
    fact_linked = 0
    citation_linked = 0
    evidence_linked = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        support_count += _int(metrics.get("formula_trace_support_count"))
        fact_linked += _int(metrics.get("formula_trace_fact_linked_count"))
        citation_linked += _int(metrics.get("formula_trace_citation_linked_count"))
        evidence_linked += _int(metrics.get("formula_trace_evidence_linked_count"))
    return {
        "average_formula_trace_support_count": round(support_count / len(results), 6) if results else 0.0,
        "formula_trace_fact_link_rate": round(fact_linked / support_count, 6) if support_count else None,
        "formula_trace_citation_link_rate": round(citation_linked / support_count, 6) if support_count else None,
        "formula_trace_evidence_link_rate": round(evidence_linked / support_count, 6) if support_count else None,
    }


def _agent_loop_breakdown(results: list[JsonObject]) -> JsonObject:
    stage_counts: dict[str, int] = {}
    coverage_values: list[float] = []
    delta_values: list[float] = []
    transition_values: list[float] = []
    toolchain_depth_values: list[float] = []
    tool_error_values: list[float] = []
    tool_repetition_values: list[float] = []
    tool_payload_repetition_values: list[float] = []
    post_final_values: list[float] = []
    tool_observation_source_counts: dict[str, int] = {}
    tool_payload_repeated_tool_counts: dict[str, int] = {}
    post_final_record_kind_counts: dict[str, int] = {}
    repeated_payload_group_count = 0
    max_payload_repeat_count = 0
    terminal_count = 0
    tool_stage_count = 0
    search_stage_count = 0
    verify_stage_count = 0
    complete_toolchain_count = 0
    post_final_clean_count = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        _merge_counts(stage_counts, _dict(metrics.get("agent_loop_stage_counts")))
        _merge_counts(tool_observation_source_counts, _dict(metrics.get("tool_observation_source_counts")))
        _merge_counts(tool_payload_repeated_tool_counts, _dict(metrics.get("tool_action_payload_repeated_tool_counts")))
        _merge_counts(post_final_record_kind_counts, _dict(metrics.get("post_final_record_kind_counts")))
        coverage = _float_or_none(metrics.get("agent_loop_stage_coverage_rate"))
        if coverage is not None:
            coverage_values.append(coverage)
        delta_count = _float_or_none(metrics.get("agent_loop_delta_count"))
        if delta_count is not None:
            delta_values.append(delta_count)
        transition_count = _float_or_none(metrics.get("agent_loop_transition_count"))
        if transition_count is not None:
            transition_values.append(transition_count)
        toolchain_depth = _float_or_none(metrics.get("toolchain_depth"))
        if toolchain_depth is not None:
            toolchain_depth_values.append(toolchain_depth)
        tool_error_rate = _float_or_none(metrics.get("tool_observation_error_rate"))
        if tool_error_rate is not None:
            tool_error_values.append(tool_error_rate)
        tool_repetition_rate = _float_or_none(metrics.get("tool_action_repetition_rate"))
        if tool_repetition_rate is not None:
            tool_repetition_values.append(tool_repetition_rate)
        tool_payload_repetition_rate = _float_or_none(metrics.get("tool_action_payload_repetition_rate"))
        if tool_payload_repetition_rate is not None:
            tool_payload_repetition_values.append(tool_payload_repetition_rate)
        repeated_payload_group_count += _int(metrics.get("tool_action_payload_repeated_group_count"))
        max_payload_repeat_count = max(max_payload_repeat_count, _int(metrics.get("tool_action_payload_max_repeat_count")))
        post_final_record_count = _float_or_none(metrics.get("post_final_record_count"))
        if post_final_record_count is not None:
            post_final_values.append(post_final_record_count)
        if metrics.get("agent_loop_terminal") is True:
            terminal_count += 1
        if metrics.get("agent_loop_tool_stage_present") is True:
            tool_stage_count += 1
        if metrics.get("agent_loop_search_stage_present") is True:
            search_stage_count += 1
        if metrics.get("agent_loop_verify_stage_present") is True:
            verify_stage_count += 1
        if metrics.get("retrieval_calculator_verifier_chain_present") is True:
            complete_toolchain_count += 1
        if _int(metrics.get("post_final_record_count")) == 0:
            post_final_clean_count += 1
    denominator = len(results)
    return {
        "agent_loop_stage_counts": stage_counts,
        "tool_observation_source_counts": tool_observation_source_counts,
        "tool_action_payload_repeated_tool_counts": tool_payload_repeated_tool_counts,
        "tool_action_payload_repeated_group_count": repeated_payload_group_count,
        "max_tool_action_payload_repeat_count": max_payload_repeat_count,
        "post_final_record_kind_counts": post_final_record_kind_counts,
        "average_agent_loop_stage_coverage_rate": round(sum(coverage_values) / len(coverage_values), 6)
        if coverage_values
        else 0.0,
        "agent_loop_terminal_rate": round(terminal_count / denominator, 6) if denominator else 0.0,
        "agent_loop_tool_stage_rate": round(tool_stage_count / denominator, 6) if denominator else 0.0,
        "agent_loop_search_stage_rate": round(search_stage_count / denominator, 6) if denominator else 0.0,
        "agent_loop_verify_stage_rate": round(verify_stage_count / denominator, 6) if denominator else 0.0,
        "average_agent_loop_delta_count": round(sum(delta_values) / len(delta_values), 6) if delta_values else 0.0,
        "average_agent_loop_transition_count": round(sum(transition_values) / len(transition_values), 6)
        if transition_values
        else 0.0,
        "average_toolchain_depth": round(sum(toolchain_depth_values) / len(toolchain_depth_values), 6)
        if toolchain_depth_values
        else 0.0,
        "retrieval_calculator_verifier_chain_rate": round(complete_toolchain_count / denominator, 6) if denominator else 0.0,
        "average_tool_observation_error_rate": round(sum(tool_error_values) / len(tool_error_values), 6)
        if tool_error_values
        else 0.0,
        "average_tool_action_repetition_rate": round(sum(tool_repetition_values) / len(tool_repetition_values), 6)
        if tool_repetition_values
        else 0.0,
        "average_tool_action_payload_repetition_rate": round(
            sum(tool_payload_repetition_values) / len(tool_payload_repetition_values),
            6,
        )
        if tool_payload_repetition_values
        else 0.0,
        "post_final_clean_rate": round(post_final_clean_count / denominator, 6) if denominator else 0.0,
        "average_post_final_record_count": round(sum(post_final_values) / len(post_final_values), 6)
        if post_final_values
        else 0.0,
    }


def _finance_verify_numeric_tool_breakdown(results: list[JsonObject]) -> JsonObject:
    call_count = 0
    error_count = 0
    used_items = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        calls = _int(metrics.get("finance_verify_numeric_tool_call_count"))
        errors = _int(metrics.get("finance_verify_numeric_tool_error_count"))
        call_count += calls
        error_count += errors
        if calls > 0:
            used_items += 1
    return {
        "finance_verify_numeric_tool_call_count": call_count,
        "finance_verify_numeric_tool_error_count": error_count,
        "finance_verify_numeric_tool_used_rate": round(used_items / len(results), 6) if results else 0.0,
        "finance_verify_numeric_tool_error_rate": round(error_count / call_count, 6) if call_count else None,
    }


def _tool_observation_diagnostics_breakdown(results: list[JsonObject]) -> JsonObject:
    observation_count = 0
    diagnostic_count = 0
    repair_guidance_count = 0
    context_diagnostic_count = 0
    issue_code_counts: dict[str, int] = {}
    context_count = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        observation_count += _int(metrics.get("tool_observation_count"))
        diagnostic_count += _int(metrics.get("tool_observation_diagnostics_count"))
        repair_guidance_count += _int(metrics.get("tool_observation_repair_guidance_count"))
        context_diagnostic_count += _int(metrics.get("context_toolchain_observation_diagnostics_present_count"))
        context_count += _int(metrics.get("context_record_count"))
        _merge_counts(issue_code_counts, _dict(metrics.get("tool_observation_diagnostic_issue_code_counts")))
    return {
        "tool_observation_diagnostics_count": diagnostic_count,
        "tool_observation_repair_guidance_count": repair_guidance_count,
        "tool_observation_diagnostics_rate": round(diagnostic_count / observation_count, 6)
        if observation_count
        else None,
        "tool_observation_repair_guidance_rate": round(repair_guidance_count / observation_count, 6)
        if observation_count
        else None,
        "tool_observation_diagnostic_issue_code_counts": issue_code_counts,
        "context_toolchain_observation_diagnostics_present_count": context_diagnostic_count,
        "context_toolchain_observation_diagnostics_prompt_eligible_rate": round(context_diagnostic_count / context_count, 6)
        if context_count
        else None,
    }


def _structured_repair_breakdown(results: list[JsonObject]) -> JsonObject:
    task_compile_retry_count = 0
    task_compile_retry_success_count = 0
    finance_slot_bind_repair_attempt_count = 0
    finance_slot_bind_repair_success_count = 0
    synthesizer_json_repair_attempt_count = 0
    synthesizer_json_repair_success_count = 0
    structured_repair_attempt_count = 0
    structured_repair_success_count = 0
    for result in results:
        metrics = _dict(result.get("trace_metrics"))
        task_compile_retry_count += _int(metrics.get("task_compile_retry_count"))
        task_compile_retry_success_count += _int(metrics.get("task_compile_retry_success_count"))
        finance_slot_bind_repair_attempt_count += _int(metrics.get("finance_slot_bind_repair_attempt_count"))
        finance_slot_bind_repair_success_count += _int(metrics.get("finance_slot_bind_repair_success_count"))
        synthesizer_json_repair_attempt_count += _int(metrics.get("synthesizer_json_repair_attempt_count"))
        synthesizer_json_repair_success_count += _int(metrics.get("synthesizer_json_repair_success_count"))
        structured_repair_attempt_count += _int(metrics.get("structured_repair_attempt_count"))
        structured_repair_success_count += _int(metrics.get("structured_repair_success_count"))
    return {
        "task_compile_retry_count": task_compile_retry_count,
        "task_compile_retry_success_count": task_compile_retry_success_count,
        "finance_slot_bind_repair_attempt_count": finance_slot_bind_repair_attempt_count,
        "finance_slot_bind_repair_success_count": finance_slot_bind_repair_success_count,
        "synthesizer_json_repair_attempt_count": synthesizer_json_repair_attempt_count,
        "synthesizer_json_repair_success_count": synthesizer_json_repair_success_count,
        "structured_repair_attempt_count": structured_repair_attempt_count,
        "structured_repair_success_count": structured_repair_success_count,
        "structured_repair_success_rate": round(structured_repair_success_count / structured_repair_attempt_count, 6)
        if structured_repair_attempt_count
        else None,
    }


def _internal_verifier_support_breakdown(results: list[JsonObject]) -> JsonObject:
    failed_count = 0
    supported_count = 0
    for result in results:
        scorecard = _dict(result.get("scorecard"))
        metrics = _dict(result.get("trace_metrics"))
        status = _text(result.get("status")) or _text(scorecard.get("status")) or "unknown"
        if status != "failed":
            continue
        failed_count += 1
        if strict_failed_internal_verifier_passed(status=status, scorecard=scorecard, trace_metrics=metrics):
            supported_count += 1
    return {
        "strict_failed_internal_verifier_passed_count": supported_count,
        "strict_failed_internal_verifier_passed_rate": round(supported_count / failed_count, 6) if failed_count else None,
    }


def _failure_layer_breakdown(results: list[JsonObject]) -> JsonObject:
    counts: dict[str, int] = {}
    for result in results:
        scorecard = _dict(result.get("scorecard"))
        metrics = _dict(result.get("trace_metrics"))
        status = _text(result.get("status")) or _text(scorecard.get("status")) or "unknown"
        if status != "failed":
            continue
        layer = finance_failure_layer(
            status=status,
            scorecard=scorecard,
            trace_metrics=metrics,
            failure_report=result.get("failure_report"),
        )
        counts[layer] = counts.get(layer, 0) + 1
    return {"failure_layer_counts": counts}


def _merge_counts(target: dict[str, int], value: JsonObject) -> None:
    for key, count in value.items():
        target[str(key)] = target.get(str(key), 0) + _int(count)


def _merge_nested_call_counts(target: dict[str, int], value: object) -> None:
    if not isinstance(value, dict):
        return
    for key, payload in value.items():
        if isinstance(payload, dict):
            count = _int(payload.get("call_count"))
        else:
            count = _int(payload)
        target[str(key)] = target.get(str(key), 0) + count


def _recommendations(summary: JsonObject, weak_items: list[JsonObject]) -> list[str]:
    recommendations: list[str] = []
    pass_rate = _float(summary.get("pass_rate"))
    citation_rate = _float(summary.get("citation_present_rate"))
    repetition = _float(summary.get("average_query_repetition_rate"))
    answer_chars = _float(summary.get("average_final_answer_chars"))
    calculator_rate = _float(summary.get("calculator_used_rate"))
    verifier_rate = _float(summary.get("numeric_verifier_pass_rate"))
    support_rate = _float(summary.get("average_answer_numeric_support_rate"))
    failure_modes = _dict(summary.get("failure_mode_counts"))
    failure_layers = _dict(summary.get("failure_layer_counts"))
    reasons = _dict(summary.get("reason_counts"))
    processor_errors = _dict(summary.get("processor_error_counts"))
    internally_supported_failures = _int(summary.get("strict_failed_internal_verifier_passed_count"))
    trace_support_count = _float(summary.get("average_formula_trace_support_count"))
    trace_fact_rate = _float_or_none(summary.get("formula_trace_fact_link_rate"))
    trace_citation_rate = _float_or_none(summary.get("formula_trace_citation_link_rate"))
    trace_evidence_rate = _float_or_none(summary.get("formula_trace_evidence_link_rate"))
    repair_attempts = _int(summary.get("structured_repair_attempt_count"))
    repair_rate = _float_or_none(summary.get("structured_repair_success_rate"))
    if pass_rate < 0.8:
        recommendations.append("Prioritize failure-cluster analysis before adding new features; pass rate is below a strong harness threshold.")
    if citation_rate < 0.9:
        recommendations.append("Tighten evidence and citation extraction, then rerun citation-heavy subsets.")
    if repetition > 0.25:
        recommendations.append("Inspect repeated-query loops and improve strategy-shift directives for failed retrieval attempts.")
    if answer_chars and answer_chars < 600:
        recommendations.append("Review answer-profile enforcement; detailed research tasks may be ending with under-developed synthesis.")
    if calculator_rate < 0.7:
        recommendations.append("Increase calculator usage on numeric finance tasks; inspect planner hints and formula planner coverage.")
    if verifier_rate is not None and verifier_rate < 0.7:
        recommendations.append("Classify numeric verifier failures into correct block, ledger miss, and policy miss before widening the benchmark slice.")
    if support_rate is not None and support_rate < 0.7:
        recommendations.append("Improve fact ledger extraction and formula trace binding; answer numeric support rate is below target.")
    failure_modes = {key: value for key, value in failure_modes.items() if str(key).lower() not in {"", "none", "unknown"}}
    if failure_modes:
        primary = max(failure_modes.items(), key=lambda item: int(item[1]) if isinstance(item[1], int) else 0)[0]
        recommendations.append(f"Run targeted live diagnostics for the largest failure mode: {primary}.")
    if failure_layers:
        primary_layer = max(failure_layers.items(), key=lambda item: _int(item[1]))[0]
        recommendations.append(f"Prioritize the largest failed-run diagnostic layer: `{primary_layer}`.")
    weak_reasons: dict[str, int] = {}
    for item in weak_items:
        reason = _text(item.get("reason"))
        if reason:
            weak_reasons[reason] = weak_reasons.get(reason, 0) + 1
    reasons = weak_reasons or reasons
    if reasons:
        primary_reason = max(reasons.items(), key=lambda item: int(item[1]) if isinstance(item[1], int) else 0)[0]
        recommendations.append(f"Use score reason `{primary_reason}` as the next scoring/evidence-support improvement target.")
    if processor_errors:
        primary_processor_error = max(processor_errors.items(), key=lambda item: _int(item[1]))[0]
        recommendations.append(f"Inspect processor error cluster `{primary_processor_error}` before widening the next live run.")
    if internally_supported_failures:
        recommendations.append("Review strict-failed items whose internal verifier passed; separate real ability failures from scoring, formatting, or final-synthesis alignment issues.")
    if repair_attempts and repair_rate is not None and repair_rate < 0.8:
        recommendations.append("Inspect structured-output repair prompts; task.compile or finance.slot_bind retries are not recovering reliably.")
    if summary.get("processor_prompt_cache_hit_ratio") is not None:
        recommendations.append("Track processor cache hit ratio across the next run to verify stable prompt-prefix reuse.")
    if _int(summary.get("context_record_count")) and _float_or_none(summary.get("context_toolchain_state_prompt_eligible_rate")) == 0.0:
        recommendations.append("Inspect context compiler output; no non-empty toolchain_state reached context packets in this benchmark run.")
    if _int(summary.get("context_record_count")) and _float_or_none(summary.get("context_finance_working_state_prompt_eligible_rate")) == 0.0:
        recommendations.append("Inspect finance working-state compaction; no non-empty finance_working_state reached context packets in this benchmark run.")
    if trace_support_count and trace_fact_rate is not None and trace_fact_rate < 0.9:
        recommendations.append("Inspect FormulaTrace input_fact_ids versus finance_fact_ledger ids; calculator traces are not consistently linked back to model-selected facts.")
    if trace_support_count and trace_citation_rate is not None and trace_citation_rate < 0.9:
        recommendations.append("Improve FormulaTrace citation provenance; computed values are not consistently linked to citation refs for final synthesis and numeric judge.")
    if trace_support_count and trace_evidence_rate is not None and trace_evidence_rate < 0.9:
        recommendations.append("Improve FormulaTrace evidence provenance; computed values are not consistently linked to evidence refs for auditability.")
    if weak_items:
        recommendations.append("Sample weak-item behavior graphs to verify whether failures are caused by planning, source acquisition, extraction, or synthesis.")
    if not recommendations:
        recommendations.append("Run a larger public benchmark slice and compare against the previous run before changing the harness.")
    return recommendations


def _counts_table(value: object) -> str:
    counts = _dict(value)
    if not counts:
        return "_None recorded._"
    lines = ["| Key | Count |", "|---|---:|"]
    for key, count in sorted(counts.items(), key=lambda item: (-_int(item[1]), str(item[0]))):
        lines.append(f"| {str(key)} | {_value(count)} |")
    return "\n".join(lines)


def _context_hygiene_table(summary: JsonObject) -> str:
    rows = [
        ("Context records", _number(summary.get("context_record_count"))),
        ("Average context records", _number(summary.get("average_context_record_count"))),
        ("Dynamic-state contexts", _number(summary.get("context_dynamic_state_present_count"))),
        ("Dynamic-state context rate", _percent(summary.get("context_dynamic_state_present_rate"))),
        ("Dynamic-state item rate", _percent(summary.get("context_dynamic_state_item_rate"))),
        ("Toolchain state present", _number(summary.get("context_toolchain_state_present_count"))),
        ("Toolchain state empty", _number(summary.get("context_toolchain_state_empty_count"))),
        ("Toolchain prompt-eligible rate", _percent(summary.get("context_toolchain_state_prompt_eligible_rate"))),
        (
            "Toolchain observation diagnostics prompt-eligible rate",
            _percent(summary.get("context_toolchain_observation_diagnostics_prompt_eligible_rate")),
        ),
        ("Finance working-state present", _number(summary.get("context_finance_working_state_present_count"))),
        ("Finance working-state empty", _number(summary.get("context_finance_working_state_empty_count"))),
        (
            "Finance working-state prompt-eligible rate",
            _percent(summary.get("context_finance_working_state_prompt_eligible_rate")),
        ),
    ]
    lines = ["| Metric | Value |", "|---|---:|"]
    for label, value in rows:
        lines.append(f"| {label} | {value} |")
    return "\n".join(lines)


def _processor_cache_table(value: object) -> str:
    rows = _dict(value)
    if not rows:
        return "_None recorded._"
    lines = ["| Task type | Calls | Cache hit | Cache miss | Cache ratio | Total tokens |", "|---|---:|---:|---:|---:|---:|"]
    for task_type, payload in sorted(rows.items()):
        bucket = _dict(payload)
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_md(str(task_type)),
                    _number(bucket.get("call_count")),
                    _number(bucket.get("prompt_cache_hit_tokens")),
                    _number(bucket.get("prompt_cache_miss_tokens")),
                    _percent(bucket.get("prompt_cache_hit_ratio")),
                    _number(bucket.get("total_tokens")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _weak_items_table(rows: list[JsonObject]) -> str:
    if not rows:
        return "_No weak items selected._"
    lines = [
        "| Item | Status | Layer | Reason | Failure | Citations | Calc | Traces | Trace link | Trace cite | Trace evidence | Claims | Missing slots | Transforms | Facts | Verifier | Gate | Internal support | Synth gate | Numeric reason | Retrieval | Repetition | Answer chars |",
        "|---|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---:|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_md(_text(row.get("item_id"))),
                    _escape_md(_text(row.get("status"))),
                    _escape_md(_preview(_text(row.get("failure_layer")), 48)),
                    _escape_md(_preview(_text(row.get("reason")), 48)),
                    _escape_md(_preview(_text(row.get("failure_mode")), 48)),
                    _value(row.get("citation_present")),
                    _number(row.get("calculator_calls")),
                    _number(row.get("formula_traces")),
                    _percent(row.get("formula_trace_fact_link_rate")),
                    _percent(row.get("formula_trace_citation_link_rate")),
                    _percent(row.get("formula_trace_evidence_link_rate")),
                    _number(row.get("claims")),
                    _number(row.get("missing_slots")),
                    _number(row.get("transform_plans")),
                    _number(row.get("finance_facts")),
                    _escape_md(_preview(_text(row.get("numeric_verifier_status")), 32)),
                    _escape_md(_preview(_text(row.get("verifier_gate_status")), 32)),
                    _value(row.get("internal_verifier_support")),
                    _escape_md(_preview(_text(row.get("synthesis_gate_status")), 32)),
                    _escape_md(_preview(_text(row.get("finance_numeric_failure_reason")), 48)),
                    _number(row.get("retrieval_runs")),
                    _percent(row.get("query_repetition_rate")),
                    _number(row.get("final_answer_chars")),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def _weak_item_sort_key(item: JsonObject) -> tuple[int, float, float, str]:
    status_penalty = 0 if item.get("status") == "failed" else 1
    citation_penalty = 0 if item.get("citation_present") is False else 1
    repetition = -_float(item.get("query_repetition_rate"))
    tokens = -_float(item.get("total_tokens"))
    return (status_penalty, citation_penalty, repetition + tokens / 1_000_000, _text(item.get("item_id")))


def _dict(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _preview(text: str, limit: int) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 1)].rstrip() + "…"


def _number(value: object) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    return f"{number:.4g}"


def _raw_number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    return None


def _percent(value: object) -> str:
    number = _float_or_none(value)
    if number is None:
        return "-"
    return f"{number * 100:.1f}%"


def _value(value: object) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return _number(value)
    return _escape_md(str(value))


def _float(value: object) -> float:
    parsed = _float_or_none(value)
    return parsed if parsed is not None else 0.0


def _float_or_none(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _escape_md(value: str) -> str:
    return str(value).replace("|", "\\|")
