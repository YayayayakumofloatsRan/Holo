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
    "market_data_provider": 0.72,
    "portfolio_risk_data_provider": 0.7,
    "credit_rating_agency": 0.66,
    "earnings_transcript": 0.62,
    "reputable_news": 0.58,
    "analyst_report": 0.5,
    "blog": 0.24,
    "forum": 0.18,
    "social": 0.15,
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
