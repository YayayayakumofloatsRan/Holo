from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE197_MARKET_RESEARCH_REPORT_ASSEMBLY_SCHEMA = "holo.stage197.market_research_report_assembly.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _first_report(rows: Any) -> dict[str, Any]:
    for row in _list_dicts(rows):
        report = _dict(row.get("stage173_market_research_report", {}))
        if report:
            return report
    return {}


def _citation_urls(report: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for citation in _list_dicts(report.get("citations", [])):
        url = str(citation.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _ordered_sources(*, promotion: dict[str, Any], report: dict[str, Any]) -> list[dict[str, Any]]:
    promoted_url = str(promotion.get("selected_url", "") or "").strip()
    promoted_family = str(promotion.get("source_family", "") or "").strip()
    citation_urls = _citation_urls(report)
    rows: list[dict[str, Any]] = []

    def add(url: str, *, selected: bool, family: str = "") -> None:
        text = str(url or "").strip()
        if not text or any(row["url"] == text for row in rows):
            return
        rows.append(
            {
                "url": text,
                "source_family": family,
                "rank": len(rows) + 1,
                "selected_by_promotion": bool(selected),
                "present_in_report_citations": text in citation_urls,
            }
        )

    add(promoted_url, selected=True, family=promoted_family)
    family_by_url = {
        str(citation.get("url", "") or ""): str(citation.get("source_family", "") or "")
        for citation in _list_dicts(report.get("citations", []))
    }
    for url in citation_urls:
        add(url, selected=False, family=family_by_url.get(url, ""))
    return rows


def _insufficient_report(question: str, missing: list[str]) -> dict[str, Any]:
    return {
        "status": "insufficient_evidence",
        "summary": _compact(
            "Insufficient current filing evidence to assemble a publication-grade market research report for "
            + (question or "the requested company")
            + "."
        ),
        "investment_recommendation": "not_provided",
        "missing_authority": missing,
    }


def _quality_score(*, promoted_url: str, report: dict[str, Any], source_promoted: bool) -> float:
    if not source_promoted:
        return 0.0
    score = 0.25
    if str(report.get("status", "") or "") == "evidence_ready":
        score += 0.3
    if promoted_url and promoted_url in _citation_urls(report):
        score += 0.35
    if int(report.get("unsupported_claim_count", 0) or 0) == 0:
        score += 0.1
    return round(min(1.0, score), 4)


def assemble_market_research_report(
    *,
    question: str,
    stage196_market_research_source_promotion: dict[str, Any] | None = None,
    stage173_market_research_report: dict[str, Any] | None = None,
    market_research_report_ledger: Any = None,
) -> dict[str, Any]:
    """Assemble a source-aware public report boundary from Stage196 and Stage173.

    Stage197 does not create new evidence. It checks whether the final market
    report actually cites the promoted authoritative source and degrades to an
    explicit insufficient-evidence report when source promotion is weak or
    blocked.
    """

    promotion = _dict(stage196_market_research_source_promotion)
    report = _dict(stage173_market_research_report) or _first_report(market_research_report_ledger)
    question_text = _compact(question, 260)
    promotion_status = str(promotion.get("status", "") or "")
    authority_status = str(promotion.get("authority_status", "") or "")
    source_family = str(promotion.get("source_family", "") or "")
    selected_url = str(promotion.get("selected_url", "") or "").strip()
    source_promoted = promotion_status == "promoted" and bool(selected_url)
    report_status = str(report.get("status", "") or "")
    report_ready = report_status == "evidence_ready"
    unsupported_count = int(report.get("unsupported_claim_count", 0) or 0) if report else 0
    citation_urls = _citation_urls(report)
    promoted_cited = bool(selected_url and selected_url in citation_urls)
    missing = [str(item) for item in list(promotion.get("missing_authority", []) or []) if str(item)]
    citation_status = "missing_report"
    status = "needs_report"
    stop_reason = "evidence_exhausted"
    final_ready = False

    if not promotion:
        status = "insufficient_evidence"
        citation_status = "weak"
        missing.append("stage196_market_research_source_promotion")
    elif not source_promoted:
        status = "blocked" if promotion_status in {"blocked", "failed"} else "insufficient_evidence"
        citation_status = "weak"
        stop_reason = str(promotion.get("canonical_stop_reason", "") or "evidence_exhausted")
    elif not report:
        status = "needs_report"
        citation_status = "missing_report"
        missing.append("stage173_market_research_report")
    elif not promoted_cited:
        status = "citation_mismatch"
        citation_status = "missing_promoted_source"
        missing.append("promoted_source_missing_from_report_citations")
    elif not report_ready or unsupported_count:
        status = "insufficient_evidence"
        citation_status = "sufficient" if promoted_cited else "weak"
        if unsupported_count:
            missing.append("unsupported_report_claims")
    else:
        status = "assembled"
        citation_status = "sufficient"
        stop_reason = "final_answer_ready"
        final_ready = True

    ordered_sources = _ordered_sources(promotion=promotion, report=report)
    score = _quality_score(promoted_url=selected_url, report=report, source_promoted=source_promoted)
    if citation_status == "missing_promoted_source":
        score = min(score, 0.45)
    if citation_status == "weak":
        score = min(score, 0.25)

    assembly = {
        "schema": STAGE197_MARKET_RESEARCH_REPORT_ASSEMBLY_SCHEMA,
        "assembly_id": "stage197_report_assembly:" + stable_digest(question_text, selected_url, status, limit=12),
        "status": status,
        "question": question_text,
        "final_report_ready": final_ready,
        "primary_source_url": selected_url,
        "source_promotion_status": promotion_status,
        "source_authority_status": authority_status,
        "source_family": source_family,
        "citation_quality_status": citation_status,
        "citation_quality_score": score,
        "ordered_sources": ordered_sources,
        "missing_requirements": sorted(set(missing)),
        "insufficient_evidence_report": _insufficient_report(question_text, sorted(set(missing))),
        "stage173_market_research_report": sanitize_public_metadata(report),
        "canonical_stop_reason": stop_reason,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
        "authority_boundary": {
            "provider_model_calls": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
            "live_network_required_for_tests": False,
        },
    }
    return sanitize_public_metadata(assembly)
