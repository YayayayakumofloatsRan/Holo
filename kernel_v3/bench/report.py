from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from pathlib import Path

from kernel_v3.behavior_graph import build_benchmark_result_graph, load_benchmark_result_records
from kernel_v3.contracts import Contract, JsonObject


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
        f"| Avg retrieval runs | {_number(summary.get('average_retrieval_runs'))} |",
        f"| Avg fetches | {_number(summary.get('average_fetches'))} |",
        f"| Avg query repetition | {_percent(summary.get('average_query_repetition_rate'))} |",
        f"| Calculator-used rate | {_percent(summary.get('calculator_used_rate'))} |",
        f"| Numeric verifier pass rate | {_percent(summary.get('numeric_verifier_pass_rate'))} |",
        f"| Verifier gate pass rate | {_percent(summary.get('verifier_gate_pass_rate'))} |",
        f"| Synthesis gate pass rate | {_percent(summary.get('synthesis_gate_pass_rate'))} |",
        f"| Synthesis gate repair rate | {_percent(summary.get('synthesis_gate_repair_rate'))} |",
        f"| Avg formula traces | {_number(summary.get('average_formula_traces'))} |",
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
        "## Failure Modes",
        "",
        _counts_table(summary.get("failure_mode_counts")),
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
                "failure_mode": _text(metrics.get("latest_failure_mode")),
                "question_preview": _preview(_text(result.get("question")), 140),
                "citation_present": citation_present,
                "total_tokens": _raw_number(metrics.get("total_tokens")),
                "retrieval_runs": _raw_number(metrics.get("retrieval_run_count")),
                "fetches": _raw_number(metrics.get("fetch_attempt_count")),
                "query_repetition_rate": _raw_number(metrics.get("query_repetition_rate")),
                "calculator_calls": _raw_number(metrics.get("calculator_call_count")),
                "formula_traces": _raw_number(metrics.get("formula_trace_count")),
                "claims": _raw_number(metrics.get("claim_count")),
                "missing_slots": _raw_number(metrics.get("missing_slot_count")),
                "transform_plans": _raw_number(metrics.get("transform_plan_count")),
                "finance_facts": _raw_number(metrics.get("finance_fact_count")),
                "numeric_verifier_status": _text(metrics.get("numeric_verifier_status")),
                "verifier_gate_status": _text(metrics.get("verifier_gate_status")),
                "synthesis_gate_status": _text(metrics.get("synthesis_gate_status")),
                "finance_numeric_failure_reason": _text(metrics.get("finance_numeric_failure_reason")),
                "final_answer_chars": _raw_number(metrics.get("final_answer_chars")),
            }
        )
    rows.sort(key=_weak_item_sort_key)
    return rows[: max(0, max_items)]


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
    reasons = _dict(summary.get("reason_counts"))
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
    weak_reasons: dict[str, int] = {}
    for item in weak_items:
        reason = _text(item.get("reason"))
        if reason:
            weak_reasons[reason] = weak_reasons.get(reason, 0) + 1
    reasons = weak_reasons or reasons
    if reasons:
        primary_reason = max(reasons.items(), key=lambda item: int(item[1]) if isinstance(item[1], int) else 0)[0]
        recommendations.append(f"Use score reason `{primary_reason}` as the next scoring/evidence-support improvement target.")
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


def _weak_items_table(rows: list[JsonObject]) -> str:
    if not rows:
        return "_No weak items selected._"
    lines = [
        "| Item | Status | Reason | Failure | Citations | Calc | Traces | Claims | Missing slots | Transforms | Facts | Verifier | Gate | Synth gate | Numeric reason | Retrieval | Repetition | Answer chars |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape_md(_text(row.get("item_id"))),
                    _escape_md(_text(row.get("status"))),
                    _escape_md(_preview(_text(row.get("reason")), 48)),
                    _escape_md(_preview(_text(row.get("failure_mode")), 48)),
                    _value(row.get("citation_present")),
                    _number(row.get("calculator_calls")),
                    _number(row.get("formula_traces")),
                    _number(row.get("claims")),
                    _number(row.get("missing_slots")),
                    _number(row.get("transform_plans")),
                    _number(row.get("finance_facts")),
                    _escape_md(_preview(_text(row.get("numeric_verifier_status")), 32)),
                    _escape_md(_preview(_text(row.get("verifier_gate_status")), 32)),
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
