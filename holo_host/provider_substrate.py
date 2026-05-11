from __future__ import annotations

from typing import Any


MODEL_PROVIDER_PREFIXES: dict[str, tuple[str, ...]] = {
    "codex_cli": ("gpt-", "o", "chatgpt-"),
    "responses": ("gpt-", "o", "chatgpt-"),
    "deepseek": ("deepseek-",),
}

SYNTHETIC_PROVIDERS = {"", "stage46_scripted", "scripted", "offline"}


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _provider_unavailable(provider_status: dict[str, Any], provider_name: str) -> tuple[bool, str]:
    providers = _as_dict(provider_status.get("providers"))
    provider = _as_dict(providers.get(provider_name))
    if not provider:
        return False, ""
    available = bool(provider.get("available", True))
    reason = str(provider.get("reason", "") or provider.get("availability_reason", "") or "")
    return not available, reason


def _turn_processor_debug(turn: dict[str, Any]) -> dict[str, Any]:
    debug = _as_dict(turn.get("processor_debug"))
    if debug:
        return debug
    return {
        "provider": turn.get("provider", ""),
        "model": turn.get("model", ""),
        "lane": turn.get("lane", ""),
        "fallback_provider": turn.get("fallback_provider", ""),
        "provider_failures": turn.get("provider_failures", []),
    }


def _model_matches_provider(provider_name: str, model: str) -> bool:
    provider = str(provider_name or "").strip()
    current = str(model or "").strip().lower()
    if not provider or not current:
        return True
    prefixes = MODEL_PROVIDER_PREFIXES.get(provider)
    if not prefixes:
        return True
    return current.startswith(prefixes)


def _add_conflict(
    conflicts: list[dict[str, Any]],
    flags: dict[str, bool],
    code: str,
    *,
    severity: str,
    detail: str,
    provider: str = "",
    lane: str = "",
    model: str = "",
) -> None:
    flags[code] = True
    conflicts.append(
        {
            "code": code,
            "severity": severity,
            "provider": provider,
            "lane": lane,
            "model": model,
            "detail": detail,
        }
    )


def analyze_provider_substrate_conflicts(
    provider_status: dict[str, Any] | None,
    *,
    turns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    status = _as_dict(provider_status)
    rows = [dict(turn) for turn in (turns or []) if isinstance(turn, dict)]
    declared_backend = str(status.get("active_backend_alias", "") or "").strip()
    providers = _as_dict(status.get("providers"))
    lanes = _as_dict(status.get("lanes"))
    flags = {
        "active_provider_unavailable": False,
        "configured_primary_unavailable": False,
        "fallback_provider_in_effect": False,
        "provider_model_mismatch": False,
    }
    conflicts: list[dict[str, Any]] = []

    if declared_backend and declared_backend not in {"auto", "codex_cli"}:
        unavailable, reason = _provider_unavailable(status, declared_backend)
        if unavailable:
            _add_conflict(
                conflicts,
                flags,
                "active_provider_unavailable",
                severity="fail",
                provider=declared_backend,
                detail=reason or f"{declared_backend} unavailable",
            )

    for lane_name, lane_payload in lanes.items():
        lane = _as_dict(lane_payload)
        primary = str(lane.get("primary_provider", "") or "").strip()
        if primary:
            unavailable, reason = _provider_unavailable(status, primary)
            if unavailable:
                _add_conflict(
                    conflicts,
                    flags,
                    "configured_primary_unavailable",
                    severity="fail",
                    provider=primary,
                    lane=str(lane_name),
                    model=str(lane.get("model", "") or ""),
                    detail=reason or f"{primary} unavailable for lane {lane_name}",
                )

    actual_providers: list[str] = []
    provider_failures: list[dict[str, Any]] = []
    for turn in rows:
        debug = _turn_processor_debug(turn)
        provider = str(debug.get("provider", "") or "").strip()
        model = str(debug.get("model", "") or "").strip()
        lane = str(debug.get("lane", "") or "").strip()
        fallback_provider = str(debug.get("fallback_provider", "") or "").strip()
        if provider and provider not in actual_providers:
            actual_providers.append(provider)
        failures = [dict(item) for item in _as_list(debug.get("provider_failures")) if isinstance(item, dict)]
        provider_failures.extend(failures)
        if provider not in SYNTHETIC_PROVIDERS and fallback_provider:
            _add_conflict(
                conflicts,
                flags,
                "fallback_provider_in_effect",
                severity="warn",
                provider=provider,
                lane=lane,
                model=model,
                detail=f"task fell back to {fallback_provider}",
            )
        elif failures:
            _add_conflict(
                conflicts,
                flags,
                "fallback_provider_in_effect",
                severity="warn",
                provider=provider,
                lane=lane,
                model=model,
                detail="provider failures were recorded before final generation",
            )
        if provider not in SYNTHETIC_PROVIDERS and not _model_matches_provider(provider, model):
            _add_conflict(
                conflicts,
                flags,
                "provider_model_mismatch",
                severity="fail",
                provider=provider,
                lane=lane,
                model=model,
                detail=f"{provider} received model {model}",
            )

    seen: set[tuple[str, str, str, str]] = set()
    unique_conflicts: list[dict[str, Any]] = []
    for conflict in conflicts:
        key = (
            str(conflict.get("code", "")),
            str(conflict.get("provider", "")),
            str(conflict.get("lane", "")),
            str(conflict.get("model", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_conflicts.append(conflict)

    severity_penalty = sum(0.35 if row.get("severity") == "fail" else 0.15 for row in unique_conflicts)
    score = round(max(0.0, 1.0 - min(1.0, severity_penalty)), 4)
    return {
        "ok": len(unique_conflicts) == 0,
        "score": score,
        "declared_backend": declared_backend,
        "actual_providers": actual_providers,
        "provider_failures": provider_failures,
        "flags": flags,
        "conflicts": unique_conflicts,
    }
