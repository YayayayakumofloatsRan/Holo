from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, replace

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.contracts import SearchSource


QUERY_TERM_PATTERN = re.compile(r"[A-Za-z0-9]+|[\u4e00-\u9fff]+")


@dataclass(frozen=True, kw_only=True)
class RankedSourceDirectoryEntry:
    entry: object
    score: float
    matched_terms: list[str]


def rank_source_directory_entries(
    entries: list[object],
    *,
    query: str,
    metadata: JsonObject,
) -> list[RankedSourceDirectoryEntry]:
    query_terms = query_terms_for_source_directory(query, metadata)
    task_terms = _source_directory_task_terms(metadata)
    task_text = " ".join(task_terms)
    preferred_families = set(_metadata_string_list(metadata, "preferred_source_families"))
    source_family = _metadata_string(metadata, "source_family")
    if source_family:
        preferred_families.add(source_family)
    scored: list[tuple[float, int, object, list[str]]] = []
    for index, entry in enumerate(entries):
        text = source_directory_entry_text(entry).lower()
        matched = _matched_query_terms(query_terms, text)
        score = _base_score(query_terms=query_terms, matched=matched)
        score += 0.08 * sum(1 for term in task_terms if term and term in text)
        family = str(getattr(entry, "source_family", "") or "")
        authority = str(getattr(entry, "authority_level", "") or "")
        if family in preferred_families:
            score += 0.3
        if metadata_requests_authority(metadata, authority):
            score += 0.2
        score += source_directory_task_boost(
            family=family.lower(),
            task_text=task_text,
            candidate_text=text,
        )
        scored.append((score, index, entry, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [
        RankedSourceDirectoryEntry(entry=entry, score=score, matched_terms=matched)
        for score, _index, entry, matched in scored
    ]


def rank_source_directory_sources(
    sources: list[SearchSource],
    *,
    query: str,
    metadata: JsonObject,
) -> list[SearchSource]:
    query_terms = query_terms_for_source_directory(query, metadata)
    task_terms = _source_directory_task_terms(metadata)
    task_text = " ".join(task_terms)
    preferred_families = set(_metadata_string_list(metadata, "preferred_source_families"))
    source_family = _metadata_string(metadata, "source_family")
    if source_family:
        preferred_families.add(source_family)
    scored: list[tuple[float, int, SearchSource, list[str]]] = []
    for index, source in enumerate(sources):
        text = source_directory_source_text(source).lower()
        matched = _matched_query_terms(query_terms, text)
        score = _base_score(query_terms=query_terms, matched=matched)
        score += 0.08 * sum(1 for term in task_terms if term and term in text)
        family = str(source.metadata.get("source_family") or "")
        authority = str(source.metadata.get("authority_level") or "")
        if family in preferred_families:
            score += 0.3
        if metadata_requests_authority(metadata, authority):
            score += 0.2
        score += source_directory_task_boost(
            family=family.lower(),
            task_text=task_text,
            candidate_text=text,
        )
        scored.append((score, index, source, matched))
    scored.sort(key=lambda item: (-item[0], item[1]))
    ranked: list[SearchSource] = []
    for rank, (score, _index, source, matched) in enumerate(scored, start=1):
        source_metadata = dict(source.metadata)
        source_metadata["rank"] = rank
        source_metadata["source_directory_relevance_score"] = round(score, 6)
        if matched:
            source_metadata["matched_query_terms"] = matched[:12]
        ranked.append(replace(source, metadata=source_metadata))
    return ranked


def query_terms_for_source_directory(query: str, metadata: JsonObject) -> list[str]:
    raw_values = [query]
    raw_values.extend(metadata_text_values(metadata))
    terms: list[str] = []
    for value in raw_values:
        for token in QUERY_TERM_PATTERN.findall(str(value).lower()):
            if len(token) >= 2:
                terms.append(token)
            if _contains_cjk(token) and len(token) >= 4:
                terms.extend(token[index : index + 2] for index in range(0, len(token) - 1))
    return _ordered_unique(terms)[:80]


def source_directory_entry_text(entry: object) -> str:
    pieces: list[str] = [
        str(getattr(entry, "source_id", "") or ""),
        str(getattr(entry, "title", "") or ""),
        str(getattr(entry, "source_family", "") or ""),
        str(getattr(entry, "authority_level", "") or ""),
        str(getattr(entry, "base_url", "") or ""),
    ]
    for field_name in ("use_cases", "required_identifiers", "query_hints", "crawl_notes", "allowed_hosts"):
        value = getattr(entry, field_name, [])
        if isinstance(value, list):
            pieces.extend(str(item) for item in value if isinstance(item, str))
    metadata = getattr(entry, "metadata", {})
    if isinstance(metadata, dict):
        pieces.extend(metadata_text_values(metadata))
    return " ".join(pieces)


def source_directory_source_text(source: SearchSource) -> str:
    parsed = urllib.parse.urlparse(source.uri)
    rank_text = source.metadata.get("source_directory_rank_text")
    if isinstance(rank_text, str) and rank_text.strip():
        return " ".join(
            [
                rank_text,
                str(source.metadata.get("source_family") or ""),
                str(source.metadata.get("authority_level") or ""),
                str(source.metadata.get("source_kind") or ""),
                parsed.hostname or "",
                parsed.path.replace("/", " "),
            ]
        )
    pieces = [
        source.title,
        source.snippet,
        source.uri,
        parsed.hostname or "",
        parsed.path.replace("/", " "),
    ]
    pieces.extend(metadata_text_values(source.metadata))
    return " ".join(pieces)


def source_directory_task_boost(*, family: str, task_text: str, candidate_text: str) -> float:
    if not task_text:
        return 0.0
    boost = 0.0
    if "market_news" in task_text or "news" in task_text or "latest" in task_text:
        if family == "reputable_news":
            boost += 0.45
        elif "news" in candidate_text:
            boost += 0.15
    if "market_data" in task_text or "quote" in task_text or "price" in task_text:
        if family == "market_data_provider":
            boost += 0.45
        elif "market data" in candidate_text or "quote" in candidate_text:
            boost += 0.15
    if "transcript" in task_text or "earnings_call" in task_text or "management" in task_text:
        if family == "earnings_transcript":
            boost += 0.45
    if "rating" in task_text or "credit" in task_text or "debt" in task_text:
        if family == "credit_rating_agency":
            boost += 0.45
    if "rate" in task_text or "macro" in task_text or "inflation" in task_text or "treasury" in task_text:
        if family in {"government_statistic", "central_bank_statistic", "treasury_data"}:
            boost += 0.35
    if "fundamental" in task_text or "filing" in task_text or "revenue" in task_text or "margin" in task_text:
        if family in {"regulatory_filing", "structured_regulatory_data", "company_ir", "exchange_filing"}:
            boost += 0.25
    return boost


def metadata_requests_authority(metadata: JsonObject, authority: str) -> bool:
    requested = _metadata_string(metadata, "source_authority_requirement")
    if not requested:
        requested = _metadata_string(metadata, "authority_level")
    requested = requested.lower()
    authority = authority.lower()
    if not requested or not authority:
        return False
    if requested == authority:
        return True
    if requested == "secondary_or_better" and authority in {"primary", "secondary"}:
        return True
    return requested == "primary_or_better" and authority == "primary"


def metadata_text_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        result: list[str] = []
        for key, item in value.items():
            if str(key).lower() in {"api_key", "token", "password", "secret", "authorization"}:
                continue
            result.extend(metadata_text_values(item))
        return result
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(metadata_text_values(item))
        return result
    return []


def _source_directory_task_terms(metadata: JsonObject) -> list[str]:
    values: list[str] = []
    for key in ("research_task_kind", "task_kind", "intent_kind", "source_family", "source_authority_requirement"):
        value = _metadata_string(metadata, key)
        if value:
            values.append(value)
    return query_terms_for_source_directory(" ".join(values), {})


def _base_score(*, query_terms: list[str], matched: list[str]) -> float:
    if not query_terms:
        return 0.0
    return len(matched) / max(1, len(query_terms))


def _matched_query_terms(query_terms: list[str], candidate_text: str) -> list[str]:
    candidate_terms = set(query_terms_for_source_directory(candidate_text, {}))
    matched: list[str] = []
    for term in query_terms:
        if term in candidate_terms:
            matched.append(term)
    return matched


def _metadata_string(metadata: JsonObject, key: str) -> str:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _metadata_string(nested, key)
    return ""


def _metadata_string_list(metadata: JsonObject, key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _metadata_string_list(nested, key)
    return []


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
