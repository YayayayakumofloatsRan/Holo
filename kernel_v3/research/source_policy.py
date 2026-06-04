from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile, SourceAssessment

if TYPE_CHECKING:
    from kernel_v3.retrieval.contracts import EvidenceItem, SearchSource


_FAMILY_SCORES = {
    "regulatory_filing": 0.98,
    "structured_regulatory_data": 0.97,
    "exchange_filing": 0.94,
    "company_ir": 0.9,
    "earnings_release": 0.88,
    "government_statistic": 0.86,
    "central_bank_statistic": 0.86,
    "treasury_data": 0.86,
    "fund_disclosure": 0.84,
    "standards_body": 0.92,
    "official_documentation": 0.88,
    "official_guidance": 0.86,
    "source_repository": 0.82,
    "scholarly_preprint": 0.88,
    "scholarly_publisher": 0.86,
    "academic_repository": 0.8,
    "scholarly_index": 0.72,
    "market_data_provider": 0.72,
    "portfolio_risk_data_provider": 0.7,
    "credit_rating_agency": 0.66,
    "earnings_transcript": 0.62,
    "reputable_news": 0.58,
    "analyst_report": 0.5,
    "blog": 0.24,
    "forum": 0.18,
    "social": 0.15,
    "encyclopedia": 0.22,
    "reference_dictionary": 0.12,
    "generic_web": 0.3,
    "unknown": 0.2,
}

_REGULATORY_DOMAINS = {
    "api.company-information.service.gov.uk",
    "disclosure2.edinet-fsa.go.jp",
    "find-and-update.company-information.service.gov.uk",
    "sec.gov",
    "sedarplus.ca",
    "www.sec.gov",
    "www.sedarplus.ca",
    "edgar.sec.gov",
}
_STRUCTURED_REGULATORY_DOMAINS = {
    "data.sec.gov",
}
_EXCHANGE_DOMAINS = {
    "asx.com.au",
    "cninfo.com.cn",
    "www.cninfo.com.cn",
    "static.cninfo.com.cn",
    "sse.com.cn",
    "www.sse.com.cn",
    "static.sse.com.cn",
    "szse.cn",
    "www.szse.cn",
    "disclosure.szse.cn",
    "nasdaq.com",
    "www.nasdaq.com",
    "nyse.com",
    "www.nyse.com",
    "hkexnews.hk",
    "www.hkexnews.hk",
    "londonstockexchange.com",
    "www.londonstockexchange.com",
    "sgx.com",
    "www.asx.com.au",
    "www.sgx.com",
}
_GOVERNMENT_STAT_DOMAINS = {
    "bea.gov",
    "bis.org",
    "data.worldbank.org",
    "www.bea.gov",
    "bls.gov",
    "imf.org",
    "oecd.org",
    "www.bls.gov",
    "www.bis.org",
    "www.imf.org",
    "www.oecd.org",
    "www.worldbank.org",
    "fred.stlouisfed.org",
    "worldbank.org",
}
_CENTRAL_BANK_DOMAINS = {
    "bankofengland.co.uk",
    "boj.or.jp",
    "data.ecb.europa.eu",
    "ecb.europa.eu",
    "federalreserve.gov",
    "pbc.gov.cn",
    "www.bankofengland.co.uk",
    "www.boj.or.jp",
    "www.ecb.europa.eu",
    "www.federalreserve.gov",
    "www.pbc.gov.cn",
}
_TREASURY_DOMAINS = {
    "fiscaldata.treasury.gov",
    "home.treasury.gov",
    "treasury.gov",
    "www.treasury.gov",
}
_FUND_DISCLOSURE_DOMAINS = {
    "blackrock.com",
    "ishares.com",
    "investor.vanguard.com",
    "ssga.com",
    "vanguard.com",
    "www.blackrock.com",
    "www.ishares.com",
    "www.ssga.com",
}
_MARKET_DATA_DOMAINS = {
    "finance.yahoo.com",
    "eastmoney.com",
    "www.eastmoney.com",
    "google.com",
    "www.google.com",
    "investing.com",
    "www.investing.com",
    "marketwatch.com",
    "www.marketwatch.com",
    "markets.businessinsider.com",
    "www.markets.businessinsider.com",
    "macrotrends.net",
    "www.macrotrends.net",
    "tradingview.com",
    "www.tradingview.com",
}
_CREDIT_RATING_DOMAINS = {
    "fitchratings.com",
    "moodys.com",
    "spglobal.com",
    "www.fitchratings.com",
    "www.moodys.com",
    "www.spglobal.com",
}
_EARNINGS_TRANSCRIPT_DOMAINS = {
    "fool.com",
    "marketscreener.com",
    "seekingalpha.com",
    "www.fool.com",
    "www.marketscreener.com",
    "www.seekingalpha.com",
}
_REPUTABLE_NEWS_DOMAINS = {
    "apnews.com",
    "www.apnews.com",
    "reuters.com",
    "www.reuters.com",
    "bloomberg.com",
    "www.bloomberg.com",
    "cnbc.com",
    "www.cnbc.com",
    "wsj.com",
    "www.wsj.com",
    "ft.com",
    "www.ft.com",
}
_STANDARDS_BODY_DOMAINS = {
    "ietf.org",
    "www.ietf.org",
    "rfc-editor.org",
    "www.rfc-editor.org",
    "w3.org",
    "www.w3.org",
    "iso.org",
    "www.iso.org",
    "nist.gov",
    "www.nist.gov",
}
_SOURCE_REPOSITORY_DOMAINS = {
    "github.com",
    "www.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
}
_SCHOLARLY_PREPRINT_DOMAINS = {
    "arxiv.org",
    "export.arxiv.org",
    "biorxiv.org",
    "www.biorxiv.org",
    "medrxiv.org",
    "www.medrxiv.org",
    "ssrn.com",
    "www.ssrn.com",
}
_ACADEMIC_REPOSITORY_DOMAINS = {
    "hal.science",
    "zenodo.org",
    "figshare.com",
    "osf.io",
    "repository.ias.ac.in",
}
_SCHOLARLY_INDEX_DOMAINS = {
    "api.semanticscholar.org",
    "semanticscholar.org",
    "www.semanticscholar.org",
    "openalex.org",
    "api.openalex.org",
    "crossref.org",
    "www.crossref.org",
    "search.crossref.org",
    "dblp.org",
    "www.dblp.org",
    "doi.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "zbmath.org",
    "mathscinet.ams.org",
}
_SCHOLARLY_PUBLISHER_DOMAINS = {
    "acm.org",
    "dl.acm.org",
    "ams.org",
    "www.ams.org",
    "annals.math.princeton.edu",
    "cambridge.org",
    "www.cambridge.org",
    "ems.press",
    "epubs.siam.org",
    "ieee.org",
    "ieeexplore.ieee.org",
    "jmlr.org",
    "www.jmlr.org",
    "link.springer.com",
    "nature.com",
    "www.nature.com",
    "pnas.org",
    "www.pnas.org",
    "projecteuclid.org",
    "www.projecteuclid.org",
    "sciencedirect.com",
    "www.sciencedirect.com",
    "springer.com",
    "www.springer.com",
    "tandfonline.com",
    "www.tandfonline.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
}
_REFERENCE_DICTIONARY_DOMAINS = {
    "dictionary.cambridge.org",
    "merriam-webster.com",
    "www.merriam-webster.com",
    "dictionary.com",
    "www.dictionary.com",
    "collinsdictionary.com",
    "www.collinsdictionary.com",
}
_ENCYCLOPEDIA_DOMAINS = {
    "britannica.com",
    "www.britannica.com",
    "wikipedia.org",
    "en.wikipedia.org",
    "zh.wikipedia.org",
    "www.wikipedia.org",
}


def assess_search_source(source: "SearchSource", *, profile: ResearchProfile) -> SourceAssessment:
    family, classification_reason = classify_source_family(
        uri=source.uri,
        title=source.title,
        metadata=source.metadata,
    )
    return _build_assessment(
        source_id=source.source_id,
        uri=source.uri,
        family=family,
        classification_reason=classification_reason,
        profile=profile,
        metadata={**_assessment_source_metadata(source.metadata), "provider": source.provider},
    )


def assess_evidence_source(item: "EvidenceItem", *, profile: ResearchProfile) -> SourceAssessment:
    existing = item.diagnostics.get("source_assessment")
    if isinstance(existing, dict):
        try:
            return SourceAssessment.from_dict(existing)
        except Exception:
            pass
    family, classification_reason = classify_source_family(uri=item.uri, title=item.title, metadata={})
    return _build_assessment(
        source_id=item.source_id,
        uri=item.uri,
        family=family,
        classification_reason=classification_reason,
        profile=profile,
        metadata={"provider": str(item.diagnostics.get("provider", "retrieval"))},
    )


def _build_assessment(
    *,
    source_id: str,
    uri: str,
    family: str,
    classification_reason: str,
    profile: ResearchProfile,
    metadata: JsonObject,
) -> SourceAssessment:
    score = _FAMILY_SCORES.get(family, _FAMILY_SCORES["unknown"])
    usable_as_primary = family in profile.primary_source_families and score >= profile.minimum_primary_authority_score
    if usable_as_primary:
        level = "primary"
    elif family in profile.secondary_source_families:
        level = "secondary"
    else:
        level = "weak"
    warnings = []
    if not usable_as_primary:
        warnings.append("not_primary_source_for_profile")
    if family in profile.weak_source_families:
        warnings.append("weak_source_family")
    return SourceAssessment(
        assessment_id="srcassess-" + _hash({"profile": profile.profile_id, "source_id": source_id, "uri": uri})[:16],
        profile_id=profile.profile_id,
        source_id=source_id,
        uri=uri,
        source_family=family,
        authority_level=level,
        authority_score=score,
        usable_as_primary=usable_as_primary,
        reasons=[classification_reason, f"authority_level:{level}"],
        warnings=warnings,
        metadata=metadata,
    )


def classify_source_family(*, uri: str, title: str, metadata: JsonObject | None = None) -> tuple[str, str]:
    metadata = metadata or {}
    explicit = metadata.get("source_family")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip(), "metadata_source_family"

    parsed = urlparse(uri)
    host = parsed.netloc.lower().split("@")[-1].split(":")[0]
    path = parsed.path.lower()
    title_l = title.lower()

    if _host_matches(host, _REFERENCE_DICTIONARY_DOMAINS):
        return "reference_dictionary", "recognized_reference_dictionary_domain"
    if _host_matches(host, _ENCYCLOPEDIA_DOMAINS):
        return "encyclopedia", "recognized_encyclopedia_domain"
    if _host_matches(host, _STRUCTURED_REGULATORY_DOMAINS):
        return "structured_regulatory_data", "recognized_structured_regulatory_domain"
    if _host_matches(host, _REGULATORY_DOMAINS):
        return "regulatory_filing", "recognized_regulatory_domain"
    if _host_matches(host, _EXCHANGE_DOMAINS):
        return "exchange_filing", "recognized_exchange_domain"
    if _host_matches(host, _CENTRAL_BANK_DOMAINS):
        return "central_bank_statistic", "recognized_central_bank_domain"
    if _host_matches(host, _TREASURY_DOMAINS):
        return "treasury_data", "recognized_treasury_domain"
    if _host_matches(host, _GOVERNMENT_STAT_DOMAINS):
        return "government_statistic", "recognized_government_statistic_domain"
    if _host_matches(host, _FUND_DISCLOSURE_DOMAINS):
        return "fund_disclosure", "recognized_fund_disclosure_domain"
    if _host_matches(host, _STANDARDS_BODY_DOMAINS):
        return "standards_body", "recognized_standards_body_domain"
    if _host_matches(host, _SOURCE_REPOSITORY_DOMAINS):
        return "source_repository", "recognized_source_repository_domain"
    if _host_matches(host, _SCHOLARLY_PREPRINT_DOMAINS):
        return "scholarly_preprint", "recognized_scholarly_preprint_domain"
    if _host_matches(host, _ACADEMIC_REPOSITORY_DOMAINS):
        return "academic_repository", "recognized_academic_repository_domain"
    if _host_matches(host, _SCHOLARLY_INDEX_DOMAINS):
        return "scholarly_index", "recognized_scholarly_index_domain"
    if _host_matches(host, _SCHOLARLY_PUBLISHER_DOMAINS):
        return "scholarly_publisher", "recognized_scholarly_publisher_domain"
    if _host_matches(host, _MARKET_DATA_DOMAINS):
        return "market_data_provider", "recognized_market_data_domain"
    if _host_matches(host, _CREDIT_RATING_DOMAINS):
        return "credit_rating_agency", "recognized_credit_rating_domain"
    if _host_matches(host, _EARNINGS_TRANSCRIPT_DOMAINS):
        return "earnings_transcript", "recognized_earnings_transcript_domain"
    if _host_matches(host, _REPUTABLE_NEWS_DOMAINS):
        return "reputable_news", "recognized_reputable_news_domain"
    if _looks_like_company_ir(host, path):
        return "company_ir", "recognized_company_ir_pattern"
    if _looks_like_official_documentation(host=host, path=path, title=title_l):
        return "official_documentation", "recognized_official_documentation_surface"
    if _looks_like_scholarly_surface(host=host, path=path, title=title_l):
        return "scholarly_publisher", "recognized_scholarly_surface"
    if "10-k" in title_l or "10 k" in title_l or "annual report" in title_l:
        return "generic_web", "untrusted_domain_mentions_primary_document"
    if "earnings release" in title_l or "quarterly results" in title_l:
        return "generic_web", "untrusted_domain_mentions_earnings_release"
    if host:
        return "generic_web", "unrecognized_web_domain"
    return "unknown", "missing_domain"


def source_authority_summary(assessments: list[SourceAssessment]) -> JsonObject:
    primary = [item for item in assessments if item.usable_as_primary]
    secondary = [item for item in assessments if item.authority_level == "secondary"]
    weak = [item for item in assessments if item.authority_level == "weak"]
    return {
        "primary_source_count": len(primary),
        "secondary_source_count": len(secondary),
        "weak_source_count": len(weak),
        "best_authority_score": max([item.authority_score for item in assessments], default=0.0),
        "source_families": [item.source_family for item in assessments],
    }


def _host_matches(host: str, domains: set[str]) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _looks_like_company_ir(host: str, path: str) -> bool:
    labels = host.split(".")
    return "investor" in labels or "investors" in labels or "ir" in labels or "/investor" in path or "/ir/" in path


def _looks_like_official_documentation(*, host: str, path: str, title: str) -> bool:
    if host.startswith("docs.") or host.startswith("developer.") or host.startswith("developers."):
        return True
    if any(part in path for part in ("/docs", "/documentation", "/api-reference", "/reference", "/developers")):
        return True
    return any(marker in title for marker in ("documentation", "docs", "api reference", "developer docs"))


def _looks_like_scholarly_surface(*, host: str, path: str, title: str) -> bool:
    if any(part in path for part in ("/abs/", "/paper/", "/papers/", "/article/", "/articles/", "/journal/", "/doi/")):
        return True
    scholarly_title_markers = (
        "journal",
        "proceedings",
        "conference",
        "arxiv",
        "doi",
        "preprint",
        "paper",
        "article",
        "transactions on",
    )
    return any(marker in title for marker in scholarly_title_markers)


def _hash(payload: JsonObject) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _assessment_source_metadata(metadata: JsonObject | None) -> JsonObject:
    if not isinstance(metadata, dict):
        return {}
    allowed = {
        "authority_level",
        "cik",
        "corpus_source_id",
        "exchange",
        "query_template_id",
        "report_date",
        "sec_accession_number",
        "sec_cik",
        "sec_form",
        "sec_primary_document",
        "source_family",
        "source_id",
        "source_kind",
        "ticker",
    }
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed and isinstance(value, (str, int, float, bool)) and str(value)
    }
