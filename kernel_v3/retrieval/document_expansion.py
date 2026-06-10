from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.parse
from html.parser import HTMLParser

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.retrieval.contracts import (
    DiscoveryExpansion,
    FetchedDocument,
    RetrievalNextAction,
    SearchGoal,
    SearchSource,
)


DOCUMENT_LINK_EXPANSION_PROVIDER_ID = "document_link_expansion"
DOCUMENT_EXPANSION_SOURCE_KINDS = {
    "issuer_investor_relations",
    "issuer_annual_reports",
    "issuer_earnings_releases",
    "official_search",
    "sec_edgar_search",
    "scholarly_publisher_metadata",
    "crawl_seed",
    "crawl_discovered",
    "crawl_sitemap",
}
DOCUMENT_EXPANSION_SOURCE_FAMILIES = {
    "company_ir",
    "regulatory_filing",
    "exchange_filing",
    "structured_regulatory_data",
    "fund_disclosure",
    "official_documentation",
    "scholarly_publisher",
    "academic_repository",
    "scholarly_preprint",
}
DOCUMENT_EXTENSIONS = {
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".pdf",
    ".txt",
    ".xhtml",
    ".xml",
}
DOCUMENT_KEYWORDS = {
    "10-k",
    "10q",
    "10-q",
    "annual",
    "annual-report",
    "annualreport",
    "companyfacts",
    "earnings",
    "exhibit",
    "financial",
    "filing",
    "form-10",
    "investor",
    "merger",
    "merger-agreement",
    "press-release",
    "press release",
    "quarter",
    "quarterly",
    "report",
    "results",
    "transaction",
    "xbrl",
}
LOW_VALUE_LINK_KEYWORDS = {
    "accessibility",
    "careers",
    "cookie",
    "contact",
    "facebook",
    "instagram",
    "linkedin",
    "login",
    "privacy",
    "terms",
    "twitter",
    "youtube",
}
URL_RE = re.compile(r"https?://[^\s<>'\")\]]+|//[A-Za-z0-9.-]+/[^\s<>'\")\]]+")
JS_HREF_RE = re.compile(
    r"(?:href\s*[:=]|\.attr\(\s*['\"]href['\"]\s*,)\s*['\"]([^'\"]{3,2048})['\"]",
    re.IGNORECASE,
)
TERM_RE = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")
STOPWORDS = {
    "a",
    "about",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "for",
    "from",
    "if",
    "in",
    "inc",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "page",
    "please",
    "source",
    "the",
    "this",
    "to",
    "tool",
    "use",
    "was",
    "were",
    "what",
    "when",
    "with",
}


def expand_document_links(
    *,
    goal: SearchGoal,
    documents: list[tuple[FetchedDocument, str]],
    source_by_id: dict[str, SearchSource],
    max_candidates: int = 48,
) -> tuple[list[SearchSource], list[DiscoveryExpansion], list[RetrievalNextAction]]:
    """Expand fetched discovery/index documents into concrete fetchable links.

    This layer is intentionally domain-general: it only converts a fetched
    official/discovery surface into document candidates. It does not decide the
    answer and it does not inject domain facts.
    """

    if max_candidates <= 0:
        return [], [], []
    expanded: list[SearchSource] = []
    records: list[DiscoveryExpansion] = []
    actions: list[RetrievalNextAction] = []
    seen_uris = {document.uri for document, _body in documents}
    query_terms = _query_terms(goal)

    for document, body in documents:
        if len(expanded) >= max_candidates:
            break
        source = source_by_id.get(document.source_id)
        if source is None or not _is_expandable_source(source=source, document=document, body=body):
            continue
        per_document_limit = min(max(4, max_candidates // max(1, len(documents))), max_candidates - len(expanded), 32)
        candidates = _candidate_links(
            goal=goal,
            document=document,
            source=source,
            body=body,
            query_terms=query_terms,
            remaining=per_document_limit,
        )
        accepted: list[SearchSource] = []
        for candidate in candidates:
            if candidate.uri in seen_uris:
                continue
            seen_uris.add(candidate.uri)
            accepted.append(candidate)
        expanded.extend(accepted)
        if accepted:
            action = _next_action(goal=goal, document=document, source=source, candidate_count=len(accepted))
            actions.append(action)
        records.append(
            DiscoveryExpansion(
                expansion_id=f"doc-exp-{goal.goal_id}-{_hash(document.document_id + document.uri)[:12]}",
                goal_id=goal.goal_id,
                source_id=document.source_id,
                uri=document.uri,
                status="expanded" if accepted else "skipped",
                candidate_sources=[candidate.to_dict() for candidate in accepted],
                next_tool_actions=[action.to_dict() for action in actions[-1:]] if accepted else [],
                diagnostics={
                    "document_id": document.document_id,
                    "source_kind": _source_kind(source),
                    "source_family": _source_family(source),
                    "candidate_count": len(accepted),
                    "candidate_uri_hashes": [_hash(candidate.uri) for candidate in accepted[:12]],
                },
            )
        )
    return expanded, records, _dedupe_actions(actions)


def _is_expandable_source(*, source: SearchSource, document: FetchedDocument, body: str) -> bool:
    kind = _source_kind(source) or _document_source_kind(document)
    if kind in {"sec_submissions_json", "sec_complete_submission_text"}:
        return bool(body)
    if not body or ("href" not in body.lower() and ".pdf" not in body.lower() and "http" not in body.lower()):
        return False
    family = _source_family(source)
    if kind in DOCUMENT_EXPANSION_SOURCE_KINDS:
        return True
    if family in DOCUMENT_EXPANSION_SOURCE_FAMILIES:
        return True
    return bool(source.metadata.get("discovery_expanded"))


def _candidate_links(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    body: str,
    query_terms: list[str],
    remaining: int,
) -> list[SearchSource]:
    scored: list[tuple[float, int, JsonObject]] = []
    for index, link in enumerate(
        _structured_candidate_links(
            goal=goal,
            document=document,
            source=source,
            body=body,
            query_terms=query_terms,
        ),
        start=-10_000,
    ):
        scored.append((float(link.get("score") or 0.0), index, link))
    link_scan_limit = _link_scan_limit(source=source, document=document, body=body)
    for index, link in enumerate(_extract_links(body[:link_scan_limit], base_url=document.uri)):
        url = str(link.get("url") or "")
        text = str(link.get("text") or "")
        if not _safe_url(url) or _is_low_value_link(url=url, text=text):
            continue
        score, matched = _link_score(url=url, text=text, query_terms=query_terms)
        if score <= 0:
            continue
        enriched = dict(link)
        enriched["score"] = score
        enriched["matched_terms"] = matched
        scored.append((score, index, enriched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    candidates: list[SearchSource] = []
    for rank, (_score, _index, link) in enumerate(scored[:remaining], start=1):
        candidates.append(_source_from_link(goal=goal, document=document, source=source, link=link, rank=rank))
    return candidates


def _link_scan_limit(*, source: SearchSource, document: FetchedDocument, body: str) -> int:
    kind = _source_kind(source) or _document_source_kind(document)
    if kind in {"sec_primary_filing_document", "sec_complete_submission_text"}:
        return min(len(body), 4_000_000)
    return min(len(body), 1_500_000)


def _source_from_link(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    link: JsonObject,
    rank: int,
) -> SearchSource:
    url = str(link["url"])
    text = str(link.get("text") or "")
    source_family = str(link.get("source_family") or "") or _source_family(source) or _metadata_source_family(document)
    authority_level = _authority_level(source)
    kind = str(link.get("source_kind") or "") or _candidate_source_kind(source=source, url=url, text=text)
    if kind in {"sec_primary_filing_document", "sec_complete_submission_text", "sec_filing_directory"}:
        source_family = "regulatory_filing"
    host = urllib.parse.urlparse(url).hostname or ""
    metadata = {
        "rank": rank,
        "research_profile": source.metadata.get("research_profile") or goal.metadata.get("research_profile"),
        "research_profile_id": source.metadata.get("research_profile_id") or goal.metadata.get("research_profile_id"),
        "source_family": source_family,
        "authority_level": authority_level,
        "source_kind": kind,
        "expanded_from_source_id": source.source_id,
        "expanded_from_document_id": document.document_id,
        "expanded_from_uri": document.uri,
        "document_link_expanded": True,
        "discovery_expanded": True,
        "fetch_allowed_hosts": [host] if host else [],
        "matched_query_terms": link.get("matched_terms", []),
        "link_relevance_score": round(float(link.get("score") or 0.0), 6),
    }
    for key in (
        "sec_accession_number",
        "sec_accession_compact",
        "sec_primary_document",
        "sec_form",
        "sec_cik",
        "sec_primary_doc_description",
        "sec_items",
        "report_date",
        "filing_date",
        "filing_index",
        "expanded_from_submission_archive",
    ):
        value = link.get(key)
        if isinstance(value, str) and value:
            metadata[key] = value
        elif isinstance(value, int):
            metadata[key] = value
        elif isinstance(value, bool):
            metadata[key] = value
    if source.metadata.get("source_directory_id"):
        metadata["source_directory_id"] = source.metadata["source_directory_id"]
    return SearchSource(
        source_id=f"{DOCUMENT_LINK_EXPANSION_PROVIDER_ID}-{_hash(document.document_id + url)[:12]}-{rank}",
        uri=url,
        title=_bounded(text or _title_from_url(url), 240),
        snippet=_bounded(f"Document link discovered from {document.title}. Path: {_path_text(url)}", 800),
        provider=DOCUMENT_LINK_EXPANSION_PROVIDER_ID,
        metadata=metadata,
    )


def _structured_candidate_links(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    body: str,
    query_terms: list[str],
) -> list[JsonObject]:
    kind = _source_kind(source) or _document_source_kind(document)
    if kind == "sec_submissions_json":
        return _sec_submission_document_links(goal=goal, document=document, source=source, body=body, query_terms=query_terms)
    if kind == "sec_complete_submission_text":
        return _sec_complete_submission_child_document_links(
            goal=goal,
            document=document,
            source=source,
            body=body,
            query_terms=query_terms,
        )
    return []


def _sec_complete_submission_child_document_links(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    body: str,
    query_terms: list[str],
) -> list[JsonObject]:
    base_uri = _sec_archive_base_uri(document.uri)
    if not base_uri:
        return []
    intent_terms = [*query_terms, *_metadata_goal_terms(goal.metadata)]
    wants_transaction_event = _query_wants_transaction_event(intent_terms)
    links: list[JsonObject] = []
    for index, block in enumerate(re.findall(r"<DOCUMENT>(.*?)(?=<DOCUMENT>|</SEC-DOCUMENT>|$)", body, re.IGNORECASE | re.DOTALL)):
        filename = _sec_document_block_value(block, "FILENAME")
        if not filename:
            continue
        safe_name = _safe_sec_document_name(filename)
        if not safe_name:
            continue
        doc_type = _sec_document_block_value(block, "TYPE")
        description = _sec_document_block_value(block, "DESCRIPTION")
        text = _bounded(" ".join(part for part in (doc_type, description, safe_name) if part), 240)
        score = _sec_child_document_score(
            filename=safe_name,
            doc_type=doc_type,
            description=description,
            query_terms=query_terms,
            wants_transaction_event=wants_transaction_event,
        )
        if score <= 0:
            continue
        links.append(
            {
                "url": urllib.parse.urljoin(base_uri + "/", safe_name),
                "text": text,
                "score": score,
                "matched_terms": _ordered_unique(
                    [
                        str(doc_type or "").lower(),
                        *[
                            term
                            for term in query_terms
                            if term and term in f"{safe_name} {description} {doc_type}".lower()
                        ],
                        "sec",
                        "exhibit",
                    ]
                )[:16],
                "source_family": "regulatory_filing",
                "source_kind": "sec_exhibit_document",
                "filing_index": index,
                "sec_accession_number": source.metadata.get("sec_accession_number")
                or document.metadata.get("sec_accession_number"),
                "sec_accession_compact": source.metadata.get("sec_accession_compact")
                or document.metadata.get("sec_accession_compact"),
                "sec_form": source.metadata.get("sec_form") or document.metadata.get("sec_form"),
                "sec_primary_doc_description": description,
            }
        )
    links.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("url") or "")))
    return links[:16]


def _sec_document_block_value(block: str, key: str) -> str:
    match = re.search(rf"<{re.escape(key)}>\s*([^\r\n<]+)", block, re.IGNORECASE)
    return " ".join(match.group(1).split()) if match else ""


def _sec_archive_base_uri(uri: str) -> str:
    parsed = urllib.parse.urlparse(str(uri or ""))
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    path = parsed.path
    if "/Archives/edgar/data/" not in path:
        return ""
    directory = path.rsplit("/", 1)[0]
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, directory, "", "", ""))


def _sec_child_document_score(
    *,
    filename: str,
    doc_type: str,
    description: str,
    query_terms: list[str],
    wants_transaction_event: bool,
) -> float:
    haystack = f"{filename} {doc_type} {description}".lower()
    score = 0.15
    matched = [term for term in query_terms if len(term) >= 3 and term in haystack]
    score += min(1.0, 0.2 * len(matched))
    if str(doc_type or "").upper().startswith("EX-99"):
        score += 1.9
    if str(doc_type or "").upper().startswith("EX-2"):
        score += 0.95
    if any(marker in haystack for marker in ("press", "release", "presentation", "investor")):
        score += 0.65
    if any(marker in haystack for marker in ("merger", "agreement", "acquisition", "transaction")):
        score += 0.65
    if wants_transaction_event and any(marker in haystack for marker in ("ex-99", "ex99", "press", "release")):
        score += 1.8
    elif wants_transaction_event and any(marker in haystack for marker in ("merger", "agreement")):
        score += 1.0
    if _extension(filename) not in {".htm", ".html", ".txt"}:
        score -= 0.35
    return score


def _sec_submission_document_links(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    body: str,
    query_terms: list[str],
) -> list[JsonObject]:
    try:
        payload = json.loads(body)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict) and isinstance(payload.get("accessionNumber"), list):
        recent = payload
    if not isinstance(recent, dict):
        return []
    accessions = _json_list(recent.get("accessionNumber"))
    forms = _json_list(recent.get("form"))
    primary_documents = _json_list(recent.get("primaryDocument"))
    primary_descriptions = _json_list(recent.get("primaryDocDescription"))
    items = _json_list(recent.get("items"))
    report_dates = _json_list(recent.get("reportDate"))
    filing_dates = _json_list(recent.get("filingDate"))
    cik = _sec_cik_from_payload(payload, document=document, source=source)
    if not cik:
        return []
    target_years = [term for term in query_terms if term.isdigit() and len(term) == 4]
    intent_terms = [*query_terms, *_metadata_goal_terms(goal.metadata)]
    wants_annual = _query_wants_annual_report(query_terms)
    wants_bridge_reconciliation = _query_wants_bridge_reconciliation(intent_terms)
    wants_transaction_event = _query_wants_transaction_event(intent_terms)
    wants_transaction_or_bridge = wants_transaction_event or wants_bridge_reconciliation
    candidates: list[JsonObject] = []
    candidates.extend(
        _sec_submission_archive_file_links(
            goal=goal,
            document=document,
            source=source,
            payload=payload,
            wants_transaction_or_bridge=wants_transaction_or_bridge,
            target_years=target_years,
        )
    )
    scan_limit = _sec_submission_recent_scan_limit(
        wants_transaction_or_bridge=wants_transaction_or_bridge,
        target_years=target_years,
        accession_count=len(accessions),
    )
    for index, accession in enumerate(accessions[:scan_limit]):
        accession_number = str(accession or "").strip()
        compact = accession_number.replace("-", "")
        primary_document = _safe_sec_document_name(_list_get(primary_documents, index))
        form = str(_list_get(forms, index) or "").strip().upper()
        primary_description = str(_list_get(primary_descriptions, index) or "").strip()
        filing_items = str(_list_get(items, index) or "").strip()
        report_date = str(_list_get(report_dates, index) or "").strip()
        filing_date = str(_list_get(filing_dates, index) or "").strip()
        if not compact or not primary_document or not form:
            continue
        if not _sec_form_is_document_candidate(
            form=form,
            wants_annual=wants_annual,
            wants_transaction_event=wants_transaction_event,
            wants_bridge_reconciliation=wants_bridge_reconciliation,
        ):
            continue
        base_uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}"
        title = _sec_submission_link_title(
            form=form,
            report_date=report_date,
            filing_date=filing_date,
            primary_document=primary_document,
            primary_description=primary_description,
            filing_items=filing_items,
        )
        score = _sec_submission_candidate_score(
            form=form,
            primary_document=primary_document,
            primary_description=primary_description,
            filing_items=filing_items,
            report_date=report_date,
            filing_date=filing_date,
            query_terms=query_terms,
            target_years=target_years,
            wants_annual=wants_annual,
            wants_transaction_event=wants_transaction_event,
            wants_bridge_reconciliation=wants_bridge_reconciliation,
        )
        if score <= 0:
            continue
        common = {
            "score": score,
            "matched_terms": _ordered_unique([form.lower(), *target_years, "sec", "filing", "10-k"])[:16],
            "source_family": "regulatory_filing",
            "filing_index": index,
            "sec_accession_number": accession_number,
            "sec_accession_compact": compact,
            "sec_primary_document": primary_document,
            "sec_form": form,
            "sec_primary_doc_description": primary_description,
            "sec_items": filing_items,
            "report_date": report_date,
            "filing_date": filing_date,
        }
        candidates.append(
            {
                **common,
                "url": f"{base_uri}/{primary_document}",
                "text": title,
                "source_kind": "sec_primary_filing_document",
            }
        )
        candidates.append(
            {
                **common,
                "url": f"{base_uri}/{accession_number}.txt",
                "text": f"SEC complete submission text for {title}",
                "source_kind": "sec_complete_submission_text",
                "score": max(0.1, score - 0.08),
            }
        )
    candidates = _select_sec_submission_candidates(
        candidates,
        wants_transaction_event=wants_transaction_event,
        wants_bridge_reconciliation=wants_bridge_reconciliation,
        target_years=target_years,
    )
    return candidates[:48 if wants_transaction_or_bridge else 24]


def _sec_submission_archive_file_links(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    source: SearchSource,
    payload: JsonObject,
    wants_transaction_or_bridge: bool,
    target_years: list[str],
) -> list[JsonObject]:
    filings = payload.get("filings")
    files = filings.get("files") if isinstance(filings, dict) else None
    if not isinstance(files, list) or not files:
        return []
    base = "https://data.sec.gov/submissions/"
    result: list[JsonObject] = []
    for index, item in enumerate(files[:24]):
        if not isinstance(item, dict):
            continue
        name = _safe_sec_submission_file_name(item.get("name"))
        if not name:
            continue
        filing_from = str(item.get("filingFrom") or "")
        filing_to = str(item.get("filingTo") or "")
        year_range = " ".join(re.findall(r"(?:19|20)\d{2}", f"{filing_from} {filing_to}"))
        score = 0.95
        if wants_transaction_or_bridge:
            score += 1.25
        if target_years:
            if any(year in year_range for year in target_years):
                score += 2.0
            else:
                score -= 0.25
        result.append(
            {
                "url": urllib.parse.urljoin(base, name),
                "text": _bounded(
                    f"SEC submissions archive file {name} filingFrom={filing_from} filingTo={filing_to}",
                    240,
                ),
                "score": score,
                "matched_terms": _ordered_unique(["sec", "submissions", "filing", *target_years])[:16],
                "source_family": "structured_regulatory_data",
                "source_kind": "sec_submissions_json",
                "filing_index": -1000 + index,
                "expanded_from_submission_archive": True,
                "research_profile": source.metadata.get("research_profile") or goal.metadata.get("research_profile"),
                "research_profile_id": source.metadata.get("research_profile_id") or goal.metadata.get("research_profile_id"),
                "authority_level": source.metadata.get("authority_level") or "primary",
                "sec_cik": source.metadata.get("sec_cik") or document.metadata.get("sec_cik"),
            }
        )
    return result


def _safe_sec_submission_file_name(value: object) -> str:
    text = str(value or "").strip().split("/")[-1]
    if not re.fullmatch(r"CIK\d{10}-submissions-\d{3}\.json", text):
        return ""
    return text


def _select_sec_submission_candidates(
    candidates: list[JsonObject],
    *,
    wants_transaction_event: bool,
    wants_bridge_reconciliation: bool,
    target_years: list[str],
) -> list[JsonObject]:
    candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("url") or "")))
    if wants_bridge_reconciliation:
        return _select_bridge_reconciliation_candidates(candidates)
    if not wants_transaction_event or target_years:
        return candidates
    by_year: dict[str, list[JsonObject]] = {}
    for candidate in sorted(candidates, key=lambda item: _safe_int(item.get("filing_index"), default=10_000)):
        form = str(candidate.get("sec_form") or "").upper().replace(" ", "")
        if form not in {"8-K", "6-K", "10-K", "20-F", "40-F"}:
            continue
        year = _year_from_date(str(candidate.get("filing_date") or "")) or _year_from_date(str(candidate.get("report_date") or ""))
        year = year or "unknown"
        by_year.setdefault(year, []).append(candidate)
    if len(by_year) <= 1:
        return candidates
    result: list[JsonObject] = []
    seen: set[str] = set()
    years = sorted(by_year, reverse=True)
    for _round in range(8):
        for year in years:
            bucket = by_year.get(year) or []
            if not bucket:
                continue
            candidate = bucket.pop(0)
            key = str(candidate.get("url") or "")
            if key in seen:
                continue
            seen.add(key)
            result.append(candidate)
            if len(result) >= 48:
                return result
    for candidate in candidates:
        key = str(candidate.get("url") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(candidate)
        if len(result) >= 48:
            break
    return result


def _select_bridge_reconciliation_candidates(candidates: list[JsonObject]) -> list[JsonObject]:
    filing_reports: list[JsonObject] = []
    other_documents: list[JsonObject] = []
    event_filings: list[JsonObject] = []
    for candidate in candidates:
        form = str(candidate.get("sec_form") or "").upper().replace(" ", "")
        if form in {"10-K", "10-Q", "20-F", "40-F"}:
            filing_reports.append(candidate)
        elif form in {"8-K", "6-K"}:
            event_filings.append(candidate)
        else:
            other_documents.append(candidate)
    ordered: list[JsonObject] = []
    seen: set[str] = set()
    for bucket in (
        _sort_sec_candidates_by_recent_index(filing_reports),
        _sort_sec_candidates_by_recent_index(other_documents),
        _sort_sec_candidates_by_recent_index(event_filings),
    ):
        for candidate in bucket:
            url = str(candidate.get("url") or "")
            if url in seen:
                continue
            seen.add(url)
            ordered.append(candidate)
    return ordered


def _sort_sec_candidates_by_recent_index(candidates: list[JsonObject]) -> list[JsonObject]:
    return sorted(
        candidates,
        key=lambda item: (
            _safe_int(item.get("filing_index"), default=10_000),
            -float(item.get("score") or 0.0),
            str(item.get("url") or ""),
        ),
    )


def _sec_submission_link_title(
    *,
    form: str,
    report_date: str,
    filing_date: str,
    primary_document: str,
    primary_description: str = "",
    filing_items: str = "",
) -> str:
    pieces = [f"SEC {form} primary filing document"]
    if report_date:
        pieces.append(f"reportDate={report_date}")
    if filing_date:
        pieces.append(f"filed={filing_date}")
    if primary_description:
        pieces.append(f"description={primary_description}")
    if filing_items:
        pieces.append(f"items={filing_items}")
    pieces.append(primary_document)
    return " ".join(pieces)


def _sec_submission_candidate_score(
    *,
    form: str,
    primary_document: str,
    primary_description: str,
    filing_items: str,
    report_date: str,
    filing_date: str,
    query_terms: list[str],
    target_years: list[str],
    wants_annual: bool,
    wants_transaction_event: bool,
    wants_bridge_reconciliation: bool,
) -> float:
    normalized_form = form.upper().replace(" ", "")
    score = 0.8
    if normalized_form in {"10-K", "20-F", "40-F"}:
        score += 1.1
    elif normalized_form == "10-Q":
        score += 0.35
    elif normalized_form in {"8-K", "6-K"} and wants_transaction_event:
        score += 1.25
    if wants_bridge_reconciliation:
        if normalized_form in {"10-K", "20-F", "40-F"}:
            score += 1.25
        elif normalized_form == "10-Q":
            score += 0.55
        elif normalized_form in {"8-K", "6-K"}:
            score -= 0.35
    if wants_annual and not wants_transaction_event and normalized_form not in {"10-K", "20-F", "40-F"}:
        score -= 0.65
    report_year = _year_from_date(report_date)
    filing_year = _year_from_date(filing_date)
    if target_years:
        if report_year in target_years:
            score += 2.4
        elif filing_year in target_years:
            score += 0.35
        else:
            score -= 0.65
    if wants_transaction_event:
        score += _sec_event_metadata_score(
            form=normalized_form,
            primary_document=primary_document,
            primary_description=primary_description,
            filing_items=filing_items,
            query_terms=query_terms,
        )
    return score


def _sec_event_metadata_score(
    *,
    form: str,
    primary_document: str,
    primary_description: str,
    filing_items: str,
    query_terms: list[str],
) -> float:
    haystack = f"{primary_document} {primary_description} {filing_items}".lower()
    if not haystack.strip():
        return 0.0
    score = 0.0
    event_terms = {
        "acquisition",
        "acquire",
        "merger",
        "transaction",
        "agreement",
        "definitive",
        "purchase",
        "consideration",
        "disposition",
        "business",
        "combination",
    }
    matched_query_terms = [
        term
        for term in query_terms
        if len(term) >= 4 and term not in STOPWORDS and term in haystack
    ]
    score += min(1.6, 0.35 * len(matched_query_terms))
    if any(term in haystack for term in event_terms):
        score += 1.1
    if form in {"8-K", "6-K"}:
        if any(item in haystack for item in ("1.01", "2.01")):
            score += 2.15
        elif "8.01" in haystack:
            score += 0.85
        if "9.01" in haystack:
            score += 0.25
        if any(item in haystack for item in ("2.02", "2.05")):
            score -= 0.75
    if any(marker in haystack for marker in ("earnings release", "financial results", "quarter results")):
        score -= 0.7
    return score


def _sec_form_is_document_candidate(
    *,
    form: str,
    wants_annual: bool,
    wants_transaction_event: bool = False,
    wants_bridge_reconciliation: bool = False,
) -> bool:
    normalized = form.upper().replace(" ", "")
    if normalized in {"10-K", "10-Q", "20-F", "40-F"}:
        return True
    if (wants_transaction_event or wants_bridge_reconciliation) and normalized in {"8-K", "6-K"}:
        return True
    if wants_annual:
        return False
    return normalized in {"8-K", "6-K"}


def _sec_submission_recent_scan_limit(
    *,
    wants_transaction_or_bridge: bool,
    target_years: list[str],
    accession_count: int,
) -> int:
    if target_years:
        return min(max(200, int(accession_count)), 1200)
    if wants_transaction_or_bridge:
        return min(max(400, int(accession_count)), 1200)
    return min(200, int(accession_count))


def _query_wants_annual_report(query_terms: list[str]) -> bool:
    return any(term in query_terms for term in {"annual", "fiscal", "fy2024", "10", "10k", "10-k"}) or any(
        term.isdigit() and len(term) == 4 for term in query_terms
    )


def _query_wants_transaction_event(query_terms: list[str]) -> bool:
    normalized = " ".join(query_terms).lower()
    compact = "".join(ch for ch in normalized if ch.isalnum())
    return any(
        marker in normalized or marker in compact
        for marker in (
            "8-k",
            "8k",
            "merger",
            "acquisition",
            "transaction",
            "deal",
            "purchase",
            "consideration",
        )
    )


def _query_wants_bridge_reconciliation(query_terms: list[str]) -> bool:
    normalized = " ".join(query_terms).lower()
    compact = "".join(ch for ch in normalized if ch.isalnum())
    return any(
        marker in normalized or marker in compact
        for marker in (
            "adjusted ebitda",
            "adjustedebitda",
            "non gaap",
            "nongaap",
            "bridge",
            "reconciliation",
            "addback",
            "add back",
        )
    )


def _metadata_goal_terms(metadata: JsonObject) -> list[str]:
    parts: list[str] = []
    for key in ("root_goal", "task_goal", "original_goal", "user_goal"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, str) and value.strip():
            parts.extend(value.replace("-", " ").split())
    for key in ("required_evidence_terms", "missing_slots"):
        value = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(value, list):
            parts.extend(_metadata_string_terms(value))
    policy = metadata.get("evidence_policy") if isinstance(metadata, dict) else None
    if isinstance(policy, dict):
        parts.extend(_metadata_string_terms(policy.get("required_terms")))
    slot_frame = metadata.get("slot_frame") if isinstance(metadata, dict) else None
    if isinstance(slot_frame, dict):
        parts.extend(_metadata_string_terms(slot_frame.get("missing_slots")))
        for key in ("required_slots", "optional_slots"):
            slots = slot_frame.get(key)
            if not isinstance(slots, list):
                continue
            for slot in slots:
                if isinstance(slot, dict):
                    accepted = slot.get("accepted_attributes")
                    accepted_terms = accepted if isinstance(accepted, list) else []
                    parts.extend(_metadata_string_terms([slot.get("name"), *accepted_terms]))
    mission = metadata.get("research_mission") if isinstance(metadata, dict) else None
    if isinstance(mission, dict):
        value = mission.get("root_goal")
        if isinstance(value, str) and value.strip():
            parts.extend(value.replace("-", " ").split())
    return parts


def _metadata_string_terms(value: object) -> list[str]:
    if isinstance(value, str):
        values: list[object] = [value]
    elif isinstance(value, list):
        values = value
    else:
        return []
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        text = item.strip()
        if not text:
            continue
        result.extend(text.replace("-", " ").replace("_", " ").split())
    return result


def _sec_cik_from_payload(payload: JsonObject, *, document: FetchedDocument, source: SearchSource) -> str:
    for value in (
        payload.get("cik"),
        source.metadata.get("sec_cik"),
        document.metadata.get("sec_cik"),
        document.uri,
    ):
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits:
            return digits[-10:].zfill(10)
    return ""


def _safe_sec_document_name(value: object) -> str:
    text = str(value or "").strip().split("/")[-1]
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,240}", text):
        return ""
    return text


def _json_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _list_get(values: list[object], index: int) -> object:
    return values[index] if 0 <= index < len(values) else ""


def _year_from_date(value: str) -> str:
    match = re.match(r"^((?:19|20)\d{2})-", str(value or ""))
    return match.group(1) if match else ""


def _safe_int(value: object, *, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def _candidate_source_kind(*, source: SearchSource, url: str, text: str) -> str:
    source_family = _source_family(source)
    lower = f"{url} {text}".lower()
    if source_family == "company_ir":
        return "issuer_report_document"
    if "sec.gov" in (urllib.parse.urlparse(url).hostname or "").lower():
        if "companyfacts" in lower:
            return "sec_companyfacts_json"
        return "sec_primary_filing_document"
    if source_family in {"scholarly_publisher", "academic_repository", "scholarly_preprint"}:
        return "scholarly_article_document"
    if source_family == "official_documentation":
        return "official_documentation_document"
    return "discovered_document"


def _link_score(*, url: str, text: str, query_terms: list[str]) -> tuple[float, list[str]]:
    haystack = f"{url} {text}".lower()
    matched = [term for term in query_terms if term in haystack]
    score = len(matched) / max(1, len(query_terms))
    document_hits = [term for term in DOCUMENT_KEYWORDS if term in haystack]
    extension = _extension(url)
    if not document_hits and extension not in DOCUMENT_EXTENSIONS:
        return 0.0, []
    if document_hits:
        score += 0.45 + min(0.25, len(document_hits) * 0.05)
    if extension in DOCUMENT_EXTENSIONS:
        score += 0.25
    if extension == ".pdf":
        score += 0.2
    year_score = _target_year_score(url=url, text=text, query_terms=query_terms)
    score += year_score
    if _looks_like_proxy_or_meeting_material(haystack) and not _query_requests_proxy(query_terms):
        score -= 0.85
    return score, _ordered_unique([*matched, *document_hits])[:16]


def _target_year_score(*, url: str, text: str, query_terms: list[str]) -> float:
    haystack = f"{url} {text}".lower()
    years = [term for term in query_terms if term.isdigit() and len(term) == 4]
    if not years:
        return 0.0
    text_years = set(re.findall(r"(?:19|20)\d{2}", text))
    url_years = set(re.findall(r"(?:19|20)\d{2}", url))
    url_years.update(_two_digit_report_years(url))
    for year in years:
        if year in text_years or year in _two_digit_report_years(text):
            return 1.2
    non_target_text_years = {year for year in text_years if year not in years}
    if non_target_text_years:
        return -0.7
    for year in years:
        if year in url_years:
            return 0.8
    non_target_url_years = {year for year in url_years if year not in years}
    if non_target_url_years:
        return -0.35
    return 0.0


def _two_digit_report_years(value: str) -> set[str]:
    years: set[str] = set()
    lower = value.lower()
    for match in re.findall(r"(?:fy|q[1-4]|ar|annual|report|10-k|10q|10-q|[_\-/])([0-9]{2})(?:[^0-9]|$)", lower):
        parsed = int(match)
        if 0 <= parsed <= 39:
            years.add(f"20{parsed:02d}")
        elif parsed >= 80:
            years.add(f"19{parsed:02d}")
    return years


def _looks_like_proxy_or_meeting_material(haystack: str) -> bool:
    return "proxy" in haystack or "shareholder meeting" in haystack or "meeting transcript" in haystack


def _query_requests_proxy(query_terms: list[str]) -> bool:
    return "proxy" in query_terms or "shareholder" in query_terms or "meeting" in query_terms


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[JsonObject] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = next((value for key, value in attrs if key.lower() == "href"), None)
        if isinstance(href, str) and href.strip():
            self._href = href.strip()
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append({"href": self._href, "text": _bounded(" ".join("".join(self._text).split()), 240)})
        self._href = None
        self._text = []


def _extract_links(body: str, *, base_url: str) -> list[JsonObject]:
    links: list[JsonObject] = []
    parser = _LinkParser()
    try:
        parser.feed(body)
    except Exception:
        parser.links = []
    for item in parser.links:
        links.append({"url": _absolute_url(str(item.get("href") or ""), base_url=base_url), "text": str(item.get("text") or "")})
    for raw in JS_HREF_RE.findall(body):
        links.append({"url": _absolute_url(html.unescape(raw), base_url=base_url), "text": ""})
    for raw in URL_RE.findall(body):
        links.append({"url": _absolute_url(html.unescape(raw), base_url=base_url), "text": ""})
    return _dedupe_link_items(links)


def _absolute_url(value: str, *, base_url: str) -> str:
    text = value.strip().strip("<>()[]{}'\"")
    if text.startswith("//"):
        parsed_base = urllib.parse.urlparse(base_url)
        text = f"{parsed_base.scheme or 'https'}:{text}"
    return urllib.parse.urljoin(base_url, text)


def _safe_url(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return not contains_secret_like_content(parsed.geturl())


def _is_low_value_link(*, url: str, text: str) -> bool:
    lower = f"{url} {text}".lower()
    if any(marker in lower for marker in LOW_VALUE_LINK_KEYWORDS):
        return True
    parsed = urllib.parse.urlparse(url)
    if parsed.fragment and not parsed.path:
        return True
    return _extension(url) in {".css", ".gif", ".ico", ".jpg", ".jpeg", ".js", ".png", ".svg", ".webp"}


def _query_terms(goal: SearchGoal) -> list[str]:
    values = [goal.query, *_metadata_strings(goal.metadata)]
    terms: list[str] = []
    for value in values:
        for token in TERM_RE.findall(value.lower()):
            if token in STOPWORDS:
                continue
            if token.isdigit() and len(token) == 4:
                terms.append(token)
            elif len(token) >= 3:
                terms.append(token)
    return _ordered_unique(terms)[:96]


def _metadata_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if str(key).lower() in {"api_key", "authorization", "password", "secret", "token"}:
                continue
            result.extend(_metadata_strings(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_metadata_strings(item))
        return result
    return []


def _source_kind(source: SearchSource) -> str:
    value = source.metadata.get("source_kind") if isinstance(source.metadata, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _document_source_kind(document: FetchedDocument) -> str:
    metadata = document.metadata.get("source_metadata") if isinstance(document.metadata, dict) else None
    if isinstance(metadata, dict):
        value = metadata.get("source_kind")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _source_family(source: SearchSource) -> str:
    value = source.metadata.get("source_family") if isinstance(source.metadata, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _metadata_source_family(document: FetchedDocument) -> str:
    metadata = document.metadata.get("source_metadata") if isinstance(document.metadata, dict) else None
    if isinstance(metadata, dict):
        value = metadata.get("source_family")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "generic_web"


def _authority_level(source: SearchSource) -> str:
    value = source.metadata.get("authority_level")
    if isinstance(value, str) and value.strip():
        return value.strip()
    assessment = source.metadata.get("source_assessment")
    if isinstance(assessment, dict):
        value = assessment.get("authority_level")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "secondary"


def _extension(url: str) -> str:
    path = urllib.parse.urlparse(url).path.lower()
    if "." not in path.rsplit("/", 1)[-1]:
        return ""
    return "." + path.rsplit(".", 1)[-1]


def _title_from_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    stem = parsed.path.strip("/").rsplit("/", 1)[-1] or parsed.hostname or url
    return stem.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")


def _path_text(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    return _bounded(parsed.path.strip("/").replace("_", " ").replace("-", " ").replace("/", " ") or (parsed.hostname or ""), 240)


def _next_action(*, goal: SearchGoal, document: FetchedDocument, source: SearchSource, candidate_count: int) -> RetrievalNextAction:
    return RetrievalNextAction(
        action_id=f"next-{goal.goal_id}-{_hash(document.document_id + source.source_id)[:12]}",
        action="fetch_discovered_document_links",
        tool_hint="retrieval.run",
        source_id=source.source_id,
        uri=document.uri,
        reason="fetched discovery page contains concrete document/report links that should be fetched before judging evidence sufficiency",
        payload_hint={"goal_id": goal.goal_id, "expanded_from_document_id": document.document_id, "candidate_count": candidate_count},
        diagnostics={"source_kind": _source_kind(source), "source_family": _source_family(source)},
    )


def _dedupe_link_items(items: list[JsonObject]) -> list[JsonObject]:
    seen: set[str] = set()
    result: list[JsonObject] = []
    for item in items:
        url = str(item.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(item)
    return result


def _dedupe_actions(actions: list[RetrievalNextAction]) -> list[RetrievalNextAction]:
    seen: set[tuple[str, str | None]] = set()
    result: list[RetrievalNextAction] = []
    for action in actions:
        key = (action.action, action.uri)
        if key in seen:
            continue
        seen.add(key)
        result.append(action)
    return result


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _bounded(text: str, limit: int) -> str:
    normalized = " ".join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
