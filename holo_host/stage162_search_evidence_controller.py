from __future__ import annotations

from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now

STAGE162_SEARCH_CONTROLLER_SCHEMA = "holo.stage162.search_evidence_controller.v1"
STAGE162_SEARCH_SCORE_SCHEMA = "holo.stage162.search_evidence_score.v1"

OFFICIAL_HOST_MARKERS = (
    ".gov",
    ".edu",
    "openai.com",
    "developers.openai.com",
    "docs.openai.com",
    "deepseek.com",
    "api-docs.deepseek.com",
    "github.com/deepseek-ai",
    "anthropic.com",
    "docs.anthropic.com",
    "google.com",
    "ai.google.dev",
    "cloud.google.com",
    "microsoft.com",
    "learn.microsoft.com",
)


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _result_urls(results: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("url", "") or "").strip() for item in results if str(item.get("url", "") or "").strip()]


def _required_source_type(user_text: str, query: str) -> str:
    text = f"{user_text} {query}".lower()
    wants_official = any(marker in text for marker in ("official", "官网", "官方", "first-party", "source"))
    wants_docs = any(marker in text for marker in ("docs", "documentation", "文档", "api", "guide", "指南"))
    wants_current = any(marker in text for marker in ("latest", "current", "today", "最新", "当前", "今天"))
    if wants_official and wants_docs:
        return "official_docs"
    if wants_official:
        return "official"
    if wants_docs:
        return "docs"
    if wants_current:
        return "current"
    return "general"


def _query_terms(query: str) -> list[str]:
    raw = str(query or "").replace("/", " ").replace("-", " ").replace("_", " ")
    terms = []
    for item in raw.split():
        token = item.strip(".,;:!?()[]{}\"'`").lower()
        if len(token) < 2 or token in {"the", "and", "for", "with", "official", "docs", "documentation", "search"}:
            continue
        terms.append(token)
    return terms[:12]


def _is_official_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return any(marker in lowered for marker in OFFICIAL_HOST_MARKERS)


def _is_docs_url(url: str, title: str = "", snippet: str = "") -> bool:
    blob = f"{url} {title} {snippet}".lower()
    return any(marker in blob for marker in ("docs", "documentation", "api-docs", "/guide", "/guides", "/reference", "文档", "指南"))


def _normalize_search_response(
    response: dict[str, Any],
    *,
    action_type: str,
    query: str,
    attempt_index: int,
) -> dict[str, Any]:
    results = _list_dicts(response.get("results", []))
    source_urls = _result_urls(results)
    status = str(response.get("status", "") or ("ok" if results else "empty"))
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:" + stable_digest(action_type, query, str(attempt_index), status, ",".join(source_urls), limit=12),
        "action_type": action_type,
        "query": _compact(response.get("query", query), 180),
        "url": str(response.get("url", "") or ""),
        "pattern": "",
        "status": status,
        "provider": str(response.get("provider", "host") or "host"),
        "results": results,
        "source_urls": source_urls,
        "fetched_at": utc_now(),
        "error": _compact(response.get("error", ""), 180),
        "confidence": 0.0,
        "attempt_index": int(attempt_index),
    }


def build_search_evidence_plan(
    query: str,
    *,
    user_text: str = "",
    max_attempts: int = 3,
) -> dict[str, Any]:
    base = _compact(query, 180)
    required = _required_source_type(user_text, base)
    variants = [base]
    lowered = base.lower()
    if required in {"official", "official_docs"} and "official" not in lowered and "官方" not in base:
        variants.append(f"{base} official")
    if required in {"docs", "official_docs"} and "docs" not in lowered and "documentation" not in lowered and "文档" not in base:
        variants.append(f"{base} docs")
    if required == "official_docs" and len(variants) < max_attempts:
        variants.append(f"{base} official documentation")
    if required == "current" and "latest" not in lowered:
        variants.append(f"{base} latest")
    seen: set[str] = set()
    attempts: list[dict[str, Any]] = []
    for variant in variants:
        current = _compact(variant, 180)
        if not current or current.lower() in seen:
            continue
        seen.add(current.lower())
        attempts.append(
            {
                "attempt_index": len(attempts) + 1,
                "query": current,
                "purpose": "satisfy_" + required,
                "required_source_type": required,
            }
        )
        if len(attempts) >= max(1, int(max_attempts or 1)):
            break
    return {
        "schema": STAGE162_SEARCH_CONTROLLER_SCHEMA,
        "query": base,
        "user_text": _compact(user_text, 220),
        "required_source_type": required,
        "max_attempts": max(1, int(max_attempts or 1)),
        "attempts": attempts or [{"attempt_index": 1, "query": base, "purpose": "satisfy_general", "required_source_type": required}],
    }


def score_web_observation(
    observation: dict[str, Any],
    *,
    user_text: str = "",
    required_source_type: str = "",
) -> dict[str, Any]:
    row = dict(observation or {})
    results = _list_dicts(row.get("results", []))
    source_urls = list(row.get("source_urls", []) or []) or _result_urls(results)
    status = str(row.get("status", "") or "")
    query = str(row.get("query", "") or "")
    required = required_source_type or _required_source_type(user_text, query)
    official_count = sum(1 for url in source_urls if _is_official_url(str(url)))
    docs_count = sum(
        1
        for item in results
        if _is_docs_url(str(item.get("url", "") or ""), str(item.get("title", "") or ""), str(item.get("snippet", "") or ""))
    )
    text_blob = " ".join(
        [query]
        + [str(item.get("title", "")) for item in results]
        + [str(item.get("snippet", "")) for item in results]
        + [str(url) for url in source_urls]
    ).lower()
    terms = _query_terms(query)
    covered = [term for term in terms if term in text_blob]
    coverage = len(covered) / max(1, len(terms)) if terms else 0.2
    result_score = min(1.0, len(results) / 3.0) * 0.18
    source_score = min(1.0, len(source_urls) / 3.0) * 0.16
    official_score = min(1.0, official_count) * 0.24
    docs_score = min(1.0, docs_count) * 0.14
    coverage_score = coverage * 0.24
    status_score = 0.04 if status == "ok" else -0.18 if status in {"error", "failed"} else -0.08
    score = max(0.0, min(1.0, result_score + source_score + official_score + docs_score + coverage_score + status_score))
    missing: list[str] = []
    if status != "ok":
        missing.append("successful_status")
    if not source_urls:
        missing.append("source_urls")
    if required in {"official", "official_docs"} and official_count < 1:
        missing.append("official_source")
    if required in {"docs", "official_docs"} and docs_count < 1:
        missing.append("documentation_source")
    if coverage < 0.35:
        missing.append("query_term_coverage")
    sufficient_threshold = 0.72 if required in {"official", "official_docs"} else 0.58
    evidence_status = "sufficient" if status == "ok" and not missing and score >= sufficient_threshold else "weak" if status == "ok" and source_urls else "failed"
    return {
        "schema": STAGE162_SEARCH_SCORE_SCHEMA,
        "status": evidence_status,
        "required_source_type": required,
        "evidence_score": round(score, 4),
        "result_count": len(results),
        "source_count": len(source_urls),
        "official_source_count": official_count,
        "docs_source_count": docs_count,
        "query_term_coverage": round(coverage, 4),
        "covered_terms": covered,
        "missing_evidence": missing,
        "source_urls": source_urls[:8],
    }


def evaluate_search_evidence(
    observations: list[dict[str, Any]],
    *,
    query: str,
    user_text: str = "",
    required_source_type: str = "",
) -> dict[str, Any]:
    required = required_source_type or _required_source_type(user_text, query)
    scored: list[dict[str, Any]] = []
    for row in observations:
        score = dict(row.get("search_evidence", {})) if isinstance(row.get("search_evidence", {}), dict) else {}
        if not score:
            score = score_web_observation(row, user_text=user_text, required_source_type=required)
        scored.append(score)
    best = max(scored, key=lambda item: float(item.get("evidence_score", 0.0) or 0.0), default={})
    status = "sufficient" if str(best.get("status", "") or "") == "sufficient" else "needs_retry" if scored else "failed"
    if scored and not any(str(item.get("status", "") or "") == "sufficient" for item in scored):
        status = "failed" if all(str(row.get("status", "") or "") in {"error", "failed", "rejected_network_disabled"} for row in observations) else "needs_retry"
    return {
        "schema": STAGE162_SEARCH_CONTROLLER_SCHEMA,
        "query": _compact(query, 180),
        "required_source_type": required,
        "status": status,
        "observation_count": len(observations),
        "best_evidence_score": round(float(best.get("evidence_score", 0.0) or 0.0), 4),
        "best_source_urls": list(best.get("source_urls", []) or [])[:8],
        "missing_evidence": list(best.get("missing_evidence", []) or []),
        "stop_reason": "sufficient_evidence" if status == "sufficient" else "evidence_exhausted" if status == "failed" else "needs_retry",
    }


def run_search_evidence_controller(
    query: str,
    *,
    user_text: str = "",
    network_enabled: bool,
    web_search_fn: Callable[[str], dict[str, Any]],
    max_attempts: int = 3,
) -> dict[str, Any]:
    plan = build_search_evidence_plan(query, user_text=user_text, max_attempts=max_attempts)
    if not network_enabled:
        row = {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:" + stable_digest("network_disabled", query, limit=12),
            "action_type": "web_search",
            "query": _compact(query, 180),
            "url": "",
            "pattern": "",
            "status": "rejected_network_disabled",
            "provider": "network_gate",
            "results": [],
            "source_urls": [],
            "fetched_at": utc_now(),
            "error": "network_disabled",
            "confidence": 0.0,
            "attempt_index": 1,
        }
        row["search_evidence"] = score_web_observation(row, user_text=user_text, required_source_type=plan["required_source_type"])
        return {
            **plan,
            "status": "rejected",
            "attempt_count": 1,
            "observations": [row],
            "best_evidence_score": 0.0,
            "best_source_urls": [],
            "stop_reason": "network_disabled",
        }
    observations: list[dict[str, Any]] = []
    for attempt in list(plan.get("attempts", []) or []):
        attempt_query = str(attempt.get("query", "") or query)
        try:
            response = dict(web_search_fn(attempt_query))
        except Exception as exc:  # noqa: BLE001
            response = {"query": attempt_query, "status": "error", "results": [], "error": str(exc), "provider": "host"}
        row = _normalize_search_response(
            response,
            action_type="web_search",
            query=attempt_query,
            attempt_index=int(attempt.get("attempt_index", len(observations) + 1) or len(observations) + 1),
        )
        row["search_evidence"] = score_web_observation(row, user_text=user_text, required_source_type=plan["required_source_type"])
        row["confidence"] = float(row["search_evidence"].get("evidence_score", 0.0) or 0.0)
        observations.append(row)
        if row["search_evidence"]["status"] == "sufficient":
            break
    evaluation = evaluate_search_evidence(
        observations,
        query=query,
        user_text=user_text,
        required_source_type=plan["required_source_type"],
    )
    status = "sufficient" if evaluation["status"] == "sufficient" else "failed" if evaluation["status"] == "failed" else "weak"
    return {
        **plan,
        "status": status,
        "attempt_count": len(observations),
        "observations": observations,
        "best_evidence_score": evaluation["best_evidence_score"],
        "best_source_urls": evaluation["best_source_urls"],
        "missing_evidence": evaluation["missing_evidence"],
        "stop_reason": evaluation["stop_reason"],
    }
