from __future__ import annotations

import base64
import binascii
import re
import urllib.parse


HTTP_URL_RE = re.compile(r"https?://[^\s<>'\")\]]+")
WRAPPER_QUERY_KEYS = {
    "pdftarget",
    "target",
    "targeturl",
    "url",
    "u",
    "uri",
    "redirect",
    "redirecturl",
    "redirect_url",
    "download",
    "file",
    "href",
}


def is_http_url(value: object) -> bool:
    text = str(value or "").strip().lower()
    return text.startswith(("http://", "https://"))


def unwrap_url_candidates(url: str) -> list[str]:
    text = str(url or "").strip()
    if not is_http_url(text):
        return []
    parsed = urllib.parse.urlparse(text)
    values: list[str] = []
    values.extend(_candidate_query_values(parsed.query))
    if parsed.fragment:
        values.extend(_candidate_query_values(parsed.fragment.lstrip("?")))

    candidates: list[str] = []
    for value in values:
        candidates.extend(_urls_from_encoded_value(value))
    original = _normalize_url(text)
    return [item for item in _ordered_unique(candidates) if _normalize_url(item) != original]


def url_equivalent_or_unwrapped(left: str, right: str) -> bool:
    left_norm = _normalize_url(left)
    right_norm = _normalize_url(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm or left_norm.startswith(f"{right_norm}/") or right_norm.startswith(f"{left_norm}/"):
        return True
    left_variants = {_normalize_url(item) for item in unwrap_url_candidates(left)}
    right_variants = {_normalize_url(item) for item in unwrap_url_candidates(right)}
    left_variants.discard("")
    right_variants.discard("")
    return bool(right_norm in left_variants or left_norm in right_variants or left_variants.intersection(right_variants))


def expanded_url_targets(url: str, *, prefer_unwrapped: bool = True) -> list[tuple[str, str | None]]:
    text = str(url or "").strip()
    if not is_http_url(text):
        return []
    unwrapped = [(candidate, text) for candidate in unwrap_url_candidates(text)]
    original = [(text, None)]
    ordered = [*unwrapped, *original] if prefer_unwrapped and unwrapped else [*original, *unwrapped]
    result: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for candidate, wrapped_from in ordered:
        normalized = _normalize_url(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append((candidate, wrapped_from))
    return result


def _candidate_query_values(query: str) -> list[str]:
    values: list[str] = []
    for key, value in urllib.parse.parse_qsl(query, keep_blank_values=False):
        key_normalized = key.strip().replace("-", "_").lower()
        value_text = str(value or "").strip()
        if not value_text:
            continue
        unquoted = urllib.parse.unquote(value_text).strip()
        if (
            key_normalized in WRAPPER_QUERY_KEYS
            or is_http_url(unquoted)
            or unquoted.lower().startswith(("http%3a", "https%3a"))
        ):
            values.append(value_text)
    return values


def _urls_from_encoded_value(value: str) -> list[str]:
    pieces = _ordered_unique([value, urllib.parse.unquote(value)])
    decoded = [_decode_base64_url(piece) for piece in pieces]
    pieces.extend(item for item in decoded if item)
    result: list[str] = []
    for piece in pieces:
        text = str(piece or "").strip()
        if is_http_url(text):
            result.append(text)
        for match in HTTP_URL_RE.findall(text):
            url = match.rstrip(".,;:，。；：")
            if is_http_url(url):
                result.append(url)
    return _ordered_unique(result)


def _decode_base64_url(value: str) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 4096:
        return ""
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 16 or not re.fullmatch(r"[A-Za-z0-9_\-+/=]+", compact):
        return ""
    padded = compact + ("=" * (-len(compact) % 4))
    try:
        decoded = base64.urlsafe_b64decode(padded.encode("ascii"))
    except (ValueError, binascii.Error):
        return ""
    return decoded.decode("utf-8", errors="replace").strip()


def _normalize_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        key = text.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result
