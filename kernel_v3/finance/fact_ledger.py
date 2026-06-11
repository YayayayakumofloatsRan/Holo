from __future__ import annotations

import hashlib
import re
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
    "sales and other operating revenues",
    "operating revenues",
    "net income",
    "net income loss",
    "cash and equivalents",
    "cash and cash equivalents",
    "short-term investments",
    "short term investments",
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
    "other expense",
    "other income",
    "general corporate expenses",
    "corporate expenses",
    "operating income",
    "income from continuing operations",
    "pretax income",
    "diluted earnings per share",
    "basic earnings per share",
    "eps",
    "operating cash flow",
    "cash flow from operations",
    "net cash provided by operating activities",
    "free cash flow",
    "capital expenditures",
    "assets",
    "liabilities",
    "shareholders equity",
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
}

KEY_PATTERN = re.compile(
    r"(?P<key>entityName|ticker|cik|taxonomy|concept|metric|label|unit|period|fy|fp|form|filed|end|start|frame|accn|value|val|scale)=",
    re.IGNORECASE,
)
AMOUNT_PATTERN = re.compile(
    r"(?P<prefix>[$€£¥])?\s*(?P<number>-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*"
    r"(?P<unit>million|billion|trillion|thousand|mn|bn|m|b|usd|dollars|shares)?",
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
    ("revenue", ("revenue", "revenues", "net sales", "net revenue", "net revenues")),
    (
        "operating cash flow",
        (
            "operating cash flow",
            "cash flow from operations",
            "net cash provided by operating activities",
            "cash provided by operating activities",
        ),
    ),
    ("free cash flow", ("free cash flow",)),
    ("capital expenditures", ("capital expenditures", "capital expenditure", "capex", "property and equipment")),
    ("income from continuing operations", ("income from continuing operations", "income from continuing ops")),
    ("net income", ("net income", "net loss", "net earnings")),
    ("operating income", ("operating income", "operating loss")),
    ("addback", ("other expense",)),
    ("deduction", ("other income",)),
    ("deduction", ("general corporate expenses", "corporate expenses")),
    ("interest expense", ("interest expense",)),
    ("tax", ("income taxes", "income tax", "provision for", "benefit from income taxes")),
    ("depreciation and amortization", ("depreciation and amortization", "d&a", "amortization")),
    ("deduction", ("divestiture-related license income", "license income", "gain on sale", "gains")),
    ("cash and cash equivalents", ("cash and cash equivalents", "cash equivalents", "cash and equivalents", "total cash")),
    ("debt", ("total debt", "debt", "borrowings", "notes payable")),
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
    global_text, metric_segments = _metric_segments(text)
    global_values = _key_values(global_text)
    result: list[FinanceFact] = []
    for segment in metric_segments:
        values = {**global_values, **_key_values(segment)}
        value = values.get("value") or values.get("val")
        metric = _canonical_metric(values.get("metric") or values.get("concept") or values.get("label") or "")
        if value is None or not metric or not _is_decimal(value):
            continue
        fact = _fact_from_values(values, item=item, citation=citation, metric=metric, value=value)
        result.append(fact)
    result.extend(_natural_facts_from_text(text, item=item, citation=citation))
    return result


def _natural_facts_from_text(text: str, *, item: EvidenceItem, citation: CitationItem | None) -> list[FinanceFact]:
    normalized_text = " ".join(str(text or "").split())
    if not normalized_text or _looks_like_structured_companyfacts(normalized_text) or _looks_like_discovery_or_search_page(item):
        return []
    document_scale_context = normalized_text[:1000]
    facts: list[FinanceFact] = []
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
        value *= scale_multiplier
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
                    "per_share": _context_indicates_per_share(
                        context,
                        amount_offset=match.start() - start,
                        amount_end=match.end() - start,
                    ),
                },
            )
        )
    return facts


def _metric_segments(text: str) -> tuple[str, list[str]]:
    if "facts=" in text:
        before, after = text.split("facts=", 1)
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
    fiscal_year = _int_or_none(values.get("fy"))
    unit = values.get("unit")
    fact_id = "finfact-" + _short_hash(
        item.evidence_id,
        metric,
        str(fiscal_year or ""),
        str(values.get("period") or ""),
        str(values.get("concept") or ""),
        str(value),
    )
    citation_ref = citation.citation_id if citation is not None else None
    metadata: JsonObject = {
        "concept": values.get("concept"),
        "label": values.get("label"),
        "cik": values.get("cik"),
        "taxonomy": values.get("taxonomy"),
        "form": values.get("form"),
        "filed": values.get("filed"),
        "end": values.get("end"),
        "start": values.get("start"),
        "frame": values.get("frame"),
        "accn": values.get("accn"),
        "supported_metric": metric in SUPPORTED_FINANCE_METRICS,
        "source_uri": item.uri,
        "source_title": item.title,
    }
    metadata = {key: item for key, item in metadata.items() if item not in (None, "")}
    return FinanceFact(
        fact_id=fact_id,
        entity=values.get("entityname"),
        ticker=values.get("ticker"),
        period=values.get("period"),
        fiscal_year=fiscal_year,
        metric=metric,
        value=_decimal_string(Decimal(str(value).replace(",", ""))),
        unit=unit,
        scale=values.get("scale") or "actual",
        source_ref=citation_ref or item.evidence_id,
        evidence_ref=item.evidence_id,
        citation_ref=citation_ref,
        metadata=metadata,
    )


def _normalize_key(value: str) -> str:
    return str(value or "").strip().lower()


def _canonical_metric(value: str) -> str:
    text = " ".join(str(value or "").replace("_", " ").replace("-", " ").lower().split())
    aliases = {
        "revenues": "revenue",
        "revenuefromcontractwithcustomerexcludingassessedtax": "revenue",
        "revenue from contract with customer excluding assessed tax": "revenue",
        "sales revenue net": "net sales",
        "net sales": "net sales",
        "profit loss": "net income",
        "netincomeloss": "net income",
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
        "costofrevenue": "cost of revenue",
        "cost of goods sold": "cogs",
        "netcashprovidedbyusedinoperatingactivities": "operating cash flow",
        "net cash provided by used in operating activities": "operating cash flow",
        "net cash provided by operating activities": "operating cash flow",
        "netcashprovidedbyoperatingactivities": "operating cash flow",
        "net cash provided by operating activities continuing operations": "operating cash flow",
        "net cash provided by used in operating activities continuing operations": "operating cash flow",
        "payments to acquire property plant and equipment": "capital expenditures",
        "paymentstoacquirepropertyplantandequipment": "capital expenditures",
        "payments to acquire property and equipment": "capital expenditures",
        "capital expenditures": "capital expenditures",
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
    return "facts=" in text or "SEC companyfacts official" in text or "entityName=" in text


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
    if not unit and not prefix and re.search(r"(?:%|\bpp\b|percentage\s+points?)", local):
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
    if re.search(r"\(\s*in\s+millions\s*\)|\bin\s+millions\b|\bamounts?\s+in\s+millions\b", text):
        return Decimal(1_000_000)
    if re.search(r"\(\s*in\s+billions\s*\)|\bin\s+billions\b|\bamounts?\s+in\s+billions\b", text):
        return Decimal(1_000_000_000)
    if re.search(r"\(\s*in\s+thousands\s*\)|\bin\s+thousands\b|\bamounts?\s+in\s+thousands\b", text):
        return Decimal(1_000)
    return Decimal(1)


def _natural_unit(prefix: str, unit: str) -> str | None:
    token = str(unit or "").strip().lower()
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
    try:
        Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return False
    return True


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
