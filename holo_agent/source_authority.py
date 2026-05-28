from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlparse


def classify_source_url(url: str) -> dict[str, Any]:
    parsed = urlparse(str(url or ""))
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    authority = "secondary"
    primary = False
    reason = "unrecognized secondary or tertiary source"

    if host.endswith("sec.gov") or "edgar" in path:
        authority = "regulatory_filing"
        primary = True
        reason = "SEC or regulator filing/source"
    elif host.startswith("investor.") or "/investor" in path or "investor-relations" in path or host.startswith("ir."):
        authority = "company_official"
        primary = True
        reason = "company investor-relations source"
    elif host.endswith("developers.openai.com") or host.endswith("openai.com") or host.endswith("api-docs.deepseek.com") or host.endswith("deepseek.com"):
        authority = "official"
        primary = True
        reason = "official organization domain"
    elif host.endswith("github.com"):
        parts = [item for item in path.split("/") if item]
        if parts and parts[0] in {"openai", "anthropics", "anthropic-ai", "nousresearch"}:
            authority = "official_repository"
            primary = True
            reason = "official repository namespace"
        else:
            authority = "repository"
            reason = "repository source"

    return {"url": url, "host": host, "authority": authority, "primary": primary, "reason": reason}


def _iter_observation_urls(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for obs in observations:
        if obs.get("status") != "ok":
            continue
        tool = obs.get("tool")
        data = obs.get("data", {}) if isinstance(obs.get("data"), dict) else {}
        if tool == "web_search":
            for result in data.get("results", []) if isinstance(data.get("results"), list) else []:
                url = str(result.get("url", "") or "")
                if url and url not in seen:
                    seen.add(url)
                    rows.append({"url": url, "opened": False, "title": result.get("title", "")})
        elif tool == "open_page":
            url = str(data.get("url", "") or "")
            if not url:
                continue
            if url in seen:
                for row in rows:
                    if row["url"] == url:
                        row["opened"] = True
                        break
            else:
                seen.add(url)
                rows.append({"url": url, "opened": True, "title": ""})
    return rows


def build_source_authority_report(observations: list[dict[str, Any]]) -> dict[str, Any]:
    sources = []
    for row in _iter_observation_urls(observations):
        classified = classify_source_url(row["url"])
        sources.append({**row, **classified})

    counts = Counter(source["authority"] for source in sources)
    primary_count = sum(1 for source in sources if source["primary"])
    opened_primary_count = sum(1 for source in sources if source["primary"] and source["opened"])
    return {
        "schema": "holo.source_authority.v1",
        "status": "ok" if primary_count else "weak_sources",
        "source_count": len(sources),
        "primary_source_count": primary_count,
        "opened_primary_source_count": opened_primary_count,
        "authority_counts": dict(counts),
        "sources": sources,
    }
