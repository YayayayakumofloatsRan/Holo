from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace, NumericVerification
from kernel_v3.finance.target_binding import filter_facts_for_target_binding, primary_source_numeric_binding_resolution
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem


NUMERIC_PATTERN = re.compile(
    r"(?P<prefix>[$€£¥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|bps|basis\s+points|million|billion|trillion|thousand|mn|bn|m|b|x|亿|万)?",
    re.IGNORECASE,
)
FY_PATTERN = re.compile(r"\b(?:FY|fiscal\s+year\s*)?(?P<year>20\d{2}|19\d{2})\b", re.IGNORECASE)
MATERIAL_NUMERIC_CONTEXT = {
    "revenue",
    "sales",
    "income",
    "profit",
    "loss",
    "eps",
    "earnings",
    "margin",
    "ratio",
    "multiple",
    "ebitda",
    "ebitdar",
    "ev/",
    "enterprise value",
    "equity value",
    "cash",
    "debt",
    "assets",
    "liabilities",
    "inventory",
    "cogs",
    "dio",
    "days inventory",
    "cagr",
    "growth",
    "bps",
    "basis point",
    "shares",
    "capex",
    "tax",
    "interest",
    "fcf",
    "irr",
    "moic",
    "市值",
    "营收",
    "收入",
    "净利润",
    "利润",
    "每股",
    "市盈率",
    "估值",
    "倍数",
    "现金",
    "债务",
    "资产",
    "负债",
    "库存",
    "毛利率",
    "增长",
}


def verify_finance_answer(
    *,
    answer: str,
    facts: list[FinanceFact],
    formula_traces: list[FormulaTrace] | None = None,
    citations: list[CitationItem] | None = None,
    evidence: list[EvidenceItem] | None = None,
    question: str = "",
    target_binding: JsonObject | None = None,
) -> NumericVerification:
    traces = list(formula_traces or [])
    candidates = _answer_numeric_candidates(answer)
    if not candidates:
        return NumericVerification(
            status="not_applicable",
            issues=[],
            matched_values=[],
            formula_traces=[item.to_dict() for item in traces],
            diagnostics={"reason": "answer_contains_no_material_numeric_values"},
        )
    binding_resolution = primary_source_numeric_binding_resolution(facts, target_binding, question=question) if target_binding else {}
    supported_facts = filter_facts_for_target_binding(facts, target_binding, question=question) if target_binding else facts
    support_values = _support_values(supported_facts, traces)
    evidence_support_values = (
        _cited_evidence_support_values(evidence or [], citations or [])
        if _source_grounded_evidence_numeric_support_allowed(question)
        else []
    )
    support_values.extend(evidence_support_values)
    matched: list[JsonObject] = []
    missing: list[JsonObject] = []
    for candidate in candidates:
        match = _match_candidate(candidate, support_values)
        if match is None:
            missing.append(candidate)
        else:
            matched.append({**candidate, "support": match})
    missing = _suppress_duplicate_display_missing(missing, matched)
    issues: list[JsonObject] = []
    if missing:
        issues.append(
            {
                "code": "unsupported_answer_number",
                "message": "answer contains numeric values not found in finance facts or formula traces",
                "values": missing[:16],
            }
        )
        if facts:
            issues.append(
                {
                    "code": "ledger_extraction_gap",
                    "message": "finance fact ledger exists but did not support every material answer number",
                    "missing_value_count": len(missing),
                    "fact_count": len(facts),
                }
            )
        if _formula_trace_required(answer=answer, question=question) and not traces:
            issues.append(
                {
                    "code": "missing_formula_trace",
                    "message": "question or answer appears to require calculation but no calculator formula trace is available",
                }
            )
    unit_mismatches = _unit_mismatches(candidates, support_values)
    period_mismatches = _period_mismatches(answer=answer, question=question, facts=facts)
    assumption_issues = _assumption_issues(answer=answer, traces=traces)
    issues.extend(unit_mismatches)
    issues.extend(period_mismatches)
    issues.extend(assumption_issues)
    status = "passed" if matched and not missing and not unit_mismatches and not period_mismatches else "failed"
    if assumption_issues:
        status = "failed"
    if not support_values:
        status = "failed"
        issues.append({"code": "missing_fact_ledger", "message": "no finance facts or formula traces available"})
    if target_binding and facts and not supported_facts:
        status = "failed"
        issues.append(
            {
                "code": "primary_source_numeric_binding_failed",
                "message": "finance facts exist, but none satisfy target document/period/source binding",
                "binding": target_binding,
                "binding_resolution": binding_resolution,
            }
        )
    return NumericVerification(
        status=status,
        issues=issues,
        matched_values=matched[:64],
        formula_traces=[item.to_dict() for item in traces],
        missing_values=missing[:64],
        unit_mismatches=unit_mismatches,
        period_mismatches=period_mismatches,
        diagnostics={
            "answer_numeric_count": len(candidates),
            "fact_count": len(facts),
            "target_bound_fact_count": len(supported_facts),
            "formula_trace_count": len(traces),
            "cited_evidence_numeric_support_count": len(evidence_support_values),
            "citation_count": len(citations or []),
            "evidence_count": len(evidence or []),
            "target_document_binding": target_binding or {},
            "primary_source_numeric_binding": binding_resolution,
        },
    )


def finance_numeric_repair_guidance(verification: NumericVerification | JsonObject) -> JsonObject:
    payload = verification.to_dict() if isinstance(verification, NumericVerification) else verification
    data = payload if isinstance(payload, dict) else {}
    issues = data.get("issues") if isinstance(data.get("issues"), list) else []
    missing_values = data.get("missing_values") if isinstance(data.get("missing_values"), list) else []
    issue_codes = _ordered_unique_text(
        [
            str(item.get("code") or item.get("reason") or "").strip()
            for item in issues
            if isinstance(item, dict)
        ]
    )[:12]
    missing_examples = _compact_missing_value_examples(missing_values)
    return {
        "schema": "holo.kernel_v3.finance_numeric_repair_guidance.v1",
        "status": _bounded_text(data.get("status"), limit=64),
        "issue_codes": issue_codes,
        "missing_value_examples": missing_examples,
        "repair_options": _verification_repair_options(issue_codes, missing_values=missing_values),
        "host_boundary": (
            "diagnostic verifier guidance only; the model still owns semantic repair, "
            "metric binding, formula intent, and final finance judgment"
        ),
    }


def _compact_missing_value_examples(values: object) -> list[JsonObject]:
    items = values if isinstance(values, list) else []
    result: list[JsonObject] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "raw": _bounded_text(item.get("raw"), limit=80),
                "value": _bounded_text(item.get("value"), limit=64),
                "unit": _bounded_text(item.get("unit"), limit=32),
                "slot": _bounded_text(item.get("slot") or item.get("metric") or item.get("name"), limit=96),
            }
        )
    return result


def _verification_repair_options(issue_codes: list[str], *, missing_values: object) -> list[str]:
    codes = {str(code or "").strip() for code in issue_codes if str(code or "").strip()}
    options: list[str] = []
    if "unsupported_answer_number" in codes:
        options.append(
            "ask synthesis to remove or replace unsupported answer numbers using only supported facts, formula traces, evidence, and citations"
        )
    if "missing_formula_trace" in codes:
        options.append("if the question requires a calculation, propose calculator.compute with model-selected fact ids and formula intent")
    if "missing_fact_ledger" in codes or "ledger_extraction_gap" in codes:
        options.append("retrieve or parse authoritative finance evidence to produce FinanceFact records before finalizing numeric claims")
    if "primary_source_numeric_binding_failed" in codes:
        options.append("inspect target document, period, source, and unit binding; retrieve the intended filing/source if existing facts bind to the wrong target")
    if any(code.endswith("_unit_mismatch") or code == "unit_mismatch" for code in codes):
        options.append("repair unit or scale wording and verify whether the value is percent, ratio, per-share, thousand, million, or billion")
    if any(code.endswith("_period_mismatch") or code == "period_mismatch" for code in codes):
        options.append("repair fiscal period binding before answering; do not mix FY, quarter, TTM, calendar year, and fiscal year values")
    if not options and missing_values:
        options.append("inspect missing numeric values and decide whether they are core claims, non-core noise, or require more evidence")
    return options[:8]


def _ordered_unique_text(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _bounded_text(value: object, *, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _answer_numeric_candidates(answer: str) -> list[JsonObject]:
    result: list[JsonObject] = []
    text = answer or ""
    for match in NUMERIC_PATTERN.finditer(text):
        number_start = match.start("number")
        number_end = match.end("number")
        raw = match.group("number")
        unit = match.group("unit") or ""
        prefix = match.group("prefix") or ""
        if _ambiguous_compact_scale_unit(text, match, raw=raw, prefix=prefix, unit=unit):
            continue
        if _embedded_identifier_or_citation(text, number_start, number_end, unit=unit):
            continue
        value = _scaled_decimal(raw, unit)
        if value is None or _looks_like_year(value):
            continue
        if _looks_like_date_component(text, number_start, number_end, value=value):
            continue
        if _looks_like_sec_item_number(text, number_start, number_end, value=value):
            continue
        if _looks_like_sec_form_code(text, number_start, number_end, value=value):
            continue
        if _looks_like_sec_exhibit_number(text, number_start, number_end, value=value):
            continue
        if _looks_like_reference_or_list_marker(
            text,
            number_start,
            number_end,
            value=value,
            unit=unit,
            prefix=prefix,
        ):
            continue
        if not _looks_material_numeric_claim(
            text,
            number_start,
            number_end,
            value=value,
            unit=unit,
            prefix=prefix,
        ):
            continue
        result.append(
            {
                "raw": match.group(0).strip(),
                "value": _decimal_string(value),
                "unit": _normalize_unit(unit or prefix),
            }
        )
    return result


def _support_values(facts: list[FinanceFact], traces: list[FormulaTrace]) -> list[JsonObject]:
    values: list[JsonObject] = []
    for fact in facts:
        value = _decimal_or_none(fact.value)
        if value is None:
            continue
        base = {
            "kind": "finance_fact",
            "ref": fact.fact_id,
            "metric": fact.metric,
            "unit": _normalize_unit(fact.unit or ""),
            "fiscal_year": fact.fiscal_year,
            "citation_ref": fact.citation_ref,
        }
        _extend_support_values(values, value, base)
    for trace in traces:
        value = _decimal_or_none(trace.result_value)
        if value is None:
            continue
        base = {
            "kind": "formula_trace",
            "ref": trace.formula_id,
            "formula_name": trace.formula_name,
            "unit": _normalize_unit(trace.unit or ""),
        }
        _extend_support_values(values, value, base)
        diagnostics = trace.diagnostics if isinstance(trace.diagnostics, dict) else {}
        variables = diagnostics.get("variables")
        if isinstance(variables, dict):
            for name, raw_value in variables.items():
                variable_value = _decimal_or_none(raw_value)
                if variable_value is None:
                    continue
                _extend_support_values(
                    values,
                    variable_value,
                    {
                        "kind": "formula_variable",
                        "ref": trace.formula_id,
                        "formula_name": trace.formula_name,
                        "variable": str(name),
                        "unit": _formula_variable_unit(str(name), trace),
                    },
                )
            average_inventory = _average_variable(variables, "inventory_begin", "inventory_end")
            if average_inventory is not None:
                _extend_support_values(
                    values,
                    average_inventory,
                    {
                        "kind": "formula_intermediate",
                        "ref": trace.formula_id,
                        "formula_name": trace.formula_name,
                        "variable": "average_inventory",
                        "unit": "",
                    },
                )
        if "/" in str(trace.expression or ""):
            values.append(
                {
                    "kind": "formula_constant",
                    "ref": trace.formula_id,
                    "formula_name": trace.formula_name,
                    "value": "2",
                    "unit": "",
                }
            )
        model_outputs = diagnostics.get("model_outputs")
        if isinstance(model_outputs, dict):
            for item in _model_output_support_values(model_outputs, trace=trace):
                _extend_support_values(values, item["value"], item["base"])
        assumptions = diagnostics.get("assumptions")
        if isinstance(assumptions, dict):
            for item in _formula_assumption_support_values(assumptions, trace=trace):
                _extend_support_values(values, item["value"], item["base"])
    values.extend(_formula_comparison_support_values(traces))
    return values


def _cited_evidence_support_values(evidence: list[EvidenceItem], citations: list[CitationItem]) -> list[JsonObject]:
    citation_by_evidence = {item.evidence_id: item for item in citations if item.evidence_id}
    values: list[JsonObject] = []
    for item in evidence:
        citation = citation_by_evidence.get(item.evidence_id)
        if citation is None:
            continue
        for numeric in _numeric_values_from_cited_text(item.text):
            _extend_support_values(
                values,
                numeric["value"],
                {
                    "kind": "cited_evidence",
                    "ref": item.evidence_id,
                    "citation_ref": citation.citation_id,
                    "unit": numeric["unit"],
                },
            )
    return values


def _numeric_values_from_cited_text(text: str) -> list[JsonObject]:
    result: list[JsonObject] = []
    source = str(text or "")
    for match in NUMERIC_PATTERN.finditer(source):
        number_start = match.start("number")
        number_end = match.end("number")
        raw = match.group("number")
        unit = match.group("unit") or ""
        prefix = match.group("prefix") or ""
        if _ambiguous_compact_scale_unit(source, match, raw=raw, prefix=prefix, unit=unit):
            continue
        if _embedded_identifier_or_citation(source, number_start, number_end, unit=unit):
            continue
        value = _scaled_decimal(raw, unit)
        if value is None or _looks_like_year(value):
            continue
        if _looks_like_date_component(source, number_start, number_end, value=value):
            continue
        if _looks_like_sec_item_number(source, number_start, number_end, value=value):
            continue
        if _looks_like_sec_form_code(source, number_start, number_end, value=value):
            continue
        if _looks_like_sec_exhibit_number(source, number_start, number_end, value=value):
            continue
        if _looks_like_reference_or_list_marker(source, number_start, number_end, value=value, unit=unit, prefix=prefix):
            continue
        result.append({"value": value, "unit": _normalize_unit(unit or prefix)})
    return result


def _formula_assumption_support_values(assumptions: JsonObject, *, trace: FormulaTrace) -> list[JsonObject]:
    values: list[JsonObject] = []
    for path, raw_value in _iter_model_output_numbers(assumptions):
        value = _decimal_or_none(raw_value)
        if value is None:
            continue
        values.append(
            {
                "value": value,
                "base": {
                    "kind": "formula_assumption",
                    "ref": trace.formula_id,
                    "formula_name": trace.formula_name,
                    "assumption": path,
                    "unit": _model_output_unit(path, trace),
                },
            }
        )
    return values


def _model_output_support_values(model_outputs: JsonObject, *, trace: FormulaTrace) -> list[JsonObject]:
    values: list[JsonObject] = []
    for path, raw_value in _iter_model_output_numbers(model_outputs):
        value = _decimal_or_none(raw_value)
        if value is None:
            continue
        values.append(
            {
                "value": value,
                "base": {
                    "kind": "formula_model_output",
                    "ref": trace.formula_id,
                    "formula_name": trace.formula_name,
                    "model_output": path,
                    "unit": _model_output_unit(path, trace),
                },
            }
        )
    return values


def _iter_model_output_numbers(value: object, *, prefix: str = "") -> list[tuple[str, object]]:
    if isinstance(value, dict):
        result: list[tuple[str, object]] = []
        for key, item in value.items():
            name = str(key)
            path = f"{prefix}.{name}" if prefix else name
            if name.lower() in {"year"}:
                continue
            result.extend(_iter_model_output_numbers(item, prefix=path))
        return result
    if isinstance(value, list):
        result: list[tuple[str, object]] = []
        for index, item in enumerate(value, start=1):
            result.extend(_iter_model_output_numbers(item, prefix=f"{prefix}[{index}]"))
        return result
    return [(prefix, value)] if _decimal_or_none(value) is not None else []


def _model_output_unit(path: str, trace: FormulaTrace) -> str:
    normalized = str(path or "").lower()
    if any(marker in normalized for marker in ("irr", "growth", "rate", "margin", "_to_", "return_on_assets")):
        return "percent"
    if any(marker in normalized for marker in ("multiple", "moic", "discount_factor")):
        return "x"
    if any(
        marker in normalized
        for marker in (
            "cash_flow",
            "free_cash_flow",
            "present_value",
            "terminal_value",
            "enterprise_value",
            "equity_value",
            "debt",
            "cash",
            "investments",
            "ebitda",
            "sponsor_equity",
        )
    ):
        return "usd/share" if "per_share" in normalized else "usd"
    return _normalize_unit(trace.unit or "")


def _suppress_duplicate_display_missing(missing: list[JsonObject], matched: list[JsonObject]) -> list[JsonObject]:
    if not missing or not matched:
        return missing
    matched_raws = [str(item.get("raw") or "") for item in matched]
    result: list[JsonObject] = []
    for item in missing:
        raw = str(item.get("raw") or "").strip()
        value = _decimal_or_none(item.get("value"))
        if not raw or value is None:
            result.append(item)
            continue
        duplicate = False
        for matched_item, matched_raw in zip(matched, matched_raws):
            matched_value = _decimal_or_none(matched_item.get("value"))
            if matched_value is None or not _within_tolerance(value, matched_value):
                continue
            if raw != matched_raw and raw in matched_raw:
                duplicate = True
                break
        if not duplicate:
            result.append(item)
    return result


def _formula_comparison_support_values(traces: list[FormulaTrace]) -> list[JsonObject]:
    values: list[JsonObject] = []
    usable: list[tuple[FormulaTrace, Decimal]] = []
    for trace in traces:
        value = _decimal_or_none(trace.result_value)
        if value is not None:
            usable.append((trace, value))
    for left_index, (left, left_value) in enumerate(usable):
        for right, right_value in usable[left_index + 1 :]:
            if str(left.formula_name or "") != str(right.formula_name or ""):
                continue
            left_unit = _normalize_unit(left.unit or "")
            right_unit = _normalize_unit(right.unit or "")
            if left_unit != right_unit:
                continue
            values.extend(
                _display_support_values(
                    left_value - right_value,
                    {
                        "kind": "formula_comparison",
                        "ref": f"{left.formula_id}:{right.formula_id}:difference",
                        "formula_name": left.formula_name,
                        "unit": left_unit,
                        "comparison": "left_minus_right",
                    },
                )
            )
            values.extend(
                _display_support_values(
                    right_value - left_value,
                    {
                        "kind": "formula_comparison",
                        "ref": f"{right.formula_id}:{left.formula_id}:difference",
                        "formula_name": left.formula_name,
                        "unit": left_unit,
                        "comparison": "right_minus_left",
                    },
                )
            )
    return values


def _formula_variable_unit(name: str, trace: FormulaTrace) -> str:
    normalized = str(name or "").lower()
    if normalized in {"fiscal_days"}:
        return "days"
    if normalized in {
        "equity_value",
        "enterprise_value",
        "market_cap",
        "debt",
        "cash",
        "investments",
        "revenue",
        "beginning_value",
        "ending_value",
        "numerator",
        "denominator",
        "base",
    } or normalized.startswith(("addback_", "deduction_")):
        return "usd"
    if any(
        marker in normalized
        for marker in (
            "asset",
            "capex",
            "capital_expenditure",
            "cash_flow",
            "net_income",
            "ocf",
            "operating_cash",
            "ppe",
            "ppne",
            "property_plant",
        )
    ):
        return "usd"
    if "inventory" in normalized or normalized in {"cogs", "prior_value", "current_value"}:
        return "usd"
    if "rate" in normalized or "margin" in normalized:
        return "percent"
    return _normalize_unit(trace.unit or "")


def _display_support_values(value: Decimal, base: JsonObject) -> list[JsonObject]:
    values: list[JsonObject] = [{**base, "value": _decimal_string(value)}]
    if value < 0:
        values.append({**base, "value": _decimal_string(abs(value)), "absolute_display_value": True})
    scale_candidates = (
        ("thousand", Decimal(1_000)),
        ("million", Decimal(1_000_000)),
        ("billion", Decimal(1_000_000_000)),
        ("trillion", Decimal(1_000_000_000_000)),
        ("hundred_million", Decimal(100_000_000)),
        ("ten_thousand", Decimal(10_000)),
    )
    for scale, divisor in scale_candidates:
        if abs(value) < divisor:
            continue
        scaled = value / divisor
        values.append(
            {
                **base,
                "value": _decimal_string(scaled),
                "unit": scale,
                "derived_display_value": True,
                "scale_divisor": _decimal_string(divisor),
            }
        )
        if value < 0:
            values.append(
                {
                    **base,
                    "value": _decimal_string(abs(scaled)),
                    "unit": scale,
                    "derived_display_value": True,
                    "absolute_display_value": True,
                    "scale_divisor": _decimal_string(divisor),
                }
            )
    return values


def _extend_support_values(values: list[JsonObject], value: Decimal, base: JsonObject) -> None:
    values.extend(_display_support_values(value, base))
    if _normalize_unit(str(base.get("unit") or "")) == "percent":
        percent_value = value * Decimal(100)
        values.append(
            {
                **base,
                "value": _decimal_string(percent_value),
                "unit": "percent",
                "derived_display_value": True,
            }
        )
        if percent_value < 0:
            values.append(
                {
                    **base,
                    "value": _decimal_string(abs(percent_value)),
                    "unit": "percent",
                    "derived_display_value": True,
                    "absolute_display_value": True,
                }
            )


def _match_candidate(candidate: JsonObject, support_values: list[JsonObject]) -> JsonObject | None:
    candidate_value = _decimal_or_none(candidate.get("value"))
    if candidate_value is None:
        return None
    for support in support_values:
        support_value = _decimal_or_none(support.get("value"))
        if support_value is None:
            continue
        if _within_tolerance(candidate_value, support_value):
            return support
    return None


def _within_tolerance(left: Decimal, right: Decimal) -> bool:
    tolerance = max(abs(right) * Decimal("0.005"), Decimal("0.000001"))
    return abs(left - right) <= tolerance


def _unit_mismatches(candidates: list[JsonObject], support_values: list[JsonObject]) -> list[JsonObject]:
    issues: list[JsonObject] = []
    for candidate in candidates:
        candidate_value = _decimal_or_none(candidate.get("value"))
        candidate_unit = str(candidate.get("unit") or "")
        if candidate_value is None or not candidate_unit:
            continue
        nearby = []
        for support in support_values:
            support_value = _decimal_or_none(support.get("value"))
            if support_value is None or not _within_tolerance(candidate_value, support_value):
                continue
            nearby.append(support)
        if nearby and not any(_units_compatible(candidate_unit, str(item.get("unit") or "")) for item in nearby):
            issues.append(
                {
                    "code": "unit_mismatch",
                    "value": candidate,
                    "support_units": sorted({str(item.get("unit") or "") for item in nearby}),
                }
            )
    return issues


def _period_mismatches(*, answer: str, question: str, facts: list[FinanceFact]) -> list[JsonObject]:
    fact_years = {fact.fiscal_year for fact in facts if isinstance(fact.fiscal_year, int)}
    if not fact_years:
        return []
    answer_years = {int(match.group("year")) for match in FY_PATTERN.finditer(answer or "")}
    question_years = {int(match.group("year")) for match in FY_PATTERN.finditer(question or "")}
    relevant_answer_years = answer_years & (question_years or answer_years)
    if relevant_answer_years and not (relevant_answer_years & fact_years):
        return [
            {
                "code": "period_mismatch",
                "answer_years": sorted(relevant_answer_years),
                "fact_years": sorted(fact_years),
            }
        ]
    return []


def _formula_trace_required(*, answer: str, question: str) -> bool:
    text = f"{question}\n{answer}".lower()
    if _source_grounded_evidence_numeric_support_allowed(question):
        return False
    return any(
        marker in text
        for marker in (
            "calculate",
            "computed",
            "cagr",
            "dio",
            "days inventory",
            "ev/revenue",
            "ev / revenue",
            "multiple",
            "margin",
            "bps",
            "basis point",
            "growth",
            "bridge",
            "dcf",
            "lbo",
            "计算",
            "增长率",
            "利润率",
            "倍数",
        )
    )


def _source_grounded_evidence_numeric_support_allowed(question: str) -> bool:
    text = str(question or "").lower()
    if not _source_grounded_explanation_intent(text):
        return False
    return not _explicit_calculation_intent(text)


def _source_grounded_explanation_intent(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "what drove",
            "what drives",
            "why did",
            "explain why",
            "explain the",
            "drivers of",
            "driver of",
            "main reasons",
            "primary reasons",
            "主要原因",
            "驱动因素",
            "为什么",
        )
    )


def _explicit_calculation_intent(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "calculate",
            "compute",
            "quantify",
            "what is the amount",
            "how much",
            "ratio",
            "multiple",
            "cagr",
            "dio",
            "ev/",
            "basis point",
            "bps",
            "计算",
            "量化",
            "是多少",
        )
    )


def _assumption_issues(*, answer: str, traces: list[FormulaTrace]) -> list[JsonObject]:
    answer_text = str(answer or "").lower()
    if not traces:
        return []
    trace_text = " ".join(str(trace.diagnostics or {}).lower() for trace in traces)
    if "assumption" not in trace_text and "assumed" not in trace_text:
        return []
    if any(marker in answer_text for marker in ("assumption", "assume", "assumed", "假设", "假定")):
        return []
    return [
        {
            "code": "assumption_not_labeled",
            "message": "calculator formula trace includes an assumption that is not labeled in the answer",
        }
    ]


def _scaled_decimal(raw: str, unit: str) -> Decimal | None:
    value = _decimal_or_none(str(raw).replace(",", ""))
    if value is None:
        return None
    normalized = _normalize_unit(unit)
    if normalized == "thousand":
        return value * Decimal(1_000)
    if normalized == "million":
        return value * Decimal(1_000_000)
    if normalized == "billion":
        return value * Decimal(1_000_000_000)
    if normalized == "trillion":
        return value * Decimal(1_000_000_000_000)
    if normalized == "hundred_million":
        return value * Decimal(100_000_000)
    if normalized == "ten_thousand":
        return value * Decimal(10_000)
    return value


def _ambiguous_compact_scale_unit(text: str, match: re.Match[str], *, raw: str, prefix: str, unit: str) -> bool:
    normalized = _normalize_unit(unit)
    if normalized not in {"million", "billion"} or unit.lower() not in {"m", "b"} or prefix:
        return False
    unit_start = match.start("unit")
    if unit_start < 0:
        return False
    separator = text[match.end("number") : unit_start]
    if separator:
        return False
    if "." in raw:
        return False
    # Bare compact tokens such as "3M" are often company names, tickers,
    # product labels, or identifiers. Explicit currency/decimal/word-scale
    # forms remain material numeric candidates.
    return True


def _normalize_unit(unit: str) -> str:
    text = " ".join(str(unit or "").strip().lower().split())
    if "usd" in text or text in {"$", "us$"}:
        return "usd"
    if text in {"€", "eur"}:
        return "eur"
    if text in {"£", "gbp"}:
        return "gbp"
    if text in {"¥", "cny", "rmb"}:
        return "cny"
    if text in {"%", "percent", "percentage"}:
        return "percent"
    if text in {"bps", "bp", "basis point", "basis points"}:
        return "bps"
    if text in {"m", "mn", "million"}:
        return "million"
    if text in {"b", "bn", "billion"}:
        return "billion"
    if text == "trillion":
        return "trillion"
    if text == "thousand":
        return "thousand"
    if text == "亿":
        return "hundred_million"
    if text == "万":
        return "ten_thousand"
    return text


def _units_compatible(left: str, right: str) -> bool:
    if not left or not right:
        return True
    if left == right:
        return True
    monetary_or_scale = {"usd", "eur", "gbp", "cny", "million", "billion", "trillion", "thousand", "hundred_million", "ten_thousand"}
    if left in monetary_or_scale and right in monetary_or_scale:
        return True
    return False


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _looks_like_year(value: Decimal) -> bool:
    return value == value.to_integral_value() and Decimal(1900) <= value <= Decimal(2100)


def _looks_like_date_component(text: str, start: int, end: int, *, value: Decimal) -> bool:
    if value != value.to_integral_value() or value < 1 or value > 31:
        return False
    window = text[max(0, start - 32) : min(len(text), end + 32)].lower()
    if re.search(
        r"\b(?:jan|january|feb|february|mar|march|apr|april|may|jun|june|jul|july|aug|august|sep|sept|september|oct|october|nov|november|dec|december)\b",
        window,
    ):
        return True
    if "月" in window or "日" in window:
        return True
    if re.search(r"\b20\d{2}\s*[-/年]\s*\d{1,2}\s*[-/月]\s*\d{1,2}", window):
        return True
    return False


def _looks_like_sec_item_number(text: str, start: int, end: int, *, value: Decimal) -> bool:
    """SEC filing item codes are not finance values and should not gate answers."""

    if value <= 0 or value >= 20:
        return False
    before = text[max(0, start - 24) : start].lower()
    after = text[end : min(len(text), end + 24)].lower()
    window = f"{before}{text[start:end]}{after}"
    if re.search(r"\bitem\s*$", before):
        return True
    if re.search(r"\bitem\s+\d{1,2}(?:\.\d{1,2})?\b", window):
        return True
    if re.search(r"\b(?:form\s*)?8-k\b", window) and re.search(r"\b\d{1,2}\.\d{1,2}\b", window):
        return True
    if "sec" in window and "item" in window and re.search(r"\b\d{1,2}\.\d{1,2}\b", window):
        return True
    return False


def _looks_like_sec_form_code(text: str, start: int, end: int, *, value: Decimal) -> bool:
    """SEC form numbers such as 8-K and 10-Q are document identifiers."""

    if value != value.to_integral_value() or value <= 0 or value > 40:
        return False
    window = text[max(0, start - 24) : min(len(text), end + 24)].lower()
    form_pattern = r"\b(?:form\s*)?(?:6|8|10|20|40)\s*[-‑–—]\s*(?:k|q|f)\b"
    return bool(re.search(form_pattern, window))


def _looks_like_sec_exhibit_number(text: str, start: int, end: int, *, value: Decimal) -> bool:
    """Exhibit numbers such as Exhibit 99.1 are document identifiers."""

    if value <= 0 or value >= 200:
        return False
    before = text[max(0, start - 24) : start].lower()
    after = text[end : min(len(text), end + 24)].lower()
    window = f"{before}{text[start:end]}{after}"
    if re.search(r"\b(?:exhibit|ex)\s*[-:]?\s*$", before):
        return True
    if re.search(r"\b(?:exhibit|ex)\s*[-:]?\s*\d{1,3}(?:\.\d{1,3})?\b", window):
        return True
    return False


def _looks_like_reference_or_list_marker(
    text: str,
    start: int,
    end: int,
    *,
    value: Decimal,
    unit: str,
    prefix: str,
) -> bool:
    """Ignore structural one-digit markers without weakening material numbers."""

    if unit or prefix:
        return False
    if value != value.to_integral_value() or value < 1 or value > 9:
        return False

    prev = text[start - 1] if start > 0 else ""
    nxt = text[end] if end < len(text) else ""
    if prev in {"[", "(", "（", "【"} and nxt in {"]", ")", "）", "】"}:
        return True

    line_start = text.rfind("\n", 0, start) + 1
    line_prefix = text[line_start:start]
    if nxt in {".", "、", ")"} and line_prefix.strip() in {"", "-", "*"}:
        return True

    before = text[max(0, start - 32) : start].lower()
    after = text[end : min(len(text), end + 32)].lower()
    window = f"{before}{text[start:end]}{after}"
    if re.search(r"(?:cite|citation|source|ref|reference|evidence|引用|来源|证据)\s*[:#\[（(]*\s*$", before):
        return True
    if re.search(r"^\s*[\]）)]", after) and any(
        marker in before for marker in ("cite", "citation", "source", "ref", "引用", "来源", "证据")
    ):
        return True
    if "trace_refs" in window or "citation" in window or "evidence" in window:
        return True
    return False


def _embedded_identifier_or_citation(text: str, start: int, end: int, *, unit: str = "") -> bool:
    before = text[max(0, start - 32) : start]
    after = text[end : min(len(text), end + 32)]
    if _inside_inline_formula_or_code_span(text, start, end):
        return True
    if _inside_reference_bracket(text, start, end):
        return True
    token_start = start
    while token_start > 0 and not _identifier_token_boundary(text[token_start - 1]):
        token_start -= 1
    token_end = end
    while token_end < len(text) and not _identifier_token_boundary(text[token_end]):
        token_end += 1
    token = text[token_start:token_end].lower()
    before_token = before.strip().lower()
    identifier_window = text[max(0, start - 48) : min(len(text), end + 48)].lower()
    if "cite-" in token or "citation-" in token or "evidence-span" in token:
        return True
    if re.search(r"\b(?:cite|citation|evidence|source|ref)[-_][a-z0-9][a-z0-9_.:-]*\b", token):
        return True
    if re.search(r"(?:cite|citation|evidence|evidence-span)[-_]?$", before_token):
        return True
    if re.search(r"\b\d{6,}-\d{2}-\d{3,}\b", token) or re.search(r"\b\d{6,}-\d{2}-\d{3,}\b", identifier_window):
        return True
    if re.search(r"(?:accn|accession|cik|filename|file|document|submission)[=:\s_-]*$", before_token):
        return True
    if any(marker in token for marker in (".htm", ".html", ".json", ".txt", ".pdf")):
        return True
    prev = text[start - 1] if start > 0 else ""
    nxt = text[end] if end < len(text) else ""
    if (prev.isascii() and prev.isalpha()) or (nxt.isascii() and nxt.isalpha() and not unit):
        return True
    if prev in {"-", "_", "/", ":"} or nxt in {"-", "_", "/", ":"}:
        return True
    if nxt == "." and (end + 1 >= len(text) or text[end + 1].isspace()):
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start]
        if not prefix.strip():
            return True
    return False


def _inside_inline_formula_or_code_span(text: str, start: int, end: int) -> bool:
    open_index = text.rfind("`", 0, start)
    if open_index < 0:
        return False
    close_index = text.find("`", end)
    if close_index < 0 or close_index - open_index > 240:
        return False
    inner = text[open_index + 1 : close_index].strip()
    if not inner:
        return False
    if re.fullmatch(r"[-+]?\d+(?:,\d{3})*(?:\.\d+)?\s*%?", inner):
        return False
    return bool(re.search(r"[A-Za-z_]", inner) and re.search(r"[+\-*/=^]", inner))


def _inside_reference_bracket(text: str, start: int, end: int) -> bool:
    brackets = (("[", "]"), ("【", "】"), ("(", ")"), ("（", "）"))
    for left, right in brackets:
        open_index = text.rfind(left, 0, start)
        if open_index < 0:
            continue
        close_index = text.find(right, end)
        if close_index < 0 or close_index - open_index > 160:
            continue
        inner = text[open_index + 1 : close_index].lower()
        if any(marker in inner for marker in ("cite", "citation", "evidence", "source", "ref", "引用", "来源", "证据")):
            return True
    return False


def _identifier_token_boundary(char: str) -> bool:
    if char.isspace():
        return True
    return char in {"[", "]", "(", ")", "（", "）", "【", "】", "{", "}", "，", "。", ",", ";", "；", "："}


def _looks_material_numeric_claim(
    text: str,
    start: int,
    end: int,
    *,
    value: Decimal,
    unit: str,
    prefix: str,
) -> bool:
    if unit or prefix:
        return True
    if abs(value) >= Decimal(1_000):
        return True
    window = text[max(0, start - 80) : min(len(text), end + 80)].lower()
    return any(marker in window for marker in MATERIAL_NUMERIC_CONTEXT)


def _decimal_string(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _average_variable(variables: JsonObject, left: str, right: str) -> Decimal | None:
    left_value = _decimal_or_none(variables.get(left))
    right_value = _decimal_or_none(variables.get(right))
    if left_value is None or right_value is None:
        return None
    return (left_value + right_value) / Decimal(2)
