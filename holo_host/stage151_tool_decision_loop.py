from __future__ import annotations

import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable
from urllib import error, parse, request
from urllib.parse import parse_qs, urlparse

from .common import compact_text, stable_digest, utc_now

STAGE151_TOOL_DECISION_SCHEMA = "holo.stage151.tool_decision.v1"
STAGE151_LIVE_TRACE_SCHEMA = "holo.stage151.live_trace.v1"
WEB_OBSERVATION_SCHEMA = "holo.web_observation.v1"
TIME_OBSERVATION_SCHEMA = "holo.time_observation.v1"
NETWORK_HEALTH_SCHEMA = "holo.stage159.network_health.v1"

URL_RE = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)
DDG_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
DDG_SNIPPET_RE = re.compile(
    r'<(?:a|div)[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)

WEB_HINTS = (
    "联网",
    "上网",
    "网页",
    "网站",
    "搜索",
    "搜一下",
    "搜一搜",
    "查一下",
    "查一查",
    "查找",
    "最新",
    "新闻",
    "官方",
    "官网",
    "主页",
    "文档",
    "功能页",
    "论文",
    "资料",
    "source",
    "sources",
    "search",
    "look up",
    "latest",
    "current",
    "today",
    "news",
    "official",
    "homepage",
    "docs",
    "documentation",
)

MEMORY_HINTS = ("记得", "回忆", "之前", "以前", "我们聊过", "memory", "remember", "recall")
ENGINEERING_HINTS = ("文件", "目录", "测试", "补丁", "commit", "git", "pytest", "patch", "workspace", "repo")
FIND_HINTS = ("find in page", "find on page", "在网页里找", "网页里找", "页面里找", "在页面里找")
TIME_HINTS = ("今天", "现在", "当前", "today", "now", "current", "as of today")


def _compact(value: Any, limit: int = 240) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _strip_tags(html_text: str, *, limit: int = 240) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(html_text or ""))
    cleaned = unescape(re.sub(r"\s+", " ", cleaned).strip())
    return _compact(cleaned, limit)


def _decode_duckduckgo_href(raw_url: str) -> str:
    current = str(raw_url or "").strip()
    if not current:
        return current
    parsed = urlparse(current)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return parse.unquote(query["uddg"][0])
    return current


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return _strip_tags(match.group(1), limit=140)


def build_time_observation(now: datetime | None = None) -> dict[str, Any]:
    local_now = (now or datetime.now().astimezone()).astimezone()
    utc = local_now.astimezone(timezone.utc)
    timezone_name = str(local_now.tzinfo or "")
    return {
        "schema": TIME_OBSERVATION_SCHEMA,
        "observation_id": "time:" + stable_digest(local_now.isoformat(), limit=12),
        "local_time": local_now.isoformat(timespec="seconds"),
        "utc_time": utc.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "timezone": timezone_name,
        "observed_at": utc_now(),
        "confidence": 1.0,
    }


def build_network_health_report(
    *,
    network_enabled: bool,
    provider: str = "host",
    proxy_from_env: bool | None = None,
    last_web_status: str = "",
    last_error: str = "",
) -> dict[str, Any]:
    if proxy_from_env is None:
        import os

        proxy_from_env = any(os.environ.get(name) for name in ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY"))
    return {
        "schema": NETWORK_HEALTH_SCHEMA,
        "network_enabled": bool(network_enabled),
        "provider": str(provider or "host"),
        "proxy_from_env": bool(proxy_from_env),
        "last_web_status": str(last_web_status or ""),
        "last_error": _compact(last_error, 180),
        "observed_at": utc_now(),
    }


def _search_query_from_text(text: str) -> str:
    current = " ".join(str(text or "").strip().split())
    for prefix in (
        "请你",
        "请",
        "帮我",
        "你去",
        "联网搜索",
        "联网查找",
        "上网搜索",
        "上网查",
        "搜索一下",
        "搜一下",
        "搜一搜",
        "搜索",
        "查一下",
        "查一查",
        "查找",
        "look up",
        "search for",
        "search",
    ):
        if current.lower().startswith(prefix.lower()):
            current = current[len(prefix) :].strip(" ：:，,。.!?？")
            break
    current = re.sub(r"(并)?(告诉我|给我|找到|找一下|看一下|详细阅览|详细说明)", " ", current)
    current = re.sub(r"\s+", " ", current).strip(" ：:，,。.!?？")
    return _compact(current, 180)


def _find_pattern_from_text(text: str) -> str:
    current = str(text or "")
    for hint in FIND_HINTS:
        if hint in current.lower() or hint in current:
            _, _, tail = current.partition(hint)
            return _compact(tail.strip(" ：:，,。.!?？"), 120)
    return ""


def build_action_candidates(text: str, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    current = str(text or "")
    lowered = current.lower()
    urls = [match.group(0).rstrip(").,!?，。！？") for match in URL_RE.finditer(current)]
    wants_find = any(hint in lowered or hint in current for hint in FIND_HINTS)
    wants_web = any(hint in lowered or hint in current for hint in WEB_HINTS)
    wants_time = any(hint in lowered or hint in current for hint in TIME_HINTS)
    wants_memory = any(hint in lowered or hint in current for hint in MEMORY_HINTS)
    wants_engineering = any(hint in lowered or hint in current for hint in ENGINEERING_HINTS)
    query = _search_query_from_text(current)
    candidates = [
        {
            "action_type": "answer_direct",
            "score": 0.38 if not wants_web and not urls else 0.12,
            "reason": "no external evidence is obviously required" if not wants_web and not urls else "external evidence appears useful",
            "required_observations": [],
        },
        {
            "action_type": "memory_recall",
            "score": 0.72 if wants_memory else 0.18,
            "reason": "turn contains memory or prior-conversation wording",
            "required_observations": ["memory_observation_ledger"],
        },
        {
            "action_type": "web_search",
            "score": 0.86 if wants_web and not urls else 0.52 if wants_web else 0.08,
            "reason": "turn asks for current, official, web, latest, document, source, or search evidence",
            "required_observations": ["web_observation_ledger"],
            "query": query,
        },
        {
            "action_type": "open_page",
            "score": 0.84 if urls and not wants_find else 0.18,
            "reason": "turn includes a URL that can be opened",
            "required_observations": ["web_observation_ledger"],
            "url": urls[0] if urls else "",
        },
        {
            "action_type": "find_in_page",
            "score": 0.88 if urls and wants_find else 0.2 if wants_find else 0.04,
            "reason": "turn asks to find a pattern inside a page",
            "required_observations": ["web_observation_ledger"],
            "url": urls[0] if urls else "",
            "pattern": _find_pattern_from_text(current),
        },
        {
            "action_type": "ask_clarification",
            "score": 0.54 if wants_find and not urls else 0.18,
            "reason": "page-specific request lacks a URL or selected source",
            "required_observations": [],
        },
        {
            "action_type": "defer",
            "score": 0.12,
            "reason": "no reason to defer by default",
            "required_observations": [],
        },
    ]
    if wants_time:
        for candidate in candidates:
            if candidate["action_type"] in {"answer_direct", "web_search"}:
                candidate["required_observations"] = sorted(set(candidate["required_observations"] + ["time_observation"]))
    if wants_engineering:
        candidates.append(
            {
                "action_type": "engineering_tool_hint",
                "score": 0.56,
                "reason": "turn mentions local files, tests, git, patches, or workspace actions",
                "required_observations": ["tool_observation_ledger"],
            }
        )
    return sorted(candidates, key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)


def build_tool_decision_report(
    text: str,
    *,
    metadata: dict[str, Any] | None = None,
    time_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    candidates = build_action_candidates(text, metadata)
    selected = [item for item in candidates if str(item.get("action_type", "")) in {"web_search", "open_page", "find_in_page"} and float(item.get("score", 0.0) or 0.0) >= 0.5]
    top = dict(candidates[0]) if candidates else {}
    purpose = "answer_direct"
    if selected:
        purpose = "gather_web_evidence"
    elif str(top.get("action_type", "")) == "memory_recall":
        purpose = "gather_memory_evidence"
    elif str(top.get("action_type", "")) == "engineering_tool_hint":
        purpose = "prepare_engineering_tool_evidence"
    elif str(top.get("action_type", "")) == "ask_clarification":
        purpose = "ask_clarification"
    return {
        "schema": STAGE151_TOOL_DECISION_SCHEMA,
        "purpose": purpose,
        "action_candidates": candidates,
        "selected_actions": selected[:3],
        "time_observation": dict(time_observation or build_time_observation()),
        "network_required": bool(selected),
    }


def _observation(
    *,
    action_type: str,
    status: str,
    query: str = "",
    url: str = "",
    pattern: str = "",
    provider: str = "host",
    results: list[dict[str, Any]] | None = None,
    source_urls: list[str] | None = None,
    error_text: str = "",
    confidence: float = 0.0,
) -> dict[str, Any]:
    source_urls = [str(item).strip() for item in list(source_urls or []) if str(item).strip()]
    results = [dict(item) for item in list(results or []) if isinstance(item, dict)]
    return {
        "schema": WEB_OBSERVATION_SCHEMA,
        "observation_id": "web:" + stable_digest(action_type, query, url, pattern, status, ",".join(source_urls), limit=12),
        "action_type": action_type,
        "query": _compact(query, 180),
        "url": str(url or "").strip(),
        "pattern": _compact(pattern, 120),
        "status": status,
        "provider": provider,
        "results": results,
        "source_urls": source_urls,
        "fetched_at": utc_now(),
        "error": _compact(error_text, 180),
        "confidence": round(max(0.0, min(1.0, float(confidence or 0.0))), 4),
    }


def default_web_search(query: str) -> dict[str, Any]:
    current = _compact(query, 180)
    if not current:
        return {"query": "", "status": "empty", "results": []}
    url = f"https://html.duckduckgo.com/html/?q={parse.quote_plus(current)}"
    opener = request.build_opener(request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        with opener.open(url, timeout=6) as response:  # noqa: S310
            html_text = response.read(64000).decode("utf-8", errors="replace")
    except (OSError, error.URLError, TimeoutError) as exc:
        return {"query": current, "status": "error", "results": [], "error": str(exc), "provider": "duckduckgo_html"}
    anchors = list(DDG_RESULT_RE.finditer(html_text))
    snippets = [match.group("snippet") for match in DDG_SNIPPET_RE.finditer(html_text)]
    results: list[dict[str, Any]] = []
    for index, match in enumerate(anchors[:5]):
        title = _strip_tags(match.group("title"), limit=140)
        target_url = _decode_duckduckgo_href(match.group("url"))
        snippet = _strip_tags(snippets[index] if index < len(snippets) else "", limit=220)
        if title or snippet:
            results.append({"title": title, "url": target_url, "snippet": snippet})
    return {"query": current, "status": "ok" if results else "empty", "results": results, "provider": "duckduckgo_html"}


def default_open_page(url: str) -> dict[str, Any]:
    target = str(url or "").strip()
    if not target:
        return {"url": "", "status": "empty", "results": []}
    opener = request.build_opener(request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        with opener.open(target, timeout=6) as response:  # noqa: S310
            html_text = response.read(96000).decode("utf-8", errors="replace")
    except (OSError, error.URLError, TimeoutError) as exc:
        return {"url": target, "status": "error", "results": [], "error": str(exc), "provider": "host_open_page"}
    title = _extract_title(html_text)
    body = _strip_tags(html_text, limit=900)
    result = {"title": title or target, "url": target, "snippet": body}
    return {"url": target, "status": "ok", "results": [result], "provider": "host_open_page"}


def _web_response_to_observation(action: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    action_type = str(action.get("action_type", "") or "web_search")
    results = [dict(item) for item in list(response.get("results", []) or []) if isinstance(item, dict)]
    source_urls = [str(item.get("url", "") or "").strip() for item in results if str(item.get("url", "") or "").strip()]
    status = str(response.get("status", "") or ("ok" if results else "empty"))
    return _observation(
        action_type=action_type,
        status=status,
        query=str(response.get("query", action.get("query", "")) or ""),
        url=str(response.get("url", action.get("url", "")) or ""),
        pattern=str(action.get("pattern", "") or ""),
        provider=str(response.get("provider", "host") or "host"),
        results=results,
        source_urls=source_urls,
        error_text=str(response.get("error", "") or ""),
        confidence=0.86 if status == "ok" and source_urls else 0.25 if status == "empty" else 0.0,
    )


def execute_tool_decision(
    decision: dict[str, Any],
    *,
    network_enabled: bool,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    web_search = web_search_fn or default_web_search
    open_page = open_page_fn or default_open_page
    for action in list(decision.get("selected_actions", []) or [])[:3]:
        if not isinstance(action, dict):
            continue
        action_type = str(action.get("action_type", "") or "")
        if action_type not in {"web_search", "open_page", "find_in_page"}:
            continue
        if not network_enabled:
            observations.append(
                _observation(
                    action_type=action_type,
                    status="rejected_network_disabled",
                    query=str(action.get("query", "") or ""),
                    url=str(action.get("url", "") or ""),
                    pattern=str(action.get("pattern", "") or ""),
                    provider="network_gate",
                    error_text="network_disabled",
                )
            )
            continue
        if action_type == "web_search":
            observations.append(_web_response_to_observation(action, web_search(str(action.get("query", "") or ""))))
        elif action_type == "open_page":
            observations.append(_web_response_to_observation(action, open_page(str(action.get("url", "") or ""))))
        elif action_type == "find_in_page":
            page_response = open_page(str(action.get("url", "") or ""))
            page_obs = _web_response_to_observation(action, page_response)
            pattern = str(action.get("pattern", "") or "").strip()
            if pattern and page_obs.get("results"):
                blob = " ".join(str(item.get("title", "")) + " " + str(item.get("snippet", "")) for item in page_obs["results"])
                found = pattern.lower() in blob.lower()
                page_obs["status"] = "ok" if found else "empty"
                page_obs["confidence"] = 0.84 if found else 0.22
                page_obs["error"] = "" if found else "pattern_not_found"
            observations.append(page_obs)
    return observations


def web_observations_to_tool_ledger(web_observation_ledger: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not isinstance(web_observation_ledger, list):
        return rows
    for item in web_observation_ledger:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "") or "")
        ok = status == "ok"
        source_urls = list(item.get("source_urls", []) or [])
        query = str(item.get("query", "") or item.get("url", "") or "")
        results = [dict(row) for row in list(item.get("results", []) or []) if isinstance(row, dict)]
        rows.append(
            {
                "provider_call_id": str(item.get("observation_id", "") or ""),
                "tool": str(item.get("action_type", "") or "web_search"),
                "status": "ok" if ok else "rejected" if status == "rejected_network_disabled" else status,
                "summary": _compact(f"{item.get('action_type', 'web')} {status}: {query}; sources={len(source_urls)}"),
                "data_keys": ["query", "results", "source_urls"],
                "grounding_tags": ["current_fact", "external_lookup"] if ok and source_urls else [],
                "query": query,
                "results": results,
                "source_urls": source_urls,
                "fetched_at": str(item.get("fetched_at", "") or ""),
                "error": str(item.get("error", "") or ""),
            }
        )
    return rows


def _has_web_claim(text: str) -> bool:
    current = str(text or "")
    lowered = current.lower()
    explicit_web_markers = (
        "searched",
        "looked up",
        "web",
        "internet",
        "online",
        "latest",
        "official",
        "homepage",
        "官网",
        "官方",
        "最新",
        "上网",
        "联网",
        "网页",
        "主页",
    )
    if any(marker in lowered or marker in current for marker in explicit_web_markers):
        return True
    if URL_RE.search(current):
        return True
    docs_markers = ("docs", "documentation", "文档")
    docs_qualifiers = ("official", "latest", "searched", "looked up", "web", "online", "官方", "最新", "联网", "搜索")
    return any(marker in lowered or marker in current for marker in docs_markers) and any(
        qualifier in lowered or qualifier in current for qualifier in docs_qualifiers
    )


def _has_time_claim(text: str) -> bool:
    current = str(text or "")
    lowered = current.lower()
    return any(hint in lowered or hint in current for hint in ("as of today", "today", "current time", "now", "今天", "当前", "现在"))


def evaluate_tool_decision_grounding(
    text: str,
    *,
    web_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    web_rows = [dict(item) for item in list(web_observation_ledger or []) if isinstance(item, dict)]
    ok_web = [row for row in web_rows if str(row.get("status", "") or "") == "ok" and list(row.get("source_urls", []) or [])]
    rejected_web = [row for row in web_rows if str(row.get("status", "") or "") == "rejected_network_disabled"]
    web_claim = _has_web_claim(text)
    time_claim = _has_time_claim(text)
    has_time = bool(time_observation and time_observation.get("schema") == TIME_OBSERVATION_SCHEMA)
    missing: list[str] = []
    if web_claim and not ok_web:
        missing.append("web_observation")
    if time_claim and not has_time:
        missing.append("time_observation")
    status = "grounded"
    if missing:
        status = "ungrounded_web_claim" if "web_observation" in missing else "ungrounded_time_claim"
    elif not web_claim and not time_claim:
        status = "no_current_claim"
    return {
        "schema": "holo.stage151.grounding.v1",
        "status": status,
        "web_claim_count": 1 if web_claim else 0,
        "time_claim_count": 1 if time_claim else 0,
        "web_observation_count": len(web_rows),
        "successful_web_observation_count": len(ok_web),
        "rejected_web_observation_count": len(rejected_web),
        "time_observation_present": has_time,
        "missing_observations": missing,
        "source_urls": [url for row in ok_web for url in list(row.get("source_urls", []) or [])][:8],
        "repair_required": bool(missing),
    }


def repair_tool_decision_grounding(text: str, grounding_report: dict[str, Any], *, channel: str = "") -> str:
    if not bool(grounding_report.get("repair_required", False)):
        return str(text or "")
    if "web_observation" in list(grounding_report.get("missing_observations", []) or []):
        if str(channel or "").startswith("wechat"):
            return "我没有可核验的联网观察，不能把这当作已经查到的当前信息。"
        return "我没有可核验的联网观察，不能把这当作已经查到的当前信息。需要先完成 web_search 或 open_page。"
    return "我有本机时间观测不足，不能确认这个时间相关说法。"


def build_grounded_web_observation_answer(
    *,
    user_text: str = "",
    web_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
    max_results: int = 3,
) -> str:
    rows = [
        dict(item)
        for item in list(web_observation_ledger or [])
        if isinstance(item, dict) and str(item.get("status", "") or "") == "ok"
    ]
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for row in rows:
        for result in list(row.get("results", []) or []):
            if not isinstance(result, dict):
                continue
            url = str(result.get("url", "") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(
                {
                    "title": _compact(result.get("title", "") or url, 90),
                    "url": url,
                    "snippet": _compact(result.get("snippet", ""), 150),
                }
            )
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    if not results:
        return ""
    query = _compact(user_text, 120)
    lines = ["我已完成联网检索，下面是可核验来源："]
    if query:
        lines.append(f"查询：{query}")
    observed_at = str((time_observation or {}).get("local_time", "") or (time_observation or {}).get("observed_at", "")).strip()
    if observed_at:
        lines.append(f"检索时间：{observed_at}")
    for index, result in enumerate(results, start=1):
        line = f"{index}. {result['title']} - {result['url']}"
        if result["snippet"]:
            line += f"\n   {result['snippet']}"
        lines.append(line)
    return "\n".join(lines)


def maybe_ground_visible_web_reply(
    *,
    user_text: str = "",
    text: str = "",
    web_observation_ledger: Any = None,
    time_observation: dict[str, Any] | None = None,
) -> str:
    current = str(text or "").strip()
    rows = [
        dict(item)
        for item in list(web_observation_ledger or [])
        if isinstance(item, dict) and str(item.get("status", "") or "") == "ok" and list(item.get("source_urls", []) or [])
    ]
    if not rows:
        return current
    lowered = current.lower()
    user_lowered = str(user_text or "").lower()
    unresolved_markers = (
        "没有可核验的联网观察",
        "需要先完成 web_search",
        "need to complete web_search",
        "no verifiable web observation",
        "没有联网观察",
    )
    source_requested = any(marker in user_lowered or marker in str(user_text or "") for marker in ("来源", "链接", "source", "sources", "url", "官方", "官网"))
    only_intends_lookup = any(marker in current for marker in ("让我联网", "我来联网", "我去查", "我查一下", "让我查"))
    missing_visible_source = source_requested and not URL_RE.search(current)
    if any(marker in lowered or marker in current for marker in unresolved_markers) or missing_visible_source or only_intends_lookup:
        grounded = build_grounded_web_observation_answer(
            user_text=user_text,
            web_observation_ledger=rows,
            time_observation=time_observation,
        )
        if grounded:
            return grounded
    return current


def build_stage151_live_trace(
    *,
    user_text: str = "",
    tool_decision: dict[str, Any] | None = None,
    web_observation_ledger: Any = None,
    grounding: dict[str, Any] | None = None,
    final_text: str = "",
) -> dict[str, Any]:
    decision = dict(tool_decision or {})
    events: list[dict[str, Any]] = [
        {"event": "purpose", "summary": str(decision.get("purpose", "answer_direct") or "answer_direct")},
    ]
    for candidate in list(decision.get("action_candidates", []) or [])[:7]:
        if isinstance(candidate, dict):
            events.append(
                {
                    "event": "candidate",
                    "action_type": str(candidate.get("action_type", "") or ""),
                    "score": round(float(candidate.get("score", 0.0) or 0.0), 3),
                    "reason": _compact(candidate.get("reason", ""), 180),
                    "required_observations": list(candidate.get("required_observations", []) or []),
                }
            )
    for action in list(decision.get("selected_actions", []) or [])[:3]:
        if isinstance(action, dict):
            events.append(
                {
                    "event": "tool_call",
                    "action_type": str(action.get("action_type", "") or ""),
                    "query": _compact(action.get("query", "") or action.get("url", ""), 180),
                    "pattern": _compact(action.get("pattern", ""), 100),
                }
            )
    for row in list(web_observation_ledger or [])[:5]:
        if isinstance(row, dict):
            events.append(
                {
                    "event": "observation",
                    "action_type": str(row.get("action_type", "") or ""),
                    "status": str(row.get("status", "") or ""),
                    "source_urls": list(row.get("source_urls", []) or [])[:3],
                    "result_count": len(list(row.get("results", []) or [])),
                    "error": _compact(row.get("error", ""), 120),
                }
            )
    report = dict(grounding or {})
    events.append(
        {
            "event": "grounding",
            "status": str(report.get("status", "") or ""),
            "missing_observations": list(report.get("missing_observations", []) or []),
            "source_urls": list(report.get("source_urls", []) or [])[:3],
        }
    )
    events.append({"event": "final", "summary": _compact(final_text, 260)})
    return {
        "schema": STAGE151_LIVE_TRACE_SCHEMA,
        "status": "recorded",
        "event_count": len(events),
        "events": events,
    }


def format_stage151_live_trace(payload: dict[str, Any]) -> str:
    trace = dict(payload.get("stage151_live_trace", payload.get("stage151_live_tool_trace", payload))) if isinstance(payload, dict) else {}
    events = list(trace.get("events", []) or []) if isinstance(trace, dict) else []
    lines: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        kind = str(event.get("event", "") or "")
        if kind == "purpose":
            lines.append(f"[purpose] {event.get('summary', '')}")
        elif kind == "candidate":
            lines.append(f"[candidate] {event.get('action_type', '')} score={event.get('score', 0)} need={','.join(str(x) for x in list(event.get('required_observations', []) or []))}")
        elif kind == "tool_call":
            lines.append(f"[tool_call] {event.get('action_type', '')} query={event.get('query', '')}")
        elif kind in {"observation", "tool_observation"}:
            source_urls = list(event.get("source_urls", []) or [])
            sources = ",".join(str(url) for url in source_urls[:3])
            source = f" sources={sources}" if sources else ""
            lines.append(
                f"[observation] {event.get('action_type', event.get('tool', ''))} "
                f"status={event.get('status', '')} results={event.get('result_count', 0)}{source}"
            )
        elif kind == "grounding":
            missing = ",".join(str(item) for item in list(event.get("missing_observations", []) or [])) or "-"
            lines.append(f"[grounding] status={event.get('status', '') or '-'} missing={missing}")
        elif kind == "final":
            lines.append(f"[final] {event.get('summary', '')}")
        elif kind == "plan":
            lines.append(f"[purpose] {event.get('summary', '')}")
    return "\n".join(lines)
