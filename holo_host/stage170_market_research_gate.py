from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE170_MARKET_RESEARCH_NEED_SCHEMA = "holo.stage170.market_research_need.v1"
STAGE170_MARKET_RESEARCH_GATE_SCHEMA = "holo.stage170.market_research_gate.v1"
STAGE170_MARKET_RESEARCH_CLAIM_SCHEMA = "holo.stage170.market_research_claim.v1"

_FILING_RE = re.compile(r"\b(10-k|10-q|8-k|annual report|quarterly report|sec filing|filing|mda|md&a)\b", re.I)
_MARKET_RE = re.compile(r"\b(market research|fundamental|valuation|financial analysis|earnings|investor|revenue|income|risk factors)\b", re.I)
_CN_MARKET_RE = re.compile(r"(市场研究|基本面|财报|年报|季报|营收|收入|净利润|利润|风险因素|估值|投资)")
_MONEY_RE = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(billion|million|bn|m)?", re.I)

_METRIC_TERMS = {
    "net_sales": ("net sales", "revenue", "total revenue", "sales", "营收", "收入"),
    "net_income": ("net income", "net profit", "净利润", "净收入"),
    "operating_income": ("operating income", "营业利润", "经营利润"),
    "gross_margin": ("gross margin", "毛利率", "毛利"),
    "cash_and_cash_equivalents": ("cash and cash equivalents", "cash", "现金及现金等价物", "现金"),
}
_SECTION_TERMS = {
    "business": ("business", "业务"),
    "risk_factors": ("risk factors", "risk factor", "风险因素", "风险"),
    "mda": ("management's discussion", "md&a", "mda", "管理层讨论"),
    "financial_statements": ("financial statements", "财务报表"),
}
_INVESTMENT_TERMS = (
    "buy",
    "sell",
    "hold",
    "undervalued",
    "overvalued",
    "fair value",
    "target price",
    "recommend",
    "买入",
    "卖出",
    "持有",
    "低估",
    "高估",
    "目标价",
    "建议",
)


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def detect_market_research_need(text: str) -> dict[str, Any]:
    body = str(text or "")
    lowered = body.lower()
    reason_flags: list[str] = []
    if _FILING_RE.search(body):
        reason_flags.append("filing_analysis_possible")
    if _MARKET_RE.search(body) or _CN_MARKET_RE.search(body):
        reason_flags.append("financial_claim_possible")
    if any(term in lowered or term in body for terms in _METRIC_TERMS.values() for term in terms):
        if "financial_claim_possible" not in reason_flags:
            reason_flags.append("financial_claim_possible")
    if any(term in lowered or term in body for term in _INVESTMENT_TERMS):
        reason_flags.append("investment_judgment_possible")
    confidence = min(1.0, 0.24 * len(reason_flags) + (0.22 if "filing_analysis_possible" in reason_flags else 0.0))
    return {
        "schema": STAGE170_MARKET_RESEARCH_NEED_SCHEMA,
        "needs_market_research_pack": confidence >= 0.5,
        "reason_flags": reason_flags,
        "confidence": round(confidence, 4),
    }


def normalize_market_research_pack(
    value: Any = None,
    *,
    sidecar: dict[str, Any] | None = None,
    reply_debug: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    for candidate in (
        value,
        _dict(reply_debug).get("stage169_market_research_pack"),
        _dict(reply_debug).get("market_research_pack"),
        _dict(sidecar).get("stage169_market_research_pack"),
        _dict(sidecar).get("market_research_pack"),
        _dict(metadata).get("stage169_market_research_pack"),
        _dict(metadata).get("market_research_pack"),
    ):
        if isinstance(candidate, dict) and str(candidate.get("schema", "") or "").startswith("holo.stage169."):
            return dict(candidate)
    return {}


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|[。\n\r]+", str(text or ""))
    return [_compact(part, 400) for part in parts if part.strip()]


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(term in lowered or term in text for term in terms)


def _numbers(text: str) -> list[float]:
    values: list[float] = []
    for match in _MONEY_RE.finditer(text):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def extract_market_research_claims(text: str) -> list[dict[str, Any]]:
    claims: list[dict[str, Any]] = []
    for sentence_index, sentence in enumerate(_sentences(text)):
        for metric_key, terms in _METRIC_TERMS.items():
            if _contains_any(sentence, terms):
                claims.append(
                    {
                        "schema": STAGE170_MARKET_RESEARCH_CLAIM_SCHEMA,
                        "claim_id": "mrclaim:" + stable_digest("metric", str(sentence_index), metric_key, sentence, limit=12),
                        "claim_family": "financial_metric",
                        "claim_text": sentence,
                        "metric_key": metric_key,
                        "section_id": "",
                        "numbers": _numbers(sentence),
                    }
                )
        for section_id, terms in _SECTION_TERMS.items():
            if _contains_any(sentence, terms):
                claims.append(
                    {
                        "schema": STAGE170_MARKET_RESEARCH_CLAIM_SCHEMA,
                        "claim_id": "mrclaim:" + stable_digest("section", str(sentence_index), section_id, sentence, limit=12),
                        "claim_family": "filing_section",
                        "claim_text": sentence,
                        "metric_key": "",
                        "section_id": section_id,
                        "numbers": [],
                    }
                )
        if any(term in sentence.lower() or term in sentence for term in _INVESTMENT_TERMS):
            claims.append(
                {
                    "schema": STAGE170_MARKET_RESEARCH_CLAIM_SCHEMA,
                    "claim_id": "mrclaim:" + stable_digest("judgment", str(sentence_index), sentence, limit=12),
                    "claim_family": "investment_judgment",
                    "claim_text": sentence,
                    "metric_key": "",
                    "section_id": "",
                    "numbers": _numbers(sentence),
                }
            )
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for claim in claims:
        key = (str(claim.get("claim_family", "")), str(claim.get("metric_key", "")), str(claim.get("section_id", "")))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(claim)
    return deduped


def _metric_rows(pack: dict[str, Any]) -> list[dict[str, Any]]:
    return _list_dicts(_dict(pack.get("financial_metrics", {})).get("metrics", []))


def _section_rows_safe(pack: dict[str, Any]) -> list[dict[str, Any]]:
    return _list_dicts(_dict(pack.get("filing_sections", {})).get("sections", []))


def _evidence_items(pack: dict[str, Any]) -> list[dict[str, Any]]:
    return _list_dicts(pack.get("evidence_items", []))


def _urls_from_evidence(rows: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for row in rows:
        url = str(row.get("source_url", "") or "")
        if url and url not in urls:
            urls.append(url)
    return urls


def _metric_support(claim: dict[str, Any], pack: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    metric_key = str(claim.get("metric_key", "") or "")
    rows = [row for row in _metric_rows(pack) if str(row.get("metric_key", "") or "") == metric_key]
    if not rows:
        return "unsupported", [], [metric_key]
    claim_numbers = [float(value) for value in list(claim.get("numbers", []) or [])]
    if claim_numbers:
        matched = []
        for row in rows:
            try:
                value = float(row.get("value", 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
            if any(abs(value - number) <= max(0.05, abs(value) * 0.003) for number in claim_numbers):
                matched.append(row)
        if matched:
            return "supported", matched, []
        return "unsupported", rows, [metric_key + ":value_mismatch"]
    return "supported", rows, []


def _section_support(claim: dict[str, Any], pack: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    section_id = str(claim.get("section_id", "") or "")
    rows = [row for row in _section_rows_safe(pack) if str(row.get("section_id", "") or "") == section_id]
    if rows:
        return "supported", rows, []
    return "unsupported", [], [section_id]


def _claim_support(claim: dict[str, Any], pack: dict[str, Any]) -> tuple[str, list[dict[str, Any]], list[str]]:
    family = str(claim.get("claim_family", "") or "")
    if family == "financial_metric":
        return _metric_support(claim, pack)
    if family == "filing_section":
        return _section_support(claim, pack)
    if family == "investment_judgment":
        evidence = _evidence_items(pack)
        return ("weak", evidence[:4], ["investment_judgment_requires_analysis"]) if evidence else ("unsupported", [], ["investment_judgment"])
    return "unsupported", [], ["unknown_claim_family"]


def _pack_failure_reasons(pack: dict[str, Any]) -> list[str]:
    reasons = [str(item) for item in list(pack.get("failure_reasons", []) or []) if str(item).strip()]
    if str(_dict(pack.get("source_authority", {})).get("status", "") or "") not in {"", "sufficient"}:
        if "source_authority_insufficient" not in reasons:
            reasons.append("source_authority_insufficient")
    if str(_dict(pack.get("filing_checklist", {})).get("status", "") or "") not in {"", "complete"}:
        if "filing_checklist_incomplete" not in reasons:
            reasons.append("filing_checklist_incomplete")
    if str(_dict(pack.get("metric_consistency", {})).get("status", "") or "") == "conflicted":
        if "metric_conflict" not in reasons:
            reasons.append("metric_conflict")
    return reasons


def evaluate_market_research_answer(
    text: str,
    market_research_pack: Any = None,
    *,
    user_text: str = "",
) -> dict[str, Any]:
    pack = normalize_market_research_pack(market_research_pack)
    need = detect_market_research_need(" ".join([str(user_text or ""), str(text or "")]))
    claims = extract_market_research_claims(text)
    financial_claim_count = sum(1 for claim in claims if claim.get("claim_family") == "financial_metric")
    if not need["needs_market_research_pack"] and not claims:
        status = "not_required"
    elif not pack:
        status = "blocked_missing_pack"
    else:
        failure_reasons = _pack_failure_reasons(pack)
        if str(pack.get("status", "") or "") != "ready" or failure_reasons:
            status = "blocked_insufficient_pack"
        else:
            status = "supported"
    evaluated_claims: list[dict[str, Any]] = []
    supported_count = 0
    weak_count = 0
    unsupported_count = 0
    if pack and status not in {"blocked_insufficient_pack"}:
        for claim in claims:
            claim_status, evidence, missing = _claim_support(claim, pack)
            if claim_status == "supported":
                supported_count += 1
            elif claim_status == "weak":
                weak_count += 1
            else:
                unsupported_count += 1
            evaluated_claims.append(
                {
                    **claim,
                    "status": claim_status,
                    "matched_evidence_ids": [
                        str(row.get("metric_id", "") or row.get("evidence_id", "") or "") for row in evidence if str(row.get("metric_id", "") or row.get("evidence_id", "") or "")
                    ],
                    "source_urls": _urls_from_evidence(evidence),
                    "missing_evidence_keys": missing,
                }
            )
        if unsupported_count and status == "supported":
            status = "unsupported_financial_claim"
    else:
        for claim in claims:
            evaluated_claims.append(
                {
                    **claim,
                    "status": "unsupported",
                    "matched_evidence_ids": [],
                    "source_urls": [],
                    "missing_evidence_keys": [str(claim.get("metric_key") or claim.get("section_id") or claim.get("claim_family") or "claim")],
                }
            )
        unsupported_count = len(evaluated_claims)
    failure_reasons = ["market_research_pack_missing"] if status == "blocked_missing_pack" else _pack_failure_reasons(pack)
    repair_required = status in {"blocked_missing_pack", "blocked_insufficient_pack", "unsupported_financial_claim"}
    return {
        "schema": STAGE170_MARKET_RESEARCH_GATE_SCHEMA,
        "status": status,
        "needs_market_research_pack": bool(need["needs_market_research_pack"] or claims),
        "need_report": need,
        "pack_status": str(pack.get("status", "") or "missing") if pack else "missing",
        "pack_id": str(pack.get("pack_id", "") or "") if pack else "",
        "failure_reasons": failure_reasons,
        "claim_count": len(evaluated_claims),
        "financial_claim_count": financial_claim_count,
        "supported_claim_count": supported_count,
        "weak_claim_count": weak_count,
        "unsupported_claim_count": unsupported_count,
        "claims": evaluated_claims,
        "citation_required": bool(claims),
        "repair_required": repair_required,
        "created_at": utc_now(),
    }


def _supporting_citations(report: dict[str, Any], pack: dict[str, Any]) -> list[dict[str, str]]:
    citations: list[dict[str, str]] = []
    seen: set[str] = set()
    evidence_by_id: dict[str, dict[str, Any]] = {}
    for row in _metric_rows(pack):
        key = str(row.get("metric_id", "") or "")
        if key:
            evidence_by_id[key] = row
    for row in _evidence_items(pack):
        key = str(row.get("evidence_id", "") or "")
        if key:
            evidence_by_id[key] = row
    for claim in _list_dicts(report.get("claims", [])):
        if str(claim.get("status", "") or "") not in {"supported", "weak"}:
            continue
        for evidence_id in list(claim.get("matched_evidence_ids", []) or []):
            evidence = evidence_by_id.get(str(evidence_id), {})
            url = str(evidence.get("source_url", "") or "")
            if not evidence_id or evidence_id in seen:
                continue
            seen.add(str(evidence_id))
            citations.append(
                {
                    "evidence_id": str(evidence_id),
                    "url": url,
                    "snippet": _compact(evidence.get("snippet", ""), 180),
                }
            )
    if not citations:
        for evidence in _evidence_items(pack)[:3]:
            evidence_id = str(evidence.get("evidence_id", "") or "")
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                citations.append(
                    {
                        "evidence_id": evidence_id,
                        "url": str(evidence.get("source_url", "") or ""),
                        "snippet": _compact(evidence.get("snippet", ""), 180),
                    }
                )
    return citations


def repair_market_research_answer(
    text: str,
    gate_report: dict[str, Any],
    *,
    market_research_pack: Any = None,
    channel: str = "",
) -> str:
    status = str(gate_report.get("status", "") or "")
    compact_channel = str(channel or "") in {"wechat", "sms"}
    if status == "blocked_missing_pack":
        return (
            "I do not have a source-authority-sufficient filing pack yet, so I cannot state financial conclusions as settled."
            if not compact_channel
            else "I do not have enough filing evidence to state that financial conclusion."
        )
    if status == "blocked_insufficient_pack":
        reasons = ", ".join(str(item) for item in list(gate_report.get("failure_reasons", []) or [])) or "insufficient evidence"
        return (
            f"The available market-research pack is not sufficient for a settled financial answer: {reasons}."
            if not compact_channel
            else f"The filing evidence is insufficient: {reasons}."
        )
    if status == "unsupported_financial_claim":
        return (
            "The market-research pack does not support that specific financial detail. I should not state it as settled."
            if not compact_channel
            else "The filing pack does not support that exact financial detail."
        )
    if status == "supported":
        pack = normalize_market_research_pack(market_research_pack)
        if not pack:
            return str(text or "")
        citations = _supporting_citations(gate_report, pack)
        if not citations:
            return str(text or "")
        if any(citation["url"] and citation["url"] in str(text or "") for citation in citations):
            return str(text or "")
        lines = [str(text or "").strip(), "", "Evidence:"]
        for index, citation in enumerate(citations[:4], start=1):
            url = citation["url"] or "source_url_unavailable"
            evidence_id = citation["evidence_id"] or "evidence_id_unavailable"
            snippet = citation["snippet"]
            lines.append(f"[{index}] {evidence_id} {url}" + (f" - {snippet}" if snippet else ""))
        return "\n".join(line for line in lines if line is not None).strip()
    return str(text or "")
