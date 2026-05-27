from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .agent_self_feedback_loop import build_self_feedback_report, evaluate_crawler_feedback_step
from .kernel_metadata_sanitizer import PRIVATE_KEYS, sanitize_public_metadata
from .stage168_source_authority import evaluate_source_authority
from .stage151_tool_decision_loop import default_open_page, default_web_search
from .stage163_page_evidence_verifier import verify_page_evidence_for_search

STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA = "holo.stage186.live_crawler_search.v1"
STAGE186_CRAWLER_LEDGER_SCHEMA = "holo.stage186.crawler_ledger.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage186" / "stage186_live_crawler_search.html"

_SEARCH_PREFIX_RE = re.compile(
    r"^\s*(please\s+)?(search|look\s+up|find|crawl|browse|联网搜索|联网检索|外网检索|搜索一下|搜索|检索|查一下|查找|爬取)\s*",
    re.IGNORECASE,
)
_SOURCE_SUFFIX_RE = re.compile(r"(并(告诉我|给出)?来源|并给出来源|and cite sources|with sources)\s*$", re.IGNORECASE)
_NOISE_RE = re.compile(r"\s+")
_FINANCIAL_TASK_RE = re.compile(r"\b(10-k|10-q|8-k|annual report|quarterly report|sec|filing|financial|investor|earnings|fundamental)\b|财报|年报|基本面|证监|监管披露", re.IGNORECASE)


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(_NOISE_RE.sub(" ", str(value or "")).strip(), limit)


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _source_urls(results: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for item in results:
        url = str(item.get("url", "") or "").strip()
        if url and url not in urls:
            urls.append(url)
    return urls


def _task_type_for_query(user_text: str) -> str:
    return "market_research" if _FINANCIAL_TASK_RE.search(str(user_text or "")) else ""


def _authority_gate_required(authority_report: dict[str, Any]) -> bool:
    return bool(str(authority_report.get("required_source_family", "") or "").strip())


def _authority_sufficient(authority_report: dict[str, Any]) -> bool:
    return str(authority_report.get("status", "") or "") == "sufficient"


def _strip_query(user_text: str) -> str:
    text = _compact(user_text, 220)
    text = _SEARCH_PREFIX_RE.sub("", text).strip(" ：:，,。.!?？")
    text = _SOURCE_SUFFIX_RE.sub("", text).strip(" ：:，,。.!?？")
    replacements = {
        "官方文档": "official docs",
        "官方": "official",
        "官网": "official site",
        "文档": "docs",
        "最新": "latest",
        "财报": "annual report",
        "年报": "annual report",
    }
    for source, target in replacements.items():
        text = text.replace(source, f" {target} ")
    return _compact(text, 180) or _compact(user_text, 180)


def build_crawler_query_plan(user_text: str, *, max_queries: int = 3) -> list[dict[str, Any]]:
    query = _strip_query(user_text)
    lowered = query.lower()
    wants_official = "official" in lowered or "官网" in user_text or "官方" in user_text
    wants_docs = "docs" in lowered or "documentation" in lowered or "文档" in user_text
    wants_latest = "latest" in lowered or "current" in lowered or "最新" in user_text

    variants: list[tuple[str, str]] = [(query, "base_query")]
    base_without_qualifiers = _compact(
        re.sub(r"\b(official|docs|documentation|latest|current|site|annual report)\b", " ", query, flags=re.IGNORECASE),
        180,
    )
    if base_without_qualifiers and base_without_qualifiers.lower() != query.lower():
        variants.insert(0, (base_without_qualifiers, "broad_first"))
    if wants_official and "official" not in base_without_qualifiers.lower():
        variants.append((_compact(f"{base_without_qualifiers or query} official", 180), "official_source"))
    if wants_docs and "docs" not in base_without_qualifiers.lower():
        variants.append((_compact(f"{base_without_qualifiers or query} docs", 180), "documentation_source"))
    if wants_official and wants_docs:
        variants.append((_compact(f"{base_without_qualifiers or query} official documentation", 180), "official_docs_source"))
    if wants_latest:
        variants.append((_compact(f"{base_without_qualifiers or query} latest", 180), "freshness_source"))

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for query_text, purpose in variants:
        normalized = _compact(query_text, 180)
        if not normalized or normalized.lower() in seen:
            continue
        seen.add(normalized.lower())
        rows.append({"query_index": len(rows) + 1, "query": normalized, "purpose": purpose})
        if len(rows) >= max(1, int(max_queries or 1)):
            break
    return rows or [{"query_index": 1, "query": query, "purpose": "base_query"}]


def _web_observation_from_response(response: dict[str, Any], *, query: str, query_index: int) -> dict[str, Any]:
    results = _list_dicts(response.get("results", []))
    status = str(response.get("status", "") or ("ok" if results else "empty"))
    urls = list(response.get("source_urls", []) or []) or _source_urls(results)
    return {
        "schema": "holo.web_observation.v1",
        "observation_id": "web:" + stable_digest(query, status, ",".join(urls), str(query_index), limit=12),
        "action_type": "web_search",
        "query": _compact(response.get("query", query), 180),
        "status": status,
        "provider": str(response.get("provider", "host_search") or "host_search"),
        "results": results,
        "source_urls": urls,
        "fetched_at": utc_now(),
        "error": _compact(response.get("error", ""), 240),
        "confidence": 0.0,
        "query_index": int(query_index),
    }


def _ledger_row(phase: str, **values: Any) -> dict[str, Any]:
    return {
        "schema": STAGE186_CRAWLER_LEDGER_SCHEMA,
        "ledger_id": "crawl:" + stable_digest(phase, json.dumps(values, ensure_ascii=False, sort_keys=True, default=str), limit=12),
        "phase": phase,
        "observed_at": utc_now(),
        **values,
    }


def _supported_page(page_evidence: dict[str, Any]) -> bool:
    return str(page_evidence.get("status", "") or "") == "supported" and bool(str(page_evidence.get("selected_url", "") or ""))


def _page_rows(page_evidence: dict[str, Any]) -> list[dict[str, Any]]:
    return _list_dicts(page_evidence.get("page_observations", []))


def _final_summary(*, status: str, stop_reason: str, query_count: int, opened_count: int, urls: list[str], errors: list[str], user_text: str) -> str:
    if status == "sufficient":
        source_text = ", ".join(urls[:3]) if urls else "recorded source URLs"
        return f"Completed web crawl: {query_count} search queries, {opened_count} opened pages, sufficient evidence from {source_text}."
    if status == "rejected_network_disabled":
        return "我已经尝试 web_search，但网络被禁用。因此不能把它当成当前联网证据。"
    error_text = "; ".join(error for error in errors if error) or stop_reason
    if any(ord(ch) > 127 for ch in user_text):
        return f"我已经尝试 web_search，但没有取得足够证据：{_compact(error_text, 180)}。因此不能把它当成当前联网证据。"
    return f"I attempted web_search but did not obtain sufficient evidence: {_compact(error_text, 180)}. I cannot treat this as current web evidence."


def run_live_crawler_search(
    *,
    user_text: str,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    network_enabled: bool = True,
    max_queries: int = 3,
    max_pages_per_query: int = 2,
) -> dict[str, Any]:
    """Run a bounded query -> open page -> evidence sufficiency crawler loop."""

    search = web_search_fn or default_web_search
    open_page = open_page_fn or default_open_page
    query_plan = build_crawler_query_plan(user_text, max_queries=max_queries)
    crawler_ledger: list[dict[str, Any]] = []
    web_observations: list[dict[str, Any]] = []
    page_observations: list[dict[str, Any]] = []
    source_urls: list[str] = []
    errors: list[str] = []
    feedback_steps: list[dict[str, Any]] = []
    prior_best_feedback_score = 0.0

    if not network_enabled:
        query = str(query_plan[0].get("query", "") or _strip_query(user_text))
        row = {
            "schema": "holo.web_observation.v1",
            "observation_id": "web:" + stable_digest("stage186_network_disabled", query, limit=12),
            "action_type": "web_search",
            "query": query,
            "status": "rejected_network_disabled",
            "provider": "network_gate",
            "results": [],
            "source_urls": [],
            "fetched_at": utc_now(),
            "error": "network_disabled",
            "confidence": 0.0,
            "query_index": 1,
        }
        web_observations.append(row)
        source_authority_report = evaluate_source_authority(
            user_text,
            web_observations,
            task_type=_task_type_for_query(user_text),
        )
        stage190_self_feedback_loop = build_self_feedback_report(
            goal=user_text,
            steps=[
                evaluate_crawler_feedback_step(
                    goal=user_text,
                    query=query,
                    action="web_search",
                    page_evidence={"status": "rejected_network_disabled", "best_evidence_score": 0.0},
                    source_authority=source_authority_report,
                    remaining_query_budget=0,
                )
            ],
            final_stop_reason="boundary_or_permission",
        )
        crawler_ledger.append(_ledger_row("query", query=query, status="rejected_network_disabled", provider="network_gate"))
        status = "rejected_network_disabled"
        stop_reason = "boundary_or_permission"
        return sanitize_public_metadata(
            {
                "schema": STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA,
                "status": status,
                "user_text": _compact(user_text, 240),
                "query_plan": query_plan,
                "query_count": 1,
                "opened_page_count": 0,
                "web_observation_ledger": web_observations,
                "page_observation_ledger": page_observations,
                "crawler_ledger": crawler_ledger,
                "source_authority_report": source_authority_report,
                "stage190_self_feedback_loop": stage190_self_feedback_loop,
                "source_urls": source_urls,
                "stop_reason": stop_reason,
                "final_summary": _final_summary(status=status, stop_reason=stop_reason, query_count=1, opened_count=0, urls=[], errors=["network_disabled"], user_text=user_text),
                "created_at": utc_now(),
            }
        )

    status = "failed"
    stop_reason = "evidence_exhausted"
    for query_row in query_plan:
        query = str(query_row.get("query", "") or "").strip()
        query_index = int(query_row.get("query_index", len(web_observations) + 1) or len(web_observations) + 1)
        crawler_ledger.append(_ledger_row("query", query=query, query_index=query_index, purpose=query_row.get("purpose", "")))
        try:
            response = dict(search(query))
        except Exception as exc:  # noqa: BLE001
            response = {"query": query, "status": "error", "provider": "host_search", "results": [], "error": str(exc)}
        web_row = _web_observation_from_response(response, query=query, query_index=query_index)
        authority_report = evaluate_source_authority(
            query,
            [web_row],
            task_type=_task_type_for_query(user_text),
        )
        web_row["source_authority"] = authority_report
        web_observations.append(web_row)
        crawler_ledger.append(
            _ledger_row(
                "observe_search",
                query=query,
                query_index=query_index,
                status=web_row["status"],
                result_count=len(web_row["results"]),
                source_count=len(web_row["source_urls"]),
                error=web_row["error"],
            )
        )
        if web_row["error"]:
            errors.append(str(web_row["error"]))
        if str(web_row["status"]) != "ok" or not web_row["source_urls"]:
            feedback = evaluate_crawler_feedback_step(
                goal=user_text,
                query=query,
                action="web_search",
                page_evidence={"status": str(web_row["status"]), "best_evidence_score": 0.0},
                source_authority=authority_report,
                remaining_query_budget=max(0, len(query_plan) - len(web_observations)),
                prior_best_score=prior_best_feedback_score,
            )
            feedback_steps.append(feedback)
            prior_best_feedback_score = max(prior_best_feedback_score, float(feedback.get("combined_sufficiency_score", 0.0) or 0.0))
            crawler_ledger.append(_ledger_row("evaluate", query=query, status="insufficient", reason="search_failed_or_empty"))
            continue

        page_evidence = verify_page_evidence_for_search(
            web_row,
            open_page_fn=open_page,
            network_enabled=True,
            query=query,
            user_text="",
            max_pages=max_pages_per_query,
        )
        opened_rows = _page_rows(page_evidence)
        page_observations.extend(opened_rows)
        for page in opened_rows:
            crawler_ledger.append(
                _ledger_row(
                    "open_page",
                    query=query,
                    url=page.get("url", ""),
                    status=page.get("status", ""),
                    title=page.get("title", ""),
                    error=page.get("error", ""),
                )
            )
            if page.get("error"):
                errors.append(str(page.get("error", "")))
        web_row["page_evidence"] = page_evidence
        selected_url = str(page_evidence.get("selected_url", "") or "")
        authority_required = _authority_gate_required(authority_report)
        authority_status = str(authority_report.get("status", "") or "")
        authority_stop_reason = "authority_sufficient" if _authority_sufficient(authority_report) else "authority_insufficient"
        feedback = evaluate_crawler_feedback_step(
            goal=user_text,
            query=query,
            action="web_search",
            page_evidence=page_evidence,
            source_authority=authority_report,
            remaining_query_budget=max(0, len(query_plan) - len(web_observations)),
            prior_best_score=prior_best_feedback_score,
        )
        feedback_steps.append(feedback)
        prior_best_feedback_score = max(prior_best_feedback_score, float(feedback.get("combined_sufficiency_score", 0.0) or 0.0))
        if _supported_page(page_evidence) and (not authority_required or _authority_sufficient(authority_report)) and selected_url and selected_url not in source_urls:
            source_urls.append(selected_url)
        crawler_ledger.append(
            _ledger_row(
                "evaluate",
                query=query,
                status=page_evidence.get("status", ""),
                selected_url=selected_url,
                score=float(page_evidence.get("best_evidence_score", 0.0) or 0.0),
                stop_reason=page_evidence.get("stop_reason", "") if not authority_required or _authority_sufficient(authority_report) else authority_stop_reason,
                authority_status=authority_status,
                authority_required_family=authority_report.get("required_source_family", ""),
            )
        )
        if _supported_page(page_evidence) and (not authority_required or _authority_sufficient(authority_report)):
            status = "sufficient"
            stop_reason = "sufficient_evidence"
            break

    if status != "sufficient":
        if any(str(row.get("status", "") or "") == "error" for row in web_observations):
            stop_reason = "tool_failure_report"
            status = "failed"
        elif any(str(row.get("status", "") or "") == "ok" for row in web_observations):
            stop_reason = "evidence_exhausted"
            status = "weak"
        else:
            stop_reason = "tool_failure_report"
            status = "failed"

    source_authority_report = evaluate_source_authority(
        user_text,
        web_observations,
        task_type=_task_type_for_query(user_text),
    )
    crawler_ledger.append(
        _ledger_row(
            "stop",
            status=status,
            stop_reason=stop_reason,
            query_count=len(web_observations),
            opened_page_count=len(page_observations),
            authority_status=source_authority_report.get("status", ""),
        )
    )
    stage190_self_feedback_loop = build_self_feedback_report(
        goal=user_text,
        steps=feedback_steps,
        final_stop_reason=stop_reason,
    )
    report = {
        "schema": STAGE186_LIVE_CRAWLER_SEARCH_SCHEMA,
        "status": status,
        "user_text": _compact(user_text, 240),
        "query_plan": query_plan,
        "query_count": len(web_observations),
        "opened_page_count": len(page_observations),
        "web_observation_ledger": web_observations,
        "page_observation_ledger": page_observations,
        "crawler_ledger": crawler_ledger,
        "source_authority_report": source_authority_report,
        "stage190_self_feedback_loop": stage190_self_feedback_loop,
        "source_urls": source_urls,
        "stop_reason": stop_reason,
        "final_summary": _final_summary(
            status=status,
            stop_reason=stop_reason,
            query_count=len(web_observations),
            opened_count=len(page_observations),
            urls=source_urls,
            errors=errors,
            user_text=user_text,
        ),
        "created_at": utc_now(),
    }
    return sanitize_public_metadata(report)


def render_live_crawler_trace(report: dict[str, Any]) -> str:
    lines: list[str] = []
    for row in _list_dicts(report.get("crawler_ledger", [])):
        phase = str(row.get("phase", "") or "")
        if phase == "query":
            lines.append(f"[crawl:query] q{row.get('query_index', '')} {row.get('query', '')}")
        elif phase == "observe_search":
            lines.append(
                f"[crawl:search] status={row.get('status', '')} results={row.get('result_count', 0)} sources={row.get('source_count', 0)}"
            )
        elif phase == "open_page":
            lines.append(f"[crawl:open] status={row.get('status', '')} url={row.get('url', '')}")
        elif phase == "evaluate":
            lines.append(f"[crawl:evaluate] status={row.get('status', '')} score={row.get('score', 0)} stop={row.get('stop_reason', '')}")
        elif phase == "stop":
            lines.append(f"[crawl:stop] status={row.get('status', '')} reason={row.get('stop_reason', '')}")
    lines.append(f"[final] {report.get('final_summary', '')}")
    return "\n".join(lines)


def _public(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _public(item) for key, item in value.items() if str(key).strip().lower() not in PRIVATE_KEYS}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _dry_search(query: str) -> dict[str, Any]:
    if "official" not in query.lower() and "docs" not in query.lower():
        return {
            "query": query,
            "status": "ok",
            "provider": "stage186_dry_search",
            "results": [
                {
                    "title": "Generic Codex overview",
                    "url": "https://example.com/codex",
                    "snippet": "A generic overview that is intentionally weak.",
                }
            ],
        }
    return {
        "query": query,
        "status": "ok",
        "provider": "stage186_dry_search",
        "results": [
            {
                "title": "OpenAI Codex CLI documentation",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Official Codex CLI documentation for a terminal coding agent.",
            }
        ],
    }


def _dry_open_page(url: str) -> dict[str, Any]:
    if "developers.openai.com" in url:
        return {
            "url": url,
            "status": "ok",
            "provider": "stage186_dry_open",
            "html": "<html><title>Codex CLI</title><body>Codex CLI is OpenAI official documentation for a terminal coding agent that can read code, edit files, run commands, and show auditable progress.</body></html>",
        }
    return {
        "url": url,
        "status": "ok",
        "provider": "stage186_dry_open",
        "html": "<html><title>Generic overview</title><body>Generic overview with no official evidence.</body></html>",
    }


def write_live_crawler_search_artifacts(
    *,
    output: str | Path = DEFAULT_OUTPUT,
    dry_run: bool = True,
    user_text: str = "联网检索 Codex CLI 官方文档并给出来源",
    network_enabled: bool = True,
) -> dict[str, Any]:
    report = run_live_crawler_search(
        user_text=user_text,
        web_search_fn=_dry_search if dry_run else None,
        open_page_fn=_dry_open_page if dry_run else None,
        network_enabled=network_enabled,
    )
    public_report = _public(report)
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.with_suffix(".json").write_text(json.dumps(public_report, ensure_ascii=False, indent=2), encoding="utf-8")
    with target.with_suffix(".jsonl").open("w", encoding="utf-8") as handle:
        for row in _list_dicts(public_report.get("crawler_ledger", [])):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    rows = []
    for row in _list_dicts(public_report.get("crawler_ledger", [])):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.get('phase', '')))}</td>"
            f"<td>{html.escape(str(row.get('query', row.get('url', ''))))}</td>"
            f"<td>{html.escape(str(row.get('status', '')))}</td>"
            f"<td>{html.escape(str(row.get('stop_reason', '')))}</td>"
            "</tr>"
        )
    body = f"""<!doctype html>
<meta charset="utf-8">
<title>Stage186 Live Crawler Search</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; line-height: 1.45; }}
table {{ border-collapse: collapse; width: 100%; }}
th, td {{ border: 1px solid #ccc; padding: 6px 8px; vertical-align: top; }}
th {{ background: #f4f4f4; }}
pre {{ white-space: pre-wrap; background: #f7f7f7; padding: 10px; }}
</style>
<h1>Stage186 Live Crawler Search</h1>
<p>Status: <b>{html.escape(str(public_report.get('status', '')))}</b></p>
<p>Stop: <b>{html.escape(str(public_report.get('stop_reason', '')))}</b></p>
<pre>{html.escape(render_live_crawler_trace(public_report))}</pre>
<table>
<thead><tr><th>Phase</th><th>Target</th><th>Status</th><th>Stop</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
"""
    target.write_text(body, encoding="utf-8")
    return public_report
