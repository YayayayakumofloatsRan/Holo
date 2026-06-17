from __future__ import annotations

import re
from collections import Counter

from kernel_v3.contracts import JsonObject


FINANCE_QUESTION_REQUIREMENTS_SCHEMA = "holo.kernel_v3.finance_question_requirements.v1"
FINANCE_REQUIREMENT_FAMILY_ORDER = (
    "direct_line_item_or_disclosure",
    "defined_formula_calculation",
    "calculation_then_business_judgment",
    "driver_attribution_or_bridge",
    "table_ranking_or_comparison",
    "multi_entity_compare",
    "market_or_macro_context",
)
FINANCE_REQUIREMENT_TOOL_ORDER = (
    "source_acquisition",
    "structured_sec_facts",
    "document_table_extraction",
    "table_operations",
    "arithmetic",
    "provenance_ledgers",
    "numeric_verification",
    "semantic_synthesis",
    "temporary_workbench",
)
FINANCE_REQUIREMENT_LOOP_STAGE_ORDER = (
    "task_compile",
    "evidence_acquire",
    "ledger_bind",
    "transform_compute",
    "semantic_synthesis",
    "verify_or_replan",
)
FINANCE_REQUIREMENT_RISK_ORDER = (
    "needs_primary_filing",
    "needs_structured_xbrl",
    "needs_table_rows",
    "needs_multi_period",
    "needs_multi_entity",
    "needs_business_context",
    "needs_bridge_reconciliation",
    "needs_market_or_macro_context",
    "requires_calculator",
    "requires_verifier",
    "requires_table_sort",
    "needs_temporary_workbench",
)
FINANCE_REQUIREMENT_FAMILY_TOOLS: dict[str, tuple[str, ...]] = {
    "direct_line_item_or_disclosure": (
        "source_acquisition",
        "structured_sec_facts",
        "document_table_extraction",
        "provenance_ledgers",
        "semantic_synthesis",
    ),
    "defined_formula_calculation": (
        "source_acquisition",
        "structured_sec_facts",
        "document_table_extraction",
        "arithmetic",
        "provenance_ledgers",
        "numeric_verification",
        "semantic_synthesis",
    ),
    "calculation_then_business_judgment": (
        "source_acquisition",
        "structured_sec_facts",
        "document_table_extraction",
        "arithmetic",
        "provenance_ledgers",
        "numeric_verification",
        "semantic_synthesis",
    ),
    "driver_attribution_or_bridge": (
        "source_acquisition",
        "document_table_extraction",
        "table_operations",
        "arithmetic",
        "provenance_ledgers",
        "semantic_synthesis",
        "temporary_workbench",
    ),
    "table_ranking_or_comparison": (
        "source_acquisition",
        "document_table_extraction",
        "table_operations",
        "arithmetic",
        "provenance_ledgers",
        "numeric_verification",
        "semantic_synthesis",
        "temporary_workbench",
    ),
    "multi_entity_compare": (
        "source_acquisition",
        "structured_sec_facts",
        "document_table_extraction",
        "table_operations",
        "arithmetic",
        "provenance_ledgers",
        "numeric_verification",
        "semantic_synthesis",
        "temporary_workbench",
    ),
    "market_or_macro_context": (
        "source_acquisition",
        "table_operations",
        "provenance_ledgers",
        "semantic_synthesis",
        "temporary_workbench",
    ),
}


def infer_finance_question_requirements(
    question: str,
    *,
    category: str | None = None,
    source: str | None = None,
    workflow_type: str | None = None,
) -> JsonObject:
    """Infer model-visible finance workbench needs from question text only.

    The result is intentionally advisory: it exposes likely task families, tool
    categories, risk flags, and loop stages so the LLM can assemble a workbench.
    It does not contain answers, thresholds, gold/reference data, or final
    finance judgments.
    """

    features = finance_question_features(question, category=category, workflow_type=workflow_type)
    families = finance_requirement_families(features)
    risk_flags = finance_requirement_risk_flags(features)
    tool_categories = finance_requirement_tool_categories(families, risk_flags)
    loop_stages = finance_requirement_loop_stages(families, risk_flags)
    return {
        "schema": FINANCE_QUESTION_REQUIREMENTS_SCHEMA,
        "question_source": "question_text_and_public_metadata_only",
        "gold_or_reference_values_used": False,
        "public_metadata": {
            "category": category,
            "source": source,
            "workflow_type": workflow_type,
        },
        "question_features": features,
        "families": families,
        "risk_flags": risk_flags,
        "required_tool_categories": tool_categories,
        "loop_stages": loop_stages,
        "workflow_hints": finance_requirement_workflow_hints(families, risk_flags),
        "decision_owner": "model",
        "host_boundary": "requirements are workbench hints only; the model still chooses tools, facts, formulas, and finance judgment",
    }


def finance_requirement_family_has_tool_categories(family: str) -> bool:
    return family in FINANCE_REQUIREMENT_FAMILY_TOOLS


def finance_requirement_counter_summary(counter: Counter[str]) -> list[JsonObject]:
    return _counter_summary(counter, order=FINANCE_REQUIREMENT_FAMILY_ORDER)


def finance_tool_category_counter_summary(counter: Counter[str]) -> list[JsonObject]:
    return _counter_summary(counter, order=FINANCE_REQUIREMENT_TOOL_ORDER)


def finance_loop_stage_counter_summary(counter: Counter[str]) -> list[JsonObject]:
    return _counter_summary(counter, order=FINANCE_REQUIREMENT_LOOP_STAGE_ORDER)


def finance_risk_counter_summary(counter: Counter[str]) -> list[JsonObject]:
    return _counter_summary(counter, order=FINANCE_REQUIREMENT_RISK_ORDER)


def finance_question_features(
    question: str,
    *,
    category: str | None = None,
    workflow_type: str | None = None,
) -> JsonObject:
    text = _normalize_text(" ".join(value for value in (question, category or "", workflow_type or "") if value))
    formula_patterns = (
        "calculate",
        "compute",
        "ratio",
        "divided by",
        "percentage",
        "percent",
        "average",
        "margin",
        "turnover",
        "return on assets",
        "roa",
        "dio",
        "days inventory outstanding",
        "dpo",
        "days payable",
        "capex /",
        "cash flow",
        "working capital",
        "current ratio",
        "quick ratio",
        "growth",
        "change",
        "cagr",
    )
    table_patterns = (
        "table",
        "row",
        "rank",
        "ranking",
        "largest",
        "smallest",
        "highest",
        "lowest",
        "least",
        "most",
        "segment",
        "activity",
        "activities",
        "breakdown",
        "reconciliation",
    )
    driver_patterns = (
        "driver",
        "drivers",
        "why",
        "explain",
        "attribut",
        "due to",
        "because",
        "excluding",
        "adjusted",
        "bridge",
        "reconciliation",
        "foreign exchange",
        "fx",
        "m&a",
        "acquisition",
        "divestiture",
        "one-off",
        "pass-through",
    )
    judgment_patterns = (
        "is ",
        "whether",
        "compare",
        "appears",
        "more efficient",
        "less efficient",
        "healthy",
        "capital-intensive",
        "capital intensive",
        "liquidity",
        "solvency",
        "profitability",
        "business context",
        "reason from",
    )
    market_patterns = (
        "share price",
        "stock price",
        "market cap",
        "market capitalization",
        "beta",
        "treasury",
        "interest rate",
        "inflation",
        "cpi",
        "gdp",
        "exchange rate",
        "macro",
        "fred",
    )
    line_item_patterns = (
        "revenue",
        "sales",
        "net sales",
        "inventory",
        "inventories",
        "cost of sales",
        "cogs",
        "assets",
        "liabilities",
        "equity",
        "pp&e",
        "ppe",
        "property, plant and equipment",
        "property plant and equipment",
        "capex",
        "capital expenditures",
        "operating cash flow",
        "net income",
        "debt",
        "cash",
        "receivable",
        "payable",
    )
    filing_patterns = (
        "10-k",
        "10-q",
        "20-f",
        "annual report",
        "quarterly report",
        "public filing",
        "public filings",
        "filing",
        "sec",
        "edgar",
        "fy20",
        "fiscal",
    )
    compare_patterns = (
        "compare",
        "versus",
        " vs ",
        "both",
        "higher",
        "lower",
        "more",
        "less",
        "difference",
    )
    multi_period_patterns = (
        "three-year",
        "3-year",
        "multi-year",
        "year-over-year",
        "yoy",
        "from fy",
        "between fy",
        "fiscal years",
    )
    fy_mentions = re.findall(r"\bfy\s*20\d{2}\b|\b20\d{2}\b", text)
    ticker_mentions = re.findall(r"\b(?:nyse|nasdaq|amex)\s*:\s*[a-z]{1,5}\b", text)
    mentions_compare = _contains_any(text, compare_patterns) or len(ticker_mentions) >= 2
    mentions_multi_entity = len(ticker_mentions) >= 2 or bool(re.search(r"\bfor\s+[^.?!]{2,80}\s+and\s+[^.?!]{2,80}", text))
    return {
        "mentions_formula_or_ratio": _contains_any(text, formula_patterns),
        "mentions_table_or_ranking": _contains_any(text, table_patterns),
        "mentions_driver_or_bridge": _contains_any(text, driver_patterns),
        "mentions_business_judgment": _contains_any(text, judgment_patterns),
        "mentions_market_or_macro_context": _contains_any(text, market_patterns),
        "mentions_line_item_or_disclosure": _contains_any(text, line_item_patterns),
        "mentions_primary_filing": _contains_any(text, filing_patterns),
        "mentions_comparison": mentions_compare,
        "mentions_multi_period": len(set(fy_mentions)) >= 2 or _contains_any(text, multi_period_patterns),
        "mentions_multi_entity": mentions_multi_entity,
        "period_mentions": sorted(set(fy_mentions))[:8],
        "ticker_mentions": sorted(set(ticker_mentions))[:8],
    }


def finance_requirement_families(features: JsonObject) -> list[str]:
    families: list[str] = []
    if bool(features.get("mentions_line_item_or_disclosure")) or bool(features.get("mentions_primary_filing")):
        families.append("direct_line_item_or_disclosure")
    if bool(features.get("mentions_formula_or_ratio")):
        families.append("defined_formula_calculation")
    if bool(features.get("mentions_business_judgment")) and (
        bool(features.get("mentions_formula_or_ratio"))
        or bool(features.get("mentions_line_item_or_disclosure"))
        or bool(features.get("mentions_primary_filing"))
    ):
        families.append("calculation_then_business_judgment")
    if bool(features.get("mentions_driver_or_bridge")):
        families.append("driver_attribution_or_bridge")
    if bool(features.get("mentions_table_or_ranking")):
        families.append("table_ranking_or_comparison")
    if bool(features.get("mentions_multi_entity")) or bool(features.get("mentions_comparison")):
        families.append("multi_entity_compare")
    if bool(features.get("mentions_market_or_macro_context")):
        families.append("market_or_macro_context")
    if not families:
        families.append("direct_line_item_or_disclosure")
    return _ordered_unique(families, order=FINANCE_REQUIREMENT_FAMILY_ORDER)


def finance_requirement_risk_flags(features: JsonObject) -> list[str]:
    flags: list[str] = ["needs_primary_filing"]
    if bool(features.get("mentions_primary_filing")) or bool(features.get("mentions_line_item_or_disclosure")):
        flags.append("needs_structured_xbrl")
    if bool(features.get("mentions_table_or_ranking")):
        flags.extend(["needs_table_rows", "requires_table_sort", "needs_temporary_workbench"])
    if bool(features.get("mentions_multi_period")):
        flags.append("needs_multi_period")
    if bool(features.get("mentions_multi_entity")) or bool(features.get("mentions_comparison")):
        flags.extend(["needs_multi_entity", "needs_temporary_workbench"])
    if bool(features.get("mentions_business_judgment")):
        flags.append("needs_business_context")
    if bool(features.get("mentions_driver_or_bridge")):
        flags.extend(["needs_bridge_reconciliation", "needs_temporary_workbench"])
    if bool(features.get("mentions_market_or_macro_context")):
        flags.extend(["needs_market_or_macro_context", "needs_temporary_workbench"])
    if bool(features.get("mentions_formula_or_ratio")):
        flags.extend(["requires_calculator", "requires_verifier"])
    return _ordered_unique(flags, order=FINANCE_REQUIREMENT_RISK_ORDER)


def finance_requirement_tool_categories(families: list[str], risk_flags: list[str]) -> list[str]:
    tools: list[str] = []
    for family in families:
        tools.extend(FINANCE_REQUIREMENT_FAMILY_TOOLS.get(family, ()))
    if "requires_calculator" in risk_flags:
        tools.append("arithmetic")
    if "requires_verifier" in risk_flags:
        tools.append("numeric_verification")
    if "needs_temporary_workbench" in risk_flags:
        tools.append("temporary_workbench")
    return _ordered_unique(tools, order=FINANCE_REQUIREMENT_TOOL_ORDER)


def finance_requirement_loop_stages(families: list[str], risk_flags: list[str]) -> list[str]:
    stages = ["task_compile", "evidence_acquire", "ledger_bind", "semantic_synthesis", "verify_or_replan"]
    if (
        "defined_formula_calculation" in families
        or "calculation_then_business_judgment" in families
        or "driver_attribution_or_bridge" in families
        or "table_ranking_or_comparison" in families
        or "multi_entity_compare" in families
        or "requires_calculator" in risk_flags
        or "requires_table_sort" in risk_flags
    ):
        stages.append("transform_compute")
    return _ordered_unique(stages, order=FINANCE_REQUIREMENT_LOOP_STAGE_ORDER)


def finance_requirement_workflow_hints(families: list[str], risk_flags: list[str]) -> list[str]:
    hints = ["compile_task_spec", "acquire_primary_sources", "bind_evidence_slots"]
    if "transform_compute" in finance_requirement_loop_stages(families, risk_flags):
        hints.append("run_formula_or_table_transform")
    if "needs_business_context" in risk_flags:
        hints.append("synthesize_business_context_without_hard_threshold")
    else:
        hints.append("synthesize_with_citations")
    hints.append("verify_numeric_provenance_and_replan_if_needed")
    return hints


def _counter_summary(counter: Counter[str], *, order: tuple[str, ...]) -> list[JsonObject]:
    order_index = {name: index for index, name in enumerate(order)}
    rows = sorted(counter.items(), key=lambda item: (order_index.get(item[0], len(order_index)), item[0]))
    return [{"name": name, "count": count} for name, count in rows]


def _ordered_unique(values: list[str], *, order: tuple[str, ...]) -> list[str]:
    seen: set[str] = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    order_index = {name: index for index, name in enumerate(order)}
    return sorted(deduped, key=lambda value: (order_index.get(value, len(order_index)), value))


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.casefold()).strip()
