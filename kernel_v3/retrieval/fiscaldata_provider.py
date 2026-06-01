from __future__ import annotations

import hashlib
import re
from urllib.parse import urlencode

from kernel_v3.contracts import JsonObject
from kernel_v3.privacy import contains_secret_like_content
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource


FISCALDATA_API_HOST = "api.fiscaldata.treasury.gov"
FISCALDATA_API_PREFIX = "/services/api/fiscal_service/"
FISCALDATA_PATH_PATTERN = re.compile(r"^/services/api/fiscal_service/[A-Za-z0-9_./-]{3,240}$")
FISCALDATA_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
FISCALDATA_SORT_PATTERN = re.compile(r"^-?[A-Za-z_][A-Za-z0-9_]{0,63}$")
FISCALDATA_FILTER_PATTERN = re.compile(r"^[A-Za-z0-9_:.<>=,-]{1,500}$")


class FiscalDataSearchProvider:
    provider_id = "fiscaldata_structured_search"
    live_network = False
    default_enabled = True
    profile_aware = True
    supported_research_profiles = [FINANCE_FUNDAMENTALS_PROFILE_ID]

    def __init__(self) -> None:
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "fiscaldata_structured_search",
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
        endpoint_path = _fiscaldata_api_path(goal.metadata)
        if endpoint_path is None:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "missing_fiscaldata_api_path",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        if not _safe_api_path(endpoint_path):
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "invalid_fiscaldata_api_path",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        params = _query_params(goal.metadata)
        if params is None:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "invalid_fiscaldata_query_params",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        source = _source(endpoint_path=endpoint_path, query=query, metadata=goal.metadata, params=params)
        self._last_search_diagnostics = {
            "status": "ok",
            "reason": "ok",
            "fiscaldata_api_path": endpoint_path,
            "source_count": 1,
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return [source][: max(0, int(goal.max_sources))]

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _source(*, endpoint_path: str, query: str, metadata: JsonObject, params: list[tuple[str, str]]) -> SearchSource:
    query_string = urlencode(params)
    uri = f"https://{FISCALDATA_API_HOST}{endpoint_path}?{query_string}"
    return SearchSource(
        source_id=f"{FiscalDataSearchProvider.provider_id}-{_hash(uri)[:12]}",
        uri=uri,
        title=f"FiscalData API endpoint {endpoint_path.rsplit('/', 1)[-1]}",
        snippet=(
            "Official US Treasury FiscalData API endpoint for fiscal, debt, "
            "auction, or Treasury-rate data."
        ),
        provider=FiscalDataSearchProvider.provider_id,
        metadata={
            "rank": 1,
            "research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID,
            "source_family": "treasury_data",
            "authority_level": "primary",
            "source_kind": "fiscaldata_api_endpoint",
            "source_directory_id": "finance-us-treasury-rates-and-fiscal-data",
            "fiscaldata_api_path": endpoint_path,
            "source_directory_rank_text": f"US Treasury FiscalData official API {endpoint_path} {query}",
            **_safe_metadata(metadata),
        },
    )


def _query_params(metadata: JsonObject) -> list[tuple[str, str]] | None:
    flattened = _flatten_metadata(metadata)
    params: list[tuple[str, str]] = []
    fields = _fields(flattened)
    if fields:
        params.append(("fields", ",".join(fields)))
    filters = _filters(flattened)
    if filters is None:
        return None
    if filters:
        params.append(("filter", ",".join(filters)))
    sort = _sort(flattened)
    if sort is None:
        return None
    if sort:
        params.append(("sort", ",".join(sort)))
    page_size = _page_size(flattened)
    params.append(("page[size]", str(page_size)))
    params.append(("format", "json"))
    return params


def _fields(metadata: JsonObject) -> list[str]:
    values = _metadata_strings(metadata, "fiscaldata_fields", "fields")
    return [value for value in values if FISCALDATA_FIELD_PATTERN.fullmatch(value)]


def _filters(metadata: JsonObject) -> list[str] | None:
    values = _metadata_strings(metadata, "fiscaldata_filter", "fiscaldata_filters", "filter", "filters")
    if not values:
        return []
    valid = []
    for value in values:
        if contains_secret_like_content(value) or not FISCALDATA_FILTER_PATTERN.fullmatch(value):
            return None
        valid.append(value)
    return valid


def _sort(metadata: JsonObject) -> list[str] | None:
    values = _metadata_strings(metadata, "fiscaldata_sort", "sort")
    if not values:
        return []
    valid = []
    for value in values:
        if not FISCALDATA_SORT_PATTERN.fullmatch(value):
            return None
        valid.append(value)
    return valid


def _page_size(metadata: JsonObject) -> int:
    raw = metadata.get("page_size", metadata.get("fiscaldata_page_size"))
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        return 100
    return max(1, min(value, 1000))


def _metadata_strings(metadata: JsonObject, *keys: str) -> list[str]:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return _split_csv(value)
        if isinstance(value, list):
            return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
    return []


def _fiscaldata_api_path(metadata: JsonObject) -> str | None:
    flattened = _flatten_metadata(metadata)
    for key in (
        "fiscaldata_api_path",
        "fiscaldata_endpoint_path",
        "fiscaldata_endpoint",
        "treasury_api_path",
    ):
        value = flattened.get(key)
        if isinstance(value, str) and value.strip():
            return _normalize_api_path(value)
    return None


def _normalize_api_path(value: str) -> str:
    text = value.strip()
    if text.startswith("https://api.fiscaldata.treasury.gov/"):
        text = text.removeprefix("https://api.fiscaldata.treasury.gov")
    if not text.startswith("/"):
        text = "/" + text
    return text


def _safe_api_path(value: str) -> bool:
    return (
        value.startswith(FISCALDATA_API_PREFIX)
        and bool(FISCALDATA_PATH_PATTERN.fullmatch(value))
        and ".." not in value
        and not contains_secret_like_content(value)
    )


def _safe_metadata(metadata: JsonObject) -> JsonObject:
    flattened = _flatten_metadata(metadata)
    result: JsonObject = {}
    for key in (
        "fiscaldata_api_path",
        "fiscaldata_endpoint_path",
        "fiscaldata_endpoint",
        "treasury_api_path",
        "fiscaldata_fields",
        "fields",
        "fiscaldata_filter",
        "filter",
        "fiscaldata_sort",
        "sort",
        "page_size",
        "fiscaldata_page_size",
        "research_task_kind",
        "preferred_source_families",
        "source_authority_requirement",
        "search_strategy",
    ):
        value = flattened.get(key)
        if value is None or contains_secret_like_content(value):
            continue
        result[key] = value
    return result


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


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in value.split(",") if part.strip()]


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()
