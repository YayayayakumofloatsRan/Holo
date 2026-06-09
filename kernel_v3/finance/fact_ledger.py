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
    "tax",
    "income tax expense",
    "operating income",
    "diluted earnings per share",
    "basic earnings per share",
    "eps",
    "assets",
    "liabilities",
    "shareholders equity",
}

KEY_PATTERN = re.compile(
    r"(?P<key>entityName|ticker|cik|taxonomy|concept|metric|label|unit|period|fy|fp|form|filed|end|start|frame|accn|value|val|scale)=",
    re.IGNORECASE,
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
    return result


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
        "earnings per share diluted": "diluted earnings per share",
        "earnings per share basic": "basic earnings per share",
        "inventory net": "inventory",
        "inventory": "inventory",
        "merchandise inventories": "inventory",
        "costofrevenue": "cost of revenue",
        "cost of goods sold": "cogs",
    }
    compact = "".join(ch for ch in text if ch.isalnum())
    return aliases.get(compact, aliases.get(text, text))


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
