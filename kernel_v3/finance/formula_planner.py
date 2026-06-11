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
    if formula == "dcf":
        return _plan_dcf(question=question, facts=usable)
    if formula == "lbo":
        return _plan_lbo(question=question, facts=usable)
    if formula == "capital_intensity":
        return _plan_capital_intensity(question=question, facts=usable)
    return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "unsupported_formula", "formula": formula})


def _detect_formula(question: str) -> str | None:
    text = str(question or "").lower()
    compact = text.replace(" ", "")
    if "cagr" in text or "compound annual growth" in text:
        return "cagr"
    if "dio" in text or "days inventory" in text or "days inventory outstanding" in text:
        return "dio"
    if "discounted cash flow" in text or re.search(r"\bdcf\b", text):
        return "dcf"
    if re.search(r"\blbo\b", text) or "leveraged buyout" in text:
        return "lbo"
    if "capital-intensive" in text or "capital intensive" in text or "capital intensity" in text:
        return "capital_intensity"
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


def _plan_capital_intensity(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    capex = _latest_fact_for_year(facts, ("capital expenditures",), target_year=target_year)
    revenue = _latest_revenue_fact(facts, target_year=target_year)
    operating_cash_flow = _latest_fact_for_year(
        facts,
        (
            "operating cash flow",
            "cash flow from operations",
            "net cash provided by operating activities",
        ),
        target_year=target_year,
    )
    ppe = _latest_fact_for_year(
        facts,
        ("property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"),
        target_year=target_year,
    )
    assets = _latest_fact_for_year(facts, ("assets", "total assets"), target_year=target_year)
    missing = []
    if capex is None:
        missing.append("capital_expenditures")
    if revenue is None:
        missing.append("revenue")
    if operating_cash_flow is None:
        missing.append("operating_cash_flow")
    if ppe is None:
        missing.append("property_plant_and_equipment_net")
    if assets is None:
        missing.append("assets")
    if missing:
        return _missing(
            "capital_intensity",
            missing,
            facts=[item for item in (capex, revenue, operating_cash_flow, ppe, assets) if item is not None],
            diagnostics={
                "required_ratios": ["capex_to_revenue", "capex_to_operating_cash_flow", "ppe_to_assets"],
                "reason": "capital_intensity_requires_multiple_balance_sheet_and_cash_flow_slots",
                "target_fiscal_year": target_year,
            },
        )
    return _ready(
        "capital_intensity",
        "capital_expenditures / revenue",
        {
            "capital_expenditures": _absolute_decimal_string(capex.value),
            "revenue": revenue.value,
            "operating_cash_flow": operating_cash_flow.value,
            "property_plant_and_equipment_net": ppe.value,
            "assets": assets.value,
        },
        unit="percent",
        facts=[capex, revenue, operating_cash_flow, ppe, assets],
        diagnostics={
            "required_ratios": ["capex_to_revenue", "capex_to_operating_cash_flow", "ppe_to_assets"],
            "secondary_expressions": {
                "capex_to_operating_cash_flow": "capital_expenditures / operating_cash_flow",
                "ppe_to_assets": "property_plant_and_equipment_net / assets",
            },
            "target_fiscal_year": target_year,
        },
    )


def _absolute_decimal_string(value: object) -> str:
    decimal = _decimal_or_none(value)
    if decimal is None:
        return str(value)
    return str(abs(decimal))


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
    cash = _latest_cash_fact(facts)
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
    cash = _latest_cash_fact(facts)
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
    candidate = _best_bridge_group(facts)
    if candidate is None:
        base = _latest_fact(facts, ("net income", "operating income", "income from continuing operations"))
        addbacks = _bridge_component_facts(facts)
        adjusted = _latest_fact(facts, ("adjusted ebitda",))
        if adjusted is not None and (base is not None or addbacks):
            support_facts = [adjusted]
            if base is not None:
                support_facts.append(base)
            support_facts.extend(addbacks[:8])
            reported_adjusted = _fact_value_for_formula(adjusted, related_facts=support_facts)
            return _ready(
                "bridge_subtotal",
                "reported_adjusted",
                {"reported_adjusted": reported_adjusted},
                unit=adjusted.unit,
                facts=support_facts,
                diagnostics={
                    "bridge_formula_source": "reported_adjusted_only",
                    "reason": "component_sum_did_not_match_reported_adjusted",
                    "reported_adjusted_scale_multiplier": str(
                        _fact_context_scale_multiplier(adjusted, related_facts=support_facts)
                    ),
                },
            )
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
    base = candidate["base"]
    addbacks = candidate["addbacks"]
    deductions = candidate["deductions"]
    adjusted = candidate["adjusted"]
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
    if adjusted is not None:
        variables["reported_adjusted"] = _fact_value_for_formula(adjusted, related_facts=input_facts)
        input_facts.append(adjusted)
    diagnostics: JsonObject = {}
    if candidate is not None:
        diagnostics.update(
            {
                "bridge_group_key": candidate["group_key"],
                "bridge_group_score": candidate["score"],
                "bridge_target_column_index": candidate.get("target_column_index"),
                "bridge_detected_column_count": candidate.get("detected_column_count"),
                "reported_adjusted_fact_id": adjusted.fact_id if adjusted is not None else None,
                "component_fact_count": len(input_facts),
            }
        )
    return _ready(
        "bridge_subtotal",
        " ".join(expression_parts),
        variables,
        unit=base.unit,
        facts=input_facts,
        diagnostics=diagnostics,
    )


def _plan_dcf(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    free_cash_flow = _latest_fact(facts, ("free cash flow",))
    operating_cash_flow = _latest_fact(
        facts,
        (
            "operating cash flow",
            "cash flow from operations",
            "net cash provided by operating activities",
        ),
    )
    capex = _latest_fact(facts, ("capital expenditures", "capex"))
    input_facts: list[FinanceFact] = []
    base_cash_flow_metric = ""
    base_cash_flow_unit: str | None = None
    if free_cash_flow is not None:
        base_cash_flow_value = free_cash_flow.value
        base_cash_flow_unit = free_cash_flow.unit
        base_cash_flow_metric = free_cash_flow.metric
        input_facts = [free_cash_flow]
    elif operating_cash_flow is not None and capex is not None:
        operating_value = _decimal_or_none(operating_cash_flow.value)
        capex_value = _decimal_or_none(capex.value)
        if operating_value is None or capex_value is None:
            return _missing("dcf", ["base_cash_flow"], facts=[operating_cash_flow, capex])
        base_cash_flow_value = _decimal_string(operating_value - abs(capex_value))
        base_cash_flow_unit = operating_cash_flow.unit
        base_cash_flow_metric = "derived free cash flow"
        input_facts = [operating_cash_flow, capex]
    elif operating_cash_flow is not None:
        base_cash_flow_value = operating_cash_flow.value
        base_cash_flow_unit = operating_cash_flow.unit
        base_cash_flow_metric = operating_cash_flow.metric
        input_facts = [operating_cash_flow]
    else:
        return _missing("dcf", ["base_cash_flow"], facts=[])

    assumptions = _dcf_assumptions(question)
    discount_rate = assumptions["discount_rate"]
    terminal_growth_rate = assumptions["terminal_growth_rate"]
    if discount_rate <= terminal_growth_rate:
        return _missing("dcf", ["discount_rate_above_terminal_growth"], facts=[base_cash_flow])
    years = int(assumptions["forecast_years"])
    debt = _latest_fact(facts, ("debt", "long term debt", "short term debt"))
    cash = _latest_cash_fact(facts)
    investments = _latest_fact(facts, ("short-term investments", "short term investments"))
    shares = _latest_fact(facts, ("shares outstanding",))
    wants_per_share = _wants_per_share_output(question)
    wants_equity_value = _wants_equity_value_output(question)
    if wants_per_share and shares is None:
        return _missing("dcf", ["shares_outstanding"], facts=[*input_facts, *[item for item in (debt, cash, investments) if item is not None]])
    variables: JsonObject = {
        "base_cash_flow": base_cash_flow_value,
        "growth_rate": _decimal_string(assumptions["growth_rate"]),
        "discount_rate": _decimal_string(discount_rate),
        "terminal_growth_rate": _decimal_string(terminal_growth_rate),
        "debt": debt.value if debt is not None else "0",
        "cash": cash.value if cash is not None else "0",
        "investments": investments.value if investments is not None else "0",
    }
    bridge_facts = [item for item in (debt, cash, investments) if item is not None]
    if shares is not None:
        variables["shares"] = shares.value
        if wants_per_share:
            bridge_facts.append(shares)
    projected_terms = [
        f"(base_cash_flow * ((1 + growth_rate) ** {year}) / ((1 + discount_rate) ** {year}))"
        for year in range(1, years + 1)
    ]
    terminal_term = (
        f"(base_cash_flow * ((1 + growth_rate) ** {years}) * (1 + terminal_growth_rate) "
        f"/ (discount_rate - terminal_growth_rate) / ((1 + discount_rate) ** {years}))"
    )
    enterprise_value_expression = " + ".join([*projected_terms, terminal_term])
    expression = enterprise_value_expression
    unit = base_cash_flow_unit
    reported_output = "enterprise_value"
    if wants_per_share and shares is not None:
        expression = f"(({enterprise_value_expression}) + cash + investments - debt) / shares"
        unit = "USD/share"
        reported_output = "equity_value_per_share"
    elif wants_equity_value:
        expression = f"({enterprise_value_expression}) + cash + investments - debt"
        reported_output = "equity_value"
    base_decimal = _decimal_or_none(base_cash_flow_value)
    model_outputs = (
        _dcf_model_outputs(
            base_cash_flow=base_decimal,
            assumptions=assumptions,
            debt=_decimal_or_zero(debt.value if debt is not None else None),
            cash=_decimal_or_zero(cash.value if cash is not None else None),
            investments=_decimal_or_zero(investments.value if investments is not None else None),
            shares=_decimal_or_none(shares.value) if shares is not None else None,
        )
        if base_decimal is not None
        else {}
    )
    defaulted = list(assumptions["defaulted"])
    if debt is None:
        defaulted.append("debt")
    if cash is None:
        defaulted.append("cash")
    if investments is None:
        defaulted.append("investments")
    return _ready(
        "dcf",
        expression,
        variables,
        unit=unit,
        facts=[*input_facts, *bridge_facts],
        diagnostics={
            "modeling_workflow": "discounted_cash_flow",
            "base_cash_flow_metric": base_cash_flow_metric,
            "assumptions": _assumption_diagnostics(assumptions),
            "defaulted_assumptions": _ordered_unique(defaulted),
            "assumption_source": "question_or_host_modeling_policy",
            "reported_output": reported_output,
            "model_outputs": model_outputs,
        },
    )


def _plan_lbo(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    ev_inputs = _enterprise_value_inputs(facts)
    basis = _lbo_basis_fact(facts)
    revenue_basis = _latest_fact(facts, ("revenue", "net sales", "net revenues", "total revenues", "sales"))
    missing: list[str] = []
    if basis is None and revenue_basis is None:
        missing.append("cash_flow_or_ebitda")
    if missing:
        return _missing(
            "lbo",
            missing,
            facts=[
                item
                for item in (
                    ev_inputs.get("equity"),
                    ev_inputs.get("debt"),
                    ev_inputs.get("cash"),
                    ev_inputs.get("investments"),
                    basis,
                )
                if isinstance(item, FinanceFact)
            ],
        )

    assumptions = _lbo_assumptions(question)
    basis_value_fact = basis or revenue_basis
    if basis_value_fact is None:
        return _missing("lbo", ["cash_flow_or_ebitda"], facts=[])
    basis_value = _decimal_or_none(basis_value_fact.value)
    if basis_value is None:
        return _missing("lbo", ["cash_flow_or_ebitda"], facts=[basis_value_fact])
    if basis is None:
        ebitda_variable_value = _decimal_string(basis_value * assumptions["ebitda_margin"])
        ebitda_source = "assumed_ebitda_margin_on_revenue"
        basis_metric = "derived ebitda from revenue"
    else:
        ebitda_variable_value = basis.value
        ebitda_source = "direct" if _metric_text(basis.metric) in {"adjusted ebitda", "ebitda"} else "cash_flow_basis"
        basis_metric = basis.metric
    variables: JsonObject
    input_facts: list[FinanceFact]
    enterprise_value_source = str(ev_inputs["source"])
    equity = ev_inputs.get("equity")
    if isinstance(equity, FinanceFact):
        variables = dict(ev_inputs["variables"])
        input_facts = [*ev_inputs["facts"], basis_value_fact]
        if "debt" in ev_inputs["missing"]:
            assumptions["defaulted"].append("debt")
        if "cash" in ev_inputs["missing"]:
            assumptions["defaulted"].append("cash")
    else:
        entry_basis_value = _decimal_or_none(ebitda_variable_value)
        if entry_basis_value is None:
            return _missing("lbo", ["cash_flow_or_ebitda"], facts=[basis_value_fact])
        variables = {
            "equity_value": _decimal_string(entry_basis_value * assumptions["entry_multiple"]),
            "debt": "0",
            "cash": "0",
            "investments": "0",
        }
        input_facts = [basis_value_fact]
        enterprise_value_source = "assumed_entry_enterprise_value_from_basis_multiple"
    variables.update(
        {
            "ebitda": ebitda_variable_value,
            "debt_multiple": _decimal_string(assumptions["debt_multiple"]),
            "exit_multiple": _decimal_string(assumptions["exit_multiple"]),
            "ebitda_growth_rate": _decimal_string(assumptions["ebitda_growth_rate"]),
            "annual_debt_paydown_multiple": _decimal_string(assumptions["annual_debt_paydown_multiple"]),
            "hold_years": int(assumptions["hold_years"]),
        }
    )
    entry_enterprise_value = _decimal_or_none(str(variables.get("equity_value") or "0"))
    if entry_enterprise_value is not None:
        entry_enterprise_value += _decimal_or_none(str(variables.get("debt") or "0")) or Decimal(0)
        entry_enterprise_value -= _decimal_or_none(str(variables.get("cash") or "0")) or Decimal(0)
        entry_enterprise_value -= _decimal_or_none(str(variables.get("investments") or "0")) or Decimal(0)
    ebitda_value = _decimal_or_none(ebitda_variable_value)
    if (
        entry_enterprise_value is not None
        and ebitda_value is not None
        and entry_enterprise_value <= ebitda_value * assumptions["debt_multiple"]
    ):
        return _missing("lbo", ["positive_sponsor_equity_after_debt_assumption"], facts=input_facts)
    model_outputs = (
        _lbo_model_outputs(
            entry_enterprise_value=entry_enterprise_value,
            ebitda=ebitda_value,
            assumptions=assumptions,
        )
        if entry_enterprise_value is not None and ebitda_value is not None
        else {}
    )
    sponsor_equity_expression = "((equity_value + debt - cash - investments) - (ebitda * debt_multiple))"
    exit_debt_expression = "max((ebitda * debt_multiple) - (ebitda * annual_debt_paydown_multiple * hold_years), 0)"
    exit_equity_expression = (
        "((ebitda * ((1 + ebitda_growth_rate) ** hold_years) * exit_multiple) "
        f"- {exit_debt_expression})"
    )
    moic_expression = f"({exit_equity_expression}) / {sponsor_equity_expression}"
    reported_output = _lbo_reported_output(question)
    expression = f"({moic_expression}) ** (1 / hold_years) - 1"
    unit = "percent"
    if reported_output == "moic":
        expression = moic_expression
        unit = "x"
    elif reported_output == "exit_equity_value":
        expression = exit_equity_expression
        unit = basis_value_fact.unit
    return _ready(
        "lbo",
        expression,
        variables,
        unit=unit,
        facts=input_facts,
        diagnostics={
            "modeling_workflow": "leveraged_buyout",
            "enterprise_value_source": enterprise_value_source,
            "ebitda_source": ebitda_source,
            "basis_metric": basis_metric,
            "assumptions": _assumption_diagnostics(assumptions),
            "defaulted_assumptions": assumptions["defaulted"],
            "assumption_source": "question_or_host_modeling_policy",
            "reported_output": reported_output,
            "model_outputs": model_outputs,
        },
    )


def _best_bridge_group(facts: list[FinanceFact]) -> JsonObject | None:
    groups = _bridge_fact_groups(facts)
    candidates: list[JsonObject] = []
    for group_key, group_facts in groups.items():
        adjusted_facts = _facts_for_metric(group_facts, ("adjusted ebitda",))
        if not adjusted_facts:
            continue
        target_index = 0
        adjusted = adjusted_facts[target_index]
        base = _bridge_select_column_fact(
            _facts_for_metric(group_facts, ("net income", "operating income", "income from continuing operations")),
            target_index=target_index,
            column_count=len(adjusted_facts),
        )
        components = _bridge_select_column_components(
            _bridge_component_facts(group_facts),
            target_index=target_index,
            column_count=len(adjusted_facts),
        )
        addbacks = [fact for fact in components if _metric_text(fact.metric) != "deduction"]
        deductions = [fact for fact in components if _metric_text(fact.metric) == "deduction"]
        if base is None or adjusted is None or not addbacks:
            continue
        subtotal = _bridge_subtotal_value(base=base, addbacks=addbacks, deductions=deductions)
        adjusted_value = _decimal_or_none(adjusted.value)
        if subtotal is None or adjusted_value is None or not _bridge_subtotal_matches_reported(subtotal, adjusted_value):
            continue
        score = _bridge_group_score(group_facts, base=base, adjusted=adjusted, addbacks=addbacks, deductions=deductions)
        candidates.append(
            {
                "group_key": group_key,
                "score": score,
                "target_column_index": target_index,
                "detected_column_count": len(adjusted_facts),
                "base": base,
                "adjusted": adjusted,
                "addbacks": addbacks,
                "deductions": deductions,
            }
        )
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda item: (
            item["score"],
            _fact_sort_token(item["adjusted"]),
            str(item["group_key"]),
        ),
    )[-1]


def _bridge_fact_groups(facts: list[FinanceFact]) -> dict[str, list[FinanceFact]]:
    groups: dict[str, list[FinanceFact]] = {}
    ungrouped: list[FinanceFact] = []
    for fact in facts:
        keys = []
        for prefix, value in (
            ("citation", fact.citation_ref),
            ("evidence", fact.evidence_ref),
            ("source", fact.source_ref),
        ):
            if value:
                keys.append(f"{prefix}:{value}")
        if not keys:
            ungrouped.append(fact)
            continue
        for key in keys:
            groups.setdefault(key, []).append(fact)
    if not groups and ungrouped:
        groups["ungrouped"] = list(ungrouped)
    return groups


def _bridge_component_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    components = _facts_for_metric(
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
            "deduction",
            "cash charges",
            "one-time cost",
            "license income",
            "divestiture-related license income",
            "gain",
        ),
    )
    selected: dict[str, FinanceFact] = {}
    for fact in components:
        if fact.fact_id not in selected:
            selected[fact.fact_id] = fact
    return list(selected.values())


def _bridge_subtotal_value(
    *,
    base: FinanceFact,
    addbacks: list[FinanceFact],
    deductions: list[FinanceFact],
) -> Decimal | None:
    base_value = _decimal_or_none(base.value)
    if base_value is None:
        return None
    total = base_value
    for fact in addbacks:
        value = _decimal_or_none(fact.value)
        if value is None:
            return None
        total += value
    for fact in deductions:
        value = _decimal_or_none(fact.value)
        if value is None:
            return None
        total -= abs(value)
    return total


def _bridge_subtotal_matches_reported(total: Decimal, reported: Decimal) -> bool:
    candidates = [reported]
    if abs(reported) < Decimal("1000000"):
        candidates.extend([reported * Decimal(1_000), reported * Decimal(1_000_000), reported * Decimal(1_000_000_000)])
    for candidate in candidates:
        tolerance = max(abs(candidate) * Decimal("0.005"), Decimal("1"))
        if abs(total - candidate) <= tolerance:
            return True
    return False


def _fact_value_for_formula(fact: FinanceFact, *, related_facts: list[FinanceFact] | None = None) -> str:
    value = _decimal_or_none(fact.value)
    if value is None:
        return str(fact.value)
    scale_multiplier = _fact_context_scale_multiplier(fact, related_facts=related_facts)
    if scale_multiplier != Decimal(1) and Decimal(0) < abs(value) < Decimal("1000000"):
        value *= scale_multiplier
    return _decimal_string(value)


def _fact_context_scale_multiplier(fact: FinanceFact, *, related_facts: list[FinanceFact] | None = None) -> Decimal:
    facts = [fact, *(related_facts or [])]
    context = " ".join(
        str(value or "")
        for item in facts
        for value in (
            item.metadata.get("context") if isinstance(item.metadata, dict) else "",
            item.metadata.get("source_title") if isinstance(item.metadata, dict) else "",
            item.metadata.get("raw") if isinstance(item.metadata, dict) else "",
        )
    ).lower()
    if re.search(r"(?:amounts?\s+)?in\s+billions|\(\s*in\s+billions\s*\)", context):
        return Decimal(1_000_000_000)
    if re.search(r"(?:amounts?\s+)?in\s+millions|\(\s*in\s+millions\s*\)", context):
        return Decimal(1_000_000)
    if re.search(r"(?:amounts?\s+)?in\s+thousands|\(\s*in\s+thousands\s*\)", context):
        return Decimal(1_000)
    return Decimal(1)


def _bridge_select_column_fact(
    facts: list[FinanceFact],
    *,
    target_index: int,
    column_count: int,
) -> FinanceFact | None:
    if not facts:
        return None
    if column_count <= 1:
        return facts[0]
    return facts[min(max(0, target_index), len(facts) - 1)]


def _bridge_select_column_components(
    facts: list[FinanceFact],
    *,
    target_index: int,
    column_count: int,
) -> list[FinanceFact]:
    if not facts or column_count <= 1:
        return facts
    selected: list[FinanceFact] = []
    position = 0
    while position < len(facts):
        chunk = facts[position : position + column_count]
        if target_index < len(chunk):
            selected.append(chunk[target_index])
        elif target_index == 0 and chunk:
            selected.append(chunk[0])
        position += max(1, column_count)
    return selected


def _bridge_group_score(
    facts: list[FinanceFact],
    *,
    base: FinanceFact,
    adjusted: FinanceFact,
    addbacks: list[FinanceFact],
    deductions: list[FinanceFact],
) -> int:
    score = 100
    score += min(len(addbacks), 16) * 6
    score += min(len(deductions), 8) * 3
    source_text = " ".join(
        str(value or "")
        for fact in facts
        for value in (
            fact.metadata.get("source_title"),
            fact.metadata.get("source_uri"),
            fact.metadata.get("form"),
            fact.metadata.get("raw"),
            fact.metadata.get("context"),
        )
    ).lower()
    if "10-k" in source_text or "form 10-k" in source_text:
        score += 30
    if "reconciliation" in source_text:
        score += 20
    if "adjusted ebitda" in source_text:
        score += 20
    if "10-q" in source_text or "form 10-q" in source_text:
        score -= 10
    years = {fact.fiscal_year for fact in [base, adjusted, *addbacks, *deductions] if fact.fiscal_year is not None}
    if len(years) == 1:
        score += 15
    elif len(years) > 1:
        score -= 5
    base_value = _decimal_or_none(base.value)
    adjusted_value = _decimal_or_none(adjusted.value)
    if base_value is not None and adjusted_value is not None and abs(adjusted_value) >= abs(base_value):
        score += 5
    return score


def _dcf_assumptions(question: str) -> JsonObject:
    defaulted: list[str] = []
    growth_rate = _percentage_assumption(
        question,
        ("fcf growth", "free cash flow growth", "cash flow growth", "revenue growth", "growth"),
        Decimal("0.03"),
        defaulted=defaulted,
        name="growth_rate",
    )
    discount_rate = _percentage_assumption(
        question,
        ("discount rate", "wacc", "cost of capital"),
        Decimal("0.10"),
        defaulted=defaulted,
        name="discount_rate",
    )
    terminal_growth_rate = _percentage_assumption(
        question,
        ("terminal growth", "perpetuity growth", "long-term growth", "long term growth"),
        Decimal("0.025"),
        defaulted=defaulted,
        name="terminal_growth_rate",
    )
    years = _integer_assumption(
        question,
        ("forecast", "projection", "projected", "year", "years"),
        5,
        defaulted=defaulted,
        name="forecast_years",
        minimum=1,
        maximum=10,
    )
    return {
        "growth_rate": growth_rate,
        "discount_rate": discount_rate,
        "terminal_growth_rate": terminal_growth_rate,
        "forecast_years": years,
        "defaulted": defaulted,
    }


def _lbo_assumptions(question: str) -> JsonObject:
    defaulted: list[str] = []
    debt_multiple = _multiple_assumption(
        question,
        ("debt multiple", "leverage", "debt"),
        Decimal("4.0"),
        defaulted=defaulted,
        name="debt_multiple",
    )
    entry_multiple = _multiple_assumption(
        question,
        ("entry multiple", "purchase multiple", "entry ev/ebitda", "valuation multiple"),
        Decimal("10.0"),
        defaulted=defaulted,
        name="entry_multiple",
    )
    exit_multiple = _multiple_assumption(
        question,
        ("exit multiple", "terminal multiple", "exit ev/ebitda"),
        Decimal("10.0"),
        defaulted=defaulted,
        name="exit_multiple",
    )
    ebitda_growth_rate = _percentage_assumption(
        question,
        ("ebitda growth", "cash flow growth", "growth"),
        Decimal("0.03"),
        defaulted=defaulted,
        name="ebitda_growth_rate",
    )
    ebitda_margin = _percentage_assumption(
        question,
        ("ebitda margin", "cash flow margin", "margin"),
        Decimal("0.20"),
        defaulted=defaulted,
        name="ebitda_margin",
    )
    annual_debt_paydown_multiple = _multiple_assumption(
        question,
        ("annual debt paydown", "debt paydown", "paydown"),
        Decimal("0.25"),
        defaulted=defaulted,
        name="annual_debt_paydown_multiple",
    )
    hold_years = _integer_assumption(
        question,
        ("hold period", "holding period", "exit year", "years"),
        5,
        defaulted=defaulted,
        name="hold_years",
        minimum=1,
        maximum=10,
    )
    return {
        "entry_multiple": entry_multiple,
        "debt_multiple": debt_multiple,
        "exit_multiple": exit_multiple,
        "ebitda_growth_rate": ebitda_growth_rate,
        "ebitda_margin": ebitda_margin,
        "annual_debt_paydown_multiple": annual_debt_paydown_multiple,
        "hold_years": hold_years,
        "defaulted": defaulted,
    }


def _lbo_basis_fact(facts: list[FinanceFact]) -> FinanceFact | None:
    return _latest_fact(
        facts,
        (
            "adjusted ebitda",
            "ebitda",
            "free cash flow",
            "operating cash flow",
            "cash flow from operations",
            "net cash provided by operating activities",
        ),
    )


def _assumption_diagnostics(assumptions: JsonObject) -> JsonObject:
    return {
        key: _decimal_string(value) if isinstance(value, Decimal) else value
        for key, value in assumptions.items()
        if key != "defaulted"
    }


def _dcf_model_outputs(
    *,
    base_cash_flow: Decimal | None,
    assumptions: JsonObject,
    debt: Decimal,
    cash: Decimal,
    investments: Decimal,
    shares: Decimal | None,
) -> JsonObject:
    if base_cash_flow is None:
        return {}
    growth_rate = assumptions["growth_rate"]
    discount_rate = assumptions["discount_rate"]
    terminal_growth_rate = assumptions["terminal_growth_rate"]
    years = int(assumptions["forecast_years"])
    projected: list[JsonObject] = []
    pv_sum = Decimal(0)
    for year in range(1, years + 1):
        free_cash_flow = base_cash_flow * ((Decimal(1) + growth_rate) ** year)
        discount_factor = (Decimal(1) + discount_rate) ** year
        present_value = free_cash_flow / discount_factor
        pv_sum += present_value
        projected.append(
            {
                "year": year,
                "free_cash_flow": _decimal_string(free_cash_flow),
                "discount_factor": _decimal_string(discount_factor),
                "present_value": _decimal_string(present_value),
            }
        )
    terminal_free_cash_flow = base_cash_flow * ((Decimal(1) + growth_rate) ** years) * (Decimal(1) + terminal_growth_rate)
    terminal_value = terminal_free_cash_flow / (discount_rate - terminal_growth_rate)
    pv_terminal_value = terminal_value / ((Decimal(1) + discount_rate) ** years)
    enterprise_value = pv_sum + pv_terminal_value
    net_debt = debt - cash - investments
    equity_value = enterprise_value - net_debt
    result: JsonObject = {
        "projection": projected,
        "terminal_free_cash_flow": _decimal_string(terminal_free_cash_flow),
        "terminal_value": _decimal_string(terminal_value),
        "pv_terminal_value": _decimal_string(pv_terminal_value),
        "enterprise_value": _decimal_string(enterprise_value),
        "debt": _decimal_string(debt),
        "cash": _decimal_string(cash),
        "investments": _decimal_string(investments),
        "net_debt": _decimal_string(net_debt),
        "equity_value": _decimal_string(equity_value),
    }
    if shares is not None and shares != 0:
        result["shares"] = _decimal_string(shares)
        result["equity_value_per_share"] = _decimal_string(equity_value / shares)
    return result


def _lbo_model_outputs(
    *,
    entry_enterprise_value: Decimal | None,
    ebitda: Decimal | None,
    assumptions: JsonObject,
) -> JsonObject:
    if entry_enterprise_value is None or ebitda is None:
        return {}
    debt_multiple = assumptions["debt_multiple"]
    exit_multiple = assumptions["exit_multiple"]
    ebitda_growth_rate = assumptions["ebitda_growth_rate"]
    annual_debt_paydown_multiple = assumptions["annual_debt_paydown_multiple"]
    hold_years = int(assumptions["hold_years"])
    initial_debt = ebitda * debt_multiple
    sponsor_equity = entry_enterprise_value - initial_debt
    schedule: list[JsonObject] = []
    debt_balance = initial_debt
    annual_debt_paydown = ebitda * annual_debt_paydown_multiple
    for year in range(1, hold_years + 1):
        projected_ebitda = ebitda * ((Decimal(1) + ebitda_growth_rate) ** year)
        debt_paydown = min(debt_balance, annual_debt_paydown)
        ending_debt = debt_balance - debt_paydown
        schedule.append(
            {
                "year": year,
                "ebitda": _decimal_string(projected_ebitda),
                "beginning_debt": _decimal_string(debt_balance),
                "debt_paydown": _decimal_string(debt_paydown),
                "ending_debt": _decimal_string(ending_debt),
            }
        )
        debt_balance = ending_debt
    exit_ebitda = ebitda * ((Decimal(1) + ebitda_growth_rate) ** hold_years)
    exit_enterprise_value = exit_ebitda * exit_multiple
    exit_equity_value = exit_enterprise_value - debt_balance
    moic = exit_equity_value / sponsor_equity if sponsor_equity != 0 else Decimal(0)
    sponsor_irr = _decimal_power(moic, Decimal(1) / Decimal(hold_years)) - Decimal(1) if moic > 0 else Decimal(0)
    return {
        "entry_enterprise_value": _decimal_string(entry_enterprise_value),
        "initial_debt": _decimal_string(initial_debt),
        "initial_sponsor_equity": _decimal_string(sponsor_equity),
        "annual_debt_paydown": _decimal_string(annual_debt_paydown),
        "projection": schedule,
        "exit_ebitda": _decimal_string(exit_ebitda),
        "exit_enterprise_value": _decimal_string(exit_enterprise_value),
        "exit_debt": _decimal_string(debt_balance),
        "exit_equity_value": _decimal_string(exit_equity_value),
        "moic": _decimal_string(moic),
        "sponsor_irr": _decimal_string(sponsor_irr),
    }


def _wants_per_share_output(question: str) -> bool:
    text = _metric_text(question)
    return (
        "per share" in text
        or "per-share" in text
        or "share price" in text
        or "price target" in text
        or "equity value per share" in text
    )


def _wants_equity_value_output(question: str) -> bool:
    text = _metric_text(question)
    if _wants_per_share_output(question):
        return False
    return any(
        marker in text
        for marker in (
            "equity value",
            "market capitalization",
            "market cap",
            "shareholder equity value",
            "value of equity",
        )
    )


def _lbo_reported_output(question: str) -> str:
    text = _metric_text(question)
    if any(
        marker in text
        for marker in (
            "exit equity",
            "exit equity value",
            "equity value at exit",
            "sponsor equity at exit",
            "exit sponsor equity",
        )
    ):
        return "exit_equity_value"
    if any(
        marker in text
        for marker in (
            "moic",
            "money on money",
            "money-on-money",
            "multiple of invested capital",
            "cash on cash multiple",
            "sponsor multiple",
        )
    ):
        return "moic"
    return "sponsor_irr"


def _decimal_or_zero(value: object) -> Decimal:
    return _decimal_or_none(value) or Decimal(0)


def _decimal_power(left: Decimal, right: Decimal) -> Decimal:
    try:
        return left.__pow__(right)
    except InvalidOperation:
        return Decimal(str(float(left) ** float(right)))


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = str(item)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _percentage_assumption(
    question: str,
    labels: tuple[str, ...],
    default: Decimal,
    *,
    defaulted: list[str],
    name: str,
) -> Decimal:
    text = _metric_text(question)
    for label in labels:
        compact_label = re.escape(_metric_text(label))
        patterns = (
            rf"{compact_label}[^\d%]{{0,60}}(?P<value>\d+(?:\.\d+)?)\s*%",
            rf"(?P<value>\d+(?:\.\d+)?)\s*%[^\w%]{{0,40}}{compact_label}",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = _decimal_or_none(match.group("value"))
            if value is not None:
                return value / Decimal(100)
    defaulted.append(name)
    return default


def _multiple_assumption(
    question: str,
    labels: tuple[str, ...],
    default: Decimal,
    *,
    defaulted: list[str],
    name: str,
) -> Decimal:
    text = _metric_text(question)
    for label in labels:
        compact_label = re.escape(_metric_text(label))
        patterns = (
            rf"{compact_label}[^\dx]{{0,60}}(?P<value>\d+(?:\.\d+)?)\s*x",
            rf"(?P<value>\d+(?:\.\d+)?)\s*x[^\w]{{0,40}}{compact_label}",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = _decimal_or_none(match.group("value"))
            if value is not None:
                return value
    defaulted.append(name)
    return default


def _integer_assumption(
    question: str,
    labels: tuple[str, ...],
    default: int,
    *,
    defaulted: list[str],
    name: str,
    minimum: int,
    maximum: int,
) -> int:
    text = _metric_text(question)
    for label in labels:
        compact_label = re.escape(_metric_text(label))
        patterns = (
            rf"{compact_label}[^\d]{{0,40}}(?P<value>\d{{1,2}})\s*(?:year|years|yr|yrs)?",
            rf"(?P<value>\d{{1,2}})\s*(?:year|years|yr|yrs)[^\w]{{0,40}}{compact_label}",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = int(match.group("value"))
            return max(minimum, min(maximum, value))
    defaulted.append(name)
    return default


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
    diagnostics_payload = dict(diagnostics or {})
    return FinanceFormulaPlan(
        status="ready",
        formula_name=formula_name,
        payload={
            "expression": expression,
            "variables": variables,
            "unit": unit,
            "formula_name": formula_name,
            "input_fact_ids": input_fact_ids,
            "diagnostics": diagnostics_payload,
        },
        input_fact_ids=input_fact_ids,
        diagnostics=diagnostics_payload,
    )


def _missing(
    formula_name: str,
    missing: list[str],
    *,
    facts: list[FinanceFact] | None = None,
    diagnostics: JsonObject | None = None,
) -> FinanceFormulaPlan:
    return FinanceFormulaPlan(
        status="missing_facts",
        formula_name=formula_name,
        missing_facts=missing,
        input_fact_ids=[fact.fact_id for fact in facts or []],
        diagnostics={"reason": "insufficient_formula_inputs", **dict(diagnostics or {})},
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


def _latest_fact_for_year(
    facts: list[FinanceFact],
    markers: tuple[str, ...],
    *,
    target_year: int | None,
    exclude_fact_ids: set[str] | None = None,
    predicate=None,
) -> FinanceFact | None:
    excluded = exclude_fact_ids or set()
    matches = [fact for fact in _facts_for_metric(facts, markers) if fact.fact_id not in excluded]
    if predicate is not None:
        matches = [fact for fact in matches if predicate(fact)]
    if not matches:
        return None
    if target_year is not None:
        target_matches = [
            fact
            for fact in matches
            if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
        ]
        if not target_matches:
            return None
        return _sort_facts(target_matches)[-1]
    return _sort_facts(matches)[-1]


def _latest_revenue_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    matches = [
        fact
        for fact in _facts_for_metric(
            facts,
            ("revenue", "revenues", "net sales", "net revenues", "total revenues", "sales"),
        )
        if _is_revenue_fact(fact)
    ]
    if not matches:
        return None
    if target_year is not None:
        matches = [
            fact
            for fact in matches
            if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
        ]
        if not matches:
            return None
    return sorted(matches, key=_revenue_fact_sort_key)[-1]


def _is_revenue_fact(fact: FinanceFact) -> bool:
    texts = [
        _metric_text(fact.metric),
        _metric_text(str(fact.metadata.get("label") or "")),
        _metric_text(str(fact.metadata.get("concept") or "")),
    ]
    blocked = ("cost of revenue", "costofrevenue", "expense", "interest income")
    if any(any(marker in text for marker in blocked) for text in texts):
        return False
    exact = {
        "revenue",
        "revenues",
        "net sales",
        "net revenues",
        "total revenue",
        "total revenues",
        "sales",
        "sales revenue net",
        "sales revenue services net",
    }
    return any(text in exact for text in texts)


def _revenue_fact_sort_key(fact: FinanceFact) -> tuple[int, Decimal, int, str, str, str]:
    value = _decimal_or_none(fact.value) or Decimal(0)
    return (
        _revenue_concept_priority(fact),
        abs(value),
        fact.fiscal_year or 0,
        str(fact.metadata.get("end") or ""),
        str(fact.metadata.get("filed") or ""),
        fact.fact_id,
    )


def _revenue_concept_priority(fact: FinanceFact) -> int:
    concept = _metric_text(str(fact.metadata.get("concept") or ""))
    label = _metric_text(str(fact.metadata.get("label") or ""))
    metric = _metric_text(fact.metric)
    demoted_markers = (
        "fair value",
        "liability revenue recognized",
        "unearned",
        "deferred",
        "tax",
        "segment",
    )
    if any(marker in label or marker in concept for marker in demoted_markers):
        return -10
    primary_concepts = {
        "revenues": 100,
        "revenuefromcontractwithcustomerexcludingassessedtax": 98,
        "revenuefromcontractwithcustomerincludingassessedtax": 96,
        "salesrevenuegoodsnet": 94,
        "salesrevenueservicesnet": 92,
        "salesrevenuenet": 90,
        "salesandotheroperatingrevenue": 88,
        "operatingrevenues": 86,
    }
    compact_concept = concept.replace(" ", "")
    if compact_concept in primary_concepts:
        return primary_concepts[compact_concept]
    if metric in {"revenue", "revenues", "total revenue", "total revenues", "net sales", "net revenues", "sales"}:
        return 10
    return 0


def _latest_cash_fact(facts: list[FinanceFact]) -> FinanceFact | None:
    cash_metrics = {"cash", "cash and equivalents", "cash and cash equivalents", "cash equivalents", "total cash"}
    matches = [fact for fact in facts if _metric_text(fact.metric) in cash_metrics]
    if not matches:
        matches = [
            fact
            for fact in facts
            if _metric_text(str(fact.metadata.get("label") or "")) in cash_metrics
            or _metric_text(str(fact.metadata.get("concept") or "")) in cash_metrics
        ]
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


def _fact_sort_token(fact: FinanceFact | None) -> tuple[int, str, str, str]:
    if fact is None:
        return (0, "", "", "")
    return (
        fact.fiscal_year or 0,
        str(fact.metadata.get("end") or ""),
        str(fact.metadata.get("filed") or ""),
        fact.fact_id,
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
