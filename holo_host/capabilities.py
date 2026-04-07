from __future__ import annotations

import mimetypes
import re
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Any
from urllib import error, request

from .common import compact_text
from .config import HostConfig
from .models import ToolRequest

URL_RE = re.compile(r"https?://[^\s<>\u3000]+", re.IGNORECASE)


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


@dataclass(slots=True)
class CapabilityBroker:
    config: HostConfig

    def summarize_turn(self, text: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = dict(metadata or {})
        tool_requests: list[ToolRequest] = []
        tool_context_lines: list[str] = []

        if self.config.runtime.network_enabled:
            for preview in self._preview_urls(text):
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
                    line = f"链接预览：{preview['url']}"
                    if title:
                        line += f" | 标题：{title}"
                    if snippet:
                        line += f" | 摘要：{snippet}"
                    tool_context_lines.append(line)

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

    def _preview_urls(self, text: str) -> list[dict[str, Any]]:
        urls = []
        for match in URL_RE.finditer(str(text or "")):
            url = match.group(0).rstrip(").,!?，。！？；;")
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
                    cleaned = re.sub(r"<[^>]+>", " ", html_text)
                    preview["snippet"] = compact_text(unescape(re.sub(r"\s+", " ", cleaned).strip()), 160)
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
            line = f"附件：{path.name}"
            if media_type:
                line += f" | 类型：{media_type}"
            if payload["summary"]:
                line += f" | 摘要：{payload['summary']}"
            rows.append({"tool_name": tool_name, "reason": reason, "payload": payload, "line": line})
        return rows
