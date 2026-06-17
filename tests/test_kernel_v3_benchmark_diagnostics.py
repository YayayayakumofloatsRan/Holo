from kernel_v3.benchmark_diagnostics import finance_failure_layer, strict_failed_internal_verifier_passed


def test_strict_failed_internal_verifier_passed_requires_failed_answer_and_passed_gate() -> None:
    assert strict_failed_internal_verifier_passed(
        status="failed",
        scorecard={"answer_present": True},
        trace_metrics={"numeric_verifier_status": "passed"},
    ) is True
    assert strict_failed_internal_verifier_passed(
        status="passed",
        scorecard={"answer_present": True},
        trace_metrics={"numeric_verifier_status": "passed"},
    ) is False
    assert strict_failed_internal_verifier_passed(
        status="failed",
        scorecard={"answer_present": False},
        trace_metrics={"verifier_gate_status": "passed"},
    ) is False


def test_finance_failure_layer_prioritizes_actionable_post_run_diagnostics() -> None:
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True, "reason": "numeric_outside_tolerance"},
        trace_metrics={"numeric_verifier_status": "passed"},
    ) == "scoring_alignment_review"
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True},
        trace_metrics={"processor_error_counts": {"json_invalid": 1}},
    ) == "processor_failure"
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True},
        trace_metrics={"latest_failure_mode": "fetch_failed"},
    ) == "retrieval_or_evidence"
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True, "citation_present": False},
        trace_metrics={},
    ) == "citation_grounding"
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True, "citation_present": True, "numeric": {"scored": True}},
        trace_metrics={"calculator_call_count": 0},
    ) == "calculation_or_formula_trace"
    assert finance_failure_layer(
        status="failed",
        scorecard={"answer_present": True, "citation_present": True, "numeric": {"scored": True}},
        trace_metrics={"calculator_call_count": 1, "numeric_verifier_status": "failed"},
    ) == "numeric_verifier"
