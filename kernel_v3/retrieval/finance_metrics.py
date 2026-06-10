from __future__ import annotations

import re
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject


@dataclass(frozen=True, kw_only=True)
class FinanceMetricIntent:
    metric_family: str | None = None
    preferred_phrases: tuple[str, ...] = field(default_factory=tuple)
    required_phrases: tuple[str, ...] = field(default_factory=tuple)
    demoted_phrases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def active(self) -> bool:
        return bool(self.metric_family or self.preferred_phrases or self.required_phrases or self.demoted_phrases)


def finance_metric_intent(query: str) -> FinanceMetricIntent:
    normalized = _normalize(query)
    if not normalized:
        return FinanceMetricIntent()

    if _has_all(normalized, "total", "assets") or "totalassets" in _compact(normalized):
        return FinanceMetricIntent(
            metric_family="assets",
            preferred_phrases=(
                "metric=assets",
                "concept=assets",
                "label=assets",
                "total assets",
            ),
            required_phrases=("assets",),
            demoted_phrases=(
                "shareholders equity",
                "stockholders equity",
                "liabilities",
                "revenue",
                "income",
                "cash flow",
            ),
        )

    if "net sales" in normalized or _has_all(normalized, "net", "sales"):
        return FinanceMetricIntent(
            metric_family="net_sales",
            preferred_phrases=(
                "metric=net sales",
                "concept=salesrevenuenet",
                "label=sales revenue net",
                "net sales",
            ),
            required_phrases=("sales",),
            demoted_phrases=(
                "membership fee",
                "cost of revenue",
                "gross profit",
                "revenue from contract",
            ),
        )

    if "sales and other operating revenues" in normalized:
        return FinanceMetricIntent(
            metric_family="sales_and_other_operating_revenues",
            preferred_phrases=(
                "metric=sales and other operating revenues",
                "concept=salesandotheroperatingrevenue",
                "sales and other operating revenues",
            ),
            required_phrases=("revenue",),
            demoted_phrases=("concept=revenues ", "metric=revenue "),
        )

    if "total revenues and other income" in normalized:
        return FinanceMetricIntent(
            metric_family="total_revenues_and_other_income",
            preferred_phrases=(
                "metric=total revenues and other income",
                "concept=totalrevenuesandotherincome",
                "total revenues and other income",
            ),
            required_phrases=("revenue",),
            demoted_phrases=("concept=revenues ", "metric=revenue "),
        )

    if _has_any(normalized, "total revenues", "total revenue"):
        return FinanceMetricIntent(
            metric_family="total_revenues",
            preferred_phrases=(
                "metric=total revenues and other income",
                "concept=totalrevenuesandotherincome",
                "total revenues and other income",
                "metric=sales and other operating revenues",
                "concept=salesandotheroperatingrevenue",
                "sales and other operating revenues",
                "metric=operating revenues",
                "concept=operatingrevenues",
                "total revenues",
                "metric=revenue",
            ),
            required_phrases=("revenue",),
            demoted_phrases=(
                "interest income",
                "net interest income",
                "investment income",
                "deferred revenue",
            ),
        )

    if _has_any(normalized, "operating cash flow", "cash flow from operations"):
        return FinanceMetricIntent(
            metric_family="operating_cash_flow",
            preferred_phrases=(
                "metric=operating cash flow",
                "concept=netcashprovidedbyusedinoperatingactivities",
                "cash flow from operations",
                "operating activities",
            ),
            required_phrases=("cash",),
            demoted_phrases=("investing activities", "financing activities"),
        )

    if "dio" in normalized or "days inventory" in normalized or _has_all(normalized, "inventory", "cost"):
        return FinanceMetricIntent(
            metric_family="days_inventory_outstanding",
            preferred_phrases=(
                "metric=inventory",
                "concept=inventorynet",
                "merchandise inventories",
                "metric=cost of revenue",
                "concept=costofrevenue",
                "metric=cost of goods sold",
                "concept=costofgoodsandservicessold",
                "cost of sales",
            ),
            required_phrases=("inventory",),
            demoted_phrases=(
                "deferred tax",
                "valuation reserves",
                "cash flow hedge",
                "interest income",
                "interest expense",
                "revenue from contract",
                "net income",
            ),
        )

    if (
        _has_any(normalized, "ev/ebitda", "ev / ebitda", "enterprise value to ebitda")
        or _has_all(normalized, "enterprise", "value", "ebitda")
        or _has_all(normalized, "ev", "ebitda")
    ):
        return FinanceMetricIntent(
            metric_family="ev_ebitda",
            preferred_phrases=(
                "metric=enterprise value",
                "enterprise value",
                "metric=market cap",
                "market cap",
                "metric=debt",
                "metric=long-term debt",
                "metric=short-term debt",
                "metric=cash and cash equivalents",
                "cash and cash equivalents",
                "metric=ebitda",
                "metric=net income",
                "metric=interest expense",
                "metric=income tax expense",
                "metric=depreciation and amortization",
                "depreciation and amortization",
            ),
            required_phrases=("value",),
            demoted_phrases=(
                "inventory",
                "cost of goods",
                "cost of sales",
                "revenue from contract",
            ),
        )

    if _has_any(normalized, "net income", "net profit"):
        return FinanceMetricIntent(
            metric_family="net_income",
            preferred_phrases=(
                "metric=net income",
                "concept=netincomeloss",
                "net income",
                "net earnings",
            ),
            required_phrases=("income",),
            demoted_phrases=("operating income", "gross profit", "revenue"),
        )

    if _has_any(normalized, "diluted eps", "diluted earnings per share"):
        return FinanceMetricIntent(
            metric_family="diluted_eps",
            preferred_phrases=(
                "metric=diluted earnings per share",
                "concept=earningspersharediluted",
                "diluted earnings per share",
                "diluted eps",
            ),
            required_phrases=("earnings",),
            demoted_phrases=("basic earnings per share",),
        )

    if _has_all(normalized, "revenue") or _has_all(normalized, "revenues"):
        return FinanceMetricIntent(
            metric_family="revenue",
            preferred_phrases=(
                "metric=net sales",
                "metric=sales and other operating revenues",
                "metric=total revenues and other income",
                "metric=operating revenues",
                "metric=revenue",
                "concept=revenuefromcontractwithcustomerexcludingassessedtax",
                "concept=revenues",
            ),
            required_phrases=("revenue",),
            demoted_phrases=("deferred revenue", "interest income"),
        )

    return FinanceMetricIntent()


def finance_metric_intent_score(text: str, *, query: str) -> float:
    intent = finance_metric_intent(query)
    if not intent.active:
        return 0.0
    normalized = _normalize(text)
    compact = _compact(normalized)
    score = 0.0
    preferred_score = 0.0
    for index, phrase in enumerate(intent.preferred_phrases):
        phrase_norm = _normalize(phrase)
        phrase_compact = _compact(phrase_norm)
        if phrase_norm and phrase_norm in normalized:
            preferred_score += max(1.0, 12.0 - index)
        elif phrase_compact and phrase_compact in compact:
            preferred_score += max(0.8, 10.0 - index)
    score += preferred_score
    for phrase in intent.required_phrases:
        phrase_norm = _normalize(phrase)
        if phrase_norm and phrase_norm in normalized:
            score += 2.0
    for phrase in intent.demoted_phrases:
        phrase_norm = _normalize(phrase)
        phrase_compact = _compact(phrase_norm)
        if (phrase_norm and phrase_norm in normalized) or (phrase_compact and phrase_compact in compact):
            score -= 1.0 if preferred_score > 0 else 8.0
    if "period=annual" in normalized:
        score += 1.5
    if "form=10-k" in normalized or "10-k" in normalized:
        score += 1.0
    if re.search(r"\b20\d{2}\b", normalized):
        score += 0.5
    return score


def finance_metric_intent_diagnostics(text: str, *, query: str) -> JsonObject:
    intent = finance_metric_intent(query)
    if not intent.active:
        return {"active": False}
    normalized = _normalize(text)
    compact = _compact(normalized)
    matched_preferred = [
        phrase
        for phrase in intent.preferred_phrases
        if _normalize(phrase) in normalized or _compact(phrase) in compact
    ]
    matched_demoted = [
        phrase
        for phrase in intent.demoted_phrases
        if _normalize(phrase) in normalized or _compact(phrase) in compact
    ]
    return {
        "active": True,
        "metric_family": intent.metric_family,
        "score": finance_metric_intent_score(text, query=query),
        "matched_preferred": matched_preferred,
        "matched_demoted": matched_demoted,
    }


def _normalize(text: str) -> str:
    return " ".join(str(text or "").lower().replace("_", " ").replace("-", " ").split())


def _compact(text: str) -> str:
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def _has_any(text: str, *phrases: str) -> bool:
    return any(phrase in text for phrase in phrases)


def _has_all(text: str, *terms: str) -> bool:
    return all(term in text for term in terms)
