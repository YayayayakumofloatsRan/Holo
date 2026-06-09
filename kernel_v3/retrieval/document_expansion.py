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
    "financial",
    "filing",
    "form-10",
    "investor",
    "press-release",
    "quarter",
    "quarterly",
    "report",
    "results",
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
    if kind == "sec_submissions_json":
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
    for index, link in enumerate(_extract_links(body[:1_500_000], base_url=document.uri)):
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
        "report_date",
        "filing_date",
    ):
        value = link.get(key)
        if isinstance(value, str) and value:
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
    return []


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
    if not isinstance(recent, dict):
        return []
    accessions = _json_list(recent.get("accessionNumber"))
    forms = _json_list(recent.get("form"))
    primary_documents = _json_list(recent.get("primaryDocument"))
    report_dates = _json_list(recent.get("reportDate"))
    filing_dates = _json_list(recent.get("filingDate"))
    cik = _sec_cik_from_payload(payload, document=document, source=source)
    if not cik:
        return []
    target_years = [term for term in query_terms if term.isdigit() and len(term) == 4]
    wants_annual = _query_wants_annual_report(query_terms)
    candidates: list[JsonObject] = []
    for index, accession in enumerate(accessions[:200]):
        accession_number = str(accession or "").strip()
        compact = accession_number.replace("-", "")
        primary_document = _safe_sec_document_name(_list_get(primary_documents, index))
        form = str(_list_get(forms, index) or "").strip().upper()
        report_date = str(_list_get(report_dates, index) or "").strip()
        filing_date = str(_list_get(filing_dates, index) or "").strip()
        if not compact or not primary_document or not form:
            continue
        if not _sec_form_is_document_candidate(form=form, wants_annual=wants_annual):
            continue
        base_uri = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{compact}"
        title = _sec_submission_link_title(
            form=form,
            report_date=report_date,
            filing_date=filing_date,
            primary_document=primary_document,
        )
        score = _sec_submission_candidate_score(
            form=form,
            report_date=report_date,
            filing_date=filing_date,
            target_years=target_years,
            wants_annual=wants_annual,
        )
        if score <= 0:
            continue
        common = {
            "score": score,
            "matched_terms": _ordered_unique([form.lower(), *target_years, "sec", "filing", "10-k"])[:16],
            "source_family": "regulatory_filing",
            "sec_accession_number": accession_number,
            "sec_accession_compact": compact,
            "sec_primary_document": primary_document,
            "sec_form": form,
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
    candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("url") or "")))
    return candidates[:24]


def _sec_submission_link_title(*, form: str, report_date: str, filing_date: str, primary_document: str) -> str:
    pieces = [f"SEC {form} primary filing document"]
    if report_date:
        pieces.append(f"reportDate={report_date}")
    if filing_date:
        pieces.append(f"filed={filing_date}")
    pieces.append(primary_document)
    return " ".join(pieces)


def _sec_submission_candidate_score(
    *,
    form: str,
    report_date: str,
    filing_date: str,
    target_years: list[str],
    wants_annual: bool,
) -> float:
    normalized_form = form.upper().replace(" ", "")
    score = 0.8
    if normalized_form in {"10-K", "20-F", "40-F"}:
        score += 1.1
    elif normalized_form == "10-Q":
        score += 0.35
    if wants_annual and normalized_form not in {"10-K", "20-F", "40-F"}:
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
    return score


def _sec_form_is_document_candidate(*, form: str, wants_annual: bool) -> bool:
    normalized = form.upper().replace(" ", "")
    if normalized in {"10-K", "10-Q", "20-F", "40-F"}:
        return True
    if wants_annual:
        return False
    return normalized in {"8-K", "6-K"}


def _query_wants_annual_report(query_terms: list[str]) -> bool:
    return any(term in query_terms for term in {"annual", "fiscal", "fy2024", "10", "10k", "10-k"}) or any(
        term.isdigit() and len(term) == 4 for term in query_terms
    )


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
