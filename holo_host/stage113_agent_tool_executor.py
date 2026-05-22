from __future__ import annotations

import hashlib
import json
import re
from html import unescape
from pathlib import Path
from typing import Any, Callable
from urllib import error, parse, request

STAGE113_SCHEMA = "holo.stage113.agent_tool_executor.v1"

LookupFn = Callable[[str, int], dict[str, Any]]

LOOKUP_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
LOOKUP_SNIPPET_RE = re.compile(
    r'<(?:a|div)[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
BING_RESULT_RE = re.compile(
    r'<li[^>]+class="b_algo"[^>]*>.*?<h2[^>]*>\s*<a[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>.*?(?:<p[^>]*>(?P<snippet>.*?)</p>)?',
    re.IGNORECASE | re.DOTALL,
)


def _stable_digest(*parts: Any, limit: int = 12) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _strip_tags(text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(text or ""))
    return " ".join(unescape(cleaned).split())


def _compact(text: Any, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tokenize(text: Any) -> set[str]:
    tokens: set[str] = set()
    for raw in re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower()):
        token = raw[:-1] if len(raw) > 4 and raw.endswith("s") else raw
        if len(token) >= 3:
            tokens.add(token)
    return tokens


def _load_memory_corpus(path: str | Path | None = None, *, repo_root: str | Path | None = None) -> list[dict[str, str]]:
    if path:
        source = Path(path)
        if not source.exists():
            return []
        rows: list[dict[str, str]] = []
        if source.suffix.lower() == ".jsonl":
            for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(item, dict):
                    rows.append(
                        {
                            "id": str(item.get("id", "") or f"{source.name}:{len(rows) + 1}"),
                            "text": str(item.get("text", "") or item.get("summary", "") or ""),
                            "source": str(item.get("source", "") or source.name),
                        }
                    )
            return [row for row in rows if row["text"]]
        return [{"id": source.name, "text": source.read_text(encoding="utf-8", errors="replace"), "source": str(source)}]

    root = Path(repo_root) if repo_root else Path.cwd()
    docs = root / "docs"
    if not docs.exists():
        return []
    rows = []
    for file_path in sorted(docs.glob("*.md"))[:80]:
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rows.append({"id": file_path.name, "text": _compact(text, 2000), "source": str(file_path)})
    return rows


def _execute_memory_recall(arguments: dict[str, Any], memory_corpus: list[dict[str, Any]] | None) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    limit = max(1, min(_safe_int(arguments.get("limit"), 6), 12))
    query_tokens = _tokenize(query)
    matches: list[dict[str, Any]] = []
    for index, row in enumerate(list(memory_corpus or [])):
        item = dict(row) if isinstance(row, dict) else {"text": str(row)}
        text = str(item.get("text", "") or "")
        overlap = sorted(query_tokens.intersection(_tokenize(text)))
        if not overlap:
            continue
        score = len(overlap) / max(1, len(query_tokens))
        matches.append(
            {
                "id": str(item.get("id", "") or f"memory:{index + 1}"),
                "score": round(score, 4),
                "matched_terms": overlap,
                "text": _compact(text, 320),
                "source": str(item.get("source", "")),
            }
        )
    matches.sort(key=lambda item: (-float(item["score"]), item["id"]))
    selected = matches[:limit]
    if selected:
        summary = "memory recall: " + " | ".join(f"{item['id']}:{item['text']}" for item in selected[:3])
    else:
        summary = f"memory recall: no local matches for {query}"
    return {
        "tool": "memory_recall",
        "status": "ok" if selected else "empty",
        "summary": _compact(summary, 420),
        "data": {"query": query, "matches": selected},
    }


def _decode_duckduckgo_href(url: str) -> str:
    parsed = parse.urlparse(unescape(str(url or "")))
    query = parse.parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return parse.unquote(query["uddg"][0])
    return unescape(str(url or ""))


def _duckduckgo_lookup(query: str, max_results: int) -> dict[str, Any]:
    if not query.strip():
        return {"query": "", "status": "skipped", "results": []}
    url = f"https://html.duckduckgo.com/html/?q={parse.quote_plus(query)}"
    opener = request.build_opener(request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        with opener.open(url, timeout=5) as response:  # noqa: S310
            html_text = response.read(48000).decode("utf-8", errors="replace")
    except (OSError, error.URLError, TimeoutError) as exc:
        fallback = _bing_lookup(query, max_results)
        if fallback.get("results"):
            fallback["fallback_from"] = "duckduckgo_html"
            return fallback
        fallback["error"] = str(exc)
        return fallback
    anchors = list(LOOKUP_RESULT_RE.finditer(html_text))
    snippets = [match.group("snippet") for match in LOOKUP_SNIPPET_RE.finditer(html_text)]
    results: list[dict[str, str]] = []
    for index, match in enumerate(anchors[:max_results]):
        title = _strip_tags(match.group("title"))
        target_url = _decode_duckduckgo_href(match.group("url"))
        snippet = _strip_tags(snippets[index] if index < len(snippets) else "")
        if title or snippet:
            results.append({"title": title, "url": target_url, "snippet": _compact(snippet, 220)})
    if results:
        return {"query": query, "status": "ok", "backend": "duckduckgo_html", "results": results}
    return _bing_lookup(query, max_results)


def _bing_lookup(query: str, max_results: int) -> dict[str, Any]:
    url = f"https://www.bing.com/search?q={parse.quote_plus(query)}"
    opener = request.build_opener(request.ProxyHandler({}))
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    try:
        with opener.open(url, timeout=8) as response:  # noqa: S310
            html_text = response.read(64000).decode("utf-8", errors="replace")
    except (OSError, error.URLError, TimeoutError) as exc:
        return {"query": query, "status": "error", "backend": "bing_html", "results": [], "error": str(exc)}
    results: list[dict[str, str]] = []
    for match in BING_RESULT_RE.finditer(html_text):
        title = _strip_tags(match.group("title"))
        target_url = unescape(str(match.group("url") or ""))
        snippet = _strip_tags(match.group("snippet") or "")
        if title or snippet:
            results.append({"title": title, "url": target_url, "snippet": _compact(snippet, 220)})
        if len(results) >= max_results:
            break
    return {"query": query, "status": "ok" if results else "empty", "backend": "bing_html", "results": results}


def _execute_external_lookup(
    arguments: dict[str, Any],
    *,
    external_lookup_fn: LookupFn | None,
    network_enabled: bool,
) -> dict[str, Any]:
    query = str(arguments.get("query", "") or "").strip()
    max_results = max(1, min(_safe_int(arguments.get("max_results"), 3), 8))
    if external_lookup_fn is not None:
        result = dict(external_lookup_fn(query, max_results))
    elif network_enabled:
        result = _duckduckgo_lookup(query, max_results)
    else:
        result = {
            "query": query,
            "status": "skipped",
            "results": [],
            "reason": "network_disabled",
        }
    results = [dict(item) for item in list(result.get("results", []) or []) if isinstance(item, dict)]
    if results:
        summary = "external lookup: " + " | ".join(
            _compact(f"{item.get('title', '')} {item.get('snippet', '')}", 180) for item in results[:3]
        )
    else:
        summary = f"external lookup: {result.get('status', 'empty')} for {query}"
    return {
        "tool": "external_lookup",
        "status": str(result.get("status", "ok") or "ok"),
        "summary": _compact(summary, 420),
        "data": {
            "query": str(result.get("query", query) or query),
            "results": results,
            "error": str(result.get("error", "") or ""),
            "reason": str(result.get("reason", "") or ""),
        },
    }


def _call_id(call: dict[str, Any], index: int) -> str:
    return str(call.get("id", "") or f"tool_call_{index + 1}")


def execute_stage113_agent_tools(
    tool_calls: list[dict[str, Any]],
    *,
    external_lookup_fn: LookupFn | None = None,
    memory_corpus: list[dict[str, Any]] | None = None,
    memory_corpus_path: str | Path | None = None,
    repo_root: str | Path | None = None,
    network_enabled: bool = False,
) -> dict[str, Any]:
    corpus = memory_corpus if memory_corpus is not None else _load_memory_corpus(memory_corpus_path, repo_root=repo_root)
    observations: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for index, raw_call in enumerate(list(tool_calls or [])):
        call = dict(raw_call) if isinstance(raw_call, dict) else {}
        call_id = _call_id(call, index)
        name = str(call.get("name", "") or "").strip()
        arguments = dict(call.get("arguments", {}) or {}) if isinstance(call.get("arguments", {}), dict) else {}
        if not bool(call.get("allowed", False)) or str(call.get("status", "")) == "rejected":
            skipped.append(
                {
                    "provider_call_id": call_id,
                    "tool": name,
                    "reason": str(call.get("error", "") or "not_allowed"),
                }
            )
            continue
        if name == "external_lookup":
            observation = _execute_external_lookup(
                arguments,
                external_lookup_fn=external_lookup_fn,
                network_enabled=network_enabled,
            )
        elif name == "memory_recall":
            observation = _execute_memory_recall(arguments, corpus)
        else:
            skipped.append({"provider_call_id": call_id, "tool": name, "reason": "unknown_tool"})
            continue
        observation["provider_call_id"] = call_id
        observations.append(observation)
    report_id = f"stage113:{_stable_digest([item.get('provider_call_id', '') for item in observations], [item.get('provider_call_id', '') for item in skipped])}"
    return {
        "schema": STAGE113_SCHEMA,
        "stage": 113,
        "report_id": report_id,
        "observations": observations,
        "skipped": skipped,
        "summary": {
            "executed_count": len(observations),
            "skipped_count": len(skipped),
            "observation_summary": _compact(" | ".join(item.get("summary", "") for item in observations), 700),
        },
        "authority": {
            "executor": "holo_local_agent",
            "provider_may_execute_tools": False,
            "executed_tools_are_allowlisted": True,
            "network_enabled": bool(network_enabled),
        },
        "reentry_contract": {
            "stage107_tool_observations": observations,
            "next_step": "feed observations into Stage107, then send the next bounded provider packet",
        },
    }
