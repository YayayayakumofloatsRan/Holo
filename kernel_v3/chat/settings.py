from __future__ import annotations

import json
from pathlib import Path

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.routing import DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO, DEEPSEEK_V4_TASK_TYPES, ProcessorRouter
from kernel_v3.storage import default_thread_root, safe_storage_id, state_root


MODEL_SETTING_PROFILES = {"speed", "balanced", "quality"}
MODEL_SETTING_TASKS = set(DEEPSEEK_V4_TASK_TYPES)
TASK_ALIASES = {
    "route": "chat.route",
    "chat": "chat.route",
    "chat.route": "chat.route",
    "intake": "semantic.intake",
    "semantic": "semantic.intake",
    "semantic.intake": "semantic.intake",
    "planner": "planner.propose",
    "plan": "planner.propose",
    "planner.propose": "planner.propose",
    "evaluator": "evaluator.assess",
    "eval": "evaluator.assess",
    "evaluator.assess": "evaluator.assess",
    "synthesizer": "synthesizer.answer",
    "synthesis": "synthesizer.answer",
    "answer": "synthesizer.answer",
    "synthesizer.answer": "synthesizer.answer",
}
MODEL_ALIASES = {
    "flash": DEEPSEEK_V4_FLASH,
    "deepseek-v4-flash": DEEPSEEK_V4_FLASH,
    "pro": DEEPSEEK_V4_PRO,
    "quality": DEEPSEEK_V4_PRO,
    "deepseek-v4-pro": DEEPSEEK_V4_PRO,
}


class ModelSettingsStore:
    def __init__(self, *, global_path: Path | str | None = None, thread_root: Path | str | None = None) -> None:
        self.global_path = Path(global_path) if global_path is not None else state_root() / "settings" / "model.json"
        self.thread_root = Path(thread_root) if thread_root is not None else default_thread_root()

    def global_settings(self) -> JsonObject:
        return _normalized_config(_read_json(self.global_path))

    def thread_settings(self, thread_id: str) -> JsonObject:
        return _normalized_config(_read_json(self.thread_path(thread_id)))

    def effective_settings(self, thread_id: str) -> JsonObject:
        settings = profile_model_settings("balanced")
        settings = merge_model_settings(settings, self.global_settings())
        settings = merge_model_settings(settings, self.thread_settings(thread_id))
        return settings

    def configured_settings(self, thread_id: str) -> JsonObject:
        settings: JsonObject = {"schema_version": 1, "profile": None, "routes": {}}
        settings = merge_model_settings(settings, self.global_settings())
        settings = merge_model_settings(settings, self.thread_settings(thread_id))
        return settings

    def update_global(self, settings: JsonObject) -> JsonObject:
        payload = merge_model_settings(self.global_settings(), settings)
        _write_json(self.global_path, payload)
        return payload

    def update_thread(self, thread_id: str, settings: JsonObject) -> JsonObject:
        payload = merge_model_settings(self.thread_settings(thread_id), settings)
        _write_json(self.thread_path(thread_id), payload)
        return payload

    def reset_global(self) -> JsonObject:
        if self.global_path.exists():
            self.global_path.unlink()
        return self.global_settings()

    def reset_thread(self, thread_id: str) -> JsonObject:
        path = self.thread_path(thread_id)
        if path.exists():
            path.unlink()
        return self.thread_settings(thread_id)

    def thread_path(self, thread_id: str) -> Path:
        return self.thread_root / safe_storage_id(thread_id) / "settings.json"


def profile_model_settings(profile: str, *, locked: bool = False) -> JsonObject:
    normalized = profile if profile in MODEL_SETTING_PROFILES else "balanced"
    if normalized == "speed":
        route = _route(model=DEEPSEEK_V4_FLASH, thinking="disabled", effort="low", latency="fast", locked=locked)
    elif normalized == "quality":
        route = _route(model=DEEPSEEK_V4_PRO, thinking="enabled", effort="high", latency="quality", locked=locked)
    else:
        route = _route(model=DEEPSEEK_V4_FLASH, thinking="disabled", effort="medium", latency="balanced", locked=locked)
    routes = {task_type: dict(route) for task_type in DEEPSEEK_V4_TASK_TYPES}
    routes["chat.route"] = _route(
        model=DEEPSEEK_V4_FLASH,
        thinking="disabled",
        effort="low",
        latency=route["latency_target"],
        locked=locked,
    )
    return {"schema_version": 1, "profile": normalized, "routes": routes}


def merge_model_settings(base: JsonObject, override: JsonObject | None) -> JsonObject:
    result = _normalized_config(base)
    incoming = _normalized_config(override or {})
    if incoming.get("profile"):
        result["profile"] = incoming["profile"]
    routes = dict(result.get("routes") or {})
    for task_type, route in dict(incoming.get("routes") or {}).items():
        current = dict(routes.get(task_type) or {})
        current.update(dict(route))
        routes[task_type] = _normalized_route(current, task_type=task_type)
    result["routes"] = routes
    return result


def apply_model_settings_to_router(router: ProcessorRouter, settings: JsonObject) -> None:
    routes = settings.get("routes")
    if not isinstance(routes, dict):
        return
    for task_type in DEEPSEEK_V4_TASK_TYPES:
        route = routes.get(task_type)
        if not isinstance(route, dict):
            continue
        router.set_route(
            task_type,
            model=str(route.get("model") or DEEPSEEK_V4_FLASH),
            thinking=str(route.get("thinking") or "disabled"),
            reasoning_effort=str(route.get("reasoning_effort") or "medium"),
            temperature=route.get("temperature") if isinstance(route.get("temperature"), float) else None,
            latency_target=str(route.get("latency_target") or "balanced"),
            timeout_seconds=int(route.get("timeout_seconds") or 60),
            model_locked=bool(route.get("model_locked")),
            thinking_locked=bool(route.get("thinking_locked")),
            temperature_locked=bool(route.get("temperature_locked")),
        )


def normalize_task_type(value: str) -> str | None:
    return TASK_ALIASES.get(str(value or "").strip().lower())


def normalize_model(value: str) -> str | None:
    return MODEL_ALIASES.get(str(value or "").strip().lower())


def normalize_thinking(value: str) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"on", "true", "1", "yes", "enabled", "enable"}:
        return "enabled"
    if normalized in {"off", "false", "0", "no", "disabled", "disable"}:
        return "disabled"
    return None


def setting_update_for_profile(profile: str) -> JsonObject | None:
    if profile not in MODEL_SETTING_PROFILES:
        return None
    return profile_model_settings(profile, locked=True)


def setting_update_for_stage(task_type: str, values: JsonObject) -> JsonObject:
    route = dict(values)
    route["model_locked"] = True
    route["thinking_locked"] = True
    if "temperature" in route:
        route["temperature_locked"] = True
    return {"schema_version": 1, "profile": "custom", "routes": {task_type: _normalized_route(route, task_type=task_type)}}


def settings_for_display(settings: JsonObject) -> list[str]:
    routes = settings.get("routes") if isinstance(settings.get("routes"), dict) else {}
    lines = [f"profile={settings.get('profile') or 'custom'}"]
    for task_type in DEEPSEEK_V4_TASK_TYPES:
        route = routes.get(task_type) if isinstance(routes, dict) else None
        route = route if isinstance(route, dict) else {}
        lines.append(
            f"{task_type}: model={route.get('model', DEEPSEEK_V4_FLASH)} "
            f"thinking={route.get('thinking', 'disabled')} "
            f"effort={route.get('reasoning_effort', 'medium')} "
            f"target={route.get('latency_target', 'balanced')} "
            f"temp={route.get('temperature', '-')} "
            f"locked={_lock_display(route)}"
        )
    return lines


def _lock_display(route: JsonObject) -> str:
    locks = []
    if route.get("model_locked"):
        locks.append("model")
    if route.get("thinking_locked"):
        locks.append("thinking")
    if route.get("temperature_locked"):
        locks.append("temp")
    return ",".join(locks) if locks else "auto"


def _route(*, model: str, thinking: str, effort: str, latency: str, locked: bool) -> JsonObject:
    return {
        "model": model,
        "thinking": thinking,
        "reasoning_effort": effort,
        "latency_target": latency,
        "temperature": 0.0,
        "timeout_seconds": 60 if thinking == "disabled" else 120,
        "model_locked": locked,
        "thinking_locked": locked,
        "temperature_locked": locked,
    }


def _normalized_config(value: JsonObject | None) -> JsonObject:
    data = value if isinstance(value, dict) else {}
    profile = data.get("profile") if data.get("profile") in MODEL_SETTING_PROFILES or data.get("profile") == "custom" else None
    routes: JsonObject = {}
    raw_routes = data.get("routes") if isinstance(data.get("routes"), dict) else {}
    for task_type in DEEPSEEK_V4_TASK_TYPES:
        raw = raw_routes.get(task_type) if isinstance(raw_routes, dict) else None
        if isinstance(raw, dict):
            routes[task_type] = _normalized_route(raw, task_type=task_type)
    return {"schema_version": 1, "profile": profile, "routes": routes}


def _normalized_route(value: JsonObject, *, task_type: str) -> JsonObject:
    model = str(value.get("model") or DEEPSEEK_V4_FLASH)
    if model not in {DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO}:
        model = DEEPSEEK_V4_FLASH
    thinking = str(value.get("thinking") or "disabled")
    if thinking not in {"enabled", "disabled"}:
        thinking = "disabled"
    if task_type == "chat.route":
        model = DEEPSEEK_V4_FLASH
        thinking = "disabled"
    effort = str(value.get("reasoning_effort") or "medium")
    if effort not in {"low", "medium", "high", "max"}:
        effort = "medium"
    latency = str(value.get("latency_target") or "balanced")
    if latency not in {"fast", "balanced", "quality", "thorough"}:
        latency = "balanced"
    timeout = _positive_int(value.get("timeout_seconds"), default=60 if thinking == "disabled" else 120)
    route: JsonObject = {
        "model": model,
        "thinking": thinking,
        "reasoning_effort": effort,
        "latency_target": latency,
        "timeout_seconds": timeout,
        "model_locked": bool(value.get("model_locked")),
        "thinking_locked": bool(value.get("thinking_locked")),
        "temperature_locked": bool(value.get("temperature_locked")),
    }
    temperature = _float_or_none(value.get("temperature"))
    if temperature is not None:
        route["temperature"] = temperature
    return route


def _read_json(path: Path) -> JsonObject:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: JsonObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
