from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace


FormulaPlanStatus = Literal["ready", "missing_facts", "not_applicable"]

_PPE_NET_METRICS = (
    "property plant and equipment net",
    "property, plant and equipment net",
    "property, plant, and equipment net",
    "net property plant and equipment",
    "net property, plant and equipment",
    "net property, plant, and equipment",
    "net ppne",
    "ppne",
)


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
        return _plan_margin(question=question, facts=usable)
    if formula == "bps_difference":
        return _plan_bps_difference(usable)
    if formula == "ev_revenue":
        return _plan_ev_revenue(question=question, facts=usable)
    if formula == "ev_ebitda":
        return _plan_ev_ebitda(usable)
    if formula == "fixed_charge_coverage":
        return _plan_fixed_charge_coverage(question=question, facts=usable)
    if formula == "mlr_rebate":
        return _plan_mlr_rebate(question=question, facts=usable)
    if formula == "purchase_price_allocation":
        return _plan_purchase_price_allocation(question=question, facts=usable)
    if formula == "dio":
        return _plan_dio(question=question, facts=usable)
    if formula == "dpo":
        return _plan_dpo(question=question, facts=usable, inventory_adjusted=False)
    if formula == "dpo_inventory_adjusted":
        return _plan_dpo(question=question, facts=usable, inventory_adjusted=True)
    if formula == "average_capex_to_revenue":
        return _plan_average_capex_to_revenue(question=question, facts=usable)
    if formula == "effective_tax_rate_change":
        return _plan_effective_tax_rate_change(question=question, facts=usable)
    if formula == "interest_coverage_ratio":
        return _plan_interest_coverage_ratio(question=question, facts=usable)
    if formula == "unadjusted_ebitda":
        return _plan_unadjusted_ebitda(question=question, facts=usable, less_capex=False)
    if formula == "unadjusted_ebitda_less_capex":
        return _plan_unadjusted_ebitda(question=question, facts=usable, less_capex=True)
    if formula == "asset_turnover":
        return _plan_asset_turnover(question=question, facts=usable)
    if formula == "average_cogs_to_revenue":
        return _plan_average_cogs_to_revenue(question=question, facts=usable)
    if formula == "liquidation_value_per_share":
        return _plan_liquidation_value_per_share(question=question, facts=usable)
    if formula == "debt_change":
        return _plan_debt_change(question=question, facts=usable)
    if formula == "component_percent_of_total":
        return _plan_component_percent_of_total(question=question, facts=usable)
    if formula == "cash_and_equivalents_change":
        return _plan_period_change(
            question=question,
            facts=usable,
            formula_name="cash_and_equivalents_change",
            markers=("cash and cash equivalents", "cash equivalents", "cash and equivalents"),
            prior_slot="cash_and_equivalents_prior",
            current_slot="cash_and_equivalents_current",
            unit="currency",
            formula_definition="current cash and cash equivalents less prior cash and cash equivalents",
        )
    if formula == "market_risk_var_change":
        return _plan_period_change(
            question=question,
            facts=usable,
            formula_name="market_risk_var_change",
            markers=("value at risk", "var", "market risk"),
            prior_slot="market_risk_var_prior",
            current_slot="market_risk_var_current",
            unit="currency",
            formula_definition="current value at risk less prior-period value at risk",
        )
    if formula == "percent_of_sales_change":
        return _plan_period_change(
            question=question,
            facts=usable,
            formula_name="percent_of_sales_change",
            markers=("as a percent of sales", "as a percent of net sales", "percent of sales", "percent of net sales"),
            prior_slot="prior_percent_of_sales",
            current_slot="current_percent_of_sales",
            unit="percent",
            formula_definition="current metric as a percent of sales less prior metric as a percent of sales",
        )
    if formula == "property_plant_and_equipment_change":
        return _plan_period_change(
            question=question,
            facts=usable,
            formula_name="property_plant_and_equipment_change",
            markers=_PPE_NET_METRICS,
            prior_slot="property_plant_and_equipment_net_prior",
            current_slot="property_plant_and_equipment_net_current",
            unit="currency",
            formula_definition="current net property, plant, and equipment less prior net property, plant, and equipment",
        )
    if formula == "store_count_change":
        return _plan_period_change(
            question=question,
            facts=usable,
            formula_name="store_count_change",
            markers=("stores", "store count", "number of stores"),
            prior_slot="store_count_prior",
            current_slot="store_count_current",
            unit="count",
            formula_definition="current store count less prior store count",
        )
    if formula == "cash_flow_activity_comparison":
        return _plan_cash_flow_activity_comparison(question=question, facts=usable)
    if formula == "margin_profile_change":
        return _plan_margin_series(question=question, facts=usable, formula_name="margin_profile_change", mode="change")
    if formula == "margin_consistency_range":
        return _plan_margin_series(question=question, facts=usable, formula_name="margin_consistency_range", mode="range")
    if formula == "category_metric_rank":
        return _plan_category_metric_rank(question=question, facts=usable)
    if formula == "metric_lookup":
        return _plan_metric_lookup(question=question, facts=usable)
    if formula == "disclosure_lookup":
        return _plan_disclosure_lookup(question=question)
    if formula == "yoy_growth":
        return _plan_yoy_growth(question=question, facts=usable)
    if formula == "debt_to_equity":
        return _plan_debt_to_equity(question=question, facts=usable)
    if formula == "bridge_subtotal":
        return _plan_bridge_subtotal(usable)
    if formula == "dcf":
        return _plan_dcf(question=question, facts=usable)
    if formula == "lbo":
        return _plan_lbo(question=question, facts=usable)
    if formula == "capital_intensity":
        return _plan_capital_intensity(question=question, facts=usable)
    if formula == "fixed_asset_turnover":
        return _plan_fixed_asset_turnover(question=question, facts=usable)
    if formula == "operating_cash_flow_ratio":
        return _plan_operating_cash_flow_ratio(question=question, facts=usable)
    if formula == "quick_ratio":
        return _plan_quick_ratio(question=question, facts=usable)
    if formula == "working_capital_ratio":
        return _plan_working_capital_ratio(question=question, facts=usable)
    if formula == "net_working_capital":
        return _plan_net_working_capital(question=question, facts=usable)
    if formula == "return_on_assets":
        return _plan_return_on_assets(question=question, facts=usable)
    if formula == "free_cash_flow":
        return _plan_free_cash_flow(question=question, facts=usable)
    if formula == "inventory_turnover":
        return _plan_inventory_turnover(question=question, facts=usable)
    if formula == "dividend_payout_ratio":
        return _plan_dividend_payout_ratio(question=question, facts=usable)
    if formula == "retention_ratio":
        return _plan_retention_ratio(question=question, facts=usable)
    return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "unsupported_formula", "formula": formula})


def _detect_formula(question: str) -> str | None:
    text = str(question or "").lower()
    compact = text.replace(" ", "")
    if "cagr" in text or "compound annual growth" in text:
        return "cagr"
    if "dio" in text or "days inventory" in text or "days inventory outstanding" in text:
        return "dio"
    if "dpo" in text or "days payable" in text or "days payable outstanding" in text:
        if "change in inventory" in text or "change in inventories" in text:
            return "dpo_inventory_adjusted"
        return "dpo"
    if _looks_like_average_capex_to_revenue(text):
        return "average_capex_to_revenue"
    if "effective tax rate" in text and any(marker in text for marker in ("change", "changed", "compare", "between", "increase", "decrease")):
        return "effective_tax_rate_change"
    if "positive working capital" in text:
        return "net_working_capital"
    if "interest coverage ratio" in text or "interest coverage" in text:
        return "interest_coverage_ratio"
    if _looks_like_unadjusted_ebitda(text):
        if "less capex" in text or "less capital expenditure" in text or "less capital expenditures" in text:
            return "unadjusted_ebitda_less_capex"
        return "unadjusted_ebitda"
    if "asset turnover" in text and "fixed asset" not in text and "fixed-asset" not in text:
        return "asset_turnover"
    if _looks_like_average_cogs_to_revenue(text):
        return "average_cogs_to_revenue"
    if "liquidated all" in text or "liquidation" in text or "pay its shareholders" in text:
        return "liquidation_value_per_share"
    if "debt" in text and any(marker in text for marker in ("increase", "increased", "decrease", "changed", "between")) and "balance sheet" in text:
        return "debt_change"
    if _looks_like_component_percent_of_total(text):
        return "component_percent_of_total"
    if _looks_like_cash_and_equivalents_change(text):
        return "cash_and_equivalents_change"
    if _looks_like_market_risk_var_change(text):
        return "market_risk_var_change"
    if _looks_like_percent_of_sales_change(text):
        return "percent_of_sales_change"
    if _looks_like_property_plant_and_equipment_change(text):
        return "property_plant_and_equipment_change"
    if _looks_like_store_count_change(text):
        return "store_count_change"
    if _looks_like_cash_flow_activity_comparison(text):
        return "cash_flow_activity_comparison"
    if _looks_like_margin_consistency(text):
        return "margin_consistency_range"
    if _looks_like_margin_profile_change(text):
        return "margin_profile_change"
    if "discounted cash flow" in text or re.search(r"\bdcf\b", text):
        return "dcf"
    if re.search(r"\blbo\b", text) or "leveraged buyout" in text:
        return "lbo"
    if "capital-intensive" in text or "capital intensive" in text or "capital intensity" in text:
        return "capital_intensity"
    if "fixed asset turnover" in text or "fixed-asset turnover" in text:
        return "fixed_asset_turnover"
    if (
        "operating cash flow ratio" in text
        or "cash flow ratio" in text
        or (
            any(marker in text for marker in ("cash from operations", "cash flow from operations", "operating cash flow"))
            and "current liabilities" in text
            and "ratio" in text
        )
    ):
        return "operating_cash_flow_ratio"
    if "quick ratio" in text:
        return "quick_ratio"
    if "working capital ratio" in text:
        return "working_capital_ratio"
    if "net working capital" in text:
        return "net_working_capital"
    if "return on assets" in text or re.search(r"\broa\b", text):
        return "return_on_assets"
    if "free cash flow" in text or "free cashflow" in text or re.search(r"\bfcf\b", text):
        return "free_cash_flow"
    if "inventory turnover" in text:
        return "inventory_turnover"
    if "dividend payout ratio" in text or "payout ratio" in text:
        return "dividend_payout_ratio"
    if "retention ratio" in text:
        return "retention_ratio"
    if "ev/revenue" in compact or "ev/rev" in compact or "enterprise value to revenue" in text:
        return "ev_revenue"
    if "ev/ebitda" in compact or "enterprise value to ebitda" in text:
        return "ev_ebitda"
    if "fixed charge" in text or "fixed-charge" in text or "earnings to fixed charges" in text:
        return "fixed_charge_coverage"
    if re.search(r"\bmlr\b", text) or "medical loss ratio" in text:
        return "mlr_rebate"
    if (
        "purchase price allocation" in text
        or "purchase-price allocation" in text
        or re.search(r"\bppa\b", text)
        or "allocation of purchase price" in text
        or "allocated purchase price" in text
        or (
            any(marker in text for marker in ("business combination", "purchase accounting", "acquisition accounting"))
            and any(marker in text for marker in ("goodwill", "intangible", "consideration"))
        )
    ):
        return "purchase_price_allocation"
    if "debt-to-equity" in text or "debt to equity" in text or "debt/equity" in compact:
        return "debt_to_equity"
    if "basis point" in text or "bps" in text:
        return "bps_difference"
    if "bridge" in text or "add-back" in text or "add back" in text or "addback" in text:
        return "bridge_subtotal"
    if _looks_like_category_metric_rank(text):
        return "category_metric_rank"
    if _looks_like_metric_lookup(text):
        return "metric_lookup"
    if _looks_like_disclosure_lookup(text):
        return "disclosure_lookup"
    if "yoy" in text or "year-over-year" in text or "year over year" in text:
        return "yoy_growth"
    if _source_grounded_explanation_intent(text) and not _explicit_calculation_intent(text):
        return None
    if "margin" in text or "利润率" in text:
        return "margin"
    if "growth rate" in text or "增长率" in text or ("growth" in text and len(re.findall(r"\b(?:19|20)\d{2}\b", text)) >= 2):
        return "yoy_growth"
    return None


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


def _looks_like_average_capex_to_revenue(text: str) -> bool:
    if not ("capex" in text or "capital expenditure" in text or "capital expenditures" in text):
        return False
    if not ("revenue" in text or "sales" in text):
        return False
    if not (
        "average" in text
        or "avg" in text
        or "as a % of revenue" in text
        or "as percent of revenue" in text
        or "as percentage of revenue" in text
        or "capex/revenue" in text.replace(" ", "")
    ):
        return False
    return True


def _looks_like_unadjusted_ebitda(text: str) -> bool:
    if "unadjusted ebitda" in text:
        return True
    return (
        "operating income" in text
        and ("depreciation and amortization" in text or "depreciation & amortization" in text or "d&a" in text)
    )


def _looks_like_average_cogs_to_revenue(text: str) -> bool:
    if not ("cost of goods sold" in text or "cost of sales" in text or "cost of revenue" in text or "cogs" in text):
        return False
    if not ("revenue" in text or "sales" in text):
        return False
    return "average" in text or "avg" in text or "as a % of revenue" in text or "as a percent of revenue" in text


def _looks_like_component_percent_of_total(text: str) -> bool:
    if "what percent" not in text and "what percentage" not in text:
        return False
    if "total" not in text:
        return False
    return any(marker in text for marker in ("occurred in", "represented", "of total", "spend on", "stock repurchase", "share repurchase"))


def _looks_like_cash_and_equivalents_change(text: str) -> bool:
    if not any(marker in text for marker in ("cash and cash equivalents", "cash & cash equivalents", "cash equivalents")):
        return False
    return any(marker in text for marker in ("drop", "dropped", "increase", "increased", "decrease", "decreased", "change", "changed", "between"))


def _looks_like_market_risk_var_change(text: str) -> bool:
    if not ("value at risk" in text or re.search(r"\bvar\b", text)):
        return False
    return any(marker in text for marker in ("decrease", "decreased", "increase", "increased", "compared", "prior year", "year over year", "year-over-year"))


def _looks_like_percent_of_sales_change(text: str) -> bool:
    if "what drove" in text or "driver" in text:
        return False
    if not any(marker in text for marker in ("as a percent of sales", "as a percent of net sales", "percent of sales", "percent of net sales")):
        return False
    return any(marker in text for marker in ("increase", "increased", "decrease", "decreased", "change", "changed", "compared"))


def _looks_like_property_plant_and_equipment_change(text: str) -> bool:
    if "turnover" in text:
        return False
    if not any(marker in text for marker in ("ppne", "pp&e", "ppe", "property plant and equipment", "property, plant and equipment")):
        return False
    return any(marker in text for marker in ("grow", "grew", "increase", "increased", "decrease", "decreased", "change", "changed"))


def _looks_like_store_count_change(text: str) -> bool:
    if not any(marker in text for marker in ("number of stores", "store count", "stores between")):
        return False
    return any(marker in text for marker in ("change", "changed", "increase", "decrease", "between"))


def _looks_like_cash_flow_activity_comparison(text: str) -> bool:
    return (
        ("operations, investing, and financing" in text or "operating, investing, and financing" in text)
        and any(marker in text for marker in ("brought in the most", "lost the least", "which brought", "among"))
        and "cash flow" in text
    )


def _looks_like_category_metric_rank(text: str) -> bool:
    rank_markers = (
        "highest",
        "lowest",
        "largest",
        "smallest",
        "best",
        "worst",
        "most",
        "least",
        "dragged down",
        "biggest drop",
        "largest drop",
        "largest decline",
        "steepest decline",
        "proportionally increase",
        "proportionally increased",
        "performed the best",
    )
    if not any(marker in text for marker in rank_markers):
        return False
    if "registered to trade" in text or "registered on a national securities exchange" in text:
        return False
    category_markers = (
        "segment",
        "region",
        "geographic",
        "product category",
        "service category",
        "category",
        "among",
        "derivative instrument",
        "notional value",
        "short term investments",
        "short-term investments",
        "type of debt",
        "liability",
        "liabilities",
        "topline",
        "ebitdar",
    )
    return any(marker in text for marker in category_markers)


def _looks_like_metric_lookup(text: str) -> bool:
    if _metric_lookup_spec(text) is None:
        return False
    if re.search(r"\b(?:ratio|turnover|margin|growth)\b", text) or any(
        marker in text for marker in ("as a percent", "as a percentage", "as %")
    ):
        return False
    lookup_markers = (
        "what is",
        "what was",
        "how much",
        "how many",
        "quantity",
        "amount",
        "total amount",
        "year end",
        "at the end",
        "generated in cash flow",
        "pay out",
        "paid out",
        "expected to pay",
        "state answer",
        "answer in",
    )
    return any(marker in text for marker in lookup_markers)


def _looks_like_disclosure_lookup(text: str) -> bool:
    return _disclosure_lookup_spec(text) is not None


def _looks_like_margin_consistency(text: str) -> bool:
    if not _mentions_operating_or_gross_margin(text):
        return False
    return "historically consistent" in text or "consistent" in text or "fluctuat" in text


def _looks_like_margin_profile_change(text: str) -> bool:
    if not _mentions_operating_or_gross_margin(text):
        return False
    return any(marker in text for marker in ("profile", "what drove", "drove", "driver", "change as of", "improving"))


def _mentions_operating_or_gross_margin(text: str) -> bool:
    return (
        "operating margin" in text
        or "gross margin" in text
        or "gross margins" in text
        or "operating margins" in text
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


def _plan_yoy_growth(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    normalized = " ".join(str(question or "").lower().split())
    markers = ("revenue", "net sales", "net income", "operating income", "ebitda")
    predicate = None
    if "net income" in normalized or "net earnings" in normalized:
        markers = ("net income",)
        predicate = _is_net_income_fact
    elif "operating income" in normalized:
        markers = ("operating income",)
    elif "ebitda" in normalized:
        markers = ("ebitda",)
    elif "net sales" in normalized:
        markers = ("net sales",)
    elif "revenue" in normalized or "revenues" in normalized:
        markers = ("revenue", "net sales", "net revenues")
    pair = _first_metric_pair(facts, markers, predicate=predicate)
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


def _plan_margin(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    normalized = " ".join(str(question or "").lower().split())
    target_year = _target_fiscal_year(question)
    denominator = _latest_revenue_fact(facts, target_year=target_year)
    numerator: FinanceFact | None
    extra_facts: list[FinanceFact] = []
    expression = "numerator / denominator"
    variables: JsonObject
    if "cogs" in normalized or "cost of goods sold" in normalized or "cost of revenue" in normalized:
        numerator = _latest_fact_for_year(
            facts,
            ("cost of revenue", "cost of sales", "cost of goods sold", "cogs"),
            target_year=target_year,
        )
        missing_numerator = "cogs_numerator"
    elif "gross margin" in normalized or "gross profit margin" in normalized:
        numerator = _latest_fact_for_year(facts, ("gross profit",), target_year=target_year)
        if numerator is None:
            cost = _latest_fact_for_year(
                facts,
                ("cost of revenue", "cost of sales", "cost of goods sold", "cogs"),
                target_year=target_year,
            )
            if denominator is not None and cost is not None:
                expression = "(denominator - cost_of_revenue) / denominator"
                variables = {"denominator": denominator.value, "cost_of_revenue": cost.value}
                return _ready(
                    "margin",
                    expression,
                    variables,
                    unit="percent",
                    facts=[denominator, cost],
                )
        missing_numerator = "gross_profit_numerator"
    elif "operating margin" in normalized:
        numerator = _latest_fact_for_year(facts, ("operating income",), target_year=target_year)
        missing_numerator = "operating_income_numerator"
    elif "net profit margin" in normalized or "net margin" in normalized or "profit margin" in normalized:
        numerator = _latest_fact_for_year(
            facts,
            ("net income",),
            target_year=target_year,
            predicate=_is_net_income_fact,
        )
        missing_numerator = "net_income_numerator"
    else:
        numerator = _latest_fact_for_year(
            facts,
            ("net income", "operating income", "adjusted ebitda", "ebitda"),
            target_year=target_year,
        )
        missing_numerator = "margin_numerator"
    missing = []
    if numerator is None:
        missing.append(missing_numerator)
    if denominator is None:
        missing.append("revenue_denominator")
    if missing:
        return _missing("margin", missing, facts=[item for item in (numerator, denominator, *extra_facts) if item is not None])
    variables = {"numerator": numerator.value, "denominator": denominator.value}
    return _ready(
        "margin",
        expression,
        variables,
        unit="percent",
        facts=[numerator, denominator],
    )


def _plan_debt_to_equity(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    numerator = _latest_fact_for_year(facts, ("liabilities",), target_year=target_year)
    if numerator is None:
        numerator = _latest_fact_for_year(facts, ("debt", "long-term debt", "short-term debt"), target_year=target_year)
    denominator = _latest_fact_for_year(
        facts,
        ("shareholders equity", "stockholders equity", "equity"),
        target_year=target_year,
    )
    missing = []
    if numerator is None:
        missing.append("liabilities_or_debt")
    if denominator is None:
        missing.append("shareholders_equity")
    if missing:
        return _missing("debt_to_equity", missing, facts=[item for item in (numerator, denominator) if item is not None])
    return _ready(
        "debt_to_equity",
        "liabilities_or_debt / shareholders_equity",
        {"liabilities_or_debt": numerator.value, "shareholders_equity": denominator.value},
        unit="ratio",
        facts=[numerator, denominator],
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "selected balance-sheet numerator divided by shareholders' equity",
            "numerator_slot": _debt_to_equity_numerator_slot(numerator),
            "denominator_slot": "shareholders_equity",
            "bound_line_items": {
                "numerator": _formula_bound_line_item(numerator),
                "denominator": _formula_bound_line_item(denominator),
            },
            "answer_wording_policy": (
                "Name the selected numerator line item when presenting the ratio. "
                "If the numerator is total liabilities, describe the calculation as liabilities-to-equity or debt-to-equity using total liabilities; "
                "do not silently present it as debt-only."
            ),
        },
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
        _PPE_NET_METRICS,
        target_year=target_year,
    )
    assets = _latest_fact_for_year(facts, ("assets", "total assets"), target_year=target_year)
    net_income = _latest_fact_for_year(
        facts,
        ("net income",),
        target_year=target_year,
        predicate=_is_net_income_fact,
    )
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
    if net_income is None:
        missing.append("net_income")
    if missing:
        return _missing(
            "capital_intensity",
            missing,
            facts=[item for item in (capex, revenue, operating_cash_flow, ppe, assets, net_income) if item is not None],
            diagnostics={
                "required_ratios": ["capex_to_revenue", "capex_to_operating_cash_flow", "ppe_to_assets", "return_on_assets"],
                "reason": "capital_intensity_requires_multiple_balance_sheet_and_cash_flow_slots",
                "target_fiscal_year": target_year,
            },
        )
    capex_value = _decimal_or_none(_absolute_decimal_string(capex.value))
    revenue_value = _decimal_or_none(revenue.value)
    operating_cash_flow_value = _decimal_or_none(operating_cash_flow.value)
    ppe_value = _decimal_or_none(ppe.value)
    assets_value = _decimal_or_none(assets.value)
    net_income_value = _decimal_or_none(net_income.value)
    model_outputs = {
        "capex_to_revenue": _ratio_decimal_string(capex_value, revenue_value),
        "capex_to_operating_cash_flow": _ratio_decimal_string(capex_value, operating_cash_flow_value),
        "ppe_to_assets": _ratio_decimal_string(ppe_value, assets_value),
        "return_on_assets": _ratio_decimal_string(net_income_value, assets_value),
    }
    return _ready(
        "capital_intensity",
        "capital_expenditures / revenue",
        {
            "capital_expenditures": _absolute_decimal_string(capex.value),
            "revenue": revenue.value,
            "operating_cash_flow": operating_cash_flow.value,
            "property_plant_and_equipment_net": ppe.value,
            "assets": assets.value,
            "net_income": net_income.value,
        },
        unit="percent",
        facts=[capex, revenue, operating_cash_flow, ppe, assets, net_income],
        diagnostics={
            "required_ratios": ["capex_to_revenue", "capex_to_operating_cash_flow", "ppe_to_assets", "return_on_assets"],
            "secondary_expressions": {
                "capex_to_operating_cash_flow": "capital_expenditures / operating_cash_flow",
                "ppe_to_assets": "property_plant_and_equipment_net / assets",
                "return_on_assets": "net_income / assets",
            },
            "model_outputs": {key: value for key, value in model_outputs.items() if value is not None},
            "target_fiscal_year": target_year,
        },
    )


def _plan_fixed_asset_turnover(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    revenue = _latest_revenue_fact(facts, target_year=target_year)
    ppe_current = _latest_fact_for_year(facts, _PPE_NET_METRICS, target_year=target_year)
    ppe_prior = _latest_fact_for_year(
        facts,
        _PPE_NET_METRICS,
        target_year=target_year - 1 if target_year is not None else None,
        exclude_fact_ids={ppe_current.fact_id} if ppe_current is not None else None,
    )
    missing: list[str] = []
    if revenue is None:
        missing.append("revenue")
    if ppe_current is None:
        missing.append("property_plant_and_equipment_net_current")
    if ppe_prior is None:
        missing.append("property_plant_and_equipment_net_prior")
    supporting = [item for item in (revenue, ppe_current, ppe_prior) if item is not None]
    if missing:
        return _missing(
            "fixed_asset_turnover",
            missing,
            facts=supporting,
            diagnostics={
                "reason": "fixed_asset_turnover_requires_revenue_and_average_ppe",
                "target_fiscal_year": target_year,
            },
        )
    return _ready(
        "fixed_asset_turnover",
        "revenue / ((property_plant_and_equipment_net_current + property_plant_and_equipment_net_prior) / 2)",
        {
            "revenue": revenue.value,
            "property_plant_and_equipment_net_current": ppe_current.value,
            "property_plant_and_equipment_net_prior": ppe_prior.value,
        },
        unit="x",
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "revenue divided by average net property, plant, and equipment",
        },
    )


def _plan_operating_cash_flow_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    operating_cash_flow = _latest_fact_for_year(
        facts,
        (
            "operating cash flow",
            "cash flow from operations",
            "cash from operations",
            "net cash provided by operating activities",
        ),
        target_year=target_year,
    )
    current_liabilities = _latest_fact_for_year(
        facts,
        (
            "total current liabilities",
            "current liabilities",
            "liabilities current",
        ),
        target_year=target_year,
    )
    missing: list[str] = []
    supporting = [item for item in (operating_cash_flow, current_liabilities) if item is not None]
    if operating_cash_flow is None:
        missing.append("operating_cash_flow")
    if current_liabilities is None:
        missing.append("total_current_liabilities")
    if missing:
        return _missing(
            "operating_cash_flow_ratio",
            missing,
            facts=supporting,
            diagnostics={
                "reason": "operating_cash_flow_ratio_requires_cash_flow_and_current_liabilities",
                "target_fiscal_year": target_year,
                "formula_definition": "cash from operations divided by total current liabilities",
            },
        )
    return _ready(
        "operating_cash_flow_ratio",
        "operating_cash_flow / total_current_liabilities",
        {
            "operating_cash_flow": operating_cash_flow.value,
            "total_current_liabilities": current_liabilities.value,
        },
        unit="ratio",
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "cash from operations divided by total current liabilities",
            "bound_line_items": {
                "numerator": _formula_bound_line_item(operating_cash_flow),
                "denominator": _formula_bound_line_item(current_liabilities),
            },
        },
    )


def _plan_quick_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    cash = _latest_fact_for_year(facts, ("cash and cash equivalents", "cash equivalents", "cash"), target_year=target_year)
    marketable = _latest_fact_for_year(
        facts,
        ("marketable securities", "short term investments", "short-term investments"),
        target_year=target_year,
    )
    receivables = _latest_fact_for_year(
        facts,
        ("accounts receivable", "receivables", "net accounts receivable"),
        target_year=target_year,
    )
    current_liabilities = _latest_fact_for_year(
        facts,
        ("total current liabilities", "current liabilities", "liabilities current"),
        target_year=target_year,
    )
    missing: list[str] = []
    if cash is None:
        missing.append("cash_and_equivalents")
    if marketable is None:
        missing.append("marketable_securities")
    if receivables is None:
        missing.append("accounts_receivable")
    if current_liabilities is None:
        missing.append("total_current_liabilities")
    supporting = [item for item in (cash, marketable, receivables, current_liabilities) if item is not None]
    if missing:
        return _missing(
            "quick_ratio",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "(cash and equivalents + marketable securities + accounts receivable) / total current liabilities",
            },
        )
    return _ready(
        "quick_ratio",
        "(cash_and_equivalents + marketable_securities + accounts_receivable) / total_current_liabilities",
        {
            "cash_and_equivalents": cash.value,
            "marketable_securities": marketable.value,
            "accounts_receivable": receivables.value,
            "total_current_liabilities": current_liabilities.value,
        },
        unit="ratio",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_working_capital_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    current_assets = _latest_fact_for_year(facts, ("total current assets", "current assets", "assets current"), target_year=target_year)
    current_liabilities = _latest_fact_for_year(
        facts,
        ("total current liabilities", "current liabilities", "liabilities current"),
        target_year=target_year,
    )
    missing: list[str] = []
    if current_assets is None:
        missing.append("total_current_assets")
    if current_liabilities is None:
        missing.append("total_current_liabilities")
    supporting = [item for item in (current_assets, current_liabilities) if item is not None]
    if missing:
        return _missing(
            "working_capital_ratio",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "total current assets divided by total current liabilities",
            },
        )
    return _ready(
        "working_capital_ratio",
        "total_current_assets / total_current_liabilities",
        {
            "total_current_assets": current_assets.value,
            "total_current_liabilities": current_liabilities.value,
        },
        unit="ratio",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_net_working_capital(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    current_assets = _latest_fact_for_year(facts, ("total current assets", "current assets", "assets current"), target_year=target_year)
    current_liabilities = _latest_fact_for_year(
        facts,
        ("total current liabilities", "current liabilities", "liabilities current"),
        target_year=target_year,
    )
    missing: list[str] = []
    if current_assets is None:
        missing.append("total_current_assets")
    if current_liabilities is None:
        missing.append("total_current_liabilities")
    supporting = [item for item in (current_assets, current_liabilities) if item is not None]
    if missing:
        return _missing(
            "net_working_capital",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "total current assets less total current liabilities",
            },
        )
    return _ready(
        "net_working_capital",
        "total_current_assets - total_current_liabilities",
        {
            "total_current_assets": current_assets.value,
            "total_current_liabilities": current_liabilities.value,
        },
        unit=current_assets.unit,
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_return_on_assets(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    normalized = _metric_text(question)
    net_income = _latest_fact_for_year(
        facts,
        ("net income", "net earnings"),
        target_year=target_year,
        predicate=_is_net_income_fact,
    )
    use_average_assets = "average" in normalized or "between" in normalized
    assets_current = _latest_fact_for_year(facts, ("assets", "total assets"), target_year=target_year)
    assets_prior = (
        _latest_fact_for_year(
            facts,
            ("assets", "total assets"),
            target_year=target_year - 1 if target_year is not None else None,
            exclude_fact_ids={assets_current.fact_id} if assets_current is not None else None,
        )
        if use_average_assets
        else None
    )
    missing: list[str] = []
    if net_income is None:
        missing.append("net_income")
    if assets_current is None:
        missing.append("assets_current" if use_average_assets else "assets")
    if use_average_assets and assets_prior is None:
        missing.append("assets_prior")
    supporting = [item for item in (net_income, assets_current, assets_prior) if item is not None]
    if missing:
        return _missing(
            "return_on_assets",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": (
                    "net income divided by average total assets"
                    if use_average_assets
                    else "net income divided by total assets"
                ),
            },
        )
    if use_average_assets:
        return _ready(
            "return_on_assets",
            "net_income / ((assets_current + assets_prior) / 2)",
            {"net_income": net_income.value, "assets_current": assets_current.value, "assets_prior": assets_prior.value},
            unit="percent",
            facts=supporting,
            diagnostics={"target_fiscal_year": target_year, "uses_average_assets": True},
        )
    return _ready(
        "return_on_assets",
        "net_income / assets",
        {"net_income": net_income.value, "assets": assets_current.value},
        unit="percent",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year, "uses_average_assets": False},
    )


def _plan_free_cash_flow(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    reported = _latest_fact_for_year(facts, ("free cash flow",), target_year=target_year)
    if reported is not None:
        return _ready(
            "free_cash_flow",
            "free_cash_flow",
            {"free_cash_flow": reported.value},
            unit=reported.unit,
            facts=[reported],
            diagnostics={"target_fiscal_year": target_year, "formula_definition": "reported free cash flow"},
        )
    operating_cash_flow = _latest_fact_for_year(
        facts,
        (
            "operating cash flow",
            "cash flow from operations",
            "cash from operations",
            "net cash provided by operating activities",
        ),
        target_year=target_year,
    )
    capex = _latest_fact_for_year(facts, ("capital expenditures", "capex"), target_year=target_year)
    missing: list[str] = []
    if operating_cash_flow is None:
        missing.append("operating_cash_flow")
    if capex is None:
        missing.append("capital_expenditures")
    supporting = [item for item in (operating_cash_flow, capex) if item is not None]
    if missing:
        return _missing(
            "free_cash_flow",
            missing,
            facts=supporting,
            diagnostics={"target_fiscal_year": target_year, "formula_definition": "operating cash flow less capital expenditures"},
        )
    return _ready(
        "free_cash_flow",
        "operating_cash_flow - capital_expenditures",
        {"operating_cash_flow": operating_cash_flow.value, "capital_expenditures": _absolute_decimal_string(capex.value)},
        unit=operating_cash_flow.unit,
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_inventory_turnover(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    inventory_facts = _dio_inventory_facts(facts)
    inventory_used = _dio_inventory_pair(inventory_facts, target_year=target_year)
    cogs = _dio_cogs_fact(facts, target_year=target_year)
    missing: list[str] = []
    if len(inventory_used) < 2:
        missing.extend(["inventory_begin", "inventory_end"] if not inventory_used else ["inventory_begin_or_end"])
    if cogs is None:
        missing.append("cogs")
    supporting = [*inventory_used, *([cogs] if cogs is not None else [])]
    if missing:
        return _missing(
            "inventory_turnover",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "cost of goods sold divided by average inventory",
            },
        )
    return _ready(
        "inventory_turnover",
        "cogs / ((inventory_begin + inventory_end) / 2)",
        {
            "cogs": cogs.value,
            "inventory_begin": inventory_used[0].value,
            "inventory_end": inventory_used[1].value,
        },
        unit="x",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_dividend_payout_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    dividends = _latest_fact_for_year(
        facts,
        ("dividends paid", "cash dividends paid", "dividends to shareholders"),
        target_year=target_year,
    )
    net_income = _latest_fact_for_year(
        facts,
        ("net income", "net earnings"),
        target_year=target_year,
        predicate=_is_net_income_fact,
    )
    missing: list[str] = []
    if dividends is None:
        missing.append("dividends_paid")
    if net_income is None:
        missing.append("net_income")
    supporting = [item for item in (dividends, net_income) if item is not None]
    if missing:
        return _missing(
            "dividend_payout_ratio",
            missing,
            facts=supporting,
            diagnostics={"target_fiscal_year": target_year, "formula_definition": "cash dividends paid divided by net income"},
        )
    return _ready(
        "dividend_payout_ratio",
        "dividends_paid / net_income",
        {"dividends_paid": _absolute_decimal_string(dividends.value), "net_income": net_income.value},
        unit="ratio",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_retention_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    payout = _plan_dividend_payout_ratio(question=question, facts=facts)
    if payout.status == "missing_facts":
        return FinanceFormulaPlan(
            status="missing_facts",
            formula_name="retention_ratio",
            missing_facts=list(payout.missing_facts),
            input_fact_ids=list(payout.input_fact_ids),
            diagnostics={**dict(payout.diagnostics), "formula_definition": "1 - cash dividends paid / net income"},
        )
    if payout.status != "ready" or not isinstance(payout.payload, dict):
        return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "dividend_payout_ratio_not_available"})
    variables = dict(payout.payload.get("variables")) if isinstance(payout.payload.get("variables"), dict) else {}
    return _ready(
        "retention_ratio",
        "1 - dividends_paid / net_income",
        variables,
        unit="ratio",
        facts=[fact for fact in facts if fact.fact_id in set(payout.input_fact_ids)],
        diagnostics={**dict(payout.diagnostics), "formula_definition": "1 - cash dividends paid / net income"},
    )


def _absolute_decimal_string(value: object) -> str:
    decimal = _decimal_or_none(value)
    if decimal is None:
        return str(value)
    return str(abs(decimal))


def _metric_lookup_spec(question: str) -> JsonObject | None:
    text = _metric_text(question)
    compact = text.replace(" ", "")
    if "capital expenditure" in text or "capital expenditures" in text or "capex" in text:
        return _lookup_spec("capital_expenditures", ("capital expenditures", "capex"), unit="currency")
    if any(
        marker in text
        for marker in (
            "net ppne",
            "net pp&e",
            "net ppe",
            "net property plant and equipment",
            "net property, plant, and equipment",
            "net property, plant and equipment",
        )
    ) or (
        ("property plant and equipment" in text or "property, plant, and equipment" in text or "property, plant and equipment" in text)
        and "net" in text
    ):
        return _lookup_spec("property_plant_and_equipment_net", _PPE_NET_METRICS, unit="currency")
    if "real change in sales" in text or "organic sales change" in text or (
        "sales" in text and "exclude the impact" in text and ("fx" in text or "foreign exchange" in text)
    ):
        return _lookup_spec("organic_sales_change", ("organic sales change", "real change in sales", "sales change excluding fx"), unit="percent")
    if "accounts receivable" in text or "net ar" in text or "net accounts receivable" in text:
        return _lookup_spec("accounts_receivable", ("accounts receivable", "net accounts receivable", "receivables"), unit="currency")
    if "accounts payable" in text:
        return _lookup_spec("accounts_payable", ("accounts payable", "trade accounts payable", "payables"), unit="currency")
    if "total current liabilities" in text or "current liabilities" in text or "liabilitiescurrent" in compact:
        return _lookup_spec("total_current_liabilities", ("total current liabilities", "current liabilities", "liabilities current"), unit="currency")
    if "total current assets" in text or "current assets" in text or "assetscurrent" in compact:
        return _lookup_spec("total_current_assets", ("total current assets", "current assets", "assets current"), unit="currency")
    if "total assets" in text:
        return _lookup_spec("assets", ("assets", "total assets"), unit="currency")
    if "inventor" in text:
        return _lookup_spec("inventory", ("inventory", "inventories", "merchandise inventories"), unit="currency")
    if "cost of goods sold" in text or "cost of sales" in text or "cost of revenue" in text or "cogs" in text:
        return _lookup_spec("cogs", ("cogs", "cost of sales", "cost of revenue", "cost of goods sold"), unit="currency")
    if "adjusted non gaap ebitda" in text or "adjusted ebitda" in text or "non gaap ebitda" in text:
        return _lookup_spec("adjusted_ebitda", ("adjusted ebitda", "non-gaap ebitda", "non gaap ebitda"), unit="currency")
    if "net income" in text or "net earnings" in text:
        return _lookup_spec("net_income", ("net income", "net earnings"), unit="currency", predicate="net_income")
    if any(marker in text for marker in ("cash flow from operating activities", "cash from operations", "operating cash flow")):
        return _lookup_spec(
            "operating_cash_flow",
            ("operating cash flow", "cash flow from operations", "net cash provided by operating activities"),
            unit="currency",
        )
    if "cash dividends" in text or "dividends paid" in text or "paid dividends" in text or "pay out in cash dividends" in text:
        return _lookup_spec("dividends_paid", ("dividends paid", "cash dividends paid", "dividends to shareholders"), unit="currency")
    if "restructuring cost" in text or "restructuring costs" in text or "restructuring expense" in text or "restructuring expenses" in text:
        return _lookup_spec(
            "restructuring_costs",
            ("restructuring costs", "restructuring expenses", "restructuring charges"),
            unit="currency",
        )
    if "gain accruing" in text or "gain on separation" in text:
        return _lookup_spec("gain_on_separation", ("gain on separation", "gain", "separation"), unit="currency")
    if "cash proceeds" in text or ("proceeds" in text and ("separation" in text or "kenvue" in text or "consumer health" in text)):
        return _lookup_spec("cash_proceeds", ("cash proceeds", "proceeds"), unit="currency")
    if "expect to pay" in text and ("spin off" in text or "spin-off" in text or "upjohn" in text or "separation" in text):
        return _lookup_spec(
            "separation_payment",
            ("expected payment", "expect to pay", "spin-off payment", "separation payment", "upjohn"),
            unit="currency",
        )
    if "value at risk" in text or re.search(r"\bvar\b", text):
        return _lookup_spec("market_risk_var", ("value at risk", "var", "market risk"), unit="currency")
    if "revolving credit" in text or "credit agreement" in text:
        return _lookup_spec("credit_facility", ("revolving credit agreement", "credit facility", "borrowings"), unit="currency")
    if "retirees" in text or "pension" in text or "postretirement" in text:
        return _lookup_spec(
            "pension_postretirement_payments",
            ("expected benefit payments", "retirees", "pension", "postretirement"),
            unit="currency",
        )
    return None


def _lookup_spec(slot_name: str, markers: tuple[str, ...], *, unit: str, predicate: str | None = None) -> JsonObject:
    return {
        "slot_name": slot_name,
        "markers": list(markers),
        "unit": unit,
        "predicate": predicate,
    }


def _disclosure_lookup_spec(question: str) -> JsonObject | None:
    text = _metric_text(question)
    if "debt securities" in text and ("registered to trade" in text or "national securities exchange" in text):
        return _disclosure_spec("registered_debt_securities", "registered_securities", "debt securities registered on national securities exchange")
    if "stable trend of dividend" in text or "dividend distribution" in text:
        return _disclosure_spec("dividend_distribution_history", "dividend_disclosure", "dividend distribution history")
    if "8k filing" in text or "8 k filing" in text or "8-k filing" in text or "key agenda" in text:
        return _disclosure_spec("filing_event_summary", "form_8k", "filing event")
    if "major acquisitions" in text or "companies acquired" in text or "main companies acquired" in text or "three main companies acquired" in text:
        return _disclosure_spec("acquisitions", "business_combinations", "acquisitions")
    if "what industry" in text or "primarily operate in" in text and "geograph" not in text:
        return _disclosure_spec("industry", "business", "industry")
    if "products and services" in text or "major products" in text or "product categories" in text or "service categories" in text:
        if "more than" in text and "revenue" in text:
            return _disclosure_spec("product_revenue_concentration", "business_or_segment_note", "product category revenue concentration")
        return _disclosure_spec("products_and_services", "business", "products and services")
    if "customer concentration" in text or "primary customers" in text:
        return _disclosure_spec("customers", "business", "customers")
    if "geographies" in text or "geographic" in text or "primarily operates in" in text:
        return _disclosure_spec("operating_geographies", "business", "geographic areas")
    if "retain card members" in text or "card members" in text or "customer retention" in text:
        return _disclosure_spec("customer_retention", "md&a_or_business", "customer retention")
    if "cyclicality" in text or "cyclical" in text:
        return _disclosure_spec("business_cyclicality", "risk_factors_or_md&a", "cyclicality")
    if "production rate" in text:
        return _disclosure_spec("production_rates", "md&a_or_business_outlook", "production rates")
    if "legal battle" in text or "legal proceedings" in text or "litigation" in text:
        return _disclosure_spec("material_legal_proceedings", "legal_proceedings", "material legal proceedings")
    if ("value at risk" in text or re.search(r"\bvar\b", text)) and any(marker in text for marker in ("decrease", "increase", "compared", "prior year")):
        return _disclosure_spec("market_risk_var", "market_risk_disclosures", "value at risk")
    if "paid dividends" in text or "dividends to common shareholders" in text:
        return _disclosure_spec("dividends_disclosure", "dividend_disclosure_or_cash_flow_statement", "dividends to common shareholders")
    if "previous ceo experience" in text or "new ceo" in text or "board member" in text or "nominees" in text:
        if "votes against" in text:
            return _disclosure_spec("shareholder_vote_results", "proxy_or_8k_voting_results", "shareholder vote")
        return _disclosure_spec("governance_disclosure", "proxy_statement", "directors and executive officers")
    if "shareholder vote" in text or "shareholder proposal" in text or "agm" in text:
        return _disclosure_spec("shareholder_vote_results", "proxy_or_8k_voting_results", "shareholder vote")
    if "guidance" in text or "adjusted eps expected" in text:
        if "percentage points" in text:
            return _disclosure_spec("guidance_change", "earnings_release_or_md&a", "guidance change")
        return _disclosure_spec("guidance", "earnings_release_or_md&a", "guidance")
    if "discontinued operation" in text or "spinning off" in text or "spin off" in text or "spin-off" in text or "upjohn" in text:
        return _disclosure_spec("separation_or_discontinued_operation", "business_combinations_or_subsequent_events", "separation or discontinued operation")
    if "standard business operations" in text or "substantially increased net income" in text:
        return _disclosure_spec("nonrecurring_events", "md&a_or_income_statement_note", "nonrecurring events")
    if "what drove" in text or "why did" in text or "why " in text:
        if "inventory" in text or "inventories" in text:
            return _disclosure_spec("inventory_driver_discussion", "md&a_or_inventory_note", "inventory balance drivers")
        if "sg&a" in text or "selling general" in text or "expense" in text or "wages" in text:
            return _disclosure_spec("expense_driver_discussion", "md&a_or_income_statement", "expense drivers")
        if "guidance" in text:
            return _disclosure_spec("guidance", "earnings_release_or_md&a", "guidance")
        return _disclosure_spec("revenue_driver_discussion", "md&a", "revenue drivers")
    if "us sales growth" in text or "international sales growth" in text or "sales growth compare" in text:
        return _disclosure_spec("geographic_sales_growth", "md&a_or_segment_note", "geographic sales growth")
    if "as a percent of sales" in text or "as a percent of net sales" in text:
        return _disclosure_spec("expense_ratio_change", "md&a_or_income_statement", "expense or earnings as percent of sales")
    if "high growth company" in text:
        return _disclosure_spec("growth_profile_evidence", "income_statement_or_md&a", "growth profile evidence")
    if "restructuring liability" in text:
        return _disclosure_spec("restructuring_liability", "restructuring_note", "restructuring liability")
    return None


def _disclosure_spec(slot_name: str, statement: str, line_item: str) -> JsonObject:
    return {
        "slot_name": slot_name,
        "statement": statement,
        "line_item": line_item,
    }


def _category_rank_direction(question: str) -> str:
    text = _metric_text(question)
    if any(
        marker in text
        for marker in (
            "lowest",
            "smallest",
            "worst",
            "least",
            "dragged down",
            "biggest drop",
            "largest drop",
            "largest decline",
            "steepest decline",
        )
    ):
        return "min"
    return "max"


def _category_rank_mode(question: str) -> str:
    text = _metric_text(question)
    if "proportionally" in text and any(marker in text for marker in ("increase", "increased", "growth", "grew")):
        return "growth_rate"
    if "growth" in text and any(marker in text for marker in ("most", "least", "highest", "lowest")):
        return "growth_rate"
    if ("year over year" in text or "year-over-year" in text or "yoy" in text) and any(
        marker in text for marker in ("percentage basis", "percent basis", "biggest drop", "largest drop", "largest decline")
    ):
        return "growth_rate"
    return "value"


def _category_rank_metric_focus(question: str) -> str:
    text = _metric_text(question)
    if "net income" in text or "net earnings" in text:
        return "net_income"
    if "ebitdar" in text:
        return "ebitdar"
    if "notional value" in text or "derivative instrument" in text:
        return "notional_value"
    if "short term investments" in text or "short term investment" in text or "type of debt" in text:
        return "short_term_investments"
    if "liability" in text or "liabilities" in text:
        return "liabilities"
    if "topline" in text or "net revenue" in text or "revenue" in text or "sales" in text:
        return "revenue"
    return "generic"


def _category_rank_candidate_facts(
    question: str,
    facts: list[FinanceFact],
    *,
    target_year: int | None,
    target_fp: str | None,
    metric_focus: str,
) -> list[tuple[str, FinanceFact]]:
    selected: dict[str, FinanceFact] = {}
    for fact in facts:
        if _decimal_or_none(fact.value) is None:
            continue
        if target_year is not None and fact.fiscal_year != target_year and _fact_end_year(fact) != target_year:
            continue
        if target_fp is not None and not _fact_matches_fiscal_quarter(fact, target_fp):
            continue
        if not _category_rank_fact_matches_metric(fact, metric_focus):
            continue
        category = _category_label_from_fact(fact)
        if not category or _category_label_is_total(category) or _category_excluded_by_question(question, category):
            continue
        existing = selected.get(category)
        if existing is None or _fact_sort_token(fact) > _fact_sort_token(existing):
            selected[category] = fact
    return [(category, selected[category]) for category in sorted(selected)]


def _category_rank_fact_matches_metric(fact: FinanceFact, metric_focus: str) -> bool:
    if metric_focus == "generic":
        return True
    text = _category_fact_text(fact)
    markers_by_focus = {
        "revenue": ("revenue", "revenues", "net revenue", "net sales", "sales", "topline"),
        "net_income": ("net income", "net earnings", "profit loss", "income loss"),
        "ebitdar": ("ebitdar",),
        "notional_value": ("notional value", "notional amount", "notional"),
        "short_term_investments": (
            "short term investments",
            "short term investment",
            "marketable securities",
            "debt securities",
            "available for sale",
            "held to maturity",
        ),
        "liabilities": ("liability", "liabilities"),
    }
    return any(marker in text for marker in markers_by_focus.get(metric_focus, (metric_focus,)))


def _category_fact_text(fact: FinanceFact) -> str:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    return _metric_text(
        " ".join(
            str(value or "")
            for value in (
                fact.metric,
                metadata.get("label"),
                metadata.get("concept"),
                metadata.get("raw_metric"),
                metadata.get("row_marker"),
                metadata.get("category"),
                metadata.get("segment"),
                metadata.get("region"),
                metadata.get("product_category"),
                metadata.get("instrument"),
                metadata.get("type"),
                metadata.get("context"),
            )
        )
    )


def _category_label_from_fact(fact: FinanceFact) -> str | None:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    for key in (
        "category",
        "segment",
        "region",
        "product_category",
        "service_category",
        "instrument",
        "debt_type",
        "type",
        "member",
    ):
        value = str(metadata.get(key) or "").strip()
        if value and not _category_label_candidate_is_generic(value):
            return value[:160]
    context_label = _category_label_from_context(fact)
    if context_label:
        return context_label
    for key in ("label", "concept"):
        value = str(metadata.get(key) or "").strip()
        if value and not _category_label_candidate_is_generic(value):
            return value[:160]
    metric = str(fact.metric or "").strip()
    if metric and not _category_label_candidate_is_generic(metric):
        return metric[:160]
    return None


def _category_label_from_context(fact: FinanceFact) -> str | None:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    context = str(metadata.get("context") or "").strip()
    if not context:
        return None
    marker = str(metadata.get("row_marker") or fact.metric or "").strip()
    position = context.lower().find(marker.lower()) if marker else -1
    before = context[:position] if position > 0 else context[:160]
    before = re.sub(r"\bcolumn_\d+\s*=\s*", " ", before)
    before = re.sub(r"\b(?:19|20)\d{2}\b", " ", before)
    before = re.sub(r"[$€£¥(),.%]", " ", before)
    tokens = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z&'/.-]*", before)
        if token.lower()
        not in {
            "table",
            "note",
            "year",
            "years",
            "ended",
            "fiscal",
            "amounts",
            "millions",
            "thousands",
            "unaudited",
            "total",
            "net",
            "sales",
            "revenue",
            "revenues",
            "income",
            "loss",
        }
    ]
    if not tokens:
        return None
    label = " ".join(tokens[-8:]).strip(" -/")
    if not label or _category_label_candidate_is_generic(label):
        return None
    return label[:160]


def _category_label_candidate_is_generic(value: str) -> bool:
    text = _metric_text(value)
    generic = {
        "",
        "revenue",
        "revenues",
        "net revenue",
        "net revenues",
        "net sales",
        "sales",
        "topline",
        "net income",
        "net earnings",
        "income",
        "loss",
        "ebitdar",
        "notional",
        "notional value",
        "notional amount",
        "short term investments",
        "marketable securities",
        "debt securities",
        "liabilities",
        "liability",
    }
    return text in generic


def _category_label_is_total(value: str) -> bool:
    text = _metric_text(value)
    return text in {"total", "totals", "consolidated"} or text.startswith("total ")


def _category_excluded_by_question(question: str, category: str) -> bool:
    text = _metric_text(question)
    category_text = _metric_text(category)
    excluded = re.findall(r"\bexcluding\s+([a-z0-9&'/-]+(?:\s+[a-z0-9&'/-]+){0,3})", text)
    for exclusion in excluded:
        first_token = exclusion.split()[0] if exclusion else ""
        if exclusion and exclusion in category_text:
            return True
        if first_token and first_token in category_text:
            return True
    return False


def _fact_matches_fiscal_quarter(fact: FinanceFact, quarter: str) -> bool:
    quarter_text = quarter.lower()
    text = _metric_text(
        " ".join(
            str(value or "")
            for value in (
                fact.period,
                fact.metadata.get("fp"),
                fact.metadata.get("frame"),
                fact.metadata.get("context"),
            )
        )
    )
    quarter_words = {
        "q1": ("q1", "first quarter", "quarter 1"),
        "q2": ("q2", "second quarter", "quarter 2"),
        "q3": ("q3", "third quarter", "quarter 3"),
        "q4": ("q4", "fourth quarter", "quarter 4"),
    }
    return any(marker in text for marker in quarter_words.get(quarter_text, (quarter_text,)))


def _target_fiscal_quarter(question: str) -> str | None:
    text = str(question or "").lower()
    match = re.search(r"\bq\s*([1-4])\b", text)
    if match:
        return f"Q{match.group(1)}"
    word_map = {
        "first quarter": "Q1",
        "second quarter": "Q2",
        "third quarter": "Q3",
        "fourth quarter": "Q4",
    }
    for marker, quarter in word_map.items():
        if marker in text:
            return quarter
    return None


def _debt_to_equity_numerator_slot(fact: FinanceFact) -> str:
    text = _metric_text(
        f"{fact.metric} {fact.metadata.get('label') or ''} {fact.metadata.get('concept') or ''}"
    )
    compact = text.replace(" ", "")
    if "liabilit" in text:
        return "total_liabilities"
    if "long term debt" in text or "longtermdebt" in compact:
        return "long_term_debt"
    if "short term debt" in text or "shorttermdebt" in compact:
        return "short_term_debt"
    return "debt"


def _formula_bound_line_item(fact: FinanceFact) -> JsonObject:
    return {
        key: value
        for key, value in {
            "fact_id": fact.fact_id,
            "metric": fact.metric,
            "label": fact.metadata.get("label"),
            "concept": fact.metadata.get("concept"),
            "value": fact.value,
            "unit": fact.unit,
            "fiscal_year": fact.fiscal_year,
        }.items()
        if value not in (None, "", [], {})
    }


def _ratio_decimal_string(numerator: Decimal | None, denominator: Decimal | None) -> str | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return _decimal_string(numerator / denominator)


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


def _plan_ev_revenue(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
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
    target_year = _target_fiscal_year(question)
    target_revenue_phrases = _ev_revenue_target_phrases(question)
    revenue = _target_revenue_fact_for_ev_revenue(
        question=question,
        facts=facts,
        target_year=target_year,
        target_phrases=target_revenue_phrases,
    )
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
        missing.append("target_revenue" if target_revenue_phrases else "revenue")
    if missing:
        return _missing(
            "ev_revenue",
            missing,
            facts=[item for item in (equity, debt, cash, investments, revenue) if item is not None],
            diagnostics={
                **({"target_revenue_phrases": target_revenue_phrases} if target_revenue_phrases else {}),
                **({"target_fiscal_year": target_year} if target_year is not None else {}),
            },
        )
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
        diagnostics={
            **({"target_revenue_phrases": target_revenue_phrases} if target_revenue_phrases else {}),
            **({"target_fiscal_year": target_year} if target_year is not None else {}),
            **({"revenue_fact_id": revenue.fact_id} if revenue is not None else {}),
        },
    )


def _target_revenue_fact_for_ev_revenue(
    *,
    question: str,
    facts: list[FinanceFact],
    target_year: int | None,
    target_phrases: list[str],
) -> FinanceFact | None:
    revenue_facts = _revenue_facts(facts, target_year=target_year)
    if not revenue_facts:
        return None
    if target_phrases:
        matches = [
            fact
            for fact in revenue_facts
            if any(_finance_fact_matches_entity_phrase(fact, phrase) for phrase in target_phrases)
        ]
        if matches:
            return sorted(matches, key=_revenue_fact_sort_key)[-1]
        if len(revenue_facts) == 1:
            return revenue_facts[0]
        return None
    return sorted(revenue_facts, key=_revenue_fact_sort_key)[-1]


def _revenue_facts(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
    matches = [
        fact
        for fact in _facts_for_metric(
            facts,
            ("revenue", "revenues", "net sales", "net revenues", "total revenues", "sales"),
        )
        if _is_revenue_fact(fact)
    ]
    if target_year is None:
        return matches
    return [
        fact
        for fact in matches
        if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
    ]


def _ev_revenue_target_phrases(question: str) -> list[str]:
    text = " ".join(str(question or "").split())
    if not text:
        return []
    patterns = (
        r"\bacquisition of (?P<target>[A-Z][A-Za-z0-9&.,' -]{1,80})",
        r"\bacquire (?P<target>[A-Z][A-Za-z0-9&.,' -]{1,80})",
        r"\bacquiring (?P<target>[A-Z][A-Za-z0-9&.,' -]{1,80})",
        r"\bbuyout of (?P<target>[A-Z][A-Za-z0-9&.,' -]{1,80})",
    )
    phrases: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            phrase = _clean_ev_target_phrase(match.group("target"))
            if phrase:
                phrases.append(phrase)
    return _ordered_unique_strings(phrases)


def _clean_ev_target_phrase(value: str) -> str:
    text = str(value or "").strip(" .,:;?!)(")
    text = re.split(
        r"\b(?:using|calculate|compute|estimate|show|with|from|based|transaction|deal|ev|enterprise|revenue|multiple|latest|public|filing|disclosure|and)\b",
        text,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    text = re.sub(r"\s+", " ", text).strip(" .,:;?!)(")
    return text


def _finance_fact_matches_entity_phrase(fact: FinanceFact, phrase: str) -> bool:
    tokens = _entity_significant_tokens(phrase)
    if not tokens:
        return False
    haystack = _normalized_entity_text(
        " ".join(
            str(value or "")
            for value in (
                fact.entity,
                fact.ticker,
                fact.period,
                fact.metadata.get("source_title"),
                fact.metadata.get("source_uri"),
                fact.metadata.get("context"),
                fact.metadata.get("raw"),
                fact.metadata.get("ticker"),
            )
        )
    )
    return all(token in haystack for token in tokens)


def _entity_significant_tokens(value: str) -> list[str]:
    ignored = {
        "inc",
        "corp",
        "corporation",
        "company",
        "co",
        "ltd",
        "plc",
        "llc",
        "holdings",
        "holding",
        "the",
        "class",
    }
    return [
        token
        for token in _normalized_entity_text(value).split()
        if len(token) >= 3 and token not in ignored
    ][:4]


def _normalized_entity_text(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def _ordered_unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


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


def _plan_fixed_charge_coverage(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    fixed_charges = _fixed_charge_denominator_fact(facts, target_year=target_year)
    earnings_available = _fixed_charge_numerator_fact(facts, target_year=target_year)
    pretax_income = _latest_fact_for_year(facts, ("pretax income",), target_year=target_year) if earnings_available is None else None
    missing: list[str] = []
    if fixed_charges is None:
        missing.append("fixed_charges")
    if earnings_available is None and pretax_income is None:
        missing.append("earnings_available_for_fixed_charges_or_pretax_income")
    support_facts = [fact for fact in (earnings_available, pretax_income, fixed_charges) if fact is not None]
    if missing:
        return _missing(
            "fixed_charge_coverage",
            missing,
            facts=support_facts,
            diagnostics={
                "reason": "fixed_charge_coverage_requires_fixed_charges_and_earnings_basis",
                "target_fiscal_year": target_year,
            },
        )
    related_facts = support_facts
    fixed_charge_value = _decimal_or_none(_fact_value_for_formula(fixed_charges, related_facts=related_facts)) if fixed_charges else None
    earnings_value = (
        _decimal_or_none(_fact_value_for_formula(earnings_available, related_facts=related_facts))
        if earnings_available
        else None
    )
    pretax_value = _decimal_or_none(_fact_value_for_formula(pretax_income, related_facts=related_facts)) if pretax_income else None
    if fixed_charge_value is None or fixed_charge_value == 0:
        return _missing(
            "fixed_charge_coverage",
            ["positive_fixed_charges"],
            facts=support_facts,
            diagnostics={"target_fiscal_year": target_year},
        )
    if earnings_value is not None:
        expression = "earnings_available_for_fixed_charges / fixed_charges"
        variables: JsonObject = {
            "earnings_available_for_fixed_charges": _decimal_string(earnings_value),
            "fixed_charges": _decimal_string(fixed_charge_value),
        }
        formula_facts = [fact for fact in (earnings_available, fixed_charges) if fact is not None]
        earnings_basis = "direct_disclosure"
        numerator_value = earnings_value
    elif pretax_value is not None:
        expression = "(pretax_income + fixed_charges) / fixed_charges"
        variables = {
            "pretax_income": _decimal_string(pretax_value),
            "fixed_charges": _decimal_string(fixed_charge_value),
        }
        formula_facts = [fact for fact in (pretax_income, fixed_charges) if fact is not None]
        earnings_basis = "derived_from_pretax_income_plus_fixed_charges"
        numerator_value = pretax_value + fixed_charge_value
    else:
        return _missing(
            "fixed_charge_coverage",
            ["earnings_available_for_fixed_charges_or_pretax_income"],
            facts=support_facts,
            diagnostics={"target_fiscal_year": target_year},
        )
    return _ready(
        "fixed_charge_coverage",
        expression,
        variables,
        unit="x",
        facts=formula_facts,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "earnings available for fixed charges divided by fixed charges",
            "earnings_basis": earnings_basis,
            "bound_line_items": {
                **(
                    {"earnings_available_for_fixed_charges": _formula_bound_line_item(earnings_available)}
                    if earnings_available is not None
                    else {"pretax_income": _formula_bound_line_item(pretax_income)}
                ),
                "fixed_charges": _formula_bound_line_item(fixed_charges),
            },
            "model_outputs": {
                "earnings_available_for_fixed_charges": _decimal_string(numerator_value),
                "fixed_charges": _decimal_string(fixed_charge_value),
                "fixed_charge_coverage": _ratio_decimal_string(numerator_value, fixed_charge_value),
            },
        },
    )


def _fixed_charge_numerator_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = [
        fact
        for fact in _facts_for_metric(
            facts,
            (
                "earnings available for fixed charges",
                "earnings before fixed charges",
                "income before fixed charges",
            ),
        )
        if _is_fixed_charge_numerator_fact(fact)
    ]
    candidates = _fixed_charge_year_matches(candidates, target_year=target_year)
    return _sort_facts(candidates)[-1] if candidates else None


def _fixed_charge_denominator_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = [
        fact
        for fact in _facts_for_metric(facts, ("fixed charges", "total fixed charges"))
        if _is_fixed_charge_denominator_fact(fact)
    ]
    candidates = _fixed_charge_year_matches(candidates, target_year=target_year)
    return _sort_facts(candidates)[-1] if candidates else None


def _fixed_charge_year_matches(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
    candidates = _sort_unique_facts(facts)
    if target_year is None:
        return candidates
    target_matches = [
        fact
        for fact in candidates
        if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
    ]
    return target_matches


def _is_fixed_charge_numerator_fact(fact: FinanceFact) -> bool:
    text = _fixed_charge_fact_text(fact)
    if _is_fixed_charge_ratio_fact(fact):
        return False
    return any(
        marker in text
        for marker in (
            "earnings available for fixed charges",
            "earnings before fixed charges",
            "income before fixed charges",
        )
    )


def _is_fixed_charge_denominator_fact(fact: FinanceFact) -> bool:
    text = _fixed_charge_fact_text(fact)
    if _is_fixed_charge_ratio_fact(fact) or _is_fixed_charge_numerator_fact(fact):
        return False
    return "fixed charges" in text


def _is_fixed_charge_ratio_fact(fact: FinanceFact) -> bool:
    text = _fixed_charge_fact_text(fact)
    return "ratio" in text or "coverage ratio" in text or "times" in text


def _fixed_charge_fact_text(fact: FinanceFact) -> str:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    return _metric_text(
        " ".join(
            str(value or "")
            for value in (
                fact.metric,
                metadata.get("label"),
                metadata.get("concept"),
                metadata.get("raw_metric"),
            )
        )
    )


def _plan_mlr_rebate(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    needs_rebate = _mlr_question_needs_rebate(question)
    actual_mlr = _mlr_actual_fact(facts, target_year=target_year)
    numerator_fact = _mlr_numerator_fact(facts, target_year=target_year)
    claims = _latest_fact_for_year(facts, ("medical claims",), target_year=target_year) if numerator_fact is None else None
    quality_improvement = (
        _latest_fact_for_year(facts, ("quality improvement expenses",), target_year=target_year)
        if numerator_fact is None
        else None
    )
    premium_basis = _mlr_premium_basis_fact(facts, target_year=target_year)
    standard_fact = _mlr_standard_fact(facts, target_year=target_year)
    standard_value, standard_source = _mlr_standard_value(question=question, fact=standard_fact)
    numerator_facts = [fact for fact in (numerator_fact, claims, quality_improvement) if fact is not None]
    supporting = [fact for fact in (actual_mlr, premium_basis, standard_fact, *numerator_facts) if fact is not None]
    missing: list[str] = []
    if actual_mlr is None and numerator_fact is None and not (claims is not None and quality_improvement is not None):
        missing.append("actual_mlr_or_complete_mlr_numerator")
    if actual_mlr is None and premium_basis is None:
        missing.append("adjusted_premium_revenue_or_mlr_denominator")
    if needs_rebate:
        if premium_basis is None:
            missing.append("rebate_basis_or_adjusted_premium_revenue")
        if standard_value is None:
            missing.append("mlr_standard_or_market_segment")
    if missing:
        return _missing(
            "mlr_rebate",
            _ordered_unique(missing),
            facts=supporting,
            diagnostics={
                "reason": "mlr_rebate_requires_actual_mlr_or_components_standard_and_rebate_basis",
                "target_fiscal_year": target_year,
                "output_requested": "rebate" if needs_rebate else "medical_loss_ratio",
            },
        )
    related_facts = supporting
    premium_value = _decimal_or_none(_fact_value_for_formula(premium_basis, related_facts=related_facts)) if premium_basis else None
    numerator_value: Decimal | None = None
    numerator_basis = ""
    formula_facts: list[FinanceFact] = []
    if actual_mlr is not None:
        actual_mlr_value = _decimal_or_none(_ratio_value(actual_mlr))
        numerator_basis = "reported_actual_mlr"
        formula_facts.append(actual_mlr)
    else:
        actual_mlr_value = None
        if numerator_fact is not None:
            numerator_value = _decimal_or_none(_fact_value_for_formula(numerator_fact, related_facts=related_facts))
            numerator_basis = "reported_mlr_numerator"
            formula_facts.append(numerator_fact)
        elif claims is not None and quality_improvement is not None:
            claims_value = _decimal_or_none(_fact_value_for_formula(claims, related_facts=related_facts))
            quality_value = _decimal_or_none(_fact_value_for_formula(quality_improvement, related_facts=related_facts))
            if claims_value is not None and quality_value is not None:
                numerator_value = claims_value + quality_value
                numerator_basis = "derived_from_claims_plus_quality_improvement"
                formula_facts.extend([claims, quality_improvement])
        if numerator_value is not None and premium_value is not None and premium_value != 0:
            actual_mlr_value = numerator_value / premium_value
    if actual_mlr_value is None:
        return _missing(
            "mlr_rebate",
            ["computable_actual_mlr"],
            facts=supporting,
            diagnostics={"target_fiscal_year": target_year},
        )
    if not needs_rebate:
        if actual_mlr is not None:
            variables: JsonObject = {"actual_mlr": _decimal_string(actual_mlr_value)}
            expression = "actual_mlr"
        else:
            if premium_value is None or premium_value == 0 or numerator_value is None:
                return _missing("mlr_rebate", ["mlr_numerator", "adjusted_premium_revenue"], facts=supporting)
            variables = {
                "mlr_numerator": _decimal_string(numerator_value),
                "adjusted_premium_revenue": _decimal_string(premium_value),
            }
            expression = "mlr_numerator / adjusted_premium_revenue"
            if premium_basis is not None:
                formula_facts.append(premium_basis)
        return _ready(
            "mlr_rebate",
            expression,
            variables,
            unit="percent",
            facts=_sort_unique_facts(formula_facts),
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "medical loss ratio numerator divided by adjusted premium revenue",
                "output_attribute": "medical_loss_ratio",
                "numerator_basis": numerator_basis,
                "bound_line_items": _mlr_bound_line_items(
                    actual_mlr=actual_mlr,
                    numerator_fact=numerator_fact,
                    claims=claims,
                    quality_improvement=quality_improvement,
                    premium_basis=premium_basis,
                    standard_fact=standard_fact,
                ),
                "model_outputs": {"actual_mlr": _decimal_string(actual_mlr_value)},
            },
        )
    if premium_value is None or premium_value == 0:
        return _missing("mlr_rebate", ["positive_rebate_basis_or_adjusted_premium_revenue"], facts=supporting)
    if standard_value is None:
        return _missing("mlr_rebate", ["mlr_standard_or_market_segment"], facts=supporting)
    rebate_gap = standard_value - actual_mlr_value
    if rebate_gap > 0:
        if actual_mlr is not None:
            expression = "(mlr_standard - actual_mlr) * adjusted_premium_revenue"
            variables = {
                "mlr_standard": _decimal_string(standard_value),
                "actual_mlr": _decimal_string(actual_mlr_value),
                "adjusted_premium_revenue": _decimal_string(premium_value),
            }
        else:
            expression = "(mlr_standard - (mlr_numerator / adjusted_premium_revenue)) * adjusted_premium_revenue"
            variables = {
                "mlr_standard": _decimal_string(standard_value),
                "mlr_numerator": _decimal_string(numerator_value or Decimal(0)),
                "adjusted_premium_revenue": _decimal_string(premium_value),
            }
    else:
        expression = "adjusted_premium_revenue * 0"
        variables = {
            "mlr_standard": _decimal_string(standard_value),
            "actual_mlr": _decimal_string(actual_mlr_value),
            "adjusted_premium_revenue": _decimal_string(premium_value),
        }
    if premium_basis is not None:
        formula_facts.append(premium_basis)
    if standard_fact is not None:
        formula_facts.append(standard_fact)
    rebate_amount = max(rebate_gap, Decimal(0)) * premium_value
    return _ready(
        "mlr_rebate",
        expression,
        variables,
        unit=str(premium_basis.unit or "USD") if premium_basis is not None else "USD",
        facts=_sort_unique_facts(formula_facts),
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "max(required MLR - actual MLR, 0) multiplied by adjusted premium revenue",
            "output_attribute": "mlr_rebate",
            "numerator_basis": numerator_basis,
            "standard_source": standard_source,
            "rebate_required": rebate_gap > 0,
            "bound_line_items": _mlr_bound_line_items(
                actual_mlr=actual_mlr,
                numerator_fact=numerator_fact,
                claims=claims,
                quality_improvement=quality_improvement,
                premium_basis=premium_basis,
                standard_fact=standard_fact,
            ),
            "model_outputs": {
                "actual_mlr": _decimal_string(actual_mlr_value),
                "mlr_standard": _decimal_string(standard_value),
                "rebate_gap": _decimal_string(rebate_gap),
                "rebate_gap_positive": _decimal_string(max(rebate_gap, Decimal(0))),
                "adjusted_premium_revenue": _decimal_string(premium_value),
                "mlr_rebate": _decimal_string(rebate_amount),
            },
        },
    )


def _mlr_question_needs_rebate(question: str) -> bool:
    text = _metric_text(question)
    return any(marker in text for marker in ("rebate", "refund", "owed", "owe", "shortfall", "amount due"))


def _mlr_actual_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = [
        fact
        for fact in _facts_for_metric(facts, ("medical loss ratio",))
        if not _is_mlr_standard_fact(fact) and not _is_mlr_rebate_fact(fact)
    ]
    candidates = _mlr_year_matches(candidates, target_year=target_year)
    return _sort_facts(candidates)[-1] if candidates else None


def _mlr_standard_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = [
        fact
        for fact in facts
        if _is_mlr_standard_fact(fact)
    ]
    candidates = _mlr_year_matches(candidates, target_year=target_year)
    return _sort_facts(candidates)[-1] if candidates else None


def _mlr_numerator_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = _facts_for_metric(facts, ("mlr numerator",))
    candidates = _mlr_year_matches(candidates, target_year=target_year)
    return _sort_facts(candidates)[-1] if candidates else None


def _mlr_premium_basis_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    for markers in (
        ("mlr denominator", "adjusted premium revenue"),
        ("premium revenue", "earned premium", "earned premiums"),
    ):
        candidates = _mlr_year_matches(_facts_for_metric(facts, markers), target_year=target_year)
        if candidates:
            return _sort_facts(candidates)[-1]
    return None


def _mlr_year_matches(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
    candidates = _sort_unique_facts(facts)
    if target_year is None:
        return candidates
    return [
        fact
        for fact in candidates
        if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
    ]


def _mlr_standard_value(*, question: str, fact: FinanceFact | None) -> tuple[Decimal | None, str]:
    if fact is not None:
        value = _decimal_or_none(_ratio_value(fact))
        if value is not None:
            return value, "fact"
    question_value = _mlr_standard_from_question(question)
    if question_value is not None:
        return question_value, "question"
    segment_value = _mlr_standard_from_market_segment(question)
    if segment_value is not None:
        return segment_value, "question_market_segment"
    return None, ""


def _mlr_standard_from_question(question: str) -> Decimal | None:
    text = str(question or "")
    patterns = (
        r"(?:standard|minimum|required|threshold|target)[^\d%]{0,40}(?P<number>\d+(?:\.\d+)?)\s*%",
        r"(?P<number>\d+(?:\.\d+)?)\s*%[^\w%]{0,20}(?:standard|minimum|required|threshold|target)",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _decimal_or_none(match.group("number"))
            if value is not None:
                return value / Decimal(100)
    return None


def _mlr_standard_from_market_segment(question: str) -> Decimal | None:
    text = _metric_text(question)
    if "large group" in text:
        return Decimal("0.85")
    if "small group" in text or "individual market" in text or "individual health" in text:
        return Decimal("0.80")
    return None


def _is_mlr_standard_fact(fact: FinanceFact) -> bool:
    text = _mlr_fact_text(fact)
    return "mlr standard" in text or any(
        marker in text
        for marker in (
            "minimum medical loss ratio",
            "medical loss ratio standard",
            "minimum mlr",
            "required mlr",
            "required medical loss ratio",
        )
    )


def _is_mlr_rebate_fact(fact: FinanceFact) -> bool:
    text = _mlr_fact_text(fact)
    return "mlr rebate" in text or "medical loss ratio rebate" in text or "rebate amount" in text


def _mlr_fact_text(fact: FinanceFact) -> str:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    return _metric_text(
        " ".join(
            str(value or "")
            for value in (
                fact.metric,
                metadata.get("label"),
                metadata.get("concept"),
                metadata.get("raw_metric"),
                metadata.get("context"),
            )
        )
    )


def _mlr_bound_line_items(
    *,
    actual_mlr: FinanceFact | None,
    numerator_fact: FinanceFact | None,
    claims: FinanceFact | None,
    quality_improvement: FinanceFact | None,
    premium_basis: FinanceFact | None,
    standard_fact: FinanceFact | None,
) -> JsonObject:
    return {
        key: value
        for key, value in {
            "actual_mlr": _formula_bound_line_item(actual_mlr) if actual_mlr is not None else None,
            "mlr_numerator": _formula_bound_line_item(numerator_fact) if numerator_fact is not None else None,
            "medical_claims": _formula_bound_line_item(claims) if claims is not None else None,
            "quality_improvement_expenses": _formula_bound_line_item(quality_improvement) if quality_improvement is not None else None,
            "adjusted_premium_revenue": _formula_bound_line_item(premium_basis) if premium_basis is not None else None,
            "mlr_standard": _formula_bound_line_item(standard_fact) if standard_fact is not None else None,
        }.items()
        if value is not None
    }


def _plan_purchase_price_allocation(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    consideration = _ppa_consideration_fact(facts, target_year=target_year)
    goodwill = _ppa_goodwill_fact(facts, target_year=target_year)
    intangible_facts = _ppa_intangible_facts(facts, target_year=target_year)
    missing: list[str] = []
    if consideration is None:
        missing.append("purchase_consideration")
    question_text = _metric_text(question)
    needs_goodwill = "goodwill" in question_text
    needs_intangibles = "intangible" in question_text or "identifiable" in question_text
    if needs_goodwill and goodwill is None:
        missing.append("goodwill")
    if needs_intangibles and not intangible_facts:
        missing.append("intangible_assets")
    if not needs_goodwill and not needs_intangibles and goodwill is None and not intangible_facts:
        missing.append("goodwill_or_intangible_assets")
    support_facts = [fact for fact in [consideration, goodwill] if fact is not None]
    support_facts.extend(intangible_facts)
    if missing:
        return _missing(
            "purchase_price_allocation",
            missing,
            facts=support_facts,
            diagnostics={
                "reason": "purchase_price_allocation_requires_consideration_and_allocated_asset_facts",
                "target_fiscal_year": target_year,
            },
        )
    related_facts = support_facts
    consideration_value = _decimal_or_none(_fact_value_for_formula(consideration, related_facts=related_facts)) if consideration else None
    goodwill_value = _decimal_or_none(_fact_value_for_formula(goodwill, related_facts=related_facts)) if goodwill else Decimal(0)
    intangible_values = [
        value
        for fact in intangible_facts
        if (value := _decimal_or_none(_fact_value_for_formula(fact, related_facts=related_facts))) is not None
    ]
    intangible_total = sum(intangible_values, Decimal(0))
    if consideration_value is None or consideration_value == 0:
        return _missing(
            "purchase_price_allocation",
            ["positive_purchase_consideration"],
            facts=support_facts,
            diagnostics={"target_fiscal_year": target_year},
        )
    if needs_goodwill and goodwill is not None and not needs_intangibles:
        expression = "goodwill / purchase_consideration"
        output_attribute = "goodwill_to_consideration"
        variables: JsonObject = {
            "purchase_consideration": _decimal_string(consideration_value),
            "goodwill": _decimal_string(goodwill_value),
        }
        formula_facts = [fact for fact in (consideration, goodwill) if fact is not None]
    elif needs_intangibles and intangible_facts and not needs_goodwill:
        expression = "intangible_assets / purchase_consideration"
        output_attribute = "intangible_assets_to_consideration"
        variables = {
            "purchase_consideration": _decimal_string(consideration_value),
            "intangible_assets": _decimal_string(intangible_total),
        }
        formula_facts = ([consideration] if consideration is not None else []) + intangible_facts
    else:
        expression = "(goodwill + intangible_assets) / purchase_consideration"
        output_attribute = "goodwill_and_intangible_assets_to_consideration"
        variables = {
            "purchase_consideration": _decimal_string(consideration_value),
            "goodwill": _decimal_string(goodwill_value),
            "intangible_assets": _decimal_string(intangible_total),
        }
        formula_facts = [fact for fact in (consideration, goodwill) if fact is not None] + intangible_facts
    allocated_total = goodwill_value + intangible_total
    model_outputs = {
        "purchase_consideration": _decimal_string(consideration_value),
        "goodwill": _decimal_string(goodwill_value) if goodwill is not None else None,
        "intangible_assets": _decimal_string(intangible_total) if intangible_facts else None,
        "goodwill_and_intangible_assets": _decimal_string(allocated_total),
        "goodwill_to_consideration": _ratio_decimal_string(goodwill_value, consideration_value) if goodwill is not None else None,
        "intangible_assets_to_consideration": _ratio_decimal_string(intangible_total, consideration_value) if intangible_facts else None,
        "goodwill_and_intangible_assets_to_consideration": _ratio_decimal_string(allocated_total, consideration_value),
        "residual_after_goodwill_and_intangible_assets": _decimal_string(consideration_value - allocated_total),
    }
    return _ready(
        "purchase_price_allocation",
        expression,
        variables,
        unit="percent",
        facts=formula_facts,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "allocated acquisition amounts divided by purchase consideration",
            "output_attribute": output_attribute,
            "bound_line_items": {
                "purchase_consideration": _formula_bound_line_item(consideration),
                **({"goodwill": _formula_bound_line_item(goodwill)} if "goodwill" in variables and goodwill is not None else {}),
                **(
                    {"intangible_assets": [_formula_bound_line_item(fact) for fact in intangible_facts]}
                    if "intangible_assets" in variables
                    else {}
                ),
            },
            "model_outputs": {key: value for key, value in model_outputs.items() if value is not None},
        },
    )


def _ppa_consideration_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = [
        fact
        for fact in _facts_for_metric(
            facts,
            (
                "purchase consideration",
                "consideration paid",
                "fair value of consideration",
                "purchase price",
                "transaction value",
                "deal value",
            ),
        )
        if not _is_per_share_fact(fact) and not _looks_like_unscaled_equity_quote(fact)
    ]
    if target_year is not None:
        year_matches = [
            fact
            for fact in candidates
            if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
        ]
        if year_matches:
            candidates = year_matches
    return _sort_facts(candidates)[-1] if candidates else None


def _ppa_goodwill_fact(facts: list[FinanceFact], *, target_year: int | None) -> FinanceFact | None:
    candidates = _sort_unique_facts(_facts_for_metric(facts, ("goodwill",)))
    if target_year is not None:
        year_matches = [
            fact
            for fact in candidates
            if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
        ]
        if year_matches:
            candidates = year_matches
    ppa_context_candidates = [
        fact
        for fact in candidates
        if _ppa_fact_has_acquisition_context(fact)
    ]
    if ppa_context_candidates:
        candidates = ppa_context_candidates
    return _sort_facts(candidates)[-1] if candidates else None


def _ppa_intangible_facts(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
    candidates = _sort_unique_facts(_facts_for_metric(facts, ("intangible assets", "developed technology", "customer relationships")))
    if target_year is not None:
        year_matches = [
            fact
            for fact in candidates
            if fact.fiscal_year == target_year or _fact_end_year(fact) == target_year
        ]
        if year_matches:
            candidates = year_matches
    ppa_context_candidates = [
        fact
        for fact in candidates
        if _ppa_fact_has_acquisition_context(fact)
    ]
    if ppa_context_candidates:
        candidates = ppa_context_candidates
    total_candidates = [
        fact
        for fact in candidates
        if _ppa_intangible_fact_is_total(fact)
    ]
    if total_candidates:
        return [_sort_facts(total_candidates)[-1]]
    return candidates


def _ppa_intangible_fact_is_total(fact: FinanceFact) -> bool:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    text = _metric_text(
        " ".join(
            str(metadata.get(key) or "")
            for key in ("label", "raw", "raw_metric", "context")
        )
    )
    return "total" in text and "intangible" in text


def _ppa_fact_has_acquisition_context(fact: FinanceFact) -> bool:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    text = _metric_text(
        " ".join(
            str(metadata.get(key) or "")
            for key in ("label", "raw", "raw_metric", "context", "section", "source_title")
        )
    )
    return any(
        marker in text
        for marker in (
            "purchase price allocation",
            "business combination",
            "acquisition",
            "acquired",
            "purchase accounting",
            "consideration transferred",
            "allocation of purchase price",
            "assets acquired",
            "liabilities assumed",
        )
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
    net_income = _latest_fact(facts, ("net income",), predicate=_is_net_income_fact)
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


def _plan_dpo(*, question: str, facts: list[FinanceFact], inventory_adjusted: bool) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    accounts_payable_used = _dpo_accounts_payable_pair(_dpo_accounts_payable_facts(facts), target_year=target_year)
    cogs = _dio_cogs_fact(facts, target_year=target_year)
    inventory_used = _dio_inventory_pair(_dio_inventory_facts(facts), target_year=target_year) if inventory_adjusted else []
    missing: list[str] = []
    if len(accounts_payable_used) < 2:
        missing.extend(["accounts_payable_begin", "accounts_payable_end"] if not accounts_payable_used else ["accounts_payable_begin_or_end"])
    if cogs is None:
        missing.append("cogs")
    if inventory_adjusted and len(inventory_used) < 2:
        missing.extend(["inventory_begin", "inventory_end"] if not inventory_used else ["inventory_begin_or_end"])
    supporting = [
        *accounts_payable_used,
        *inventory_used,
        *([cogs] if cogs is not None else []),
    ]
    formula_name = "dpo_inventory_adjusted" if inventory_adjusted else "dpo"
    fiscal_days = _fiscal_days(question)
    if missing:
        return _missing(
            formula_name,
            _ordered_unique(missing),
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "fiscal_days": fiscal_days,
                "formula_definition": (
                    "days payable outstanding using average accounts payable divided by COGS plus change in inventory"
                    if inventory_adjusted
                    else "days payable outstanding using average accounts payable divided by COGS"
                ),
            },
        )
    variables: JsonObject = {
        "fiscal_days": fiscal_days,
        "accounts_payable_begin": accounts_payable_used[0].value,
        "accounts_payable_end": accounts_payable_used[1].value,
        "cogs": cogs.value,
    }
    expression = "fiscal_days * ((accounts_payable_begin + accounts_payable_end) / 2) / cogs"
    if inventory_adjusted:
        variables["inventory_begin"] = inventory_used[0].value
        variables["inventory_end"] = inventory_used[1].value
        expression = (
            "fiscal_days * ((accounts_payable_begin + accounts_payable_end) / 2) / "
            "(cogs + (inventory_end - inventory_begin))"
        )
    return _ready(
        formula_name,
        expression,
        variables,
        unit="days",
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "fiscal_days": fiscal_days,
            "fiscal_days_source": "question_or_default",
            "uses_inventory_change_adjustment": inventory_adjusted,
        },
    )


def _plan_average_capex_to_revenue(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    years = _target_fiscal_years(question)
    if len(years) >= 2:
        start, end = min(years), max(years)
        if end - start <= 10:
            years = list(range(start, end + 1))
    elif len(years) == 1 and re.search(r"\b3\s*year\b|\bthree\s+year\b", question or "", re.IGNORECASE):
        years = [years[0] - 2, years[0] - 1, years[0]]
    target_year = _target_fiscal_year(question)
    if not years and target_year is not None:
        years = [target_year]
    if not years:
        years = []
    variables: JsonObject = {}
    input_facts: list[FinanceFact] = []
    missing: list[str] = []
    terms: list[str] = []
    for year in years:
        capex = _latest_fact_for_year(facts, ("capital expenditures", "capex"), target_year=year)
        revenue = _latest_revenue_fact(facts, target_year=year)
        capex_slot = f"capital_expenditures_{year}"
        revenue_slot = f"revenue_{year}"
        if capex is None:
            missing.append(capex_slot)
        else:
            variables[capex_slot] = _absolute_decimal_string(capex.value)
            input_facts.append(capex)
        if revenue is None:
            missing.append(revenue_slot)
        else:
            variables[revenue_slot] = revenue.value
            input_facts.append(revenue)
        terms.append(f"({capex_slot} / {revenue_slot})")
    if not years:
        missing.extend(["capital_expenditures_by_period", "revenue_by_period"])
    expression = f"({' + '.join(terms)}) / {len(terms)}" if terms else "average(capital_expenditures / revenue)"
    if missing:
        return _missing(
            "average_capex_to_revenue",
            _ordered_unique(missing),
            facts=input_facts,
            diagnostics={
                "target_fiscal_years": years,
                "formula_definition": "average of annual capital expenditures divided by annual revenue",
                "expression": expression,
            },
        )
    return _ready(
        "average_capex_to_revenue",
        expression,
        variables,
        unit="percent",
        facts=input_facts,
        diagnostics={
            "target_fiscal_years": years,
            "formula_definition": "average of annual capital expenditures divided by annual revenue",
        },
    )


def _plan_effective_tax_rate_change(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    years = _target_fiscal_years(question)
    prior_year = min(years) if len(years) >= 2 else None
    current_year = max(years) if len(years) >= 2 else _target_fiscal_year(question)
    prior = (
        _latest_effective_tax_rate_fact(facts, target_year=prior_year)
        if prior_year is not None
        else None
    )
    current = _latest_effective_tax_rate_fact(facts, target_year=current_year)
    if prior is None and current is not None:
        prior = _latest_effective_tax_rate_fact(
            facts,
            target_year=(current.fiscal_year - 1 if isinstance(current.fiscal_year, int) else None),
            exclude_fact_ids={current.fact_id},
        )
    missing: list[str] = []
    if prior is None:
        missing.append("prior_effective_tax_rate")
    if current is None:
        missing.append("current_effective_tax_rate")
    supporting = [fact for fact in (prior, current) if fact is not None]
    if missing:
        return _missing(
            "effective_tax_rate_change",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_years": years,
                "formula_definition": "current effective tax rate less prior effective tax rate",
            },
        )
    return _ready(
        "effective_tax_rate_change",
        "(current_effective_tax_rate - prior_effective_tax_rate) * 100",
        {
            "prior_effective_tax_rate": _ratio_value(prior),
            "current_effective_tax_rate": _ratio_value(current),
        },
        unit="percentage_points",
        facts=supporting,
        diagnostics={
            "target_fiscal_years": years,
            "formula_definition": "current effective tax rate less prior effective tax rate",
        },
    )


def _plan_interest_coverage_ratio(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    numerator = _latest_fact_for_year(
        facts,
        ("adjusted ebit", "ebit", "operating income"),
        target_year=target_year,
    )
    interest_expense = _latest_fact_for_year(facts, ("interest expense", "interest"), target_year=target_year)
    missing: list[str] = []
    if numerator is None:
        missing.append("adjusted_ebit_or_ebit")
    if interest_expense is None:
        missing.append("interest_expense")
    supporting = [fact for fact in (numerator, interest_expense) if fact is not None]
    if missing:
        return _missing(
            "interest_coverage_ratio",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "adjusted EBIT or EBIT divided by interest expense",
            },
        )
    return _ready(
        "interest_coverage_ratio",
        "adjusted_ebit_or_ebit / interest_expense",
        {
            "adjusted_ebit_or_ebit": numerator.value,
            "interest_expense": _absolute_decimal_string(interest_expense.value),
        },
        unit="x",
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "adjusted EBIT or EBIT divided by interest expense",
        },
    )


def _plan_unadjusted_ebitda(*, question: str, facts: list[FinanceFact], less_capex: bool) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    operating_income = _latest_fact_for_year(facts, ("operating income", "income from operations"), target_year=target_year)
    depreciation_amortization = _latest_fact_for_year(
        facts,
        ("depreciation and amortization", "depreciation amortization", "d&a"),
        target_year=target_year,
    )
    capex = _latest_fact_for_year(facts, ("capital expenditures", "capex"), target_year=target_year) if less_capex else None
    missing: list[str] = []
    if operating_income is None:
        missing.append("operating_income")
    if depreciation_amortization is None:
        missing.append("depreciation_and_amortization")
    if less_capex and capex is None:
        missing.append("capital_expenditures")
    supporting = [fact for fact in (operating_income, depreciation_amortization, capex) if fact is not None]
    formula_name = "unadjusted_ebitda_less_capex" if less_capex else "unadjusted_ebitda"
    if missing:
        return _missing(
            formula_name,
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": (
                    "operating income plus depreciation and amortization less capital expenditures"
                    if less_capex
                    else "operating income plus depreciation and amortization"
                ),
            },
        )
    variables: JsonObject = {
        "operating_income": operating_income.value,
        "depreciation_and_amortization": depreciation_amortization.value,
    }
    expression = "operating_income + depreciation_and_amortization"
    if less_capex:
        variables["capital_expenditures"] = _absolute_decimal_string(capex.value)
        expression = "operating_income + depreciation_and_amortization - capital_expenditures"
    return _ready(
        formula_name,
        expression,
        variables,
        unit=operating_income.unit,
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_asset_turnover(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    revenue = _latest_revenue_fact(facts, target_year=target_year)
    assets_current = _latest_fact_for_year(facts, ("assets", "total assets"), target_year=target_year)
    assets_prior = _latest_fact_for_year(
        facts,
        ("assets", "total assets"),
        target_year=target_year - 1 if target_year is not None else None,
        exclude_fact_ids={assets_current.fact_id} if assets_current is not None else None,
    )
    missing: list[str] = []
    if revenue is None:
        missing.append("revenue")
    if assets_current is None:
        missing.append("assets_current")
    if assets_prior is None:
        missing.append("assets_prior")
    supporting = [fact for fact in (revenue, assets_current, assets_prior) if fact is not None]
    if missing:
        return _missing(
            "asset_turnover",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "revenue divided by average total assets",
            },
        )
    return _ready(
        "asset_turnover",
        "revenue / ((assets_current + assets_prior) / 2)",
        {"revenue": revenue.value, "assets_current": assets_current.value, "assets_prior": assets_prior.value},
        unit="x",
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "revenue divided by average total assets",
        },
    )


def _plan_average_cogs_to_revenue(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    years = _target_fiscal_years(question)
    if len(years) >= 2:
        start, end = min(years), max(years)
        if end - start <= 10:
            years = list(range(start, end + 1))
    elif len(years) == 1 and re.search(r"\b3\s*year\b|\bthree\s+year\b", question or "", re.IGNORECASE):
        years = [years[0] - 2, years[0] - 1, years[0]]
    variables: JsonObject = {}
    input_facts: list[FinanceFact] = []
    missing: list[str] = []
    terms: list[str] = []
    for year in years:
        cogs = _dio_cogs_fact(facts, target_year=year)
        revenue = _latest_revenue_fact(facts, target_year=year)
        cogs_slot = f"cogs_{year}"
        revenue_slot = f"revenue_{year}"
        if cogs is None:
            missing.append(cogs_slot)
        else:
            variables[cogs_slot] = _absolute_decimal_string(cogs.value)
            input_facts.append(cogs)
        if revenue is None:
            missing.append(revenue_slot)
        else:
            variables[revenue_slot] = revenue.value
            input_facts.append(revenue)
        terms.append(f"({cogs_slot} / {revenue_slot})")
    if not years:
        missing.extend(["cogs_by_period", "revenue_by_period"])
    expression = f"({' + '.join(terms)}) / {len(terms)}" if terms else "average(cogs / revenue)"
    if missing:
        return _missing(
            "average_cogs_to_revenue",
            _ordered_unique(missing),
            facts=input_facts,
            diagnostics={
                "target_fiscal_years": years,
                "formula_definition": "average of annual cost of goods sold divided by annual revenue",
                "expression": expression,
            },
        )
    return _ready(
        "average_cogs_to_revenue",
        expression,
        variables,
        unit="percent",
        facts=input_facts,
        diagnostics={
            "target_fiscal_years": years,
            "formula_definition": "average of annual cost of goods sold divided by annual revenue",
        },
    )


def _plan_liquidation_value_per_share(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    assets = _latest_fact_for_year(facts, ("assets", "total assets"), target_year=target_year)
    liabilities = _latest_fact_for_year(facts, ("liabilities", "total liabilities"), target_year=target_year)
    shares = _latest_fact_for_year(
        facts,
        ("shares outstanding", "common shares outstanding", "weighted average shares"),
        target_year=target_year,
    )
    missing: list[str] = []
    if assets is None:
        missing.append("assets")
    if liabilities is None:
        missing.append("liabilities")
    if shares is None:
        missing.append("shares_outstanding")
    supporting = [fact for fact in (assets, liabilities, shares) if fact is not None]
    if missing:
        return _missing(
            "liquidation_value_per_share",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "total assets less total liabilities divided by shares outstanding",
            },
        )
    return _ready(
        "liquidation_value_per_share",
        "(assets - liabilities) / shares_outstanding",
        {"assets": assets.value, "liabilities": liabilities.value, "shares_outstanding": shares.value},
        unit="currency_per_share",
        facts=supporting,
        diagnostics={"target_fiscal_year": target_year},
    )


def _plan_debt_change(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    years = _target_fiscal_years(question)
    prior_year = min(years) if len(years) >= 2 else None
    current_year = max(years) if len(years) >= 2 else _target_fiscal_year(question)
    current = _latest_fact_for_year(facts, ("debt", "borrowings", "long term debt", "short term debt"), target_year=current_year)
    prior = (
        _latest_fact_for_year(facts, ("debt", "borrowings", "long term debt", "short term debt"), target_year=prior_year)
        if prior_year is not None
        else None
    )
    if prior is None and current is not None:
        prior = _latest_fact_for_year(
            facts,
            ("debt", "borrowings", "long term debt", "short term debt"),
            target_year=(current.fiscal_year - 1 if isinstance(current.fiscal_year, int) else None),
            exclude_fact_ids={current.fact_id},
        )
    missing: list[str] = []
    if prior is None:
        missing.append("prior_debt")
    if current is None:
        missing.append("current_debt")
    supporting = [fact for fact in (prior, current) if fact is not None]
    if missing:
        return _missing(
            "debt_change",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_years": years,
                "formula_definition": "current debt less prior debt",
            },
        )
    return _ready(
        "debt_change",
        "current_debt - prior_debt",
        {"prior_debt": prior.value, "current_debt": current.value},
        unit=current.unit,
        facts=supporting,
        diagnostics={"target_fiscal_years": years},
    )


def _plan_component_percent_of_total(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    metric_markers = _component_percent_metric_markers(question)
    component = _component_period_fact(facts, metric_markers=metric_markers, component_hint=_component_period_hint(question))
    total = _latest_fact(facts, metric_markers, exclude_fact_ids={component.fact_id} if component is not None else None)
    missing: list[str] = []
    if component is None:
        missing.append("component_amount")
    if total is None:
        missing.append("total_amount")
    supporting = [fact for fact in (component, total) if fact is not None]
    if missing:
        return _missing(
            "component_percent_of_total",
            missing,
            facts=supporting,
            diagnostics={
                "formula_definition": "component amount divided by total amount",
                "metric_markers": list(metric_markers),
            },
        )
    return _ready(
        "component_percent_of_total",
        "component_amount / total_amount",
        {"component_amount": _absolute_decimal_string(component.value), "total_amount": _absolute_decimal_string(total.value)},
        unit="percent",
        facts=supporting,
        diagnostics={"metric_markers": list(metric_markers)},
    )


def _plan_period_change(
    *,
    question: str,
    facts: list[FinanceFact],
    formula_name: str,
    markers: tuple[str, ...],
    prior_slot: str,
    current_slot: str,
    unit: str,
    formula_definition: str,
) -> FinanceFormulaPlan:
    years = _target_fiscal_years(question)
    prior_year = min(years) if len(years) >= 2 else None
    current_year = max(years) if len(years) >= 2 else _target_fiscal_year(question)
    current = _latest_fact_for_year(facts, markers, target_year=current_year)
    prior = _latest_fact_for_year(facts, markers, target_year=prior_year) if prior_year is not None else None
    if prior is None and current is not None:
        prior = _latest_fact_for_year(
            facts,
            markers,
            target_year=current.fiscal_year - 1 if isinstance(current.fiscal_year, int) else None,
            exclude_fact_ids={current.fact_id},
        )
    missing: list[str] = []
    if prior is None:
        missing.append(prior_slot)
    if current is None:
        missing.append(current_slot)
    supporting = [fact for fact in (prior, current) if fact is not None]
    if missing:
        return _missing(
            formula_name,
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_years": years,
                "formula_definition": formula_definition,
                "comparison_policy": "LLM decides increase/decrease/growth wording from the signed change and cited facts.",
            },
        )
    return _ready(
        formula_name,
        f"{current_slot} - {prior_slot}",
        {prior_slot: prior.value, current_slot: current.value},
        unit=unit,
        facts=supporting,
        diagnostics={
            "target_fiscal_years": years,
            "formula_definition": formula_definition,
            "comparison_policy": "LLM decides increase/decrease/growth wording from the signed change and cited facts.",
        },
    )


def _plan_cash_flow_activity_comparison(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    operating = _latest_fact_for_year(
        facts,
        ("operating cash flow", "cash flow from operations", "net cash provided by operating activities"),
        target_year=target_year,
    )
    investing = _latest_fact_for_year(
        facts,
        ("investing cash flow", "cash flow from investing activities", "net cash provided by investing activities", "net cash used in investing activities"),
        target_year=target_year,
    )
    financing = _latest_fact_for_year(
        facts,
        ("financing cash flow", "cash flow from financing activities", "net cash provided by financing activities", "net cash used in financing activities"),
        target_year=target_year,
    )
    missing: list[str] = []
    if operating is None:
        missing.append("operating_cash_flow")
    if investing is None:
        missing.append("investing_cash_flow")
    if financing is None:
        missing.append("financing_cash_flow")
    supporting = [fact for fact in (operating, investing, financing) if fact is not None]
    if missing:
        return _missing(
            "cash_flow_activity_comparison",
            missing,
            facts=supporting,
            diagnostics={
                "target_fiscal_year": target_year,
                "formula_definition": "maximum of operating, investing, and financing cash flow activity amounts",
                "comparison_policy": "LLM maps the maximum signed amount to the activity name and explains most cash brought in or least cash lost.",
            },
        )
    return _ready(
        "cash_flow_activity_comparison",
        "max(operating_cash_flow, investing_cash_flow, financing_cash_flow)",
        {
            "operating_cash_flow": operating.value,
            "investing_cash_flow": investing.value,
            "financing_cash_flow": financing.value,
        },
        unit=operating.unit,
        facts=supporting,
        diagnostics={
            "target_fiscal_year": target_year,
            "formula_definition": "maximum of operating, investing, and financing cash flow activity amounts",
            "comparison_policy": "LLM maps the maximum signed amount to the activity name and explains most cash brought in or least cash lost.",
        },
    )


def _plan_metric_lookup(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    spec = _metric_lookup_spec(question)
    if spec is None:
        return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "no_metric_lookup_spec"})
    slot_name = str(spec["slot_name"])
    markers = tuple(str(item) for item in spec.get("markers", []))
    target_year = _target_fiscal_year(question)
    predicate = _metric_lookup_predicate(str(spec.get("predicate") or ""))
    fact = _latest_fact_for_year(facts, markers, target_year=target_year, predicate=predicate)
    diagnostics: JsonObject = {
        "target_fiscal_year": target_year,
        "slot_name": slot_name,
        "formula_definition": "direct metric lookup from the cited filing line item",
        "semantic_decision_policy": (
            "The host only binds the requested metric slot. The LLM must verify the statement, period, unit, "
            "sign convention, and any explicit absence condition from cited evidence before finalizing."
        ),
    }
    if fact is None:
        return _missing("metric_lookup", [slot_name], diagnostics=diagnostics)
    value = _metric_lookup_value_for_formula(slot_name, fact.value)
    return _ready(
        "metric_lookup",
        slot_name,
        {slot_name: value},
        unit=fact.unit or str(spec.get("unit") or ""),
        facts=[fact],
        diagnostics={
            **diagnostics,
            "bound_line_item": _formula_bound_line_item(fact),
            "cash_flow_outflow_magnitude_policy": slot_name
            in {"capital_expenditures", "dividends_paid", "cogs", "restructuring_costs"},
        },
    )


def _metric_lookup_predicate(name: str):
    if name == "net_income":
        return _is_net_income_fact
    return None


def _metric_lookup_value_for_formula(slot_name: str, value: object) -> str:
    if slot_name in {"capital_expenditures", "dividends_paid", "cogs", "restructuring_costs"}:
        return _absolute_decimal_string(value)
    return str(value)


def _plan_disclosure_lookup(*, question: str) -> FinanceFormulaPlan:
    spec = _disclosure_lookup_spec(question)
    if spec is None:
        return FinanceFormulaPlan(status="not_applicable", diagnostics={"reason": "no_disclosure_lookup_spec"})
    slot_name = str(spec["slot_name"])
    return _missing(
        "disclosure_lookup",
        [slot_name],
        diagnostics={
            "slot_name": slot_name,
            "statement": spec.get("statement"),
            "line_item": spec.get("line_item"),
            "formula_definition": "source-grounded disclosure lookup with LLM-owned semantic judgment",
            "semantic_decision_policy": (
                "The host only identifies the disclosure evidence slot. The LLM must read cited filing evidence, "
                "decide the qualitative answer, and state uncertainty or absence explicitly."
            ),
        },
    )


def _plan_category_metric_rank(*, question: str, facts: list[FinanceFact]) -> FinanceFormulaPlan:
    target_year = _target_fiscal_year(question)
    target_years = _target_fiscal_years(question)
    target_fp = _target_fiscal_quarter(question)
    direction = _category_rank_direction(question)
    metric_focus = _category_rank_metric_focus(question)
    mode = _category_rank_mode(question)
    diagnostics: JsonObject = {
        "target_fiscal_year": target_year,
        "target_fiscal_years": target_years,
        "target_fiscal_quarter": target_fp,
        "rank_direction": direction,
        "metric_focus": metric_focus,
        "rank_mode": mode,
        "formula_definition": "rank numeric values from a cited category, segment, region, instrument, or line-item table",
        "semantic_decision_policy": (
            "The calculator only returns an extreme numeric value. The LLM must map that value back to the cited "
            "category row, resolve ties or disclosure wording, and explain the final answer from filing evidence."
        ),
    }
    if mode == "growth_rate" and len(target_years) >= 2:
        growth_plan = _plan_category_metric_growth_rank(
            question=question,
            facts=facts,
            prior_year=min(target_years),
            current_year=max(target_years),
            direction=direction,
            metric_focus=metric_focus,
            diagnostics=diagnostics,
        )
        if growth_plan.status != "missing_facts" or not facts:
            return growth_plan
    candidates = _category_rank_candidate_facts(
        question,
        facts,
        target_year=target_year,
        target_fp=target_fp,
        metric_focus=metric_focus,
    )
    if len(candidates) < 2:
        return _missing(
            "category_metric_rank",
            ["ranked_category_metric_table"],
            facts=[fact for _, fact in candidates],
            diagnostics={**diagnostics, "candidate_count": len(candidates)},
        )
    variables: JsonObject = {}
    variable_category_map: JsonObject = {}
    input_facts: list[FinanceFact] = []
    for index, (category, fact) in enumerate(candidates, start=1):
        variable = f"category_{index}"
        variables[variable] = fact.value
        variable_category_map[variable] = {
            "category": category,
            "bound_line_item": _formula_bound_line_item(fact),
        }
        input_facts.append(fact)
    operator = "min" if direction == "min" else "max"
    expression = f"{operator}({', '.join(variables.keys())})"
    return _ready(
        "category_metric_rank",
        expression,
        variables,
        unit=input_facts[0].unit,
        facts=input_facts,
        diagnostics={
            **diagnostics,
            "candidate_count": len(candidates),
            "variable_category_map": variable_category_map,
        },
    )


def _plan_category_metric_growth_rank(
    *,
    question: str,
    facts: list[FinanceFact],
    prior_year: int,
    current_year: int,
    direction: str,
    metric_focus: str,
    diagnostics: JsonObject,
) -> FinanceFormulaPlan:
    prior_candidates = _category_rank_candidate_facts(
        question,
        facts,
        target_year=prior_year,
        target_fp=None,
        metric_focus=metric_focus,
    )
    current_candidates = _category_rank_candidate_facts(
        question,
        facts,
        target_year=current_year,
        target_fp=None,
        metric_focus=metric_focus,
    )
    prior_by_category = {category: fact for category, fact in prior_candidates}
    current_by_category = {category: fact for category, fact in current_candidates}
    common_categories = [category for category in current_by_category if category in prior_by_category]
    if len(common_categories) < 2:
        return _missing(
            "category_metric_rank",
            ["ranked_category_metric_table"],
            facts=[fact for _, fact in [*prior_candidates, *current_candidates]],
            diagnostics={
                **diagnostics,
                "candidate_count": len(common_categories),
                "formula_definition": "rank category growth rates as (current period value - prior period value) / abs(prior period value)",
            },
        )
    variables: JsonObject = {}
    terms: list[str] = []
    input_facts: list[FinanceFact] = []
    variable_category_map: JsonObject = {}
    for index, category in enumerate(common_categories, start=1):
        prior_fact = prior_by_category[category]
        current_fact = current_by_category[category]
        prior_slot = f"category_{index}_prior"
        current_slot = f"category_{index}_current"
        variables[prior_slot] = prior_fact.value
        variables[current_slot] = current_fact.value
        term = f"(({current_slot} - {prior_slot}) / abs({prior_slot}))"
        terms.append(term)
        variable_category_map[f"category_{index}"] = {
            "category": category,
            "prior_slot": prior_slot,
            "current_slot": current_slot,
            "prior_bound_line_item": _formula_bound_line_item(prior_fact),
            "current_bound_line_item": _formula_bound_line_item(current_fact),
            "growth_expression": term,
        }
        input_facts.extend([prior_fact, current_fact])
    operator = "min" if direction == "min" else "max"
    expression = f"{operator}({', '.join(terms)})"
    return _ready(
        "category_metric_rank",
        expression,
        variables,
        unit="percent",
        facts=input_facts,
        diagnostics={
            **diagnostics,
            "candidate_count": len(common_categories),
            "formula_definition": "rank category growth rates as (current period value - prior period value) / abs(prior period value)",
            "variable_category_map": variable_category_map,
        },
    )


def _plan_margin_series(
    *,
    question: str,
    facts: list[FinanceFact],
    formula_name: str,
    mode: str,
) -> FinanceFormulaPlan:
    years = _margin_series_years(question)
    margin_kind = _margin_series_kind(question)
    variables: JsonObject = {}
    input_facts: list[FinanceFact] = []
    missing: list[str] = []
    terms: list[tuple[int, str]] = []
    for year in years:
        revenue = _latest_revenue_fact(facts, target_year=year)
        revenue_slot = f"revenue_{year}"
        revenue_missing = revenue is None
        if revenue is not None:
            variables[revenue_slot] = revenue.value
            input_facts.append(revenue)
        if margin_kind == "operating":
            numerator = _latest_fact_for_year(facts, ("operating income", "income from operations"), target_year=year)
            numerator_slot = f"operating_income_{year}"
            if numerator is None:
                missing.append(numerator_slot)
            else:
                variables[numerator_slot] = numerator.value
                input_facts.append(numerator)
            if revenue_missing:
                missing.append(revenue_slot)
            terms.append((year, f"({numerator_slot} / {revenue_slot})"))
            continue
        gross_profit = _latest_fact_for_year(facts, ("gross profit",), target_year=year)
        if gross_profit is not None:
            numerator_slot = f"gross_profit_{year}"
            variables[numerator_slot] = gross_profit.value
            input_facts.append(gross_profit)
            if revenue_missing:
                missing.append(revenue_slot)
            terms.append((year, f"({numerator_slot} / {revenue_slot})"))
            continue
        cogs = _dio_cogs_fact(facts, target_year=year)
        cogs_slot = f"cogs_{year}"
        if cogs is None:
            gross_profit_slot = f"gross_profit_{year}"
            missing.append(gross_profit_slot)
            if revenue_missing:
                missing.append(revenue_slot)
            terms.append((year, f"({gross_profit_slot} / {revenue_slot})"))
            continue
        else:
            variables[cogs_slot] = _absolute_decimal_string(cogs.value)
            input_facts.append(cogs)
        if revenue_missing:
            missing.append(revenue_slot)
        terms.append((year, f"(({revenue_slot} - {cogs_slot}) / {revenue_slot})"))
    if not years:
        base = "operating_income" if margin_kind == "operating" else "gross_profit_or_cogs"
        missing.extend([f"{base}_by_period", "revenue_by_period"])
    expression = _margin_series_expression(terms, mode=mode)
    formula_definition = (
        "range between maximum and minimum annual margin in the requested period"
        if mode == "range"
        else "ending annual margin less beginning annual margin in the requested period"
    )
    diagnostics = {
        "target_fiscal_years": years,
        "margin_kind": margin_kind,
        "formula_definition": formula_definition,
        "semantic_decision_policy": (
            "The host computes margin movement or range only. The LLM decides whether the margin is useful, improving, "
            "stable, or source-driven from cited evidence and any explicit threshold in the question."
        ),
        "expression": expression,
    }
    if missing:
        return _missing(
            formula_name,
            _ordered_unique(missing),
            facts=input_facts,
            diagnostics=diagnostics,
        )
    return _ready(
        formula_name,
        expression,
        variables,
        unit="percent",
        facts=input_facts,
        diagnostics=diagnostics,
    )


def _margin_series_years(question: str) -> list[int]:
    years = _target_fiscal_years(question)
    if len(years) >= 2:
        start, end = min(years), max(years)
        if end - start <= 10:
            return list(range(start, end + 1))
        return years
    if len(years) == 1:
        return [years[0] - 2, years[0] - 1, years[0]]
    return []


def _margin_series_kind(question: str) -> str:
    text = _metric_text(question)
    if "operating margin" in text or "operating margins" in text:
        return "operating"
    return "gross"


def _margin_series_expression(terms: list[tuple[int, str]], *, mode: str) -> str:
    ordered_terms = [term for _year, term in sorted(terms)]
    if not ordered_terms:
        return "margin_range" if mode == "range" else "ending_margin - beginning_margin"
    if mode == "range":
        joined = ", ".join(ordered_terms)
        return f"max({joined}) - min({joined})"
    if len(ordered_terms) == 1:
        return ordered_terms[0]
    return f"{ordered_terms[-1]} - {ordered_terms[0]}"


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
            "restructuring activities",
            "impairment",
            "impairment losses",
            "stock-based compensation",
            "stock based compensation",
            "equity award compensation",
            "equity award compensation expense",
            "legal and regulatory",
            "regulatory matters",
            "commodity hedges",
            "unrealized losses",
            "unrealized gains",
            "deduction",
            "cash charges",
            "one-time cost",
            "deal costs",
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


def _first_metric_pair(
    facts: list[FinanceFact],
    markers: tuple[str, ...],
    *,
    predicate=None,
) -> tuple[FinanceFact, FinanceFact] | None:
    by_metric: dict[str, list[FinanceFact]] = {}
    for fact in _facts_for_metric(facts, markers):
        if predicate is not None and not predicate(fact):
            continue
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
    predicate=None,
) -> FinanceFact | None:
    excluded = exclude_fact_ids or set()
    matches = [fact for fact in _facts_for_metric(facts, markers) if fact.fact_id not in excluded]
    if predicate is not None:
        matches = [fact for fact in matches if predicate(fact)]
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
        return _sort_target_year_facts(target_matches)[-1]
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


def _latest_effective_tax_rate_fact(
    facts: list[FinanceFact],
    *,
    target_year: int | None,
    exclude_fact_ids: set[str] | None = None,
) -> FinanceFact | None:
    excluded = exclude_fact_ids or set()
    matches = [
        fact
        for fact in _facts_for_metric(facts, ("effective tax rate", "income tax rate", "tax rate"))
        if fact.fact_id not in excluded and _is_effective_tax_rate_fact(fact)
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
    return _sort_target_year_facts(matches)[-1]


def _is_effective_tax_rate_fact(fact: FinanceFact) -> bool:
    text = _fact_text(fact)
    compact = "".join(ch for ch in text if ch.isalnum())
    if "effectivetaxrate" in compact:
        return True
    return "effective tax rate" in text


def _component_percent_metric_markers(question: str) -> tuple[str, ...]:
    text = _metric_text(question)
    if "stock repurchase" in text or "share repurchase" in text:
        return ("share repurchases", "stock repurchases", "repurchases of common stock")
    if "dividend" in text:
        return ("dividends paid", "cash dividends paid", "dividends to shareholders")
    if "capital expenditure" in text or "capex" in text:
        return ("capital expenditures", "capex")
    return ("amount", "total")


def _component_period_hint(question: str) -> str | None:
    text = _metric_text(question)
    if "q4" in text or "fourth quarter" in text:
        return "q4"
    if "q3" in text or "third quarter" in text:
        return "q3"
    if "q2" in text or "second quarter" in text:
        return "q2"
    if "q1" in text or "first quarter" in text:
        return "q1"
    return None


def _component_period_fact(
    facts: list[FinanceFact],
    *,
    metric_markers: tuple[str, ...],
    component_hint: str | None,
) -> FinanceFact | None:
    matches = _facts_for_metric(facts, metric_markers)
    if not matches:
        return None
    if component_hint:
        hinted = [
            fact
            for fact in matches
            if component_hint in _metric_text(
                " ".join(
                    str(value or "")
                    for value in (
                        fact.period,
                        fact.metadata.get("label"),
                        fact.metadata.get("context"),
                        fact.metadata.get("frame"),
                        fact.metadata.get("fp"),
                    )
                )
            )
        ]
        if hinted:
            return _sort_target_year_facts(hinted)[-1]
    quarterly = [fact for fact in matches if _fact_period_priority(fact) == 1]
    if quarterly:
        return _sort_target_year_facts(quarterly)[-1]
    return None


def _is_revenue_fact(fact: FinanceFact) -> bool:
    texts = [
        _metric_text(fact.metric),
        _metric_text(str(fact.metadata.get("label") or "")),
        _metric_text(str(fact.metadata.get("concept") or "")),
    ]
    blocked = ("cost of revenue", "costofrevenue", "expense", "interest income")
    blocked += (
        "contract liability",
        "contractwithcustomerliability",
        "deferred revenue",
        "remaining performance obligation",
        "performance obligation",
        "revenuerecognized",
    )
    if any(any(marker in text for marker in blocked) for text in texts):
        return False
    exact = {
        "revenue",
        "revenues",
        "net revenue",
        "net sales",
        "net revenues",
        "total net revenues",
        "total revenue",
        "total revenues",
        "total revenues and other income",
        "sales",
        "operating revenue",
        "operating revenues",
        "sales and other operating revenue",
        "sales and other operating revenues",
        "sales revenue net",
        "sales revenue goods net",
        "sales revenue services net",
    }
    compact_exact = {
        "revenuefromcontractwithcustomerexcludingassessedtax",
        "revenuefromcontractwithcustomerincludingassessedtax",
        "salesandotheroperatingrevenue",
        "operatingrevenues",
        "salesrevenuegoodsnet",
        "salesrevenueservicesnet",
        "salesrevenuenet",
        "revenuesnetofinterestexpense",
        "totalrevenuesandotherincome",
    }
    return any(text in exact or text.replace(" ", "") in compact_exact for text in texts)


def _is_net_income_fact(fact: FinanceFact) -> bool:
    concept = _metric_text(str(fact.metadata.get("concept") or "")).replace(" ", "")
    label = _metric_text(str(fact.metadata.get("label") or ""))
    metric = _metric_text(fact.metric)
    combined_compact = _metric_text(
        f"{fact.metric} {fact.metadata.get('concept') or ''} {fact.metadata.get('label') or ''}"
    ).replace(" ", "")
    blocked = (
        "incometax",
        "incometaxes",
        "taxexpense",
        "taxespaid",
        "taxpaid",
        "deferredtax",
        "provisionforincometaxes",
        "beforeincometaxes",
        "interestincome",
        "operatingincome",
        "noninterestincome",
    )
    if any(marker in combined_compact for marker in blocked):
        return False
    if concept in {
        "netincomeloss",
        "profitloss",
        "netincomelossavailabletocommonstockholdersbasic",
        "netincomelossattributabletoparent",
    }:
        return True
    if any(marker in label for marker in ("net income", "net earnings", "net loss")):
        return True
    return metric in {"net income", "net earnings", "net loss"} and not concept and not label


def _revenue_fact_sort_key(fact: FinanceFact) -> tuple[int, int, int, Decimal, int, str, str, str]:
    value = _decimal_or_none(fact.value) or Decimal(0)
    return (
        _revenue_concept_priority(fact),
        _fact_period_priority(fact),
        _fact_source_priority(fact),
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
    if "totalrevenuesandotherincome" in concept.replace(" ", "") or (
        "revenue" in label and "other income" in label
    ):
        return 5
    if any(marker in label or marker in concept for marker in demoted_markers):
        return -10
    primary_concepts = {
        "salesandotheroperatingrevenue": 104,
        "operatingrevenues": 102,
        "revenues": 100,
        "revenuefromcontractwithcustomerexcludingassessedtax": 98,
        "revenuefromcontractwithcustomerincludingassessedtax": 96,
        "salesrevenuegoodsnet": 94,
        "salesrevenueservicesnet": 92,
        "salesrevenuenet": 90,
    }
    compact_concept = concept.replace(" ", "")
    if compact_concept in primary_concepts:
        return primary_concepts[compact_concept]
    if metric in {
        "revenue",
        "revenues",
        "total revenue",
        "total revenues",
        "net revenue",
        "net sales",
        "net revenues",
        "total net revenues",
        "sales",
        "operating revenue",
        "operating revenues",
        "sales and other operating revenue",
        "sales and other operating revenues",
    }:
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


def _dpo_accounts_payable_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    return _sort_unique_facts([fact for fact in facts if _dpo_accounts_payable_eligible(fact)])


def _dpo_accounts_payable_pair(facts: list[FinanceFact], *, target_year: int | None) -> list[FinanceFact]:
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


def _dpo_accounts_payable_eligible(fact: FinanceFact) -> bool:
    text = _fact_text(fact)
    compact = "".join(ch for ch in text if ch.isalnum())
    if any(marker in compact for marker in ("tradeaccountspayable", "accountspayablecurrent", "accountspayable")):
        return True
    metric = _metric_text(fact.metric)
    return metric in {"accounts payable", "account payable", "trade accounts payable", "payables"}


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


def _sort_target_year_facts(facts: list[FinanceFact]) -> list[FinanceFact]:
    return sorted(
        facts,
        key=lambda fact: (
            _fact_period_priority(fact),
            _fact_source_priority(fact),
            _fact_specificity(fact),
            fact.fiscal_year or 0,
            str(fact.metadata.get("end") or ""),
            str(fact.metadata.get("filed") or ""),
            str(fact.period or ""),
            fact.fact_id,
        ),
    )


def _fact_period_priority(fact: FinanceFact) -> int:
    metadata = fact.metadata if isinstance(fact.metadata, dict) else {}
    form = str(metadata.get("form") or "").upper().replace(" ", "")
    fp = str(metadata.get("fp") or "").upper().replace(" ", "")
    frame = str(metadata.get("frame") or "").upper().replace(" ", "")
    period = str(fact.period or metadata.get("period") or "").strip().lower()
    if period in {"quarterly", "quarter", "qtr"} or form == "10-Q" or fp.startswith("Q") or re.search(r"CY\d{4}Q\d", frame):
        return 1
    if (
        period in {"annual", "year", "yearly"}
        or period.startswith("fy")
        or re.fullmatch(r"(?:19|20)\d{2}", period)
        or form in {"10-K", "20-F", "40-F"}
        or fp == "FY"
    ):
        return 4
    if period in {"ttm", "trailing twelve months", "ltm", "last twelve months"}:
        return 3
    return 2


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
            _fact_source_priority(fact),
            str(fact.metadata.get("end") or ""),
            str(fact.metadata.get("filed") or ""),
            str(fact.period or ""),
            fact.fact_id,
        ),
    )


def _fact_source_priority(fact: FinanceFact) -> int:
    source = str(fact.metadata.get("source") or "").strip().lower()
    if source in {"structured", "sec_companyfacts", "sec_xbrl_companyfacts"}:
        return 4
    if source == "natural_table_row":
        return 3
    if source == "natural_text":
        return 1
    return 0


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
    years = _target_fiscal_years(question)
    return years[0] if years else None


def _target_fiscal_years(question: str) -> list[int]:
    years: list[int] = []
    seen: set[int] = set()
    text = str(question or "")
    for match in re.finditer(r"\b(?:FY|fiscal\s+year\s*)?(?P<year>20\d{2}|19\d{2})\b", text, re.IGNORECASE):
        year = int(match.group("year"))
        if year in seen:
            continue
        seen.add(year)
        years.append(year)
    for match in re.finditer(r"\bFY\s*'?(?P<year>\d{2})\b", text, re.IGNORECASE):
        short_year = int(match.group("year"))
        year = 1900 + short_year if short_year >= 70 else 2000 + short_year
        if year in seen:
            continue
        seen.add(year)
        years.append(year)
    return years


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
