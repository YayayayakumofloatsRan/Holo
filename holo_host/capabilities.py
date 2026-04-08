from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from urllib.parse import parse_qs, urlparse

from .common import compact_text
from .config import HostConfig
from .models import ToolRequest

URL_RE = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)
LOOKUP_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
LOOKUP_SNIPPET_RE = re.compile(
    r'<(?:a|div)[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</(?:a|div)>',
    re.IGNORECASE | re.DOTALL,
)
SEARCH_HINTS = (
    "联网",
    "上网",
    "网上",
    "搜索",
    "搜一下",
    "查一下",
    "查查",
    "查找",
    "最新",
    "新闻",
    "资料",
    "百科",
    "维基",
    "官网",
    "look up",
    "search",
    "latest",
    "news",
    "official",
)
MEMORY_LOCAL_HINTS = (
    "记得",
    "之前",
    "回忆",
    "我们",
    "holo",
    "mindos",
    "系统",
    "架构",
    "线程",
    "session",
    "memory",
)


def _safe_sidecar_candidates(path: Path) -> list[Path]:
    suffix = path.suffix
    candidates = [path.with_suffix(f"{suffix}.txt"), path.with_suffix(f"{suffix}.ocr.txt")]
    if suffix:
        candidates.append(path.with_suffix(".txt"))
    return candidates


def _read_sidecar_text(path: Path) -> str:
    for candidate in _safe_sidecar_candidates(path):
        if candidate.exists():
            try:
                return candidate.read_text(encoding="utf-8").strip()
            except OSError:
                continue
    return ""


def _extract_title(html_text: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return compact_text(unescape(re.sub(r"\s+", " ", match.group(1)).strip()), 140)


def _strip_tags(html_text: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", str(html_text or ""))
    cleaned = unescape(re.sub(r"\s+", " ", cleaned).strip())
    return compact_text(cleaned, 200)


def _decode_duckduckgo_href(raw_url: str) -> str:
    current = str(raw_url or "").strip()
    if not current:
        return current
    parsed = urlparse(current)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return parse.unquote(query["uddg"][0])
    return current


@dataclass(slots=True)
class CapabilityBroker:
    config: HostConfig

    def summarize_turn(self, text: str, metadata: dict[str, Any] | None = None, *, eager_network: bool = True) -> dict[str, Any]:
        meta = dict(metadata or {})
        tool_requests: list[ToolRequest] = []
        tool_context_lines: list[str] = []

        if self.config.runtime.network_enabled and eager_network:
            previews = self._preview_urls(text)
            for preview in previews:
                tool_requests.append(
                    ToolRequest(
                        name="web_preview",
                        reason=f"message references {preview['url']}",
                        payload=preview,
                    )
                )
                title = preview.get("title", "")
                snippet = preview.get("snippet", "")
                if title or snippet:
                    line = f"web preview: {preview['url']}"
                    if title:
                        line += f" | title: {title}"
                    if snippet:
                        line += f" | snippet: {snippet}"
                    tool_context_lines.append(line)
        else:
            previews = []

        if not previews and self._should_external_lookup(text, meta):
            query = self._normalize_lookup_query(text)
            lookup = self._external_lookup(text) if eager_network else {"query": query, "results": [], "status": "planned"}
            tool_requests.append(
                ToolRequest(
                    name="external_lookup",
                    reason=f"turn requests external lookup for {lookup.get('query', query)}",
                    payload=lookup,
                )
            )
            if eager_network:
                for item in lookup.get("results", [])[:2]:
                    line = f"external lookup: {lookup.get('query', query)}"
                    title = str(item.get("title", "") or "")
                    snippet = str(item.get("snippet", "") or "")
                    if title:
                        line += f" | title: {title}"
                    if snippet:
                        line += f" | snippet: {snippet}"
                    tool_context_lines.append(line)
            elif query:
                tool_context_lines.append(f"lookup planned: {query}")

        attachment_summaries = self._summarize_attachments(meta.get("attachments"))
        for item in attachment_summaries:
            tool_requests.append(
                ToolRequest(
                    name=item["tool_name"],
                    reason=item["reason"],
                    payload=item["payload"],
                )
            )
            tool_context_lines.append(item["line"])

        return {
            "tool_context_lines": tool_context_lines,
            "tool_requests": [request.to_dict() for request in tool_requests],
            "attachment_summaries": attachment_summaries,
        }

    def execute_external_lookup(self, text: str) -> dict[str, Any]:
        return self._external_lookup(text)

    @staticmethod
    def _normalize_lookup_query(text: str) -> str:
        current = " ".join(str(text or "").strip().split())
        prefixes = (
            "帮我查一下",
            "帮我搜一下",
            "你去查一下",
            "你去搜一下",
            "查一下",
            "搜一下",
            "搜索一下",
            "look up",
            "search for",
        )
        for prefix in prefixes:
            if current.lower().startswith(prefix.lower()):
                current = current[len(prefix):].strip(" ：:，,。.!?？")
                break
        return compact_text(current, 160)

    @staticmethod
    def _should_external_lookup(text: str, metadata: dict[str, Any]) -> bool:
        current = " ".join(str(text or "").strip().split())
        if not current or URL_RE.search(current):
            return False
        lowered = current.lower()
        explicit_search = any(hint in current or hint in lowered for hint in SEARCH_HINTS)
        local_memory = any(hint in current or hint in lowered for hint in MEMORY_LOCAL_HINTS)
        factual_shape = (
            any(marker in current for marker in ("是什么", "是谁", "资料", "百科", "官网", "电影", "演员", "导演"))
            or any(marker in lowered for marker in ("what is", "who is", "official", "latest", "movie", "film", "actor", "director"))
        )
        if metadata.get("attachments"):
            return False
        if explicit_search:
            return True
        return bool(factual_shape and not local_memory)

    def _external_lookup(self, text: str) -> dict[str, Any]:
        query = self._normalize_lookup_query(text)
        if not query:
            return {"query": "", "results": [], "status": "skipped"}
        url = f"https://html.duckduckgo.com/html/?q={parse.quote_plus(query)}"
        opener = request.build_opener(request.ProxyHandler({}))
        opener.addheaders = [("User-Agent", "Mozilla/5.0")]
        try:
            with opener.open(url, timeout=5) as response:  # noqa: S310
                html_text = response.read(48000).decode("utf-8", errors="replace")
        except (OSError, error.URLError, TimeoutError) as exc:
            return {"query": query, "results": [], "status": "error", "error": str(exc)}

        anchors = list(LOOKUP_RESULT_RE.finditer(html_text))
        snippets = [match.group("snippet") for match in LOOKUP_SNIPPET_RE.finditer(html_text)]
        results: list[dict[str, Any]] = []
        for index, match in enumerate(anchors[:3]):
            title = _strip_tags(match.group("title"))
            target_url = _decode_duckduckgo_href(match.group("url"))
            snippet = _strip_tags(snippets[index] if index < len(snippets) else "")
            if not title and not snippet:
                continue
            results.append(
                {
                    "title": title,
                    "url": target_url,
                    "snippet": compact_text(snippet, 180),
                }
            )
        return {"query": query, "results": results, "status": "ok" if results else "empty"}

    def _preview_urls(self, text: str) -> list[dict[str, Any]]:
        urls = []
        for match in URL_RE.finditer(str(text or "")):
            url = match.group(0).rstrip(").,!?，。！；;")
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= 2:
                break
        previews: list[dict[str, Any]] = []
        opener = request.build_opener(request.ProxyHandler({}))
        for url in urls:
            preview: dict[str, Any] = {"url": url}
            try:
                with opener.open(url, timeout=4) as response:  # noqa: S310
                    content_type = str(response.headers.get("Content-Type", "") or "")
                    raw = response.read(12000)
                preview["content_type"] = content_type
                if "text/html" in content_type:
                    html_text = raw.decode("utf-8", errors="replace")
                    preview["title"] = _extract_title(html_text)
                    preview["snippet"] = _strip_tags(html_text)
                elif content_type.startswith("text/"):
                    preview["snippet"] = compact_text(raw.decode("utf-8", errors="replace"), 160)
            except (OSError, error.URLError, TimeoutError) as exc:
                preview["error"] = str(exc)
            previews.append(preview)
        return previews

    def _summarize_attachments(self, attachments: Any) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        if not isinstance(attachments, list):
            return rows
        for attachment in attachments[:4]:
            if not isinstance(attachment, dict):
                continue
            raw_path = str(attachment.get("path", "") or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            media_type = str(attachment.get("media_type", "") or "").strip()
            if not media_type:
                media_type = mimetypes.guess_type(str(path))[0] or ""
            sidecar = _read_sidecar_text(path)
            payload = {
                "path": str(path),
                "file_name": path.name,
                "media_type": media_type,
                "summary": compact_text(str(attachment.get("summary", "") or sidecar), 220),
            }
            if not self.config.runtime.image_enabled and media_type.startswith("image/"):
                continue
            tool_name = "image_describe" if media_type.startswith("image/") else "artifact_read"
            reason = f"turn includes attachment {path.name}"
            line = f"attachment: {path.name}"
            if media_type:
                line += f" | media_type: {media_type}"
            if payload["summary"]:
                line += f" | summary: {payload['summary']}"
            rows.append({"tool_name": tool_name, "reason": reason, "payload": payload, "line": line})
        return rows
