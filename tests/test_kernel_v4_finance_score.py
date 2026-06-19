from __future__ import annotations

import json

from kernel_v4.finance_score import main, score_run_payload


def test_finance_score_matches_expected_numeric_in_answer() -> None:
    payload = {
        "status": "completed",
        "answer": "Answer: $127.40 per transaction. Calculation: 637 / 5.0 = 127.4.",
        "task": {"task_id": "V/2008/page_17.pdf-1"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "V/2008/page_17.pdf-1",
        "source": "finqa",
        "expected_numeric": [{"name": "gold_numeric_1", "value": 127.4, "tolerance": 1.274}],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["reason"] == "numeric_within_tolerance"
    assert score["numeric_hit_count"] == 1
    assert score["gold_reference_material_used_for_scoring_only"] is True
    assert score["gold_reference_material_in_model_context"] is False


def test_finance_score_percent_can_match_fraction_expectation() -> None:
    payload = {
        "status": "completed",
        "answer": "Revenue growth was 20%.",
        "task": {"task_id": "row-1"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "row-1",
        "expected_numeric": [{"name": "growth", "value": 0.2, "tolerance": 0.001}],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["numeric_matches"][0]["matched_value"] == 0.2


def test_finance_score_skips_company_name_3m_numeric_noise() -> None:
    payload = {
        "status": "completed",
        "answer": "3M operating margin declined from 20.8% to 19.1%, a 1.7 percentage point decrease.",
        "task": {"task_id": "financebench_id_01226"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_01226",
        "expected_numeric": [
            {"name": "entity_name_noise", "value": 3_000_000.0, "tolerance": 30_000.0},
            {"name": "margin_change", "value": 1.7, "tolerance": 1.0},
        ],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["numeric_scored_count"] == 1
    assert score["numeric_unscored_count"] == 1
    assert score["numeric_matches"][0]["reason"] == "likely_entity_name_numeric_noise"


def test_finance_score_prefers_closest_match_and_accepts_negative_delta_magnitude() -> None:
    payload = {
        "status": "completed",
        "answer": "Goodwill impairment was 0.8%, but operating margin changed by -1.7 percentage points.",
        "task": {"task_id": "row-1"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "row-1",
        "expected_numeric": [{"name": "margin_change", "value": 1.7, "tolerance": 1.0}],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["numeric_matches"][0]["matched_value"] == 1.7


def test_finance_score_normalizes_generated_large_ratio_noise() -> None:
    payload = {
        "status": "completed",
        "answer": "The quick ratio was 0.96, calculated as (15,754 - 5,280) / 10,936.",
        "task": {"task_id": "financebench_id_00807"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_00807",
        "expected_numeric": [{"name": "quick_ratio", "value": 960_000_000.0, "tolerance": 9_600_000.0}],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    match = score["numeric_matches"][0]
    assert match["matched_value"] == 0.96
    assert match["matched_expected"] == 0.96
    assert match["expected_normalization"] == "expected_scaled_from_billions"


def test_finance_score_skips_two_digit_year_suffix_noise() -> None:
    payload = {
        "status": "completed",
        "answer": "For June 30, 2023, the quick ratio was 0.96.",
        "task": {"task_id": "financebench_id_00807", "doc_period": "2023"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_00807",
        "expected_numeric": [
            {"name": "year_suffix_noise", "value": 23.0, "tolerance": 1.0},
            {"name": "quick_ratio", "value": 0.96, "tolerance": 0.01},
        ],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["numeric_scored_count"] == 1
    assert score["numeric_unscored_count"] == 1
    assert score["numeric_matches"][0]["reason"] == "likely_year_suffix_numeric_noise"


def test_finance_score_accepts_expected_negative_bullet_rate_noise() -> None:
    payload = {
        "status": "completed",
        "answer": "The registered debt securities were 1.500% Notes due 2026 and 1.750% Notes due 2030.",
        "task": {"task_id": "financebench_id_00941"},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_00941",
        "expected_numeric": [
            {"name": "coupon_1", "value": -1.5, "tolerance": 1.0},
            {"name": "coupon_2", "value": -1.75, "tolerance": 1.0},
        ],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert all(match["expected_normalization"] == "expected_abs_magnitude" for match in score["numeric_matches"])


def test_finance_score_source_grounded_qualitative_without_expected_numeric() -> None:
    payload = {
        "status": "completed",
        "answer": (
            "Answer: The key agenda of Amcor's Form 8-K filing was Item 8.01 - Other Events, "
            "covering supplemental indentures and substitution of the issuer for the senior notes."
        ),
        "task": {"task_id": "financebench_id_01935"},
        "tool_trace_summary": {"by_tool": {"document.docling.convert": 1, "artifact.read": 1}},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_01935",
        "workflow_type": "source_grounded_research",
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings", "company_filing"]},
        "required_sources": ["8k", "sec_filings", "company_filing"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["reason"] == "source_grounded_qualitative_pass"
    assert score["numeric_scored_count"] == 0
    assert score["qualitative_score"]["scored"] is True
    assert all(check["passed"] is True for check in score["qualitative_score"]["checks"])


def test_finance_score_source_grounded_qualitative_rejects_generic_failure() -> None:
    payload = {
        "status": "completed",
        "answer": "I cannot determine the answer from the available information.",
        "task": {"task_id": "financebench_id_01935"},
        "tool_trace_summary": {"by_tool": {}},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_01935",
        "workflow_type": "source_grounded_research",
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings"]},
        "required_sources": ["8k"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is False
    assert score["reason"] == "generic_failure_final_answer"


def test_finance_score_accepts_company_earnings_press_release_as_primary_source() -> None:
    payload = {
        "status": "completed",
        "answer": (
            "Final answer: Amcor's real sales change was flat, or 0%, based on the FY2023 "
            "press release table for comparable constant currency growth."
        ),
        "task": {"task_id": "financebench_id_01930"},
        "tool_trace_summary": {
            "by_tool": {
                "document.docling.convert": 1,
                "artifact.read": 1,
                "calculator.compute": 1,
            }
        },
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_01930",
        "workflow_type": "source_grounded_research",
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings", "company_filing"]},
        "required_sources": ["earnings", "assets.ctfassets.net", "sec_filings", "company_filing"],
        "required_source_urls": ["https://assets.ctfassets.net/example/Amcor_FY23_Press_Release.pdf"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["reason"] == "source_grounded_qualitative_pass"
    checks = {check["name"]: check for check in score["qualitative_score"]["checks"]}
    assert checks["required_source_family:sec_filings"]["company_primary_source_used"] is True
    assert checks["required_doc_type_signal"]["matched_terms"] == ["earnings"]


def test_finance_score_accepts_based_on_structured_product_service_answer() -> None:
    payload = {
        "status": "completed",
        "answer": (
            "Based on AMD's FY2022 Form 10-K, here are the major products and services AMD sells:\n"
            "- Server CPUs, GPUs, DPUs, FPGAs, and Adaptive SoCs for data centers.\n"
            "- CPUs, APUs, and chipsets for desktop and notebook personal computers.\n"
            "- Discrete GPUs and semi-custom SoC products and development services.\n"
            "- Embedded CPUs, GPUs, APUs, FPGAs, and Adaptive SoC products."
        ),
        "task": {"task_id": "financebench_id_00995"},
        "tool_trace_summary": {
            "by_tool": {
                "sec.edgar.company_filings": 1,
                "document.docling.convert": 1,
                "artifact.read": 1,
            }
        },
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_00995",
        "workflow_type": "source_grounded_research",
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings", "company_filing"]},
        "required_sources": ["10k", "ir.amd.com", "sec_filings", "company_filing"],
        "required_source_urls": ["https://ir.amd.com/sec-filings/content/0000002488-23-000047/0000002488-23-000047.pdf"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["reason"] == "source_grounded_qualitative_pass"
    checks = {check["name"]: check for check in score["qualitative_score"]["checks"]}
    assert checks["synthesis_signal"]["has_direct_answer_signal"] is True


def test_finance_score_accepts_direct_yes_no_vote_table_synthesis() -> None:
    payload = {
        "status": "completed",
        "answer": (
            "**Yes, Richard A. Johnson had substantially more votes against joining the Board than all other nominees.**\n"
            "From Foot Locker's Form 8-K Item 5.07 vote table:\n"
            "| Nominee | Votes Against |\n"
            "|---|---:|\n"
            "| Richard A. Johnson | 16,105,005 |\n"
            "| Dona D. Young | 6,074,467 |\n"
            "Johnson's votes against were about 2.65x the next-highest nominee."
        ),
        "task": {"task_id": "financebench_id_00822"},
        "tool_trace_summary": {
            "by_tool": {
                "sec.edgar.company_filings": 1,
                "document.text.extract": 1,
                "artifact.read": 1,
            }
        },
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_00822",
        "workflow_type": "source_grounded_research",
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings", "company_filing"]},
        "required_sources": ["8k", "sec_filings", "company_filing"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is True
    assert score["reason"] == "source_grounded_qualitative_pass"
    checks = {check["name"]: check for check in score["qualitative_score"]["checks"]}
    assert checks["synthesis_signal"]["has_direct_answer_signal"] is True


def test_finance_score_numeric_failure_reason_takes_precedence_over_qualitative() -> None:
    payload = {
        "status": "completed",
        "answer": "",
        "task": {"task_id": "financebench_id_01079"},
        "tool_trace_summary": {"by_tool": {"document.docling.convert": 1}},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_01079",
        "workflow_type": "event_transaction",
        "dealbreakers": ["citation_required"],
        "expected_numeric": [{"name": "ownership", "value": 100.0, "tolerance": 1.0}],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is False
    assert score["reason"] == "numeric_outside_tolerance"


def test_finance_score_generic_failure_vetoes_numeric_match() -> None:
    payload = {
        "status": "completed",
        "answer": (
            "**Unable to compute the requested ratio.**\n"
            "What was missing:\n"
            "1. Net income attributable to shareholders\n"
            "2. Total cash dividends paid\n"
            "Without these values, the ratio cannot be calculated."
        ),
        "task": {"task_id": "financebench_id_10136"},
        "tool_trace_summary": {"by_tool": {"document.text.extract": 1, "calculator.compute": 1}},
        "gold_reference_material_included": False,
    }
    annotation = {
        "item_id": "financebench_id_10136",
        "workflow_type": "source_grounded_research",
        "expected_numeric": [{"name": "retention_ratio", "value": 0.54, "tolerance": 1.0}],
        "dealbreakers": ["citation_required", "synthesis_gate_pass_required"],
        "evidence_policy": {"required_source_families": ["sec_filings", "company_filing"]},
        "required_sources": ["10k", "sec_filings", "company_filing"],
    }

    score = score_run_payload(payload, annotation)

    assert score["passed"] is False
    assert score["reason"] == "generic_failure_final_answer"
    assert score["numeric_hit_count"] == 1
    checks = {check["name"]: check for check in score["qualitative_score"]["checks"]}
    assert checks["no_generic_failure"]["passed"] is False
    assert "unable to compute" in checks["no_generic_failure"]["matched_phrases"]


def test_finance_score_cli_scores_json_output_against_gold_sidecar(tmp_path) -> None:
    run_output = tmp_path / "run.json"
    gold = tmp_path / "gold.jsonl"
    score_output = tmp_path / "score.json"
    run_output.write_text(
        json.dumps(
            {
                "status": "completed",
                "answer": "The FY2018 capex amount is $1,577 million.",
                "task": {"task_id": "financebench_id_03029"},
                "gold_reference_material_included": False,
            }
        ),
        encoding="utf-8",
    )
    gold.write_text(
        json.dumps(
            {
                "item_id": "financebench_id_03029",
                "expected_numeric": [{"name": "capex", "value": 1577.0, "tolerance": 15.77}],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    code = main(["--run-output", str(run_output), "--gold-jsonl", str(gold), "--output", str(score_output)])
    payload = json.loads(score_output.read_text(encoding="utf-8"))

    assert code == 0
    assert payload["score"]["passed"] is True
    assert payload["score"]["reason"] == "numeric_within_tolerance"
