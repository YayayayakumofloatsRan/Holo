from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace


FormulaPlanStatus = Literal["ready", "missing_facts", "not_applicable"]


@dataclass(frozen=True, kw_only=True)
class FinanceFormulaPlan(Contract):
    status: FormulaPlanStatus
    formula_name: str | None = None
    payload: JsonObject | None = None
    missing_facts: list[str] = field(default_factory=list)
    input_fact_ids: list[str] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)


def plan_finance_formula(
    *,
    question: str,
    facts: list[FinanceFact],
    existing_traces: list[FormulaTrace] | None = None,
) -> FinanceFormulaPlan:
    _ = existing_traces
    formula = _detect_formula(question)
    if formula is None:
        return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "no_supported_formula_intent"})
    usable = [fact for fact in facts if _decimal_or_none(fact.value) is not None]
    if formula == "cagr":
        return _plan_cagr(usable)
    if formula == "margin":
        return _plan_margin(usable)
    if formula == "bps_difference":
        return _plan_bps_difference(usable)
    if formula == "ev_revenue":
        return _plan_ev_revenue(usable)
    if formula == "ev_ebitda":
        return _plan_ev_ebitda(usable)
    if formula == "dio":
        return _plan_dio(question=question, facts=usable)
    if formula == "yoy_growth":
        return _plan_yoy_growth(usable)
    if formula == "bridge_subtotal":
        return _plan_bridge_subtotal(usable)
    return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "unsupported_formula", "formula": formula})


def _detect_formula(question: str) -> str | None:
    text = str(question or "").lower()
    compact = text.replace(" ", "")
    if "cagr" in text or "compound annual growth" in text:
        return "cagr"
    if "dio" in text or "days inventory" in text or "days inventory outstanding" in text:
        return "dio"
    if "ev/revenue" in compact or "ev/rev" in compact or "enterprise value to revenue" in text:
        return "ev_revenue"
    if "ev/ebitda" in compact or "enterprise value to ebitda" in text:
        return "ev_ebitda"
    if "basis point" in text or "bps" in text:
        return "bps_difference"
    if "bridge" in text or "add-back" in text or "add back" in text or "addback" in text:
        return "bridge_subtotal"
    if "yoy" in text or "year-over-year" in text or "year over year" in text:
        return "yoy_growth"
    if "margin" in text or "利润率" in text:
        return "margin"
    if "growth" in text or "增长率" in text:
        return "yoy_growth"
    return None


def _plan_cagr(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    pair = _first_metric_pair(facts, ("revenue", "net sales", "net revenues", "total revenues", "sales"))
    if pair is None:
        return _missing("cagr", ["beginning_revenue", "ending_revenue"])
    beginning, ending = pair
    years = _year_span(beginning, ending)
    if years <= 0:
        return _missing("cagr", ["positive_year_span"], facts=[beginning, ending])
    return _ready(
        "cagr",
        "(ending_value / beginning_value) ** (1 / years) - 1",
        {
            "beginning_value": beginning.value,
            "ending_value": ending.value,
            "years": years,
        },
        unit="percent",
        facts=[beginning, ending],
    )


def _plan_yoy_growth(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    pair = _first_metric_pair(facts, ("revenue", "net sales", "net income", "operating income", "ebitda"))
    if pair is None:
        return _missing("yoy_growth", ["prior_period_value", "current_period_value"])
    prior, current = pair
    return _ready(
        "yoy_growth",
        "current_value / prior_value - 1",
        {"prior_value": prior.value, "current_value": current.value},
        unit="percent",
        facts=[prior, current],
    )


def _plan_margin(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    numerator = _latest_fact(facts, ("net income", "operating income", "adjusted ebitda", "ebitda"))
    denominator = _latest_fact(facts, ("revenue", "net sales", "net revenues", "total revenues", "sales"))
    missing = []
    if numerator is None:
        missing.append("margin_numerator")
    if denominator is None:
        missing.append("revenue_denominator")
    if missing:
        return _missing("margin", missing, facts=[item for item in (numerator, denominator) if item is not None])
    return _ready(
        "margin",
        "numerator / denominator",
        {"numerator": numerator.value, "denominator": denominator.value},
        unit="percent",
        facts=[numerator, denominator],
    )


def _plan_bps_difference(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    pair = _first_metric_pair(facts, ("margin", "rate", "yield"))
    if pair is None:
        return _missing("bps_difference", ["prior_rate_or_margin", "current_rate_or_margin"])
    prior, current = pair
    return _ready(
        "bps_difference",
        "(current_rate - prior_rate) * 10000",
        {"prior_rate": _ratio_value(prior), "current_rate": _ratio_value(current)},
        unit="bps",
        facts=[prior, current],
    )


def _plan_ev_revenue(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    equity_candidates = [
        fact
        for fact in facts
        if _metric_text(fact.metric)
        in {
            "equity value",
            "market cap",
            "market capitalization",
            "enterprise value",
            "transaction value",
            "deal value",
            "purchase price",
            "consideration paid",
            "purchase consideration",
            "fair value of consideration",
        }
    ]
    per_share_consideration = [
        fact for fact in equity_candidates if _is_per_share_fact(fact) or _looks_like_unscaled_equity_quote(fact)
    ]
    equity = _latest_fact(
        facts,
        (
            "equity value",
            "market cap",
            "market capitalization",
            "enterprise value",
            "transaction value",
            "deal value",
            "purchase price",
            "consideration paid",
            "purchase consideration",
            "fair value of consideration",
        ),
        exclude_fact_ids={fact.fact_id for fact in per_share_consideration},
    )
    debt = _latest_fact(facts, ("debt", "long term debt", "short term debt"))
    cash = _latest_fact(facts, ("cash", "cash and equivalents", "cash and cash equivalents"))
    investments = _latest_fact(facts, ("short-term investments", "short term investments"))
    revenue = _latest_fact(facts, ("revenue", "net sales", "net revenues", "total revenues", "sales"))
    missing = []
    if equity is None:
        if per_share_consideration:
            missing.append("shares_outstanding_or_transaction_value")
        else:
            missing.append("equity_value_or_market_cap")
    if debt is None and not _transaction_value_already_enterprise_value(equity):
        missing.append("debt")
    if cash is None and not _transaction_value_already_enterprise_value(equity):
        missing.append("cash")
    if revenue is None:
        missing.append("revenue")
    if missing:
        return _missing("ev_revenue", missing, facts=[item for item in (equity, debt, cash, investments, revenue) if item is not None])
    variables: JsonObject = {
        "equity_value": equity.value,
        "debt": debt.value if debt is not None else "0",
        "cash": cash.value if cash is not None else "0",
        "revenue": revenue.value,
        "investments": investments.value if investments is not None else "0",
    }
    return _ready(
        "ev_revenue",
        "(equity_value + debt - cash - investments) / revenue",
        variables,
        unit="x",
        facts=[item for item in (equity, debt, cash, investments, revenue) if item is not None],
    )


def _plan_ev_ebitda(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    ev_inputs = _enterprise_value_inputs(facts)
    ebitda = _latest_fact(facts, ("adjusted ebitda", "ebitda"))
    ebitda_components = _ebitda_component_inputs(facts) if ebitda is None else {}
    missing = list(ev_inputs["missing"])
    if ebitda is None and not ebitda_components:
        missing.append("ebitda_or_ebitda_components")
    if missing:
        return _missing(
            "ev_ebitda",
            missing,
            facts=[
                item
                for item in (
                    ev_inputs.get("equity"),
                    ev_inputs.get("debt"),
                    ev_inputs.get("cash"),
                    ev_inputs.get("investments"),
                    ebitda,
                    *ebitda_components.values(),
                )
                if isinstance(item, FinanceFact)
            ],
        )
    variables: JsonObject = dict(ev_inputs["variables"])
    input_facts = list(ev_inputs["facts"])
    if ebitda is not None:
        variables["ebitda"] = ebitda.value
        input_facts.append(ebitda)
        denominator = "ebitda"
    else:
        for name, fact in ebitda_components.items():
            variables[name] = fact.value
            input_facts.append(fact)
        denominator = "(net_income + interest_expense + tax_expense + depreciation_amortization)"
    return _ready(
        "ev_ebitda",
        f"(equity_value + debt - cash - investments) / {denominator}",
        variables,
        unit="x",
        facts=input_facts,
        diagnostics={
            "enterprise_value_source": ev_inputs["source"],
            "ebitda_source": "direct" if ebitda is not None else "derived_from_components",
        },
    )


def _enterprise_value_inputs(facts: list[FinanceFact]) -> JsonObject:
    equity_candidates = [
        fact
        for fact in facts
        if _metric_text(fact.metric)
        in {
            "equity value",
            "market cap",
            "market capitalization",
            "enterprise value",
            "transaction value",
            "deal value",
            "purchase price",
            "consideration paid",
            "purchase consideration",
            "fair value of consideration",
        }
    ]
    per_share_consideration = [
        fact for fact in equity_candidates if _is_per_share_fact(fact) or _looks_like_unscaled_equity_quote(fact)
    ]
    equity = _latest_fact(
        facts,
        (
            "equity value",
            "market cap",
            "market capitalization",
            "enterprise value",
            "transaction value",
            "deal value",
            "purchase price",
            "consideration paid",
            "purchase consideration",
            "fair value of consideration",
        ),
        exclude_fact_ids={fact.fact_id for fact in per_share_consideration},
    )
    debt = _latest_fact(facts, ("debt", "long term debt", "short term debt"))
    cash = _latest_fact(facts, ("cash", "cash and equivalents", "cash and cash equivalents"))
    investments = _latest_fact(facts, ("short-term investments", "short term investments"))
    missing = []
    if equity is None:
        if per_share_consideration:
            missing.append("shares_outstanding_or_enterprise_value")
        else:
            missing.append("enterprise_value_or_market_cap")
    enterprise_value_source = "enterprise_value" if _transaction_value_already_enterprise_value(equity) else "equity_value_adjusted"
    if debt is None and enterprise_value_source != "enterprise_value":
        missing.append("debt")
    if cash is None and enterprise_value_source != "enterprise_value":
        missing.append("cash")
    variables: JsonObject = {
        "equity_value": equity.value if equity is not None else "0",
        "debt": debt.value if debt is not None else "0",
        "cash": cash.value if cash is not None else "0",
        "investments": investments.value if investments is not None else "0",
    }
    return {
        "equity": equity,
        "debt": debt,
        "cash": cash,
        "investments": investments,
        "variables": variables,
        "missing": missing,
        "source": enterprise_value_source,
        "facts": [item for item in (equity, debt, cash, investments) if item is not None],
    }


def _ebitda_component_inputs(facts: list[FinanceFact]) -> dict[str, FinanceFact]:
    net_income = _latest_fact(facts, ("net income",))
    interest = _latest_fact(facts, ("interest expense", "net interest income"))
    tax = _latest_fact(facts, ("tax", "income tax expense"))
    depreciation = _latest_fact(facts, ("depreciation and amortization", "d&a"))
    if not all((net_income, interest, tax, depreciation)):
        return {}
    return {
        "net_income": net_income,
        "interest_expense": interest,
        "tax_expense": tax,
        "depreciation_amortization": depreciation,
    }


def _is_per_share_fact(fact: FinanceFact) -> bool:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    return metadata.get("per_share") is True


def _looks_like_unscaled_equity_quote(fact: FinanceFact) -> bool:
    metric = _metric_text(fact.metric)
    if metric not in {"equity value", "market cap", "market capitalization", "enterprise value"}:
        return False
    value = _decimal_or_none(fact.value)
    if value is None:
        return False
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    context = " ".join(
        str(metadata.get(key) or "")
        for key in ("raw", "context", "source_title", "source_uri")
    ).lower()
    if any(marker in context for marker in ("per share", "eps", "earnings per share", "last sale", "stock price", "share price")):
        return True
    if Decimal(0) < abs(value) < Decimal(1_000_000):
        source = str(metadata.get("source") or "").lower()
        uri = str(metadata.get("source_uri") or "").lower()
        title = str(metadata.get("source_title") or "").lower()
        return source == "natural_text" and any(
            marker in f"{uri} {title}"
            for marker in ("stockanalysis", "finance.yahoo", "nasdaq.com", "marketwatch", "quote")
        )
    return False


def _transaction_value_already_enterprise_value(fact: FinanceFact | None) -> bool:
    if fact is None:
        return False
    metric = _metric_text(fact.metric)
    return any(
        marker in metric
        for marker in (
            "enterprise value",
            "transaction value",
            "deal value",
            "purchase price",
            "consideration paid",
            "purchase consideration",
            "fair value of consideration",
        )
    )


def _plan_dio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    inventory_facts = _dio_inventory_facts(facts)
    cogs = _dio_cogs_fact(facts, target_year=target_year)
    missing = []
    if not inventory_facts:
        missing.append("inventory")
    if cogs is None:
        missing.append("cogs_or_cost_of_sales")
    if missing:
        return _missing("dio", missing, facts=[cogs] if cogs is not None else [])
    inventory_used = _dio_inventory_pair(inventory_facts, target_year=target_year or cogs.fiscal_year)
    avg_inventory_expr = "inventory" if len(inventory_used) == 1 else "(inventory_begin + inventory_end) / 2"
    fiscal_days = _fiscal_days(question)
    variables: JsonObject = {"cogs": cogs.value, "fiscal_days": fiscal_days}
    if len(inventory_used) == 1:
        variables["inventory"] = inventory_used[0].value
    else:
        variables["inventory_begin"] = inventory_used[0].value
        variables["inventory_end"] = inventory_used[1].value
    return _ready(
        "dio",
        f"{avg_inventory_expr} / cogs * fiscal_days",
        variables,
        unit="days",
        facts=[*inventory_used, cogs],
        diagnostics={
            "fiscal_days": fiscal_days,
            "fiscal_days_source": "question_or_default",
            "target_fiscal_year": target_year or cogs.fiscal_year,
        },
    )


def _plan_bridge_subtotal(facts: list[FinanceFact]) -> FinanceFormulaPlan:
    base = _latest_fact(facts, ("net income", "operating income"))
    addbacks = _first_fact_per_metric(
        _facts_for_metric(
            facts,
            (
                "addback",
                "add-back",
                "depreciation and amortization",
                "d&a",
                "interest expense",
                "tax",
                "income tax expense",
                "other expense",
                "other income",
                "restructuring",
            ),
        )
    )
    deductions = _first_fact_per_metric(
        _facts_for_metric(
            facts,
            (
                "deduction",
                "cash charges",
                "one-time cost",
                "license income",
                "divestiture-related license income",
                "gain",
            ),
        )
    )
    adjusted = _latest_fact(facts, ("adjusted ebitda",))
    if base is None or not addbacks or adjusted is None:
        missing = ["base_metric"] if base is None else []
        if not addbacks:
            missing.append("addback_components")
        if adjusted is None:
            missing.append("adjusted_metric")
        return _missing(
            "bridge_subtotal",
            missing,
            facts=[item for item in (base, adjusted) if item is not None],
        )
    variables: JsonObject = {"base": base.value}
    expression_parts = ["base"]
    input_facts = [base]
    for index, fact in enumerate(addbacks, start=1):
        name = f"addback_{index}"
        variables[name] = fact.value
        expression_parts.append(f"+ {name}")
        input_facts.append(fact)
    for index, fact in enumerate(deductions, start=1):
        name = f"deduction_{index}"
        variables[name] = _absolute_decimal_string(fact.value)
        expression_parts.append(f"- {name}")
        input_facts.append(fact)
    return _ready(
        "bridge_subtotal",
        " ".join(expression_parts),
        variables,
        unit=base.unit,
        facts=input_facts,
    )


def _ready(
    formula_name: str,
    expression: str,
    variables: JsonObject,
    *,
    unit: str | None,
    facts: list[FinanceFact],
    diagnostics: JsonObject | None = None,
) -> FinanceFormulaPlan:
    input_fact_ids = [fact.fact_id for fact in facts]
    return FinanceFormulaPlan(
        status="ready",
        formula_name=formula_name,
        payload={
            "expression": expression,
            "variables": variables,
            "unit": unit,
            "formula_name": formula_name,
            "input_fact_ids": input_fact_ids,
        },
        input_fact_ids=input_fact_ids,
        diagnostics=dict(diagnostics or {}),
    )


def _missing(formula_name: str, missing: list[str], *, facts: list[FinanceFact] | None = None) -> FinanceFormulaPlan:
    return FinanceFormulaPlan(
        status="missing_facts",
        formula_name=formula_name,
        missing_facts=missing,
        input_fact_ids=[fact.fact_id for fact in facts or []],
        diagnostics={"reason": "insufficient_formula_inputs"},
    )


def _first_metric_pair(facts: list[FinanceFact], markers: tuple[str, ...]) -> tuple[FinanceFact, FinanceFact] | None:
    by_metric: dict[str, list[FinanceFact]] = {}
    for fact in _facts_for_metric(facts, markers):
        by_metric.setdefault(_metric_key(fact), []).append(fact)
    for metric_facts in by_metric.values():
        ordered = _sort_facts(metric_facts)
        if len(ordered) >= 2:
            return ordered[0], ordered[-1]
    return None


def _latest_fact(
    facts: list[FinanceFact],
    markers: tuple[str, ...],
    *,
    exclude_fact_ids: set[str] | None = None,
) -> FinanceFact | None:
    excluded = exclude_fact_ids or set()
    matches = [fact for fact in _facts_for_metric(facts, markers) if fact.fact_id not in excluded]
    if not matches:
        return None
    return _sort_facts(matches)[-1]


def _facts_for_metric(facts: list[FinanceFact], markers: tuple[str, ...]) -> list[FinanceFact]:
    normalized_markers = tuple(_metric_text(marker) for marker in markers)
    return [
        fact
        for fact in facts
        if any(marker in _metric_text(fact.metric) for marker in normalized_markers)
        or any(marker in _metric_text(str(fact.metadata.get("label") or "")) for marker in normalized_markers)
        or any(marker in _metric_text(str(fact.metadata.get("concept") or "")) for marker in normalized_markers)
    ]


def _first_fact_per_metric(facts: list[FinanceFact]) -> list[FinanceFact]:
    selected: dict[str, FinanceFact] = {}
    for fact in facts:
        key = _metric_key(fact)
        if key not in selected:
            selected[key] = fact
    return list(selected.values())


def _dio_inventory_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    result = [
        fact
        for fact in facts
        if _dio_inventory_eligible(fact)
    ]
    return _sort_unique_facts(result)


def _dio_cogs_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    matches = _sort_unique_facts([fact for fact in facts if _dio_cogs_eligible(fact)])
    if not matches:
        return None
    if target_year is not None:
        by_period_end = [fact for fact in matches if _fact_end_year(fact) == target_year + 1]
        if by_period_end:
            return by_period_end[-1]
        by_year = [fact for fact in matches if fact.fiscal_year == target_year]
        if by_year:
            return by_year[-1]
    return matches[-1]


def _dio_inventory_pair(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
    ordered = _sort_unique_facts(facts)
    if not ordered:
        return []
    if target_year is not None:
        period_begin = [fact for fact in ordered if _fact_end_year(fact) == target_year]
        period_end = [fact for fact in ordered if _fact_end_year(fact) == target_year + 1]
        if period_begin and period_end:
            return [period_begin[-1], period_end[-1]]
        target = [fact for fact in ordered if fact.fiscal_year == target_year]
        prior = [fact for fact in ordered if fact.fiscal_year == target_year - 1]
        if prior and target:
            return [prior[-1], target[-1]]
        current_or_prior = [fact for fact in ordered if isinstance(fact.fiscal_year, int) and fact.fiscal_year <= target_year]
        if len(current_or_prior) >= 2:
            return current_or_prior[-2:]
        if target:
            return [target[-1]]
    return ordered[-2:] if len(ordered) >= 2 else ordered[-1:]


def _dio_inventory_eligible(fact: FinanceFact) -> bool:
    text = _fact_text(fact)
    compact = "".join(ch for ch in text if ch.isalnum())
    if any(marker in compact for marker in ("deferredtax", "taxasset", "taxliabilit")):
        return False
    if "valuationreserve" in compact or "inventoryreserve" in compact:
        return False
    if "increasedecrease" in compact or "changeininventor" in compact:
        return False
    if any(marker in compact for marker in ("inventorynet", "inventoriesnet", "merchandiseinventories")):
        return True
    metric = _metric_text(fact.metric)
    return metric in {"inventory", "inventories"}


def _dio_cogs_eligible(fact: FinanceFact) -> bool:
    text = _fact_text(fact)
    compact = "".join(ch for ch in text if ch.isalnum())
    if any(marker in compact for marker in ("deferredtax", "inventorycostcapitalized")):
        return False
    if "depreciation" in compact or "amortization" in compact:
        return False
    if any(
        marker in compact
        for marker in (
            "costofrevenue",
            "costofgoodsandservicessold",
            "costofgoodssold",
            "costofsales",
            "costofgoodsandserviceexcludingdepreciationdepletionandamortization",
        )
    ):
        return True
    metric = _metric_text(fact.metric)
    return metric in {"cogs", "cost of sales", "cost of revenue", "cost of goods sold"}


def _sort_unique_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    selected: dict[tuple[str, int | None, str, str], FinanceFact] = {}
    for fact in facts:
        key = (
            _metric_key(fact),
            fact.fiscal_year,
            str(fact.period or ""),
            str(fact.value or ""),
        )
        current = selected.get(key)
        if current is None or _fact_specificity(fact) >= _fact_specificity(current):
            selected[key] = fact
    return _sort_facts(list(selected.values()))


def _fact_specificity(fact: FinanceFact) -> int:
    score = 0
    if fact.citation_ref:
        score += 4
    if fact.fiscal_year is not None:
        score += 3
    if fact.period:
        score += 2
    if fact.metadata.get("form") == "10-K":
        score += 2
    return score


def _fact_text(fact: FinanceFact) -> str:
    return " ".join(
        str(value or "")
        for value in (
            fact.metric,
            fact.metadata.get("concept"),
            fact.metadata.get("label"),
        )
    ).lower()


def _fact_end_year(fact: FinanceFact) -> int | None:
    end = str(fact.metadata.get("end") or "")
    match = re.match(r"^(?P<year>\d{4})-", end)
    if not match:
        return None
    return int(match.group("year"))


def _sort_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    return sorted(
        facts,
        key=lambda fact: (
            fact.fiscal_year or 0,
            str(fact.metadata.get("end") or ""),
            str(fact.metadata.get("filed") or ""),
            str(fact.period or ""),
            fact.fact_id,
        ),
    )


def _metric_key(fact: FinanceFact) -> str:
    return _metric_text(fact.metric or str(fact.metadata.get("concept") or ""))


def _metric_text(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").replace("-", " ").lower().split())


def _year_span(beginning: FinanceFact, ending: FinanceFact) -> int:
    if isinstance(beginning.fiscal_year, int) and isinstance(ending.fiscal_year, int):
        return abs(ending.fiscal_year - beginning.fiscal_year)
    return 1


def _fiscal_days(question: str) -> int:
    match = re.search(r"\b(?P<days>3[5-7]\d)\s*(?:days|day|天)\b", question or "", re.IGNORECASE)
    if match:
        return int(match.group("days"))
    return 365


def _target_fiscal_year(question: str) -> int | None:
    match = re.search(r"\b(?:FY|fiscal\s+year\s*)?(?P<year>20\d{2}|19\d{2})\b", question or "", re.IGNORECASE)
    if not match:
        return None
    return int(match.group("year"))


def _ratio_value(fact: FinanceFact) -> str:
    value = _decimal_or_none(fact.value)
    if value is None:
        return fact.value
    unit = str(fact.unit or "").lower()
    if unit in {"%", "percent"} or abs(value) > Decimal("1.5"):
        return _decimal_string(value / Decimal(100))
    return _decimal_string(value)


def _absolute_decimal_string(value: object) -> str:
    parsed = _decimal_or_none(value)
    if parsed is None:
        return str(value)
    return _decimal_string(abs(parsed))


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _decimal_string(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
