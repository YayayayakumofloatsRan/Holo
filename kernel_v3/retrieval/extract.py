from __future__ import annotations

import csv
import html
import io
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from kernel_v3.contracts import JsonObject
from kernel_v3.research.profile_policy import (
    QUERY_FACET_ALIASES,
    profile_extraction_aliases,
    query_facets,
    resolve_goal_research_profile,
)
from kernel_v3.retrieval.contracts import ExtractedSpan, FetchedDocument, SearchGoal
from kernel_v3.retrieval.finance_metrics import (
    finance_metric_intent,
    finance_metric_intent_diagnostics,
    finance_metric_intent_score,
)

READABLE_TEXT_LIMIT = 200_000
SEC_FILING_TEXT_LIMIT = 4_000_000
SEC_COMPLETE_SUBMISSION_TEXT_LIMIT = SEC_FILING_TEXT_LIMIT
SPAN_BEFORE_CHARS = 120
SPAN_AFTER_CHARS = 520
HTML_MIME_MARKERS = ("html", "xhtml")
PDF_MIME_MARKERS = ("pdf", "application/pdf")
JSON_MIME_MARKERS = ("json", "application/json")
CSV_MIME_MARKERS = ("csv", "comma-separated-values")
STRUCTURED_LINE_LIMIT = 4_000
STRUCTURED_VALUE_LIMIT = 240
SCHOLARLY_RECORD_LIMIT = 80
SCHOLARLY_ABSTRACT_LIMIT = 700
SCHOLARLY_METADATA_SOURCE_KINDS = {
    "scholarly_preprint",
    "scholarly_index_metadata",
    "scholarly_publisher_metadata",
}
GENERIC_QUERY_TERMS = {
    "academic",
    "analysis",
    "article",
    "case",
    "complete",
    "comprehensive",
    "deep",
    "detailed",
    "evidence",
    "frontier",
    "frontiers",
    "information",
    "investigate",
    "journal",
    "latest",
    "literature",
    "open",
    "paper",
    "papers",
    "preprint",
    "problem",
    "problems",
    "recent",
    "report",
    "research",
    "review",
    "scholarly",
    "state",
    "study",
    "survey",
    "thorough",
}
STRUCTURED_TEXT_MODES = {
    "sec_companyfacts_readable_text",
    "arxiv_atom_readable_text",
    "openalex_readable_text",
    "crossref_readable_text",
    "semantic_scholar_readable_text",
    "scholarly_json_readable_text",
}
SEC_COMPANYFACTS_CONCEPTS = (
    ("Revenues", "revenue"),
    ("RevenuesNetOfInterestExpense", "net revenues"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "revenue"),
    ("RevenueFromContractWithCustomerIncludingAssessedTax", "revenue including assessed tax"),
    ("SalesAndOtherOperatingRevenue", "sales and other operating revenues"),
    ("SalesRevenueServicesNet", "service revenue"),
    ("SalesRevenueGoodsNet", "goods revenue"),
    ("SalesRevenueNet", "net sales"),
    ("OperatingRevenues", "operating revenues"),
    ("RegulatedAndUnregulatedOperatingRevenue", "operating revenues"),
    ("RevenuesFromExternalCustomers", "segment revenue from external customers"),
    ("SegmentReportingInformationRevenue", "segment revenue"),
    ("SegmentReportingInformationRevenueFromExternalCustomers", "segment revenue from external customers"),
    ("InvestmentAdvisoryAdministrationFees", "investment advisory and administration fees"),
    ("InvestmentBankingRevenue", "investment banking revenue"),
    ("InterestIncomeExpenseNet", "net interest income"),
    ("NetInterestIncome", "net interest income"),
    ("InterestAndDividendIncomeOperating", "interest and dividend income"),
    ("InterestIncomeOperating", "interest income"),
    ("InterestExpenseOperating", "interest expense"),
    ("InterestExpense", "interest expense"),
    ("InterestExpenseNonoperating", "interest expense"),
    ("NoninterestIncome", "noninterest income"),
    ("ProvisionForLoanLeaseAndOtherLosses", "provision for credit losses"),
    ("NetIncomeLoss", "net income"),
    ("NetIncomeLossAvailableToCommonStockholdersBasic", "net income available to common shareholders"),
    ("NetIncomeLossAttributableToParent", "net income attributable to parent"),
    ("ProfitLoss", "net income"),
    ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", "pretax income"),
    ("IncomeLossFromContinuingOperationsBeforeIncomeTaxes", "pretax income"),
    ("IncomeTaxExpenseBenefit", "income tax expense"),
    ("OperatingIncomeLoss", "operating income"),
    ("GrossProfit", "gross profit"),
    ("Depreciation", "depreciation and amortization"),
    ("DepreciationDepletionAndAmortization", "depreciation and amortization"),
    ("DepreciationDepletionAndAmortizationPropertyPlantAndEquipment", "depreciation and amortization"),
    ("AmortizationOfIntangibleAssets", "depreciation and amortization"),
    ("InventoryNet", "inventory"),
    ("InventoryFinishedGoodsNetOfReserves", "inventory"),
    ("InventoryRawMaterialsAndSupplies", "inventory"),
    ("MerchandiseInventories", "inventory"),
    ("CostOfRevenue", "cost of revenue"),
    ("CostOfGoodsAndServicesSold", "cost of goods sold"),
    ("CostOfGoodsSold", "cost of goods sold"),
    ("CostOfSales", "cost of sales"),
    ("CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization", "cost of goods sold"),
    ("NetCashProvidedByUsedInOperatingActivities", "operating cash flow"),
    ("PaymentsToAcquirePropertyPlantAndEquipment", "capital expenditures"),
    ("PaymentsToAcquireProductiveAssets", "capital expenditures"),
    ("PropertyPlantAndEquipmentAdditions", "capital expenditures"),
    ("CapitalExpendituresIncurredButNotYetPaid", "capital expenditures"),
    ("CashAndCashEquivalentsAtCarryingValue", "cash and cash equivalents"),
    ("Assets", "assets"),
    ("Liabilities", "liabilities"),
    ("StockholdersEquity", "shareholders equity"),
    ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", "shareholders equity including noncontrolling interest"),
    ("CommonStocksIncludingAdditionalPaidInCapital", "common stock and additional paid-in capital"),
    ("LongTermDebt", "long-term debt"),
    ("LongTermDebtCurrent", "current long-term debt"),
    ("LongTermDebtNoncurrent", "long-term debt"),
    ("DebtCurrent", "short-term debt"),
    ("DebtLongtermAndShorttermCombinedAmount", "debt"),
    ("LongTermDebtAndFinanceLeaseObligations", "long-term debt and finance lease obligations"),
    ("LongTermDebtAndFinanceLeaseObligationsCurrent", "current long-term debt and finance lease obligations"),
    ("ShortTermBorrowings", "short-term borrowings"),
    ("Deposits", "deposits"),
    ("FederalFundsPurchasedAndSecuritiesSoldUnderAgreementsToRepurchase", "federal funds purchased and securities sold under agreements to repurchase"),
    ("EarningsPerShareDiluted", "diluted earnings per share"),
    ("EarningsPerShareBasic", "basic earnings per share"),
)
SEC_COMPANYFACTS_DYNAMIC_KEYWORDS = (
    "revenue",
    "revenues",
    "sales",
    "net interest",
    "interest income",
    "interest expense",
    "noninterest",
    "segment",
    "family of apps",
    "reality labs",
    "cloud",
    "artificial intelligence",
    "infrastructure",
    "investment",
    "income",
    "loss",
    "inventory",
    "inventories",
    "cost of revenue",
    "cost of sales",
    "cost of goods",
    "cash flow",
    "capital expenditure",
    "capital expenditures",
    "capex",
    "property plant",
    "payments to acquire",
    "cash",
    "assets",
    "liabilities",
    "equity",
    "debt",
    "tax",
    "income tax",
    "depreciation",
    "amortization",
    "earnings per share",
    "eps",
)
SEC_COMPANYFACTS_SUMMARY_YEARS = 4
SEC_COMPANYFACTS_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
HTML_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
HTML_SKIP_TAGS = {
    "canvas",
    "footer",
    "head",
    "header",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
}
MARKET_SCRIPT_METRIC_LABELS = {
    "marketCap": "Market Cap",
    "marketCapitalization": "Market Cap",
    "enterpriseValue": "Enterprise Value",
    "totalDebt": "Total Debt",
    "totalCash": "Total Cash",
    "totalCashPerShare": "Total Cash Per Share",
    "ebitda": "EBITDA",
    "trailingEbitda": "EBITDA",
}
MARKET_SCRIPT_SNIPPET_LIMIT = 24
MARKET_SCRIPT_WINDOW_CHARS = 700


def extract_spans(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    body: str,
) -> list[ExtractedSpan]:
    if not body:
        return []
    terms = _terms(goal.query, goal=goal)
    if not terms:
        return []
    text, text_mode, document_reader = readable_document_text_with_diagnostics(body, document=document, goal=goal)
    if not text:
        return []
    spans: list[ExtractedSpan] = []
    candidates = (
        _ranked_structured_line_candidates(
            text,
            terms,
            query=goal.query,
            required_terms=_topic_anchor_terms(goal.query) if text_mode in _scholarly_text_modes() else None,
        )
        if text_mode in STRUCTURED_TEXT_MODES
        else _ranked_span_candidates(text, terms)
    )
    for candidate in candidates:
        spans.append(
            ExtractedSpan(
                span_id=f"span-{document.document_id}-{len(spans) + 1}",
                goal_id=goal.goal_id,
                document_id=document.document_id,
                source_id=document.source_id,
                text=candidate["text"],
                start_offset=candidate["start_offset"],
                end_offset=candidate["end_offset"],
                score=candidate["score"],
                metadata={
                    "matched_terms": candidate["matched_terms"],
                    "text_mode": text_mode,
                    **(
                        {"finance_metric_intent": candidate["finance_metric_intent"]}
                        if candidate.get("finance_metric_intent")
                        else {}
                    ),
                    **({"document_reader": document_reader} if document_reader else {}),
                    **({"anchor_terms": candidate["anchor_terms"]} if candidate.get("anchor_terms") else {}),
                },
            )
        )
        if len(spans) >= goal.max_spans_per_document:
            break
    return spans


def readable_document_text(
    body: str,
    *,
    document: FetchedDocument,
    goal: SearchGoal | None = None,
) -> tuple[str, str]:
    text, mode, _diagnostics = readable_document_text_with_diagnostics(body, document=document, goal=goal)
    return text, mode


def readable_document_text_with_diagnostics(
    body: str,
    *,
    document: FetchedDocument,
    goal: SearchGoal | None = None,
) -> tuple[str, str, JsonObject]:
    mime_type = str(document.metadata.get("mime_type") or "").lower()
    if _looks_like_pdf(body, mime_type=mime_type):
        text, diagnostics = _extract_pdf_text_with_diagnostics(body)
        return text, str(diagnostics.get("parser_used") or "pdf_text_literals"), diagnostics
    if _looks_like_sec_companyfacts(body, document=document):
        text = _extract_sec_companyfacts_readable_text(body, goal=goal)
        if text:
            return text, "sec_companyfacts_readable_text", {}
    if _looks_like_scholarly_metadata(body, document=document, mime_type=mime_type):
        text, mode = _extract_scholarly_metadata_readable_text(body, document=document)
        if text:
            return text, mode, {}
    if _looks_like_json(body, mime_type=mime_type):
        text = _extract_json_readable_text(body)
        if text:
            return text, "json_readable_text", {}
    if _looks_like_csv(body, document=document, mime_type=mime_type):
        text = _extract_csv_readable_text(body)
        if text:
            return text, "csv_readable_text", {}
    if _looks_like_html(body, mime_type=mime_type):
        return _extract_html_readable_text(body, limit=_readable_text_limit_for_document(document)), "html_readable_text", {}
    return _normalize_span(body[: _readable_text_limit_for_document(document)]), "plain_text", {}


def _readable_text_limit_for_document(document: FetchedDocument) -> int:
    source_kind = _document_source_kind(document)
    if source_kind in {"sec_complete_submission_text", "sec_primary_filing_document", "sec_exhibit_document"}:
        return SEC_FILING_TEXT_LIMIT
    return READABLE_TEXT_LIMIT


def _ranked_span_candidates(text: str, terms: list[str]) -> list[dict]:
    lower = text.lower()
    candidates: list[dict] = []
    seen_windows: set[tuple[int, int]] = set()
    for term in terms:
        start = 0
        while True:
            index = lower.find(term, start)
            if index < 0:
                break
            window_start = max(0, index - SPAN_BEFORE_CHARS)
            window_end = min(len(text), index + len(term) + SPAN_AFTER_CHARS)
            key = _coarse_window_key(window_start, window_end)
            if key not in seen_windows:
                seen_windows.add(key)
                snippet = _normalize_span(text[window_start:window_end])
                matched = [candidate for candidate in terms if candidate in snippet.lower()]
                if snippet and matched:
                    bonus = _transaction_amount_span_bonus(snippet, terms)
                    candidates.append(
                        {
                            "start_offset": window_start,
                            "end_offset": window_end,
                            "text": snippet,
                            "matched_terms": matched,
                            "score": min(1.0, len(matched) / max(1, len(terms)) + bonus),
                        }
                    )
            start = index + max(1, len(term))
    return sorted(
        candidates,
        key=lambda item: (
            -float(item["score"]),
            -len(item["matched_terms"]),
            int(item["start_offset"]),
        ),
    )


def _transaction_amount_span_bonus(snippet: str, terms: list[str]) -> float:
    query_has_transaction_intent = any(
        term in {"acquisition", "acquire", "merger", "transaction", "deal", "consideration", "purchase"}
        for term in terms
    )
    if not query_has_transaction_intent:
        return 0.0
    text = snippet.lower()
    if not re.search(r"[$€£¥]\s*\d|\b\d+(?:\.\d+)?\s*(?:million|billion|trillion|mn|bn)\b", text):
        return 0.0
    if any(marker in text for marker in ("enterprise value", "transaction value", "deal value", "total transaction")):
        return 0.65
    if any(marker in text for marker in ("consideration", "purchase price")):
        return 0.45
    if any(marker in text for marker in ("right to receive", "per share", "in cash")):
        return 0.32
    return 0.0


def _ranked_structured_line_candidates(
    text: str,
    terms: list[str],
    *,
    query: str,
    required_terms: list[str] | None = None,
) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0]
    required_terms = required_terms or []
    required_match_count = min(2, len(required_terms)) if required_terms else 0
    candidates: list[dict] = []
    offset = 0
    for line_index, line in enumerate(lines):
        lower = line.lower()
        if line_index == 0 and _looks_like_structured_header(line):
            offset += len(line) + 1
            continue
        required_matched = [candidate for candidate in required_terms if candidate in lower]
        if required_match_count and len(required_matched) < required_match_count:
            offset += len(line) + 1
            continue
        matched = [candidate for candidate in terms if candidate in lower]
        if matched:
            metric_score = finance_metric_intent_score(line, query=query)
            structured_summary_bonus = 1.0 if _looks_like_structured_finance_summary(line) else 0.0
            snippet = _normalize_span(f"{header} {line}")
            candidates.append(
                {
                    "start_offset": offset,
                    "end_offset": offset + len(line),
                    "text": snippet,
                    "matched_terms": matched,
                    "anchor_terms": required_matched,
                    "finance_metric_intent": finance_metric_intent_diagnostics(line, query=query),
                    "structured_summary_bonus": structured_summary_bonus,
                    "score": min(
                        1.0,
                        ((len(matched) + len(required_matched)) / max(1, len(terms)))
                        + max(0.0, metric_score) / 40.0
                        + structured_summary_bonus / 10.0,
                    ),
                }
            )
        offset += len(line) + 1
    return sorted(
        candidates,
        key=lambda item: (
            -float(item["score"]),
            -float(item.get("structured_summary_bonus") or 0.0),
            -float((item.get("finance_metric_intent") or {}).get("score") or 0.0),
            -len(item["matched_terms"]),
            int(item["start_offset"]),
        ),
    )


def _coarse_window_key(start: int, end: int) -> tuple[int, int]:
    return start // 120, end // 120


def _scholarly_text_modes() -> set[str]:
    return {
        "arxiv_atom_readable_text",
        "openalex_readable_text",
        "crossref_readable_text",
        "semantic_scholar_readable_text",
        "scholarly_json_readable_text",
    }


def _looks_like_structured_header(line: str) -> bool:
    normalized = line.lower()
    return normalized.startswith("scholarly metadata records") or normalized.startswith("sec companyfacts official")


def _looks_like_structured_finance_summary(line: str) -> bool:
    normalized = line.lower()
    return "sec companyfacts annual financial summary" in normalized or (
        "period=annual" in normalized and "facts=metric=" in normalized
    )


def _topic_anchor_terms(text: str) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    normalized = text.lower().replace("-", " ").replace("_", " ")
    for raw in normalized.split():
        term = "".join(char for char in raw if char.isalnum() or "\u4e00" <= char <= "\u9fff")
        if not term or term in seen:
            continue
        if term in GENERIC_QUERY_TERMS or term in QUERY_FACET_ALIASES or len(term) < 3:
            continue
        seen.add(term)
        anchors.append(term)
    return anchors


def _looks_like_html(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in HTML_MIME_MARKERS):
        return True
    prefix = body[:2048].lower()
    return "<html" in prefix or "<!doctype html" in prefix or "<body" in prefix


def _looks_like_pdf(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in PDF_MIME_MARKERS):
        return True
    return body[:16].lstrip().startswith("%PDF")


def _looks_like_json(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in JSON_MIME_MARKERS):
        return True
    prefix = body[:1024].lstrip()
    return prefix.startswith("{") or prefix.startswith("[")


def _looks_like_csv(body: str, *, document: FetchedDocument, mime_type: str) -> bool:
    if any(marker in mime_type for marker in CSV_MIME_MARKERS):
        return True
    uri = document.uri.lower()
    if uri.endswith(".csv") or ".csv?" in uri:
        return True
    lines = [line for line in body[:4096].splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    first_columns = [item.strip() for item in lines[0].split(",")]
    second_columns = [item.strip() for item in lines[1].split(",")]
    if len(first_columns) < 2 or len(second_columns) < 2:
        return False
    return abs(len(first_columns) - len(second_columns)) <= 1


def _extract_json_readable_text(body: str) -> str:
    try:
        payload = json.loads(body[:READABLE_TEXT_LIMIT])
    except json.JSONDecodeError:
        return ""
    lines: list[str] = []
    lines.extend(_extract_market_json_fact_lines(payload))
    _flatten_json(payload, path="", lines=lines, depth=0)
    return _normalize_span(" ".join(lines)[:READABLE_TEXT_LIMIT])


def _extract_market_json_fact_lines(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    summary = data.get("summaryData")
    if not isinstance(summary, dict):
        return []
    ticker = str(data.get("symbol") or "").strip().upper()
    lines: list[str] = []
    for key, item in summary.items():
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or key or "").strip()
        metric = _market_json_metric(label, str(key))
        if metric is None:
            continue
        value = _market_json_value(item.get("value"))
        if value is None:
            continue
        prefix = f"ticker={ticker} " if ticker else ""
        lines.append(f"{prefix}metric={metric} value={value} unit=USD source=market_data_json")
    return lines


def _market_json_metric(label: str, key: str) -> str | None:
    text = f"{label} {key}".lower()
    if "market cap" in text or "marketcap" in text:
        return "market cap"
    if "enterprise value" in text or "enterprisevalue" in text:
        return "enterprise value"
    if "total debt" in text or "totaldebt" in text:
        return "debt"
    if "total cash" in text or "totalcash" in text:
        return "cash and cash equivalents"
    if "ebitda" in text:
        return "ebitda"
    return None


def _market_json_value(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.upper() in {"N/A", "NA", "--"}:
        return None
    text = text.replace("$", "").replace(",", "").strip()
    multiplier = 1
    suffix = text[-1:].upper()
    if suffix in {"K", "M", "B", "T"}:
        text = text[:-1].strip()
        multiplier = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000, "T": 1_000_000_000_000}[suffix]
    try:
        number = float(text) * multiplier
    except ValueError:
        return None
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _looks_like_scholarly_metadata(body: str, *, document: FetchedDocument, mime_type: str) -> bool:
    source_kind = _document_source_kind(document)
    if source_kind in SCHOLARLY_METADATA_SOURCE_KINDS:
        return True
    uri = document.uri.lower()
    if any(
        marker in uri
        for marker in (
            "export.arxiv.org/api/query",
            "api.openalex.org/works",
            "api.crossref.org/works",
            "api.semanticscholar.org/graph/v1/paper/search",
        )
    ):
        return True
    prefix = body[:4096].lstrip().lower()
    if "atom" in mime_type and "<feed" in prefix and ("arxiv" in prefix or "<entry" in prefix):
        return True
    if prefix.startswith("<feed") and ("arxiv.org" in prefix or "<entry" in prefix):
        return True
    if _looks_like_json(body, mime_type=mime_type):
        return any(
            marker in prefix
            for marker in (
                '"abstract_inverted_index"',
                '"authorships"',
                '"container-title"',
                '"date-parts"',
                '"externalids"',
                '"is-referenced-by-count"',
                '"paperid"',
            )
        )
    return False


def _extract_scholarly_metadata_readable_text(
    body: str, *, document: FetchedDocument
) -> tuple[str, str]:
    uri = document.uri.lower()
    prefix = body[:4096].lstrip().lower()
    if "export.arxiv.org/api/query" in uri or prefix.startswith("<feed"):
        text = _extract_arxiv_atom_readable_text(body)
        if text:
            return text, "arxiv_atom_readable_text"
    if not _looks_like_json(body, mime_type=str(document.metadata.get("mime_type") or "").lower()):
        return "", "scholarly_json_readable_text"
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "", "scholarly_json_readable_text"
    if "api.openalex.org/works" in uri or _looks_like_openalex_payload(payload):
        text = _extract_openalex_readable_text(payload)
        if text:
            return text, "openalex_readable_text"
    if "api.crossref.org/works" in uri or _looks_like_crossref_payload(payload):
        text = _extract_crossref_readable_text(payload)
        if text:
            return text, "crossref_readable_text"
    if "api.semanticscholar.org/graph/v1/paper/search" in uri or _looks_like_semantic_scholar_payload(payload):
        text = _extract_semantic_scholar_readable_text(payload)
        if text:
            return text, "semantic_scholar_readable_text"
    text = _extract_generic_scholarly_json_readable_text(payload)
    return (text, "scholarly_json_readable_text") if text else ("", "scholarly_json_readable_text")


def _extract_arxiv_atom_readable_text(body: str) -> str:
    try:
        root = ET.fromstring(body[:READABLE_TEXT_LIMIT])
    except ET.ParseError:
        return ""
    entries = [_element for _element in root.iter() if _xml_local_name(_element.tag) == "entry"]
    lines = [f"scholarly metadata records source=arXiv record_count={len(entries)}"]
    for entry in entries[:SCHOLARLY_RECORD_LIMIT]:
        title = _strip_markup(_xml_child_text(entry, "title"))
        abstract = _strip_markup(_xml_child_text(entry, "summary"))
        paper_id = _strip_markup(_xml_child_text(entry, "id"))
        published = _strip_markup(_xml_child_text(entry, "published"))
        updated = _strip_markup(_xml_child_text(entry, "updated"))
        doi = _strip_markup(_xml_child_text(entry, "doi"))
        authors = [
            _strip_markup(_xml_child_text(author, "name"))
            for author in entry
            if _xml_local_name(author.tag) == "author"
        ]
        categories = [
            str(category.attrib.get("term") or "").strip()
            for category in entry
            if _xml_local_name(category.tag) == "category" and str(category.attrib.get("term") or "").strip()
        ]
        lines.append(
            _scholarly_record_line(
                source="arXiv",
                title=title,
                abstract=abstract,
                authors=authors,
                year=_year_from_text(published or updated),
                published=published,
                identifier=paper_id,
                doi=doi,
                url=paper_id,
                venue="arXiv",
                concepts=categories,
                citation_count=None,
            )
        )
    return "\n".join(line for line in lines if line.strip())[:READABLE_TEXT_LIMIT]


def _extract_openalex_readable_text(payload: object) -> str:
    items = _payload_items(payload, collection_key="results")
    lines = [f"scholarly metadata records source=OpenAlex record_count={len(items)}"]
    for item in items[:SCHOLARLY_RECORD_LIMIT]:
        if not isinstance(item, dict):
            continue
        title = _string_value(item.get("display_name") or item.get("title"))
        abstract = _openalex_abstract(item.get("abstract_inverted_index"))
        ids = item.get("ids") if isinstance(item.get("ids"), dict) else {}
        primary_location = item.get("primary_location") if isinstance(item.get("primary_location"), dict) else {}
        source = primary_location.get("source") if isinstance(primary_location.get("source"), dict) else {}
        authors = _openalex_authors(item.get("authorships"))
        concepts = [
            _string_value(concept.get("display_name"))
            for concept in (item.get("concepts") if isinstance(item.get("concepts"), list) else [])
            if isinstance(concept, dict) and _string_value(concept.get("display_name"))
        ]
        lines.append(
            _scholarly_record_line(
                source="OpenAlex",
                title=title,
                abstract=abstract,
                authors=authors,
                year=_int_or_none(item.get("publication_year") or item.get("year")),
                published=_string_value(item.get("publication_date")),
                identifier=_string_value(item.get("id")),
                doi=_string_value(item.get("doi") or ids.get("doi")),
                url=_string_value(primary_location.get("landing_page_url") or item.get("doi") or item.get("id")),
                venue=_openalex_venue(item, source=source),
                concepts=concepts,
                citation_count=_int_or_none(item.get("cited_by_count")),
            )
        )
    return "\n".join(line for line in lines if line.strip())[:READABLE_TEXT_LIMIT]


def _extract_crossref_readable_text(payload: object) -> str:
    message = payload.get("message") if isinstance(payload, dict) else None
    items = message.get("items") if isinstance(message, dict) and isinstance(message.get("items"), list) else []
    if not items and isinstance(message, dict):
        items = [message]
    lines = [f"scholarly metadata records source=Crossref record_count={len(items)}"]
    for item in items[:SCHOLARLY_RECORD_LIMIT]:
        if not isinstance(item, dict):
            continue
        title = _first_text(item.get("title"))
        abstract = _strip_markup(_string_value(item.get("abstract")))
        authors = _crossref_authors(item.get("author"))
        concepts = [_string_value(value) for value in item.get("subject", [])] if isinstance(item.get("subject"), list) else []
        lines.append(
            _scholarly_record_line(
                source="Crossref",
                title=title,
                abstract=abstract,
                authors=authors,
                year=_crossref_year(item),
                published=_crossref_published(item),
                identifier=_string_value(item.get("DOI")),
                doi=_string_value(item.get("DOI")),
                url=_string_value(item.get("URL")),
                venue=_first_text(item.get("container-title")) or _string_value(item.get("publisher")),
                concepts=concepts,
                citation_count=_int_or_none(item.get("is-referenced-by-count")),
            )
        )
    return "\n".join(line for line in lines if line.strip())[:READABLE_TEXT_LIMIT]


def _extract_semantic_scholar_readable_text(payload: object) -> str:
    items = _payload_items(payload, collection_key="data")
    lines = [f"scholarly metadata records source=SemanticScholar record_count={len(items)}"]
    for item in items[:SCHOLARLY_RECORD_LIMIT]:
        if not isinstance(item, dict):
            continue
        external_ids = item.get("externalIds") if isinstance(item.get("externalIds"), dict) else {}
        open_access = item.get("openAccessPdf") if isinstance(item.get("openAccessPdf"), dict) else {}
        concepts = [_string_value(value) for value in item.get("fieldsOfStudy", [])] if isinstance(item.get("fieldsOfStudy"), list) else []
        lines.append(
            _scholarly_record_line(
                source="SemanticScholar",
                title=_string_value(item.get("title")),
                abstract=_string_value(item.get("abstract")),
                authors=[
                    _string_value(author.get("name"))
                    for author in item.get("authors", [])
                    if isinstance(author, dict) and _string_value(author.get("name"))
                ],
                year=_int_or_none(item.get("year")),
                published=_string_value(item.get("publicationDate")),
                identifier=_string_value(item.get("paperId") or external_ids.get("CorpusId")),
                doi=_string_value(external_ids.get("DOI")),
                url=_string_value(open_access.get("url") or item.get("url")),
                venue=_string_value(item.get("venue")),
                concepts=concepts,
                citation_count=_int_or_none(item.get("citationCount")),
            )
        )
    return "\n".join(line for line in lines if line.strip())[:READABLE_TEXT_LIMIT]


def _extract_generic_scholarly_json_readable_text(payload: object) -> str:
    items: list[object] = []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        for key in ("results", "items", "data", "records", "works"):
            value = payload.get(key)
            if isinstance(value, list):
                items = value
                break
        if not items and any(key in payload for key in ("title", "abstract", "doi", "DOI")):
            items = [payload]
    if not items:
        return ""
    lines = [f"scholarly metadata records source=GenericScholarlyJSON record_count={len(items)}"]
    for item in items[:SCHOLARLY_RECORD_LIMIT]:
        if not isinstance(item, dict):
            continue
        title = _string_value(item.get("title") or item.get("display_name") or item.get("name"))
        abstract = _string_value(item.get("abstract") or item.get("summary") or item.get("description"))
        if not title and not abstract:
            continue
        lines.append(
            _scholarly_record_line(
                source="GenericScholarlyJSON",
                title=title,
                abstract=abstract,
                authors=[],
                year=_int_or_none(item.get("year") or item.get("publication_year")),
                published=_string_value(item.get("published") or item.get("publication_date")),
                identifier=_string_value(item.get("id") or item.get("paperId")),
                doi=_string_value(item.get("doi") or item.get("DOI")),
                url=_string_value(item.get("url") or item.get("URL")),
                venue=_string_value(item.get("venue") or item.get("journal")),
                concepts=[],
                citation_count=_int_or_none(item.get("citationCount") or item.get("cited_by_count")),
            )
        )
    return "\n".join(line for line in lines if line.strip())[:READABLE_TEXT_LIMIT]


def _scholarly_record_line(
    *,
    source: str,
    title: str,
    abstract: str,
    authors: list[str],
    year: int | None,
    published: str,
    identifier: str,
    doi: str,
    url: str,
    venue: str,
    concepts: list[str],
    citation_count: int | None,
) -> str:
    parts = [f"scholarly_work source={_structured_value(source)}"]
    if title:
        parts.append(f"title={_structured_long_value(title, limit=360)}")
    if authors:
        parts.append(f"authors={_structured_long_value('; '.join(authors[:8]), limit=360)}")
    if year is not None:
        parts.append(f"year={year}")
    if published:
        parts.append(f"published={_structured_value(published)}")
    if venue:
        parts.append(f"venue={_structured_value(venue)}")
    if doi:
        parts.append(f"doi={_structured_value(doi)}")
    if identifier:
        parts.append(f"id={_structured_value(identifier)}")
    if url:
        parts.append(f"url={_structured_long_value(url, limit=360)}")
    if concepts:
        parts.append(f"concepts={_structured_long_value('; '.join(concepts[:12]), limit=360)}")
    if citation_count is not None:
        parts.append(f"citation_count={citation_count}")
    if abstract:
        parts.append(f"abstract={_structured_long_value(abstract, limit=SCHOLARLY_ABSTRACT_LIMIT)}")
    return _truncate_structured_line(" ".join(parts))


def _looks_like_openalex_payload(payload: object) -> bool:
    items = _payload_items(payload, collection_key="results")
    return any(
        isinstance(item, dict) and ("abstract_inverted_index" in item or "authorships" in item or "openalex" in str(item.get("id") or "").lower())
        for item in items[:5]
    )


def _looks_like_crossref_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    message = payload.get("message")
    return isinstance(message, dict) and ("items" in message or "DOI" in message or "query" in message)


def _looks_like_semantic_scholar_payload(payload: object) -> bool:
    items = _payload_items(payload, collection_key="data")
    return any(isinstance(item, dict) and ("paperId" in item or "externalIds" in item or "citationCount" in item) for item in items[:5])


def _payload_items(payload: object, *, collection_key: str) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        value = payload.get(collection_key)
        if isinstance(value, list):
            return value
        if any(key in payload for key in ("title", "display_name", "abstract", "paperId", "DOI")):
            return [payload]
    return []


def _openalex_abstract(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    words_by_position: dict[int, str] = {}
    for word, positions in value.items():
        if not isinstance(word, str) or not isinstance(positions, list):
            continue
        for position in positions:
            if isinstance(position, int):
                words_by_position[position] = word
    if not words_by_position:
        return ""
    return _normalize_span(" ".join(words_by_position[index] for index in sorted(words_by_position)))


def _openalex_authors(value: object) -> list[str]:
    authors: list[str] = []
    if not isinstance(value, list):
        return authors
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        name = _string_value(item.get("raw_author_name"))
        if not name:
            author = item.get("author")
            if isinstance(author, dict):
                name = _string_value(author.get("display_name"))
        if name:
            authors.append(name)
    return authors


def _openalex_venue(item: dict, *, source: dict) -> str:
    source_name = _string_value(source.get("display_name"))
    if source_name:
        return source_name
    host_venue = item.get("host_venue")
    if isinstance(host_venue, dict):
        return _string_value(host_venue.get("display_name"))
    return ""


def _crossref_authors(value: object) -> list[str]:
    authors: list[str] = []
    if not isinstance(value, list):
        return authors
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        name = " ".join(
            part for part in (_string_value(item.get("given")), _string_value(item.get("family"))) if part
        ).strip()
        if name:
            authors.append(name)
    return authors


def _crossref_year(item: dict) -> int | None:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = item.get(key)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list) and date_parts[0]:
            year = _int_or_none(date_parts[0][0])
            if year is not None:
                return year
    return None


def _crossref_published(item: dict) -> str:
    for key in ("published-print", "published-online", "published", "issued", "created"):
        value = item.get(key)
        if not isinstance(value, dict):
            continue
        date_parts = value.get("date-parts")
        if isinstance(date_parts, list) and date_parts and isinstance(date_parts[0], list):
            return "-".join(str(part) for part in date_parts[0])
    return ""


def _document_source_kind(document: FetchedDocument) -> str:
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    source_metadata = metadata.get("source_metadata") if isinstance(metadata.get("source_metadata"), dict) else {}
    for container in (source_metadata, metadata):
        value = container.get("source_kind")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _xml_child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _xml_local_name(child.tag) == name:
            return "".join(child.itertext())
    return ""


def _xml_local_name(tag: object) -> str:
    text = str(tag)
    if "}" in text:
        return text.rsplit("}", 1)[-1]
    return text


def _first_text(value: object) -> str:
    if isinstance(value, list):
        for item in value:
            text = _string_value(item)
            if text:
                return text
        return ""
    return _string_value(value)


def _string_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _normalize_span(value)
    if isinstance(value, (int, float, bool)):
        return str(value)
    return ""


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _year_from_text(value: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", value)
    return int(match.group(0)) if match else None


def _strip_markup(value: str) -> str:
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    return _normalize_span(text)


def _looks_like_sec_companyfacts(body: str, *, document: FetchedDocument) -> bool:
    uri = document.uri.lower()
    title = document.title.lower()
    if "data.sec.gov/api/xbrl/companyfacts/" in uri or "sec companyfacts" in title:
        return True
    prefix = body[:4096]
    return '"facts"' in prefix and '"entityName"' in prefix and "us-gaap" in prefix


def _extract_sec_companyfacts_readable_text(body: str, *, goal: SearchGoal | None = None) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return ""
    entity_name = _structured_value(payload.get("entityName") or "")
    cik = _structured_value(payload.get("cik") or "")
    lines = [
        _normalize_span(
            f"SEC companyfacts official financial statements entityName={entity_name} cik={cik} source=SEC_XBRL_companyfacts"
        )
    ]
    lines.extend(_companyfacts_annual_summary_lines(facts, entity_name=entity_name, cik=cik, goal=goal))
    for taxonomy_name in ("us-gaap", "ifrs-full", "dei"):
        taxonomy = facts.get(taxonomy_name)
        if not isinstance(taxonomy, dict):
            continue
        for concept, metric in _companyfacts_concept_specs(taxonomy):
            item = taxonomy.get(concept)
            if not isinstance(item, dict):
                continue
            label = _structured_value(item.get("label") or concept)
            units = item.get("units")
            if not isinstance(units, dict):
                continue
            for unit, records in units.items():
                if not isinstance(records, list):
                    continue
                for record in _recent_companyfacts_records(records)[:6]:
                    if not isinstance(record, dict):
                        continue
                    lines.append(
                        _companyfacts_record_line(
                            entity_name=entity_name,
                            cik=cik,
                            taxonomy=taxonomy_name,
                            concept=concept,
                            metric=metric,
                            label=label,
                            unit=_structured_value(unit),
                            record=record,
                        )
                    )
                    if len(lines) >= STRUCTURED_LINE_LIMIT:
                        return "\n".join(lines)[:READABLE_TEXT_LIMIT]
    return "\n".join(lines)[:READABLE_TEXT_LIMIT]


def _companyfacts_concept_specs(taxonomy: dict) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for concept, metric in SEC_COMPANYFACTS_CONCEPTS:
        if concept in taxonomy and concept not in seen:
            seen.add(concept)
            specs.append((concept, metric))
    dynamic: list[tuple[int, str, str]] = []
    for concept, item in taxonomy.items():
        if concept in seen or not isinstance(item, dict):
            continue
        label = _structured_value(item.get("label") or concept)
        metric = _companyfacts_dynamic_metric(concept=concept, label=label)
        if not metric:
            continue
        dynamic.append((_companyfacts_dynamic_priority(concept=concept, label=label, metric=metric), concept, metric))
    dynamic.sort(key=lambda item: (-item[0], item[1].lower()))
    for _priority, concept, metric in dynamic[:96]:
        specs.append((concept, metric))
    return specs


def _ordered_companyfacts_metrics(
    metrics: dict[str, object],
    *,
    priority_metric_names: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    order: list[tuple[str, str]] = []
    seen: set[str] = set()
    priority_metrics = (
        *priority_metric_names,
        "inventory",
        "cost of revenue",
        "cost of goods sold",
        "cost of sales",
    )
    for metric in priority_metrics:
        if metric in metrics and metric not in seen:
            seen.add(metric)
            order.append(("", metric))
    for concept, metric in SEC_COMPANYFACTS_CONCEPTS:
        if metric in metrics and metric not in seen:
            seen.add(metric)
            order.append((concept, metric))
    for metric in sorted(str(item) for item in metrics.keys() if str(item) not in seen):
        order.append(("", metric))
    return order


def _companyfacts_dynamic_metric(*, concept: str, label: str) -> str | None:
    compact = _compact_metric_text(concept)
    lower = f"{concept} {label}".lower().replace("_", " ")
    if "familyofapps" in compact and "revenue" in compact:
        return "family of apps revenue"
    if "realitylabs" in compact and "revenue" in compact:
        return "reality labs revenue"
    if "salesandotheroperatingrevenue" in compact:
        return "sales and other operating revenues"
    if "totalrevenuesandotherincome" in compact or ("total revenues" in lower and "other income" in lower):
        return "total revenues and other income"
    if "operatingrevenues" in compact or ("operating" in lower and "revenue" in lower):
        return "operating revenues"
    if "netrevenues" in compact or "net revenues" in lower:
        return "net revenues"
    if "netinterestincome" in compact or ("net interest" in lower and "income" in lower):
        return "net interest income"
    if "interestincomeexpensenet" in compact:
        return "net interest income"
    if "incomelossfromcontinuingoperationsbeforeincometaxes" in compact:
        return "pretax income"
    if "interestincome" in compact or "interest income" in lower:
        return "interest income"
    if "interestexpense" in compact or "interest expense" in lower:
        return "interest expense"
    if "noninterestincome" in compact or "noninterest income" in lower:
        return "noninterest income"
    if "revenuefromexternalcustomers" in compact:
        return "segment revenue from external customers"
    if "segment" in lower and "revenue" in lower:
        return "segment revenue"
    if "cloud" in lower and ("investment" in lower or "infrastructure" in lower):
        return "cloud and AI infrastructure investment"
    if "artificial intelligence" in lower and ("investment" in lower or "infrastructure" in lower):
        return "cloud and AI infrastructure investment"
    if "capitalexpenditure" in compact or ("capital" in lower and "expenditure" in lower):
        return "capital expenditures"
    if "capitalized" in lower and ("software" in lower or "cloud" in lower):
        return "capitalized software or cloud infrastructure"
    if (
        ("depreciation" in lower or "amortization" in lower)
        and ("cost of goods" in lower or "costofgoods" in compact or "cost of revenue" in lower)
    ):
        return None
    if "revenue" in lower or "revenues" in lower or compact.endswith("sales"):
        return "revenue"
    if "earningspershare" in compact or "earnings per share" in lower:
        return "earnings per share"
    if "netincomeloss" in compact or "net income" in lower:
        return "net income"
    if "operatingincomeloss" in compact or "operating income" in lower:
        return "operating income"
    if ("deferredtax" in compact or "deferred tax" in lower) and (
        "inventory" in compact or "inventor" in lower
    ):
        return None
    if "valuationreserve" in compact or "valuation reserves" in lower:
        return None
    if "increasedecrease" in compact and ("inventory" in compact or "inventor" in lower):
        return None
    if "inventory" in compact or "inventories" in lower or "merchandise inventories" in lower:
        return "inventory"
    if "costofrevenue" in compact or "cost of revenue" in lower:
        return "cost of revenue"
    if (
        "costofgoods" in compact
        or "costofsales" in compact
        or "cost of goods" in lower
        or "cost of sales" in lower
    ):
        return "cost of goods sold"
    if "cashflow" in compact or "cash flow" in lower:
        return "cash flow"
    if "stockholdersequity" in compact or "shareholders equity" in lower or "stockholders equity" in lower:
        return "shareholders equity"
    if "liabilities" in lower:
        return "liabilities"
    if "assets" in lower:
        return "assets"
    if "longtermdebt" in compact:
        return "long-term debt"
    if "shorttermborrowings" in compact:
        return "short-term borrowings"
    if "debt" in lower:
        return "debt"
    return None


def _companyfacts_dynamic_priority(*, concept: str, label: str, metric: str) -> int:
    text = f"{concept} {label} {metric}".lower()
    priority = 0
    for index, keyword in enumerate(SEC_COMPANYFACTS_DYNAMIC_KEYWORDS):
        if keyword in text:
            priority += max(1, len(SEC_COMPANYFACTS_DYNAMIC_KEYWORDS) - index)
    if metric in {
        "net interest income",
        "sales and other operating revenues",
        "total revenues and other income",
        "operating revenues",
        "segment revenue",
        "family of apps revenue",
        "inventory",
        "cost of revenue",
        "cost of goods sold",
        "capital expenditures",
    }:
        priority += 40
    if "abstract" in text or "policy" in text or "schedule" in text:
        priority -= 20
    return priority


def _compact_metric_text(value: str) -> str:
    return "".join(ch.lower() for ch in str(value or "") if ch.isalnum())


def _companyfacts_annual_summary_lines(
    facts: dict,
    *,
    entity_name: str,
    cik: str,
    goal: SearchGoal | None = None,
) -> list[str]:
    groups: dict[tuple[int, str], dict[str, object]] = {}
    for taxonomy_name in ("us-gaap", "ifrs-full"):
        taxonomy = facts.get(taxonomy_name)
        if not isinstance(taxonomy, dict):
            continue
        for concept, metric in _companyfacts_concept_specs(taxonomy):
            item = taxonomy.get(concept)
            if not isinstance(item, dict):
                continue
            units = item.get("units")
            if not isinstance(units, dict):
                continue
            label = _structured_value(item.get("label") or concept)
            for unit, records in units.items():
                if not isinstance(records, list):
                    continue
                for record in _recent_companyfacts_records(records):
                    if not isinstance(record, dict) or _companyfacts_period_rank(record) < 3:
                        continue
                    year = _companyfacts_year(record)
                    if year is None:
                        continue
                    key = (year, str(record.get("end") or ""))
                    group = groups.setdefault(
                        key,
                        {
                            "year": year,
                            "end": str(record.get("end") or ""),
                            "filed": str(record.get("filed") or ""),
                            "form": str(record.get("form") or ""),
                            "metrics": {},
                        },
                    )
                    if str(record.get("filed") or "") > str(group.get("filed") or ""):
                        group["filed"] = str(record.get("filed") or "")
                    if not group.get("form") and record.get("form"):
                        group["form"] = str(record.get("form") or "")
                    metrics = group.get("metrics")
                    if not isinstance(metrics, dict):
                        continue
                    existing = metrics.get(metric)
                    candidate = {
                        "concept": concept,
                        "metric": metric,
                        "label": label,
                        "unit": _structured_value(unit),
                        "val": record.get("val"),
                        "fy": record.get("fy"),
                        "fp": record.get("fp"),
                        "form": record.get("form"),
                        "filed": record.get("filed"),
                        "start": record.get("start"),
                        "end": record.get("end"),
                        "frame": record.get("frame"),
                        "accn": record.get("accn"),
                        "taxonomy": taxonomy_name,
                    }
                    if existing is None or _companyfacts_record_prefer(candidate, existing):
                        metrics[metric] = candidate
    ordered = sorted(
        groups.values(),
        key=lambda group: (int(group.get("year") or 0), str(group.get("filed") or ""), str(group.get("end") or "")),
        reverse=True,
    )
    target_years = _companyfacts_target_years(goal.query if goal is not None else "")
    query_priority_metrics = _companyfacts_query_priority_metrics(goal.query if goal is not None else "")
    selected_groups = _companyfacts_selected_summary_groups(ordered, target_years=target_years)
    lines = []
    for group in selected_groups:
        metrics = group.get("metrics") if isinstance(group.get("metrics"), dict) else {}
        metric_parts = []
        emitted_metrics: set[str] = set()
        for _concept, metric in _ordered_companyfacts_metrics(metrics, priority_metric_names=query_priority_metrics):
            if metric in emitted_metrics:
                continue
            entry = metrics.get(metric)
            if not isinstance(entry, dict):
                continue
            emitted_metrics.add(metric)
            metric_parts.append(_companyfacts_summary_metric_part(entry, metric=metric))
        if not metric_parts:
            continue
        lines.append(
            _truncate_structured_line(
                " ".join(
                    [
                        f"SEC companyfacts annual financial summary entityName={entity_name}",
                        f"cik={cik}",
                        f"fy={_structured_value(group.get('year'))}",
                        f"period=annual",
                        f"form={_structured_value(group.get('form'))}",
                        f"filed={_structured_value(group.get('filed'))}",
                        f"end={_structured_value(group.get('end'))}",
                        "facts=" + " ; ".join(metric_parts),
                    ]
                )
            )
        )
    return lines


def _companyfacts_query_priority_metrics(query: str) -> tuple[str, ...]:
    normalized = " ".join(str(query or "").lower().replace("_", " ").split())
    priorities: list[str] = []

    def add(metric: str) -> None:
        if metric not in priorities:
            priorities.append(metric)

    if any(
        alias in normalized
        for alias in (
            "capital expenditure",
            "capital expenditures",
            "capex",
            "property, plant and equipment",
            "property plant and equipment",
            "pp&e",
            "purchases of property",
            "payments to acquire property",
        )
    ):
        add("capital expenditures")
    if any(alias in normalized for alias in ("operating cash flow", "cash flow from operating", "operating activities")):
        add("operating cash flow")
    if any(alias in normalized for alias in ("revenue", "revenues", "sales", "net sales")):
        add("revenue")
        add("net sales")
    if any(alias in normalized for alias in ("net income", "net earnings", "profit")):
        add("net income")
    if any(alias in normalized for alias in ("eps", "earnings per share")):
        add("diluted earnings per share")
        add("basic earnings per share")
    if "inventory" in normalized or "inventories" in normalized:
        add("inventory")
    if any(alias in normalized for alias in ("cost of goods", "cost of sales", "cogs", "cost of revenue")):
        add("cost of goods sold")
        add("cost of sales")
        add("cost of revenue")
    return tuple(priorities)


def _companyfacts_target_years(query: str) -> set[int]:
    years: set[int] = set()
    for match in re.finditer(r"\b(?:FY|fiscal\s+year\s*)?((?:19|20)\d{2})\b", str(query or ""), flags=re.IGNORECASE):
        try:
            years.add(int(match.group(1)))
        except ValueError:
            continue
    return years


def _companyfacts_selected_summary_groups(groups: list[dict[str, object]], *, target_years: set[int]) -> list[dict[str, object]]:
    selected: list[dict[str, object]] = []
    seen: set[tuple[int, str]] = set()

    def append_group(group: dict[str, object]) -> None:
        try:
            year = int(group.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        key = (year, str(group.get("end") or ""))
        if key in seen:
            return
        seen.add(key)
        selected.append(group)

    if target_years:
        for group in groups:
            try:
                year = int(group.get("year") or 0)
            except (TypeError, ValueError):
                continue
            if year in target_years:
                append_group(group)
    for group in groups[:SEC_COMPANYFACTS_SUMMARY_YEARS]:
        append_group(group)
    return selected


def _companyfacts_summary_metric_part(entry: dict, *, metric: str) -> str:
    parts = [
        f"metric={_structured_value(metric)}",
        f"concept={_structured_value(entry.get('concept'))}",
    ]
    period_year = _companyfacts_year(entry)
    if period_year is not None:
        parts.append(f"period_fy={_structured_value(period_year)}")
    value = entry.get("val")
    if value is not None and value != "":
        parts.append(f"value={_structured_value(value)}")
        parts.append(f"val={_structured_value(value)}")
    for key in ("unit", "fy", "fp", "form", "filed", "start", "end", "frame", "accn"):
        value = entry.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}={_structured_value(value)}")
    return " ".join(parts)


def _companyfacts_record_prefer(candidate: dict, existing: object) -> bool:
    if not isinstance(existing, dict):
        return True
    return (
        str(candidate.get("form") or "").upper().replace(" ", "") in {"10-K", "20-F", "40-F"},
        str(candidate.get("filed") or ""),
        str(candidate.get("end") or ""),
    ) > (
        str(existing.get("form") or "").upper().replace(" ", "") in {"10-K", "20-F", "40-F"},
        str(existing.get("filed") or ""),
        str(existing.get("end") or ""),
    )


def _recent_companyfacts_records(records: list[object]) -> list[object]:
    filtered = [
        record
        for record in records
        if isinstance(record, dict) and str(record.get("form") or "").upper().replace(" ", "") in SEC_COMPANYFACTS_FORMS
    ]
    if not filtered:
        filtered = [record for record in records if isinstance(record, dict)]
    return sorted(
        filtered,
        key=lambda record: (
            _companyfacts_period_rank(record),
            _companyfacts_duration_days(record),
            int(record.get("fy") or 0) if isinstance(record.get("fy"), int) else 0,
            str(record.get("filed") or ""),
            str(record.get("end") or ""),
        ),
        reverse=True,
    )


def _companyfacts_period_rank(record: dict) -> int:
    form = str(record.get("form") or "").upper().replace(" ", "")
    fp = str(record.get("fp") or "").upper().replace(" ", "")
    if form in {"10-K", "20-F", "40-F"} or fp == "FY":
        return 3
    if form == "10-Q" or fp.startswith("Q"):
        return 2
    return 1


def _companyfacts_period_label(record: dict) -> str:
    rank = _companyfacts_period_rank(record)
    if rank >= 3:
        return "annual"
    if rank == 2:
        return "quarterly"
    return "period"


def _companyfacts_year(record: dict) -> int | None:
    if _companyfacts_duration_days(record) >= 250:
        end_year = _year_from_text(str(record.get("end") or ""))
        if end_year is not None:
            return end_year
    end_year = _year_from_text(str(record.get("end") or ""))
    if end_year is not None:
        return end_year
    frame_year = _year_from_text(str(record.get("frame") or ""))
    if frame_year is not None:
        return frame_year
    fy = record.get("fy")
    if isinstance(fy, int) and 1900 <= fy <= 2100:
        return fy
    return None


def _companyfacts_duration_days(record: dict) -> int:
    start = str(record.get("start") or "")
    end = str(record.get("end") or "")
    if not start or not end:
        return 0
    start_days = _date_days(start)
    end_days = _date_days(end)
    if start_days is None or end_days is None:
        return 0
    return max(0, end_days - start_days)


def _date_days(value: str) -> int | None:
    match = re.match(r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})$", value)
    if not match:
        return None
    year = int(match.group("year"))
    month = int(match.group("month"))
    day = int(match.group("day"))
    return year * 372 + month * 31 + day


def _companyfacts_record_line(
    *,
    entity_name: str,
    cik: str,
    taxonomy: str,
    concept: str,
    metric: str,
    label: str,
    unit: str,
    record: dict,
) -> str:
    parts = [
        f"SEC companyfacts official financial statement entityName={entity_name}",
        f"cik={cik}",
        f"taxonomy={taxonomy}",
        f"concept={concept}",
        f"metric={metric}",
        f"label={label}",
        f"unit={unit}",
        f"period={_companyfacts_period_label(record)}",
    ]
    for key in ("val", "fy", "fp", "form", "filed", "end", "start", "frame", "accn"):
        value = record.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}={_structured_value(value)}")
    return _truncate_structured_line(" ".join(parts))


def _flatten_json(value: object, *, path: str, lines: list[str], depth: int) -> None:
    if len(lines) >= STRUCTURED_LINE_LIMIT or depth > 12:
        return
    if isinstance(value, dict):
        scalar_parts = []
        complex_items = []
        for key, item in value.items():
            key_text = _structured_key(key)
            next_path = f"{path}.{key_text}" if path else key_text
            if _is_scalar(item):
                scalar_parts.append(f"{key_text}={_structured_value(item)}")
            else:
                complex_items.append((next_path, item))
        if scalar_parts:
            prefix = f"{path}: " if path else ""
            lines.append(_truncate_structured_line(prefix + " ".join(scalar_parts)))
        for next_path, item in complex_items:
            _flatten_json(item, path=next_path, lines=lines, depth=depth + 1)
            if len(lines) >= STRUCTURED_LINE_LIMIT:
                break
        return
    if isinstance(value, list):
        for index, item in enumerate(value[:500]):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            _flatten_json(item, path=next_path, lines=lines, depth=depth + 1)
            if len(lines) >= STRUCTURED_LINE_LIMIT:
                break
        if len(value) > 500 and len(lines) < STRUCTURED_LINE_LIMIT:
            lines.append(f"{path}: truncated_list_count={len(value)}")
        return
    if _is_scalar(value):
        lines.append(_truncate_structured_line(f"{path}: {_structured_value(value)}" if path else _structured_value(value)))


def _extract_csv_readable_text(body: str) -> str:
    sample = body[:READABLE_TEXT_LIMIT]
    try:
        rows = list(csv.reader(io.StringIO(sample)))
    except csv.Error:
        return ""
    if not rows:
        return ""
    header = [_structured_key(item) for item in rows[0]]
    has_header = bool(header) and any(not _looks_numeric(item) for item in header)
    lines: list[str] = []
    if has_header:
        lines.append("csv_header: " + " ".join(header))
        data_rows = rows[1:]
    else:
        header = [f"column_{index + 1}" for index in range(max(len(row) for row in rows[:20]))]
        data_rows = rows
    for row_index, row in enumerate(data_rows[: min(500, STRUCTURED_LINE_LIMIT - len(lines))], start=1):
        if not any(cell.strip() for cell in row):
            continue
        parts = []
        for column_index, cell in enumerate(row):
            key = header[column_index] if column_index < len(header) else f"column_{column_index + 1}"
            parts.append(f"{key}={_structured_value(cell)}")
        lines.append(_truncate_structured_line(f"csv_row_{row_index}: " + " ".join(parts)))
    return _normalize_span(" ".join(lines)[:READABLE_TEXT_LIMIT])


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _structured_key(value: object) -> str:
    text = str(value).strip()
    return re.sub(r"\s+", "_", text)[:80] or "field"


def _structured_value(value: object) -> str:
    if value is None:
        return "null"
    text = str(value).strip()
    return _normalize_span(text)[:STRUCTURED_VALUE_LIMIT]


def _structured_long_value(value: object, *, limit: int) -> str:
    if value is None:
        return ""
    text = _normalize_span(str(value).strip())
    return text[: max(0, limit)]


def _truncate_structured_line(text: str) -> str:
    normalized = _normalize_span(text)
    if len(normalized) <= 1_000:
        return normalized
    return normalized[:997] + "..."


def _looks_numeric(value: object) -> bool:
    try:
        float(str(value).strip())
    except ValueError:
        return False
    return True


def _extract_pdf_text(body: str) -> str:
    text, _diagnostics = _extract_pdf_text_with_diagnostics(body)
    return text


def _extract_pdf_text_with_diagnostics(body: str) -> tuple[str, JsonObject]:
    failures: list[str] = []
    for parser_name, parser in (("pdf_text_pypdf", _extract_pdf_text_pypdf), ("pdf_text_pdfminer", _extract_pdf_text_pdfminer)):
        try:
            text, diagnostics = parser(body)
        except Exception as exc:  # pragma: no cover - optional parser failures vary by dependency/version.
            failures.append(f"{parser_name}:{type(exc).__name__}")
            continue
        if text:
            return text[:READABLE_TEXT_LIMIT], {
                **diagnostics,
                "parser_used": parser_name,
                "chars_extracted": len(text),
                "table_like_blocks": _table_like_block_count(text),
                **({"fallback_failures": failures} if failures else {}),
            }
        failures.append(f"{parser_name}:empty")
    fallback = _extract_pdf_text_literals(body)
    return fallback, {
        "parser_used": "pdf_text_literals",
        "pages_extracted": 0,
        "chars_extracted": len(fallback),
        "table_like_blocks": _table_like_block_count(fallback),
        "extraction_failure_reason": ";".join(failures) if failures else "optional_pdf_parser_unavailable",
    }


def _extract_pdf_text_pypdf(body: str) -> tuple[str, JsonObject]:
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency is optional.
        raise RuntimeError("pypdf_unavailable") from exc
    data = _pdf_body_bytes(body)
    reader = PdfReader(io.BytesIO(data))
    pieces: list[str] = []
    for page in reader.pages:
        try:
            pieces.append(page.extract_text() or "")
        except Exception:
            continue
    text = _normalize_span("\n".join(piece for piece in pieces if piece.strip()))
    return text, {"pages_extracted": len(pieces)}


def _extract_pdf_text_pdfminer(body: str) -> tuple[str, JsonObject]:
    try:
        from pdfminer.high_level import extract_text_to_fp  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency is optional.
        raise RuntimeError("pdfminer_unavailable") from exc
    data = _pdf_body_bytes(body)
    output = io.StringIO()
    extract_text_to_fp(io.BytesIO(data), output)
    text = _normalize_span(output.getvalue())
    return text, {"pages_extracted": _pdf_page_marker_count(body)}


def _pdf_body_bytes(body: str) -> bytes:
    return str(body or "").encode("latin-1", errors="ignore")


def _extract_pdf_text_literals(body: str) -> str:
    sample = body[:READABLE_TEXT_LIMIT]
    pieces = []
    pieces.extend(_pdf_literal_strings(sample))
    pieces.extend(_pdf_hex_strings(sample))
    return _normalize_span(" ".join(pieces)[:READABLE_TEXT_LIMIT])


def _pdf_page_marker_count(body: str) -> int:
    return len(re.findall(r"/Type\s*/Page\b", body[:READABLE_TEXT_LIMIT]))


def _table_like_block_count(text: str) -> int:
    count = 0
    for line in str(text or "").splitlines():
        if len(re.findall(r"\b-?\d[\d,]*(?:\.\d+)?\b", line)) >= 3:
            count += 1
    return count


def _pdf_literal_strings(text: str) -> list[str]:
    pieces: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "(":
            index += 1
            continue
        parsed, next_index = _parse_pdf_literal(text, index + 1)
        if _looks_like_readable_pdf_text(parsed):
            pieces.append(parsed)
        index = max(next_index, index + 1)
    return pieces


def _parse_pdf_literal(text: str, index: int) -> tuple[str, int]:
    depth = 1
    pieces: list[str] = []
    while index < len(text) and depth:
        char = text[index]
        if char == "\\":
            parsed, index = _parse_pdf_escape(text, index + 1)
            if parsed:
                pieces.append(parsed)
            continue
        if char == "(":
            depth += 1
            pieces.append(char)
            index += 1
            continue
        if char == ")":
            depth -= 1
            if depth:
                pieces.append(char)
            index += 1
            continue
        pieces.append(char)
        index += 1
    return "".join(pieces), index


def _parse_pdf_escape(text: str, index: int) -> tuple[str, int]:
    if index >= len(text):
        return "", index
    char = text[index]
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "(": "(",
        ")": ")",
        "\\": "\\",
    }
    if char in escapes:
        return escapes[char], index + 1
    if char in "\r\n":
        while index < len(text) and text[index] in "\r\n":
            index += 1
        return "", index
    if char in "01234567":
        end = index
        while end < min(len(text), index + 3) and text[end] in "01234567":
            end += 1
        try:
            return chr(int(text[index:end], 8)), end
        except ValueError:
            return "", end
    return char, index + 1


def _pdf_hex_strings(text: str) -> list[str]:
    pieces: list[str] = []
    for match in re.finditer(r"(?<!<)<([0-9A-Fa-f\s]{4,4096})>(?!>)", text):
        raw = "".join(match.group(1).split())
        if len(raw) % 2:
            raw = raw[:-1]
        if len(raw) < 4:
            continue
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue
        decoded = _decode_pdf_hex_text(data)
        if _looks_like_readable_pdf_text(decoded):
            pieces.append(decoded)
    return pieces


def _decode_pdf_hex_text(data: bytes) -> str:
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="ignore")
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="ignore")
    if len(data) >= 4:
        odd_nulls = sum(1 for index in range(0, len(data), 2) if data[index] == 0)
        even_nulls = sum(1 for index in range(1, len(data), 2) if data[index] == 0)
        if odd_nulls >= max(2, len(data) // 6):
            return data.decode("utf-16-be", errors="ignore")
        if even_nulls >= max(2, len(data) // 6):
            return data.decode("utf-16-le", errors="ignore")
    return data.decode("latin-1", errors="ignore")


def _looks_like_readable_pdf_text(text: str) -> bool:
    normalized = _normalize_span(text)
    if len(normalized) < 3:
        return False
    content_chars = sum(1 for char in normalized if char.isalnum() or "\u4e00" <= char <= "\u9fff")
    printable_chars = sum(1 for char in normalized if char.isprintable())
    if content_chars < 2:
        return False
    if printable_chars / max(1, len(normalized)) < 0.8:
        return False
    return True


def _extract_html_readable_text(body: str, *, limit: int = READABLE_TEXT_LIMIT) -> str:
    parser = _ReadableHtmlParser()
    parser.feed(body[:limit])
    parser.close()
    parsed_text = parser.text()
    text_parts = [parsed_text]
    visible_market_snippets = _extract_market_visible_snippets(parsed_text)
    if visible_market_snippets:
        text_parts.append("\nMarket data visible snippets:\n")
        text_parts.extend(f"{line}.\n" for line in visible_market_snippets)
    market_snippets = _extract_market_script_snippets(body[:limit])
    if market_snippets:
        text_parts.append("\nMarket data structured snippets:\n")
        text_parts.extend(f"{line}.\n" for line in market_snippets)
    return _normalize_span("".join(text_parts))


def _extract_market_visible_snippets(text: str) -> list[str]:
    normalized = _normalize_span(text)
    if not normalized:
        return []
    labels = (
        "Market Cap",
        "Enterprise Value",
        "Total Debt",
        "Cash & Cash Equivalents",
        "Cash and Cash Equivalents",
        "Total Cash",
        "EBITDA",
        "Revenue",
        "Net Income",
        "Operating Income",
    )
    snippets: list[str] = []
    seen: set[tuple[str, str]] = set()
    for label in labels:
        pattern = rf"\b{re.escape(label)}\b\s*(?P<value>[$€£¥]?\s*-?\d+(?:,\d{{3}})*(?:\.\d+)?\s*(?:K|M|B|T|million|billion|trillion|mn|bn)?)"
        for match in re.finditer(pattern, normalized, flags=re.IGNORECASE):
            value = _normalize_market_metric_value(match.group("value"))
            if not value:
                continue
            key = (label.lower(), value.lower())
            if key in seen:
                continue
            seen.add(key)
            snippets.append(f"{label} {value}")
            if len(snippets) >= MARKET_SCRIPT_SNIPPET_LIMIT:
                return snippets
    return snippets


def _extract_market_script_snippets(body: str) -> list[str]:
    script_texts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", body, flags=re.IGNORECASE | re.DOTALL)
    if not script_texts:
        return []
    snippets: list[str] = []
    seen: set[tuple[str, str]] = set()
    for script in script_texts:
        if not _script_may_contain_market_metrics(script):
            continue
        decoded = _decode_script_for_market_metrics(script)
        for key, label in MARKET_SCRIPT_METRIC_LABELS.items():
            for match in re.finditer(rf'(?:"|\\")?{re.escape(key)}(?:"|\\")?\s*:', decoded):
                window = decoded[match.start() : match.start() + MARKET_SCRIPT_WINDOW_CHARS]
                value = _market_metric_value_from_window(window)
                if value is None:
                    continue
                normalized_value = _normalize_market_metric_value(value)
                if not normalized_value:
                    continue
                dedupe_key = (label.lower(), normalized_value.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                snippets.append(f"{label} {normalized_value}")
                if len(snippets) >= MARKET_SCRIPT_SNIPPET_LIMIT:
                    return snippets
    return snippets


def _script_may_contain_market_metrics(script: str) -> bool:
    lower = script.lower()
    return any(key.lower() in lower for key in MARKET_SCRIPT_METRIC_LABELS)


def _decode_script_for_market_metrics(script: str) -> str:
    decoded = html.unescape(script)
    decoded = decoded.replace('\\"', '"')
    decoded = decoded.replace("\\u002F", "/").replace("\\/", "/")
    return decoded


def _market_metric_value_from_window(window: str) -> str | None:
    for pattern in (
        r'"fmt"\s*:\s*"(?P<value>[^"]{1,80})"',
        r'"longFmt"\s*:\s*"(?P<value>[^"]{1,120})"',
        r'"raw"\s*:\s*(?P<value>-?\d+(?:\.\d+)?)',
        r":\s*\"(?P<value>-?\d+(?:\.\d+)?\s*(?:K|M|B|T|million|billion|trillion)?)\"",
        r":\s*(?P<value>-?\d+(?:\.\d+)?)",
    ):
        match = re.search(pattern, window, flags=re.IGNORECASE)
        if match:
            return match.group("value")
    return None


def _normalize_market_metric_value(value: str) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    normalized = normalized.replace(",", "")
    if normalized in {"N/A", "-", "--"}:
        return ""
    return normalized


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in HTML_SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if normalized in HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in HTML_SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if normalized in HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(html.unescape(data).split())
        if text:
            self._parts.append(text)
            self._parts.append(" ")

    def text(self) -> str:
        return "".join(self._parts)


def _terms(text: str, *, goal: SearchGoal | None = None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    def add(term: str) -> None:
        normalized = term.lower().replace("-", " ").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(normalized)

    for term in text.lower().replace("-", " ").split():
        add(term)
    for facet in query_facets(text):
        for alias in QUERY_FACET_ALIASES.get(facet, ()):
            add(alias)
    if goal is not None:
        profile = resolve_goal_research_profile(goal)
        for alias in profile_extraction_aliases(goal=goal, research_profile=profile):
            add(alias)
        for alias in _finance_bridge_extraction_aliases(goal):
            add(alias)
    intent = finance_metric_intent(text)
    for phrase in intent.preferred_phrases:
        cleaned = phrase
        if cleaned.startswith("metric="):
            cleaned = cleaned.split("=", 1)[1]
        if cleaned.startswith("concept=") or cleaned.startswith("label="):
            continue
        add(cleaned)
    return terms


def _finance_bridge_extraction_aliases(goal: SearchGoal) -> tuple[str, ...]:
    query = f"{goal.query or ''} {_metadata_intent_text(goal.metadata)}".lower()
    compact = "".join(ch for ch in query if ch.isalnum())
    wants_bridge = any(
        marker in query or marker in compact
        for marker in (
            "adjusted ebitda",
            "adjustedebitda",
            "non-gaap",
            "nongaap",
            "reconciliation",
            "add-back",
            "addback",
            "add back",
            "bridge",
        )
    )
    if not wants_bridge:
        return ()
    return (
        "reconciliation of",
        "income from continuing operations",
        "adjusted ebitda",
        "depreciation and amortization",
        "stock-based compensation",
        "stock based compensation",
        "restructuring",
        "transaction costs",
    )


def _metadata_intent_text(metadata: object) -> str:
    if not isinstance(metadata, dict):
        return ""
    parts: list[str] = []
    for key in ("root_goal", "user_goal", "original_goal"):
        value = metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    mission = metadata.get("research_mission")
    if isinstance(mission, dict) and isinstance(mission.get("root_goal"), str):
        parts.append(mission["root_goal"])
    policy = metadata.get("evidence_policy")
    if isinstance(policy, dict):
        for item in policy.get("required_terms") or []:
            if isinstance(item, str):
                parts.append(item)
    slot_frame = metadata.get("slot_frame")
    if isinstance(slot_frame, dict):
        for item in slot_frame.get("missing_slots") or []:
            if isinstance(item, str):
                parts.append(item)
    return " ".join(parts)


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
