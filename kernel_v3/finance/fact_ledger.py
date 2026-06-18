from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from decimal import Decimal, InvalidOperation

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem


SUPPORTED_FINANCE_METRICS = {
    "revenue",
    "revenues",
    "net sales",
    "net revenues",
    "total revenues",
    "total revenues and other income",
    "sales and other operating revenues",
    "operating revenues",
    "segment revenue",
    "segment revenue from external customers",
    "segment income",
    "segment net income",
    "segment operating income",
    "ebitdar",
    "ebitdar contribution",
    "family of apps revenue",
    "reality labs revenue",
    "cloud and AI infrastructure investment",
    "net income",
    "net income loss",
    "cash and equivalents",
    "cash and cash equivalents",
    "short-term investments",
    "short term investments",
    "marketable securities",
    "debt securities",
    "notional value",
    "notional amount",
    "derivative instruments",
    "debt",
    "long term debt",
    "long-term debt",
    "short term debt",
    "short-term debt",
    "current long-term debt",
    "long-term debt and finance lease obligations",
    "current long-term debt and finance lease obligations",
    "shares outstanding",
    "cogs",
    "cost of sales",
    "cost of revenue",
    "inventory",
    "inventories",
    "adjusted ebitda",
    "ebitda",
    "depreciation and amortization",
    "d&a",
    "interest expense",
    "interest income",
    "net interest income",
    "tax",
    "income tax expense",
    "gross profit",
    "research and development expense",
    "r&d expense",
    "other expense",
    "other income",
    "general corporate expenses",
    "corporate expenses",
    "operating income",
    "income from continuing operations",
    "pretax income",
    "earnings available for fixed charges",
    "fixed charges",
    "medical loss ratio",
    "mlr standard",
    "mlr numerator",
    "mlr denominator",
    "premium revenue",
    "adjusted premium revenue",
    "medical claims",
    "quality improvement expenses",
    "mlr rebate",
    "diluted earnings per share",
    "basic earnings per share",
    "eps",
    "operating cash flow",
    "cash flow from operations",
    "net cash provided by operating activities",
    "investing cash flow",
    "cash flow from investing activities",
    "net cash provided by investing activities",
    "net cash used in investing activities",
    "financing cash flow",
    "cash flow from financing activities",
    "net cash provided by financing activities",
    "net cash used in financing activities",
    "free cash flow",
    "capital expenditures",
    "property plant and equipment net",
    "net property plant and equipment",
    "net ppne",
    "ppne",
    "assets",
    "liabilities",
    "current liabilities",
    "current assets",
    "accounts receivable",
    "accounts payable",
    "dividends paid",
    "cash dividends paid",
    "restructuring costs",
    "restructuring expenses",
    "gain on separation",
    "cash proceeds",
    "value at risk",
    "credit facility",
    "revolving credit agreement",
    "expected benefit payments",
    "organic sales",
    "organic growth",
    "organic revenue growth",
    "divestitures",
    "translation",
    "total sales change",
    "percent change",
    "percent of sales",
    "shareholders equity",
    "stockholders equity",
    "market cap",
    "market capitalization",
    "equity value",
    "enterprise value",
    "transaction value",
    "deal value",
    "purchase price",
    "consideration paid",
    "purchase consideration",
    "fair value of consideration",
    "goodwill",
    "intangible assets",
    "margin",
    "rate",
    "yield",
    "addback",
    "add-back",
    "deduction",
    "one-time cost",
    "store count",
    "stores",
}

KEY_PATTERN = re.compile(
    r"(?P<key>entityName|ticker|cik|taxonomy|concept|metric|label|unit|period_fy|period|fy|fp|form|filed|end|start|frame|accn|source_uri|source_title|source_kind|value|val|scale)=",
    re.IGNORECASE,
)
HTML_TABLE_FACT_PATTERN = re.compile(
    r"html_table_fact_(?P<table_index>\d+)_(?P<row_index>\d+)_(?P<fy>20\d{2}|19\d{2}):\s*"
    r"metric=(?P<metric>.*?)\s+fy=(?P=fy)\s+value=(?P<value>\([^)]+\)|[^\s]+)\s+scale=(?P<scale>[A-Za-z]+)",
    re.IGNORECASE,
)
HTML_SENTENCE_FACT_PATTERN = re.compile(
    r"html_sentence_fact_(?P<fact_index>\d+)_(?P<fy>20\d{2}|19\d{2}):\s*"
    r"metric=(?P<metric>.*?)\s+fy=(?P=fy)\s+value=(?P<value>\([^)]+\)|[^\s]+)\s+scale=(?P<scale>[A-Za-z]+)",
    re.IGNORECASE,
)
HTML_TABLE_COLUMN_CELL_PATTERN = re.compile(
    r"\bcolumn_(?P<index>\d+)=(?P<value>.*?)(?=\s*column_\d+=|\s*html_table_\d+_row_\d+:|$)",
    re.IGNORECASE,
)
HTML_TABLE_ROW_BOUNDARY_PATTERN = re.compile(r"\s+html_table_\d+_row_\d+:", re.IGNORECASE)
HTML_TABLE_SEGMENT_HEADING_PATTERN = re.compile(
    r"(?P<segment>[A-Z][A-Za-z&/ -]{2,90}?)\s+Business\s*\([^)]*consolidated\s+sales",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?P<prefix>[$€£¥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>%|bps|basis\s+points|basis\s+point|percentage\s+points|percentage\s+point|"
    r"million|billion|trillion|thousand|mn|bn|m|b|usd|dollars|shares)?",
    re.IGNORECASE,
)
SCALE_SCOPE_PATTERN = re.compile(
    r"\(\s*(?:in\s+)?(?P<paren>millions|million|billions|billion|thousands|thousand)\s*\)"
    r"|\b(?:amounts?|dollars|u\.s\.\s+dollars|usd|financial\s+data)\s+in\s+"
    r"(?P<named>millions|million|billions|billion|thousands|thousand)\b"
    r"|\bin\s+(?P<plain>millions|million|billions|billion|thousands|thousand)\b",
    re.IGNORECASE,
)
NATURAL_METRIC_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("transaction value", ("transaction value", "deal value", "total transaction", "valued at")),
    (
        "purchase price",
        (
            "purchase price",
            "purchase consideration",
            "consideration paid",
            "fair value of consideration",
            "right to receive",
        ),
    ),
    ("enterprise value", ("enterprise value",)),
    ("market cap", ("market cap", "market capitalization")),
    ("adjusted ebitda", ("adjusted ebitda", "adjusted earnings before interest")),
    ("ebitda", ("ebitda",)),
    ("addback", ("add-back", "add back", "addback", "added back", "restructuring", "impairment", "stock-based compensation")),
    ("deduction", ("deduction", "deducted", "less:", "less ")),
    ("net revenues", ("total net revenues", "net revenues", "net revenue")),
    ("net sales", ("net sales",)),
    ("total revenues and other income", ("total revenues and other income",)),
    ("sales and other operating revenues", ("sales and other operating revenues", "sales and other operating revenue")),
    ("operating revenues", ("operating revenues", "operating revenue")),
    ("total revenues", ("total revenues", "total revenue", "sales to customers")),
    ("revenue", ("revenue", "revenues")),
    (
        "operating cash flow",
        (
            "operating cash flow",
            "cash flow from operations",
            "net cash provided by operating activities",
            "net cash used in operating activities",
            "cash provided by operating activities",
        ),
    ),
    (
        "investing cash flow",
        (
            "investing cash flow",
            "cash flow from investing activities",
            "net cash provided by investing activities",
            "net cash used in investing activities",
            "net cash provided by used in investing activities",
        ),
    ),
    (
        "financing cash flow",
        (
            "financing cash flow",
            "cash flow from financing activities",
            "net cash provided by financing activities",
            "net cash used in financing activities",
            "net cash provided by used in financing activities",
        ),
    ),
    ("free cash flow", ("free cash flow",)),
    ("marketable securities", ("marketable securities", "short-term investments", "short term investments")),
    ("debt securities", ("debt securities", "available-for-sale debt securities", "available for sale debt securities")),
    ("notional value", ("notional value", "notional amount", "notional")),
    (
        "capital expenditures",
        (
            "capital expenditures",
            "capital expenditure",
            "capex",
            "purchases of property plant and equipment",
            "purchases of property, plant and equipment",
        ),
    ),
    (
        "property plant and equipment net",
        (
            "property, plant and equipment, net",
            "property, plant and equipment - net",
            "property, plant and equipment net",
            "property plant and equipment net",
            "property and equipment, net",
            "property and equipment - net",
            "property and equipment net",
            "net property, plant and equipment",
            "net property plant and equipment",
            "net property and equipment",
            "net pp&e",
            "net ppe",
            "net ppne",
            "ppne",
        ),
    ),
    ("assets", ("total assets", "assets")),
    ("current assets", ("total current assets", "current assets", "assets current")),
    ("accounts receivable", ("accounts receivable", "net accounts receivable", "receivables")),
    ("accounts payable", ("accounts payable", "trade accounts payable", "payables")),
    ("income from continuing operations", ("income from continuing operations", "income from continuing ops")),
    ("net income", ("net income", "net loss", "net earnings")),
    ("segment net income", ("segment net income", "business segment net income")),
    ("segment income", ("segment income", "business segment income", "segment profit")),
    ("ebitdar contribution", ("ebitdar contribution", "ebitdar")),
    ("operating income", ("operating income", "operating loss")),
    ("gross profit", ("gross profit",)),
    ("research and development expense", ("research and development expense", "research and development", "r&d expense", "rd expense")),
    ("dividends paid", ("dividends paid", "cash dividends paid", "dividends to shareholders")),
    ("restructuring costs", ("restructuring costs", "restructuring expenses", "restructuring charges")),
    ("gain on separation", ("gain on separation", "gain from separation", "gain related to separation")),
    ("cash proceeds", ("cash proceeds", "proceeds from separation", "proceeds")),
    ("value at risk", ("value at risk", "var")),
    ("credit facility", ("credit facility", "revolving credit agreement", "revolving credit facility")),
    ("expected benefit payments", ("expected benefit payments", "pension payments", "postretirement payments")),
    ("addback", ("other expense",)),
    ("deduction", ("other income",)),
    ("deduction", ("general corporate expenses", "corporate expenses")),
    ("margin", ("operating margin", "gross margin", "margin")),
    ("interest expense", ("interest expense",)),
    ("tax", ("income taxes", "income tax", "provision for", "benefit from income taxes")),
    (
        "earnings available for fixed charges",
        (
            "earnings available for fixed charges",
            "earnings before fixed charges",
        ),
    ),
    ("fixed charges", ("total fixed charges", "fixed charges")),
    ("medical loss ratio", ("medical loss ratio", "mlr")),
    (
        "mlr standard",
        (
            "minimum medical loss ratio",
            "medical loss ratio standard",
            "minimum mlr",
            "mlr standard",
            "required mlr",
        ),
    ),
    (
        "mlr numerator",
        (
            "mlr numerator",
            "claims and quality improvement expenses",
            "claims and quality improvement activities",
            "clinical services and quality improvement",
        ),
    ),
    (
        "mlr denominator",
        (
            "mlr denominator",
            "adjusted premium revenue",
            "premium revenue after taxes",
        ),
    ),
    (
        "adjusted premium revenue",
        (
            "adjusted premium revenue",
            "premium revenue after taxes",
            "rebate basis",
        ),
    ),
    ("premium revenue", ("premium revenue", "earned premium", "premiums earned", "earned premiums")),
    (
        "medical claims",
        (
            "medical claims",
            "incurred claims",
            "clinical services",
            "medical costs",
            "medical expenses",
            "health care costs",
        ),
    ),
    (
        "quality improvement expenses",
        (
            "quality improvement expenses",
            "quality improvement activities",
            "health care quality improvement",
            "quality improving activities",
        ),
    ),
    ("mlr rebate", ("mlr rebate", "medical loss ratio rebate", "rebate amount")),
    ("depreciation and amortization", ("depreciation and amortization", "d&a", "amortization")),
    ("deduction", ("divestiture-related license income", "license income", "gain on sale", "gains")),
    ("cash and cash equivalents", ("cash and cash equivalents", "cash equivalents", "cash and equivalents", "total cash")),
    ("store count", ("number of stores", "store count", "stores")),
    ("debt", ("total debt", "debt", "borrowings", "notes payable")),
    (
        "shareholders equity",
        (
            "shareholders equity",
            "shareholders' equity",
            "stockholders equity",
            "stockholders' equity",
            "total shareholders equity",
            "total shareholders' equity",
            "total stockholders equity",
            "total stockholders' equity",
            "total equity",
        ),
    ),
    ("current liabilities", ("total current liabilities", "current liabilities", "liabilities current")),
    ("liabilities", ("total liabilities", "liabilities")),
    ("goodwill", ("goodwill",)),
    ("intangible assets", ("intangible assets", "developed technology", "customer relationships")),
)


def build_finance_fact_ledger(
    *,
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
) -> list[FinanceFact]:
    citation_by_evidence = {item.evidence_id: item for item in citations}
    facts: list[FinanceFact] = []
    seen: set[str] = set()
    for item in evidence:
        citation = citation_by_evidence.get(item.evidence_id)
        for fact in _facts_from_text(item, citation):
            if fact.fact_id in seen:
                continue
            seen.add(fact.fact_id)
            facts.append(fact)
    return facts


def _facts_from_text(item: EvidenceItem, citation: CitationItem | None) -> list[FinanceFact]:
    text = " ".join(str(item.text or "").split())
    if not text:
        return []
    result: list[FinanceFact] = []
    if "html_table_fact_" not in text and "html_sentence_fact_" not in text:
        global_text, metric_segments = _metric_segments(text)
        global_values = _key_values(global_text)
        for segment in metric_segments:
            values = {**global_values, **_key_values(segment)}
            value = values.get("value") or values.get("val")
            metric = _canonical_metric(values.get("metric") or values.get("concept") or values.get("label") or "")
            if value is None or not metric or not _is_decimal(value):
                continue
            fact = _fact_from_values(values, item=item, citation=citation, metric=metric, value=value)
            result.append(fact)
    result.extend(_html_table_facts_from_text(text, item=item, citation=citation))
    result.extend(_html_sentence_facts_from_text(text, item=item, citation=citation))
    result.extend(_natural_facts_from_text(text, item=item, citation=citation))
    return result


def _html_table_facts_from_text(text: str, *, item: EvidenceItem, citation: CitationItem | None) -> list[FinanceFact]:
    facts: list[FinanceFact] = []
    for match in HTML_TABLE_FACT_PATTERN.finditer(str(text or "")):
        raw_metric = match.group("metric").strip()
        metric = _canonical_metric(raw_metric)
        value = _clean_html_table_fact_value(match.group("value"))
        if value is None or not metric or not _is_decimal(value):
            continue
        start = max(0, match.start() - 240)
        end = min(len(text), match.end() + 240)
        context = text[start:end]
        pre_context = text[start:match.start()]
        scale = match.group("scale")
        unit = None
        percentage_fact = _html_table_fact_is_percentage(raw_metric, context=context)
        if percentage_fact:
            scale = "actual"
            unit = "percent"
        values = {
            "metric": raw_metric,
            "concept": f"html_table_fact_{match.group('table_index')}_{match.group('row_index')}",
            "fy": match.group("fy"),
            "period": f"FY{match.group('fy')}",
            "value": value,
            "scale": scale,
        }
        if unit:
            values["unit"] = unit
        fact = _fact_from_values(values, item=item, citation=citation, metric=metric, value=value)
        segment_name = _html_table_segment_name(pre_context)
        metadata_extra: JsonObject = {}
        if percentage_fact:
            metadata_extra.update(
                {
                    "value_is_percentage": True,
                    "display_unit": "percent",
                    "scale_overridden_from": match.group("scale"),
                    "unit_inferred_from_table_context": True,
                }
            )
        if segment_name:
            metadata_extra["segment_name"] = segment_name
            metadata_extra["category_name"] = segment_name
        facts.append(
            replace(
                fact,
                fact_id="finfact-html-table-" + _short_hash(
                    item.evidence_id,
                    match.group("table_index"),
                    match.group("row_index"),
                    match.group("fy"),
                    raw_metric,
                    value,
                ),
                metadata={
                    **fact.metadata,
                    "source": "html_table_fact",
                    "raw": match.group(0),
                    "context": context,
                    "html_table_index": match.group("table_index"),
                    "html_table_row_index": match.group("row_index"),
                    "raw_metric": raw_metric,
                    **metadata_extra,
                },
            )
        )
    return facts


def _html_sentence_facts_from_text(text: str, *, item: EvidenceItem, citation: CitationItem | None) -> list[FinanceFact]:
    facts: list[FinanceFact] = []
    for match in HTML_SENTENCE_FACT_PATTERN.finditer(str(text or "")):
        raw_metric = match.group("metric").strip()
        metric = _canonical_metric(raw_metric)
        value = _clean_html_table_fact_value(match.group("value"))
        if value is None or not metric or not _is_decimal(value):
            continue
        values = {
            "metric": raw_metric,
            "concept": f"html_sentence_fact_{match.group('fact_index')}",
            "fy": match.group("fy"),
            "period": f"FY{match.group('fy')}",
            "value": value,
            "scale": match.group("scale"),
        }
        fact = _fact_from_values(values, item=item, citation=citation, metric=metric, value=value)
        start = max(0, match.start() - 240)
        end = min(len(text), match.end() + 360)
        facts.append(
            replace(
                fact,
                fact_id="finfact-html-sentence-" + _short_hash(
                    item.evidence_id,
                    match.group("fact_index"),
                    match.group("fy"),
                    raw_metric,
                    value,
                ),
                metadata={
                    **fact.metadata,
                    "source": "html_sentence_fact",
                    "raw": match.group(0),
                    "context": text[start:end],
                    "html_sentence_fact_index": match.group("fact_index"),
                    "raw_metric": raw_metric,
                },
            )
        )
    return facts


def _clean_html_table_fact_value(value: str) -> str | None:
    text = str(value or "").strip().replace("$", "").replace(",", "")
    text = re.sub(r"\s+", "", text)
    if text in {"", "-", "—", "--"}:
        return None
    return text


def _html_table_fact_is_percentage(raw_metric: str, *, context: str) -> bool:
    metric = " ".join(str(raw_metric or "").lower().split())
    if any(marker in metric for marker in ("percent", "margin", "rate", "yield", "ratio")):
        return True
    if metric not in {
        "organic sales",
        "organic growth",
        "organic revenue",
        "organic revenue growth",
        "divestitures",
        "divestiture",
        "acquisitions",
        "acquisition",
        "translation",
        "currency translation",
        "total sales change",
        "sales change",
    }:
        return False
    normalized_context = " ".join(str(context or "").lower().split())
    return any(
        marker in normalized_context
        for marker in (
            "percent change",
            "percent of sales",
            "organic sales",
            "total sales change",
            "components of change",
            "consolidated sales",
        )
    )


def _html_table_segment_name(context: str) -> str | None:
    matches = list(HTML_TABLE_SEGMENT_HEADING_PATTERN.finditer(str(context or "")))
    if not matches:
        return None
    raw = matches[-1].group("segment")
    value = " ".join(raw.replace("T able of Contents", "").replace("Table of Contents", "").split())
    value = re.sub(r"^.*\bscale\s*=\s*[A-Za-z]+\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^(?:millions|million|billions|billion|thousands|thousand|actual)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^\d+\s+", "", value).strip(" :-")
    return value or None


def _natural_facts_from_text(text: str, *, item: EvidenceItem, citation: CitationItem | None) -> list[FinanceFact]:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text or _looks_like_structured_companyfacts(normalized_text) or _looks_like_discovery_or_search_page(item):
        return []
    document_scale_context = normalized_text[:1000]
    facts: list[FinanceFact] = (
        _natural_table_row_facts_from_text(
            normalized_text,
            item=item,
            citation=citation,
            document_scale_context=document_scale_context,
        )
        if _natural_table_row_extraction_enabled(item=item, text=normalized_text)
        else []
    )
    for index, match in enumerate(AMOUNT_PATTERN.finditer(normalized_text), start=1):
        raw_number = match.group("number")
        raw_unit = match.group("unit") or ""
        if raw_unit.lower() in {"m", "b"} and match.end() < len(normalized_text) and normalized_text[match.end()].isalpha():
            raw_unit = ""
        if not raw_number:
            continue
        value_number = f"-{raw_number}" if _is_parenthesized_amount(normalized_text, match.start(), match.end()) else raw_number
        display_raw = f"({match.group(0).strip()})" if value_number.startswith("-") else match.group(0).strip()
        if not raw_unit and not (match.group("prefix") or "") and _looks_like_non_material_amount(raw_number):
            continue
        if _looks_like_standalone_year(raw_number, raw_unit, match.group("prefix") or ""):
            continue
        if _looks_like_period_day(
            normalized_text,
            match.start(),
            match.end(),
            raw_number=raw_number,
            unit=raw_unit,
            prefix=match.group("prefix") or "",
        ):
            continue
        if _looks_like_filing_item_or_identifier(
            normalized_text,
            match.start(),
            match.end(),
            raw_number=raw_number,
            unit=raw_unit,
            prefix=match.group("prefix") or "",
        ):
            continue
        start = max(0, match.start() - 140)
        end = min(len(normalized_text), match.end() + 180)
        context = normalized_text[start:end]
        metric = _metric_from_context(context, amount_offset=match.start() - start, amount_end=match.end() - start)
        if metric is None:
            continue
        if _looks_like_natural_context_noise(
            context,
            raw_number=raw_number,
            unit=raw_unit,
            prefix=match.group("prefix") or "",
            metric=metric,
            amount_offset=match.start() - start,
            amount_end=match.end() - start,
            document_scale_context=document_scale_context,
        ):
            continue
        value = _scaled_amount(value_number, raw_unit, match.group("prefix") or "")
        if value is None:
            continue
        scale_multiplier = _context_scale_multiplier(context, raw_unit=raw_unit)
        if scale_multiplier == Decimal(1):
            scale_multiplier = _context_scale_multiplier(document_scale_context, raw_unit=raw_unit)
        if scale_multiplier == Decimal(1):
            scale_multiplier = _nearby_scale_scope_multiplier(normalized_text, match.start(), raw_unit=raw_unit)
        value *= scale_multiplier
        scale_metadata = _scale_scope_metadata(scale_multiplier)
        year = _nearby_year(context)
        fact_id = "finfact-natural-" + _short_hash(
            item.evidence_id,
            str(index),
            metric,
            _decimal_string(value),
            str(year or ""),
        )
        facts.append(
            FinanceFact(
                fact_id=fact_id,
                entity=_natural_entity(item=item, text=normalized_text),
                ticker=None,
                period=str(year) if year is not None else None,
                fiscal_year=year,
                metric=metric,
                value=_decimal_string(value),
                unit=_natural_unit(match.group("prefix") or "", raw_unit),
                scale="actual",
                source_ref=citation.citation_id if citation is not None else item.evidence_id,
                evidence_ref=item.evidence_id,
                citation_ref=citation.citation_id if citation is not None else None,
                metadata={
                    "source": "natural_text",
                    "raw": display_raw,
                    "context": context[:500],
                    "source_uri": item.uri,
                    "source_title": item.title,
                    "supported_metric": metric in SUPPORTED_FINANCE_METRICS,
                    **scale_metadata,
                    **_evidence_fact_diagnostics(item),
                    "per_share": _context_indicates_per_share(
                        context,
                        amount_offset=match.start() - start,
                        amount_end=match.end() - start,
                    ),
                },
            )
        )
    return facts


def _evidence_has_target_line_item(item: EvidenceItem) -> bool:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    span_metadata = diagnostics.get("span_metadata") if isinstance(diagnostics.get("span_metadata"), dict) else {}
    return bool(
        diagnostics.get("target_slot")
        or diagnostics.get("target_line_item")
        or span_metadata.get("target_slot")
        or span_metadata.get("target_line_item")
        or isinstance(diagnostics.get("target_document_binding"), dict)
        or isinstance(span_metadata.get("target_document_binding"), dict)
    )


def _evidence_fact_diagnostics(item: EvidenceItem) -> JsonObject:
    diagnostics = item.diagnostics if isinstance(item.diagnostics, dict) else {}
    span_metadata = diagnostics.get("span_metadata") if isinstance(diagnostics.get("span_metadata"), dict) else {}
    result: JsonObject = {}
    for key in (
        "finance_metric_intent",
        "target_line_item",
        "target_slot",
        "target_period",
        "target_statement",
    ):
        value = span_metadata.get(key) if key in span_metadata else diagnostics.get(key)
        if value not in (None, "", [], {}):
            result[key] = value
    return result


def _natural_table_row_extraction_enabled(*, item: EvidenceItem, text: str) -> bool:
    if _evidence_has_target_line_item(item):
        return True
    lower = str(text or "").lower()
    if "adjusted ebitda" in lower and "reconciliation" in lower:
        return False
    return True


def _natural_table_row_facts_from_text(
    text: str,
    *,
    item: EvidenceItem,
    citation: CitationItem | None,
    document_scale_context: str,
) -> list[FinanceFact]:
    normalized_text = " ".join(str(text or "").split())
    lower = normalized_text.lower()
    facts: list[FinanceFact] = []
    seen: set[str] = set()
    for metric, markers in NATURAL_METRIC_MARKERS:
        metric = _canonical_metric(metric)
        if metric not in SUPPORTED_FINANCE_METRICS:
            continue
        for marker in markers:
            normalized_marker = " ".join(str(marker or "").lower().split())
            if not normalized_marker:
                continue
            for match in re.finditer(re.escape(normalized_marker), lower):
                years = _table_header_years(normalized_text[max(0, match.start() - 600) : match.start()])
                if not years:
                    continue
                after = normalized_text[match.end() : min(len(normalized_text), match.end() + 240)]
                amounts = _table_row_amounts(after, max_count=len(years))
                if len(amounts) < 2:
                    continue
                row_context = normalized_text[max(0, match.start() - 180) : min(len(normalized_text), match.end() + 240)]
                scale_multiplier = _context_scale_multiplier(row_context, raw_unit="")
                if scale_multiplier == Decimal(1):
                    scale_multiplier = _context_scale_multiplier(document_scale_context, raw_unit="")
                if scale_multiplier == Decimal(1):
                    scale_multiplier = _nearby_scale_scope_multiplier(normalized_text, match.start(), raw_unit="")
                for year, amount in zip(years, amounts):
                    raw_number, raw_unit, prefix, display_raw, signed_number = amount
                    value = _scaled_amount(signed_number, raw_unit, prefix)
                    if value is None:
                        continue
                    value *= scale_multiplier
                    scale_metadata = _scale_scope_metadata(scale_multiplier)
                    fact_key = f"{metric}|{year}|{_decimal_string(value)}|{item.evidence_id}"
                    if fact_key in seen:
                        continue
                    seen.add(fact_key)
                    fact_id = "finfact-table-row-" + _short_hash(
                        item.evidence_id,
                        marker,
                        metric,
                        str(year),
                        _decimal_string(value),
                    )
                    facts.append(
                        FinanceFact(
                            fact_id=fact_id,
                            entity=_natural_entity(item=item, text=normalized_text),
                            ticker=None,
                            period=str(year),
                            fiscal_year=year,
                            metric=metric,
                            value=_decimal_string(value),
                            unit=_natural_unit(prefix, raw_unit),
                            scale="actual",
                            source_ref=citation.citation_id if citation is not None else item.evidence_id,
                            evidence_ref=item.evidence_id,
                            citation_ref=citation.citation_id if citation is not None else None,
                            metadata={
                                "source": "natural_table_row",
                                "raw": display_raw,
                                "row_marker": marker,
                                "context": row_context[:500],
                                "source_uri": item.uri,
                                "source_title": item.title,
                                "supported_metric": True,
                                **scale_metadata,
                                **_evidence_fact_diagnostics(item),
                                "per_share": False,
                            },
                        )
                    )
    return facts


def _table_header_years(text: str) -> list[int]:
    matches = list(re.finditer(r"\b(20\d{2}|19\d{2})\b", str(text or "")))
    if not matches:
        return []
    cluster = [matches[-1]]
    cluster_start = matches[-1].start()
    for match in reversed(matches[:-1]):
        if cluster_start - match.end() > 80:
            break
        cluster.append(match)
        cluster_start = match.start()
    years: list[int] = []
    for match in reversed(cluster):
        year = int(match.group(1))
        if year not in years:
            years.append(year)
    return years[-6:]


def _table_row_amounts(after_marker: str, *, max_count: int) -> list[tuple[str, str, str, str, str]]:
    html_column_amounts = _table_row_amounts_from_html_columns(after_marker, max_count=max_count)
    if html_column_amounts:
        return html_column_amounts
    amounts: list[tuple[str, str, str, str, str]] = []
    first_amount = True
    for match in AMOUNT_PATTERN.finditer(str(after_marker or "")):
        if first_amount and match.start() > 80:
            return []
        gap_before_amount = str(after_marker or "")[: match.start()]
        normalized_gap = re.sub(r"\([^)]{0,40}\)", "", gap_before_amount)
        if first_amount and re.search(r"[A-Za-z]", normalized_gap):
            return []
        first_amount = False
        raw_number = match.group("number") or ""
        raw_unit = match.group("unit") or ""
        prefix = match.group("prefix") or ""
        if not raw_number:
            continue
        if _looks_like_standalone_year(raw_number, raw_unit, prefix):
            continue
        if raw_unit.lower() in {"m", "b"} and match.end() < len(after_marker) and after_marker[match.end()].isalpha():
            raw_unit = ""
        signed_number = f"-{raw_number}" if _is_parenthesized_amount(after_marker, match.start(), match.end()) else raw_number
        display_raw = f"({match.group(0).strip()})" if signed_number.startswith("-") else match.group(0).strip()
        amounts.append((raw_number, raw_unit, prefix, display_raw, signed_number))
        if len(amounts) >= max_count:
            break
    return amounts


def _table_row_amounts_from_html_columns(after_marker: str, *, max_count: int) -> list[tuple[str, str, str, str, str]]:
    text = str(after_marker or "")
    if "column_" not in text:
        return []
    row_segment = HTML_TABLE_ROW_BOUNDARY_PATTERN.split(text, maxsplit=1)[0]
    amounts: list[tuple[str, str, str, str, str]] = []
    for cell in HTML_TABLE_COLUMN_CELL_PATTERN.finditer(row_segment):
        raw_cell = " ".join(str(cell.group("value") or "").split())
        if raw_cell in {"", "$", "€", "£", "¥", "-", "—", "--"}:
            continue
        match = AMOUNT_PATTERN.search(raw_cell)
        if match is None:
            continue
        raw_number = match.group("number") or ""
        raw_unit = match.group("unit") or ""
        prefix = match.group("prefix") or ""
        if not raw_number:
            continue
        if _looks_like_standalone_year(raw_number, raw_unit, prefix):
            continue
        if raw_unit.lower() in {"m", "b"} and match.end() < len(raw_cell) and raw_cell[match.end()].isalpha():
            raw_unit = ""
        signed_number = f"-{raw_number}" if _is_parenthesized_amount(raw_cell, match.start(), match.end()) else raw_number
        display_raw = f"({match.group(0).strip()})" if signed_number.startswith("-") else match.group(0).strip()
        amounts.append((raw_number, raw_unit, prefix, display_raw, signed_number))
        if len(amounts) >= max_count:
            break
    return amounts


def _metric_segments(text: str) -> tuple[str, list[str]]:
    if "facts=" in text:
        before, after = text.split("facts=", 1)
        segments = [segment.strip() for segment in after.split(" ; ") if segment.strip()]
        return before, segments
    metric_match = re.search(r"\bmetric=", text, re.IGNORECASE)
    if metric_match is not None and " ; " in text[metric_match.start() :]:
        before = text[: metric_match.start()]
        after = text[metric_match.start() :]
        segments = [segment.strip() for segment in after.split(" ; ") if segment.strip()]
        return before, segments
    return text, [text]


def _key_values(text: str) -> dict[str, str]:
    matches = list(KEY_PATTERN.finditer(text))
    values: dict[str, str] = {}
    for index, match in enumerate(matches):
        key = match.group("key")
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        raw = text[start:end].strip()
        if raw:
            values[_normalize_key(key)] = raw
    return values


def _fact_from_values(
    values: dict[str, str],
    *,
    item: EvidenceItem,
    citation: CitationItem | None,
    metric: str,
    value: str,
) -> FinanceFact:
    fiscal_year = _int_or_none(values.get("period_fy")) or _int_or_none(values.get("fy"))
    unit = values.get("unit")
    scale = values.get("scale") or "actual"
    decimal_value = _decimal_amount_from_structured_value(value)
    if decimal_value is None:
        decimal_value = Decimal(str(value).replace(",", "").strip())
    actual_value = _scaled_value_from_scale(decimal_value, scale)
    fact_id = "finfact-" + _short_hash(
        item.evidence_id,
        metric,
        str(fiscal_year or ""),
        str(values.get("period") or ""),
        str(values.get("concept") or ""),
        _decimal_string(actual_value),
    )
    citation_ref = citation.citation_id if citation is not None else None
    metadata: JsonObject = {
        "concept": values.get("concept"),
        "label": values.get("label"),
        "cik": values.get("cik"),
        "taxonomy": values.get("taxonomy"),
        "period": values.get("period"),
        "form": values.get("form"),
        "fp": values.get("fp"),
        "filed": values.get("filed"),
        "end": values.get("end"),
        "start": values.get("start"),
        "duration_days": _period_duration_days(values.get("start"), values.get("end")),
        "frame": values.get("frame"),
        "accn": values.get("accn"),
        "supported_metric": metric in SUPPORTED_FINANCE_METRICS,
        "source_uri": values.get("source_uri") or item.uri,
        "source_title": values.get("source_title") or item.title,
        "source_kind": values.get("source_kind"),
        **_evidence_fact_diagnostics(item),
    }
    metadata = {key: item for key, item in metadata.items() if item not in (None, "")}
    return FinanceFact(
        fact_id=fact_id,
        entity=values.get("entityname"),
        ticker=values.get("ticker"),
        period=values.get("period"),
        fiscal_year=fiscal_year,
        metric=metric,
        value=_decimal_string(actual_value),
        unit=unit,
        scale=scale,
        source_ref=citation_ref or item.evidence_id,
        evidence_ref=item.evidence_id,
        citation_ref=citation_ref,
        metadata=metadata,
    )


def _scaled_value_from_scale(value: Decimal, scale: str) -> Decimal:
    text = str(scale or "").strip().lower()
    if text in {"thousand", "thousands", "in thousands"}:
        return value * Decimal(1_000)
    if text in {"million", "millions", "in millions", "mm"}:
        return value * Decimal(1_000_000)
    if text in {"billion", "billions", "in billions", "bn"}:
        return value * Decimal(1_000_000_000)
    if text in {"trillion", "trillions", "in trillions"}:
        return value * Decimal(1_000_000_000_000)
    return value


def _period_duration_days(start: str | None, end: str | None) -> int | None:
    start_days = _date_days(start)
    end_days = _date_days(end)
    if start_days is None or end_days is None:
        return None
    return max(0, end_days - start_days)


def _date_days(value: str | None) -> int | None:
    match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$", str(value or ""))
    if not match:
        return None
    return int(match.group("year")) * 372 + int(match.group("month")) * 31 + int(match.group("day"))


def _decimal_amount_from_structured_value(value: str) -> Decimal | None:
    text = str(value or "").strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()").replace(",", "").strip()
    decimal = _decimal_or_none(text)
    if decimal is None:
        return None
    return -decimal if negative else decimal


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_metric(value: str) -> str:
    text = " ".join(str(value or "").replace("_", " ").replace("-", " ").lower().split())
    aliases = {
        "revenues": "revenue",
        "revenuesnetofinterestexpense": "net revenues",
        "revenues net of interest expense": "net revenues",
        "net revenues": "net revenues",
        "net revenue": "net revenues",
        "total net revenues": "net revenues",
        "salesandotheroperatingrevenue": "sales and other operating revenues",
        "sales and other operating revenue": "sales and other operating revenues",
        "sales and other operating revenues": "sales and other operating revenues",
        "totalrevenuesandotherincome": "total revenues and other income",
        "total revenues and other income": "total revenues and other income",
        "operatingrevenues": "operating revenues",
        "operating revenues": "operating revenues",
        "operating revenue": "operating revenues",
        "segmentreportinginformationrevenue": "segment revenue",
        "segment reporting information revenue": "segment revenue",
        "segmentreportinginformationrevenuefromexternalcustomers": "segment revenue from external customers",
        "segment reporting information revenue from external customers": "segment revenue from external customers",
        "revenuesfromexternalcustomers": "segment revenue from external customers",
        "revenues from external customers": "segment revenue from external customers",
        "segmentincome": "segment income",
        "segment income": "segment income",
        "segmentprofit": "segment income",
        "segment profit": "segment income",
        "segmentnetincome": "segment net income",
        "segment net income": "segment net income",
        "segmentoperatingincome": "segment operating income",
        "segment operating income": "segment operating income",
        "ebitdar": "ebitdar",
        "ebitdarcontribution": "ebitdar contribution",
        "ebitdar contribution": "ebitdar contribution",
        "familyofappsrevenue": "family of apps revenue",
        "family of apps revenue": "family of apps revenue",
        "realitylabsrevenue": "reality labs revenue",
        "reality labs revenue": "reality labs revenue",
        "cloudandaiinfrastructureinvestment": "cloud and AI infrastructure investment",
        "cloud and ai infrastructure investment": "cloud and AI infrastructure investment",
        "total revenues": "total revenues",
        "total revenue": "total revenues",
        "sales to customers": "total revenues",
        "revenuefromcontractwithcustomerexcludingassessedtax": "revenue",
        "revenue from contract with customer excluding assessed tax": "revenue",
        "sales revenue net": "net sales",
        "net sales": "net sales",
        "notionalvalue": "notional value",
        "notional value": "notional value",
        "notionalamount": "notional value",
        "notional amount": "notional value",
        "debtsecurities": "debt securities",
        "debt securities": "debt securities",
        "marketablesecurities": "marketable securities",
        "marketable securities": "marketable securities",
        "profit loss": "net income",
        "netincomeloss": "net income",
        "net income loss": "net income",
        "incomelossfromcontinuingoperationsbeforeincometaxesextraordinaryitemsnoncontrollinginterest": "pretax income",
        "incomelossfromcontinuingoperationsbeforeincometaxes": "pretax income",
        "income loss from continuing operations before income taxes extraordinary items noncontrolling interest": "pretax income",
        "income loss from continuing operations before income taxes": "pretax income",
        "income from continuing operations": "income from continuing operations",
        "incomefromcontinuingoperations": "income from continuing operations",
        "earnings per share diluted": "diluted earnings per share",
        "earnings per share basic": "basic earnings per share",
        "inventory net": "inventory",
        "inventory": "inventory",
        "merchandise inventories": "inventory",
        "accountsreceivable": "accounts receivable",
        "accounts receivable": "accounts receivable",
        "netaccountsreceivable": "accounts receivable",
        "net accounts receivable": "accounts receivable",
        "accountsreceivablenetcurrent": "accounts receivable",
        "accounts receivable net current": "accounts receivable",
        "accounts payable": "accounts payable",
        "accountspayable": "accounts payable",
        "trade accounts payable": "accounts payable",
        "total current assets": "current assets",
        "totalcurrentassets": "current assets",
        "current assets": "current assets",
        "assetscurrent": "current assets",
        "costofrevenue": "cost of revenue",
        "cost of goods sold": "cogs",
        "netcashprovidedbyusedinoperatingactivities": "operating cash flow",
        "net cash provided by used in operating activities": "operating cash flow",
        "net cash provided by operating activities": "operating cash flow",
        "netcashprovidedbyoperatingactivities": "operating cash flow",
        "net cash used in operating activities": "operating cash flow",
        "netcashusedinoperatingactivities": "operating cash flow",
        "net cash provided by operating activities continuing operations": "operating cash flow",
        "net cash provided by used in operating activities continuing operations": "operating cash flow",
        "cash flow from investing activities": "investing cash flow",
        "cashflowfrominvestingactivities": "investing cash flow",
        "net cash provided by investing activities": "investing cash flow",
        "netcashprovidedbyinvestingactivities": "investing cash flow",
        "net cash used in investing activities": "investing cash flow",
        "netcashusedininvestingactivities": "investing cash flow",
        "net cash provided by used in investing activities": "investing cash flow",
        "netcashprovidedbyusedininvestingactivities": "investing cash flow",
        "cash flow from financing activities": "financing cash flow",
        "cashflowfromfinancingactivities": "financing cash flow",
        "net cash provided by financing activities": "financing cash flow",
        "netcashprovidedbyfinancingactivities": "financing cash flow",
        "net cash used in financing activities": "financing cash flow",
        "netcashusedinfinancingactivities": "financing cash flow",
        "net cash provided by used in financing activities": "financing cash flow",
        "netcashprovidedbyusedinfinancingactivities": "financing cash flow",
        "paymentsofdividends": "dividends paid",
        "payments of dividends": "dividends paid",
        "dividendspaid": "dividends paid",
        "dividends paid": "dividends paid",
        "cash dividends paid": "dividends paid",
        "cashdividendspaid": "dividends paid",
        "grossprofit": "gross profit",
        "gross profit": "gross profit",
        "restructuringcosts": "restructuring costs",
        "restructuring costs": "restructuring costs",
        "restructuringexpenses": "restructuring costs",
        "restructuring expenses": "restructuring costs",
        "restructuringcharges": "restructuring costs",
        "restructuring charges": "restructuring costs",
        "gainonseparation": "gain on separation",
        "gain on separation": "gain on separation",
        "cashproceeds": "cash proceeds",
        "cash proceeds": "cash proceeds",
        "valueatrisk": "value at risk",
        "value at risk": "value at risk",
        "var": "value at risk",
        "creditfacility": "credit facility",
        "credit facility": "credit facility",
        "revolvingcreditagreement": "revolving credit agreement",
        "revolving credit agreement": "revolving credit agreement",
        "expectedbenefitpayments": "expected benefit payments",
        "expected benefit payments": "expected benefit payments",
        "provisionforbenefitfromincometaxes": "tax",
        "provision for benefit from income taxes": "tax",
        "benefitfromincometaxes": "tax",
        "benefit from income taxes": "tax",
        "incometaxes": "tax",
        "income taxes": "tax",
        "interestexpense": "interest expense",
        "interest expense": "interest expense",
        "earningsavailableforfixedcharges": "earnings available for fixed charges",
        "earnings available for fixed charges": "earnings available for fixed charges",
        "earningsbeforefixedcharges": "earnings available for fixed charges",
        "earnings before fixed charges": "earnings available for fixed charges",
        "incomebeforefixedcharges": "earnings available for fixed charges",
        "income before fixed charges": "earnings available for fixed charges",
        "fixedcharges": "fixed charges",
        "fixed charges": "fixed charges",
        "totalfixedcharges": "fixed charges",
        "total fixed charges": "fixed charges",
        "medicallossratio": "medical loss ratio",
        "medical loss ratio": "medical loss ratio",
        "mlr": "medical loss ratio",
        "minimummlr": "mlr standard",
        "minimum mlr": "mlr standard",
        "requiredmlr": "mlr standard",
        "required mlr": "mlr standard",
        "mlrstandard": "mlr standard",
        "mlr standard": "mlr standard",
        "minimum medical loss ratio": "mlr standard",
        "minimummedicallossratio": "mlr standard",
        "medical loss ratio standard": "mlr standard",
        "medicallossratiostandard": "mlr standard",
        "mlrnumerator": "mlr numerator",
        "mlr numerator": "mlr numerator",
        "claimsandqualityimprovementexpenses": "mlr numerator",
        "claims and quality improvement expenses": "mlr numerator",
        "claimsandqualityimprovementactivities": "mlr numerator",
        "claims and quality improvement activities": "mlr numerator",
        "clinicalservicesandqualityimprovement": "mlr numerator",
        "clinical services and quality improvement": "mlr numerator",
        "mlrdenominator": "mlr denominator",
        "mlr denominator": "mlr denominator",
        "adjustedpremiumrevenue": "adjusted premium revenue",
        "adjusted premium revenue": "adjusted premium revenue",
        "premiumrevenueaftertaxes": "adjusted premium revenue",
        "premium revenue after taxes": "adjusted premium revenue",
        "rebatebasis": "adjusted premium revenue",
        "rebate basis": "adjusted premium revenue",
        "premiumrevenue": "premium revenue",
        "premium revenue": "premium revenue",
        "earnedpremium": "premium revenue",
        "earned premium": "premium revenue",
        "earnedpremiums": "premium revenue",
        "earned premiums": "premium revenue",
        "premiumsearned": "premium revenue",
        "premiums earned": "premium revenue",
        "medicalclaims": "medical claims",
        "medical claims": "medical claims",
        "incurredclaims": "medical claims",
        "incurred claims": "medical claims",
        "medicalcosts": "medical claims",
        "medical costs": "medical claims",
        "medicalexpenses": "medical claims",
        "medical expenses": "medical claims",
        "healthcarecosts": "medical claims",
        "health care costs": "medical claims",
        "qualityimprovementexpenses": "quality improvement expenses",
        "quality improvement expenses": "quality improvement expenses",
        "qualityimprovementactivities": "quality improvement expenses",
        "quality improvement activities": "quality improvement expenses",
        "healthcarequalityimprovement": "quality improvement expenses",
        "health care quality improvement": "quality improvement expenses",
        "mlrrebate": "mlr rebate",
        "mlr rebate": "mlr rebate",
        "medicallossratiorebate": "mlr rebate",
        "medical loss ratio rebate": "mlr rebate",
        "rebateamount": "mlr rebate",
        "rebate amount": "mlr rebate",
        "otherexpenseincome": "other expense",
        "other expense income": "other expense",
        "operatingincomeloss": "operating income",
        "operating income loss": "operating income",
        "depreciationandamortizationexcludingrestructuringactivities": "depreciation and amortization",
        "depreciation and amortization excluding restructuring activities": "depreciation and amortization",
        "impairmentlosses": "addback",
        "impairment losses": "addback",
        "equityawardcompensationexpense": "addback",
        "equity award compensation expense": "addback",
        "stockbasedcompensation": "addback",
        "stock based compensation": "addback",
        "unrealizedlossesgainsoncommodityhedges": "addback",
        "unrealized losses gains on commodity hedges": "addback",
        "restructuringactivities": "addback",
        "restructuring activities": "addback",
        "dealcosts": "addback",
        "deal costs": "addback",
        "certainnonordinarycourselegalandregulatorymatters": "addback",
        "certain non ordinary course legal and regulatory matters": "addback",
        "researchanddevelopmentexpense": "research and development expense",
        "research and development expense": "research and development expense",
        "research and development": "research and development expense",
        "r d expense": "research and development expense",
        "payments to acquire property plant and equipment": "capital expenditures",
        "paymentstoacquirepropertyplantandequipment": "capital expenditures",
        "payments to acquire property and equipment": "capital expenditures",
        "purchases of property plant and equipment": "capital expenditures",
        "purchasesofpropertyplantandequipment": "capital expenditures",
        "purchases of property, plant and equipment": "capital expenditures",
        "purchases of property plant and equipment pp e": "capital expenditures",
        "purchasesofpropertyplantandequipmentppe": "capital expenditures",
        "capital expenditures": "capital expenditures",
        "propertyplantandequipmentnet": "property plant and equipment net",
        "property plant and equipment  net": "property plant and equipment net",
        "property plant and equipment net": "property plant and equipment net",
        "property, plant and equipment, net": "property plant and equipment net",
        "property, plant and equipment net": "property plant and equipment net",
        "property and equipment net": "property plant and equipment net",
        "property and equipment  net": "property plant and equipment net",
        "net property plant and equipment": "property plant and equipment net",
        "net property and equipment": "property plant and equipment net",
        "net ppe": "property plant and equipment net",
        "net ppne": "property plant and equipment net",
        "ppne": "property plant and equipment net",
        "number of stores": "store count",
        "numberofstores": "store count",
        "store count": "store count",
        "storecount": "store count",
        "stores": "store count",
        "assets": "assets",
        "totalassets": "assets",
        "total assets": "assets",
        "stockholdersequity": "shareholders equity",
        "stockholders equity": "shareholders equity",
        "stockholders' equity": "shareholders equity",
        "total stockholders equity": "shareholders equity",
        "total stockholders' equity": "shareholders equity",
        "shareholdersequity": "shareholders equity",
        "shareholders equity": "shareholders equity",
        "shareholders' equity": "shareholders equity",
        "total shareholders equity": "shareholders equity",
        "total shareholders' equity": "shareholders equity",
        "total equity": "shareholders equity",
        "liabilitiescurrent": "current liabilities",
        "liabilities current": "current liabilities",
        "current liabilities": "current liabilities",
        "total current liabilities": "current liabilities",
        "liabilities": "liabilities",
        "total liabilities": "liabilities",
        "free cash flow": "free cash flow",
        "marketcapitalization": "market cap",
        "market cap": "market cap",
        "equityvalue": "equity value",
        "enterprisevalue": "enterprise value",
        "transactionvalue": "transaction value",
        "dealvalue": "deal value",
        "purchaseprice": "purchase price",
        "considerationpaid": "consideration paid",
        "purchaseconsideration": "purchase consideration",
        "fairvalueofconsideration": "fair value of consideration",
        "intangibleassets": "intangible assets",
        "add back": "addback",
        "addback": "addback",
        "add backs": "addback",
        "addbacks": "addback",
    }
    compact = "".join(ch for ch in text if ch.isalnum())
    return aliases.get(compact, aliases.get(text, text))


def _looks_like_structured_companyfacts(text: str) -> bool:
    normalized = str(text or "")
    return (
        "facts=" in normalized
        or "SEC companyfacts official" in normalized
        or "entityName=" in normalized
        or ("metric=" in normalized and ("value=" in normalized or "val=" in normalized))
    )


def _looks_like_discovery_or_search_page(item: EvidenceItem) -> bool:
    uri = str(item.uri or "").lower()
    title = str(item.title or "").lower()
    if "sec.gov/edgar/search" in uri or "sec.gov/search-filings" in uri:
        return True
    if "company-information.service.gov.uk" in uri or "investor.gov" in uri:
        return True
    return any(marker in title for marker in ("search", "faq", "budget & performance", "investor.gov"))


def _looks_like_non_material_amount(raw: str) -> bool:
    stripped = str(raw or "").strip().replace(",", "")
    if not stripped:
        return True
    try:
        value = Decimal(stripped.lstrip("$€£¥"))
    except InvalidOperation:
        return True
    return abs(value) < Decimal("1")


def _looks_like_standalone_year(raw: str, unit: str, prefix: str) -> bool:
    if unit or prefix:
        return False
    text = str(raw or "").replace(",", "").strip()
    if not re.fullmatch(r"(?:19|20)\d{2}", text):
        return False
    return True


def _looks_like_period_day(text: str, start: int, end: int, *, raw_number: str, unit: str, prefix: str) -> bool:
    if unit or prefix:
        return False
    value = _decimal_or_none(str(raw_number).replace(",", ""))
    if value is None or value != value.to_integral_value() or value < Decimal(1) or value > Decimal(31):
        return False
    source = str(text or "")
    window = source[max(0, start - 24) : min(len(source), end + 36)].lower()
    return bool(
        re.search(
            r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
            r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b",
            window,
        )
    )


def _is_parenthesized_amount(text: str, start: int, end: int) -> bool:
    source = str(text or "")
    left = source[max(0, start - 3) : start]
    right = source[end : min(len(source), end + 3)]
    return "(" in left and ")" in right


def _looks_like_filing_item_or_identifier(
    text: str,
    start: int,
    end: int,
    *,
    raw_number: str,
    unit: str,
    prefix: str,
) -> bool:
    if unit or prefix:
        return False
    value = _decimal_or_none(str(raw_number).replace(",", ""))
    if value is None:
        return False
    before = text[max(0, start - 36) : start].lower()
    after = text[end : min(len(text), end + 36)].lower()
    window = f"{before}{text[start:end]}{after}"
    if re.search(r"\bitem\s*$", before):
        return True
    if re.search(r"\bitem\s+\d{1,2}(?:\.\d{1,2})?\b", window):
        return True
    if re.search(r"\b(?:form\s*)?8-k\b", window) and re.search(r"\b\d{1,2}\.\d{1,2}\b", window):
        return True
    if "sec" in window and "item" in window and re.search(r"\b\d{1,2}\.\d{1,2}\b", window):
        return True
    if value == value.to_integral_value() and Decimal(0) < value < Decimal(100):
        if re.search(r"\b(?:item|section|article|note|exhibit)\b", window):
            return True
    if re.search(r"\b(?:ex|exhibit)[-\s]*\d{1,3}(?:\.\d{1,3})?\b", window):
        return True
    if re.search(r"\bd\d{4,}(?:d|dex)?\b", window):
        return True
    return False


def _looks_like_natural_context_noise(
    context: str,
    *,
    raw_number: str,
    unit: str,
    prefix: str,
    metric: str,
    amount_offset: int,
    amount_end: int,
    document_scale_context: str = "",
) -> bool:
    value = _decimal_or_none(str(raw_number).replace(",", ""))
    if value is None:
        return True
    text = str(context or "").lower()
    offset = max(0, min(len(text), int(amount_offset)))
    end = max(offset, min(len(text), int(amount_end)))
    local = text[max(0, offset - 70) : min(len(text), end + 70)]
    before_near = text[max(0, offset - 40) : offset]
    after = text[end : min(len(text), end + 80)]
    if _looks_like_sec_metadata_context(local):
        return True
    next_amount = AMOUNT_PATTERN.search(after)
    own_after = after[: next_amount.start()] if next_amount is not None else after
    net_cash_local = f"{before_near} {own_after}"
    if metric in {"market cap", "market capitalization", "equity value", "enterprise value"}:
        if re.search(r"\b(?:eps|earnings per share|per share|book value per share|net cash per share)\b", local):
            return True
    if metric in {"ebitda", "adjusted ebitda", "addback"}:
        direct_adjusted_ebitda_amount = metric == "adjusted ebitda" and re.search(
            r"\badjusted\s+ebitda\b[\s$€£¥,.\d()/-]*$",
            before_near,
        )
        if re.search(
            r"\b(?:dividend|dividends|dividend per share|dividend yield|earnings per share|eps|"
            r"book value per share|net cash per share|price target|share price|per share)\b",
            local,
        ) and not direct_adjusted_ebitda_amount:
            return True
        if re.search(r"\b(?:ebitda|adjusted ebitda)\s+margin\b", local) and re.search(
            r"\b(?:dividend|yield|per share|price target|share price)\b",
            local,
        ):
            return True
    if metric in {"debt", "long term debt", "short term debt"}:
        if value < 0:
            return True
        if re.search(r"\bnet cash\b", net_cash_local) and not re.search(r"\bin\s+debt\b", own_after):
            return True
    if (
        metric in {"cash and cash equivalents", "cash and equivalents"}
        and re.search(r"\bnet cash\b", net_cash_local)
        and not re.search(r"\bin\s+cash\b", own_after)
    ):
        return True
    if not unit and not prefix and re.search(r"(?:%|\bpp\b(?!\s*&|\s*and\s*e)|percentage\s+points?)", local):
        return True
    if unit or prefix:
        return False
    if _context_scale_multiplier(context, raw_unit=unit) > Decimal(1):
        return False
    if document_scale_context and _context_scale_multiplier(document_scale_context, raw_unit=unit) > Decimal(1):
        return False
    if abs(value) < Decimal("1000") and metric not in {"margin", "rate", "yield"}:
        return True
    return False


def _looks_like_sec_metadata_context(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        marker in normalized
        for marker in (
            "former conformed name",
            "date of name change",
            "http://fasb.org/us-gaap",
            "http://xbrl.sec.gov",
            "dei:",
            "document fiscal year focus",
            "central index key",
            "standard industrial classification",
            "irs number",
            "accession number",
        )
    )


def _metric_from_context(context: str, *, amount_offset: int, amount_end: int) -> str | None:
    text = " ".join(str(context or "").lower().replace("_", " ").split())
    offset = max(0, int(amount_offset))
    end = max(offset, min(len(text), int(amount_end)))
    before = text[max(0, offset - 80) : offset]
    after = text[end : min(len(text), end + 80)]
    next_amount = AMOUNT_PATTERN.search(after)
    own_after = after[: next_amount.start()] if next_amount is not None else after
    before_near = before[-70:]
    if re.search(r"\b(?:general\s+corporate\s+expenses|corporate\s+expenses)\b[^.]{0,80}$", before_near):
        return "deduction"
    if before_near.rfind("adjusted ebitda") > before_near.rfind("license income"):
        return "adjusted ebitda"
    if re.search(r"\badjusted\s+ebitda\b(?:\s+(?:was|were|of|:))?\s*$", before_near):
        return "adjusted ebitda"
    if re.search(r"\badjusted\s+ebitda\b[\s$€£¥,.\d()/-]*$", before_near):
        return "adjusted ebitda"
    if re.search(r"\b(?:depreciation\s+and\s+amortization|d&a|amortization)\b[^.]{0,80}$", before_near):
        return "depreciation and amortization"
    if re.search(r"\b(?:divestiture-related\s+license\s+income|license\s+income|gain\s+on\s+sale|gains?)\b[^.]{0,80}$", before_near):
        return "deduction"
    if re.search(r"\b(?:property,\s*plant\s+and\s+equipment|property\s+plant\s+and\s+equipment|property\s+and\s+equipment|net\s+pp&e|net\s+ppe|ppne)\b[^.]{0,80}$", before_near):
        return "property plant and equipment net"
    if re.search(r"\b(?:add-back|add back|addback|add-backs|add backs|restructuring)\b[^.]{0,60}$", before_near):
        return "addback"
    if re.search(r"\b(?:less|deduction|deducted)\b[^.]{0,60}$", before_near):
        return "deduction"
    if re.search(r"\b(?:right to receive|converted into|acquire|acquisition|merger)\b", before) and re.search(
        r"\b(?:per\s+[a-z0-9&.' -]{0,40}share|in\s+cash)\b",
        own_after,
    ):
        return "purchase price"
    if re.search(r"\bin\s+debt\b", own_after) or re.search(r"\btotal\s+debt\s*$", before):
        return "debt"
    if re.search(r"\bin\s+cash\b", own_after) or re.search(r"\bcash\s*(?:&|and)\s*cash\s+equivalents\s*$", before):
        return "cash and cash equivalents"
    best: tuple[int, str] | None = None
    for metric, markers in NATURAL_METRIC_MARKERS:
        for marker in markers:
            for match in re.finditer(re.escape(marker), text):
                if match.start() <= offset:
                    distance = offset - match.start()
                else:
                    trailing_distance = match.start() - offset
                    distance = 50 + trailing_distance if trailing_distance <= 80 else 10_000 + trailing_distance
                if best is None or distance < best[0]:
                    best = (distance, metric)
    if best is not None and best[1] == "ebitda" and "adjusted ebitda" in before_near:
        return "adjusted ebitda"
    return best[1] if best is not None else None


def _scaled_amount(raw_number: str, raw_unit: str, prefix: str) -> Decimal | None:
    value = _decimal_or_none(str(raw_number).replace(",", ""))
    if value is None:
        return None
    unit = str(raw_unit or "").strip().lower()
    if unit in {"thousand"}:
        value *= Decimal(1_000)
    elif unit in {"million", "mn", "m"}:
        value *= Decimal(1_000_000)
    elif unit in {"billion", "bn", "b"}:
        value *= Decimal(1_000_000_000)
    elif unit == "trillion":
        value *= Decimal(1_000_000_000_000)
    return value


def _context_scale_multiplier(context: str, *, raw_unit: str) -> Decimal:
    if raw_unit:
        return Decimal(1)
    text = str(context or "").lower()
    if re.search(r"\(\s*millions\s*\)|\(\s*in\s+millions\s*\)|\bin\s+millions\b|\bamounts?\s+in\s+millions\b", text):
        return Decimal(1_000_000)
    if re.search(r"\(\s*billions\s*\)|\(\s*in\s+billions\s*\)|\bin\s+billions\b|\bamounts?\s+in\s+billions\b", text):
        return Decimal(1_000_000_000)
    if re.search(r"\(\s*thousands\s*\)|\(\s*in\s+thousands\s*\)|\bin\s+thousands\b|\bamounts?\s+in\s+thousands\b", text):
        return Decimal(1_000)
    return Decimal(1)


def _nearby_scale_scope_multiplier(text: str, offset: int, *, raw_unit: str) -> Decimal:
    if raw_unit:
        return Decimal(1)
    source = str(text or "")
    if not source:
        return Decimal(1)
    cursor = max(0, min(len(source), int(offset or 0)))
    start = max(0, cursor - 1200)
    end = min(len(source), cursor + 160)
    scope = source[start:end]
    matches = list(SCALE_SCOPE_PATTERN.finditer(scope))
    if not matches:
        return Decimal(1)
    before = [match for match in matches if start + match.end() <= cursor + 24]
    match = before[-1] if before else min(matches, key=lambda item: abs((start + item.start()) - cursor))
    label = next(
        (
            match.group(name)
            for name in ("paren", "named", "plain")
            if match.group(name)
        ),
        "",
    )
    return _scale_multiplier_from_label(label)


def _scale_multiplier_from_label(label: str) -> Decimal:
    text = str(label or "").strip().lower()
    if text in {"thousand", "thousands"}:
        return Decimal(1_000)
    if text in {"million", "millions"}:
        return Decimal(1_000_000)
    if text in {"billion", "billions"}:
        return Decimal(1_000_000_000)
    return Decimal(1)


def _scale_scope_metadata(multiplier: Decimal) -> JsonObject:
    if multiplier == Decimal(1_000):
        scale = "thousands"
    elif multiplier == Decimal(1_000_000):
        scale = "millions"
    elif multiplier == Decimal(1_000_000_000):
        scale = "billions"
    else:
        return {}
    return {
        "source_scale": scale,
        "source_scale_multiplier": _decimal_string(multiplier),
        "source_scale_applied": True,
    }


def _natural_unit(prefix: str, unit: str) -> str | None:
    token = str(unit or "").strip().lower()
    token = " ".join(token.split())
    if token in {"%", "percentage point", "percentage points", "bps", "basis point", "basis points"}:
        return "percent" if token in {"%", "percentage point", "percentage points"} else "bps"
    if prefix == "$" or token in {"usd", "dollars", "million", "billion", "trillion", "mn", "bn", "m", "b"}:
        return "USD"
    if prefix == "€":
        return "EUR"
    if prefix == "£":
        return "GBP"
    if prefix == "¥":
        return "CNY"
    if token == "shares":
        return "shares"
    return None


def _context_indicates_per_share(context: str, *, amount_offset: int, amount_end: int) -> bool:
    text = str(context or "").lower()
    offset = max(0, min(len(text), int(amount_offset)))
    end = max(offset, min(len(text), int(amount_end)))
    before_near = text[max(0, offset - 80) : offset]
    if re.search(r"\b(?:eps|earnings per share|per share|book value per share|net cash per share)\b", before_near):
        return True
    after = text[end : end + 100]
    after_share_match = re.search(r"\bper\s+share\b|\bper\s+[a-z0-9&.' -]{1,60}\s+share\b", after)
    if after_share_match:
        after_before_share = after[: after_share_match.start()]
        if re.search(r"[$€£¥]\s*\d", after_before_share):
            return False
        return True
    before = text[max(0, offset - 160) : offset]
    if re.search(r"[$€£¥]\s*\d", before):
        return False
    return (
        ("each share" in before or "common share" in before)
        and ("right to receive" in before or "converted into" in before)
    )


def _nearby_year(context: str) -> int | None:
    years = [int(match) for match in re.findall(r"\b((?:19|20)\d{2})\b", str(context or ""))]
    return max(years) if years else None


def _natural_entity(*, item: EvidenceItem, text: str) -> str | None:
    title = str(item.title or "").strip()
    if title:
        return title[:160]
    match = re.search(r"\b([A-Z][A-Za-z&.' -]{2,80}(?:Inc\.|Corporation|Corp\.|Company|Co\.|Ltd\.|plc))\b", text)
    return match.group(1).strip() if match else None


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _is_decimal(value: str) -> bool:
    return _decimal_amount_from_structured_value(value) is not None


def _int_or_none(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _decimal_string(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
