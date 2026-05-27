from __future__ import annotations

import re
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE210_LAST_ACTION_RECALL_SCHEMA = "holo.stage210.last_action_recall.v1"

_LAST_ACTION_RE = re.compile(
    r"(你|刚才|上一轮|上一次|外网|联网|web|search|searched|搜索|检索|查找|爬取).{0,16}(搜|搜索|检索|查|查找|爬|做|是什么|什么|which|what)"
    r"|what\s+did\s+you\s+(search|look\s+up|do)"
    r"|what\s+was\s+searched",
    re.IGNORECASE,
)


def _compact(value: Any, limit: int = 220) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def is_last_action_recall_query(text: str) -> bool:
    current = str(text or "").strip()
    return bool(current and _LAST_ACTION_RE.search(current))


def _crawler_from_payload(previous_payload: dict[str, Any]) -> dict[str, Any]:
    crawler = _dict(previous_payload.get("stage186_live_crawler_search", {}))
    if crawler.get("schema") == "holo.stage186.live_crawler_search.v1":
        return crawler
    metadata = _dict(previous_payload.get("metadata", {}))
    crawler = _dict(metadata.get("stage186_live_crawler_search", {}))
    return crawler if crawler.get("schema") == "holo.stage186.live_crawler_search.v1" else {}


def _web_rows(previous_payload: dict[str, Any], crawler: dict[str, Any]) -> list[dict[str, Any]]:
    rows = _rows(crawler.get("web_observation_ledger", []))
    if rows:
        return rows
    rows = _rows(previous_payload.get("web_observation_ledger", []))
    if rows:
        return rows
    return _rows(_dict(previous_payload.get("metadata", {})).get("web_observation_ledger", []))


def _queries_from_crawler(crawler: dict[str, Any], web_rows: list[dict[str, Any]]) -> list[str]:
    queries: list[str] = []
    for row in _rows(crawler.get("crawler_ledger", [])):
        if str(row.get("phase", "") or "") == "query":
            query = _compact(row.get("query", ""), 180)
            if query and query not in queries:
                queries.append(query)
    for row in web_rows:
        query = _compact(row.get("query", ""), 180)
        if query and query not in queries:
            queries.append(query)
    return queries


def _source_urls_for_row(row: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in list(row.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    for result in _rows(row.get("results", [])):
        text = str(result.get("url", "") or "").strip()
        if text and text not in urls:
            urls.append(text)
    selected = str(_dict(row.get("page_evidence", {})).get("selected_url", "") or "").strip()
    if selected and selected not in urls:
        urls.append(selected)
    return urls


def _promoted_urls(crawler: dict[str, Any], web_rows: list[dict[str, Any]]) -> list[str]:
    urls: list[str] = []
    for url in list(crawler.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
    if urls:
        return urls
    for row in web_rows:
        if str(_dict(row.get("page_evidence", {})).get("status", "") or "") == "supported":
            for url in _source_urls_for_row(row):
                if url and url not in urls:
                    urls.append(url)
    return urls


def _weak_urls(web_rows: list[dict[str, Any]], promoted_urls: list[str]) -> list[str]:
    urls: list[str] = []
    for row in web_rows:
        page_status = str(_dict(row.get("page_evidence", {})).get("status", "") or "")
        authority_status = str(_dict(row.get("source_authority", {})).get("status", "") or "")
        row_status = str(row.get("status", "") or "")
        weak = row_status != "ok" or (page_status and page_status != "supported") or (authority_status and authority_status != "sufficient")
        if not weak:
            continue
        for url in _source_urls_for_row(row):
            if url and url not in promoted_urls and url not in urls:
                urls.append(url)
    return urls


def _is_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text or ""))


def _render_answer(report: dict[str, Any], *, user_text: str = "") -> str:
    if report.get("status") != "answered":
        return "I do not have a previous action ledger to inspect."
    queries = [str(item) for item in list(report.get("queries", []) or [])]
    promoted = [str(item) for item in list(report.get("promoted_source_urls", []) or [])]
    weak = [str(item) for item in list(report.get("observed_weak_source_urls", []) or [])]
    stop = str(report.get("stop_reason", "") or "")
    if _is_chinese(user_text):
        lines = [
            "我直接读取上一轮工具 ledger，不靠模型回忆。",
            f"动作：{report.get('action_type', 'unknown')}，状态：{report.get('crawler_status', '-')}",
        ]
        if queries:
            lines.append("搜索查询：" + "；".join(f"{index}. {query}" for index, query in enumerate(queries, start=1)))
        if weak:
            lines.append("过程里看到但未采纳的弱来源：" + "；".join(weak[:3]) + "（weak source not promoted）")
        if promoted:
            lines.append("最终采纳来源：" + "；".join(promoted[:3]))
        if stop:
            lines.append(f"停止原因：{stop}")
        return "\n".join(lines)
    lines = [
        "I read the previous tool ledger directly.",
        f"Action: {report.get('action_type', 'unknown')}; status: {report.get('crawler_status', '-')}.",
    ]
    if queries:
        lines.append("Search queries: " + "; ".join(f"{index}. {query}" for index, query in enumerate(queries, start=1)))
    if weak:
        lines.append("Observed weak sources not promoted: " + "; ".join(weak[:3]))
    if promoted:
        lines.append("Promoted sources: " + "; ".join(promoted[:3]))
    if stop:
        lines.append(f"Stop reason: {stop}")
    return "\n".join(lines)


def build_last_action_recall_report(text: str, *, previous_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    previous = dict(previous_payload or {})
    crawler = _crawler_from_payload(previous)
    web_rows = _web_rows(previous, crawler)
    if not crawler and not web_rows:
        report = {
            "schema": STAGE210_LAST_ACTION_RECALL_SCHEMA,
            "status": "missing",
            "action_type": "unknown",
            "query_count": 0,
            "queries": [],
            "promoted_source_urls": [],
            "observed_weak_source_urls": [],
            "stop_reason": "missing_previous_action_ledger",
            "created_at": utc_now(),
        }
        report["answer_text"] = _render_answer(report, user_text=text)
        return sanitize_public_metadata(report)
    promoted = _promoted_urls(crawler, web_rows)
    weak = _weak_urls(web_rows, promoted)
    queries = _queries_from_crawler(crawler, web_rows)
    action_type = "web_search" if crawler or any(str(row.get("action_type", "") or "") == "web_search" for row in web_rows) else "tool_action"
    report = {
        "schema": STAGE210_LAST_ACTION_RECALL_SCHEMA,
        "status": "answered",
        "recall_id": "stage210:" + stable_digest(text, ",".join(queries), ",".join(promoted), limit=12),
        "action_type": action_type,
        "crawler_status": str(crawler.get("status", "") or ("observed" if web_rows else "missing")),
        "query_count": int(crawler.get("query_count", 0) or len(queries)),
        "opened_page_count": int(crawler.get("opened_page_count", 0) or 0),
        "queries": queries,
        "promoted_source_urls": promoted,
        "observed_weak_source_urls": weak,
        "stop_reason": str(crawler.get("stop_reason", "") or ""),
        "source": "previous_turn_ledger",
        "hidden_reasoning_exposed": False,
        "created_at": utc_now(),
    }
    report["answer_text"] = _render_answer(report, user_text=text)
    return sanitize_public_metadata(report)


def maybe_build_last_action_recall_reply(
    text: str,
    *,
    previous_payload: dict[str, Any] | None,
    thread_key: str = "",
    chat_name: str = "",
    channel: str = "holo_cli",
) -> dict[str, Any]:
    if not is_last_action_recall_query(text):
        return {}
    report = build_last_action_recall_report(text, previous_payload=previous_payload)
    if str(report.get("status", "") or "") != "answered":
        return {}
    return sanitize_public_metadata(
        {
            "action": "reply",
            "text": str(report.get("answer_text", "") or ""),
            "bubbles": [str(report.get("answer_text", "") or "")],
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "canonical_stop_reason": "final_answer_ready",
            "canonical_stop_source": "stage210_last_action_recall",
            "stage210_last_action_recall": report,
        }
    )
