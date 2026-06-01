from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode

from kernel_v3.contracts import JsonObject
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


FRED_SERIES_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{1,63}$")


class FredSearchProvider:
    provider_id = "fred_structured_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = [FINANCE_FUNDAMENTALS_PROFILE_ID]

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "fred_structured_search",
            "network_access": "none",
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        profile_id = _research_profile_id(goal.metadata)
        if profile_id != FINANCE_FUNDAMENTALS_PROFILE_ID:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "not_finance_profile",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        series_id = _fred_series_id(goal.metadata)
        if series_id is None:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "missing_fred_series_id",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        if not _safe_series_id(series_id):
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "invalid_fred_series_id",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        sources = _series_sources(series_id=series_id, query=query, metadata=goal.metadata)
        sources = sources[: max(0, int(goal.max_sources))]
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "reason": "ok" if sources else "no_sources",
            "fred_series_id": series_id.upper(),
            "source_count": len(sources),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _series_sources(*, series_id: str, query: str, metadata: JsonObject) -> list[SearchSource]:
    normalized = series_id.upper()
    common = _common_metadata(series_id=normalized, metadata=metadata)
    series_url = f"https://fred.stlouisfed.org/series/{normalized}"
    csv_url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?{urlencode({'id': normalized})}"
    return [
        _source(
            uri=series_url,
            title=f"FRED series page for {normalized}",
            snippet=(
                "Official Federal Reserve Economic Data series page with source, units, "
                "release, frequency, and revision context."
            ),
            source_kind="fred_series_page",
            query=query,
            metadata=common,
            rank=1,
        ),
        _source(
            uri=csv_url,
            title=f"FRED CSV observations for {normalized}",
            snippet="Official FRED CSV download endpoint for bounded retrieval of macroeconomic observations.",
            source_kind="fred_observations_csv",
            query=query,
            metadata=common,
            rank=2,
        ),
    ]


def _source(
    *,
    uri: str,
    title: str,
    snippet: str,
    source_kind: str,
    query: str,
    metadata: JsonObject,
    rank: int,
) -> SearchSource:
    series_id = str(metadata["fred_series_id"])
    return SearchSource(
        source_id=f"{FredSearchProvider.provider_id}-{_hash(uri)[:12]}-{rank}",
        uri=uri,
        title=title,
        snippet=snippet,
        provider=FredSearchProvider.provider_id,
        metadata={
            "rank": rank,
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "government_statistic",
            "authority_level": "primary",
            "source_kind": source_kind,
            "fred_series_id": series_id,
            "source_directory_id": "finance-us-official-statistics",
            "source_directory_rank_text": f"FRED official macro data {series_id} {query}",
            **metadata,
        },
    )


def _common_metadata(*, series_id: str, metadata: JsonObject) -> JsonObject:
    flattened = _flatten_metadata(metadata)
    result: JsonObject = {
        "fred_series_id": series_id,
    }
    for key in ("observation_start", "observation_end", "units", "frequency", "aggregation_method"):
        value = flattened.get(key)
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    return result


def _fred_series_id(metadata: JsonObject) -> str | None:
    flattened = _flatten_metadata(metadata)
    for key in (
        "fred_series_id",
        "series_id",
        "fred_series",
        "economic_series_id",
        "macro_series_id",
    ):
        value = flattened.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


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


def _safe_series_id(value: str) -> bool:
    return bool(FRED_SERIES_ID_PATTERN.fullmatch(value.strip()))


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
