from __future__ import annotations

from dataclasses import asdict, dataclass
import html
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(slots=True)
class PageFetchResult:
    url: str
    final_url: str
    status: str
    status_code: int = 0
    content_type: str = ""
    text: str = ""
    bytes_read: int = 0
    elapsed_ms: int = 0
    error: str = ""
    error_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ExtractedPage:
    url: str
    title: str
    text: str
    content_type: str
    extraction_quality: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PageFetcher:
    def __init__(self, *, user_agent: str = "Mozilla/5.0 HoloAgentKernel/2.1.0", opener: Any | None = None, max_bytes: int = 2_000_000) -> None:
        self.user_agent = user_agent
        self.opener = opener
        self.max_bytes = max_bytes

    def fetch(self, url: str, *, timeout: int = 15) -> PageFetchResult:
        started = time.perf_counter()
        request = Request(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,text/plain;q=0.8,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            },
        )
        try:
            response = self.opener.open(request, timeout=timeout) if self.opener is not None else urlopen(request, timeout=timeout)  # nosec B310
            with response:
                raw = response.read(self.max_bytes)
                charset = response.headers.get_content_charset() or "utf-8"
                text = raw.decode(charset, errors="replace")
                final_url = getattr(response, "url", url) or url
                status_code = int(getattr(response, "status", 200) or 200)
                content_type = str(response.headers.get("content-type", "") or "")
            return PageFetchResult(
                url=url,
                final_url=final_url,
                status="ok",
                status_code=status_code,
                content_type=content_type,
                text=text,
                bytes_read=len(raw),
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except HTTPError as exc:
            return PageFetchResult(
                url=url,
                final_url=getattr(exc, "url", url) or url,
                status="error",
                status_code=int(getattr(exc, "code", 0) or 0),
                content_type=str(getattr(exc, "headers", {}).get("content-type", "") or ""),
                error=str(exc),
                error_type=exc.__class__.__name__,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except URLError as exc:
            return PageFetchResult(
                url=url,
                final_url=url,
                status="error",
                error=str(exc),
                error_type=exc.__class__.__name__,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return PageFetchResult(
                url=url,
                final_url=url,
                status="error",
                error=str(exc),
                error_type=exc.__class__.__name__,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
            )


def _compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(text or ""))).strip()


def extract_page_text(raw: str, *, url: str, content_type: str = "") -> ExtractedPage:
    text = str(raw or "")
    title = ""
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", text)
    if match:
        title = _compact_whitespace(re.sub(r"(?is)<[^>]+>", " ", match.group(1)))
    if "html" in content_type.lower() or "<html" in text.lower() or "<body" in text.lower():
        text = re.sub(r"(?is)<(script|style|noscript|svg|canvas).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?is)<(nav|footer|header|aside).*?>.*?</\1>", " ", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
    clean = _compact_whitespace(text)
    if not title:
        title = clean[:80]
    html_like = "html" in content_type.lower() or "<html" in str(raw or "").lower() or "<body" in str(raw or "").lower()
    length_score = min(0.55, len(clean) / 1200.0)
    title_bonus = 0.2 if title else 0.0
    structure_bonus = 0.15 if html_like else 0.0
    content_bonus = 0.1 if len(clean) >= 20 else 0.0
    quality = min(1.0, length_score + title_bonus + structure_bonus + content_bonus)
    return ExtractedPage(url=url, title=title, text=clean, content_type=content_type, extraction_quality=round(quality, 4))
