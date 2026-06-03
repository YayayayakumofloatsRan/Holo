from __future__ import annotations

import re


ENTITY_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9&'.-]*")
QUOTED_PHRASE_RE = re.compile(r'"([^"\n]{2,120})"|“([^”\n]{2,120})”|\'([^\'\n]{2,120})\'')
URL_RE = re.compile(r"https?://[^\s<>'\")\]]+", re.IGNORECASE)

GENERIC_QUERY_TERMS = {
    "about",
    "annual",
    "balance",
    "business",
    "cash",
    "company",
    "companies",
    "current",
    "data",
    "employees",
    "employee",
    "financial",
    "financials",
    "find",
    "flow",
    "fundamental",
    "fundamentals",
    "how",
    "income",
    "information",
    "info",
    "key",
    "latest",
    "market",
    "metrics",
    "model",
    "official",
    "operation",
    "operations",
    "quarterly",
    "report",
    "reports",
    "research",
    "revenue",
    "revenues",
    "scale",
    "search",
    "size",
    "source",
    "sources",
    "statement",
    "statements",
    "stock",
    "valuation",
    "work",
    "works",
    "cashandcashequivalentsatcarryingvalue",
    "earningspersharediluted",
    "grossprofit",
    "liabilities",
    "netcashprovidedbyusedinoperatingactivities",
    "netincomeloss",
    "operatingincomeloss",
    "profitloss",
    "revenuefromcontractwithcustomerexcludingassessedtax",
    "salesrevenuenet",
    "stockholdersequity",
}

LEGAL_SUFFIX_TERMS = {
    "ag",
    "bv",
    "co",
    "corp",
    "corporation",
    "gmbh",
    "inc",
    "incorporated",
    "llc",
    "llp",
    "ltd",
    "limited",
    "nv",
    "plc",
    "sa",
}


def target_entity_phrases(query: str) -> list[str]:
    query = URL_RE.sub(" ", query)
    phrases: list[str] = []
    for match in QUOTED_PHRASE_RE.finditer(query):
        raw = next((group for group in match.groups() if group), "")
        _append_phrase(phrases, raw)

    run: list[str] = []
    for token in ENTITY_TOKEN_RE.findall(query):
        if _is_entity_token(token):
            run.append(_clean_entity_token(token))
            continue
        _flush_entity_run(phrases, run)
        run = []
    _flush_entity_run(phrases, run)
    return _ordered_unique(phrases)


def target_entity_diagnostics(query: str, texts: list[str]) -> dict[str, object]:
    required = target_entity_phrases(query)
    haystack = _normalized_text(" ".join(text for text in texts if text))
    matched = [phrase for phrase in required if _phrase_matches(phrase, haystack)]
    missing = [phrase for phrase in required if phrase not in matched]
    return {
        "target_entity_required": bool(required),
        "required_target_phrases": required,
        "matched_target_phrases": matched,
        "missing_target_phrases": missing,
        "target_entity_satisfied": not missing,
    }


def assess_target_entity_coverage(query: str, evidence_texts: list[str]) -> dict[str, object]:
    diagnostics = target_entity_diagnostics(query, evidence_texts)
    return {
        "target_entity_required": diagnostics["target_entity_required"],
        "required_target_phrases": diagnostics["required_target_phrases"],
        "covered_target_phrases": diagnostics["matched_target_phrases"],
        "missing_target_phrases": diagnostics["missing_target_phrases"],
        "target_entity_satisfied": diagnostics["target_entity_satisfied"],
    }


def _is_entity_token(token: str) -> bool:
    cleaned = _clean_entity_token(token)
    if not cleaned:
        return False
    lower = cleaned.lower()
    if lower in GENERIC_QUERY_TERMS:
        return False
    if len(lower) <= 1:
        return False
    if cleaned.isupper():
        return True
    return cleaned[0].isupper() and any(char.islower() for char in cleaned)


def _flush_entity_run(phrases: list[str], run: list[str]) -> None:
    if len(run) < 2:
        return
    lower_terms = {token.lower() for token in run}
    if len(lower_terms) < 2:
        return
    mixed_case_count = sum(1 for token in run if any(char.islower() for char in token))
    has_legal_suffix = bool(lower_terms & LEGAL_SUFFIX_TERMS)
    if mixed_case_count >= 2 or has_legal_suffix:
        _append_phrase(phrases, " ".join(run))


def _append_phrase(phrases: list[str], raw: str) -> None:
    normalized = " ".join(_clean_entity_token(token) for token in ENTITY_TOKEN_RE.findall(raw))
    normalized = " ".join(token for token in normalized.split() if token)
    if len({token.lower() for token in normalized.split()}) >= 2:
        phrases.append(normalized)


def _phrase_matches(phrase: str, normalized_haystack: str) -> bool:
    normalized_phrase = _normalized_text(phrase)
    if not normalized_phrase:
        return False
    return f" {normalized_phrase} " in f" {normalized_haystack} "


def _normalized_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


def _clean_entity_token(token: str) -> str:
    return token.strip(" .'\"")


def _ordered_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out
