from __future__ import annotations

from kernel_v3.contracts import JsonObject


def strict_failed_internal_verifier_passed(
    *,
    status: str,
    scorecard: JsonObject,
    trace_metrics: JsonObject,
) -> bool:
    if status != "failed":
        return False
    if scorecard.get("answer_present") is not True:
        return False
    numeric_status = _text(trace_metrics.get("numeric_verifier_status")).lower()
    gate_status = _text(trace_metrics.get("verifier_gate_status")).lower()
    return numeric_status == "passed" or gate_status == "passed"


def finance_failure_layer(
    *,
    status: str,
    scorecard: JsonObject,
    trace_metrics: JsonObject,
    failure_report: object = None,
) -> str:
    if status != "failed":
        return ""
    if strict_failed_internal_verifier_passed(
        status=status,
        scorecard=scorecard,
        trace_metrics=trace_metrics,
    ):
        return "scoring_alignment_review"
    reason = _text(scorecard.get("reason")).lower()
    latest_failure_mode = _text(trace_metrics.get("latest_failure_mode")).lower()
    if _int(trace_metrics.get("processor_error_count")) > 0 or _dict(trace_metrics.get("processor_error_counts")):
        return "processor_failure"
    if reason == "empty_answer" or scorecard.get("answer_present") is False:
        return "empty_answer"
    if isinstance(failure_report, dict) or reason == "failure_report_not_final_answer":
        return "failure_report"
    if any(token in latest_failure_mode for token in ("retrieval", "search", "fetch", "source", "evidence")):
        return "retrieval_or_evidence"
    if scorecard.get("citation_present") is False:
        return "citation_grounding"
    numeric = _dict(scorecard.get("numeric"))
    if numeric.get("scored") is True and _int(trace_metrics.get("calculator_call_count")) == 0:
        return "calculation_or_formula_trace"
    if _text(trace_metrics.get("numeric_verifier_status")).lower() == "failed" or _text(trace_metrics.get("verifier_gate_status")).lower() == "failed":
        return "numeric_verifier"
    if _text(trace_metrics.get("synthesis_gate_status")).lower() == "failed":
        return "synthesis_gate"
    if reason in {"numeric_outside_tolerance", "gold_text_not_matched"}:
        return "strict_scoring"
    return "unknown"


def _dict(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()
