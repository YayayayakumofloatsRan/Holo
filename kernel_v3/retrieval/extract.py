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
SPAN_AFTER_CHARS = 780
FINANCE_TABLE_SPAN_AFTER_CHARS = 2_400
RANKED_SPAN_TERM_LIMIT = 40
RANKED_SPAN_POSITIONS_PER_TERM_LIMIT = 240
RANKED_SPAN_CANDIDATE_LIMIT = 1_600
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
LOW_SIGNAL_QUERY_TERMS = GENERIC_QUERY_TERMS | {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "company",
    "could",
    "did",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "if",
    "in",
    "is",
    "it",
    "its",
    "like",
    "metric",
    "not",
    "of",
    "on",
    "or",
    "please",
    "state",
    "than",
    "that",
    "the",
    "then",
    "this",
    "to",
    "useful",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "why",
    "with",
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
    ("ResearchAndDevelopmentExpense", "research and development expense"),
    ("ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost", "research and development expense"),
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
    ("PropertyPlantAndEquipmentNet", "property plant and equipment net"),
    ("PropertyPlantAndEquipmentGross", "property plant and equipment gross"),
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
    "property, plant",
    "ppne",
    "pp&e",
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
HTML_TABLE_BLOCK_LIMIT = 40
HTML_TABLE_ROW_LIMIT = 36
HTML_TABLE_CELL_CHARS = 240


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
    target_candidates = _target_document_binding_candidates(text, goal=goal, terms=terms)
    ranked_candidates = (
        _ranked_structured_line_candidates(
            text,
            terms,
            query=goal.query,
            required_terms=_topic_anchor_terms(goal.query) if text_mode in _scholarly_text_modes() else None,
        )
        if text_mode in STRUCTURED_TEXT_MODES
        else _ranked_span_candidates(text, terms)
    )
    candidates = _dedupe_candidate_windows([*target_candidates, *ranked_candidates])
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
                    **({"target_document_binding": candidate["target_document_binding"]} if candidate.get("target_document_binding") else {}),
                    **({"target_statement": candidate["target_statement"]} if candidate.get("target_statement") else {}),
                    **({"target_line_item": candidate["target_line_item"]} if candidate.get("target_line_item") else {}),
                    **({"target_slot": candidate["target_slot"]} if candidate.get("target_slot") else {}),
                    **({"target_period": candidate["target_period"]} if candidate.get("target_period") else {}),
                },
            )
        )
        if len(spans) >= goal.max_spans_per_document:
            break
    return spans


def _dedupe_candidate_windows(candidates: list[dict]) -> list[dict]:
    seen: set[tuple[object, ...]] = set()
    result: list[dict] = []
    for candidate in sorted(
        candidates,
        key=lambda item: (
            0 if item.get("target_document_binding") or item.get("target_slot") or item.get("target_line_item") else 1,
            -float(item.get("structured_summary_bonus") or 0.0),
            -float(item.get("structured_finance_bonus") or 0.0),
            -float(item.get("score") or 0.0),
            int(item.get("start_offset") or 0),
            int(item.get("end_offset") or 0),
        ),
    ):
        start = int(candidate.get("start_offset") or 0)
        end = int(candidate.get("end_offset") or start)
        coarse_key = _coarse_window_key(start, end)
        target_key = str(candidate.get("target_slot") or candidate.get("target_line_item") or "")
        key: tuple[object, ...] = (*coarse_key, target_key) if target_key else coarse_key
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
    return _prioritize_target_slot_diversity(result)


def _prioritize_target_slot_diversity(candidates: list[dict]) -> list[dict]:
    target_candidates = [item for item in candidates if item.get("target_slot")]
    if len(target_candidates) < 2:
        return candidates
    remaining = list(candidates)
    prioritized: list[dict] = []
    emitted_ids: set[int] = set()
    target_slots = []
    for item in target_candidates:
        slot = str(item.get("target_slot") or "")
        if slot and slot not in target_slots:
            target_slots.append(slot)
    while target_slots:
        emitted_in_pass = False
        for slot in list(target_slots):
            match = next(
                (
                    item
                    for item in remaining
                    if id(item) not in emitted_ids and str(item.get("target_slot") or "") == slot
                ),
                None,
            )
            if match is None:
                target_slots.remove(slot)
                continue
            prioritized.append(match)
            emitted_ids.add(id(match))
            emitted_in_pass = True
        if not emitted_in_pass:
            break
        if len(prioritized) >= len(candidates):
            break
    prioritized.extend(item for item in candidates if id(item) not in emitted_ids)
    return prioritized


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
        text, diagnostics = _extract_pdf_text_with_diagnostics(
            body,
            limit=_readable_text_limit_for_document(document),
        )
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
        text, diagnostics = _extract_html_readable_text_with_diagnostics(
            body,
            limit=_readable_text_limit_for_document(document),
            document=document,
            goal=goal,
        )
        return text, str(diagnostics.get("parser_used") or "html_readable_text"), diagnostics
    return _normalize_span(body[: _readable_text_limit_for_document(document)]), "plain_text", {}


def _readable_text_limit_for_document(document: FetchedDocument) -> int:
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    source_metadata = metadata.get("source_metadata") if isinstance(metadata.get("source_metadata"), dict) else {}
    if isinstance(metadata.get("target_document_binding"), dict):
        return SEC_FILING_TEXT_LIMIT
    if bool(source_metadata.get("explicit_source_url")):
        return SEC_FILING_TEXT_LIMIT
    if str(source_metadata.get("source_family") or "").lower() in {"company_filing", "regulatory_filing"}:
        return SEC_FILING_TEXT_LIMIT
    source_kind = _document_source_kind(document)
    if source_kind in {"sec_complete_submission_text", "sec_primary_filing_document", "sec_exhibit_document"}:
        return SEC_FILING_TEXT_LIMIT
    return READABLE_TEXT_LIMIT


def _ranked_span_candidates(text: str, terms: list[str]) -> list[dict]:
    lower = text.lower()
    candidates: list[dict] = []
    seen_windows: set[tuple[int, int]] = set()
    search_terms = _ranked_span_search_terms(terms)
    transaction_intent = _terms_have_transaction_intent(terms)
    for term in search_terms:
        for index in _term_positions(lower, term)[:RANKED_SPAN_POSITIONS_PER_TERM_LIMIT]:
            window_start = max(0, index - SPAN_BEFORE_CHARS)
            window_after_chars = _span_after_chars_for_anchor(text, index=index, term=term)
            window_end = min(len(text), index + len(term) + window_after_chars)
            key = _coarse_window_key(window_start, window_end)
            if key not in seen_windows:
                seen_windows.add(key)
                snippet = _normalize_span(text[window_start:window_end])
                matched = [candidate for candidate in terms if _term_in_text(snippet.lower(), candidate)]
                if snippet and matched:
                    bonus = _transaction_amount_span_bonus(snippet, transaction_intent=transaction_intent)
                    structured_finance_bonus = _structured_finance_span_bonus(snippet)
                    candidates.append(
                        {
                            "start_offset": window_start,
                            "end_offset": window_end,
                            "text": snippet,
                            "matched_terms": matched,
                            "score": min(1.0, len(matched) / max(1, len(terms)) + bonus),
                            "structured_finance_bonus": structured_finance_bonus,
                        }
                    )
                    if len(candidates) >= RANKED_SPAN_CANDIDATE_LIMIT:
                        break
        if len(candidates) >= RANKED_SPAN_CANDIDATE_LIMIT:
            break
    return sorted(
        candidates,
        key=lambda item: (
            -float(item.get("structured_finance_bonus") or 0.0),
            -float(item["score"]),
            -len(item["matched_terms"]),
            int(item["start_offset"]),
        ),
    )


def _ranked_span_search_terms(terms: list[str]) -> list[str]:
    return sorted(
        _ordered_unique(terms),
        key=lambda term: (
            _ranked_span_term_priority(term),
            len(term),
            term,
        ),
        reverse=True,
    )[:RANKED_SPAN_TERM_LIMIT]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _ranked_span_term_priority(term: str) -> int:
    normalized = str(term or "").strip().lower()
    priority = 0
    if " " in normalized:
        priority += 6
    if any(char.isdigit() for char in normalized):
        priority += 3
    if any(
        marker in normalized
        for marker in (
            "capital expenditure",
            "property plant",
            "equipment",
            "revenue",
            "net sales",
            "operating cash",
            "total assets",
            "net income",
            "cash flow",
        )
    ):
        priority += 5
    if len(normalized) >= 8:
        priority += 2
    return priority


def _span_after_chars_for_anchor(text: str, *, index: int, term: str) -> int:
    context = str(text or "")[max(0, index - 220) : min(len(text), index + 220)].lower()
    normalized_term = str(term or "").lower()
    if "html_table_" in context or any(
        marker in context or marker in normalized_term
        for marker in (
            "cash flows",
            "cash flow",
            "balance sheet",
            "statement of income",
            "statement of operations",
            "property, plant and equipment",
            "property plant and equipment",
            "total assets",
            "net sales",
            "capital expenditures",
        )
    ):
        return FINANCE_TABLE_SPAN_AFTER_CHARS
    return SPAN_AFTER_CHARS


def _term_positions(text: str, term: str) -> list[int]:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return []
    if _term_requires_token_boundary(normalized):
        return [match.start() for match in re.finditer(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", text)]
    positions: list[int] = []
    start = 0
    while True:
        index = text.find(normalized, start)
        if index < 0:
            break
        positions.append(index)
        start = index + max(1, len(normalized))
    return positions


def _term_in_text(text: str, term: str) -> bool:
    return bool(_term_positions(text, term))


def _term_requires_token_boundary(term: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+", term))


def _target_document_binding_candidates(text: str, *, goal: SearchGoal, terms: list[str]) -> list[dict]:
    binding = _target_document_binding(goal)
    if not binding:
        return []
    structured_companyfacts = _target_structured_companyfacts_candidates(text, goal=goal, binding=binding, terms=terms)
    if structured_companyfacts:
        return structured_companyfacts
    specs = _target_document_evidence_specs(goal=goal, binding=binding)
    if not specs:
        return []
    lower = text.lower()
    candidates: list[dict] = []
    for spec_index, spec in enumerate(specs):
        line_aliases = spec["line_aliases"]
        statement_aliases = spec["statement_aliases"]
        if not line_aliases and not statement_aliases:
            continue
        marker_positions = _target_marker_positions(lower, line_aliases)
        line_item = spec["line_item"]
        if not marker_positions and line_item:
            marker_positions = _target_marker_positions(lower, [line_item])
        for marker, index in marker_positions:
            statement_index = _nearest_preceding_marker(lower, statement_aliases, index)
            if _target_should_use_structured_line(text, index):
                window_start, window_end = _line_bounds(text, index)
            else:
                window_start = max(0, (statement_index if statement_index >= 0 else index) - 900)
                window_end = min(len(text), index + max(900, len(marker) + 700))
            snippet = _normalize_span(text[window_start:window_end])
            if not snippet:
                continue
            snippet_lower = snippet.lower()
            period = spec["period"]
            statement = spec["statement"]
            period_match = bool(period and period in snippet_lower)
            statement_match = not statement_aliases or any(alias in snippet_lower for alias in statement_aliases)
            line_match = any(alias in snippet_lower for alias in line_aliases) or bool(line_item and line_item in snippet_lower)
            if not line_match:
                continue
            matched = [candidate for candidate in terms if candidate in snippet_lower]
            for alias in [*line_aliases, *statement_aliases, period, spec["slot_name"]]:
                if alias and alias in snippet_lower and alias not in matched:
                    matched.append(alias)
            score = 0.72
            if period_match:
                score += 0.12
            if statement_match:
                score += 0.10
            if line_match:
                score += 0.08
            score += max(0.0, 0.04 - spec_index * 0.002)
            candidates.append(
                {
                    "start_offset": window_start,
                    "end_offset": window_end,
                    "text": snippet,
                    "matched_terms": matched,
                    "score": min(1.0, score),
                    "target_document_binding": binding,
                    "target_statement": statement,
                    "target_line_item": line_item or spec["slot_name"],
                    "target_period": period,
                    "target_slot": spec["slot_name"],
                }
            )
    return candidates


def _target_structured_companyfacts_candidates(
    text: str,
    *,
    goal: SearchGoal,
    binding: JsonObject,
    terms: list[str],
) -> list[dict]:
    if "sec companyfacts official" not in text.lower():
        return []
    intent_text = " ".join(
        part
        for part in (
            goal.query,
            _metadata_intent_text(goal.metadata),
        )
        if part
    )
    target_years = _companyfacts_target_years(intent_text)
    if not target_years and binding.get("doc_period"):
        try:
            target_years = {int(str(binding.get("doc_period")))}
        except ValueError:
            target_years = set()
    target_metrics = _companyfacts_query_priority_metrics(intent_text)
    if not target_metrics:
        target_metrics = _companyfacts_target_binding_metrics(binding)
    if not target_years or not target_metrics:
        return []
    target_accession = _target_binding_accession(binding)
    metric_order = {metric: index for index, metric in enumerate(target_metrics)}
    candidates: list[tuple[tuple[int, int, int, int, str], dict]] = []
    offset = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            offset += len(line) + 1
            continue
        lower = stripped.lower()
        if "sec companyfacts official financial statement" not in lower:
            offset += len(line) + 1
            continue
        metric = _structured_line_value(lower, "metric")
        if metric not in metric_order:
            offset += len(line) + 1
            continue
        year = _structured_line_int_value(lower, "period_fy")
        if year not in target_years:
            offset += len(line) + 1
            continue
        line_accession = _structured_line_value(lower, "accn").replace("-", "")
        exact_accession = bool(target_accession and line_accession == target_accession)
        form = _structured_line_value(lower, "form").replace("-", "")
        target_form = str(binding.get("doc_type") or "").lower().replace("-", "")
        exact_form = bool(target_form and form == target_form)
        matched = [candidate for candidate in terms if candidate in lower]
        for marker in (metric, str(year), "companyfacts", "sec_xbrl_companyfacts"):
            if marker and marker not in matched:
                matched.append(marker)
        intent_score = finance_metric_intent_score(stripped, query=intent_text)
        candidate = {
            "start_offset": offset,
            "end_offset": offset + len(line),
            "text": _normalize_span(f"{text.splitlines()[0]} {stripped}"),
            "matched_terms": matched,
            "score": 1.0,
            "target_document_binding": binding,
            "target_period": str(year),
            "target_line_item": metric,
        }
        priority = (
            metric_order.get(metric, 999),
            -intent_score,
            0 if exact_accession else 1,
            0 if exact_form else 1,
            offset,
            stripped,
        )
        candidates.append((priority, candidate))
        offset += len(line) + 1
    return [candidate for _priority, candidate in sorted(candidates, key=lambda item: item[0])[:32]]


STRUCTURED_LINE_KEYS = (
    "entityname",
    "ticker",
    "cik",
    "taxonomy",
    "concept",
    "metric",
    "label",
    "unit",
    "period_fy",
    "period",
    "fy",
    "fp",
    "form",
    "filed",
    "end",
    "start",
    "frame",
    "accn",
    "value",
    "val",
    "scale",
)


def _structured_line_value(line: str, key: str) -> str:
    normalized_key = key.lower()
    match = re.search(rf"(?:^|\s){re.escape(normalized_key)}=", line, flags=re.IGNORECASE)
    if not match:
        return ""
    key_pattern = re.compile(
        r"(?P<key>" + "|".join(re.escape(item) for item in STRUCTURED_LINE_KEYS) + r")=",
        flags=re.IGNORECASE,
    )
    value_start = match.end()
    next_match = key_pattern.search(line, value_start)
    value_end = next_match.start() if next_match else len(line)
    return line[value_start:value_end].strip().strip(",;")


def _structured_line_int_value(line: str, key: str) -> int | None:
    value = _structured_line_value(line, key)
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _target_should_use_structured_line(text: str, index: int) -> bool:
    prefix = text[max(0, index - 240): index + 240].lower()
    return "sec companyfacts" in prefix or "source=sec_xbrl_companyfacts" in prefix


def _line_bounds(text: str, index: int) -> tuple[int, int]:
    start = text.rfind("\n", 0, index)
    end = text.find("\n", index)
    return (0 if start < 0 else start + 1, len(text) if end < 0 else end)


def _target_document_binding(goal: SearchGoal) -> JsonObject:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    binding = metadata.get("target_document_binding")
    if isinstance(binding, dict):
        return dict(binding)
    return {}


def _target_document_evidence_specs(*, goal: SearchGoal, binding: JsonObject) -> list[JsonObject]:
    specs: list[JsonObject] = []

    def add_spec(*, slot_name: str, line_item: str, statement: str, period: str, attributes: list[str]) -> None:
        aliases = _ordered_normalized_terms([
            *_target_line_item_aliases(line_item),
            line_item,
            slot_name.replace("_", " "),
            *attributes,
        ])
        statements = _ordered_normalized_terms(_target_statement_aliases(statement))
        if not aliases and not statements:
            return
        key = (slot_name, line_item, statement, period, tuple(aliases))
        if any(item.get("_dedupe_key") == key for item in specs):
            return
        specs.append(
            {
                "_dedupe_key": key,
                "slot_name": slot_name,
                "line_item": line_item,
                "statement": statement,
                "period": period,
                "line_aliases": aliases,
                "statement_aliases": statements,
            }
        )

    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    compiled_specs = _compiled_task_evidence_specs(metadata)
    binding_line = _string_value(binding.get("required_line_item")).lower()
    binding_statement = _string_value(binding.get("required_statement")).lower()
    binding_period = _string_value(binding.get("doc_period"))
    if (binding_line or binding_statement) and not compiled_specs:
        add_spec(
            slot_name=_slot_name_from_line_item(binding_line),
            line_item=binding_line,
            statement=binding_statement,
            period=binding_period,
            attributes=[],
        )

    for spec in compiled_specs:
        line_item = _string_value(spec.get("line_item")).lower()
        slot_name = _string_value(spec.get("slot_name")).lower().replace(" ", "_")
        statement = _string_value(spec.get("statement")).lower() or binding_statement
        period = _string_value(spec.get("target_period")) or binding_period
        attributes = [_string_value(item).lower() for item in _object_string_list(spec.get("accepted_attributes"))]
        if not line_item and attributes:
            line_item = attributes[0]
        add_spec(
            slot_name=slot_name or _slot_name_from_line_item(line_item),
            line_item=line_item,
            statement=statement,
            period=period,
            attributes=attributes,
        )
    for item in specs:
        item.pop("_dedupe_key", None)
    return specs[:24]


def _compiled_task_evidence_specs(metadata: object) -> list[JsonObject]:
    if not isinstance(metadata, dict):
        return []
    hint = metadata.get("compiled_task_hint")
    if not isinstance(hint, dict):
        return []
    specs = hint.get("evidence_specs")
    if not isinstance(specs, list):
        return []
    return [dict(item) for item in specs if isinstance(item, dict)]


def _object_string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _string_value(item)
        if text:
            result.append(text)
    return result


def _ordered_normalized_terms(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_span(str(value or "").lower().replace("_", " "))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _slot_name_from_line_item(line_item: str) -> str:
    normalized = _normalize_span(str(line_item or "").lower().replace("&", "and"))
    if not normalized:
        return ""
    if "property plant and equipment" in normalized and "net" in normalized:
        return "property_plant_and_equipment_net"
    if "capital expenditure" in normalized or "capex" in normalized or "purchases of property" in normalized:
        return "capital_expenditures"
    if "operating cash flow" in normalized or "operating activities" in normalized:
        return "operating_cash_flow"
    if "revenue" in normalized or "sales" in normalized:
        return "revenue"
    if normalized == "assets" or "total assets" in normalized:
        return "assets"
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _target_line_item_aliases(line_item: str) -> list[str]:
    normalized = line_item.lower().strip()
    if normalized in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        return [
            "property, plant and equipment, net",
            "property plant and equipment net",
            "property, plant and equipment net",
            "property and equipment, net",
            "property and equipment net",
            "net property, plant and equipment",
            "net property plant and equipment",
            "net property and equipment",
            "net pp&e",
            "net ppe",
            "net ppne",
            "ppne",
        ]
    if normalized == "capital expenditures":
        return [
            "purchases of property, plant and equipment",
            "purchases of property plant and equipment",
            "payments to acquire property, plant and equipment",
            "payments to acquire property plant and equipment",
            "property, plant and equipment",
            "property plant and equipment",
            "property and equipment",
            "capital expenditures",
            "capital expenditure",
            "capex",
            "pp&e",
        ]
    if normalized == "net income":
        return ["net income", "net earnings", "net income attributable", "net loss"]
    if normalized == "revenue":
        return ["revenue", "revenues", "net sales", "net revenues", "sales"]
    return [normalized] if normalized else []


def _target_statement_aliases(statement: str) -> list[str]:
    normalized = statement.lower().strip()
    if normalized == "cash_flow_statement":
        return [
            "consolidated statement of cash flows",
            "statement of cash flows",
            "statements of cash flows",
            "cash flows from investing activities",
            "cash flows",
        ]
    if normalized == "income_statement":
        return [
            "consolidated statement of income",
            "consolidated statements of income",
            "statement of income",
            "statements of income",
            "consolidated statement of operations",
            "consolidated statements of operations",
            "statement of operations",
            "statements of operations",
            "income statement",
            "income statements",
        ]
    if normalized == "balance_sheet":
        return ["consolidated balance sheet", "balance sheet", "assets", "liabilities"]
    if normalized == "non_gaap_reconciliation":
        return ["reconciliation", "non-gaap", "non gaap"]
    return [normalized] if normalized else []


def _target_marker_positions(lower: str, markers: list[str]) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for marker in markers:
        if not marker:
            continue
        start = 0
        while True:
            index = lower.find(marker, start)
            if index < 0:
                break
            key = (marker, index)
            if key not in seen:
                seen.add(key)
                result.append((marker, index))
            start = index + max(1, len(marker))
    return sorted(result, key=lambda item: item[1])


def _nearest_preceding_marker(lower: str, markers: list[str], index: int) -> int:
    best = -1
    for marker in markers:
        pos = lower.rfind(marker, 0, index)
        if pos > best:
            best = pos
    return best


def _terms_have_transaction_intent(terms: list[str]) -> bool:
    return any(
        term in {"acquisition", "acquire", "merger", "transaction", "deal", "consideration", "purchase"}
        for term in terms
    )


def _transaction_amount_span_bonus(snippet: str, *, transaction_intent: bool) -> float:
    if not transaction_intent:
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


def _structured_finance_span_bonus(snippet: str) -> float:
    normalized = str(snippet or "").lower()
    if "html_sentence_fact_" in normalized:
        return 1.0
    if "html_table_fact_" in normalized:
        return 0.7
    if "sec companyfacts official financial statement" in normalized:
        return 0.7
    if "sec companyfacts annual financial summary" in normalized:
        return 0.6
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
            -float(item.get("structured_summary_bonus") or 0.0),
            -float(item["score"]),
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
    lines = []
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
            source_kind = value.strip()
            if source_kind == "direct_url" and _looks_like_sec_complete_submission_text_url(document.uri):
                return "sec_complete_submission_text"
            return source_kind
    if _looks_like_sec_complete_submission_text_url(document.uri):
        return "sec_complete_submission_text"
    return ""


def _looks_like_sec_complete_submission_text_url(uri: object) -> bool:
    text = str(uri or "").strip()
    if not text:
        return False
    return bool(
        re.search(
            r"https?://(?:www\.)?sec\.gov/Archives/edgar/data/\d+/\d+/\d{10}-\d{2}-\d{6}\.txt(?:[?#].*)?$",
            text,
            re.IGNORECASE,
        )
    )


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
    source_kind = _document_source_kind(document).lower()
    if (
        "data.sec.gov/api/xbrl/companyfacts/" in uri
        or "data.sec.gov/api/xbrl/companyconcept/" in uri
        or source_kind in {"sec_companyfacts_json", "sec_companyconcept_json"}
        or "sec companyfacts" in title
        or "sec companyconcept" in title
    ):
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
    if isinstance(payload.get("units"), dict) and payload.get("tag"):
        return _extract_sec_companyconcept_readable_text(payload, goal=goal)
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
    lines.extend(_companyfacts_target_binding_lines(facts, entity_name=entity_name, cik=cik, goal=goal))
    lines.extend(_companyfacts_query_focus_lines(facts, entity_name=entity_name, cik=cik, goal=goal))
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


def _extract_sec_companyconcept_readable_text(payload: dict, *, goal: SearchGoal | None = None) -> str:
    concept = _structured_value(payload.get("tag") or "")
    if not concept:
        return ""
    label = _structured_value(payload.get("label") or concept)
    metric = _companyfacts_metric_for_concept(concept=concept, label=label)
    if not metric:
        return ""
    entity_name = _structured_value(payload.get("entityName") or "")
    cik = _structured_value(payload.get("cik") or "")
    taxonomy_name = _structured_value(payload.get("taxonomy") or "us-gaap") or "us-gaap"
    units = payload.get("units")
    if not isinstance(units, dict):
        return ""
    intent_text = " ".join(
        part
        for part in (
            goal.query if goal is not None else "",
            _metadata_intent_text(goal.metadata) if goal is not None else "",
        )
        if part
    )
    target_years = _companyfacts_target_years(intent_text)
    lines = [
        _normalize_span(
            f"SEC companyfacts official financial statements entityName={entity_name} cik={cik} source=SEC_XBRL_companyfacts"
        )
    ]
    for unit, records in units.items():
        if not isinstance(records, list):
            continue
        for record in _recent_companyfacts_records(records):
            if not isinstance(record, dict):
                continue
            year = _companyfacts_year(record)
            if target_years and year not in target_years:
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


def _companyfacts_target_binding_lines(
    facts: dict,
    *,
    entity_name: str,
    cik: str,
    goal: SearchGoal | None = None,
) -> list[str]:
    binding = _target_document_binding(goal) if goal is not None else {}
    if not binding:
        return []
    intent_text = " ".join(
        part
        for part in (
            goal.query if goal is not None else "",
            _metadata_intent_text(goal.metadata) if goal is not None else "",
        )
        if part
    )
    target_years = _companyfacts_target_years(intent_text)
    target_metrics = _companyfacts_query_priority_metrics(intent_text)
    if not target_metrics:
        target_metrics = _companyfacts_target_binding_metrics(binding)
    if not target_years and binding.get("doc_period"):
        try:
            target_years = {int(str(binding.get("doc_period")))}
        except ValueError:
            target_years = set()
    if not target_metrics or not target_years:
        return []
    target_doc_period = None
    try:
        target_doc_period = int(str(binding.get("doc_period") or ""))
    except ValueError:
        target_doc_period = None
    target_accession = _target_binding_accession(binding)
    metric_order = {metric: index for index, metric in enumerate(target_metrics)}
    candidates: list[tuple[tuple[int, int, int, int, float, str], str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for taxonomy_name in ("us-gaap", "ifrs-full"):
        taxonomy = facts.get(taxonomy_name)
        if not isinstance(taxonomy, dict):
            continue
        for concept, metric in _companyfacts_concept_specs(taxonomy):
            if metric not in target_metrics:
                continue
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
                for record in _recent_companyfacts_records(records):
                    if not isinstance(record, dict) or _companyfacts_period_rank(record) < 3:
                        continue
                    year = _companyfacts_year(record)
                    if year not in target_years:
                        continue
                    key = (
                        concept,
                        str(record.get("start") or ""),
                        str(record.get("end") or ""),
                        str(record.get("accn") or ""),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    record_accession = str(record.get("accn") or "").replace("-", "")
                    record_fy = record.get("fy")
                    exact_target_fy = (
                        isinstance(record_fy, int)
                        and target_doc_period is not None
                        and int(record_fy) == target_doc_period
                    )
                    exact_accession = bool(target_accession and record_accession == target_accession)
                    target_form = str(binding.get("doc_type") or "").upper().replace(" ", "").replace("-", "")
                    record_form = str(record.get("form") or "").upper().replace(" ", "").replace("-", "")
                    line = _companyfacts_record_line(
                        entity_name=entity_name,
                        cik=cik,
                        taxonomy=taxonomy_name,
                        concept=concept,
                        metric=metric,
                        label=label,
                        unit=_structured_value(unit),
                        record=record,
                    )
                    priority = (
                        metric_order.get(metric, 999),
                        0 if exact_accession else 1,
                        0 if exact_target_fy else 1,
                        0 if target_form and target_form == record_form else 1,
                        -finance_metric_intent_score(line, query=intent_text),
                        str(record.get("filed") or ""),
                    )
                    candidates.append((priority, line))
    return [line for _priority, line in sorted(candidates, key=lambda item: item[0])[:24]]


def _companyfacts_query_focus_lines(
    facts: dict,
    *,
    entity_name: str,
    cik: str,
    goal: SearchGoal | None = None,
) -> list[str]:
    if goal is None:
        return []
    intent_text = " ".join(
        part
        for part in (
            goal.query,
            _metadata_intent_text(goal.metadata),
        )
        if part
    )
    target_metrics = _companyfacts_query_priority_metrics(intent_text)
    if not target_metrics:
        return []
    target_years = _companyfacts_target_years(intent_text)
    metric_order = {metric: index for index, metric in enumerate(target_metrics)}
    candidates: list[tuple[tuple[int, int, float, int, int, int, str, str], str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for taxonomy_name in ("us-gaap", "ifrs-full"):
        taxonomy = facts.get(taxonomy_name)
        if not isinstance(taxonomy, dict):
            continue
        for concept, metric in _companyfacts_concept_specs(taxonomy):
            if metric not in metric_order:
                continue
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
                emitted_for_concept = 0
                for record in _recent_companyfacts_records(records):
                    if not isinstance(record, dict) or _companyfacts_period_rank(record) < 3:
                        continue
                    year = _companyfacts_year(record)
                    if target_years and year not in target_years:
                        continue
                    key = (
                        taxonomy_name,
                        concept,
                        str(record.get("start") or ""),
                        str(record.get("end") or ""),
                        str(record.get("accn") or ""),
                    )
                    if key in seen:
                        continue
                    seen.add(key)
                    line = _companyfacts_record_line(
                        entity_name=entity_name,
                        cik=cik,
                        taxonomy=taxonomy_name,
                        concept=concept,
                        metric=metric,
                        label=label,
                        unit=_structured_value(unit),
                        record=record,
                    )
                    intent_score = finance_metric_intent_score(line, query=intent_text)
                    candidates.append(
                        (
                            (
                                metric_order.get(metric, 999),
                                0 if target_years and year in target_years else 1,
                                -intent_score,
                                -_companyfacts_period_rank(record),
                                -_companyfacts_duration_days(record),
                                -(year or 0),
                                str(record.get("filed") or ""),
                                concept.lower(),
                            ),
                            line,
                        )
                    )
                    emitted_for_concept += 1
                    if not target_years and emitted_for_concept >= 2:
                        break
    return [line for _priority, line in sorted(candidates, key=lambda item: item[0])[:36]]


def _target_binding_accession(binding: JsonObject) -> str:
    doc_link = str(binding.get("doc_link") or "")
    match = re.search(r"/Archives/edgar/data/\d+/(\d{18})/", doc_link, flags=re.IGNORECASE)
    if match:
        return match.group(1)
    match = re.search(r"\b(\d{10})-?(\d{2})-?(\d{6})\b", doc_link)
    if match:
        return "".join(match.groups())
    return ""


def _companyfacts_target_binding_metrics(binding: JsonObject) -> tuple[str, ...]:
    line_item = str(binding.get("required_line_item") or "").strip().lower()
    statement = str(binding.get("required_statement") or "").strip().lower()
    metrics: list[str] = []

    def add(metric: str) -> None:
        if metric not in metrics:
            metrics.append(metric)

    if line_item in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        add("property plant and equipment net")
    if line_item == "capital expenditures" or any(
        marker in line_item for marker in ("capital expenditure", "capex", "payments to acquire", "purchases of property")
    ):
        add("capital expenditures")
    if line_item in {"revenue", "revenues"} or "revenue" in line_item or "sales" in line_item:
        add("revenue")
        add("net sales")
    if line_item == "net income" or "net income" in line_item:
        add("net income")
    if "cash flow" in statement and not metrics:
        add("operating cash flow")
        add("capital expenditures")
    return tuple(metrics)


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


def _companyfacts_metric_for_concept(*, concept: str, label: str) -> str | None:
    for known_concept, metric in SEC_COMPANYFACTS_CONCEPTS:
        if concept == known_concept:
            return metric
    return _companyfacts_dynamic_metric(concept=concept, label=label)


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
    if "revenue" in lower and (
        any(marker in lower for marker in ("contract liability", "deferred revenue", "remaining performance obligation"))
        or any(marker in compact for marker in ("contractwithcustomerliability", "remainingperformanceobligation"))
    ):
        return None
    if "capitalexpenditure" in compact or ("capital" in lower and "expenditure" in lower):
        return "capital expenditures"
    if (
        "researchanddevelopmentexpense" in compact
        or "research and development expense" in lower
        or "research and development" in lower
        or "r&d" in lower
    ):
        return "research and development expense"
    if (
        "propertyplantandequipmentnet" in compact
        or "property plant and equipment, net" in lower
        or "property plant and equipment net" in lower
        or "net property plant and equipment" in lower
    ):
        return "property plant and equipment net"
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
    if "taxespaid" in compact or "incometaxespaid" in compact:
        return None
    if "incometax" in compact or "income tax" in lower:
        return "tax"
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
        "gross profit",
        "property plant and equipment net",
        "research and development expense",
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
    intent_text = " ".join(
        part
        for part in (
            goal.query if goal is not None else "",
            _metadata_intent_text(goal.metadata) if goal is not None else "",
        )
        if part
    )
    target_years = _companyfacts_target_years(intent_text)
    query_priority_metrics = _companyfacts_query_priority_metrics(intent_text)
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

    if "capital intensive" in normalized or "capital-intensive" in normalized or "capital intensity" in normalized:
        add("revenue")
        add("operating cash flow")
        add("capital expenditures")
        add("property plant and equipment net")
        add("assets")
        add("net income")
    if "debt-to-equity" in normalized or "debt to equity" in normalized or "debt/equity" in normalized:
        add("liabilities")
        add("shareholders equity")
        add("assets")
        add("debt")
    if any(
        alias in normalized
        for alias in (
            "net ppne",
            "ppne",
            "net ppe",
            "net pp&e",
            "propertyplantandequipmentnet",
            "property, plant and equipment, net",
            "property plant and equipment net",
            "net property plant and equipment",
        )
    ) or ("property plant and equipment" in normalized and "balance sheet" in normalized):
        add("property plant and equipment net")
    if any(
        alias in normalized
        for alias in (
            "capital expenditure",
            "capital expenditures",
            "capex",
            "purchases of property",
            "payments to acquire property",
        )
    ):
        add("capital expenditures")
    if any(alias in normalized for alias in ("operating cash flow", "cash flow from operating", "operating activities")):
        add("operating cash flow")
    if "net interest income" in normalized:
        add("net interest income")
    if "family of apps" in normalized or "foa" in normalized:
        add("family of apps revenue")
        add("segment revenue")
        add("segment revenue from external customers")
        add("revenue")
    if "reality labs" in normalized:
        add("reality labs revenue")
        add("segment revenue")
        add("segment revenue from external customers")
        add("revenue")
    if "segment revenue" in normalized or ("segment" in normalized and "revenue" in normalized):
        add("segment revenue")
        add("segment revenue from external customers")
        add("revenue")
    if (
        ("cloud" in normalized or "ai" in normalized or "artificial intelligence" in normalized)
        and ("infrastructure" in normalized or "investment" in normalized or "capex" in normalized)
    ):
        add("cloud and AI infrastructure investment")
        add("capital expenditures")
        add("property plant and equipment net")
    if (
        "research and development" in normalized
        or "r&d" in normalized
        or "rd spending" in normalized
        or "research development" in normalized
    ):
        add("research and development expense")
    if "gross margin" in normalized or "gross profit" in normalized:
        add("gross profit")
        add("cost of revenue")
        add("cost of goods sold")
        add("cost of sales")
        add("revenue")
    if "operating margin" in normalized:
        add("operating income")
        add("revenue")
    if "net profit margin" in normalized or "net margin" in normalized:
        add("net income")
        add("revenue")
    if any(alias in normalized for alias in ("total assets", "assets")):
        add("assets")
    if "sales and other operating revenues" in normalized:
        add("sales and other operating revenues")
    if "total revenues and other income" in normalized:
        add("total revenues and other income")
    if "operating revenues" in normalized or "operating revenue" in normalized:
        add("operating revenues")
    if any(alias in normalized for alias in ("net revenues", "net revenue")):
        add("net revenues")
    if any(alias in normalized for alias in ("total revenues", "total revenue")):
        add("sales and other operating revenues")
        add("total revenues and other income")
        add("operating revenues")
        add("revenue")
    if any(alias in normalized for alias in ("revenue", "revenues", "sales", "net sales")):
        if "net sales" in normalized:
            add("net sales")
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
    period_year = _companyfacts_year(record)
    if period_year is not None:
        parts.append(f"period_fy={_structured_value(period_year)}")
    for key in ("val", "fy", "fp", "form", "filed", "end", "start", "frame", "accn"):
        value = record.get(key)
        if value is None or value == "":
            continue
        if key == "val":
            parts.append(f"value={_structured_value(value)}")
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


def _extract_pdf_text_with_diagnostics(body: str, *, limit: int = READABLE_TEXT_LIMIT) -> tuple[str, JsonObject]:
    failures: list[str] = []
    for parser_name, parser in (
        ("pdf_text_pymupdf", _extract_pdf_text_pymupdf),
        ("pdf_text_pypdf", _extract_pdf_text_pypdf),
        ("pdf_text_pdfminer", _extract_pdf_text_pdfminer),
    ):
        try:
            text, diagnostics = parser(body)
        except Exception as exc:  # pragma: no cover - optional parser failures vary by dependency/version.
            failures.append(f"{parser_name}:{type(exc).__name__}")
            continue
        if text and _pdf_text_quality_too_low(text, body=body, limit=limit):
            failures.append(f"{parser_name}:low_quality_chars={len(text)}")
            continue
        if text:
            return text[:limit], {
                **diagnostics,
                "parser_used": parser_name,
                "chars_extracted": len(text),
                "readable_text_limit": limit,
                "table_like_blocks": _table_like_block_count(text),
                **({"fallback_failures": failures} if failures else {}),
            }
        failures.append(f"{parser_name}:empty")
    fallback = _extract_pdf_text_literals(body, limit=limit)
    return fallback, {
        "parser_used": "pdf_text_literals",
        "pages_extracted": 0,
        "chars_extracted": len(fallback),
        "readable_text_limit": limit,
        "table_like_blocks": _table_like_block_count(fallback),
        "extraction_failure_reason": ";".join(failures) if failures else "optional_pdf_parser_unavailable",
    }


def _pdf_text_quality_too_low(text: str, *, body: str, limit: int) -> bool:
    if len(body or "") < 200_000:
        return False
    if limit <= READABLE_TEXT_LIMIT:
        return False
    return len(str(text or "").strip()) < 10_000


def _extract_pdf_text_pymupdf(body: str) -> tuple[str, JsonObject]:
    try:
        import fitz  # type: ignore
    except Exception as exc:  # pragma: no cover - dependency is optional.
        raise RuntimeError("pymupdf_unavailable") from exc
    data = _pdf_body_bytes(body)
    try:
        fitz.TOOLS.reset_mupdf_warnings()
        fitz.TOOLS.mupdf_display_errors(False)
        fitz.TOOLS.mupdf_display_warnings(False)
    except Exception:
        pass
    document = fitz.open(stream=data, filetype="pdf")
    pieces: list[str] = []
    try:
        for page in document:
            try:
                pieces.append(page.get_text("text") or "")
            except Exception:
                continue
        warnings = ""
        try:
            warnings = str(fitz.TOOLS.mupdf_warnings() or "")
        except Exception:
            warnings = ""
    finally:
        try:
            fitz.TOOLS.mupdf_display_errors(True)
            fitz.TOOLS.mupdf_display_warnings(True)
        except Exception:
            pass
    text = _normalize_span("\n".join(piece for piece in pieces if piece.strip()))
    diagnostics: JsonObject = {
        "pages_extracted": int(getattr(document, "page_count", len(pieces))),
        "parser_library": "PyMuPDF",
    }
    if warnings:
        diagnostics["parser_warning_count"] = len([line for line in warnings.splitlines() if line.strip()])
        diagnostics["parser_warning_preview"] = warnings[:500]
    return text, diagnostics


def _extract_pdf_text_pypdf(body: str) -> tuple[str, JsonObject]:
    library = "pypdf"
    try:
        from pypdf import PdfReader  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader  # type: ignore
            library = "PyPDF2"
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
    return text, {"pages_extracted": len(pieces), "parser_library": library}


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


def _extract_pdf_text_literals(body: str, *, limit: int = READABLE_TEXT_LIMIT) -> str:
    sample = body[:limit]
    pieces = []
    pieces.extend(_pdf_literal_strings(sample))
    pieces.extend(_pdf_hex_strings(sample))
    return _normalize_span(" ".join(pieces)[:limit])


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


def _extract_html_readable_text_with_diagnostics(
    body: str,
    *,
    limit: int = READABLE_TEXT_LIMIT,
    document: FetchedDocument | None = None,
    goal: SearchGoal | None = None,
) -> tuple[str, JsonObject]:
    parser = _ReadableHtmlParser()
    parser.feed(body[:limit])
    parser.close()
    parsed_text = parser.text()
    text_parts: list[str] = []
    sentence_fact_lines = _extract_html_finance_sentence_fact_lines(
        parsed_text,
        body=body[:limit],
        goal=goal,
    )
    if sentence_fact_lines:
        text_parts.append("\nHTML financial sentence facts:\n")
        text_parts.extend(f"{line}\n" for line in sentence_fact_lines)
    table_blocks = _extract_html_table_blocks(body[:limit], goal=goal, document=document)
    if table_blocks:
        text_parts.append("\nHTML table blocks:\n")
        text_parts.extend(f"{line}\n" for line in table_blocks)
    text_parts.append(parsed_text)
    visible_market_snippets = _extract_market_visible_snippets(parsed_text)
    if visible_market_snippets:
        text_parts.append("\nMarket data visible snippets:\n")
        text_parts.extend(f"{line}.\n" for line in visible_market_snippets)
    market_snippets = _extract_market_script_snippets(body[:limit])
    if market_snippets:
        text_parts.append("\nMarket data structured snippets:\n")
        text_parts.extend(f"{line}.\n" for line in market_snippets)
    text = _normalize_span("".join(text_parts))
    return text, {
        "parser_used": "html_readable_text",
        "chars_extracted": len(text),
        "sentence_fact_blocks": len(sentence_fact_lines),
        "table_like_blocks": len(table_blocks),
        "market_visible_snippets": len(visible_market_snippets),
        "market_structured_snippets": len(market_snippets),
        "source_kind": _document_source_kind(document) if document is not None else "",
    }


def _extract_html_readable_text(body: str, *, limit: int = READABLE_TEXT_LIMIT) -> str:
    text, _diagnostics = _extract_html_readable_text_with_diagnostics(body, limit=limit)
    return text


def _extract_html_table_blocks(
    body: str,
    *,
    goal: SearchGoal | None = None,
    document: FetchedDocument | None = None,
) -> list[str]:
    tables = _html_tables(body)
    if not tables:
        return []
    goal_text = " ".join(
        part
        for part in (
            goal.query if goal is not None else "",
            _metadata_intent_text(goal.metadata) if goal is not None else "",
            document.title if document is not None else "",
        )
        if part
    )
    terms = _ordered_normalized_terms([*_terms(goal_text, goal=goal), *_html_table_extra_terms(goal_text)])
    ranked: list[tuple[tuple[int, int, int], list[str]]] = []
    for index, table in enumerate(tables, start=1):
        block = _html_table_block_lines(table, table_index=index)
        if not block:
            continue
        table_text = _normalize_span(" ".join(block)).lower()
        term_hits = sum(1 for term in terms if term and term in table_text)
        numeric_cells = sum(1 for row in table.get("rows", []) for cell in row if _looks_numeric_cell(cell))
        source_kind = _document_source_kind(document) if document is not None else ""
        should_keep = bool(term_hits) or (
            source_kind in {"sec_complete_submission_text", "sec_primary_filing_document", "sec_exhibit_document"}
            and numeric_cells >= 3
            and _looks_like_financial_table_text(table_text)
        )
        if not should_keep:
            continue
        ranked.append(((-term_hits, -numeric_cells, index), block))
    result: list[str] = []
    for _rank, block in sorted(ranked, key=lambda item: item[0])[:HTML_TABLE_BLOCK_LIMIT]:
        result.extend(block)
    return result


HTML_SENTENCE_FACT_METRICS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("net sales", ("net sales",)),
)


def _extract_html_finance_sentence_fact_lines(
    parsed_text: str,
    *,
    body: str,
    goal: SearchGoal | None = None,
) -> list[str]:
    goal_text = " ".join(
        part
        for part in (
            goal.query if goal is not None else "",
            _metadata_intent_text(goal.metadata) if goal is not None else "",
        )
        if part
    )
    focus_metrics = _html_sentence_focus_metrics(goal_text)
    if not focus_metrics:
        return []
    text = _normalize_span(parsed_text)
    if not text:
        return []
    lower = text.lower()
    target_years = _companyfacts_target_years(goal_text)
    document_scale = _html_table_scale(body) or _html_table_scale(text)
    lines: list[str] = []
    seen: set[tuple[str, int, str]] = set()
    for metric, markers in HTML_SENTENCE_FACT_METRICS:
        if metric not in focus_metrics:
            continue
        for marker in markers:
            marker_lower = marker.lower()
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(marker_lower)}(?![a-z0-9])", lower):
                start = max(0, match.start() - 160)
                end = min(len(text), match.end() + 360)
                context = text[start:end]
                if _html_sentence_fact_noise_context(context):
                    continue
                amount = _html_sentence_amount_after_marker(context, marker_offset=match.start() - start)
                if amount is None:
                    continue
                raw_value, scale = amount
                year = _html_sentence_fact_year(context, target_years=target_years)
                if year is None:
                    continue
                fact_scale = scale or document_scale or "actual"
                key = (metric, year, raw_value.replace(",", ""))
                if key in seen:
                    continue
                seen.add(key)
                sentence = _truncate_structured_line(context)
                lines.append(
                    _truncate_structured_line(
                        f"html_sentence_fact_{len(lines) + 1}_{year}: "
                        f"metric={metric} fy={year} value={raw_value} scale={fact_scale} sentence={sentence}"
                    )
                )
                if len(lines) >= 24:
                    return lines
    return lines


def _html_sentence_focus_metrics(goal_text: str) -> set[str]:
    normalized = str(goal_text or "").lower()
    focus: set[str] = set()
    if "net sales" in normalized or ("net" in normalized and "sales" in normalized):
        focus.add("net sales")
    return focus


def _html_sentence_amount_after_marker(context: str, *, marker_offset: int) -> tuple[str, str] | None:
    tail = context[max(0, marker_offset):]
    sentence_end = _html_sentence_boundary(tail)
    if sentence_end > 0:
        tail = tail[:sentence_end]
    if re.search(r"\b(following table|summarizes|reportable segments|merchandise category|disaggregated revenue)\b", tail, re.IGNORECASE):
        return None
    if _html_sentence_fact_noise_context(tail):
        return None
    candidates: list[tuple[int, str, str]] = []
    for match in re.finditer(
        r"(?P<prefix>[$€£¥])?\s*(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<unit>%|million|billion|trillion|thousand|mn|bn|m|b)?",
        tail,
        flags=re.IGNORECASE,
    ):
        raw_number = match.group("number") or ""
        raw_unit = (match.group("unit") or "").lower()
        prefix = match.group("prefix") or ""
        if not raw_number or raw_unit == "%":
            continue
        if _candidate_year_from_column(raw_number) is not None and not prefix and not raw_unit:
            continue
        if not prefix and raw_unit in {"m", "b"} and match.end() < len(tail) and tail[match.end()].isalpha():
            continue
        if not prefix and not raw_unit and _looks_numeric_cell(raw_number) and float(raw_number.replace(",", "")) < 1000:
            continue
        scale = _html_sentence_unit_scale(raw_unit)
        before = tail[max(0, match.start() - 24): match.start()].lower()
        if not re.search(r"\b(to|were|was|totaled|amounted to|amounting to)\s*$", before):
            continue
        candidates.append((match.start(), raw_number, scale))
    if not candidates:
        return None
    _rank, raw_number, scale = sorted(candidates, key=lambda item: item[0])[0]
    return raw_number, scale


def _html_sentence_fact_noise_context(text: str) -> bool:
    normalized = str(text or "").lower()
    return any(
        marker in normalized
        for marker in (
            "reclassified",
            "aocl",
            "hedge",
            "designated hedges",
            "net loss",
            "gain (loss)",
            "pro forma",
            "supplemental pro forma",
            "unaudited",
            "acquisition",
            "acquired assets",
            "associated with the acquired assets",
            "from the acquisition date",
            "transaction-related costs",
            "merger agreement",
            "working interest",
            "higher volumes",
            "production and operating expenses",
            "transportation costs",
            "differentials",
            "earnings decreases",
            "earnings increased",
            "basis points",
        )
    )


def _html_sentence_boundary(text: str) -> int:
    for match in re.finditer(r"[.;]", str(text or "")):
        if match.start() >= 24:
            return match.start() + 1
    return 0


def _html_sentence_unit_scale(unit: str) -> str:
    normalized = str(unit or "").lower()
    if normalized in {"thousand"}:
        return "thousands"
    if normalized in {"million", "mn", "m"}:
        return "millions"
    if normalized in {"billion", "bn", "b"}:
        return "billions"
    if normalized == "trillion":
        return "trillions"
    return ""


def _html_sentence_fact_year(context: str, *, target_years: set[int]) -> int | None:
    if len(target_years) == 1:
        return next(iter(target_years))
    years = [int(match.group(1)) for match in re.finditer(r"\b((?:19|20)\d{2})\b", context)]
    if not years:
        return None
    for year in reversed(years):
        if not target_years or year in target_years:
            return year
    return years[-1]


def _html_table_extra_terms(goal_text: str) -> list[str]:
    text = str(goal_text or "").lower()
    extras: list[str] = []
    for marker in (
        "segment",
        "business segment",
        "organic",
        "acquisition",
        "divestiture",
        "net sales",
        "sales",
        "revenue",
        "operating",
        "margin",
        "liquidity",
        "quick ratio",
        "cash",
        "inventory",
        "debt securities",
        "trading symbol",
        "exchange",
    ):
        if marker in text:
            extras.append(marker)
    return extras


def _html_table_block_lines(table: JsonObject, *, table_index: int) -> list[str]:
    rows = table.get("rows")
    if not isinstance(rows, list) or not rows:
        return []
    heading = _normalize_span(str(table.get("heading") or ""))
    scale = _html_table_scale(" ".join([heading, *(" ".join(row) for row in rows if isinstance(row, list))]))
    lines: list[str] = [f"html_table_{table_index}: heading={heading or 'unknown'}" + (f" scale={scale}" if scale else "")]
    header = _html_table_header(rows)
    facts = _html_table_candidate_fact_lines(rows, header=header, scale=scale, table_index=table_index)
    if facts:
        lines.extend(facts)
    for row_index, row in enumerate(rows[:HTML_TABLE_ROW_LIMIT], start=1):
        if not isinstance(row, list) or not any(str(cell).strip() for cell in row):
            continue
        cells = [_truncate_html_cell(cell) for cell in row]
        if header and len(cells) == len(header) and row_index > 1:
            rendered = " ".join(f"{_structured_key(header[col_index])}={cells[col_index]}" for col_index in range(len(cells)))
        else:
            rendered = " | ".join(cells)
        lines.append(_truncate_structured_line(f"html_table_{table_index}_row_{row_index}: {rendered}"))
    return lines


def _html_table_header(rows: list[object]) -> list[str]:
    for row in rows[:4]:
        if not isinstance(row, list) or len(row) < 2:
            continue
        non_numeric = sum(1 for cell in row if not _looks_numeric_cell(str(cell)))
        year_like = sum(1 for cell in row if _candidate_year_from_column(str(cell)) is not None)
        if year_like or non_numeric >= max(1, len(row) // 2):
            return [_normalize_span(str(cell)) or f"column_{index + 1}" for index, cell in enumerate(row)]
    return []


def _html_table_candidate_fact_lines(
    rows: list[object],
    *,
    header: list[str],
    scale: str,
    table_index: int,
) -> list[str]:
    if not header or len(header) < 2:
        return []
    year_columns = [(index, _candidate_year_from_column(header[index])) for index in range(1, len(header))]
    year_columns = [(index, year) for index, year in year_columns if year is not None]
    if not year_columns:
        return []
    lines: list[str] = []
    for row_index, row in enumerate(rows[1:HTML_TABLE_ROW_LIMIT], start=2):
        if not isinstance(row, list) or len(row) < 2:
            continue
        metric = _normalize_span(str(row[0] or ""))
        if not metric or _looks_numeric_cell(metric):
            continue
        for col_index, year in year_columns:
            if col_index >= len(row):
                continue
            value = _normalize_html_numeric_cell(str(row[col_index] or ""))
            if not value:
                continue
            parts = [
                f"html_table_fact_{table_index}_{row_index}_{year}:",
                f"metric={metric}",
                f"fy={year}",
                f"value={value}",
            ]
            if scale:
                parts.append(f"scale={scale}")
            lines.append(_truncate_structured_line(" ".join(parts)))
    return lines[:HTML_TABLE_ROW_LIMIT]


def _html_table_scale(text: str) -> str:
    normalized = str(text or "").lower()
    if "in millions" in normalized or "(millions" in normalized or "dollars in millions" in normalized:
        return "millions"
    if "in billions" in normalized or "(billions" in normalized or "dollars in billions" in normalized:
        return "billions"
    if "in thousands" in normalized or "(thousands" in normalized or "dollars in thousands" in normalized:
        return "thousands"
    return ""


def _looks_like_financial_table_text(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "net sales",
            "revenue",
            "cash flows",
            "balance sheet",
            "assets",
            "liabilities",
            "operating income",
            "operating margin",
            "business segment",
            "segment",
            "organic",
            "acquisition",
            "divestiture",
            "trading symbol",
            "exchange",
        )
    )


def _looks_numeric_cell(value: object) -> bool:
    text = _normalize_html_numeric_cell(str(value or ""))
    return bool(text)


def _candidate_year_from_column(value: str) -> int | None:
    text = str(value or "").strip()
    match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if not match:
        return None
    return int(match.group(1))


def _normalize_html_numeric_cell(value: str) -> str:
    text = _normalize_span(str(value or ""))
    text = text.replace("$", "").replace("%", "").strip()
    if not text or text in {"-", "--", "—"}:
        return ""
    text = re.sub(r"^\(\s*(-?\d[\d,]*(?:\.\d+)?)\s*\)$", r"(\1)", text)
    if re.fullmatch(r"\(?-?\d[\d,]*(?:\.\d+)?\)?", text):
        return text
    return ""


def _truncate_html_cell(value: object) -> str:
    text = _normalize_span(str(value or ""))
    if len(text) <= HTML_TABLE_CELL_CHARS:
        return text
    return text[: HTML_TABLE_CELL_CHARS - 3] + "..."


def _html_tables(body: str) -> list[JsonObject]:
    tables: list[JsonObject] = []
    for match in re.finditer(r"<table\b[^>]*>.*?</table\s*>", body, flags=re.IGNORECASE | re.DOTALL):
        fragment = match.group(0)
        rows = _html_table_rows(fragment)
        if not rows:
            continue
        context = _html_fragment_text(body[max(0, match.start() - 1800) : match.start()])
        heading = _html_table_heading(context)
        tables.append({"heading": heading, "rows": rows})
    return tables


def _html_table_rows(fragment: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for row_match in re.finditer(r"<tr\b[^>]*>(.*?)</tr\s*>", fragment, flags=re.IGNORECASE | re.DOTALL):
        row_html = row_match.group(1)
        cells = [
            _html_fragment_text(cell_match.group(1))
            for cell_match in re.finditer(r"<t[dh]\b[^>]*>(.*?)</t[dh]\s*>", row_html, flags=re.IGNORECASE | re.DOTALL)
        ]
        cleaned = [_normalize_span(cell) for cell in cells]
        if any(cleaned):
            rows.append(cleaned)
    return rows


def _html_fragment_text(fragment: str) -> str:
    parser = _ReadableHtmlParser()
    try:
        parser.feed(fragment)
        parser.close()
    except Exception:
        text = re.sub(r"<[^>]+>", " ", fragment)
        return _normalize_span(html.unescape(text))
    return _normalize_span(parser.text())


def _html_table_heading(context: str) -> str:
    normalized = _normalize_span(context)
    if not normalized:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+|\n+", normalized)
    candidates = [item.strip() for item in sentences if item.strip()]
    if not candidates:
        return normalized[-320:]
    return _normalize_span(" ".join(candidates[-3:]))[-420:]


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
        normalized = _normalize_query_term(term)
        if not normalized or normalized in seen or _low_signal_query_term(normalized):
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


def _normalize_query_term(term: str) -> str:
    raw = str(term or "").lower().replace("-", " ").replace("_", " ")
    parts: list[str] = []
    for piece in raw.split():
        cleaned = "".join(
            char
            for char in piece.strip()
            if char.isalnum() or char in {"%", "$", "/", "&"} or "\u4e00" <= char <= "\u9fff"
        )
        if cleaned:
            parts.append(cleaned)
    return " ".join(parts)


def _low_signal_query_term(term: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return True
    if " " in normalized:
        return False
    if normalized in LOW_SIGNAL_QUERY_TERMS or normalized in QUERY_FACET_ALIASES:
        return True
    if len(normalized) < 3 and not any(char.isdigit() for char in normalized):
        return True
    return False


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
    binding = metadata.get("target_document_binding")
    if isinstance(binding, dict):
        for key in (
            "company",
            "doc_name",
            "doc_type",
            "doc_period",
            "required_statement",
            "required_line_item",
            "doc_host",
            "doc_path_tail",
        ):
            value = binding.get(key)
            if isinstance(value, str):
                parts.append(value)
    slot_frame = metadata.get("slot_frame")
    if isinstance(slot_frame, dict):
        for item in slot_frame.get("missing_slots") or []:
            if isinstance(item, str):
                parts.append(item)
    compiled_hint = metadata.get("compiled_task_hint")
    if isinstance(compiled_hint, dict):
        task_spec = compiled_hint.get("task_spec")
        if isinstance(task_spec, dict):
            for key in ("task_type",):
                value = task_spec.get(key)
                if isinstance(value, str):
                    parts.append(value)
            for key in ("target_entities", "target_periods", "success_criteria"):
                for item in task_spec.get(key) or []:
                    if isinstance(item, str):
                        parts.append(item)
        for spec in compiled_hint.get("evidence_specs") or []:
            if not isinstance(spec, dict):
                continue
            for key in ("slot_name", "source_role", "target_period", "statement", "line_item"):
                value = spec.get(key)
                if isinstance(value, str):
                    parts.append(value)
            for item in spec.get("accepted_attributes") or []:
                if isinstance(item, str):
                    parts.append(item)
            for item in spec.get("required_source_families") or []:
                if isinstance(item, str):
                    parts.append(item)
        for spec in compiled_hint.get("transform_specs") or []:
            if not isinstance(spec, dict):
                continue
            for key in ("name", "expression", "output_unit", "output_attribute"):
                value = spec.get(key)
                if isinstance(value, str):
                    parts.append(value)
            for item in spec.get("required_slots") or []:
                if isinstance(item, str):
                    parts.append(item)
    return " ".join(parts)


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
