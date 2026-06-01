from __future__ import annotations

import html
import re
from html.parser import HTMLParser

from kernel_v3.retrieval.contracts import ExtractedSpan, FetchedDocument, SearchGoal
from kernel_v3.retrieval.evaluate import QUERY_FACET_ALIASES, query_facets

READABLE_TEXT_LIMIT = 200_000
SPAN_BEFORE_CHARS = 120
SPAN_AFTER_CHARS = 280
HTML_MIME_MARKERS = ("html", "xhtml")
PDF_MIME_MARKERS = ("pdf", "application/pdf")
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
    if _looks_like_pdf(body, mime_type=mime_type):
        return _extract_pdf_text(body), "pdf_text_literals"
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


def _looks_like_pdf(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in PDF_MIME_MARKERS):
        return True
    return body[:16].lstrip().startswith("%PDF")


def _extract_pdf_text(body: str) -> str:
    sample = body[:READABLE_TEXT_LIMIT]
    pieces = []
    pieces.extend(_pdf_literal_strings(sample))
    pieces.extend(_pdf_hex_strings(sample))
    return _normalize_span(" ".join(pieces)[:READABLE_TEXT_LIMIT])


def _pdf_literal_strings(text: str) -> list[str]:
    pieces: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "(":
            index += 1
            continue
        parsed, next_index = _parse_pdf_literal(text, index + 1)
        if _looks_like_readable_pdf_text(parsed):
            pieces.append(parsed)
        index = max(next_index, index + 1)
    return pieces


def _parse_pdf_literal(text: str, index: int) -> tuple[str, int]:
    depth = 1
    pieces: list[str] = []
    while index < len(text) and depth:
        char = text[index]
        if char == "\\":
            parsed, index = _parse_pdf_escape(text, index + 1)
            if parsed:
                pieces.append(parsed)
            continue
        if char == "(":
            depth += 1
            pieces.append(char)
            index += 1
            continue
        if char == ")":
            depth -= 1
            if depth:
                pieces.append(char)
            index += 1
            continue
        pieces.append(char)
        index += 1
    return "".join(pieces), index


def _parse_pdf_escape(text: str, index: int) -> tuple[str, int]:
    if index >= len(text):
        return "", index
    char = text[index]
    escapes = {
        "n": "\n",
        "r": "\r",
        "t": "\t",
        "b": "\b",
        "f": "\f",
        "(": "(",
        ")": ")",
        "\\": "\\",
    }
    if char in escapes:
        return escapes[char], index + 1
    if char in "\r\n":
        while index < len(text) and text[index] in "\r\n":
            index += 1
        return "", index
    if char in "01234567":
        end = index
        while end < min(len(text), index + 3) and text[end] in "01234567":
            end += 1
        try:
            return chr(int(text[index:end], 8)), end
        except ValueError:
            return "", end
    return char, index + 1


def _pdf_hex_strings(text: str) -> list[str]:
    pieces: list[str] = []
    for match in re.finditer(r"(?<!<)<([0-9A-Fa-f\s]{4,4096})>(?!>)", text):
        raw = "".join(match.group(1).split())
        if len(raw) % 2:
            raw = raw[:-1]
        if len(raw) < 4:
            continue
        try:
            data = bytes.fromhex(raw)
        except ValueError:
            continue
        decoded = _decode_pdf_hex_text(data)
        if _looks_like_readable_pdf_text(decoded):
            pieces.append(decoded)
    return pieces


def _decode_pdf_hex_text(data: bytes) -> str:
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16-be", errors="ignore")
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16-le", errors="ignore")
    if len(data) >= 4:
        odd_nulls = sum(1 for index in range(0, len(data), 2) if data[index] == 0)
        even_nulls = sum(1 for index in range(1, len(data), 2) if data[index] == 0)
        if odd_nulls >= max(2, len(data) // 6):
            return data.decode("utf-16-be", errors="ignore")
        if even_nulls >= max(2, len(data) // 6):
            return data.decode("utf-16-le", errors="ignore")
    return data.decode("latin-1", errors="ignore")


def _looks_like_readable_pdf_text(text: str) -> bool:
    normalized = _normalize_span(text)
    if len(normalized) < 3:
        return False
    content_chars = sum(1 for char in normalized if char.isalnum() or "\u4e00" <= char <= "\u9fff")
    printable_chars = sum(1 for char in normalized if char.isprintable())
    if content_chars < 2:
        return False
    if printable_chars / max(1, len(normalized)) < 0.8:
        return False
    return True


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
    for facet in query_facets(text):
        for alias in QUERY_FACET_ALIASES.get(facet, ()):
            normalized = alias.lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                terms.append(normalized)
    return terms


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
