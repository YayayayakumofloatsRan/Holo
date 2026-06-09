from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace, NumericVerification
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem


NUMERIC_PATTERN = re.compile(
    r"(?P<prefix>[$€£¥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|bps|basis\s+points|million|billion|trillion|thousand|mn|bn|m|b|亿|万)?",
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
    support_values = _support_values(facts, traces)
    matched: list[JsonObject] = []
    missing: list[JsonObject] = []
    for candidate in candidates:
        match = _match_candidate(candidate, support_values)
        if match is None:
            missing.append(candidate)
        else:
            matched.append({**candidate, "support": match})
    issues: list[JsonObject] = []
    if missing:
        issues.append(
            {
                "code": "unsupported_numeric_value",
                "message": "answer contains numeric values not found in finance facts or formula traces",
                "values": missing[:16],
            }
        )
    unit_mismatches = _unit_mismatches(candidates, support_values)
    period_mismatches = _period_mismatches(answer=answer, question=question, facts=facts)
    issues.extend(unit_mismatches)
    issues.extend(period_mismatches)
    status = "passed" if matched and not missing and not unit_mismatches and not period_mismatches else "failed"
    if not support_values:
        status = "failed"
        issues.append({"code": "missing_finance_fact_ledger", "message": "no finance facts or formula traces available"})
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
            "formula_trace_count": len(traces),
            "citation_count": len(citations or []),
            "evidence_count": len(evidence or []),
        },
    )


def _answer_numeric_candidates(answer: str) -> list[JsonObject]:
    result: list[JsonObject] = []
    text = answer or ""
    for match in NUMERIC_PATTERN.finditer(text):
        if _embedded_identifier_or_citation(text, match.start(), match.end()):
            continue
        raw = match.group("number")
        unit = match.group("unit") or ""
        prefix = match.group("prefix") or ""
        value = _scaled_decimal(raw, unit)
        if value is None or _looks_like_year(value):
            continue
        if not _looks_material_numeric_claim(
            text,
            match.start(),
            match.end(),
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
        values.append(
            {
                "kind": "finance_fact",
                "ref": fact.fact_id,
                "metric": fact.metric,
                "value": _decimal_string(value),
                "unit": _normalize_unit(fact.unit or ""),
                "fiscal_year": fact.fiscal_year,
                "citation_ref": fact.citation_ref,
            }
        )
    for trace in traces:
        value = _decimal_or_none(trace.result_value)
        if value is None:
            continue
        values.append(
            {
                "kind": "formula_trace",
                "ref": trace.formula_id,
                "formula_name": trace.formula_name,
                "value": _decimal_string(value),
                "unit": _normalize_unit(trace.unit or ""),
            }
        )
        if _normalize_unit(trace.unit or "") == "percent":
            values.append(
                {
                    "kind": "formula_trace",
                    "ref": trace.formula_id,
                    "formula_name": trace.formula_name,
                    "value": _decimal_string(value * Decimal(100)),
                    "unit": "percent",
                    "derived_display_value": True,
                }
            )
    return values


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


def _embedded_identifier_or_citation(text: str, start: int, end: int) -> bool:
    before = text[max(0, start - 32) : start]
    after = text[end : min(len(text), end + 32)]
    token_start = start
    while token_start > 0 and not text[token_start - 1].isspace():
        token_start -= 1
    token_end = end
    while token_end < len(text) and not text[token_end].isspace():
        token_end += 1
    token = text[token_start:token_end].lower()
    before_token = before.strip().lower()
    if "cite-" in token or "citation-" in token or "evidence-span" in token:
        return True
    if re.search(r"(?:cite|citation|evidence|evidence-span)[-_]?$", before_token):
        return True
    prev = text[start - 1] if start > 0 else ""
    nxt = text[end] if end < len(text) else ""
    if prev in {"-", "_", "/", ":"} or nxt in {"-", "_", "/", ":"}:
        return True
    if nxt == "." and (end + 1 >= len(text) or text[end + 1].isspace()):
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start]
        if not prefix.strip():
            return True
    return False


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
