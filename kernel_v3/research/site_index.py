from __future__ import annotations

import hashlib
import urllib.parse

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research.sources import source_directory_for_profile
from kernel_v3.retrieval.source_directory_rank import rank_source_directory_entries


def site_index_list(
    *,
    profile_id: str,
    authority: str | None = None,
    family: str | None = None,
    source_id: str | None = None,
    limit: int = 100,
) -> JsonObject:
    entries = filter_site_index_entries(
        profile_id=profile_id,
        authority=authority,
        family=family,
        source_id=source_id,
    )
    limited = entries[: _positive_limit(limit, default=100)]
    return {
        "status": "ok",
        "profile": profile_id,
        "total": len(entries),
        "returned": len(limited),
        "facets": site_index_facets(entries),
        "sources": [site_index_entry_payload(entry) for entry in limited],
    }


def site_index_seeds(
    *,
    profile_id: str,
    authority: str | None = None,
    family: str | None = None,
    source_id: str | None = None,
    limit: int = 100,
) -> JsonObject:
    entries = filter_site_index_entries(
        profile_id=profile_id,
        authority=authority,
        family=family,
        source_id=source_id,
    )
    seeds = site_index_seed_payloads(entries)
    limited = seeds[: _positive_limit(limit, default=100)]
    return {
        "status": "ok",
        "profile": profile_id,
        "total": len(seeds),
        "returned": len(limited),
        "seeds": limited,
        "usage": {
            "purpose": "seed or refresh a local research corpus; seed URLs are source pointers, not evidence by themselves",
            "recommended_command": (
                "holo-v3 retrieve '<query or seed url>' --live-retrieval "
                "--profile finance_fundamentals --index-corpus"
            ),
        },
    }


def site_index_families(*, profile_id: str) -> JsonObject:
    entries = filter_site_index_entries(profile_id=profile_id)
    return {
        "status": "ok",
        "profile": profile_id,
        "facets": site_index_facets(entries),
    }


def site_index_plan(
    *,
    profile_id: str,
    query: str,
    authority: str | None = None,
    family: str | None = None,
    source_id: str | None = None,
    limit: int = 12,
) -> JsonObject:
    entries = filter_site_index_entries(
        profile_id=profile_id,
        authority=authority,
        family=family,
        source_id=source_id,
    )
    ranked = rank_source_directory_entries(entries, query=query, metadata={"research_profile": profile_id})
    planned: list[JsonObject] = []
    for ranked_entry in ranked[: _positive_limit(limit, default=12)]:
        entry = ranked_entry.entry
        payload = site_index_entry_payload(entry)
        payload["relevance_score"] = round(ranked_entry.score, 6)
        payload["matched_query_terms"] = list(ranked_entry.matched_terms)
        payload["seed_urls"] = seed_urls_for_site_index_entry(entry)[:5]
        planned.append(payload)
    return {
        "status": "ok",
        "profile": profile_id,
        "query_hash": _hash_for_site_index(query),
        "total_candidates": len(entries),
        "returned": len(planned),
        "strategy": {
            "primary": "use ranked trusted sites before generic web search",
            "fallback": "use live web search only when the site index cannot identify enough relevant entry points",
        },
        "sources": planned,
    }


def filter_site_index_entries(
    *,
    profile_id: str,
    authority: str | None = None,
    family: str | None = None,
    source_id: str | None = None,
) -> list[object]:
    entries = source_directory_for_profile(profile_id)
    if authority:
        entries = [entry for entry in entries if entry.authority_level == authority]
    if family:
        normalized_family = family.strip().lower()
        entries = [entry for entry in entries if entry.source_family.lower() == normalized_family]
    if source_id:
        normalized_source_id = source_id.strip().lower()
        entries = [entry for entry in entries if entry.source_id.lower() == normalized_source_id]
    return entries


def site_index_entry_payload(entry: object) -> JsonObject:
    return {
        "source_id": entry.source_id,
        "title": entry.title,
        "profile_id": entry.profile_id,
        "source_family": entry.source_family,
        "authority_level": entry.authority_level,
        "base_url": entry.base_url,
        "allowed_hosts": list(entry.allowed_hosts),
        "use_cases": list(entry.use_cases),
        "required_identifiers": list(entry.required_identifiers),
        "query_hints": list(entry.query_hints),
        "crawl_notes": list(entry.crawl_notes),
        "seed_url_count": len(seed_urls_for_site_index_entry(entry)),
    }


def site_index_facets(entries: list[object]) -> JsonObject:
    families: dict[str, int] = {}
    authorities: dict[str, int] = {}
    for entry in entries:
        families[entry.source_family] = families.get(entry.source_family, 0) + 1
        authorities[entry.authority_level] = authorities.get(entry.authority_level, 0) + 1
    return {
        "source_families": dict(sorted(families.items())),
        "authority_levels": dict(sorted(authorities.items())),
    }


def site_index_seed_payloads(entries: list[object]) -> list[JsonObject]:
    result: list[JsonObject] = []
    seen: set[str] = set()
    for entry in entries:
        for seed in seed_urls_for_site_index_entry(entry):
            if seed["url"] in seen:
                continue
            seen.add(str(seed["url"]))
            result.append(
                {
                    "source_id": entry.source_id,
                    "title": entry.title,
                    "source_family": entry.source_family,
                    "authority_level": entry.authority_level,
                    **seed,
                }
            )
    return result


def seed_urls_for_site_index_entry(entry: object) -> list[JsonObject]:
    seeds: list[JsonObject] = []
    if _safe_seed_url(entry.base_url):
        seeds.append({"seed_kind": "base_url", "url": entry.base_url})
    metadata = entry.metadata if isinstance(entry.metadata, dict) else {}
    crawl_seed_urls = metadata.get("crawl_seed_urls")
    if isinstance(crawl_seed_urls, list):
        for url in crawl_seed_urls:
            if isinstance(url, str) and _safe_seed_url(url):
                seeds.append({"seed_kind": "crawl_seed_url", "url": url})
    query_templates = metadata.get("query_url_templates")
    if isinstance(query_templates, list):
        for template in query_templates:
            if not isinstance(template, dict):
                continue
            raw = template.get("template")
            if isinstance(raw, str) and _template_is_static_seed(raw) and _safe_seed_url(raw):
                seeds.append(
                    {
                        "seed_kind": "static_query_template",
                        "template_id": str(template.get("template_id") or ""),
                        "url": raw,
                    }
                )
    return seeds


def _safe_seed_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return not contains_secret_like_content(parsed.geturl())


def _template_is_static_seed(template: str) -> bool:
    return "{" not in template and "}" not in template


def _positive_limit(value: int, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, parsed)


def _hash_for_site_index(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
