from __future__ import annotations

import os
import json
import re
from pathlib import Path
from typing import Any, Mapping

from .config import HostConfig


STAGE35_NAME = "stage35-internal-runtime-readiness"
REQUIRED_DEEPSEEK_LANES = ("kernel_xhigh", "subject_main", "micro_fast")

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("api_key_token", re.compile(r"\bsk-[A-Za-z0-9][A-Za-z0-9_-]{12,}\b")),
)


def scan_config_for_secret_material(config_path: str | Path | None) -> dict[str, Any]:
    path = Path(config_path).expanduser().resolve() if config_path else None
    if path is None:
        return {"ok": False, "exists": False, "path": "", "secret_like_tokens": [], "error": "missing_config_path"}
    if not path.exists():
        return {
            "ok": False,
            "exists": False,
            "path": str(path),
            "secret_like_tokens": [],
            "error": "config_path_not_found",
        }
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="replace")
    findings: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                findings.append({"line": line_number, "kind": kind})
                break
    return {
        "ok": not findings,
        "exists": True,
        "path": str(path),
        "secret_like_tokens": findings,
    }


def deepseek_env_readiness(config: HostConfig, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    env_name = str(config.processor_fabric.deepseek_api_key_env or "DEEPSEEK_API_KEY").strip() or "DEEPSEEK_API_KEY"
    value = str(env.get(env_name, "") or "")
    return {
        "ok": bool(value.strip()),
        "env_name": env_name,
        "present": bool(value.strip()),
        "value_redacted": "<set>" if value.strip() else "",
        "value_length": len(value) if value.strip() else 0,
    }


def deepseek_lane_readiness(config: HostConfig) -> dict[str, Any]:
    backends = dict(config.processor_fabric.provider_backends)
    lanes: dict[str, dict[str, Any]] = {}
    for lane_name in REQUIRED_DEEPSEEK_LANES:
        lane = backends.get(lane_name)
        lanes[lane_name] = {
            "present": lane is not None,
            "primary_provider": str(getattr(lane, "primary_provider", "") or ""),
            "backup_provider": str(getattr(lane, "backup_provider", "") or ""),
            "model": str(getattr(lane, "model", "") or ""),
            "reasoning_effort": str(getattr(lane, "reasoning_effort", "") or ""),
            "max_output_tokens": int(getattr(lane, "max_output_tokens", 0) or 0),
        }
    ok = all(
        bool(payload.get("present"))
        and str(payload.get("primary_provider", "")).strip().lower() == "deepseek"
        and str(payload.get("model", "")).strip().lower().startswith("deepseek-")
        for payload in lanes.values()
    )
    return {
        "ok": ok,
        "required_lanes": list(REQUIRED_DEEPSEEK_LANES),
        "lanes": lanes,
    }


def wechat_transport_quiescence(config: HostConfig) -> dict[str, Any]:
    runtime_dir = config.runtime.state_dir / "wechat-helper"
    send_queue = runtime_dir / "send_queue"
    queued_files = sorted(send_queue.glob("*.json")) if send_queue.exists() else []
    state_files = [runtime_dir / "transport_state.live.json", runtime_dir / "state.live.json"]
    state_payloads: list[dict[str, Any]] = []
    active_states: list[str] = []
    stopped_states = {"", "stopped", "stop", "offline", "inactive", "disabled", "idle", "not_running"}
    for state_file in state_files:
        if not state_file.exists():
            continue
        try:
            loaded = json.loads(state_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            loaded = {"status": "unreadable"}
        if not isinstance(loaded, dict):
            loaded = {"status": "invalid"}
        status = str(loaded.get("status", loaded.get("state", "")) or "").strip().lower()
        state_payloads.append({"path": str(state_file), "status": status or "unknown"})
        if status not in stopped_states:
            active_states.append(status or "unknown")
    ok = not queued_files and not active_states
    if not runtime_dir.exists():
        detail = "absent"
    elif active_states:
        detail = "active_or_unknown_state"
    elif queued_files:
        detail = "queued_sends_present"
    else:
        detail = "stopped_or_stale_runtime_dir"
    return {
        "ok": ok,
        "runtime_dir": str(runtime_dir),
        "runtime_dir_present": runtime_dir.exists(),
        "queued_send_count": len(queued_files),
        "state_files": state_payloads,
        "active_states": active_states,
        "detail": detail,
    }


def build_internal_runtime_readiness(config: HostConfig, provider_status: dict[str, Any]) -> dict[str, Any]:
    config_scan = scan_config_for_secret_material(config.config_path)
    env_status = deepseek_env_readiness(config)
    lane_status = deepseek_lane_readiness(config)
    transport_status = wechat_transport_quiescence(config)
    providers = dict(provider_status.get("providers", {}))
    deepseek_provider_visible = "deepseek" in providers
    checks = {
        "deepseek_primary_lanes": bool(lane_status.get("ok")),
        "deepseek_key_env_present": bool(env_status.get("ok")),
        "local_config_secret_free": bool(config_scan.get("ok")),
        "deepseek_provider_visible": deepseek_provider_visible,
        "wechat_transport_not_started_by_gate": bool(transport_status.get("ok")),
    }
    ok = all(checks.values())
    return {
        "ok": ok,
        "stage": STAGE35_NAME,
        "status": "pass" if ok else "fail",
        "checks": checks,
        "config_secret_scan": config_scan,
        "deepseek_env": env_status,
        "deepseek_lanes": lane_status,
        "transport_quiescence": transport_status,
        "provider_status": provider_status,
        "hard_boundaries": {
            "no_live_model_call": True,
            "no_wechat_transport_start": True,
            "no_self_memory_mutation": True,
            "no_new_unbounded_loop": True,
        },
    }
