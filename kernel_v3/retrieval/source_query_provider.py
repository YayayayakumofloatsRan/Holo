from __future__ import annotations

import hashlib
import string
import urllib.parse

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research import identity_template_values, resolve_issuer_identity, source_directory_for_profile
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


class ResearchSourceQuerySearchProvider:
    provider_id = "research_source_query_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = ["*"]

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "research_source_query_search",
            "network_access": "none",
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        profile_id = _research_profile_id(goal.metadata)
        if profile_id is None:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "no_research_profile",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []

        values = _template_values(query, goal.metadata)
        sources: list[SearchSource] = []
        skipped = 0
        for entry in source_directory_for_profile(profile_id):
            templates = _query_templates(entry.metadata)
            for template in templates:
                if len(sources) >= max(0, int(goal.max_sources)):
                    break
                rendered = _render_source(entry=entry, template=template, values=values)
                if rendered is None:
                    skipped += 1
                    continue
                if rendered.uri in {item.uri for item in sources}:
                    continue
                sources.append(rendered)

        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "research_profile": profile_id,
            "source_count": len(sources),
            "skipped_template_count": skipped,
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _render_source(*, entry: object, template: JsonObject, values: dict[str, str]) -> SearchSource | None:
    if not _template_matches(template, values):
        return None
    raw_template = template.get("template")
    if not isinstance(raw_template, str) or not raw_template.strip():
        return None
    uri = _render(raw_template, values)
    if uri is None or not _safe_url(uri):
        return None
    allowed_hosts = list(getattr(entry, "allowed_hosts", []))
    host = urllib.parse.urlparse(uri).hostname or ""
    if not _host_allowed(host.lower(), allowed_hosts):
        return None
    title = _render(str(template.get("title") or getattr(entry, "title", "research source")), values)
    snippet = _render(str(template.get("snippet") or "; ".join(getattr(entry, "query_hints", [])[:3])), values)
    source_kind = str(template.get("source_kind") or "source_directory_query")
    template_id = str(template.get("template_id") or _hash(raw_template)[:12])
    source_id = f"{ResearchSourceQuerySearchProvider.provider_id}-{_hash(uri)[:12]}"
    return SearchSource(
        source_id=source_id,
        uri=uri,
        title=_bounded(title or getattr(entry, "title", "research source"), 240),
        snippet=_bounded(snippet or getattr(entry, "title", "research source"), 800),
        provider=ResearchSourceQuerySearchProvider.provider_id,
        metadata={
            "research_profile": getattr(entry, "profile_id"),
            "source_directory_id": getattr(entry, "source_id"),
            "source_family": getattr(entry, "source_family"),
            "authority_level": getattr(entry, "authority_level"),
            "allowed_hosts": allowed_hosts,
            "source_kind": source_kind,
            "template_id": template_id,
        },
    )


def _query_templates(metadata: JsonObject) -> list[JsonObject]:
    raw = metadata.get("query_url_templates")
    if not isinstance(raw, list):
        return []
    templates: list[JsonObject] = []
    for item in raw:
        if isinstance(item, str):
            templates.append({"template": item})
        elif isinstance(item, dict):
            templates.append(dict(item))
    return templates


def _template_matches(template: JsonObject, values: dict[str, str]) -> bool:
    required = template.get("required_values")
    if isinstance(required, list):
        for key in required:
            if not isinstance(key, str) or not values.get(key):
                return False
    match_any = template.get("match_any")
    if isinstance(match_any, list) and match_any:
        haystack = " ".join(values.values()).lower()
        return any(isinstance(item, str) and item.lower() in haystack for item in match_any)
    return True


def _render(template: str, values: dict[str, str]) -> str | None:
    fields = [field for _, field, _, _ in string.Formatter().parse(template) if field]
    if any(field not in values or values[field] == "" for field in fields):
        return None
    try:
        return template.format(**values)
    except (KeyError, ValueError):
        return None


def _template_values(query: str, metadata: JsonObject) -> dict[str, str]:
    raw: dict[str, str] = {"query": _compact(query)}
    raw.update(identity_template_values(resolve_issuer_identity(query, metadata)))
    for key, value in _flatten_metadata(metadata).items():
        if isinstance(value, str) and value.strip():
            raw[key] = _compact(value)
    raw["company_or_query"] = raw.get("company") or raw.get("issuer") or raw["query"]
    raw["ticker_or_query"] = raw.get("ticker") or raw.get("sec_ticker") or raw["query"]
    raw["stock_code_or_ticker"] = raw.get("stock_code") or raw.get("asx_code") or raw.get("ticker") or raw["query"]
    raw["metric_or_query"] = raw.get("metric") or raw.get("indicator") or raw["query"]

    values: dict[str, str] = {}
    for key, value in raw.items():
        if not value:
            continue
        values[key] = value
        values[f"{key}_url"] = urllib.parse.quote(value, safe="")
        lowered = value.lower()
        values[f"{key}_lower"] = lowered
        values[f"{key}_lower_url"] = urllib.parse.quote(lowered, safe="")
    return values


def _flatten_metadata(metadata: JsonObject) -> JsonObject:
    result: JsonObject = {}
    for key, value in metadata.items():
        if key == "metadata" and isinstance(value, dict):
            result.update(_flatten_metadata(value))
        else:
            result[key] = value
    return result


def _research_profile_id(metadata: JsonObject) -> str | None:
    for key in ("research_profile_id", "research_profile"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return value
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _research_profile_id(nested)
    return None


def _safe_url(uri: str) -> bool:
    parsed = urllib.parse.urlparse(uri)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if not parsed.hostname or parsed.username or parsed.password:
        return False
    return not contains_secret_like_content(parsed.geturl())


def _host_allowed(host: str, allowed_hosts: list[str]) -> bool:
    normalized = [_normalize_host(item) for item in allowed_hosts]
    return any(_host_matches(host, allowed) for allowed in normalized if allowed)


def _host_matches(host: str, allowed: str) -> bool:
    if "*" in allowed:
        prefix, _, suffix = allowed.partition("*")
        return host.startswith(prefix) and host.endswith(suffix)
    return host == allowed or host.endswith(f".{allowed}")


def _normalize_host(value: str) -> str:
    parsed = urllib.parse.urlparse(value if "://" in value else f"//{value}")
    return (parsed.hostname or value).lower().rstrip(".")


def _compact(value: object) -> str:
    return " ".join(str(value or "").split())


def _bounded(text: str, limit: int) -> str:
    normalized = _compact(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
