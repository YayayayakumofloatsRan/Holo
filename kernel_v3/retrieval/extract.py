from __future__ import annotations

import html
from html.parser import HTMLParser

from kernel_v3.retrieval.contracts import ExtractedSpan, FetchedDocument, SearchGoal

READABLE_TEXT_LIMIT = 200_000
SPAN_BEFORE_CHARS = 120
SPAN_AFTER_CHARS = 280
HTML_MIME_MARKERS = ("html", "xhtml")
HTML_BLOCK_TAGS = {
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
HTML_SKIP_TAGS = {
    "canvas",
    "footer",
    "head",
    "header",
    "nav",
    "noscript",
    "script",
    "style",
    "svg",
    "template",
}


def extract_spans(
    *,
    goal: SearchGoal,
    document: FetchedDocument,
    body: str,
) -> list[ExtractedSpan]:
    if not body:
        return []
    terms = _terms(goal.query)
    if not terms:
        return []
    text, text_mode = readable_document_text(body, document=document)
    if not text:
        return []
    spans: list[ExtractedSpan] = []
    for candidate in _ranked_span_candidates(text, terms):
        spans.append(
            ExtractedSpan(
                span_id=f"span-{document.document_id}-{len(spans) + 1}",
                goal_id=goal.goal_id,
                document_id=document.document_id,
                source_id=document.source_id,
                text=candidate["text"],
                start_offset=candidate["start_offset"],
                end_offset=candidate["end_offset"],
                score=candidate["score"],
                metadata={
                    "matched_terms": candidate["matched_terms"],
                    "text_mode": text_mode,
                },
            )
        )
        if len(spans) >= goal.max_spans_per_document:
            break
    return spans


def readable_document_text(body: str, *, document: FetchedDocument) -> tuple[str, str]:
    mime_type = str(document.metadata.get("mime_type") or "").lower()
    if _looks_like_html(body, mime_type=mime_type):
        return _extract_html_readable_text(body), "html_readable_text"
    return _normalize_span(body[:READABLE_TEXT_LIMIT]), "plain_text"


def _ranked_span_candidates(text: str, terms: list[str]) -> list[dict]:
    lower = text.lower()
    candidates: list[dict] = []
    seen_windows: set[tuple[int, int]] = set()
    for term in terms:
        start = 0
        while True:
            index = lower.find(term, start)
            if index < 0:
                break
            window_start = max(0, index - SPAN_BEFORE_CHARS)
            window_end = min(len(text), index + len(term) + SPAN_AFTER_CHARS)
            key = _coarse_window_key(window_start, window_end)
            if key not in seen_windows:
                seen_windows.add(key)
                snippet = _normalize_span(text[window_start:window_end])
                matched = [candidate for candidate in terms if candidate in snippet.lower()]
                if snippet and matched:
                    candidates.append(
                        {
                            "start_offset": window_start,
                            "end_offset": window_end,
                            "text": snippet,
                            "matched_terms": matched,
                            "score": min(1.0, len(matched) / max(1, len(terms))),
                        }
                    )
            start = index + max(1, len(term))
    return sorted(
        candidates,
        key=lambda item: (
            -float(item["score"]),
            -len(item["matched_terms"]),
            int(item["start_offset"]),
        ),
    )


def _coarse_window_key(start: int, end: int) -> tuple[int, int]:
    return start // 120, end // 120


def _looks_like_html(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in HTML_MIME_MARKERS):
        return True
    prefix = body[:2048].lower()
    return "<html" in prefix or "<!doctype html" in prefix or "<body" in prefix


def _extract_html_readable_text(body: str) -> str:
    parser = _ReadableHtmlParser()
    parser.feed(body[:READABLE_TEXT_LIMIT])
    parser.close()
    return _normalize_span(parser.text())


class _ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in HTML_SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if normalized in HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in HTML_SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if normalized in HTML_BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = " ".join(html.unescape(data).split())
        if text:
            self._parts.append(text)
            self._parts.append(" ")

    def text(self) -> str:
        return "".join(self._parts)


def _terms(text: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for term in text.lower().replace("-", " ").split():
        if not term or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
