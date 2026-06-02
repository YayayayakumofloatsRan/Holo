from __future__ import annotations

import time
from collections.abc import Callable

from kernel_v3.contracts import JsonObject
from kernel_v3.retrieval.contracts import RetrievalProviderInspection
from kernel_v3.retrieval.operator import RetrievalOperator


def inspect_retrieval_providers(
    operator: RetrievalOperator,
    *,
    research_profile_id: str | None = None,
    clock_ms: Callable[[], int] | None = None,
) -> RetrievalProviderInspection:
    capabilities = operator.provider_capabilities()
    provider_chain = _provider_chain(capabilities)
    issues = _provider_issues(
        provider_chain,
        raw_capabilities=capabilities,
        network_access=operator.network_access,
        research_profile_id=research_profile_id,
    )
    return RetrievalProviderInspection(
        status=_inspection_status(issues),
        generated_at_ms=_now_ms(clock_ms),
        network_access=bool(operator.network_access),
        provider_capabilities=capabilities,
        issues=issues,
        recommended_actions=_recommended_actions(issues),
        diagnostics={
            "provider_count": len(capabilities),
            "provider_chain": provider_chain,
            "search_provider_ids": _provider_ids(provider_chain, provider_kind="search"),
            "fetch_provider_ids": _provider_ids(provider_chain, provider_kind="fetch"),
            **({"research_profile_id": research_profile_id} if research_profile_id else {}),
        },
    )


def _provider_issues(
    capabilities: list[JsonObject],
    *,
    raw_capabilities: list[JsonObject],
    network_access: bool,
    research_profile_id: str | None,
) -> list[JsonObject]:
    issues: list[JsonObject] = []
    if not _providers_by_kind(capabilities, "search"):
        issues.append({"severity": "error", "code": "missing_search_provider"})
    if not _providers_by_kind(capabilities, "fetch"):
        issues.append({"severity": "error", "code": "missing_fetch_provider"})
    issues.extend(_composite_provider_issues(raw_capabilities))
    issues.extend(_live_provider_configuration_issues(raw_capabilities))
    if network_access:
        issues.append({"severity": "attention", "code": "live_retrieval_provider_present"})
    for capability in capabilities:
        if not bool(capability.get("default_enabled", True)):
            issues.append(
                {
                    "severity": "attention",
                    "code": "retrieval_provider_disabled_by_default",
                    "provider_id": str(capability.get("provider_id") or ""),
                    "provider_kind": str(capability.get("provider_kind") or ""),
                }
            )
    if research_profile_id and not _has_profile_aware_search_provider(capabilities, research_profile_id):
        issues.append(
            {
                "severity": "info",
                "code": "research_profile_not_provider_native",
                "research_profile_id": research_profile_id,
            }
        )
    return issues


def _composite_provider_issues(capabilities: list[JsonObject]) -> list[JsonObject]:
    issues: list[JsonObject] = []
    for capability in _walk_capabilities(capabilities):
        provider_id = str(capability.get("provider_id") or "")
        provider_kind = str(capability.get("provider_kind") or "")
        diagnostics = capability.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        if provider_kind == "search" and provider_id == "fallback_search" and diagnostics.get("provider_count") == 0:
            issues.append(
                {
                    "severity": "error",
                    "code": "empty_fallback_search_chain",
                    "provider_id": provider_id,
                }
            )
        if (
            provider_kind == "search"
            and provider_id == "fallback_search"
            and int(diagnostics.get("provider_count") or 0) > 0
            and int(diagnostics.get("enabled_provider_count") or 0) == 0
        ):
            issues.append(
                {
                    "severity": "error",
                    "code": "no_enabled_fallback_search_provider",
                    "provider_id": provider_id,
                    "disabled_provider_ids": _string_list(diagnostics.get("disabled_provider_ids")),
                }
            )
    return issues


def _live_provider_configuration_issues(capabilities: list[JsonObject]) -> list[JsonObject]:
    issues: list[JsonObject] = []
    for capability in _walk_capabilities(capabilities):
        if _is_composite_capability(capability):
            continue
        if not bool(capability.get("live_network", False)):
            continue
        if not bool(capability.get("default_enabled", True)):
            continue
        diagnostics = capability.get("diagnostics")
        if not isinstance(diagnostics, dict):
            continue
        allow_all_hosts = bool(diagnostics.get("allow_all_hosts", False))
        allowed_host_count = int(diagnostics.get("allowed_host_count") or 0)
        allow_discovered_search_hosts = bool(diagnostics.get("allow_discovered_search_hosts", False))
        if allow_all_hosts or allowed_host_count > 0 or allow_discovered_search_hosts:
            continue
        issues.append(
            {
                "severity": "error",
                "code": "live_provider_without_allowed_hosts",
                "provider_id": str(capability.get("provider_id") or ""),
                "provider_kind": str(capability.get("provider_kind") or ""),
            }
        )
    return issues


def _is_composite_capability(capability: JsonObject) -> bool:
    diagnostics = capability.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return False
    return any(key in diagnostics for key in ("providers", "fallback", "route_providers"))


def _providers_by_kind(capabilities: list[JsonObject], provider_kind: str) -> list[JsonObject]:
    return [capability for capability in capabilities if capability.get("provider_kind") == provider_kind]


def _has_profile_aware_search_provider(capabilities: list[JsonObject], research_profile_id: str) -> bool:
    for capability in _providers_by_kind(capabilities, "search"):
        if not bool(capability.get("profile_aware", False)):
            continue
        supported = capability.get("supported_research_profiles")
        if isinstance(supported, list) and ("*" in supported or research_profile_id in supported):
            return True
    return False


def _inspection_status(issues: list[JsonObject]) -> str:
    severities = {str(issue.get("severity") or "attention") for issue in issues}
    if "error" in severities:
        return "error"
    if "warning" in severities:
        return "warning"
    if "attention" in severities:
        return "attention"
    return "ok"


def _recommended_actions(issues: list[JsonObject]) -> list[str]:
    actions: list[str] = []
    codes = {str(issue.get("code") or "") for issue in issues}
    if "missing_search_provider" in codes:
        actions.append("configure a retrieval search provider")
    if "missing_fetch_provider" in codes:
        actions.append("configure a retrieval fetch provider")
    if "live_retrieval_provider_present" in codes:
        actions.append("verify PolicyGate network permission before live retrieval runs")
    if "retrieval_provider_disabled_by_default" in codes:
        actions.append("explicitly enable retrieval providers before using them")
    if "empty_fallback_search_chain" in codes:
        actions.append("configure at least one concrete fallback search provider")
    if "no_enabled_fallback_search_provider" in codes:
        actions.append("enable at least one concrete fallback search provider")
    if "live_provider_without_allowed_hosts" in codes:
        actions.append("configure allowed hosts for live retrieval providers")
    if "research_profile_not_provider_native" in codes:
        actions.append("prefer a profile-aware corpus or retrieval provider for directed research")
    return _ordered_unique(actions)


def _provider_ids(capabilities: list[JsonObject], *, provider_kind: str) -> list[str]:
    ids: list[str] = []
    for capability in _providers_by_kind(capabilities, provider_kind):
        provider_id = capability.get("provider_id")
        if isinstance(provider_id, str) and provider_id:
            ids.append(provider_id)
    return ids


def _provider_chain(capabilities: list[JsonObject]) -> list[JsonObject]:
    flattened: list[JsonObject] = []
    seen: set[tuple[str, str]] = set()
    for capability in _walk_capabilities(capabilities):
        provider_id = capability.get("provider_id")
        provider_kind = capability.get("provider_kind")
        if not isinstance(provider_id, str) or not provider_id:
            continue
        if not isinstance(provider_kind, str) or not provider_kind:
            continue
        key = (provider_kind, provider_id)
        if key in seen:
            continue
        seen.add(key)
        flattened.append(
            {
                "provider_id": provider_id,
                "provider_kind": provider_kind,
                "live_network": bool(capability.get("live_network", False)),
                "default_enabled": bool(capability.get("default_enabled", True)),
                "profile_aware": bool(capability.get("profile_aware", False)),
                "supported_research_profiles": _string_list(capability.get("supported_research_profiles")),
            }
        )
    return flattened


def _walk_capabilities(value: object) -> list[JsonObject]:
    if isinstance(value, list):
        return [capability for item in value for capability in _walk_capabilities(item)]
    if not isinstance(value, dict):
        return []
    capabilities: list[JsonObject] = [dict(value)] if "provider_id" in value else []
    diagnostics = value.get("diagnostics")
    if isinstance(diagnostics, dict):
        capabilities.extend(_walk_capabilities(diagnostics.get("providers")))
        capabilities.extend(_walk_capabilities(diagnostics.get("fallback")))
        capabilities.extend(_walk_capabilities(diagnostics.get("route_providers")))
    return capabilities


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _now_ms(clock_ms: Callable[[], int] | None) -> int:
    if clock_ms is not None:
        return int(clock_ms())
    return time.monotonic_ns() // 1_000_000
