from __future__ import annotations

import re
from dataclasses import replace
from urllib.parse import urlparse

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact


def target_document_binding_from_metadata(metadata: JsonObject | None, *, question: str = "") -> JsonObject:
    metadata = metadata if isinstance(metadata, dict) else {}
    existing = metadata.get("target_document_binding")
    if isinstance(existing, dict) and existing:
        return dict(existing)
    text = " ".join(
        str(item or "")
        for item in (
            question,
            metadata.get("root_goal"),
            metadata.get("company"),
            metadata.get("doc_name"),
            metadata.get("doc_type"),
            metadata.get("doc_period"),
            metadata.get("required_statement"),
            metadata.get("required_line_item"),
        )
    )
    doc_link = _string(metadata.get("doc_link") or metadata.get("source_url"))
    required_line_item = _string(metadata.get("required_line_item")) or _required_line_item(text)
    required_statement = _string(metadata.get("required_statement")) or _required_statement(text, required_line_item=required_line_item)
    binding: JsonObject = {
        "schema": "holo.kernel_v3.finance.target_document_binding.v1",
        "company": _string(metadata.get("company") or metadata.get("issuer")),
        "doc_name": _string(metadata.get("doc_name")),
        "doc_link": doc_link,
        "doc_type": _string(metadata.get("doc_type") or metadata.get("sec_form")),
        "doc_period": _string(metadata.get("doc_period") or metadata.get("report_date")),
        "required_statement": required_statement,
        "required_line_item": required_line_item,
        "primary_source_required": bool(
            metadata.get("primary_source_required")
            or metadata.get("primary_source")
            or metadata.get("require_primary_source")
            or metadata.get("target_primary_source_required")
            or metadata.get("benchmark_doc_retrieval")
            or str(metadata.get("source_authority_requirement") or "").strip().lower() in {"primary", "primary_or_structured"}
        ),
    }
    if doc_link:
        parsed = urlparse(doc_link)
        binding["doc_host"] = parsed.netloc.lower()
        binding["doc_path_tail"] = parsed.path.rsplit("/", 1)[-1].lower()
    return {key: value for key, value in binding.items() if value not in (None, "", [])}


def attach_target_binding_to_facts(facts: list[FinanceFact], binding: JsonObject | None, *, question: str = "") -> list[FinanceFact]:
    binding = target_document_binding_from_metadata(binding, question=question)
    if not binding:
        return facts
    result: list[FinanceFact] = []
    for fact in facts:
        score, reasons = primary_source_numeric_binding_score(fact, binding=binding, question=question)
        result.append(
            replace(
                fact,
                metadata={
                    **dict(fact.metadata),
                    "target_document_binding_score": score,
                    "target_document_binding_reasons": reasons,
                    "target_document_binding": binding,
                    "target_document_binding_accepted": score >= _minimum_binding_score(binding),
                },
            )
        )
    return result


def primary_source_numeric_binding_resolution(
    facts: list[FinanceFact],
    binding: JsonObject | None,
    *,
    question: str = "",
) -> JsonObject:
    binding = target_document_binding_from_metadata(binding, question=question)
    if not binding:
        return {"status": "not_applicable", "selected_fact_ids": [], "rejected_candidates": []}
    scored: list[tuple[int, FinanceFact, list[str]]] = []
    for fact in facts:
        score, reasons = primary_source_numeric_binding_score(fact, binding=binding, question=question)
        scored.append((score, fact, reasons))
    scored.sort(key=lambda item: item[0], reverse=True)
    minimum = _minimum_binding_score(binding)
    selected = [fact for score, fact, _reasons in scored if score >= minimum]
    rejected = [
        {
            "fact_id": fact.fact_id,
            "metric": fact.metric,
            "value": fact.value,
            "source_uri": fact.metadata.get("source_uri"),
            "source_title": fact.metadata.get("source_title"),
            "score": score,
            "reasons": reasons,
        }
        for score, fact, reasons in scored
        if score < minimum
    ]
    return {
        "schema": "holo.kernel_v3.finance.primary_source_numeric_binding.v1",
        "status": "selected" if selected else "no_binding_match",
        "binding": binding,
        "selected_fact_ids": [fact.fact_id for fact in selected[:16]],
        "selected_count": len(selected),
        "rejected_count": len(rejected),
        "rejected_candidates": rejected[:32],
    }


def filter_facts_for_target_binding(
    facts: list[FinanceFact],
    binding: JsonObject | None,
    *,
    question: str = "",
) -> list[FinanceFact]:
    binding = target_document_binding_from_metadata(binding, question=question)
    if not binding or not binding.get("primary_source_required"):
        return facts
    filtered = [
        fact
        for fact in attach_target_binding_to_facts(facts, binding, question=question)
        if bool(fact.metadata.get("target_document_binding_accepted"))
    ]
    return filtered if filtered else []


def primary_source_numeric_binding_score(
    fact: FinanceFact,
    *,
    binding: JsonObject,
    question: str = "",
) -> tuple[int, list[str]]:
    reasons: list[str] = []
    score = 0
    source_uri = _string(fact.metadata.get("source_uri"))
    source_title = _string(fact.metadata.get("source_title"))
    if _same_target_document(source_uri, binding):
        score += 70
        reasons.append("target_document_match")
    elif _is_primary_filing_source(source_uri, source_title):
        score += 45
        reasons.append("primary_filing_source")
    elif "data.sec.gov/api/xbrl/companyfacts" in source_uri.lower():
        score += 35
        reasons.append("sec_structured_source")
    elif _is_secondary_market_source(source_uri, source_title):
        score -= 80
        reasons.append("secondary_market_source_rejected_for_primary_binding")
    if _period_matches(fact, binding):
        score += 25
        reasons.append("target_period_match")
    elif binding.get("doc_period"):
        score -= 25
        reasons.append("target_period_missing_or_mismatch")
    if _metric_matches(fact, binding=binding, question=question):
        score += 35
        reasons.append("target_line_item_match")
    if _statement_matches(fact, binding=binding):
        score += 15
        reasons.append("target_statement_match")
    if fact.citation_ref:
        score += 10
        reasons.append("citation_present")
    return score, reasons


def _minimum_binding_score(binding: JsonObject) -> int:
    return 85 if binding.get("primary_source_required") else 55


def _same_target_document(source_uri: str, binding: JsonObject) -> bool:
    doc_link = _string(binding.get("doc_link"))
    if not source_uri or not doc_link:
        return False
    source = source_uri.rstrip("/")
    target = doc_link.rstrip("/")
    if source == target or source.startswith(target) or target.startswith(source):
        return True
    parsed_source = urlparse(source)
    parsed_target = urlparse(target)
    return bool(parsed_source.netloc and parsed_source.netloc == parsed_target.netloc and parsed_source.path == parsed_target.path)


def _is_primary_filing_source(uri: str, title: str) -> bool:
    text = f"{uri} {title}".lower()
    return any(marker in text for marker in ("sec.gov/archives", "investors.", "annual report", "10-k", "10k", "form 10"))


def _is_secondary_market_source(uri: str, title: str) -> bool:
    text = f"{uri} {title}".lower()
    return any(marker in text for marker in ("stockanalysis.com", "macrotrends", "ycharts", "companiesmarketcap", "finance.yahoo"))


def _period_matches(fact: FinanceFact, binding: JsonObject) -> bool:
    period = _string(binding.get("doc_period"))
    if not period:
        return False
    period_year = _period_year(period)
    if period_year is not None and fact.fiscal_year == period_year:
        return True
    return str(fact.fiscal_year or "") == period or _string(fact.period) == period


def _metric_matches(fact: FinanceFact, *, binding: JsonObject, question: str) -> bool:
    metric = _string(fact.metric).lower()
    line_item = _string(binding.get("required_line_item")).lower()
    text = f"{question} {line_item}"
    if line_item in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        return metric in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}
    if line_item == "capital expenditures":
        return metric == "capital expenditures"
    if line_item == "revenue":
        return metric in {"revenue", "revenues", "net sales", "net revenues"}
    if line_item == "net income":
        return metric == "net income"
    return bool(metric and metric in text.lower())


def _statement_matches(fact: FinanceFact, *, binding: JsonObject) -> bool:
    statement = _string(binding.get("required_statement")).lower()
    if not statement:
        return False
    context = _string(fact.metadata.get("context")).lower()
    source_title = _string(fact.metadata.get("source_title")).lower()
    concept = _string(fact.metadata.get("concept")).lower()
    if statement == "cash_flow_statement":
        return any(marker in f"{context} {source_title} {concept}" for marker in ("cash flow", "cash flows", "paymentstoacquire"))
    if statement == "income_statement":
        return "income" in f"{context} {source_title} {concept}"
    if statement == "balance_sheet":
        return any(
            marker in f"{context} {source_title} {concept}"
            for marker in ("balance sheet", "assets", "liabilities", "propertyplantandequipment", "property plant and equipment")
        )
    return False


def _required_statement(text: str, *, required_line_item: str | None = None) -> str | None:
    normalized = _normalize(text)
    if "cash flow" in normalized or "cash-flow" in normalized:
        return "cash_flow_statement"
    if required_line_item == "capital expenditures":
        return "cash_flow_statement"
    if required_line_item == "property plant and equipment net":
        return "balance_sheet"
    if "balance sheet" in normalized:
        return "balance_sheet"
    if "income statement" in normalized or "statement of operations" in normalized:
        return "income_statement"
    if "reconciliation" in normalized or "non gaap" in normalized or "non-gaap" in normalized:
        return "non_gaap_reconciliation"
    return None


def _required_line_item(text: str) -> str | None:
    normalized = _normalize(text)
    if any(
        marker in normalized
        for marker in ("capital expenditure", "capital expenditures", "capex", "payments to acquire", "purchases of property")
    ):
        return "capital expenditures"
    if any(
        marker in normalized
        for marker in (
            "net ppne",
            "ppne",
            "net ppe",
            "net pp and e",
            "property plant and equipment net",
            "property plant and equipment  net",
        )
    ) or ("property plant and equipment" in normalized and "balance sheet" in normalized):
        return "property plant and equipment net"
    if any(marker in normalized for marker in ("net income", "net earnings")):
        return "net income"
    if any(marker in normalized for marker in ("revenue", "revenues", "net sales")):
        return "revenue"
    return None


def _normalize(value: object) -> str:
    return " ".join(_string(value).lower().replace("&", " and ").replace(",", " ").replace("(", " ").replace(")", " ").split())


def _string(value: object) -> str:
    return str(value or "").strip()


def _period_year(value: object) -> int | None:
    match = re.search(r"\b(?:FY|fiscal\s+year\s*)?((?:19|20)\d{2})\b", _string(value), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None
