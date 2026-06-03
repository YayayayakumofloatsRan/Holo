from __future__ import annotations

import csv
import html
import io
import json
import re
from html.parser import HTMLParser

from kernel_v3.research.profile_policy import (
    QUERY_FACET_ALIASES,
    profile_extraction_aliases,
    query_facets,
    resolve_goal_research_profile,
)
from kernel_v3.retrieval.contracts import ExtractedSpan, FetchedDocument, SearchGoal

READABLE_TEXT_LIMIT = 200_000
SPAN_BEFORE_CHARS = 120
SPAN_AFTER_CHARS = 280
HTML_MIME_MARKERS = ("html", "xhtml")
PDF_MIME_MARKERS = ("pdf", "application/pdf")
JSON_MIME_MARKERS = ("json", "application/json")
CSV_MIME_MARKERS = ("csv", "comma-separated-values")
STRUCTURED_LINE_LIMIT = 2_000
STRUCTURED_VALUE_LIMIT = 240
SEC_COMPANYFACTS_CONCEPTS = (
    ("Revenues", "revenue"),
    ("RevenueFromContractWithCustomerExcludingAssessedTax", "revenue"),
    ("SalesRevenueNet", "net sales"),
    ("NetIncomeLoss", "net income"),
    ("ProfitLoss", "net income"),
    ("OperatingIncomeLoss", "operating income"),
    ("GrossProfit", "gross profit"),
    ("NetCashProvidedByUsedInOperatingActivities", "operating cash flow"),
    ("CashAndCashEquivalentsAtCarryingValue", "cash and cash equivalents"),
    ("Assets", "assets"),
    ("Liabilities", "liabilities"),
    ("StockholdersEquity", "shareholders equity"),
    ("EarningsPerShareDiluted", "diluted earnings per share"),
)
SEC_COMPANYFACTS_FORMS = {"10-K", "10-Q", "20-F", "40-F"}
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
    terms = _terms(goal.query, goal=goal)
    if not terms:
        return []
    text, text_mode = readable_document_text(body, document=document)
    if not text:
        return []
    spans: list[ExtractedSpan] = []
    candidates = (
        _ranked_structured_line_candidates(text, terms)
        if text_mode == "sec_companyfacts_readable_text"
        else _ranked_span_candidates(text, terms)
    )
    for candidate in candidates:
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
    if _looks_like_sec_companyfacts(body, document=document):
        text = _extract_sec_companyfacts_readable_text(body)
        if text:
            return text, "sec_companyfacts_readable_text"
    if _looks_like_json(body, mime_type=mime_type):
        text = _extract_json_readable_text(body)
        if text:
            return text, "json_readable_text"
    if _looks_like_csv(body, document=document, mime_type=mime_type):
        text = _extract_csv_readable_text(body)
        if text:
            return text, "csv_readable_text"
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


def _ranked_structured_line_candidates(text: str, terms: list[str]) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []
    header = lines[0]
    candidates: list[dict] = []
    offset = 0
    for line in lines:
        lower = line.lower()
        matched = [candidate for candidate in terms if candidate in lower]
        if matched:
            snippet = _normalize_span(f"{header} {line}")
            candidates.append(
                {
                    "start_offset": offset,
                    "end_offset": offset + len(line),
                    "text": snippet,
                    "matched_terms": matched,
                    "score": min(1.0, len(matched) / max(1, len(terms))),
                }
            )
        offset += len(line) + 1
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


def _looks_like_json(body: str, *, mime_type: str) -> bool:
    if any(marker in mime_type for marker in JSON_MIME_MARKERS):
        return True
    prefix = body[:1024].lstrip()
    return prefix.startswith("{") or prefix.startswith("[")


def _looks_like_csv(body: str, *, document: FetchedDocument, mime_type: str) -> bool:
    if any(marker in mime_type for marker in CSV_MIME_MARKERS):
        return True
    uri = document.uri.lower()
    if uri.endswith(".csv") or ".csv?" in uri:
        return True
    lines = [line for line in body[:4096].splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    first_columns = [item.strip() for item in lines[0].split(",")]
    second_columns = [item.strip() for item in lines[1].split(",")]
    if len(first_columns) < 2 or len(second_columns) < 2:
        return False
    return abs(len(first_columns) - len(second_columns)) <= 1


def _extract_json_readable_text(body: str) -> str:
    try:
        payload = json.loads(body[:READABLE_TEXT_LIMIT])
    except json.JSONDecodeError:
        return ""
    lines: list[str] = []
    _flatten_json(payload, path="", lines=lines, depth=0)
    return _normalize_span(" ".join(lines)[:READABLE_TEXT_LIMIT])


def _looks_like_sec_companyfacts(body: str, *, document: FetchedDocument) -> bool:
    uri = document.uri.lower()
    title = document.title.lower()
    if "data.sec.gov/api/xbrl/companyfacts/" in uri or "sec companyfacts" in title:
        return True
    prefix = body[:4096]
    return '"facts"' in prefix and '"entityName"' in prefix and "us-gaap" in prefix


def _extract_sec_companyfacts_readable_text(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if not isinstance(payload, dict):
        return ""
    facts = payload.get("facts")
    if not isinstance(facts, dict):
        return ""
    entity_name = _structured_value(payload.get("entityName") or "")
    cik = _structured_value(payload.get("cik") or "")
    lines = [
        _normalize_span(
            f"SEC companyfacts official financial statements entityName={entity_name} cik={cik} source=SEC_XBRL_companyfacts"
        )
    ]
    for taxonomy_name in ("us-gaap", "ifrs-full", "dei"):
        taxonomy = facts.get(taxonomy_name)
        if not isinstance(taxonomy, dict):
            continue
        for concept, metric in SEC_COMPANYFACTS_CONCEPTS:
            item = taxonomy.get(concept)
            if not isinstance(item, dict):
                continue
            label = _structured_value(item.get("label") or concept)
            units = item.get("units")
            if not isinstance(units, dict):
                continue
            for unit, records in units.items():
                if not isinstance(records, list):
                    continue
                for record in _recent_companyfacts_records(records)[:6]:
                    if not isinstance(record, dict):
                        continue
                    lines.append(
                        _companyfacts_record_line(
                            entity_name=entity_name,
                            cik=cik,
                            taxonomy=taxonomy_name,
                            concept=concept,
                            metric=metric,
                            label=label,
                            unit=_structured_value(unit),
                            record=record,
                        )
                    )
                    if len(lines) >= STRUCTURED_LINE_LIMIT:
                        return "\n".join(lines)[:READABLE_TEXT_LIMIT]
    return "\n".join(lines)[:READABLE_TEXT_LIMIT]


def _recent_companyfacts_records(records: list[object]) -> list[object]:
    filtered = [
        record
        for record in records
        if isinstance(record, dict) and str(record.get("form") or "").upper().replace(" ", "") in SEC_COMPANYFACTS_FORMS
    ]
    if not filtered:
        filtered = [record for record in records if isinstance(record, dict)]
    return sorted(
        filtered,
        key=lambda record: (
            str(record.get("filed") or ""),
            str(record.get("end") or ""),
            int(record.get("fy") or 0) if isinstance(record.get("fy"), int) else 0,
        ),
        reverse=True,
    )


def _companyfacts_record_line(
    *,
    entity_name: str,
    cik: str,
    taxonomy: str,
    concept: str,
    metric: str,
    label: str,
    unit: str,
    record: dict,
) -> str:
    parts = [
        f"SEC companyfacts official financial statement entityName={entity_name}",
        f"cik={cik}",
        f"taxonomy={taxonomy}",
        f"concept={concept}",
        f"metric={metric}",
        f"label={label}",
        f"unit={unit}",
    ]
    for key in ("val", "fy", "fp", "form", "filed", "end", "start", "frame", "accn"):
        value = record.get(key)
        if value is None or value == "":
            continue
        parts.append(f"{key}={_structured_value(value)}")
    return _truncate_structured_line(" ".join(parts))


def _flatten_json(value: object, *, path: str, lines: list[str], depth: int) -> None:
    if len(lines) >= STRUCTURED_LINE_LIMIT or depth > 12:
        return
    if isinstance(value, dict):
        scalar_parts = []
        complex_items = []
        for key, item in value.items():
            key_text = _structured_key(key)
            next_path = f"{path}.{key_text}" if path else key_text
            if _is_scalar(item):
                scalar_parts.append(f"{key_text}={_structured_value(item)}")
            else:
                complex_items.append((next_path, item))
        if scalar_parts:
            prefix = f"{path}: " if path else ""
            lines.append(_truncate_structured_line(prefix + " ".join(scalar_parts)))
        for next_path, item in complex_items:
            _flatten_json(item, path=next_path, lines=lines, depth=depth + 1)
            if len(lines) >= STRUCTURED_LINE_LIMIT:
                break
        return
    if isinstance(value, list):
        for index, item in enumerate(value[:500]):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            _flatten_json(item, path=next_path, lines=lines, depth=depth + 1)
            if len(lines) >= STRUCTURED_LINE_LIMIT:
                break
        if len(value) > 500 and len(lines) < STRUCTURED_LINE_LIMIT:
            lines.append(f"{path}: truncated_list_count={len(value)}")
        return
    if _is_scalar(value):
        lines.append(_truncate_structured_line(f"{path}: {_structured_value(value)}" if path else _structured_value(value)))


def _extract_csv_readable_text(body: str) -> str:
    sample = body[:READABLE_TEXT_LIMIT]
    try:
        rows = list(csv.reader(io.StringIO(sample)))
    except csv.Error:
        return ""
    if not rows:
        return ""
    header = [_structured_key(item) for item in rows[0]]
    has_header = bool(header) and any(not _looks_numeric(item) for item in header)
    lines: list[str] = []
    if has_header:
        lines.append("csv_header: " + " ".join(header))
        data_rows = rows[1:]
    else:
        header = [f"column_{index + 1}" for index in range(max(len(row) for row in rows[:20]))]
        data_rows = rows
    for row_index, row in enumerate(data_rows[: min(500, STRUCTURED_LINE_LIMIT - len(lines))], start=1):
        if not any(cell.strip() for cell in row):
            continue
        parts = []
        for column_index, cell in enumerate(row):
            key = header[column_index] if column_index < len(header) else f"column_{column_index + 1}"
            parts.append(f"{key}={_structured_value(cell)}")
        lines.append(_truncate_structured_line(f"csv_row_{row_index}: " + " ".join(parts)))
    return _normalize_span(" ".join(lines)[:READABLE_TEXT_LIMIT])


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _structured_key(value: object) -> str:
    text = str(value).strip()
    return re.sub(r"\s+", "_", text)[:80] or "field"


def _structured_value(value: object) -> str:
    if value is None:
        return "null"
    text = str(value).strip()
    return _normalize_span(text)[:STRUCTURED_VALUE_LIMIT]


def _truncate_structured_line(text: str) -> str:
    normalized = _normalize_span(text)
    if len(normalized) <= 1_000:
        return normalized
    return normalized[:997] + "..."


def _looks_numeric(value: object) -> bool:
    try:
        float(str(value).strip())
    except ValueError:
        return False
    return True


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


def _terms(text: str, *, goal: SearchGoal | None = None) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    def add(term: str) -> None:
        normalized = term.lower().replace("-", " ").strip()
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        terms.append(normalized)

    for term in text.lower().replace("-", " ").split():
        add(term)
    for facet in query_facets(text):
        for alias in QUERY_FACET_ALIASES.get(facet, ()):
            add(alias)
    if goal is not None:
        profile = resolve_goal_research_profile(goal)
        for alias in profile_extraction_aliases(goal=goal, research_profile=profile):
            add(alias)
    return terms


def _normalize_span(text: str) -> str:
    return " ".join(text.split())
