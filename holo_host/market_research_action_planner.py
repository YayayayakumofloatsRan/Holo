from __future__ import annotations

from typing import Any

from .common import compact_text, stable_digest, utc_now

STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA = "holo.stage193.market_research_action_plan.v1"
STAGE193_MARKET_RESEARCH_ACTION_CANDIDATE_SCHEMA = "holo.stage193.market_research_action_candidate.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _first_ledger_payload(rows: Any, key: str) -> dict[str, Any]:
    for row in _list_dicts(rows):
        payload = row.get(key, {})
        if isinstance(payload, dict):
            return dict(payload)
    return {}


def _entity_terms(question: str, pack: dict[str, Any]) -> dict[str, str]:
    entity = _dict(pack.get("entity", {}))
    ticker = str(entity.get("ticker", "") or "").strip().upper()
    company = str(entity.get("company", "") or entity.get("entity_name", "") or "").strip()
    if not ticker:
        text = f" {question} "
        for candidate in ("AAPL", "MSFT", "NVDA", "TSLA", "GOOGL", "GOOG", "AMZN", "META"):
            if f" {candidate} " in text.upper():
                ticker = candidate
                break
    if not company and ticker == "AAPL":
        company = "Apple"
    if not company:
        company = ticker or _compact(question, 64)
    return {"ticker": ticker, "company": company}


def _source_url(pack: dict[str, Any]) -> str:
    authority = _dict(pack.get("source_authority", {}))
    url = str(authority.get("selected_url", "") or authority.get("source_url", "") or "").strip()
    if url:
        return url
    for item in _list_dicts(pack.get("evidence_items", [])):
        url = str(item.get("source_url", "") or "").strip()
        if url:
            return url
    return ""


def _candidate(
    *,
    action_type: str,
    priority: float,
    reason: str,
    expected_observation: str,
    query: str = "",
    url: str = "",
    arguments: dict[str, Any] | None = None,
    required_source_family: str = "",
    can_execute_now: bool = True,
    blocked_reason: str = "",
) -> dict[str, Any]:
    digest = stable_digest(action_type, query, url, repr(arguments or {}), reason, limit=12)
    row = {
        "schema": STAGE193_MARKET_RESEARCH_ACTION_CANDIDATE_SCHEMA,
        "action_id": f"stage193_action:{digest}",
        "action_type": action_type,
        "priority": round(max(0.0, min(1.0, float(priority or 0.0))), 4),
        "query": _compact(query, 220),
        "url": url.strip(),
        "arguments": dict(arguments or {}),
        "required_source_family": required_source_family,
        "reason": _compact(reason, 260),
        "expected_observation": _compact(expected_observation, 240),
        "can_execute_now": bool(can_execute_now),
        "blocked_reason": blocked_reason,
    }
    return row


def _finalize_candidate(report: dict[str, Any]) -> dict[str, Any]:
    return _candidate(
        action_type="finalize_report",
        priority=1.0,
        arguments={"report_id": str(report.get("report_id", "") or "")},
        reason="Stage192 marked the filing-grounded report as ready.",
        expected_observation="final market research answer can be delivered from the existing report.",
        can_execute_now=True,
    )


def _authority_search_candidates(
    *,
    question: str,
    pack: dict[str, Any],
    network_enabled: bool,
) -> list[dict[str, Any]]:
    terms = _entity_terms(question, pack)
    ticker = terms["ticker"]
    company = terms["company"]
    base = f"{company} {ticker} 2024 Form 10-K SEC filing".strip()
    can_fetch = bool(network_enabled)
    blocked = "" if can_fetch else "network_disabled"
    return [
        _candidate(
            action_type="web_search",
            priority=1.0,
            query=f"site:sec.gov {base}",
            required_source_family="financial_filing",
            reason="Stage192 reported insufficient financial-filing source authority; search SEC first.",
            expected_observation="SEC filing URL and source-authority-sufficient web observation.",
            can_execute_now=can_fetch,
            blocked_reason=blocked,
        ),
        _candidate(
            action_type="web_search",
            priority=0.74,
            query=f"{company} investor relations annual report 2024 10-K",
            required_source_family="financial_filing",
            reason="Investor-relations annual report is a first-party fallback when SEC retrieval is incomplete.",
            expected_observation="company IR annual report or 10-K filing page.",
            can_execute_now=can_fetch,
            blocked_reason=blocked,
        ),
    ]


def build_market_research_action_plan(
    *,
    question: str,
    stage192_market_research_feedback_loop: dict[str, Any] | None = None,
    market_research_pack: dict[str, Any] | None = None,
    market_research_report: dict[str, Any] | None = None,
    market_research_pack_ledger: Any = None,
    market_research_report_ledger: Any = None,
    remaining_action_budget: int = 1,
    network_enabled: bool = True,
) -> dict[str, Any]:
    """Convert Stage192 market feedback into concrete next host actions.

    This is a planning layer only. It does not call providers, fetch the web,
    mutate memory, or execute host tools.
    """

    feedback = _dict(stage192_market_research_feedback_loop)
    pack = _dict(market_research_pack) or _first_ledger_payload(market_research_pack_ledger, "stage169_market_research_pack")
    report = _dict(market_research_report) or _first_ledger_payload(market_research_report_ledger, "stage173_market_research_report")
    unresolved = [str(item) for item in list(feedback.get("unresolved_items", []) or []) if str(item or "").strip()]
    budget = max(0, int(remaining_action_budget or 0))
    feedback_next = str(feedback.get("next_action", "") or "").strip()
    can_finalize = bool(feedback.get("can_finalize", False)) or feedback_next == "finalize_report"

    candidates: list[dict[str, Any]]
    next_action = feedback_next or "market_research_pack"
    status = "planned"
    stop_reason = "action_plan_ready"
    reason = str(feedback.get("public_loop_summary", "") or "Stage192 requested another market-research action.")

    if can_finalize:
        next_action = "finalize_report"
        status = "no_action_needed"
        stop_reason = "report_ready"
        candidates = [_finalize_candidate(report)]
    elif budget <= 0:
        status = "exhausted"
        next_action = feedback_next or "report_insufficient_evidence"
        stop_reason = "evidence_exhausted"
        candidates = [
            _candidate(
                action_type=next_action,
                priority=0.2,
                arguments={"budget": budget},
                reason="Stage192 still has unresolved evidence needs, but no action budget remains.",
                expected_observation="operator must increase budget or accept an insufficient-evidence report.",
                can_execute_now=False,
                blocked_reason="action_budget_exhausted",
            )
        ]
    elif any(item.startswith("source_authority:") for item in unresolved):
        next_action = "web_search"
        candidates = _authority_search_candidates(question=question, pack=pack, network_enabled=network_enabled)
        if not network_enabled:
            status = "blocked"
            stop_reason = "boundary_or_permission"
    elif feedback_next == "market_research_report" or str(report.get("status", "") or "") != "evidence_ready":
        next_action = "market_research_report"
        candidates = [
            _candidate(
                action_type="market_research_report",
                priority=0.88,
                arguments={"pack_id": str(pack.get("pack_id", "") or ""), "question": question},
                reason="The filing pack is ready enough, but Stage192 still needs a report synthesis.",
                expected_observation="market research report with sections, metrics, citations, and unsupported-claim accounting.",
                can_execute_now=True,
            )
        ]
    elif "filing_checklist" in unresolved or "financial_metrics" in unresolved:
        url = _source_url(pack)
        if url:
            next_action = "filing_text_retrieval"
            candidates = [
                _candidate(
                    action_type="filing_text_retrieval",
                    priority=0.92,
                    url=url,
                    required_source_family="financial_filing",
                    arguments={"source_url": url, "filing_type": "10-K"},
                    reason="The source is usable but filing sections or metrics are incomplete.",
                    expected_observation="full filing text with Item 1, 1A, 7, and 8 evidence.",
                    can_execute_now=True,
                )
            ]
        else:
            next_action = "market_research_pack"
            candidates = [
                _candidate(
                    action_type="market_research_pack",
                    priority=0.82,
                    arguments={"query": question, "requires_filing_text": True},
                    required_source_family="financial_filing",
                    reason="The pack is incomplete and no reusable filing URL is available.",
                    expected_observation="rebuilt market research pack with complete filing checklist.",
                    can_execute_now=True,
                )
            ]
    else:
        next_action = "market_research_pack"
        candidates = [
            _candidate(
                action_type="market_research_pack",
                priority=0.7,
                arguments={"query": question},
                required_source_family="financial_filing",
                reason="Stage192 requested more market-research evidence.",
                expected_observation="rebuilt market research pack.",
                can_execute_now=True,
            )
        ]

    if status == "planned" and candidates and not any(bool(item.get("can_execute_now", False)) for item in candidates):
        status = "blocked"
        stop_reason = "boundary_or_permission"

    return {
        "schema": STAGE193_MARKET_RESEARCH_ACTION_PLAN_SCHEMA,
        "status": status,
        "goal": _compact(question, 260),
        "next_action": next_action,
        "action_candidates": candidates,
        "candidate_count": len(candidates),
        "stop_reason": stop_reason,
        "can_finalize": bool(can_finalize),
        "unresolved_items": unresolved,
        "reason": _compact(reason, 260),
        "remaining_action_budget": budget,
        "network_enabled": bool(network_enabled),
        "planning_only": True,
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
