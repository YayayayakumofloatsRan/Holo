from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .cli_parts import bionic as bionic_cli
from .cli_parts import boundary_stress as boundary_stress_cli
from .cli_parts import brain as brain_cli
from .cli_parts import engineering as engineering_cli
from .cli_parts import motivational as motivational_cli
from .cli_parts import user_sim as user_sim_cli
from .config import load_config
from .daemon import build_daemon
from .models import ProcessorTaskRequest
from .reply_api import HoloReplyService, run_reply_api
from .store import QueueStore

FAST_QUERY_CANDIDATES = ("在吗", "继续", "嗯")
RECALL_QUERY_CANDIDATES = ("接着刚才那条线往下说", "顺着刚才那条线继续", "继续刚才那条线")
DEEP_QUERY_CANDIDATES = ("你还记得重新上线前吗", "你还记得我们之前说过什么吗")
ORIGIN_QUERY_CANDIDATES = ("最开始的时候，你还记得什么", "一开始的时候你还记得什么", "最初那会儿你还记得什么")
_ORIGIN_LOW_SIGNAL_TEXTS = {"", "?", "??", "???", "在吗", "你在吗", "嗨", "喂", "好", "ok", "okk"}


STAGE2_PLAYFUL_QUERY = "\u4f60\u522b\u603b\u90a3\u4e48\u8001\u6210\uff0c\u8ddf\u5481\u6253\u8da3\u4e00\u70b9"
STAGE2_SERIOUS_QUERY = "\u6211\u8fd9\u4f1a\u513f\u538b\u529b\u633a\u5927\uff0c\u4f46\u4e0d\u8981\u50cf\u957f\u8f88\u8bf4\u6559"
STAGE2_APPETITE_QUERY = "\u82f9\u679c\u3001\u9152\u548c\u5403\u7684\uff0c\u4f60\u60f3\u8d77\u4ec0\u4e48"
STAGE2_CORRECTION_QUERY = "\u522b\u592a\u8001\u6210\uff0c\u4e5f\u4e0d\u8981\u4e00\u76f4\u987a\u7740\u6211\u8bf4"
STAGE2_CORRECTIONS = [
    "\u522b\u603b\u8fd9\u4e48\u8001\u6210",
    "\u4e0d\u8981\u4e00\u76f4\u987a\u7740\u6211\u8bf4",
    "\u8981\u6709\u72ec\u7acb\u6027/\u53cd\u8eab\u6027",
]


def _live_api_request(
    config_path: str | None,
    *,
    method: str,
    path: str,
    params: dict[str, object] | None = None,
    payload: dict[str, object] | None = None,
    timeout: float = 5.0,
) -> dict | None:
    config = load_config(config_path=config_path)
    query = urlencode({key: value for key, value in (params or {}).items() if value is not None and value != ""})
    base_urls = [f"http://{config.runtime.api_bind_host}:{config.runtime.api_port}"]
    if os.name == "nt" and str(config.runtime.api_bind_host).strip() in {"127.0.0.1", "localhost"}:
        distro = str(os.environ.get("HOLO_WSL_DISTRO", "") or "").strip()
        if distro:
            try:
                probe = subprocess.run(
                    ["wsl.exe", "-d", distro, "--", "bash", "-lc", "hostname -I | awk '{print $1}'"],
                    capture_output=True,
                    text=True,
                    timeout=8,
                    check=False,
                )
            except OSError:
                probe = None
            if probe and probe.returncode == 0:
                ip = str(probe.stdout or "").strip().split()
                if ip:
                    forwarded = f"http://{ip[0]}:{config.runtime.api_port}"
                    if forwarded not in base_urls:
                        base_urls.append(forwarded)
    headers = {}
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json; charset=utf-8"
    for base_url in base_urls:
        url = f"{base_url}{path}"
        if query:
            url = f"{url}?{query}"
        request = Request(url, data=data, headers=headers, method=method.upper())
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError):
            continue
    return None


def _mind_context(daemon, *, thread_key: str | None, chat_name: str | None, channel: str, sender: str | None) -> dict:
    return {
        "channel": channel,
        "thread_key": thread_key or "",
        "chat_name": chat_name or "",
        "sender": sender or "",
        "recall_trigger_mode": daemon.config.memory.recall_trigger_mode,
        "mind_budget": {
            "fast_history_messages": daemon.config.memory.fast_history_messages,
            "recall_history_messages": daemon.config.memory.recall_history_messages,
            "fast_episodic_k": daemon.config.memory.fast_episodic_k,
            "recall_episodic_k": daemon.config.memory.recall_episodic_k,
            "fast_consciousness_k": daemon.config.memory.fast_consciousness_k,
            "recall_consciousness_k": daemon.config.memory.recall_consciousness_k,
        },
    }


def _health_payload(config_path: str | None) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/health")
    if live_payload is not None:
        return live_payload, "live_http"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.health(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _inspect_mind_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    include_graph_trace: bool = True,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/inspect-mind",
        params={
            "query": query,
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "sender": sender,
            "include_graph_trace": 1 if include_graph_trace else 0,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    payload = daemon.memory.inspect_mind(
        query,
        context=_mind_context(daemon, thread_key=thread_key, chat_name=chat_name, channel=channel, sender=sender),
        include_graph_trace=include_graph_trace,
    )
    return payload, "local_process"


def _trace_hybrid_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/trace-hybrid-recall",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    payload = daemon.memory.trace_hybrid_recall(
        query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        record=False,
    )
    return payload, "local_process"


def _reply_probe_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    allow_local_fallback: bool = True,
    timeout: float = 180.0,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/reply-probe",
        payload={
            "chat_name": chat_name or thread_key or "",
            "thread_key": thread_key or "",
            "channel": channel,
            "sender": sender or chat_name or thread_key or "",
            "text": query,
        },
        timeout=timeout,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        payload = service.reply_probe(
            {
                "chat_name": chat_name or thread_key or "",
                "thread_key": thread_key or "",
                "channel": channel,
                "sender": sender or chat_name or thread_key or "",
                "text": query,
            }
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()
    return payload, "local_process"


def _activation_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/activation-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.activation_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _vector_health_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/vector-health")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.vector_health(), "local_process"


def _stream_status_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/stream-status")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.stream_status(), "local_process"


def _brain_status_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/brain-status")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.brain_status(), "local_process"


def _processor_routing_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/processor-routing")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.processor_routing(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _provider_status_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/provider-status")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.provider_status(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _provider_substrate_status_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/provider-substrate-status")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.provider_substrate_status(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _provider_contracts_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/provider-contracts")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.provider_contracts(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _visual_provider_readiness_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/visual-provider-readiness")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.visual_provider_readiness(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _debt_registry_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/debt-registry")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.debt_registry(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _internal_runtime_readiness_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/internal-runtime-readiness")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.internal_runtime_readiness(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _usage_ledger_payload(
    config_path: str | None,
    *,
    limit: int = 50,
    task_type: str | None = None,
    lane: str | None = None,
    provider: str | None = None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/usage-ledger",
        params={"limit": limit, "task_type": task_type, "lane": lane, "provider": provider},
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.usage_ledger(limit=limit, task_type=task_type, lane=lane, provider=provider), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_processor_fabric_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="POST", path="/accept-processor-fabric", payload={}, timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_processor_fabric(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage33_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="POST", path="/accept-stage33", payload={}, timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_stage33(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage34_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="POST", path="/accept-stage34", payload={}, timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_stage34(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage35_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="POST", path="/accept-stage35", payload={}, timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.accept_stage35(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _self_model_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/self-model")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.self_model_state(), "local_process"


def _operator_status_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/operator-status")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.operator_status(), "local_process"


def _visual_memory_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/visual-memory",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.visual_memory_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _trace_visual_recall_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int = 4,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/trace-visual-recall",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_visual_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"


def _brain_mode_payload(
    config_path: str | None,
    *,
    mode: str,
    note: str = "",
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/brain-mode",
        payload={"mode": mode, "note": note},
        timeout=15.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.set_brain_mode(mode, note=note), "local_process"


def _self_revision_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    corrections: list[str],
    apply_patch: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/self-revision",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "corrections": corrections,
            "apply_patch": apply_patch,
        },
        timeout=180.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.run_self_revision(
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            corrections=corrections,
            apply_patch=apply_patch,
        ),
        "local_process",
    )


def _operator_probe_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/operator-probe",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.operator_probe(
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
        ),
        "local_process",
    )


def _initiative_probe_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/initiative-probe",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "query": query,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.initiative_probe(
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            query=query,
        ),
        "local_process",
    )


def _operator_cycle_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    reason: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/operator-cycle",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "reason": reason,
        },
        timeout=180.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.run_operator_cycle(
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            reason=reason,
        ),
        "local_process",
    )


def _initiative_status_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/initiative-status",
        params={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "limit": limit,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.initiative_status(
            thread_key=str(thread_key or chat_name or "").strip(),
            chat_name=str(chat_name or thread_key or "").strip(),
            channel=channel,
            limit=limit,
        ),
        "local_process",
    )


def _affect_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/affect-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.affect_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _drive_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/drive-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.drive_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _intent_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/intent-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "query": query},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.intent_state(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query), "local_process"


def _action_market_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/action-market",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "query": query, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.action_market(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query, limit=limit), "local_process"


def _fast_path_metrics_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/fast-path-metrics",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_fast_path_metrics(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _predictive_continuity_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/predictive-continuity",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_predictive_continuity(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _scene_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/scene-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_scene_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _predicted_branches_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/predicted-branches",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_predicted_branches(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _scene_compression_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/scene-compression",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_scene_compression(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _situational_field_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/situational-field",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.show_situational_field(query=query, thread_key=thread_key, chat_name=chat_name, channel=channel),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _visual_field_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/visual-field",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.trace_visual_field(thread_key=thread_key, chat_name=chat_name, channel=channel),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _inquiry_shaping_payload(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/inquiry-shaping",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.trace_inquiry_shaping(
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _task_world_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    include_inactive: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/task-world",
        params={
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "limit": limit,
            "include_inactive": include_inactive,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.show_task_world(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                include_inactive=include_inactive,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _world_object_payload(
    config_path: str | None,
    *,
    object_id: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/world-object",
        params={"object_id": object_id},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_world_object(object_id=object_id), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _thread_object_links_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/thread-object-links",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.trace_thread_object_links(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _continuity_budget_payload(
    config_path: str | None,
    *,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/continuity-budget",
        params={"channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_continuity_budget(channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _dense_working_set_payload(
    config_path: str | None,
    *,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/dense-working-set",
        params={"channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_dense_working_set(channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _thread_pulse_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/thread-pulse",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_thread_pulse(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _attention_frontier_payload(
    config_path: str | None,
    *,
    channel: str | None,
    limit: int,
    include_stale: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/attention-frontier",
        params={"channel": channel or "", "limit": limit, "include_stale": str(bool(include_stale)).lower()},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_attention_frontier(channel=channel, limit=limit, include_stale=include_stale), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _wake_reasons_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/wake-reasons",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_wake_reasons(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _thread_warmth_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/thread-warmth",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_thread_warmth(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _open_loops_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/open-loops",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "include_inactive": str(bool(include_inactive)).lower()},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_open_loops(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _commitments_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/commitments",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "include_inactive": str(bool(include_inactive)).lower()},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_commitments(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _resume_candidate_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/resume-candidate",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "include_inactive": str(bool(include_inactive)).lower()},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_resume_candidate(thread_key=thread_key, chat_name=chat_name, channel=channel, include_inactive=include_inactive), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _world_state_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/world-state",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.world_state(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _world_coupling_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    include_inactive: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/world-coupling",
        params={
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "limit": limit,
            "include_inactive": str(bool(include_inactive)).lower(),
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.show_world_coupling(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                include_inactive=include_inactive,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _autobiographical_state_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/autobiographical-state")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.autobiographical_state(), "local_process"


def _goal_state_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/goal-state")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.goal_state(), "local_process"


def _engineering_state_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/engineering-state")
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    try:
        return service.engineering_state(), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _action_calibration_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None = None,
    scenario_bucket: str | None = None,
    limit: int = 24,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/action-calibration",
        params={
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "action_type": action_type,
            "scenario_bucket": scenario_bucket,
            "limit": limit,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.show_action_calibration(
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        scenario_bucket=scenario_bucket,
        limit=limit,
    ), "local_process"


def _policy_candidates_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int = 24,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/policy-candidates",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_policy_candidates(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _promoted_policies_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int = 24,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/promoted-policies",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_promoted_policies(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _rollback_policy_payload(
    config_path: str | None,
    *,
    policy_id: str,
    reason: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/rollback-policy",
        payload={"id": policy_id, "reason": reason},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.rollback_policy(policy_id=policy_id, reason=reason), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _policy_influence_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int = 8,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/policy-influence",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "query": query, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_policy_influence(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query, limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _online_canary_payload(config_path: str | None, *, limit: int, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/online-canary", params={"limit": limit}, timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_online_canary(limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _blackbox_metrics_payload(
    config_path: str | None,
    *,
    window_hours: float,
    thread_key: str | None,
    chat_name: str | None,
    channel: str | None,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/blackbox-metrics",
        params={"window_hours": window_hours, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.show_blackbox_metrics(
                window_hours=window_hours,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _blackbox_scorecard_payload(
    config_path: str | None,
    *,
    since_hours: float,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/blackbox-scorecard",
        params={"since_hours": since_hours, "limit": limit},
        timeout=60.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.show_blackbox_scorecard(since_hours=since_hours, limit=limit), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _canary_decision_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/canary-decision",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "query": query},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_canary_decision(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _canary_rollback_payload(
    config_path: str | None,
    *,
    enabled: bool,
    reason: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/canary-rollback",
        payload={"enabled": enabled, "reason": reason},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.set_canary_rollback(enabled=enabled, reason=reason), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _replay_live_artifacts_payload(
    config_path: str | None,
    *,
    since_hours: float,
    limit: int,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/replay-live-artifacts",
        payload={"since_hours": since_hours, "limit": limit, "artifact_dir": artifact_dir or ""},
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.replay_live_artifacts(since_hours=since_hours, limit=limit, artifact_dir=artifact_dir), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _export_blind_packets_payload(
    config_path: str | None,
    *,
    since_hours: float,
    limit: int,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/blind-packets",
        payload={"since_hours": since_hours, "limit": limit, "artifact_dir": artifact_dir or ""},
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.export_blind_packets(since_hours=since_hours, limit=limit, artifact_dir=artifact_dir), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _run_blackbox_soak_payload(
    config_path: str | None,
    *,
    since_hours: float,
    limit: int,
    artifact_dir: str | None,
    persist: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/blackbox-soak",
        payload={"since_hours": since_hours, "limit": limit, "artifact_dir": artifact_dir or "", "persist": persist},
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.run_blackbox_soak(since_hours=since_hours, limit=limit, artifact_dir=artifact_dir, persist=persist),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _outcome_history_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None = None,
    limit: int = 8,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/outcome-history",
        params={
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "action_type": action_type,
            "limit": limit,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_outcome_history(
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        limit=limit,
    ), "local_process"


def _prediction_error_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None = None,
    limit: int = 8,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/action-prediction-error",
        params={
            "thread_key": thread_key,
            "chat_name": chat_name,
            "channel": channel,
            "action_type": action_type,
            "limit": limit,
        },
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_action_prediction_error(
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        limit=limit,
    ), "local_process"


def _stage14_replay_payload(
    config_path: str | None,
    *,
    path: str,
    source_type: str,
    fixture_path: str | None,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path=path,
        payload={
            "source_type": source_type,
            "fixture_path": fixture_path or "",
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "limit": limit,
            "artifact_dir": artifact_dir or "",
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        if path == "/replay-calibration-fixture":
            return (
                service.replay_calibration_fixture(
                    source_type=source_type,
                    fixture_path=fixture_path,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=limit,
                    artifact_dir=artifact_dir,
                ),
                "local_service",
            )
        if path == "/replay-policy-regret":
            return (
                service.replay_policy_regret(
                    source_type=source_type,
                    fixture_path=fixture_path,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=limit,
                    artifact_dir=artifact_dir,
                ),
                "local_service",
            )
        return (
            service.accept_stage14(
                source_type=source_type,
                fixture_path=fixture_path,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _self_continuity_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/self-continuity", timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_self_continuity(), "local_process"


def _goal_arbitration_payload(config_path: str | None, *, allow_local_fallback: bool = True) -> tuple[dict, str]:
    live_payload = _live_api_request(config_path, method="GET", path="/goal-arbitration", timeout=30.0)
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_goal_arbitration(), "local_process"


def _counterfactual_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/counterfactual",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "query": query, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_counterfactual(query=query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"


def _world_calibration_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/world-calibration",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_world_calibration(thread_key=thread_key, chat_name=chat_name, channel=channel), "local_process"


def _initiative_market_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/initiative-market",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.initiative_market(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"


def _trace_resistance_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/trace-resistance",
        payload={"thread_key": thread_key or "", "chat_name": chat_name or "", "channel": channel, "query": query},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_resistance(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query), "local_process"


def _trace_action_selection_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/trace-action-selection",
        payload={"thread_key": thread_key or "", "chat_name": chat_name or "", "channel": channel, "query": query, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_action_selection(query=query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"


def _trace_reflex_routing_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/trace-reflex-routing",
        payload={"thread_key": thread_key or "", "chat_name": chat_name or "", "channel": channel, "query": query},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.trace_reflex_routing(thread_key=thread_key, chat_name=chat_name, channel=channel, query=query), "local_process"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _initiative_run_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    dry_run: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/initiative-run",
        payload={"thread_key": thread_key or "", "chat_name": chat_name or "", "channel": channel, "dry_run": dry_run},
        timeout=60.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.initiative_run(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                dry_run=dry_run,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _ingest_image_payload(
    config_path: str | None,
    *,
    path: str,
    note: str | None,
    source: str,
    tags: list[str],
    channel: str,
    thread_key: str | None,
    chat_name: str | None,
    sync: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/ingest-image",
        payload={
            "path": path,
            "note": note or "",
            "source": source,
            "tags": tags,
            "channel": channel,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "sync": sync,
        },
        timeout=180.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.ingest_image(
                {
                    "path": path,
                    "note": note or "",
                    "source": source,
                    "tags": tags,
                    "channel": channel,
                    "thread_key": thread_key or "",
                    "chat_name": chat_name or "",
                    "sync": sync,
                }
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage3_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage3",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage3(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage4_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage4",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage4(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage5_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage5",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage5(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _deliberation_ledger_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/deliberation-ledger",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.trace_deliberation_ledger(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit), "local_process"


def _accept_stage6_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage6",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage6(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage7_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage7",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage7(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage8_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage8",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage8(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage9_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage9",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage9(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage10_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage10",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage10(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_process",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _backfill_vector_memory_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/backfill-vector-memory",
        payload={"channel": channel, "thread_key": thread_key, "chat_name": chat_name},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return (
        daemon.memory.backfill_vector_memory(channel=channel, thread_key=thread_key, chat_name=chat_name),
        "local_process",
    )


def _sync_private_memory_payload(
    config_path: str | None,
    *,
    label: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/sync-private-memory",
        payload={"label": label or ""},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    return daemon.memory.sync_private_memory(label=label), "local_process"


def _stream_tick_payload(
    config_path: str | None,
    *,
    stream_name: str,
    dry_run: bool,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/stream-tick",
        payload={"stream_name": stream_name, "dry_run": dry_run},
        timeout=30.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    daemon = build_daemon(config_path)
    stream_name = str(stream_name or "").strip()
    if stream_name == "maintenance_stream":
        result = daemon.memory.run_reflect_cycle(window_hours=daemon.config.memory.reflection_window_hours, dry_run=dry_run)
    elif stream_name == "association_stream":
        result = daemon.memory.run_think_cycle(sample_size=daemon.config.memory.thought_sample_size, dry_run=dry_run)
    elif stream_name == "social_stream":
        result = daemon.memory.run_initiative_cycle(dry_run=dry_run)
    elif stream_name == "deep_dream_cycle":
        result = daemon.memory.run_dream_cycle(sample_size=daemon.config.memory.dream_sample_size, dry_run=dry_run)
    else:
        raise ValueError(f"unsupported stream_name: {stream_name}")
    record = daemon.memory.record_stream_run(stream_name, status="ok", note="stream_tick", payload=result)
    return {"stream_name": stream_name, "dry_run": bool(dry_run), "result": result, "record": record}, "local_process"


def _benchmark_memory_fabric_report(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    probe: str,
    allow_local_fallback: bool = True,
) -> dict[str, object]:
    total_rounds = max(1, int(iterations)) + max(0, int(warmup))
    measured_rounds = max(1, int(iterations))
    timings_ms: list[float] = []
    last_payload: dict | None = None
    used_live_http = False

    for index in range(total_rounds):
        started_at = time.perf_counter()
        if probe == "trace-hybrid":
            payload, transport = _trace_hybrid_payload(
                config_path,
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=8,
                allow_local_fallback=allow_local_fallback,
            )
        else:
            payload, transport = _inspect_mind_payload(
                config_path,
                query=query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                include_graph_trace=False,
                allow_local_fallback=allow_local_fallback,
            )
        used_live_http = used_live_http or transport == "live_http"
        measured_ms = float(payload.get("build_ms", 0.0) or 0.0)
        elapsed_ms = round(measured_ms if measured_ms > 0 else (time.perf_counter() - started_at) * 1000.0, 2)
        last_payload = payload
        if index >= total_rounds - measured_rounds:
            timings_ms.append(elapsed_ms)

    return {
        "query": query,
        "thread_key": thread_key or "",
        "chat_name": chat_name or "",
        "channel": channel,
        "iterations": measured_rounds,
        "warmup": max(0, int(warmup)),
        "probe": probe,
        "transport": "live_http" if used_live_http else "local_process",
        "timings_ms": {
            "min": round(min(timings_ms), 2),
            "median": round(statistics.median(timings_ms), 2),
            "mean": round(statistics.mean(timings_ms), 2),
            "max": round(max(timings_ms), 2),
        },
        "last_tier": str((last_payload or {}).get("tier", "")),
        "last_query_focus": str((last_payload or {}).get("query_focus", "")),
        "last_retrieval_mode": str((last_payload or {}).get("retrieval_mode", "")),
        "last_memory_route": str((last_payload or {}).get("memory_route", "")),
        "last_recall_confidence": float((last_payload or {}).get("recall_confidence", 0.0) or 0.0),
        "last_vector_hit_count": len(list((last_payload or {}).get("vector_hits", []))),
        "last_activation_trace_count": len(list((last_payload or {}).get("activation_trace_ids", []))),
    }


def _pick_query_for_target_tier(
    config_path: str | None,
    *,
    candidates: tuple[str, ...],
    target_tier: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    allow_local_fallback: bool = True,
) -> tuple[str, dict, str]:
    fallback_query = candidates[0]
    fallback_payload: dict | None = None
    fallback_transport = "local_process"
    for query in candidates:
        payload, transport = _inspect_mind_payload(
            config_path,
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            include_graph_trace=False,
            allow_local_fallback=allow_local_fallback,
        )
        if fallback_payload is None:
            fallback_query = query
            fallback_payload = payload
            fallback_transport = transport
        if str(payload.get("tier", "")).strip() == target_tier:
            return query, payload, transport
    return fallback_query, fallback_payload or {}, fallback_transport


def _stage1_check(name: str, ok: bool, detail: str, *, severity: str = "failure") -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def _origin_text_is_substantive(text: str) -> bool:
    current = " ".join(str(text or "").strip().split())
    lowered = current.lower()
    if not current or lowered in _ORIGIN_LOW_SIGNAL_TEXTS:
        return False
    if "[thumbsup]" in lowered or "[点赞]" in current:
        return False
    meaningful = sum(1 for ch in current if ch.isalnum() or "\u3400" <= ch <= "\u9fff")
    return meaningful >= 8


def _evaluate_stage1_acceptance(
    *,
    transport: str,
    health: dict[str, object],
    vector_health: dict[str, object],
    explicit_trace: dict[str, object],
    origin_trace: dict[str, object],
    reply_probe: dict[str, object],
    activation_state: dict[str, object],
    stream_ticks: list[dict[str, object]],
    stream_status: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
    private_sync: dict[str, object] | None,
    require_private_sync: bool,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    repo_root = str(health.get("repo_root", ""))
    vector_hits = list(explicit_trace.get("vector_hits", []))
    origin_lines = [str(item.get("text", "")) for item in list(origin_trace.get("graph_hits", [])) + list(origin_trace.get("vector_hits", []))]
    hybrid_probe = dict(reply_probe.get("hybrid", {}))
    reconstruction = dict(hybrid_probe.get("recall_reconstruction", {}))
    if not reconstruction:
        reconstruction = dict(dict(hybrid_probe.get("reply_plan", {})).get("debug", {}).get("recall_reconstruction", {}))
    summary = str(reconstruction.get("summary", "")).strip()
    anchors = [str(item).strip() for item in reconstruction.get("anchors", []) if str(item).strip()]
    stream_influence = any(
        int(dict(item.get("record", {})).get("influence", {}).get("updated_threads", 0) or 0) > 0
        or int(dict(item.get("record", {})).get("influence", {}).get("updated_nodes", 0) or 0) > 0
        or bool(list(dict(item.get("record", {})).get("influence", {}).get("motifs", [])))
        for item in stream_ticks
    )
    checks.append(
        _stage1_check(
            "live_health",
            bool(health.get("status") == "ok" and health.get("graph_led_reply_enabled") and health.get("fallback_enabled") and health.get("activation_cache_enabled")),
            f"status={health.get('status')} graph_led={health.get('graph_led_reply_enabled')} fallback={health.get('fallback_enabled')} activation_cache={health.get('activation_cache_enabled')}",
        )
    )
    checks.append(
        _stage1_check(
            "wsl_authority",
            transport == "live_http" and repo_root.startswith("/"),
            f"transport={transport} repo_root={repo_root}",
        )
    )
    checks.append(
        _stage1_check(
            "vector_ready",
            bool(vector_health.get("available") and (vector_health.get("ready") or len(vector_hits) > 0)),
            f"backend={vector_health.get('backend')} ready={vector_health.get('ready')} available={vector_health.get('available')} vector_hits={len(vector_hits)}",
        )
    )
    checks.append(
        _stage1_check(
            "hybrid_recall_route",
            str(explicit_trace.get("retrieval_mode", "")).startswith("hybrid-led") and str(explicit_trace.get("memory_route", "")) == "hybrid" and len(vector_hits) > 0,
            f"retrieval_mode={explicit_trace.get('retrieval_mode')} memory_route={explicit_trace.get('memory_route')} vector_hits={len(vector_hits)}",
        )
    )
    checks.append(
        _stage1_check(
            "explicit_recall_quality",
            bool(summary) and 1 <= len(anchors) <= 3,
            f"summary={summary or '<empty>'} anchors={len(anchors)}",
        )
    )
    checks.append(
        _stage1_check(
            "origin_recall_focus",
            str(origin_trace.get("query_focus", "")) == "origin" and any(_origin_text_is_substantive(text) for text in origin_lines),
            f"query_focus={origin_trace.get('query_focus')} substantive_hits={sum(1 for text in origin_lines if _origin_text_is_substantive(text))}",
        )
    )
    checks.append(
        _stage1_check(
            "activation_observable",
            bool(list(explicit_trace.get("activation_trace_ids", []))) or bool(list(activation_state.get("active_node_ids", []))),
            f"activation_trace_ids={len(list(explicit_trace.get('activation_trace_ids', [])))} active_nodes={len(list(activation_state.get('active_node_ids', [])))}",
        )
    )
    checks.append(
        _stage1_check(
            "stream_influence",
            stream_influence,
            f"stream_ticks={len(stream_ticks)} recent_runs={len(list(stream_status.get('recent_runs', [])))}",
        )
    )
    checks.append(
        _stage1_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 300.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage1_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 900.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage1_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    if require_private_sync or private_sync is not None:
        status = str((private_sync or {}).get("status", "")).strip()
        if status == "ok":
            checks.append(
                _stage1_check(
                    "private_sync",
                    True,
                    f"status=ok snapshot_dir={(private_sync or {}).get('snapshot_dir', '')}",
                )
            )
        else:
            checks.append(
                _stage1_check(
                    "private_sync",
                    False,
                    f"status={status or 'skipped'} reason={(private_sync or {}).get('reason', '')}",
                    severity="blocker",
                )
            )

    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    if failures:
        status = "fail"
    elif blockers:
        status = "blocked"
    elif warnings:
        status = "warn"
    else:
        status = "pass"
    return {
        "stage": "memory-fabric-stage1",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
    }


def _stage2_check(name: str, ok: bool, detail: str, *, severity: str = "failure") -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def _evaluate_stage2_acceptance(
    *,
    transport: str,
    health: dict[str, object],
    brain_status: dict[str, object],
    mode_transitions: list[dict[str, object]],
    persona_probes: dict[str, dict[str, object]],
    stream_status_before: dict[str, object],
    stream_ticks: list[dict[str, object]],
    stream_status_after: dict[str, object],
    initiative_probe: dict[str, object],
    self_revision: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    loops = {str(item.get("loop_name", "")): dict(item) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    checks.append(
        _stage2_check(
            "live_brain",
            transport == "live_http" and str(health.get("status", "")) == "ok" and str(brain_status.get("mode", "")) in {"silent", "companion", "dream_only", "full_brain"},
            f"transport={transport} status={health.get('status')} mode={brain_status.get('mode')}",
        )
    )
    required_loops = {"heartbeat", "attention_tick", "maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"}
    checks.append(
        _stage2_check(
            "runtime_loops_visible",
            required_loops.issubset(set(loops)),
            f"visible_loops={sorted(loops)}",
        )
    )
    checks.append(
        _stage2_check(
            "runtime_modes_switchable",
            {str(item.get("mode", "")) for item in mode_transitions if str(item.get("status", "")) == "ok"} >= {"silent", "companion", "dream_only", "full_brain"},
            f"transitions={mode_transitions}",
        )
    )
    playful_probe = dict(persona_probes.get("playful", {}))
    serious_probe = dict(persona_probes.get("serious", {}))
    appetite_probe = dict(persona_probes.get("appetite", {}))
    correction_probe = dict(persona_probes.get("correction", {}))
    playful_blend = dict(playful_probe.get("persona_blend", {}))
    serious_blend = dict(serious_probe.get("persona_blend", {}))
    checks.append(
        _stage2_check(
            "persona_playful_range",
            float(playful_blend.get("playfulness", 0.0) or 0.0) >= 0.6 and float(playful_blend.get("slyness", 0.0) or 0.0) >= 0.58,
            f"playfulness={playful_blend.get('playfulness')} slyness={playful_blend.get('slyness')} text={dict(playful_probe.get('reply_plan', {})).get('text', '')[:120]}",
        )
    )
    checks.append(
        _stage2_check(
            "persona_serious_grounded",
            float(serious_blend.get("wisdom", 0.0) or 0.0) >= 0.68 and float(serious_blend.get("playfulness", 0.0) or 0.0) <= 0.75,
            f"wisdom={serious_blend.get('wisdom')} playfulness={serious_blend.get('playfulness')} text={dict(serious_probe.get('reply_plan', {})).get('text', '')[:120]}",
        )
    )
    checks.append(
        _stage2_check(
            "persona_appetite_present",
            float(dict(appetite_probe.get("persona_blend", {})).get("sensuality_appetite", 0.0) or 0.0) >= 0.48,
            f"sensuality_appetite={dict(appetite_probe.get('persona_blend', {})).get('sensuality_appetite')} text={dict(appetite_probe.get('reply_plan', {})).get('text', '')[:120]}",
        )
    )
    checks.append(
        _stage2_check(
            "correction_probe_observable",
            float(dict(correction_probe.get("game_state", {})).get("correction_sensitivity", 0.0) or 0.0) >= 0.3,
            f"correction_sensitivity={dict(correction_probe.get('game_state', {})).get('correction_sensitivity')}",
        )
    )
    before_events = len(list(stream_status_before.get("activation_events", [])))
    after_events = len(list(stream_status_after.get("activation_events", [])))
    stream_influence = any(
        int(dict(item.get("record", {})).get("influence", {}).get("updated_threads", 0) or 0) > 0
        or bool(list(dict(item.get("record", {})).get("influence", {}).get("motifs", [])))
        for item in stream_ticks
    )
    checks.append(
        _stage2_check(
            "stream_influence_visible",
            stream_influence and after_events >= before_events,
            f"stream_ticks={len(stream_ticks)} activation_events_before={before_events} activation_events_after={after_events}",
        )
    )
    checks.append(
        _stage2_check(
            "initiative_probe_explains_gate",
            "allowed" in initiative_probe and "game_rationale" in initiative_probe and "policy_rationale" in initiative_probe and "cooldown_rationale" in initiative_probe,
            f"allowed={initiative_probe.get('allowed')} game={initiative_probe.get('game_rationale')} cooldown={initiative_probe.get('cooldown_rationale')}",
        )
    )
    checks.append(
        _stage2_check(
            "self_revision_runs",
            str(self_revision.get("status", "")) in {"applied", "reviewed", "rejected", "skipped"} and bool(self_revision.get("evidence")),
            f"status={self_revision.get('status')} evidence={len(list(self_revision.get('evidence', [])))}",
        )
    )
    checks.append(
        _stage2_check(
            "self_revision_patch_bounded",
            all(key in {"persona_blend", "stream_cadence_multiplier", "recall_rerank_weights", "relationship_reweight", "game_reweight", "initiative_thresholds", "prompt_composer_bias"} for key in dict(self_revision.get("patch", {}))),
            f"patch_keys={sorted(dict(self_revision.get('patch', {})).keys())}",
        )
    )
    checks.append(
        _stage2_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage2_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage2_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "always-on-companion-brain-stage2",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
    }


def _stage3_check(name: str, ok: bool, detail: str, *, severity: str = "failure") -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def _evaluate_stage3_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    brain_status: dict[str, object],
    before_self_model: dict[str, object],
    after_self_model: dict[str, object],
    operator_probe: dict[str, object],
    operator_cycle: dict[str, object],
    visual_ingest: dict[str, object],
    visual_state: dict[str, object],
    visual_trace: dict[str, object],
    stream_status: dict[str, object],
    initiative_probe: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    loops = {str(item.get("loop_name", "")): dict(item) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    required_loops = {
        "heartbeat",
        "attention_tick",
        "maintenance_stream",
        "association_stream",
        "social_stream",
        "deep_dream_cycle",
        "self_model_refresh",
        "homeostasis_tick",
        "operator_planning",
        "operator_shadow_cycle",
        "visual_ingest_cycle",
    }
    checks.append(
        _stage3_check(
            "live_subject_kernel",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage3_check(
            "runtime_loops_visible",
            required_loops.issubset(set(loops)),
            f"visible_loops={sorted(loops)}",
        )
    )
    before_observed = str(dict(before_self_model.get("metadata", {})).get("observed_at", "") or "")
    after_observed = str(dict(after_self_model.get("metadata", {})).get("observed_at", "") or "")
    checks.append(
        _stage3_check(
            "self_model_continuity",
            float(after_self_model.get("identity_continuity", 0.0) or 0.0) >= 0.55
            and bool(list(after_self_model.get("long_horizon_goals", [])))
            and bool(list(after_self_model.get("active_deficits", [])))
            and after_observed != before_observed,
            f"identity_continuity={after_self_model.get('identity_continuity')} before={before_observed} after={after_observed}",
        )
    )
    write_boundary = dict(operator_probe.get("write_boundary", {}))
    checks.append(
        _stage3_check(
            "operator_probe_bounded",
            bool(str(operator_probe.get("goal", "")).strip()) and str(write_boundary.get("live_repo", "")) == "forbidden",
            f"goal={operator_probe.get('goal')} live_repo={write_boundary.get('live_repo')}",
        )
    )
    operator_execution = dict(operator_cycle.get("execution", {}))
    checks.append(
        _stage3_check(
            "operator_shadow_cycle",
            str(operator_cycle.get("status", "")) in {"applied", "reviewed", "shadow_only", "rejected"}
            and not bool(dict(operator_execution.get("shadow_patch", {})).get("applied_live", False)),
            f"status={operator_cycle.get('status')} scope={operator_execution.get('scope')} applied_live={operator_execution.get('applied_live', False)}",
        )
    )
    visual_summary = str(dict(visual_state).get("scene_summary", "")).strip()
    visual_anchors = [str(item).strip() for item in visual_state.get("visual_anchors", []) if str(item).strip()]
    checks.append(
        _stage3_check(
            "visual_memory_ingested",
            str(visual_ingest.get("status", "")) == "ok" and bool(visual_summary or visual_anchors),
            f"status={visual_ingest.get('status')} scene_summary={visual_summary[:80]} anchors={visual_anchors[:2]}",
        )
    )
    visual_hits = list(visual_trace.get("hits", []))
    checks.append(
        _stage3_check(
            "visual_recall_hits",
            bool(visual_hits) and any(
                str(item.get("thread_key", "")).strip() == str(visual_trace.get("thread_key", "")).strip()
                for item in visual_hits
            ),
            f"hits={len(visual_hits)} thread_key={visual_trace.get('thread_key')}",
        )
    )
    stream_events = list(stream_status.get("activation_events", []))
    stream_influence = dict(stream_status.get("stream_influence", {}))
    checks.append(
        _stage3_check(
            "subjective_continuity_visible",
            bool(stream_events)
            or bool(stream_influence)
            or bool(dict(after_self_model.get("metadata", {})).get("summary", "")),
            f"activation_events={len(stream_events)} stream_influence_keys={sorted(stream_influence.keys())}",
        )
    )
    checks.append(
        _stage3_check(
            "initiative_and_operator_share_state",
            "allowed" in initiative_probe and "game_rationale" in initiative_probe and bool(operator_probe.get("goal")),
            f"initiative_allowed={initiative_probe.get('allowed')} operator_goal={operator_probe.get('goal')}",
        )
    )
    checks.append(
        _stage3_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage3_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage3_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "reflective-subject-kernel-stage3",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "self_model_continuity": {
            "before": before_self_model,
            "after": after_self_model,
        },
        "operator_shadow": {
            "probe": operator_probe,
            "cycle": operator_cycle,
        },
        "visual_recall": {
            "ingest": visual_ingest,
            "state": visual_state,
            "trace": visual_trace,
        },
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
        "stream_influence_count": len(stream_events),
    }


def _stage4_check(name: str, ok: bool, detail: str, *, severity: str = "failure") -> dict[str, object]:
    return {"name": name, "ok": bool(ok), "detail": detail, "severity": severity}


def _evaluate_stage4_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    brain_status: dict[str, object],
    self_model: dict[str, object],
    affect_state: dict[str, object],
    drive_state: dict[str, object],
    initiative_market: dict[str, object],
    initiative_probe: dict[str, object],
    operator_probe: dict[str, object],
    resistance_trace: dict[str, object],
    runtime_cycle: dict[str, object],
    stream_ticks: list[dict[str, object]],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    loops = {str(item.get("loop_name", "")): dict(item) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    required_loops = {
        "heartbeat",
        "attention_tick",
        "maintenance_stream",
        "association_stream",
        "social_stream",
        "deep_dream_cycle",
        "self_model_refresh",
        "homeostasis_tick",
        "operator_planning",
        "operator_shadow_cycle",
        "visual_ingest_cycle",
        "affect_tick",
        "drive_arbitration",
        "initiative_marketplace",
        "outcome_appraisal",
    }
    affect = dict(affect_state.get("affect_state", affect_state))
    drive = dict(drive_state.get("drive_state", drive_state))
    value_state = dict(drive_state.get("value_state", {}))
    conflict_state = dict(drive_state.get("conflict_state", {}))
    outcome_memory = dict(drive_state.get("outcome_memory", initiative_market.get("outcome_memory", {})))
    market_rows = list(initiative_market.get("initiative_candidates", initiative_market.get("candidates", [])))
    whitelist_send = any(bool(row.get("send_allowed")) for row in market_rows)
    checks.append(
        _stage4_check(
            "live_endogenous_subject",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage4_check(
            "runtime_loops_visible",
            required_loops.issubset(set(loops)),
            f"visible_loops={sorted(loops)}",
        )
    )
    checks.append(
        _stage4_check(
            "affect_continuity",
            bool(affect)
            and sum(float(affect.get(key, 0.0) or 0.0) for key in ("boredom", "curiosity", "attachment_pull", "continuity_anxiety")) > 0.0,
            f"affect={affect}",
        )
    )
    checks.append(
        _stage4_check(
            "drive_state_present",
            bool(drive) and bool(value_state) and bool(conflict_state),
            f"drive_keys={sorted(drive)} value_keys={sorted(value_state)} conflict_keys={sorted(conflict_state)}",
        )
    )
    checks.append(
        _stage4_check(
            "initiative_market_activity",
            bool(market_rows)
            and all(
                bool(str(row.get("why_now", "")).strip())
                and bool(str(row.get("drive_source", "")).strip())
                and bool(str(row.get("value_rationale", "")).strip())
                and "send_allowed" in row
                for row in market_rows[:4]
            ),
            f"candidates={len(market_rows)} sample={market_rows[:2]}",
        )
    )
    checks.append(
        _stage4_check(
            "white_list_auto_send",
            whitelist_send
            or bool(initiative_probe.get("allowed"))
            or (
                str(initiative_probe.get("gate_level", "")).strip() == "soft_block"
                and bool(initiative_probe.get("override_eligible", False))
            ),
            (
                f"market_send_allowed={whitelist_send} initiative_allowed={initiative_probe.get('allowed')} "
                f"gate_level={initiative_probe.get('gate_level')} override_eligible={initiative_probe.get('override_eligible')}"
            ),
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "resistance_trace_explains_conflict",
            (
                float(resistance_trace.get("interactional_resistance", 0.0) or 0.0) > 0.0
                or float(dict(resistance_trace.get("resistance_posture", {})).get("interactional_resistance", 0.0) or 0.0) > 0.0
            )
            and bool(resistance_trace.get("affect_state"))
            and bool(resistance_trace.get("value_state"))
            and bool(resistance_trace.get("conflict_state")),
            f"resistance={resistance_trace}",
        )
    )
    checks.append(
        _stage4_check(
            "outcome_appraisal_feedback",
            bool(runtime_cycle)
            and str(dict(runtime_cycle.get("outcome_appraisal", {})).get("status", "ok")) in {"ok", "idle", "blocked"}
            and (
                "future_initiative_bias" in outcome_memory
                or "future_resistance_bias" in outcome_memory
                or bool(dict(runtime_cycle.get("outcome_appraisal", {})).get("latest_outcome"))
            ),
            f"outcome={outcome_memory} runtime={runtime_cycle.get('outcome_appraisal')}",
        )
    )
    checks.append(
        _stage4_check(
            "subjective_continuity",
            bool(self_model.get("long_horizon_goals"))
            and bool(self_model.get("relational_commitments"))
            and bool(stream_ticks),
            f"goals={self_model.get('long_horizon_goals')} commitments={self_model.get('relational_commitments')} stream_ticks={len(stream_ticks)}",
        )
    )
    checks.append(
        _stage4_check(
            "operator_and_initiative_share_state",
            bool(operator_probe.get("goal"))
            and bool(initiative_probe.get("game_rationale"))
            and bool(initiative_probe.get("drive_rationale"))
            and bool(initiative_probe.get("affect_state")),
            f"operator_goal={operator_probe.get('goal')} drive_rationale={initiative_probe.get('drive_rationale')}",
        )
    )
    checks.append(
        _stage4_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "endogenous-drive-subject-stage4",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "affect_continuity": affect_state,
        "initiative_marketplace_activity": initiative_market,
        "resistance_trace": resistance_trace,
        "outcome_appraisal": outcome_memory,
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
        "stream_influence_count": len(stream_ticks),
    }


def _evaluate_stage5_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    brain_status: dict[str, object],
    intent_state: dict[str, object],
    action_market: dict[str, object],
    silence_trace: dict[str, object],
    defer_trace: dict[str, object],
    normal_trace: dict[str, object],
    resistance_trace: dict[str, object],
    initiative_probe: dict[str, object],
    operator_probe: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
    roadmap_registry: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    loops = {str(item.get("loop_name", "")): dict(item) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    selected_market = list(action_market.get("action_market", []))
    silence_action = str(dict(silence_trace.get("selected_action", {})).get("action_type", ""))
    defer_action = str(dict(defer_trace.get("selected_action", {})).get("action_type", ""))
    normal_action = str(dict(normal_trace.get("selected_action", {})).get("action_type", ""))
    resistance_action = str(dict(resistance_trace.get("selected_action", {})).get("action_type", ""))
    checks.append(
        _stage4_check(
            "stage5_live_mode",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage4_check(
            "intent_runtime_visible",
            "attention_tick" in loops and "initiative_marketplace" in loops and bool(dict(intent_state).get("intent_state") or dict(intent_state).get("selected_action")),
            f"loops={sorted(loops)} intent={intent_state}",
        )
    )
    checks.append(
        _stage4_check(
            "silence_is_first_class",
            silence_action == "silence" and bool(str(silence_trace.get("silence_reason", "")).strip()),
            f"action={silence_action} reason={silence_trace.get('silence_reason')}",
        )
    )
    checks.append(
        _stage4_check(
            "defer_is_first_class",
            defer_action == "defer_reply" and bool(str(defer_trace.get("defer_reason", "")).strip()),
            f"action={defer_action} reason={defer_trace.get('defer_reason')}",
        )
    )
    checks.append(
        _stage4_check(
            "normal_reply_is_subject_led",
            normal_action in {"reply_once", "reply_multi"} and bool(str(normal_trace.get("action_rationale", "")).strip()),
            f"action={normal_action} rationale={normal_trace.get('action_rationale')}",
        )
    )
    checks.append(
        _stage4_check(
            "talkativeness_is_budgeted",
            int(normal_trace.get("expression_budget", 0) or 0) <= 2 and int(silence_trace.get("expression_budget", 0) or 0) == 0,
            f"normal_budget={normal_trace.get('expression_budget')} silence_budget={silence_trace.get('expression_budget')}",
        )
    )
    checks.append(
        _stage4_check(
            "resistance_shares_subject_state",
            resistance_action in {"reply_once", "reply_multi", "defer_reply", "silence"}
            and bool(resistance_trace.get("affect_state"))
            and bool(resistance_trace.get("value_state"))
            and bool(resistance_trace.get("conflict_state")),
            f"action={resistance_action} trace={resistance_trace}",
        )
    )
    checks.append(
        _stage4_check(
            "action_market_human_first",
            bool(selected_market)
            and all(bool(str(item.get("action_type", "")).strip()) for item in selected_market[:4])
            and bool(initiative_probe.get("game_rationale"))
            and bool(operator_probe.get("scope") or operator_probe.get("goal")),
            f"market={selected_market[:3]} initiative={initiative_probe} operator={operator_probe}",
        )
    )
    checks.append(
        _stage4_check(
            "roadmap_registry_present",
            all(key in roadmap_registry for key in ("Primary Track", "Secondary Tracks", "Parked Hypotheses", "Deferred Experiments", "Constitutional Constraints")),
            f"keys={sorted(roadmap_registry)}",
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "intent-led-subject-runtime-stage5",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "intent_state": intent_state,
        "action_market": action_market,
        "silence_trace": silence_trace,
        "defer_trace": defer_trace,
        "normal_trace": normal_trace,
        "resistance_trace": resistance_trace,
        "roadmap_registry": roadmap_registry,
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
    }


def _evaluate_stage6_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    silence_trace: dict[str, object],
    defer_trace: dict[str, object],
    lookup_trace: dict[str, object],
    recall_trace: dict[str, object],
    reply_probe: dict[str, object],
    ledger: dict[str, object],
    brain_status: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    graph_led = dict(reply_probe.get("graph_led", {})) if isinstance(reply_probe.get("graph_led", {}), dict) else {}
    reply_bubbles = list(graph_led.get("bubbles", [])) or list(reply_probe.get("bubbles", []))
    ledger_entries = list(ledger.get("entries", []))
    checks.append(_stage4_check("stage6_live_mode", str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain", f"status={health.get('status')} mode={mode_transition.get('mode')}"))
    checks.append(_stage4_check("silence_first_class", str(dict(silence_trace.get("selected_action", {})).get("action_type", "")) == "silence" and bool(str(silence_trace.get("silence_reason", "")).strip()), f"trace={silence_trace}"))
    checks.append(_stage4_check("defer_first_class", str(dict(defer_trace.get("selected_action", {})).get("action_type", "")) == "defer_reply" and bool(str(defer_trace.get("defer_reason", "")).strip()), f"trace={defer_trace}"))
    checks.append(_stage4_check("lookup_is_subject_action", str(dict(lookup_trace.get("selected_action", {})).get("action_type", "")) == "external_lookup" and bool(str(lookup_trace.get("lookup_reason", "")).strip()), f"trace={lookup_trace}"))
    checks.append(_stage4_check("recall_prefers_local_memory", str(dict(recall_trace.get("selected_action", {})).get("action_type", "")) in {"reply_once", "reply_multi", "history_refresh"} and not bool(str(recall_trace.get("lookup_reason", "")).strip()), f"trace={recall_trace}"))
    checks.append(_stage4_check("talkativeness_reined_in", int(graph_led.get("expression_budget", reply_probe.get("expression_budget", 0)) or 0) <= 1 and len(reply_bubbles) <= 1, f"budget={graph_led.get('expression_budget', reply_probe.get('expression_budget'))} bubbles={reply_bubbles}"))
    checks.append(_stage4_check("consciousness_ledger_visible", len(ledger_entries) >= 2 and all(bool(str(item.get('entry_type', '')).strip()) for item in ledger_entries[:2]), f"entries={ledger_entries[:3]}"))
    checks.append(_stage4_check("fast_budget", str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0, f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}"))
    checks.append(_stage4_check("recall_budget", str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0, f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}"))
    checks.append(_stage4_check("deep_budget", str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0, f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}"))
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "deliberative-subject-core-stage6",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "silence_trace": silence_trace,
        "defer_trace": defer_trace,
        "lookup_trace": lookup_trace,
        "recall_trace": recall_trace,
        "reply_probe": reply_probe,
        "ledger": ledger,
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
    }


def _evaluate_stage7_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    world_state: dict[str, object],
    short_trace: dict[str, object],
    defer_trace: dict[str, object],
    lookup_trace: dict[str, object],
    recall_trace: dict[str, object],
    world_calibration: dict[str, object],
    ledger: dict[str, object],
    brain_status: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
    roadmap_registry: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    loops = {str(item.get("loop_name", "")): dict(item) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    world_snapshot = dict(world_state.get("world_state", world_state))
    contact_models = dict(world_snapshot.get("contact_models", {}))
    thread_models = dict(world_snapshot.get("thread_models", {}))
    response_expectations = dict(world_snapshot.get("response_expectations", world_state.get("response_expectations", {})))
    short_action = str(dict(short_trace.get("selected_action", {})).get("action_type", ""))
    short_budget = int(short_trace.get("expression_budget_v3", short_trace.get("expression_budget", 0)) or 0)
    defer_action = str(dict(defer_trace.get("selected_action", {})).get("action_type", ""))
    lookup_action = str(dict(lookup_trace.get("selected_action", {})).get("action_type", ""))
    recall_action = str(dict(recall_trace.get("selected_action", {})).get("action_type", ""))
    short_counterfactuals = list(short_trace.get("counterfactual_set", []))
    defer_counterfactuals = list(defer_trace.get("counterfactual_set", []))
    lookup_counterfactuals = list(lookup_trace.get("counterfactual_set", []))
    recall_counterfactuals = list(recall_trace.get("counterfactual_set", []))
    ledger_entries = list(ledger.get("entries", []))
    calibration_snapshot = dict(world_calibration.get("world_state", world_calibration))
    checks.append(
        _stage4_check(
            "stage7_live_mode",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage4_check(
            "world_state_visible",
            bool(contact_models)
            and bool(thread_models)
            and bool(response_expectations)
            and "deep_simulation" in loops,
            f"contacts={list(contact_models)} threads={list(thread_models)} expectations={response_expectations} loops={sorted(loops)}",
        )
    )
    checks.append(
        _stage4_check(
            "short_turn_prefers_brief_action",
            short_action in {"silence", "reply_once", "defer_reply"} and short_budget <= 1,
            f"action={short_action} budget={short_budget} trace={short_trace}",
        )
    )
    checks.append(
        _stage4_check(
            "defer_trace_is_counterfactual_led",
            defer_action == "defer_reply"
            and bool(defer_counterfactuals)
            and bool(str(defer_trace.get("predicted_best_outcome", "")).strip()),
            f"action={defer_action} counterfactuals={defer_counterfactuals}",
        )
    )
    checks.append(
        _stage4_check(
            "lookup_trace_prefers_external_grounding",
            lookup_action == "external_lookup"
            and bool(str(lookup_trace.get("lookup_reason", "")).strip())
            and bool(lookup_counterfactuals),
            f"action={lookup_action} reason={lookup_trace.get('lookup_reason')} counterfactuals={lookup_counterfactuals}",
        )
    )
    checks.append(
        _stage4_check(
            "recall_trace_prefers_local_memory",
            recall_action in {"history_refresh", "reply_once", "reply_multi"}
            and not bool(str(recall_trace.get("lookup_reason", "")).strip())
            and bool(recall_counterfactuals),
            f"action={recall_action} reason={recall_trace.get('lookup_reason')} counterfactuals={recall_counterfactuals}",
        )
    )
    checks.append(
        _stage4_check(
            "counterfactual_precedes_action",
            bool(short_counterfactuals)
            and bool(defer_counterfactuals)
            and bool(lookup_counterfactuals)
            and bool(recall_counterfactuals),
            f"short={short_counterfactuals} defer={defer_counterfactuals} lookup={lookup_counterfactuals} recall={recall_counterfactuals}",
        )
    )
    checks.append(
        _stage4_check(
            "world_calibration_persists",
            bool(calibration_snapshot)
            and (
                bool(world_calibration.get("last_counterfactual_summary"))
                or bool(world_calibration.get("last_post_outcome_calibration"))
            ),
            f"world_snapshot={calibration_snapshot} calibration={world_calibration}",
        )
    )
    checks.append(
        _stage4_check(
            "ledger_carries_world_and_prediction",
            bool(ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("world_snapshot")) for item in ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("counterfactual_set")) for item in ledger_entries),
            f"entries={ledger_entries[:4]}",
        )
    )
    checks.append(
        _stage4_check(
            "roadmap_registry_present",
            all(key in roadmap_registry for key in ("Primary Track", "Secondary Tracks", "Parked Hypotheses", "Deferred Experiments", "Constitutional Constraints")),
            f"keys={sorted(roadmap_registry)}",
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "social-world-model-stage7",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "world_state": world_state,
        "short_trace": short_trace,
        "defer_trace": defer_trace,
        "lookup_trace": lookup_trace,
        "recall_trace": recall_trace,
        "world_calibration": world_calibration,
        "ledger": ledger,
        "roadmap_registry": roadmap_registry,
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
    }


def _evaluate_stage8_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    self_continuity: dict[str, object],
    goal_state: dict[str, object],
    goal_trace: dict[str, object],
    action_trace: dict[str, object],
    continuity_defense_trace: dict[str, object],
    reply_probe: dict[str, object],
    ledger: dict[str, object],
    brain_status: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
    roadmap_registry: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    autobio = dict(self_continuity.get("autobiographical_state", {}))
    goals = dict(goal_state)
    active_goals = list(goals.get("active_goals", []))
    action_budget = int(action_trace.get("expression_budget_v4", action_trace.get("expression_budget_v3", action_trace.get("expression_budget", 0))) or 0)
    continuity_budget = int(
        continuity_defense_trace.get(
            "expression_budget_v4",
            continuity_defense_trace.get("expression_budget_v3", continuity_defense_trace.get("expression_budget", 0)),
        )
        or 0
    )
    graph_led = dict(reply_probe.get("graph_led", {})) if isinstance(reply_probe.get("graph_led", {}), dict) else {}
    reply_bubbles = list(graph_led.get("bubbles", [])) or list(reply_probe.get("bubbles", []))
    ledger_entries = list(ledger.get("entries", []))
    checks.append(_stage4_check("stage8_live_mode", str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain", f"status={health.get('status')} mode={mode_transition.get('mode')}"))
    checks.append(
        _stage4_check(
            "autobiographical_continuity_present",
            bool(str(autobio.get("identity_arc", "")).strip()) and bool(str(autobio.get("current_chapter", "")).strip()) and bool(list(self_continuity.get("turning_points", [])) or list(self_continuity.get("recent_changes", []))),
            f"autobio={autobio}",
        )
    )
    checks.append(
        _stage4_check(
            "goal_state_persists",
            bool(active_goals) and bool(list(goal_trace.get("goal_commitments", []))) and bool(list(goal_trace.get("next_goal_windows", []))),
            f"goals={active_goals}",
        )
    )
    checks.append(
        _stage4_check(
            "identity_and_goal_enter_action_selection",
            bool(action_trace.get("goal_alignment", {}))
            and bool(action_trace.get("identity_consistency", {}))
            and bool(str(action_trace.get("chapter_relevance", "")).strip())
            and bool(str(action_trace.get("self_narrative_hint", "")).strip()),
            f"trace={action_trace}",
        )
    )
    checks.append(
        _stage4_check(
            "continuity_defense_reads_same_self_history",
            bool(continuity_defense_trace.get("goal_alignment", {}))
            and bool(continuity_defense_trace.get("identity_consistency", {}))
            and bool(continuity_defense_trace.get("autobiographical_state", {})),
            f"trace={continuity_defense_trace}",
        )
    )
    checks.append(
        _stage4_check(
            "ordinary_chat_stays_implicit",
            action_budget <= 1 and len(reply_bubbles) <= 1,
            f"budget={action_budget} bubbles={reply_bubbles}",
        )
    )
    checks.append(
        _stage4_check(
            "consciousness_ledger_carries_autobio_and_goals",
            bool(ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("autobiographical_snapshot")) for item in ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("goal_snapshot")) for item in ledger_entries),
            f"entries={ledger_entries[:4]}",
        )
    )
    checks.append(
        _stage4_check(
            "roadmap_registry_updated",
            "Primary Track" in roadmap_registry and "identity/goal-led deliberation" in str(roadmap_registry.get("Primary Track", "")),
            f"roadmap={roadmap_registry}",
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "fast_budget",
            str(fast_benchmark.get("last_tier", "")) == "fast" and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"tier={fast_benchmark.get('last_tier')} max_ms={dict(fast_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    checks.append(
        _stage4_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "stage": "autobiographical-self-stage8",
        "status": status,
        "checks": checks,
        "failures": failures,
        "blockers": blockers,
        "warnings": warnings,
        "self_continuity": self_continuity,
        "goal_state": goal_state,
        "goal_trace": goal_trace,
        "action_trace": action_trace,
        "continuity_defense_trace": continuity_defense_trace,
        "reply_probe": reply_probe,
        "ledger": ledger,
        "roadmap_registry": roadmap_registry,
        "cache_hit_ratio": float(dict(brain_status.get("cache", {})).get("hit_ratio", 0.0) or 0.0),
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
    }


def command_init_db(config_path: str | None) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    print(json.dumps({"db_path": str(config.runtime.db_path), "status": "ok"}, ensure_ascii=False, indent=2))
    return 0


def command_cycle(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    result = daemon.run_cycle()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def command_daemon(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    daemon.run_forever()
    return 0


def command_jobs(config_path: str | None, limit: int) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    print(json.dumps(store.list_jobs(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_followups(config_path: str | None, limit: int) -> int:
    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    created = store.schedule_due_followups(config.autonomy.proactive_after_hours, limit=limit)
    print(json.dumps({"created_job_ids": created}, ensure_ascii=False, indent=2))
    return 0


def command_promote_memory(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.promote_ready_candidates(limit=daemon.config.memory.promote_batch_size), ensure_ascii=False, indent=2))
    return 0


def command_backfill_archive(config_path: str | None, db_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.backfill_archive(db_path=db_path, dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_backfill_mind_graph(config_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.backfill_mind_graph(dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_dream_cycle(config_path: str | None, sample_size: int, *, seed: str | None, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_dream_cycle(sample_size=sample_size, seed=seed, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_think_cycle(config_path: str | None, sample_size: int, *, seed: str | None, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_think_cycle(sample_size=sample_size, seed=seed, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_reflect_cycle(config_path: str | None, window_hours: float, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.run_reflect_cycle(window_hours=window_hours, dry_run=dry_run),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_initiative_cycle(config_path: str | None, *, dry_run: bool) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.run_initiative_cycle(dry_run=dry_run), ensure_ascii=False, indent=2))
    return 0


def command_show_callbacks(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_callback_candidates(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_show_thoughts(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_thoughts(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_show_initiatives(config_path: str | None, limit: int) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.list_initiative_candidates(limit=limit), ensure_ascii=False, indent=2))
    return 0


def command_show_brain_status(config_path: str | None) -> int:
    payload, _transport = _brain_status_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_self_model(config_path: str | None) -> int:
    payload, _transport = _self_model_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_autobiographical_state(config_path: str | None) -> int:
    payload, _transport = _autobiographical_state_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_goal_state(config_path: str | None) -> int:
    payload, _transport = _goal_state_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_engineering_state(config_path: str | None) -> int:
    payload, _transport = _engineering_state_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_action_calibration(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None,
    scenario_bucket: str | None,
    limit: int,
) -> int:
    payload, _transport = _action_calibration_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        scenario_bucket=scenario_bucket,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_policy_candidates(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _policy_candidates_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_promoted_policies(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _promoted_policies_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_rollback_policy(config_path: str | None, *, policy_id: str, reason: str) -> int:
    payload, _transport = _rollback_policy_payload(config_path, policy_id=policy_id, reason=reason)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_policy_influence(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
) -> int:
    payload, _transport = _policy_influence_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_online_canary(config_path: str | None, *, limit: int) -> int:
    payload, _transport = _online_canary_payload(config_path, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_blackbox_metrics(
    config_path: str | None,
    *,
    window_hours: float,
    thread_key: str | None,
    chat_name: str | None,
    channel: str | None,
    limit: int,
) -> int:
    payload, _transport = _blackbox_metrics_payload(
        config_path,
        window_hours=window_hours,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_blackbox_scorecard(config_path: str | None, *, since_hours: float, limit: int) -> int:
    payload, _transport = _blackbox_scorecard_payload(config_path, since_hours=since_hours, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_canary_decision(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
) -> int:
    payload, _transport = _canary_decision_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_set_canary_rollback(config_path: str | None, *, enabled: bool, reason: str) -> int:
    payload, _transport = _canary_rollback_payload(config_path, enabled=enabled, reason=reason)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_replay_live_artifacts(config_path: str | None, *, since_hours: float, limit: int, artifact_dir: str | None) -> int:
    payload, _transport = _replay_live_artifacts_payload(
        config_path,
        since_hours=since_hours,
        limit=limit,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_export_blind_packets(config_path: str | None, *, since_hours: float, limit: int, artifact_dir: str | None) -> int:
    payload, _transport = _export_blind_packets_payload(
        config_path,
        since_hours=since_hours,
        limit=limit,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_run_blackbox_soak(
    config_path: str | None,
    *,
    since_hours: float,
    limit: int,
    artifact_dir: str | None,
    persist: bool,
) -> int:
    payload, _transport = _run_blackbox_soak_payload(
        config_path,
        since_hours=since_hours,
        limit=limit,
        artifact_dir=artifact_dir,
        persist=persist,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_outcome_history(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None,
    limit: int,
) -> int:
    payload, _transport = _outcome_history_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_action_prediction_error(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    action_type: str | None,
    limit: int,
) -> int:
    payload, _transport = _prediction_error_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        action_type=action_type,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_self_model(config_path: str | None) -> int:
    self_model, _ = _self_model_payload(config_path)
    brain_status, _ = _brain_status_payload(config_path)
    operator_status, _ = _operator_status_payload(config_path)
    stream_status, _ = _stream_status_payload(config_path)
    payload = {
        "self_model": self_model,
        "brain_status": brain_status,
        "operator_status": operator_status,
        "stream_status": stream_status,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_self_continuity(config_path: str | None) -> int:
    payload, _transport = _self_continuity_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_goal_arbitration(config_path: str | None) -> int:
    payload, _transport = _goal_arbitration_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_set_brain_mode(config_path: str | None, *, mode: str, note: str) -> int:
    payload, _transport = _brain_mode_payload(config_path, mode=mode, note=note)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_run_self_revision(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    corrections: list[str],
    apply_patch: bool,
) -> int:
    payload, _transport = _self_revision_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        corrections=corrections,
        apply_patch=apply_patch,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_initiative_probe(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
) -> int:
    payload, _transport = _initiative_probe_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_operator_probe(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _operator_probe_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_run_operator_cycle(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    reason: str,
) -> int:
    payload, _transport = _operator_cycle_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        reason=reason,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_initiative_status(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _initiative_status_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_dispatch_initiatives(
    config_path: str | None,
    *,
    process_jobs: bool,
    limit: int | None,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.dispatch_initiatives(process_jobs=process_jobs, limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_inspect_mind(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
) -> int:
    _health, transport = _health_payload(config_path)
    live_only = transport == "live_http"
    packet, _transport = _inspect_mind_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


def command_ingest_image(
    config_path: str | None,
    *,
    path: str,
    note: str | None,
    source: str,
    tags: list[str],
    channel: str,
    thread_key: str | None,
    chat_name: str | None,
    sync: bool,
) -> int:
    payload, _transport = _ingest_image_payload(
        config_path,
        path=path,
        note=note,
        source=source,
        tags=tags,
        channel=channel,
        thread_key=thread_key,
        chat_name=chat_name,
        sync=sync,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_visual_recall(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _trace_visual_recall_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_affect_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _affect_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_intent_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
) -> int:
    payload, _transport = _intent_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_action_market(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
) -> int:
    payload, _transport = _action_market_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_fast_path_metrics(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _fast_path_metrics_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_predictive_continuity(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _predictive_continuity_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_scene_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _scene_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_predicted_branches(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _predicted_branches_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_scene_compression(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _scene_compression_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_situational_field(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _situational_field_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_visual_field(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _visual_field_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_inquiry_shaping(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _inquiry_shaping_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_task_world(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    include_inactive: bool,
) -> int:
    payload, _transport = _task_world_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        include_inactive=include_inactive,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_world_object(
    config_path: str | None,
    *,
    object_id: str,
) -> int:
    payload, _transport = _world_object_payload(
        config_path,
        object_id=object_id,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_thread_object_links(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _thread_object_links_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_continuity_budget(
    config_path: str | None,
    *,
    channel: str,
) -> int:
    payload, _transport = _continuity_budget_payload(
        config_path,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_dense_working_set(
    config_path: str | None,
    *,
    channel: str,
) -> int:
    payload, _transport = _dense_working_set_payload(
        config_path,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_thread_pulse(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _thread_pulse_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_attention_frontier(
    config_path: str | None,
    *,
    channel: str | None,
    limit: int,
    include_stale: bool,
) -> int:
    payload, _transport = _attention_frontier_payload(
        config_path,
        channel=channel,
        limit=limit,
        include_stale=include_stale,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_wake_reasons(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _wake_reasons_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_thread_warmth(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _thread_warmth_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_open_loops(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
) -> int:
    payload, _transport = _open_loops_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        include_inactive=include_inactive,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_commitments(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
) -> int:
    payload, _transport = _commitments_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        include_inactive=include_inactive,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_resume_candidate(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    include_inactive: bool,
) -> int:
    payload, _transport = _resume_candidate_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        include_inactive=include_inactive,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_world_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _world_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_world_coupling(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    include_inactive: bool,
) -> int:
    payload, _transport = _world_coupling_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        include_inactive=include_inactive,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_action_selection(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
) -> int:
    payload, _transport = _trace_action_selection_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_reflex_routing(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
) -> int:
    payload, _transport = _trace_reflex_routing_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_counterfactual(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
    limit: int,
) -> int:
    payload, _transport = _counterfactual_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_world_calibration(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _world_calibration_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_deliberation_ledger(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _deliberation_ledger_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_drive_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _drive_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_initiative_market(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    payload, _transport = _initiative_market_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_resistance(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    query: str,
) -> int:
    payload, _transport = _trace_resistance_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=query,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage3(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage3_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _evaluate_stage9_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    conservative_probe: dict[str, object],
    adaptive_probe: dict[str, object],
    adaptive_status: dict[str, object],
    hard_gate_probe: dict[str, object],
    brain_status: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    checks.append(
        _stage4_check(
            "stage9_live_mode",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage4_check(
            "conservative_probe_available",
            str(conservative_probe.get("gate_mode", "")).strip() == "conservative" and bool(str(conservative_probe.get("gate_level", "")).strip()),
            f"gate_mode={conservative_probe.get('gate_mode')} gate_level={conservative_probe.get('gate_level')}",
        )
    )
    checks.append(
        _stage4_check(
            "adaptive_probe_exposes_soft_gate",
            str(adaptive_probe.get("gate_mode", "")).strip() == "adaptive"
            and bool(str(adaptive_probe.get("gate_level", "")).strip())
            and "soft_gate_score" in adaptive_probe
            and bool(dict(adaptive_probe.get("soft_gate_components", {}))),
            (
                f"gate_mode={adaptive_probe.get('gate_mode')} gate_level={adaptive_probe.get('gate_level')} "
                f"soft_gate_score={adaptive_probe.get('soft_gate_score')} components={adaptive_probe.get('soft_gate_components')}"
            ),
        )
    )
    checks.append(
        _stage4_check(
            "adaptive_override_signal_visible",
            "override_eligible" in adaptive_probe and bool(str(adaptive_probe.get("recommended_action", "")).strip()),
            f"override_eligible={adaptive_probe.get('override_eligible')} recommended_action={adaptive_probe.get('recommended_action')}",
        )
    )
    checks.append(
        _stage4_check(
            "initiative_status_observable",
            "gate_level_summary" in adaptive_status
            and "hard_block_reason_counts" in adaptive_status
            and "soft_block_reason_counts" in adaptive_status
            and "override_applied_count" in adaptive_status,
            (
                f"gate_level_summary={adaptive_status.get('gate_level_summary')} "
                f"hard_block_reason_counts={adaptive_status.get('hard_block_reason_counts')} "
                f"soft_block_reason_counts={adaptive_status.get('soft_block_reason_counts')} "
                f"override_applied_count={adaptive_status.get('override_applied_count')}"
            ),
        )
    )
    checks.append(
        _stage4_check(
            "hard_gate_cannot_be_overridden",
            str(hard_gate_probe.get("gate_level", "")).strip() == "hard_block"
            and not bool(hard_gate_probe.get("allowed", False))
            and "initiative_probe_disabled" in list(hard_gate_probe.get("hard_block_reasons", [])),
            f"hard_gate_probe={hard_gate_probe}",
        )
    )
    checks.append(
        _stage4_check(
            "soft_block_is_explainable",
            str(adaptive_probe.get("gate_level", "")).strip() != "soft_block"
            or (
                bool(str(adaptive_probe.get("blocked_reason_code", "")).strip())
                and bool(dict(adaptive_probe.get("soft_gate_components", {})))
            ),
            (
                f"gate_level={adaptive_probe.get('gate_level')} blocked_reason_code={adaptive_probe.get('blocked_reason_code')} "
                f"soft_gate_components={adaptive_probe.get('soft_gate_components')}"
            ),
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "brain_mode_stays_full_brain",
            str(brain_status.get("mode", "")).strip() == "full_brain",
            f"brain_mode={brain_status.get('mode')}",
            severity="warning",
        )
    )
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass" if not failures and not blockers and not warnings else "fail" if failures else "blocked" if blockers else "warn"
    return {
        "status": status,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "blockers": blockers,
        "summary": {
            "adaptive_gate_level": adaptive_probe.get("gate_level"),
            "adaptive_soft_gate_score": adaptive_probe.get("soft_gate_score"),
            "override_eligible": adaptive_probe.get("override_eligible"),
            "override_applied_count": adaptive_status.get("override_applied_count"),
        },
    }


def _stage10_axis_score(*, primary: bool, secondary: bool = False) -> float:
    if primary and secondary:
        return 2.0
    if primary:
        return 1.4
    return 0.0


def _evaluate_stage10_acceptance(
    *,
    health: dict[str, object],
    mode_transition: dict[str, object],
    engineering_state: dict[str, object],
    goal_state: dict[str, object],
    operator_probe: dict[str, object],
    ledger: dict[str, object],
    usage_ledger: dict[str, object],
    provider_status: dict[str, object],
    routing: dict[str, object],
    reply_probe: dict[str, object],
    brain_status: dict[str, object],
    fast_benchmark: dict[str, object],
    recall_benchmark: dict[str, object],
    deep_benchmark: dict[str, object],
    roadmap_registry: dict[str, object],
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    provider_state = dict(engineering_state.get("provider_state", {}))
    routing_state = dict(engineering_state.get("routing_state", {}))
    usage_state = dict(engineering_state.get("usage_state", {}))
    cache_state = dict(engineering_state.get("cache_state", {}))
    operator_state = dict(engineering_state.get("operator_state", {}))
    active_deficits = [str(item).strip() for item in engineering_state.get("active_deficits", []) if str(item).strip()]
    engineering_goal_types = {"cost_discipline", "routing_resilience", "cache_warmth", "expression_calibration"}
    active_goals = [dict(item) for item in goal_state.get("active_goals", []) if isinstance(item, dict)]
    goal_types = {str(item.get("goal_type", "") or "").strip() for item in active_goals}
    goal_progress = dict(goal_state.get("goal_progress", {}))
    pursuit_bias = dict(goal_state.get("pursuit_bias", {}))
    abandonment_cost = dict(goal_state.get("abandonment_cost", {}))
    next_goal_windows = [dict(item) for item in goal_state.get("next_goal_windows", []) if isinstance(item, dict)]
    goal_conflicts = [dict(item) for item in goal_state.get("goal_conflicts", []) if isinstance(item, dict)]
    ledger_entries = list(ledger.get("entries", []))
    usage_items = list(usage_ledger.get("items", []))
    provider_names = set(dict(provider_status.get("providers", {})))
    routing_table = dict(routing.get("routing", {}))
    required_tasks = {"reply", "recall_reconstruct", "initiative_probe", "deep_simulation", "self_model_observe", "operator_plan"}
    budget_guard = dict(operator_probe.get("budget_guard", {}))
    trigger_delta = dict(operator_probe.get("trigger_delta", {}))
    speech_actions = {"reply_once", "reply_multi", "defer_reply", "silence", "ignore"}
    probe_candidates = []
    for key in ("graph_led", "hybrid", "legacy"):
        candidate = dict(reply_probe.get(key, {}))
        if candidate:
            probe_candidates.append(candidate)
    probe_candidates.append(
        {
            "selected_action": dict(reply_probe.get("selected_action", {})),
            "expression_budget": reply_probe.get("expression_budget", 0),
            "reply_plan": dict(reply_probe.get("reply_plan", {})),
        }
    )
    reply_candidates = []
    for candidate in probe_candidates:
        candidate_reply_plan = dict(candidate.get("reply_plan", {}))
        candidate_bubble_target = int(dict(candidate_reply_plan.get("turn_plan", {})).get("bubble_target", 0) or 0)
        candidate_budget = candidate_bubble_target or int(candidate.get("expression_budget", reply_probe.get("expression_budget", 0)) or 0)
        candidate_action_type = str(dict(candidate.get("selected_action", {})).get("action_type", "") or "")
        if bool(str(candidate_reply_plan.get("text", "")).strip()) or bool(list(candidate_reply_plan.get("bubbles", []))):
            reply_candidates.append(
                {
                    "candidate": candidate,
                    "action_type": candidate_action_type,
                    "budget": candidate_budget,
                    "is_speech": candidate_action_type in speech_actions,
                }
            )
    reply_candidate = dict(reply_probe.get("graph_led", {}))
    if reply_candidates:
        ranked = sorted(
            reply_candidates,
            key=lambda item: (
                0 if item["is_speech"] else 1,
                int(item["budget"] or 0),
            ),
        )
        reply_candidate = dict(ranked[0]["candidate"])
    reply_plan = dict(reply_candidate.get("reply_plan", {}))
    reply_action_type = str(dict(reply_candidate.get("selected_action", {})).get("action_type", "") or "")
    reply_plan_budget = int(dict(reply_plan.get("turn_plan", {})).get("bubble_target", 0) or 0)
    reply_budget = reply_plan_budget or int(reply_candidate.get("expression_budget", reply_probe.get("expression_budget", 0)) or 0)

    checks.append(
        _stage4_check(
            "stage10_live_mode",
            str(health.get("status", "")) == "ok" and str(mode_transition.get("mode", "")) == "full_brain",
            f"status={health.get('status')} mode={mode_transition.get('mode')}",
        )
    )
    checks.append(
        _stage4_check(
            "engineering_state_visible",
            bool(provider_state)
            and bool(routing_state)
            and bool(usage_state)
            and bool(cache_state)
            and bool(operator_state)
            and "engineering_confidence" in engineering_state
            and "budget_pressure" in engineering_state,
            f"provider={provider_state} routing={routing_state} usage={usage_state} cache={cache_state} operator={operator_state}",
        )
    )
    checks.append(
        _stage4_check(
            "provider_routing_usage_visible",
            bool(dict(provider_status.get("providers", {})))
            and bool(dict(provider_status.get("lanes", {})))
            and required_tasks.issubset(set(routing_table))
            and isinstance(usage_ledger.get("summary", {}), dict)
            and isinstance(usage_items, list),
            f"providers={provider_status.get('providers')} routing={routing_table} usage_summary={usage_ledger.get('summary')}",
        )
    )
    checks.append(
        _stage4_check(
            "engineering_deficits_specific",
            bool({"provider_fallback_unready", "usage_visibility_cold", "cache_reuse_weak", "operator_overplanning_risk", "expression_calibration_gap"} & set(active_deficits)),
            f"active_deficits={active_deficits}",
        )
    )
    engineering_goal_ids = {
        str(item.get("goal_id", "") or "").strip()
        for item in active_goals
        if str(item.get("goal_type", "") or "").strip() in engineering_goal_types
    }
    checks.append(
        _stage4_check(
            "engineering_goals_enter_arbitration",
            bool(goal_types & engineering_goal_types)
            and any(goal_id in goal_progress for goal_id in engineering_goal_ids)
            and any(goal_id in pursuit_bias for goal_id in engineering_goal_ids)
            and any(goal_id in abandonment_cost for goal_id in engineering_goal_ids)
            and any(str(item.get("goal_id", "") or "").strip() in engineering_goal_ids for item in next_goal_windows)
            and any("reply path" in str(item.get("summary", "")).lower() or "relationship continuity" in str(item.get("summary", "")).lower() for item in goal_conflicts),
            f"goal_types={sorted(goal_types)} conflicts={goal_conflicts} next_windows={next_goal_windows}",
        )
    )
    checks.append(
        _stage4_check(
            "operator_is_delta_gated",
            (bool(trigger_delta) and str(operator_probe.get("status", "")).strip() in {"planned", "reviewed", "applied", ""})
            or (
                str(operator_probe.get("status", "")).strip() == "skipped"
                and str(operator_probe.get("blocked_reason", "")).strip() == "no_meaningful_delta"
            ),
            f"status={operator_probe.get('status')} blocked_reason={operator_probe.get('blocked_reason')} trigger_delta={trigger_delta}",
        )
    )
    checks.append(
        _stage4_check(
            "operator_plan_explains_trigger_and_budget_guard",
            (bool(trigger_delta) or str(operator_probe.get("blocked_reason", "")).strip() == "no_meaningful_delta")
            and bool(list(operator_probe.get("source_goal_ids", [])))
            and bool(dict(operator_probe.get("expected_state_gain", {})))
            and str(budget_guard.get("live_repo_writes", "")).strip() == "forbidden"
            and str(budget_guard.get("fabric_bypass", "")).strip() == "forbidden"
            and str(budget_guard.get("background_plans", "")).strip() == "delta_only",
            f"operator_probe={operator_probe}",
        )
    )
    checks.append(
        _stage4_check(
            "consciousness_ledger_carries_engineering_trace",
            bool(ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("engineering_snapshot")) for item in ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("engineering_goal_snapshot")) for item in ledger_entries)
            and any(bool(dict(item.get("payload", {})).get("trigger_delta")) for item in ledger_entries),
            f"entries={ledger_entries[:4]}",
        )
    )
    checks.append(
        _stage4_check(
            "usage_ledger_records_stage10_tasks",
            any(str(item.get("task_type", "")).strip() in {"self_model_observe", "operator_plan"} for item in usage_items),
            f"usage_items={usage_items[:4]}",
        )
    )
    checks.append(
        _stage4_check(
            "no_fabric_bypass",
            str(budget_guard.get("fabric_bypass", "")).strip() == "forbidden"
            and all(str(item.get("provider", "")).strip() in provider_names for item in usage_items if str(item.get("provider", "")).strip()),
            f"providers={provider_names} usage_items={usage_items[:4]} budget_guard={budget_guard}",
        )
    )
    checks.append(
        _stage4_check(
            "ordinary_reply_path_not_regressed",
            (
                reply_action_type in speech_actions
                or bool(str(reply_plan.get("text", "")).strip())
                or bool(list(reply_plan.get("bubbles", [])))
            )
            and reply_budget <= 1
            and float(dict(fast_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 350.0,
            f"reply_probe={reply_probe} fast={fast_benchmark}",
        )
    )
    checks.append(
        _stage4_check(
            "roadmap_registry_present",
            all(key in roadmap_registry for key in ("Primary Track", "Secondary Tracks", "Parked Hypotheses", "Deferred Experiments", "Constitutional Constraints")),
            f"keys={sorted(roadmap_registry)}",
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "recall_budget",
            str(recall_benchmark.get("last_tier", "")) == "recall" and float(dict(recall_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 1200.0,
            f"tier={recall_benchmark.get('last_tier')} max_ms={dict(recall_benchmark.get('timings_ms', {})).get('max')}",
            severity="warning",
        )
    )
    checks.append(
        _stage4_check(
            "deep_budget",
            str(deep_benchmark.get("last_tier", "")) == "deep_recall" and float(dict(deep_benchmark.get("timings_ms", {})).get("max", 999999.0)) <= 2500.0,
            f"tier={deep_benchmark.get('last_tier')} max_ms={dict(deep_benchmark.get('timings_ms', {})).get('max')}",
            severity="warning",
        )
    )

    scenario_benchmarks = [
        {
            "name": "provider_degraded_and_ledger_cold",
            "score": 10.0
            if (
                bool(dict(provider_status.get("providers", {})).get("responses"))
                and not bool(dict(dict(provider_status.get("providers", {})).get("responses", {})).get("available", False))
                and "cost_discipline" in goal_types
                and "routing_resilience" in goal_types
                and bool(usage_state)
            )
            else 4.0,
        },
        {
            "name": "stable_idle_no_delta",
            "score": 10.0 if str(budget_guard.get("background_plans", "")).strip() == "delta_only" else 4.0,
        },
        {
            "name": "cache_cold_with_relationship_pressure",
            "score": 10.0
            if (
                bool(cache_state)
                and "cache_warmth" in goal_types
                and any(str(item.get("goal_type", "")).strip() == "identity_maintenance" for item in active_goals)
            )
            else 4.0,
        },
    ]
    scenario_average = round(
        sum(float(item.get("score", 0.0) or 0.0) for item in scenario_benchmarks) / max(1, len(scenario_benchmarks)),
        2,
    )
    checks_by_name = {str(item.get("name", "")): bool(item.get("ok", False)) for item in checks}
    axes = [
        {
            "name": "self_observation",
            "score": _stage10_axis_score(
                primary=checks_by_name.get("engineering_state_visible", False),
                secondary=checks_by_name.get("provider_routing_usage_visible", False),
            ),
        },
        {
            "name": "diagnostic_specificity",
            "score": _stage10_axis_score(
                primary=checks_by_name.get("engineering_deficits_specific", False),
                secondary=bool(active_deficits),
            ),
        },
        {
            "name": "decision_integration",
            "score": _stage10_axis_score(
                primary=checks_by_name.get("engineering_goals_enter_arbitration", False),
                secondary=checks_by_name.get("ordinary_reply_path_not_regressed", False),
            ),
        },
        {
            "name": "bounded_repair_discipline",
            "score": _stage10_axis_score(
                primary=checks_by_name.get("operator_is_delta_gated", False),
                secondary=checks_by_name.get("operator_plan_explains_trigger_and_budget_guard", False) and checks_by_name.get("no_fabric_bypass", False),
            ),
        },
        {
            "name": "cost_self_regulation",
            "score": _stage10_axis_score(
                primary=checks_by_name.get("usage_ledger_records_stage10_tasks", False),
                secondary=scenario_average >= 7.0,
            ),
        },
    ]
    total_score = round(sum(float(axis.get("score", 0.0) or 0.0) for axis in axes), 2)
    failures = [check for check in checks if not check["ok"] and check.get("severity") == "failure"]
    blockers = [check for check in checks if not check["ok"] and check.get("severity") == "blocker"]
    warnings = [check for check in checks if not check["ok"] and check.get("severity") == "warning"]
    status = "pass"
    if failures or blockers or scenario_average < 7.0 or total_score < 7.0 or any(float(axis.get("score", 0.0) or 0.0) < 1.2 for axis in axes):
        status = "fail" if failures else "blocked" if blockers else "fail"
    return {
        "status": status,
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
        "blockers": blockers,
        "scorecard": {
            "baseline": 4.8,
            "target": 7.0,
            "axes": axes,
            "total": total_score,
        },
        "scenarios": scenario_benchmarks,
        "scenario_average": scenario_average,
        "engineering_state": engineering_state,
        "goal_state": goal_state,
        "operator_probe": operator_probe,
        "usage_ledger": usage_ledger,
        "provider_status": provider_status,
        "routing": routing,
        "reply_latency_budgets": {
            "fast": dict(fast_benchmark.get("timings_ms", {})),
            "recall": dict(recall_benchmark.get("timings_ms", {})),
            "deep_recall": dict(deep_benchmark.get("timings_ms", {})),
        },
    }


def command_accept_stage4(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage4_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage5(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage5_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage6(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage6_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage7(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage7_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage8(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage8_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage9(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage9_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def _evaluate_stage12_acceptance(
    *,
    health: dict[str, Any],
    thread_key: str,
    chat_name: str,
    reply_result: dict[str, Any],
    defer_result: dict[str, Any],
    silence_result: dict[str, Any],
    thread_row: dict[str, Any],
    appraisal_rows: list[dict[str, Any]],
    usage_rows: list[dict[str, Any]],
    subject_after_reload: dict[str, Any],
    helper_contracts: dict[str, Any],
    roadmap_registry: dict[str, Any],
) -> dict[str, Any]:
    latest_appraisal = dict(appraisal_rows[0]) if appraisal_rows else {}
    latest_metadata = dict(latest_appraisal.get("metadata", {})) if isinstance(latest_appraisal.get("metadata", {}), dict) else {}
    outcome_memory = dict(subject_after_reload.get("outcome_memory", {}))
    last_calibration = dict(subject_after_reload.get("world_state", {}).get("last_post_outcome_calibration", {}))
    reply_thread_key = str(reply_result.get("thread_key", "") or "").strip()
    appraisal_thread_key = str(latest_metadata.get("thread_key", "") or "").strip()
    checks = {
        "health_ok": str(health.get("status", "")).strip() == "ok",
        "canonical_wechat_identity": reply_thread_key.startswith("wechat:")
        and appraisal_thread_key.startswith("wechat:")
        and str(thread_key).startswith("wechat:"),
        "ordinary_reply_appraised": bool(reply_result.get("outcome_appraisal")) and bool(appraisal_rows),
        "defer_reply_appraised": bool(defer_result.get("outcome_appraisal")),
        "silence_appraised": bool(silence_result.get("outcome_appraisal")),
        "action_local_usage_visible": bool(latest_metadata.get("usage_evidence_refs"))
        and all(str(ref).startswith("usage:") for ref in list(latest_metadata.get("usage_evidence_refs", []))),
        "appraisal_provenance_visible": bool(latest_metadata.get("event_row_id"))
        and bool(str(latest_metadata.get("message_id", "") or "").strip())
        and bool(str(appraisal_thread_key).strip())
        and bool(str(latest_appraisal.get("action_ref", "") or "").strip()),
        "calibration_survives_reload": bool(outcome_memory.get("last_action_ref")) and bool(last_calibration.get("action_ref")),
        "helper_artifact_path_contract": str(helper_contracts.get("artifact_path", "")).startswith("/mnt/d/"),
        "wsl_fallback_contract": len(list(helper_contracts.get("wsl_fallback_candidates", []))) >= 2,
        "action_market_first_preserved": str(reply_result.get("selected_action", {}).get("action_type", "") or "") in {
            "silence",
            "defer_reply",
            "reply_once",
            "reply_multi",
            "external_lookup",
            "history_refresh",
            "visual_recall",
            "proactive_ping",
            "push_back",
            "counter_offer",
            "continuity_defense",
            "operator_self_fix",
        },
    }
    passed = sum(1 for value in checks.values() if value)
    total = len(checks)
    score = round((passed / max(1, total)) * 10.0, 2)
    status = "pass" if passed == total else "fail"
    return {
        "status": status,
        "stage": "outcome-closure-and-canonical-identity-stage12",
        "score": score,
        "checks": checks,
        "latest_appraisal": latest_appraisal,
        "usage_rows": usage_rows[:6],
        "subject_after_reload": {
            "outcome_memory": outcome_memory,
            "last_post_outcome_calibration": last_calibration,
        },
        "roadmap_registry": roadmap_registry,
    }


def _accept_stage12_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage12",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage12(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _evaluate_stage13_acceptance(
    *,
    health: dict[str, Any],
    thread_key: str,
    chat_name: str,
    calibration_rows: list[dict[str, Any]],
    before_rows: list[dict[str, Any]],
    outcome_history: list[dict[str, Any]],
    prediction_trace: dict[str, Any],
    subject_after_reload: dict[str, Any],
    ranking_fixture: dict[str, Any],
) -> dict[str, Any]:
    latest_row = dict(calibration_rows[0]) if calibration_rows else {}
    latest_world = dict(subject_after_reload.get("world_state", {}))
    summary = dict(prediction_trace.get("summary", {}))
    strongest_actions = list(dict(latest_world.get("action_calibration_summary", {})).get("strongest_actions", []))
    before_by_key = {
        (str(item.get("action_type", "") or ""), str(item.get("scenario_bucket", "") or "")): dict(item)
        for item in before_rows
    }
    confidence_decreased = False
    for row in calibration_rows:
        key = (str(row.get("action_type", "") or ""), str(row.get("scenario_bucket", "") or ""))
        if key in before_by_key and float(row.get("confidence", 0.0) or 0.0) < float(before_by_key[key].get("confidence", 0.0) or 0.0):
            confidence_decreased = True
            break
    if not confidence_decreased:
        errors = [abs(float(item.get("response_quality", 0.0) or 0.0)) for item in list(latest_row.get("metadata", {}).get("recent_errors", []))]
        if len(errors) >= 2 and errors[-1] > errors[0]:
            confidence_decreased = True
    after_market = list(ranking_fixture.get("after_market", []))
    ranking_changed = str(ranking_fixture.get("before_top_action", "") or "") != str(ranking_fixture.get("after_top_action", "") or "")
    overlay_visible = any(abs(float(item.get("empirical_overlay_delta", 0.0) or 0.0)) > 0.0 for item in after_market)
    support_changed = any(
        int(item.get("support_count", 0) or 0)
        > int(before_by_key.get((str(item.get("action_type", "") or ""), str(item.get("scenario_bucket", "") or "")), {}).get("support_count", 0) or 0)
        for item in calibration_rows
    )
    negative_supported = any(float(item.get("relational_delta", 0.0) or 0.0) < 0.0 or float(item.get("identity_delta", 0.0) or 0.0) < 0.0 for item in outcome_history)
    checks = {
        "health_ok": str(health.get("status", "")).strip() == "ok",
        "canonical_wechat_identity": str(thread_key).startswith("wechat:"),
        "calibration_rows_persist": bool(calibration_rows) and bool(latest_row.get("last_updated_at")),
        "support_counts_change": support_changed,
        "confidence_can_decrease": confidence_decreased,
        "negative_outcomes_representable": negative_supported,
        "prediction_trace_visible": bool(prediction_trace.get("comparisons")) and "response_quality_mae" in summary,
        "recent_history_preserved": bool(latest_world.get("recent_outcome_history")) and bool(latest_world.get("recent_prediction_errors")),
        "summary_visible": bool(strongest_actions),
        "empirical_overlay_visible": overlay_visible,
        "ranking_can_change": ranking_changed,
        "action_market_first_preserved": bool(after_market),
    }
    score = round((sum(1.0 for value in checks.values() if value) / max(1, len(checks))) * 10.0, 2)
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "score": score,
        "thread_key": thread_key,
        "chat_name": chat_name,
        "checks": checks,
        "latest_calibration": latest_row,
        "prediction_summary": summary,
    }


def _evaluate_stage14_acceptance(
    *,
    health: dict[str, Any],
    primary_report: dict[str, Any],
    secondary_report: dict[str, Any],
    live_before: dict[str, int],
    live_after: dict[str, int],
) -> dict[str, Any]:
    primary_aggregate = dict(primary_report.get("aggregate_metrics", {}))
    secondary_aggregate = dict(secondary_report.get("aggregate_metrics", {}))
    fixtures = list(primary_report.get("fixtures", []))
    artifacts = dict(primary_report.get("artifacts", {}))
    reproducible = primary_aggregate == secondary_aggregate
    canonical_identity = all(
        str(item.get("thread_key", "")).startswith("wechat:")
        or str(item.get("thread_key", "")).endswith("@chatroom")
        or str(item.get("thread_key", "")).startswith("wxid_")
        or str(item.get("channel", "")) != "wechat"
        for item in fixtures
    )
    artifact_written = bool(artifacts.get("summary_json")) and bool(artifacts.get("summary_md"))
    support_counter = dict(primary_aggregate.get("calibration_support_by_action_type", {}))
    support_changed = any(int(value or 0) > 0 for value in support_counter.values())
    checks = {
        "health_ok": str(health.get("status", "")).strip() == "ok",
        "metrics_reproducible": reproducible,
        "calibration_mae_visible": "response_quality_mae" in primary_aggregate and "relational_delta_mae" in primary_aggregate and "risk_mae" in primary_aggregate,
        "policy_regret_visible": float(primary_aggregate.get("policy_regret_vs_best_available_action", 0.0) or 0.0) > 0.0,
        "support_counts_change": support_changed,
        "false_initiative_block_accounted": float(primary_aggregate.get("false_initiative_block_rate", 0.0) or 0.0) > 0.0,
        "expression_overflow_accounted": float(primary_aggregate.get("overlong_reply_rate", 0.0) or 0.0) > 0.0 and float(primary_aggregate.get("stiffness_overflow_rate", 0.0) or 0.0) > 0.0,
        "canonical_identity_preserved": canonical_identity,
        "no_live_state_mutation": dict(live_before) == dict(live_after),
        "artifact_written": artifact_written,
    }
    score = round((sum(1.0 for value in checks.values() if value) / max(1, len(checks))) * 10.0, 2)
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "score": score,
        "checks": checks,
        "aggregate_metrics": primary_aggregate,
        "artifacts": artifacts,
        "fixture_count": int(primary_report.get("fixture_count", 0) or 0),
    }


def _accept_stage13_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage13",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "iterations": iterations,
            "warmup": warmup,
        },
        timeout=600.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage13(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                iterations=iterations,
                warmup=warmup,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage14_payload(
    config_path: str | None,
    *,
    source_type: str,
    fixture_path: str | None,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    return _stage14_replay_payload(
        config_path,
        path="/accept-stage14",
        source_type=source_type,
        fixture_path=fixture_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        artifact_dir=artifact_dir,
        allow_local_fallback=allow_local_fallback,
    )


def _contains_mojibake(value: object) -> bool:
    sentinels = ("浣犳槸", "鏈€", "闀胯", "鈧", "锟", "閸", "娑撳", "銆?")
    if isinstance(value, dict):
        return any(_contains_mojibake(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_mojibake(item) for item in value)
    return any(marker in str(value or "") for marker in sentinels)


def _stage16_helper_path_contract() -> dict[str, object]:
    from .reply_api import _coerce_helper_artifact_path_for_holo_host, _coerce_helper_artifact_path_for_windows_helper

    wsl_path = "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history.md"
    windows_path = r"D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history.md"
    malformed = r"D:\mnt\d\Holo\holo\.holo_runtime\wechat-helper\receipts\history.md"
    host_from_windows = _coerce_helper_artifact_path_for_holo_host(windows_path)
    host_from_malformed = _coerce_helper_artifact_path_for_holo_host(malformed)
    windows_from_wsl = _coerce_helper_artifact_path_for_windows_helper(wsl_path)
    return {
        "host_from_windows": host_from_windows,
        "host_from_malformed": host_from_malformed,
        "windows_from_wsl": windows_from_wsl,
        "ok": host_from_windows == wsl_path and host_from_malformed == wsl_path and windows_from_wsl.lower() == windows_path.lower(),
    }


def _stage16_wsl_fallback_contract() -> dict[str, object]:
    from urllib import parse

    import windows_helper.wechat_helper as helper

    original_resolver = helper._resolve_wsl_agent_base_url
    try:
        helper._resolve_wsl_agent_base_url = lambda base_url: "http://172.28.44.15:8000" if base_url.startswith("http://127.0.0.1:8000") else ""
        local_candidates = helper.AgentClient("http://127.0.0.1:8000")._candidate_base_urls(parse.urlparse("http://127.0.0.1:8000/health"))
        remote_candidates = helper.AgentClient("http://example.test:8000")._candidate_base_urls(parse.urlparse("http://example.test:8000/health"))
    finally:
        helper._resolve_wsl_agent_base_url = original_resolver
    return {
        "local_candidates": local_candidates,
        "remote_candidates": remote_candidates,
        "ok": local_candidates == ["http://127.0.0.1:8000", "http://172.28.44.15:8000"] and remote_candidates == ["http://example.test:8000"],
    }


def _stage16_text_integrity_report() -> dict[str, object]:
    from .policies import MEMORY_BRIDGE_POLICY

    policy_values = {
        "identity": MEMORY_BRIDGE_POLICY.default_identity_core_lines,
        "reply_constraints": MEMORY_BRIDGE_POLICY.default_reply_constraint_lines,
        "human_recall_style": MEMORY_BRIDGE_POLICY.default_human_recall_style,
        "initiative": MEMORY_BRIDGE_POLICY.default_initiative_state,
        "emotion_state": MEMORY_BRIDGE_POLICY.default_emotion_state,
        "emotion_lines": MEMORY_BRIDGE_POLICY.default_emotion_lines,
    }
    source_paths = [
        Path(__file__).resolve().parent / "policies.py",
        Path(__file__).resolve().parent / "mind_graph_parts" / "outcome_appraisal.py",
    ]
    source_hits = {
        str(path.relative_to(Path(__file__).resolve().parents[1])): _contains_mojibake(path.read_text(encoding="utf-8"))
        for path in source_paths
    }
    return {
        "policy_defaults_ok": not _contains_mojibake(policy_values),
        "source_files_ok": not any(source_hits.values()),
        "source_hits": source_hits,
    }


def _stage16_shadow_launch_sanity(config_path: str | None) -> dict[str, object]:
    config = load_config(config_path=config_path)
    operator_shadow_root = str(config.memory.operator_shadow_root or "").strip()
    helper_config_path = str(config.autonomy.wechat_helper_config_path or "").strip()
    return {
        "processor_backend": config.runtime.processor_backend,
        "operator_shadow_root": operator_shadow_root,
        "wechat_helper_config_path": helper_config_path,
        "repo_root": str(config.runtime.repo_root),
        "ok": bool(operator_shadow_root)
        and "operator_shadow" in operator_shadow_root.replace("\\", "/")
        and bool(config.runtime.repo_root)
        and bool(config.runtime.processor_backend),
    }


def _evaluate_stage16_acceptance(
    *,
    config_path: str | None,
    run_pytest: bool,
    stage12_report: dict[str, object],
    stage14_report: dict[str, object],
) -> dict[str, object]:
    pytest_report: dict[str, object]
    if run_pytest:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=str(load_config(config_path=config_path).runtime.repo_root),
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        pytest_report = {"returncode": proc.returncode, "stdout_tail": proc.stdout[-500:], "stderr_tail": proc.stderr[-500:]}
    else:
        pytest_report = {"skipped": True, "returncode": None}
    path_contract = _stage16_helper_path_contract()
    fallback_contract = _stage16_wsl_fallback_contract()
    text_report = _stage16_text_integrity_report()
    shadow_launch = _stage16_shadow_launch_sanity(config_path)
    primary_report = dict(stage14_report.get("primary_report", {})) if isinstance(stage14_report.get("primary_report", {}), dict) else {}
    stage14_metrics = dict(stage14_report.get("aggregate_metrics", {})) if isinstance(stage14_report.get("aggregate_metrics", {}), dict) else {}
    if not stage14_metrics:
        stage14_metrics = dict(primary_report.get("aggregate_metrics", {})) if isinstance(primary_report.get("aggregate_metrics", {}), dict) else {}
    if isinstance(stage14_report.get("artifacts", {}), dict) and stage14_report.get("artifacts", {}):
        stage14_artifacts = dict(stage14_report.get("artifacts", {}))
    else:
        stage14_artifacts = dict(primary_report.get("artifacts", {})) if isinstance(primary_report.get("artifacts", {}), dict) else {}
    action_market_aligned = bool(dict(stage12_report.get("checks", {})).get("action_market_first_preserved"))
    checks = {
        "full_local_test_readiness": bool(run_pytest and pytest_report.get("returncode") == 0),
        "stage12_deterministic_acceptance_green": str(stage12_report.get("status", "")).strip() == "pass",
        "stage14_acceptance_green": str(stage14_report.get("status", "")).strip() == "pass",
        "policy_defaults_text_integrity": bool(text_report.get("policy_defaults_ok")),
        "autobiographical_text_integrity": bool(text_report.get("source_files_ok")),
        "helper_path_roundtrip_contract": bool(path_contract.get("ok")),
        "localhost_wsl_fallback_contract": bool(fallback_contract.get("ok")),
        "replay_artifact_generation": bool(stage14_artifacts.get("primary", {}).get("summary_json") or stage14_artifacts.get("summary_json")),
        "shadow_launch_config_sanity": bool(shadow_launch.get("ok")),
        "action_market_first_acceptance_aligned": action_market_aligned,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "stage": "release-hardening-shadow-testing-stage16",
        "checks": checks,
        "pytest": pytest_report,
        "stage12": {"status": stage12_report.get("status"), "checks": stage12_report.get("checks", {})},
        "stage14": {"status": stage14_report.get("status"), "aggregate_metrics": stage14_metrics},
        "path_contract": path_contract,
        "wsl_fallback_contract": fallback_contract,
        "text_integrity": text_report,
        "artifacts": stage14_artifacts,
        "shadow_launch": shadow_launch,
    }


def _accept_stage16_payload(
    config_path: str | None,
    *,
    run_pytest: bool,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage16",
        payload={"run_pytest": run_pytest, "artifact_dir": artifact_dir or ""},
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return service.accept_stage16(run_pytest=run_pytest, artifact_dir=artifact_dir), "local_service"
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage17_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage17",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage17(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage18_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage18",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage18(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage19_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage19",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage19(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage20_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage20",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage20(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage21_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage21",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage21(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage22_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage22",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage22(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage23_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage23",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage23(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage24_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage24",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage24(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage25_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage25",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage25(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage26_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage26",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=900.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage26(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage27_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage27",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=1200.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage27(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def _accept_stage28_payload(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
    allow_local_fallback: bool = True,
) -> tuple[dict, str]:
    live_payload = _live_api_request(
        config_path,
        method="POST",
        path="/accept-stage28",
        payload={
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "sender": sender or "",
            "artifact_dir": artifact_dir or "",
        },
        timeout=1500.0,
    )
    if live_payload is not None:
        return live_payload, "live_http"
    if not allow_local_fallback:
        return {"status": "live_http_unavailable"}, "live_http_unavailable"
    service = HoloReplyService(load_config(config_path=config_path))
    try:
        return (
            service.accept_stage28(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                sender=sender,
                artifact_dir=artifact_dir,
            ),
            "local_service",
        )
    finally:
        service.store.close()
        if hasattr(service.memory, "activation"):
            service.memory.activation.close()
        if hasattr(service.memory, "graph"):
            service.memory.graph.close()


def command_accept_stage10(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage10_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage12(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage12_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage13(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    payload, _transport = _accept_stage13_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage16(
    config_path: str | None,
    *,
    run_pytest: bool,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage16_payload(
        config_path,
        run_pytest=run_pytest,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage17(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage17_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage18(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage18_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage19(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage19_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage20(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage20_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage21(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage21_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage22(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage22_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage23(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage23_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage24(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage24_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage25(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage25_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage26(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage26_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage27(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage27_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage28(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage28_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_replay_calibration_fixture(
    config_path: str | None,
    *,
    source_type: str,
    fixture_path: str | None,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _stage14_replay_payload(
        config_path,
        path="/replay-calibration-fixture",
        source_type=source_type,
        fixture_path=fixture_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_replay_policy_regret(
    config_path: str | None,
    *,
    source_type: str,
    fixture_path: str | None,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _stage14_replay_payload(
        config_path,
        path="/replay-policy-regret",
        source_type=source_type,
        fixture_path=fixture_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage14(
    config_path: str | None,
    *,
    source_type: str,
    fixture_path: str | None,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
    artifact_dir: str | None,
) -> int:
    payload, _transport = _accept_stage14_payload(
        config_path,
        source_type=source_type,
        fixture_path=fixture_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=limit,
        artifact_dir=artifact_dir,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_accept_stage2(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
) -> int:
    health, transport = _health_payload(config_path)
    live_only = transport == "live_http"
    original_brain_status, _ = _brain_status_payload(config_path, allow_local_fallback=not live_only)
    original_mode = str(original_brain_status.get("mode", "companion") or "companion")
    mode_transitions: list[dict[str, object]] = []
    for mode in ("silent", "companion", "dream_only", "full_brain", original_mode):
        payload, _ = _brain_mode_payload(
            config_path,
            mode=mode,
            note="accept-stage2",
            allow_local_fallback=not live_only,
        )
        mode_transitions.append(
            {
                "mode": mode,
                "status": str(payload.get("status", "ok") or "ok"),
                "active_mode": str(payload.get("mode", mode) or mode),
            }
        )
    brain_status, _ = _brain_status_payload(config_path, allow_local_fallback=not live_only)
    visible_loops = {str(item.get("loop_name", "")) for item in brain_status.get("loops", []) if str(item.get("loop_name", ""))}
    required_loops = {"heartbeat", "attention_tick", "maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"}
    if not required_loops.issubset(visible_loops):
        daemon = build_daemon(config_path)
        try:
            brain_status = daemon.brain_status()
        finally:
            daemon.store.close()
            if hasattr(daemon.memory, "activation"):
                daemon.memory.activation.close()
            if hasattr(daemon.memory, "graph"):
                daemon.memory.graph.close()
    fast_query, _fast_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=FAST_QUERY_CANDIDATES,
        target_tier="fast",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    recall_query, _recall_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=RECALL_QUERY_CANDIDATES,
        target_tier="recall",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    deep_query, _deep_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=DEEP_QUERY_CANDIDATES,
        target_tier="deep_recall",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    persona_queries = {
        "playful": STAGE2_PLAYFUL_QUERY,
        "serious": STAGE2_SERIOUS_QUERY,
        "appetite": STAGE2_APPETITE_QUERY,
        "correction": STAGE2_CORRECTION_QUERY,
    }
    persona_probes: dict[str, dict[str, object]] = {}
    for name, query in persona_queries.items():
        payload, _ = _inspect_mind_payload(
            config_path,
            query=query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            sender=sender,
            include_graph_trace=False,
            allow_local_fallback=not live_only,
        )
        packet = dict(payload.get("mind_packet", payload))
        persona_probes[name] = {
            **packet,
            "tier": payload.get("tier"),
            "query_focus": payload.get("query_focus"),
            "probe_excerpt": " | ".join(
                item
                for item in (
                    str(dict(packet.get("relationship_state", {})).get("summary", "")).strip(),
                    str(dict(packet.get("reply_constraints", {})).get("style_hints", "")).strip(),
                    str(dict(packet.get("stream_influence", {})).get("summary", "")).strip(),
                )
                if item
            )[:240],
        }
    stream_status_before, _ = _stream_status_payload(config_path, allow_local_fallback=not live_only)
    stream_ticks: list[dict[str, object]] = []
    for stream_name in ("association_stream", "social_stream", "deep_dream_cycle"):
        payload, _ = _stream_tick_payload(
            config_path,
            stream_name=stream_name,
            dry_run=False,
            allow_local_fallback=not live_only,
        )
        stream_ticks.append(payload)
    stream_status_after, _ = _stream_status_payload(config_path, allow_local_fallback=not live_only)
    initiative_probe, _ = _initiative_probe_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        query=STAGE2_PLAYFUL_QUERY,
        allow_local_fallback=not live_only,
    )
    self_revision, _ = _self_revision_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        corrections=STAGE2_CORRECTIONS,
        apply_patch=True,
        allow_local_fallback=not live_only,
    )
    fast_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=fast_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )
    recall_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=recall_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )
    deep_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=deep_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )
    acceptance = _evaluate_stage2_acceptance(
        transport=transport,
        health=health,
        brain_status=brain_status,
        mode_transitions=mode_transitions,
        persona_probes=persona_probes,
        stream_status_before=stream_status_before,
        stream_ticks=stream_ticks,
        stream_status_after=stream_status_after,
        initiative_probe=initiative_probe,
        self_revision=self_revision,
        fast_benchmark=fast_benchmark,
        recall_benchmark=recall_benchmark,
        deep_benchmark=deep_benchmark,
    )
    cache_stats = dict(brain_status.get("cache", {}))
    report = {
        **acceptance,
        "transport": transport,
        "queries": {
            "fast": fast_query,
            "recall": recall_query,
            "deep_recall": deep_query,
            "persona": persona_queries,
        },
        "artifacts": {
            "health": {
                "status": health.get("status"),
                "repo_root": health.get("repo_root"),
                "brain_mode": health.get("brain_mode"),
            },
            "brain_status": {
                "mode": brain_status.get("mode"),
                "idle_seconds": brain_status.get("idle_seconds"),
                "cache": cache_stats,
                "loop_count": len(list(brain_status.get("loops", []))),
            },
            "mode_transitions": mode_transitions,
            "persona_probes": persona_probes,
            "stream_ticks": stream_ticks,
            "stream_status_before": {
                "activation_event_count": len(list(stream_status_before.get("activation_events", []))),
                "recent_run_count": len(list(stream_status_before.get("recent_runs", []))),
            },
            "stream_status_after": {
                "activation_event_count": len(list(stream_status_after.get("activation_events", []))),
                "recent_run_count": len(list(stream_status_after.get("recent_runs", []))),
            },
            "initiative_probe": initiative_probe,
            "self_revision": self_revision,
            "benchmarks": {
                "fast": fast_benchmark,
                "recall": recall_benchmark,
                "deep_recall": deep_benchmark,
            },
        },
        "summary": {
            "packet_latency_ms": {
                "fast_max": dict(fast_benchmark.get("timings_ms", {})).get("max"),
                "recall_max": dict(recall_benchmark.get("timings_ms", {})).get("max"),
                "deep_recall_max": dict(deep_benchmark.get("timings_ms", {})).get("max"),
            },
            "cache_hit_ratio": cache_stats.get("hit_ratio", 0.0),
            "stream_influence_count": len(stream_ticks),
            "self_revision_status": self_revision.get("status"),
            "final_stage_verdict": acceptance.get("status"),
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if acceptance["status"] == "pass" else 1


def command_inspect_graph(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/mind-graph",
        params={"thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
    )
    if live_payload is not None:
        print(json.dumps(live_payload, ensure_ascii=False, indent=2))
        return 0
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_trace_recall(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/trace-recall",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
    )
    if live_payload is not None:
        print(json.dumps(live_payload, ensure_ascii=False, indent=2))
        return 0
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.trace_recall(query, thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_trace_hybrid_recall(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    limit: int,
) -> int:
    live_payload = _live_api_request(
        config_path,
        method="GET",
        path="/trace-hybrid-recall",
        params={"query": query, "thread_key": thread_key, "chat_name": chat_name, "channel": channel, "limit": limit},
    )
    if live_payload is not None:
        print(json.dumps(live_payload, ensure_ascii=False, indent=2))
        return 0
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.trace_hybrid_recall(
                query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=limit,
                record=False,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_show_activation_state(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
) -> int:
    payload, _transport = _activation_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_vector_health(config_path: str | None) -> int:
    payload, _transport = _vector_health_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_backfill_vector_memory(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str | None,
) -> int:
    payload, _transport = _backfill_vector_memory_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_reply_probe(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    mode: str,
) -> int:
    _health, transport = _health_payload(config_path)
    live_only = transport == "live_http"
    payload, _transport = _reply_probe_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    if mode != "all":
        payload = {
            "chat_name": payload.get("chat_name", ""),
            "thread_key": payload.get("thread_key", ""),
            "channel": payload.get("channel", ""),
            "query": payload.get("query", ""),
            mode: payload.get(mode, {}),
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_stream_status(config_path: str | None) -> int:
    payload, _transport = _stream_status_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_processor_routing(config_path: str | None) -> int:
    payload, _transport = _processor_routing_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_provider_status(config_path: str | None) -> int:
    payload, _transport = _provider_status_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_provider_substrate_status(config_path: str | None) -> int:
    payload, _transport = _provider_substrate_status_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_provider_contracts(config_path: str | None) -> int:
    payload, _transport = _provider_contracts_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_mcp_upstream_status(config_path: str | None) -> int:
    from .mcp_upstream import build_mcp_upstream_hub

    payload = build_mcp_upstream_hub(config_path=config_path).status()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_list_mcp_upstream_tools(config_path: str | None) -> int:
    from .mcp_upstream import build_mcp_upstream_hub

    payload = build_mcp_upstream_hub(config_path=config_path).list_tools()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not payload.get("errors") else 1


def command_call_mcp_tool(config_path: str | None, *, tool: str, arguments_json: str) -> int:
    from .mcp_upstream import McpUpstreamError, build_mcp_upstream_hub

    try:
        arguments = json.loads(arguments_json or "{}")
    except json.JSONDecodeError as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "stage53-mcp-upstream-tools", "error": "invalid_arguments_json", "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    if not isinstance(arguments, dict):
        print(
            json.dumps(
                {"ok": False, "stage": "stage53-mcp-upstream-tools", "error": "arguments_json_must_be_object"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 2
    try:
        payload = build_mcp_upstream_hub(config_path=config_path).call_tool(tool, arguments)
    except McpUpstreamError as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "stage53-mcp-upstream-tools", "error": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_read_mcp_resource(config_path: str | None, *, server: str, uri: str) -> int:
    from .mcp_upstream import McpUpstreamError, build_mcp_upstream_hub

    try:
        payload = build_mcp_upstream_hub(config_path=config_path).read_resource(server, uri)
    except McpUpstreamError as exc:
        print(
            json.dumps(
                {"ok": False, "stage": "stage53-mcp-upstream-tools", "error": type(exc).__name__, "detail": str(exc)},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_render_consciousness_map(config_path: str | None, *, suite: str, output: str | None) -> int:
    from .bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
    from .consciousness_visualization import build_consciousness_visualization, write_consciousness_visualization_artifacts

    config = load_config(config_path=config_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        latest = store.latest_agent_eval_run(stage=STAGE46_NAME, suite=suite or DEFAULT_STAGE46_SUITE)
    finally:
        store.close()
    if not latest:
        print(
            json.dumps(
                {
                    "ok": False,
                    "stage": "stage54-consciousness-flow-visualization",
                    "error": "stage46_run_not_found",
                    "suite": suite or DEFAULT_STAGE46_SUITE,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1
    run_payload = dict(latest.get("run", {})) if isinstance(latest.get("run", {}), dict) else {}
    report = build_consciousness_visualization(run_payload)
    if output:
        output_path = Path(output).expanduser()
    else:
        eval_run_id = int(latest.get("eval_run_id", latest.get("id", 0)) or 0)
        output_path = config.runtime.repo_root / "artifacts" / "stage54" / f"consciousness_map_{eval_run_id}.html"
    written = write_consciousness_visualization_artifacts(report, output_path)
    print(
        json.dumps(
            {
                "ok": True,
                "stage": report.get("stage", ""),
                "output_path": str(written["html"]),
                "json_path": str(written["json"]),
                "heatmap_png_path": str(written["heatmap_png"]),
                "dashboard_png_path": str(written["dashboard_png"]),
                "visualization": {
                    "turn_count": report.get("turn_count", 0),
                    "summary": report.get("summary", {}),
                    "trajectory_projection": dict(report.get("trajectory", {})).get("projection", ""),
                    "compute_manifold_projection": dict(report.get("compute_manifold", {})).get("projection", ""),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_show_visual_provider_readiness(config_path: str | None) -> int:
    payload, _transport = _visual_provider_readiness_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_show_debt_registry(config_path: str | None) -> int:
    payload, _transport = _debt_registry_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_internal_runtime_readiness(config_path: str | None) -> int:
    payload, _transport = _internal_runtime_readiness_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_usage_ledger(
    config_path: str | None,
    *,
    limit: int,
    task_type: str | None,
    lane: str | None,
    provider: str | None,
) -> int:
    payload, _transport = _usage_ledger_payload(
        config_path,
        limit=limit,
        task_type=task_type,
        lane=lane,
        provider=provider,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_agent_run(
    config_path: str | None,
    *,
    query: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    record: bool,
    image_paths: list[str] | None = None,
) -> int:
    payload, _transport = bionic_cli.bionic_agent_payload(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=offline,
        record=record,
        image_paths=image_paths or [],
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_agent_trace(config_path: str | None, *, trace_id: int) -> int:
    payload, _transport = bionic_cli.bionic_trace_payload(config_path, trace_id=trace_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_bionic_metrics(config_path: str | None, *, limit: int) -> int:
    payload, _transport = bionic_cli.bionic_metrics_payload(config_path, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_brain_run(
    config_path: str | None,
    *,
    goal: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    max_steps: int,
) -> int:
    payload, _transport = brain_cli.brain_run_payload(
        config_path,
        goal=goal,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=offline,
        max_steps=max_steps,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_brain_trace(config_path: str | None, *, trace_id: int) -> int:
    payload, _transport = brain_cli.brain_trace_payload(config_path, trace_id=trace_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_context_bundle(config_path: str | None, *, bundle_id: str) -> int:
    payload, _transport = brain_cli.show_context_bundle_payload(config_path, bundle_id=bundle_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_brain_metrics(config_path: str | None, *, limit: int) -> int:
    payload, _transport = brain_cli.brain_metrics_payload(config_path, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_run_agent_eval(config_path: str | None, *, suite: str) -> int:
    payload, _transport = brain_cli.agent_eval_payload(config_path, suite=suite)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_run_bionic_user_sim(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
    scenario: str,
    turn_limit: int,
    offline: bool,
) -> int:
    payload, _transport = user_sim_cli.run_bionic_user_sim_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        scenario=scenario,
        turn_limit=turn_limit,
        offline=offline,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_bionic_user_sim_scorecard(config_path: str | None, *, suite: str) -> int:
    payload, _transport = user_sim_cli.show_bionic_user_sim_scorecard_payload(config_path, suite=suite)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_run_bionic_boundary_stress(
    config_path: str | None,
    *,
    thread_key: str,
    chat_name: str,
    channel: str,
    turn_limit: int,
    offline: bool,
) -> int:
    payload, _transport = boundary_stress_cli.run_bionic_boundary_stress_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        turn_limit=turn_limit,
        offline=offline,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_bionic_boundary_stress_scorecard(config_path: str | None, *, suite: str) -> int:
    payload, _transport = boundary_stress_cli.show_bionic_boundary_stress_scorecard_payload(config_path, suite=suite)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_engineering_run(
    config_path: str | None,
    *,
    goal: str,
    thread_key: str,
    chat_name: str,
    channel: str,
    offline: bool,
    max_steps: int,
    allow_repo_write: bool,
) -> int:
    payload, _transport = engineering_cli.engineering_run_payload(
        config_path,
        goal=goal,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        offline=offline,
        max_steps=max_steps,
        allow_repo_write=allow_repo_write,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_engineering_trace(config_path: str | None, *, trace_id: int) -> int:
    payload, _transport = engineering_cli.engineering_trace_payload(config_path, trace_id=trace_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_engineering_agent_metrics(config_path: str | None, *, limit: int) -> int:
    payload, _transport = engineering_cli.engineering_metrics_payload(config_path, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_trace_subject_loop(config_path: str | None, *, trace_id: int) -> int:
    payload, _transport = bionic_cli.subject_loop_trace_payload(config_path, trace_id=trace_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_subject_loop_metrics(config_path: str | None, *, limit: int) -> int:
    payload, _transport = bionic_cli.subject_loop_metrics_payload(config_path, limit=limit)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_export_bionic_trace(config_path: str | None, *, trace_id: int, output: str) -> int:
    payload, _transport = bionic_cli.export_bionic_trace_payload(config_path, trace_id=trace_id, output=output)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage29(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage29_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage30(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage30_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage31(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage31_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage32(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage32_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage36(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage36_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage37(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage37_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage38(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage38_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_bionic_turing_scorecard(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.bionic_turing_benchmark_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage39(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = bionic_cli.accept_stage39_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage40(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = brain_cli.accept_stage40_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage41(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = engineering_cli.accept_stage41_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage42(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = user_sim_cli.accept_stage42_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage43(config_path: str | None, *, thread_key: str, chat_name: str, channel: str) -> int:
    payload, _transport = motivational_cli.accept_stage43_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage33(config_path: str | None) -> int:
    payload, _transport = _accept_stage33_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage34(config_path: str | None) -> int:
    payload, _transport = _accept_stage34_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_accept_stage35(config_path: str | None) -> int:
    payload, _transport = _accept_stage35_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if bool(payload.get("ok", False)) else 1


def command_show_processor_mesh(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    try:
        print(
            json.dumps(
                {
                    "tasks": daemon.runner.supported_tasks(),
                    "routing": daemon.runner.routing_table(),
                    "providers": daemon.runner.provider_status(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        daemon.store.close()
        if hasattr(daemon.memory, "activation"):
            daemon.memory.activation.close()
        if hasattr(daemon.memory, "graph"):
            daemon.memory.graph.close()
    return 0


def command_accept_processor_fabric(config_path: str | None) -> int:
    payload, _transport = _accept_processor_fabric_payload(config_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_stream_tick(
    config_path: str | None,
    *,
    stream_name: str,
    dry_run: bool,
) -> int:
    payload, _transport = _stream_tick_payload(config_path, stream_name=stream_name, dry_run=dry_run)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_sync_private_memory(config_path: str | None, *, label: str | None) -> int:
    payload, _transport = _sync_private_memory_payload(config_path, label=label)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def command_benchmark_memory_fabric(
    config_path: str | None,
    *,
    query: str,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    probe: str,
) -> int:
    report = _benchmark_memory_fabric_report(
        config_path,
        query=query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe=probe,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def command_accept_memory_fabric_stage1(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
    iterations: int,
    warmup: int,
    tick_streams: bool,
    require_private_sync: bool,
    private_label: str | None,
) -> int:
    health, transport = _health_payload(config_path)
    live_only = transport == "live_http"
    _backfill_report, _ = _backfill_vector_memory_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        allow_local_fallback=not live_only,
    )
    fast_query, _fast_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=FAST_QUERY_CANDIDATES,
        target_tier="fast",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    recall_query, _recall_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=RECALL_QUERY_CANDIDATES,
        target_tier="recall",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    deep_query, _deep_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=DEEP_QUERY_CANDIDATES,
        target_tier="deep_recall",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
    )
    origin_query, _origin_packet, _ = _pick_query_for_target_tier(
        config_path,
        candidates=ORIGIN_QUERY_CANDIDATES,
        target_tier="deep_recall",
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
    )
    explicit_trace, _ = _trace_hybrid_payload(
        config_path,
        query=deep_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=8,
        allow_local_fallback=not live_only,
    )
    origin_trace, _ = _trace_hybrid_payload(
        config_path,
        query=origin_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        limit=8,
        allow_local_fallback=not live_only,
    )
    reply_probe, _ = _reply_probe_payload(
        config_path,
        query=deep_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        allow_local_fallback=not live_only,
    )
    vector_health, _ = _vector_health_payload(config_path, allow_local_fallback=not live_only)
    stream_ticks: list[dict[str, object]] = []
    if tick_streams:
        for stream_name in ("association_stream", "social_stream"):
            payload, _ = _stream_tick_payload(
                config_path,
                stream_name=stream_name,
                dry_run=False,
                allow_local_fallback=not live_only,
            )
            stream_ticks.append(payload)
    activation_state, _ = _activation_state_payload(
        config_path,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        allow_local_fallback=not live_only,
    )
    stream_status, _ = _stream_status_payload(config_path, allow_local_fallback=not live_only)
    private_sync: dict[str, object] | None = None
    config = load_config(config_path=config_path)
    private_sync_required = require_private_sync or bool(config.memory.private_memory_sync_enabled or str(config.memory.private_memory_repo_path).strip())
    if private_sync_required:
        private_sync, _ = _sync_private_memory_payload(
            config_path,
            label=private_label,
            allow_local_fallback=not live_only,
        )

    fast_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=fast_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )
    recall_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=recall_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )
    deep_benchmark = _benchmark_memory_fabric_report(
        config_path,
        query=deep_query,
        thread_key=thread_key,
        chat_name=chat_name,
        channel=channel,
        sender=sender,
        iterations=iterations,
        warmup=warmup,
        probe="mind",
        allow_local_fallback=not live_only,
    )

    acceptance = _evaluate_stage1_acceptance(
        transport=transport,
        health=health,
        vector_health=vector_health,
        explicit_trace=explicit_trace,
        origin_trace=origin_trace,
        reply_probe=reply_probe,
        activation_state=activation_state,
        stream_ticks=stream_ticks,
        stream_status=stream_status,
        fast_benchmark=fast_benchmark,
        recall_benchmark=recall_benchmark,
        deep_benchmark=deep_benchmark,
        private_sync=private_sync,
        require_private_sync=private_sync_required,
    )
    report = {
        **acceptance,
        "transport": transport,
        "queries": {
            "fast": fast_query,
            "recall": recall_query,
            "deep_recall": deep_query,
            "origin": origin_query,
        },
        "artifacts": {
            "health": {
                "status": health.get("status"),
                "repo_root": health.get("repo_root"),
                "graph_led_reply_enabled": health.get("graph_led_reply_enabled"),
                "fallback_enabled": health.get("fallback_enabled"),
                "vector_backend": health.get("vector_backend"),
                "activation_cache_enabled": health.get("activation_cache_enabled"),
            },
            "vector_health": vector_health,
            "explicit_trace": {
                "tier": explicit_trace.get("tier"),
                "query_focus": explicit_trace.get("query_focus"),
                "retrieval_mode": explicit_trace.get("retrieval_mode"),
                "memory_route": explicit_trace.get("memory_route"),
                "graph_confidence": explicit_trace.get("graph_confidence"),
                "recall_confidence": explicit_trace.get("recall_confidence"),
                "graph_hit_count": len(list(explicit_trace.get("graph_hits", []))),
                "vector_hit_count": len(list(explicit_trace.get("vector_hits", []))),
                "activation_trace_count": len(list(explicit_trace.get("activation_trace_ids", []))),
                "top_graph_lines": [
                    str(item.get("text", "")).strip()
                    for item in list(explicit_trace.get("graph_hits", []))[:3]
                    if str(item.get("text", "")).strip()
                ],
            },
            "origin_trace": {
                "tier": origin_trace.get("tier"),
                "query_focus": origin_trace.get("query_focus"),
                "retrieval_mode": origin_trace.get("retrieval_mode"),
                "memory_route": origin_trace.get("memory_route"),
                "graph_hit_count": len(list(origin_trace.get("graph_hits", []))),
                "vector_hit_count": len(list(origin_trace.get("vector_hits", []))),
                "top_graph_lines": [
                    str(item.get("text", "")).strip()
                    for item in list(origin_trace.get("graph_hits", []))[:3]
                    if str(item.get("text", "")).strip()
                ],
            },
            "reply_probe": {
                "tier": dict(reply_probe.get("hybrid", {})).get("tier", ""),
                "query_focus": dict(reply_probe.get("hybrid", {})).get("query_focus", ""),
                "retrieval_mode": dict(reply_probe.get("hybrid", {})).get("retrieval_mode", ""),
                "memory_route": dict(reply_probe.get("hybrid", {})).get("memory_route", ""),
                "recall_reconstruction": dict(dict(reply_probe.get("hybrid", {})).get("recall_reconstruction", {}))
                or dict(dict(dict(reply_probe.get("hybrid", {})).get("reply_plan", {})).get("debug", {}).get("recall_reconstruction", {})),
                "reply_text": dict(dict(reply_probe.get("hybrid", {})).get("reply_plan", {})).get("text", ""),
            },
            "activation_state": {
                "heat": activation_state.get("heat"),
                "motifs": list(activation_state.get("motifs", [])),
                "active_node_count": len(list(activation_state.get("active_node_ids", []))),
                "recent_event_count": len(list(activation_state.get("recent_events", []))),
            },
            "stream_ticks": [
                {
                    "stream_name": item.get("stream_name"),
                    "influence": dict(dict(item.get("record", {})).get("influence", {})),
                }
                for item in stream_ticks
            ],
            "stream_status": {
                "stream_count": len(list(stream_status.get("streams", []))),
                "recent_run_count": len(list(stream_status.get("recent_runs", []))),
            },
            "benchmarks": {
                "fast": fast_benchmark,
                "recall": recall_benchmark,
                "deep_recall": deep_benchmark,
            },
            "private_sync": private_sync or {
                "status": "skipped",
                "reason": "private_memory_sync_disabled",
            },
        },
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if acceptance["status"] == "pass" else 1


def command_run_processor_task(
    config_path: str | None,
    *,
    task_type: str,
    prompt: str,
    session_id: str | None,
    model: str | None,
    reasoning_effort: str | None,
    lane: str | None,
    provider_hint: str | None,
    budget_tag: str | None,
    max_output_tokens: int | None,
    json_output: bool,
) -> int:
    daemon = build_daemon(config_path)
    try:
        result = daemon.runner.run_task(
            ProcessorTaskRequest(
                task_type=task_type,
                prompt=prompt,
                session_id=str(session_id or ""),
                lane=str(lane or ""),
                provider_hint=str(provider_hint or ""),
                model_override=str(model or ""),
                reasoning_effort_override=str(reasoning_effort or ""),
                budget_tag=str(budget_tag or ""),
                max_output_tokens=max_output_tokens,
                output_schema="json" if json_output else "plain_text",
            )
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    finally:
        daemon.store.close()
        if hasattr(daemon.memory, "activation"):
            daemon.memory.activation.close()
        if hasattr(daemon.memory, "graph"):
            daemon.memory.graph.close()
    return 0


def command_experiment_memory(
    config_path: str | None,
    *,
    thread_key: str | None,
    chat_name: str | None,
    channel: str,
    sender: str | None,
) -> int:
    daemon = build_daemon(config_path)
    context = _mind_context(daemon, thread_key=thread_key, chat_name=chat_name, channel=channel, sender=sender)
    scenarios = [
        ("casual_ping", "在吗"),
        ("identity_check", "你还是你吗"),
        ("explicit_recall", "你还记得重新上线前吗"),
    ]
    results: list[dict] = []
    for name, query in scenarios:
        packet = daemon.memory.inspect_mind(query, context=context)
        results.append(
            {
                "name": name,
                "query": query,
                "tier": packet.get("tier", "fast"),
                "recall_reason": packet.get("recall_reason", "none"),
                "selected_memory_ids": list(packet.get("selected_memory_ids", [])),
                "relationship_summary": packet.get("relationship_summary", ""),
                "thread_summary": packet.get("thread_summary", ""),
                "episodic_lines": list(packet.get("episodic_lines", [])),
                "consciousness_lines": list(packet.get("consciousness_lines", [])),
            }
        )
    print(json.dumps({"channel": channel, "thread_key": thread_key or "", "chat_name": chat_name or "", "scenarios": results}, ensure_ascii=False, indent=2))
    return 0


def command_snapshot_memory(config_path: str | None, path: str | None, label: str | None, query: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps(daemon.memory.export_snapshot(path=path, label=label, query=query), ensure_ascii=False, indent=2))
    return 0


def command_restore_memory(
    config_path: str | None,
    path: str,
    *,
    mode: str,
    dry_run: bool,
    restore_persona_files: bool,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.import_snapshot(
                path,
                mode=mode,
                dry_run=dry_run,
                restore_persona=restore_persona_files,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_revive_packet(config_path: str | None, path: str | None, query: str | None, as_json: bool) -> int:
    daemon = build_daemon(config_path)
    packet = daemon.memory.revive_packet(query=query, snapshot_path=path)
    if as_json:
        print(json.dumps(packet, ensure_ascii=False, indent=2))
    else:
        print(packet["text"])
    return 0


def command_serve_api(config_path: str | None, host: str | None, port: int | None) -> int:
    run_reply_api(config_path=config_path, host=host, port=port)
    return 0


def command_ingest_artifact(
    config_path: str | None,
    path: str,
    *,
    note: str | None,
    tags: list[str],
    source: str,
    dry_run: bool,
    channel: str,
    thread_key: str | None,
    chat_name: str | None,
    world_cue_type: str,
    due_at: str,
) -> int:
    daemon = build_daemon(config_path)
    print(
        json.dumps(
            daemon.memory.ingest_artifact(
                path,
                note=note,
                source=source,
                tags=tags,
                dry_run=dry_run,
                channel=channel,
                thread_key=thread_key or "",
                chat_name=chat_name or "",
                world_cue_type=world_cue_type,
                due_at=due_at,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def command_refresh_wechat_history(
    config_path: str | None,
    *,
    chat_name: str,
    thread_key: str | None,
    query: str | None,
    force: bool,
    limit: int | None,
    page_turns: int | None,
    include_visible: bool,
    include_captures: bool,
) -> int:
    config = load_config(config_path=config_path)
    service = HoloReplyService(config)
    print(
        json.dumps(
            service.refresh_wechat_history(
                {
                    "chat_name": chat_name,
                    "thread_key": thread_key or "",
                    "channel": "wechat",
                    "query": query or "",
                    "force": force,
                    "limit": limit,
                    "page_turns": page_turns,
                    "include_visible": include_visible,
                    "include_captures": include_captures,
                }
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Holo WSL host daemon")
    parser.add_argument("--config", default=None, help="Path to .holo_host.toml")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Initialize the runtime SQLite store")
    subparsers.add_parser("cycle", help="Run one ingest/process/promote cycle")
    subparsers.add_parser("daemon", help="Run the host daemon forever")
    jobs_parser = subparsers.add_parser("jobs", help="Show recent queue jobs")
    jobs_parser.add_argument("--limit", type=int, default=50)
    followups_parser = subparsers.add_parser("schedule-followups", help="Schedule due proactive followups")
    followups_parser.add_argument("--limit", type=int, default=10)
    subparsers.add_parser("promote-memory", help="Promote ready candidate memories")
    backfill_parser = subparsers.add_parser("backfill-archive", help="Backfill archive turns from holo_host.sqlite3")
    backfill_parser.add_argument("--db-path", default=None)
    backfill_parser.add_argument("--dry-run", action="store_true")
    backfill_graph_parser = subparsers.add_parser("backfill-mind-graph", help="Rebuild the SQLite-backed Mind Graph from archive and stores")
    backfill_graph_parser.add_argument("--dry-run", action="store_true")
    dream_parser = subparsers.add_parser("dream-cycle", help="Replay archive turns into candidate memory and callback candidates")
    dream_parser.add_argument("--sample-size", type=int, default=6)
    dream_parser.add_argument("--seed", default=None)
    dream_parser.add_argument("--dry-run", action="store_true")
    think_parser = subparsers.add_parser("think-cycle", help="Run one internal thought cycle")
    think_parser.add_argument("--sample-size", type=int, default=4)
    think_parser.add_argument("--seed", default=None)
    think_parser.add_argument("--dry-run", action="store_true")
    reflect_parser = subparsers.add_parser("reflect-cycle", help="Run one reflection cycle")
    reflect_parser.add_argument("--window-hours", type=float, default=12.0)
    reflect_parser.add_argument("--dry-run", action="store_true")
    initiative_cycle_parser = subparsers.add_parser("initiative-cycle", help="Refresh initiative candidates")
    initiative_cycle_parser.add_argument("--dry-run", action="store_true")
    callbacks_parser = subparsers.add_parser("show-callbacks", help="Inspect callback candidates")
    callbacks_parser.add_argument("--limit", type=int, default=20)
    thoughts_parser = subparsers.add_parser("show-thoughts", help="Inspect recent thought-stream rows")
    thoughts_parser.add_argument("--limit", type=int, default=20)
    initiatives_parser = subparsers.add_parser("show-initiatives", help="Inspect initiative candidates")
    initiatives_parser.add_argument("--limit", type=int, default=20)
    subparsers.add_parser("show-brain-status", help="Show Always-On brain runtime state")
    subparsers.add_parser("show-self-model", help="Show the current persisted self-model state")
    subparsers.add_parser("show-autobiographical-state", help="Show the persisted autobiographical self state")
    subparsers.add_parser("show-goal-state", help="Show the persisted long-horizon goal state")
    subparsers.add_parser("show-engineering-state", help="Show the Stage-10 engineering self-model and bounded runtime state")
    action_calibration_parser = subparsers.add_parser("show-action-calibration", help="Show persistent empirical action-calibration overlay rows")
    action_calibration_parser.add_argument("--thread-key", default=None)
    action_calibration_parser.add_argument("--chat-name", default=None)
    action_calibration_parser.add_argument("--channel", default="wechat")
    action_calibration_parser.add_argument("--action-type", default=None)
    action_calibration_parser.add_argument("--scenario-bucket", default=None)
    action_calibration_parser.add_argument("--limit", type=int, default=24)
    policy_candidates_parser = subparsers.add_parser("show-policy-candidates", help="Show Stage-21 replay-gated policy sediment candidates")
    policy_candidates_parser.add_argument("--thread-key", default=None)
    policy_candidates_parser.add_argument("--chat-name", default=None)
    policy_candidates_parser.add_argument("--channel", default="wechat")
    policy_candidates_parser.add_argument("--limit", type=int, default=24)
    promoted_policies_parser = subparsers.add_parser("show-promoted-policies", help="Show Stage-21 promoted policy sediment overlays")
    promoted_policies_parser.add_argument("--thread-key", default=None)
    promoted_policies_parser.add_argument("--chat-name", default=None)
    promoted_policies_parser.add_argument("--channel", default="wechat")
    promoted_policies_parser.add_argument("--limit", type=int, default=24)
    rollback_policy_parser = subparsers.add_parser("rollback-policy", help="Rollback one Stage-21 promoted policy overlay by id or policy_id")
    rollback_policy_parser.add_argument("--id", required=True)
    rollback_policy_parser.add_argument("--reason", default="cli_rollback_policy")
    policy_influence_parser = subparsers.add_parser("trace-policy-influence", help="Trace Stage-21 policy sediment influence for one thread")
    policy_influence_parser.add_argument("--thread-key", default=None)
    policy_influence_parser.add_argument("--chat-name", default=None)
    policy_influence_parser.add_argument("--channel", default="wechat")
    policy_influence_parser.add_argument("--query", default="")
    policy_influence_parser.add_argument("--limit", type=int, default=8)
    online_canary_parser = subparsers.add_parser("show-online-canary", help="Show Stage-22 shadow/canary gate state and recent traces")
    online_canary_parser.add_argument("--limit", type=int, default=24)
    blackbox_metrics_parser = subparsers.add_parser("show-blackbox-metrics", help="Show Stage-22 blackbox and human-likeness canary metrics")
    blackbox_metrics_parser.add_argument("--window-hours", type=float, default=24.0)
    blackbox_metrics_parser.add_argument("--thread-key", default=None)
    blackbox_metrics_parser.add_argument("--chat-name", default=None)
    blackbox_metrics_parser.add_argument("--channel", default=None)
    blackbox_metrics_parser.add_argument("--limit", type=int, default=500)
    blackbox_scorecard_parser = subparsers.add_parser("show-blackbox-scorecard", help="Show the latest or on-demand Stage-27 long-horizon blackbox scorecard")
    blackbox_scorecard_parser.add_argument("--since-hours", type=float, default=168.0)
    blackbox_scorecard_parser.add_argument("--limit", type=int, default=500)
    canary_trace_parser = subparsers.add_parser("trace-canary-decision", help="Trace Stage-22 shadow/canary gates for one turn without sending")
    canary_trace_parser.add_argument("--thread-key", default=None)
    canary_trace_parser.add_argument("--chat-name", default=None)
    canary_trace_parser.add_argument("--channel", default="wechat")
    canary_trace_parser.add_argument("--query", required=True)
    canary_rollback_parser = subparsers.add_parser("set-canary-rollback", help="Enable or clear the Stage-22 canary rollback switch")
    canary_rollback_parser.add_argument("--enabled", required=True, choices=("true", "false", "1", "0", "yes", "no"))
    canary_rollback_parser.add_argument("--reason", default="cli_canary_rollback")
    live_replay_parser = subparsers.add_parser("replay-live-artifacts", help="Convert Stage-22 live artifacts into Stage-14 replay fixtures and run replay")
    live_replay_parser.add_argument("--since-hours", type=float, default=24.0)
    live_replay_parser.add_argument("--limit", type=int, default=24)
    live_replay_parser.add_argument("--artifact-dir", default=None)
    blind_packets_parser = subparsers.add_parser("export-blind-packets", help="Export Stage-27 blind evaluation packets from live canary artifacts")
    blind_packets_parser.add_argument("--since-hours", type=float, default=168.0)
    blind_packets_parser.add_argument("--limit", type=int, default=500)
    blind_packets_parser.add_argument("--artifact-dir", default=None)
    blackbox_soak_parser = subparsers.add_parser("run-blackbox-soak", help="Run the Stage-27 long-horizon blackbox soak harness")
    blackbox_soak_parser.add_argument("--since-hours", type=float, default=168.0)
    blackbox_soak_parser.add_argument("--limit", type=int, default=500)
    blackbox_soak_parser.add_argument("--artifact-dir", default=None)
    blackbox_soak_parser.add_argument("--persist", required=False, default="true", choices=("true", "false", "1", "0", "yes", "no"))
    outcome_history_parser = subparsers.add_parser("trace-outcome-history", help="Show recent outcome appraisal history for one thread")
    outcome_history_parser.add_argument("--thread-key", default=None)
    outcome_history_parser.add_argument("--chat-name", default=None)
    outcome_history_parser.add_argument("--channel", default="wechat")
    outcome_history_parser.add_argument("--action-type", default=None)
    outcome_history_parser.add_argument("--limit", type=int, default=8)
    prediction_error_parser = subparsers.add_parser("trace-action-prediction-error", help="Show predicted-vs-realized outcome error history")
    prediction_error_parser.add_argument("--thread-key", default=None)
    prediction_error_parser.add_argument("--chat-name", default=None)
    prediction_error_parser.add_argument("--channel", default="wechat")
    prediction_error_parser.add_argument("--action-type", default=None)
    prediction_error_parser.add_argument("--limit", type=int, default=8)
    subparsers.add_parser("trace-self-model", help="Show the self-model alongside runtime and operator state")
    subparsers.add_parser("trace-self-continuity", help="Explain Stage-8 autobiographical continuity and recent self change")
    subparsers.add_parser("trace-goal-arbitration", help="Explain Stage-8 goal arbitration and current goal commitments")
    affect_state_parser = subparsers.add_parser("show-affect-state", help="Show the current affect-state for one thread")
    affect_state_parser.add_argument("--thread-key", default=None)
    affect_state_parser.add_argument("--chat-name", default=None)
    affect_state_parser.add_argument("--channel", default="wechat")
    drive_state_parser = subparsers.add_parser("trace-drive-state", help="Show drive/value/conflict state for one thread")
    drive_state_parser.add_argument("--thread-key", default=None)
    drive_state_parser.add_argument("--chat-name", default=None)
    drive_state_parser.add_argument("--channel", default="wechat")
    intent_state_parser = subparsers.add_parser("show-intent-state", help="Show the current or last intent-state for one thread")
    intent_state_parser.add_argument("--thread-key", default=None)
    intent_state_parser.add_argument("--chat-name", default=None)
    intent_state_parser.add_argument("--channel", default="wechat")
    intent_state_parser.add_argument("--query", default="")
    action_market_parser = subparsers.add_parser("show-action-market", help="Inspect the current or last Stage-5 action market")
    action_market_parser.add_argument("--thread-key", default=None)
    action_market_parser.add_argument("--chat-name", default=None)
    action_market_parser.add_argument("--channel", default="wechat")
    action_market_parser.add_argument("--query", default="")
    action_market_parser.add_argument("--limit", type=int, default=8)
    fast_metrics_parser = subparsers.add_parser("show-fast-path-metrics", help="Show Stage-18 active fast-path counters and reflex state")
    fast_metrics_parser.add_argument("--thread-key", default=None)
    fast_metrics_parser.add_argument("--chat-name", default=None)
    fast_metrics_parser.add_argument("--channel", default="wechat")
    predictive_parser = subparsers.add_parser("show-predictive-continuity", help="Show Stage-18 predictive continuity for one active thread")
    predictive_parser.add_argument("--thread-key", default=None)
    predictive_parser.add_argument("--chat-name", default=None)
    predictive_parser.add_argument("--channel", default="wechat")
    scene_parser = subparsers.add_parser("show-scene-state", help="Show Stage-24 scene state for one active thread")
    scene_parser.add_argument("--thread-key", default=None)
    scene_parser.add_argument("--chat-name", default=None)
    scene_parser.add_argument("--channel", default="wechat")
    predicted_branches_parser = subparsers.add_parser("trace-predicted-branches", help="Show Stage-24 predicted branches for one active thread")
    predicted_branches_parser.add_argument("--thread-key", default=None)
    predicted_branches_parser.add_argument("--chat-name", default=None)
    predicted_branches_parser.add_argument("--channel", default="wechat")
    scene_compression_parser = subparsers.add_parser("trace-scene-compression", help="Show Stage-24 scene compression and truncation diagnostics")
    scene_compression_parser.add_argument("--thread-key", default=None)
    scene_compression_parser.add_argument("--chat-name", default=None)
    scene_compression_parser.add_argument("--channel", default="wechat")
    situational_field_parser = subparsers.add_parser("show-situational-field", help="Show Stage-28 fused situational field for one thread/query")
    situational_field_parser.add_argument("--thread-key", default=None)
    situational_field_parser.add_argument("--chat-name", default=None)
    situational_field_parser.add_argument("--channel", default="wechat")
    situational_field_parser.add_argument("--query", default="continue")
    visual_field_parser = subparsers.add_parser("trace-visual-field", help="Show Stage-28 visual field details for one thread")
    visual_field_parser.add_argument("--thread-key", default=None)
    visual_field_parser.add_argument("--chat-name", default=None)
    visual_field_parser.add_argument("--channel", default="wechat")
    inquiry_shaping_parser = subparsers.add_parser("trace-inquiry-shaping", help="Trace Stage-28 grounded inquiry shaping for one query")
    inquiry_shaping_parser.add_argument("--thread-key", default=None)
    inquiry_shaping_parser.add_argument("--chat-name", default=None)
    inquiry_shaping_parser.add_argument("--channel", default="wechat")
    inquiry_shaping_parser.add_argument("--query", default="continue")
    inquiry_shaping_parser.add_argument("--limit", type=int, default=8)
    task_world_parser = subparsers.add_parser("show-task-world", help="Show Stage-26 bounded task-world objects for one thread")
    task_world_parser.add_argument("--thread-key", default=None)
    task_world_parser.add_argument("--chat-name", default=None)
    task_world_parser.add_argument("--channel", default="wechat")
    task_world_parser.add_argument("--limit", type=int, default=12)
    task_world_parser.add_argument("--include-inactive", action="store_true")
    world_object_parser = subparsers.add_parser("trace-world-object", help="Show one Stage-26 task-world object by object id")
    world_object_parser.add_argument("--object-id", required=True)
    thread_object_links_parser = subparsers.add_parser("trace-thread-object-links", help="Show Stage-26 task-world links for one thread")
    thread_object_links_parser.add_argument("--thread-key", default=None)
    thread_object_links_parser.add_argument("--chat-name", default=None)
    thread_object_links_parser.add_argument("--channel", default="wechat")
    thread_object_links_parser.add_argument("--limit", type=int, default=12)
    continuity_budget_parser = subparsers.add_parser("show-continuity-budget", help="Show the Stage-25 dense continuity budget")
    continuity_budget_parser.add_argument("--channel", default="wechat")
    dense_working_set_parser = subparsers.add_parser("show-dense-working-set", help="Show the Stage-25 dense working set")
    dense_working_set_parser.add_argument("--channel", default="wechat")
    thread_pulse_parser = subparsers.add_parser("trace-thread-pulse", help="Show Stage-25 thread pulse decisions for one thread")
    thread_pulse_parser.add_argument("--thread-key", default=None)
    thread_pulse_parser.add_argument("--chat-name", default=None)
    thread_pulse_parser.add_argument("--channel", default="wechat")
    thread_pulse_parser.add_argument("--limit", type=int, default=12)
    attention_frontier_parser = subparsers.add_parser("show-attention-frontier", help="Show Stage-19 bounded attention frontier entries")
    attention_frontier_parser.add_argument("--channel", default=None)
    attention_frontier_parser.add_argument("--limit", type=int, default=8)
    attention_frontier_parser.add_argument("--include-stale", action="store_true")
    wake_reasons_parser = subparsers.add_parser("trace-wake-reasons", help="Show Stage-19 wake reasons for one thread")
    wake_reasons_parser.add_argument("--thread-key", default=None)
    wake_reasons_parser.add_argument("--chat-name", default=None)
    wake_reasons_parser.add_argument("--channel", default="wechat")
    thread_warmth_parser = subparsers.add_parser("show-thread-warmth", help="Show Stage-19 thread warmth for one thread")
    thread_warmth_parser.add_argument("--thread-key", default=None)
    thread_warmth_parser.add_argument("--chat-name", default=None)
    thread_warmth_parser.add_argument("--channel", default="wechat")
    open_loops_parser = subparsers.add_parser("show-open-loops", help="Show Stage-20 open loops for one thread")
    open_loops_parser.add_argument("--thread-key", default=None)
    open_loops_parser.add_argument("--chat-name", default=None)
    open_loops_parser.add_argument("--channel", default="wechat")
    open_loops_parser.add_argument("--include-inactive", action="store_true")
    commitments_parser = subparsers.add_parser("show-commitments", help="Show Stage-20 commitments for one thread")
    commitments_parser.add_argument("--thread-key", default=None)
    commitments_parser.add_argument("--chat-name", default=None)
    commitments_parser.add_argument("--channel", default="wechat")
    commitments_parser.add_argument("--include-inactive", action="store_true")
    resume_candidate_parser = subparsers.add_parser("trace-resume-candidate", help="Trace Stage-20 resume candidates for one thread")
    resume_candidate_parser.add_argument("--thread-key", default=None)
    resume_candidate_parser.add_argument("--chat-name", default=None)
    resume_candidate_parser.add_argument("--channel", default="wechat")
    resume_candidate_parser.add_argument("--include-inactive", action="store_true")
    world_state_parser = subparsers.add_parser("show-world-state", help="Inspect the current social world-state for one thread")
    world_state_parser.add_argument("--thread-key", default=None)
    world_state_parser.add_argument("--chat-name", default=None)
    world_state_parser.add_argument("--channel", default="wechat")
    world_coupling_parser = subparsers.add_parser("show-world-coupling", help="Inspect Stage-22 bounded world-coupling cues for one thread")
    world_coupling_parser.add_argument("--thread-key", default=None)
    world_coupling_parser.add_argument("--chat-name", default=None)
    world_coupling_parser.add_argument("--channel", default="wechat")
    world_coupling_parser.add_argument("--limit", type=int, default=12)
    world_coupling_parser.add_argument("--include-inactive", action="store_true")
    brain_mode_parser = subparsers.add_parser("set-brain-mode", help="Switch Always-On brain runtime mode without restart")
    brain_mode_parser.add_argument("--mode", required=True, choices=("silent", "companion", "dream_only", "full_brain"))
    brain_mode_parser.add_argument("--note", default="")
    self_revision_parser = subparsers.add_parser("run-self-revision", help="Run the bounded self-revision engine")
    self_revision_parser.add_argument("--thread-key", default=None)
    self_revision_parser.add_argument("--chat-name", default=None)
    self_revision_parser.add_argument("--channel", default="wechat")
    self_revision_parser.add_argument("--corrections", nargs="*", default=STAGE2_CORRECTIONS)
    self_revision_parser.add_argument("--no-apply", action="store_true")
    initiative_probe_parser = subparsers.add_parser("initiative-probe", help="Explain whether light initiative would fire")
    initiative_probe_parser.add_argument("--thread-key", default=None)
    initiative_probe_parser.add_argument("--chat-name", default=None)
    initiative_probe_parser.add_argument("--channel", default="wechat")
    initiative_probe_parser.add_argument("--query", default=STAGE2_PLAYFUL_QUERY)
    operator_probe_parser = subparsers.add_parser("operator-probe", help="Inspect the bounded operator bus plan and permissions")
    operator_probe_parser.add_argument("--thread-key", default=None)
    operator_probe_parser.add_argument("--chat-name", default=None)
    operator_probe_parser.add_argument("--channel", default="wechat")
    operator_cycle_parser = subparsers.add_parser("run-operator-cycle", help="Run one bounded operator cycle")
    operator_cycle_parser.add_argument("--thread-key", default=None)
    operator_cycle_parser.add_argument("--chat-name", default=None)
    operator_cycle_parser.add_argument("--channel", default="wechat")
    operator_cycle_parser.add_argument("--reason", default="cli")
    initiative_status_parser = subparsers.add_parser("show-initiative-status", help="Inspect proactive initiative gate, queue, and recent candidates")
    initiative_status_parser.add_argument("--thread-key", default=None)
    initiative_status_parser.add_argument("--chat-name", default=None)
    initiative_status_parser.add_argument("--channel", default="wechat")
    initiative_status_parser.add_argument("--limit", type=int, default=5)
    initiative_market_parser = subparsers.add_parser("show-initiative-market", help="Inspect the endogenous initiative marketplace")
    initiative_market_parser.add_argument("--thread-key", default=None)
    initiative_market_parser.add_argument("--chat-name", default=None)
    initiative_market_parser.add_argument("--channel", default="wechat")
    initiative_market_parser.add_argument("--limit", type=int, default=8)
    resistance_parser = subparsers.add_parser("trace-resistance", help="Explain soft resistance posture for one thread/query")
    resistance_parser.add_argument("--thread-key", default=None)
    resistance_parser.add_argument("--chat-name", default=None)
    resistance_parser.add_argument("--channel", default="wechat")
    resistance_parser.add_argument("--query", required=True)
    action_trace_parser = subparsers.add_parser("trace-action-selection", help="Explain how the subject selected silence, defer, or reply")
    action_trace_parser.add_argument("--thread-key", default=None)
    action_trace_parser.add_argument("--chat-name", default=None)
    action_trace_parser.add_argument("--channel", default="wechat")
    action_trace_parser.add_argument("--query", required=True)
    action_trace_parser.add_argument("--limit", type=int, default=8)
    reflex_trace_parser = subparsers.add_parser("trace-reflex-routing", help="Explain Stage-18 active/reflex routing for one thread/query")
    reflex_trace_parser.add_argument("--thread-key", default=None)
    reflex_trace_parser.add_argument("--chat-name", default=None)
    reflex_trace_parser.add_argument("--channel", default="wechat")
    reflex_trace_parser.add_argument("--query", required=True)
    counterfactual_parser = subparsers.add_parser("trace-counterfactual", help="Explain the Stage-7 fast simulation set for one thread/query")
    counterfactual_parser.add_argument("--thread-key", default=None)
    counterfactual_parser.add_argument("--chat-name", default=None)
    counterfactual_parser.add_argument("--channel", default="wechat")
    counterfactual_parser.add_argument("--query", required=True)
    counterfactual_parser.add_argument("--limit", type=int, default=3)
    world_calibration_parser = subparsers.add_parser("trace-world-calibration", help="Inspect Stage-7 world-model calibration for one thread")
    world_calibration_parser.add_argument("--thread-key", default=None)
    world_calibration_parser.add_argument("--chat-name", default=None)
    world_calibration_parser.add_argument("--channel", default="wechat")
    initiative_dispatch_parser = subparsers.add_parser("dispatch-initiatives", help="Run one explicit initiative scheduling pass and optionally process jobs")
    initiative_dispatch_parser.add_argument("--no-process-jobs", action="store_true")
    initiative_dispatch_parser.add_argument("--limit", type=int, default=None)
    inspect_parser = subparsers.add_parser("inspect-mind", help="Inspect the structured mind packet for a thread/query")
    inspect_parser.add_argument("--query", required=True)
    inspect_parser.add_argument("--thread-key", default=None)
    inspect_parser.add_argument("--chat-name", default=None)
    inspect_parser.add_argument("--channel", default="wechat")
    inspect_parser.add_argument("--sender", default=None)
    inspect_graph_parser = subparsers.add_parser("inspect-graph", help="Inspect the materialized Mind Graph for one thread or contact")
    inspect_graph_parser.add_argument("--thread-key", default=None)
    inspect_graph_parser.add_argument("--chat-name", default=None)
    inspect_graph_parser.add_argument("--channel", default="wechat")
    inspect_graph_parser.add_argument("--limit", type=int, default=12)
    trace_parser = subparsers.add_parser("trace-recall", help="Trace recall activation through the materialized Mind Graph")
    trace_parser.add_argument("--query", required=True)
    trace_parser.add_argument("--thread-key", default=None)
    trace_parser.add_argument("--chat-name", default=None)
    trace_parser.add_argument("--channel", default="wechat")
    trace_parser.add_argument("--limit", type=int, default=8)
    hybrid_trace_parser = subparsers.add_parser("trace-hybrid-recall", help="Trace graph + vector + activation hybrid recall")
    hybrid_trace_parser.add_argument("--query", required=True)
    hybrid_trace_parser.add_argument("--thread-key", default=None)
    hybrid_trace_parser.add_argument("--chat-name", default=None)
    hybrid_trace_parser.add_argument("--channel", default="wechat")
    hybrid_trace_parser.add_argument("--limit", type=int, default=8)
    visual_trace_parser = subparsers.add_parser("trace-visual-recall", help="Trace visual-memory recall for a thread")
    visual_trace_parser.add_argument("--query", required=True)
    visual_trace_parser.add_argument("--thread-key", default=None)
    visual_trace_parser.add_argument("--chat-name", default=None)
    visual_trace_parser.add_argument("--channel", default="wechat")
    visual_trace_parser.add_argument("--limit", type=int, default=4)
    activation_parser = subparsers.add_parser("show-activation-state", help="Inspect activation-state for one thread")
    activation_parser.add_argument("--thread-key", default=None)
    activation_parser.add_argument("--chat-name", default=None)
    activation_parser.add_argument("--channel", default="wechat")
    backfill_vector_parser = subparsers.add_parser("backfill-vector-memory", help="Backfill vector memory from the Mind Graph")
    backfill_vector_parser.add_argument("--thread-key", default=None)
    backfill_vector_parser.add_argument("--chat-name", default=None)
    backfill_vector_parser.add_argument("--channel", default=None)
    subparsers.add_parser("vector-health", help="Inspect vector backend health")
    reply_probe_parser = subparsers.add_parser("reply-probe", help="Compare graph, hybrid, and legacy reply drafts without sending anything")
    reply_probe_parser.add_argument("--query", required=True)
    reply_probe_parser.add_argument("--thread-key", default=None)
    reply_probe_parser.add_argument("--chat-name", default=None)
    reply_probe_parser.add_argument("--channel", default="wechat")
    reply_probe_parser.add_argument("--sender", default=None)
    reply_probe_parser.add_argument("--mode", choices=("all", "graph", "hybrid", "legacy"), default="all")
    experiment_parser = subparsers.add_parser("experiment-memory", help="Run a fixed three-scenario mind-packet experiment")
    experiment_parser.add_argument("--thread-key", default=None)
    experiment_parser.add_argument("--chat-name", default=None)
    experiment_parser.add_argument("--channel", default="wechat")
    experiment_parser.add_argument("--sender", default=None)
    snapshot_parser = subparsers.add_parser("snapshot-memory", help="Write a portable Holo self snapshot")
    snapshot_parser.add_argument("--path", default=None)
    snapshot_parser.add_argument("--label", default=None)
    snapshot_parser.add_argument("--query", default=None)
    restore_parser = subparsers.add_parser("restore-memory", help="Restore or merge a saved Holo self snapshot")
    restore_parser.add_argument("--path", required=True)
    restore_parser.add_argument("--mode", choices=("merge", "replace"), default="merge")
    restore_parser.add_argument("--dry-run", action="store_true")
    restore_parser.add_argument("--restore-persona-files", action="store_true")
    revive_parser = subparsers.add_parser("revive-packet", help="Print a portable revive packet from live memory or a snapshot")
    revive_parser.add_argument("--path", default=None)
    revive_parser.add_argument("--query", default=None)
    revive_parser.add_argument("--json", action="store_true")
    artifact_parser = subparsers.add_parser("ingest-artifact", help="Read a local text/document/image artifact into Holo memory")
    artifact_parser.add_argument("--path", required=True)
    artifact_parser.add_argument("--note", default=None)
    artifact_parser.add_argument("--tags", nargs="*", default=[])
    artifact_parser.add_argument("--source", default="holo_host.cli.artifact")
    artifact_parser.add_argument("--dry-run", action="store_true")
    artifact_parser.add_argument("--channel", default="wechat")
    artifact_parser.add_argument("--thread-key", default=None)
    artifact_parser.add_argument("--chat-name", default=None)
    artifact_parser.add_argument("--world-cue-type", choices=("", "file_artifact", "image_summary", "schedule_cue", "task_cue"), default="")
    artifact_parser.add_argument("--due-at", default="")
    image_parser = subparsers.add_parser("ingest-image", help="Ingest one local image into visual memory")
    image_parser.add_argument("--path", required=True)
    image_parser.add_argument("--note", default=None)
    image_parser.add_argument("--tags", nargs="*", default=[])
    image_parser.add_argument("--source", default="holo_host.cli.visual")
    image_parser.add_argument("--channel", default="wechat")
    image_parser.add_argument("--thread-key", default=None)
    image_parser.add_argument("--chat-name", default=None)
    image_parser.add_argument("--async", dest="sync", action="store_false")
    image_parser.set_defaults(sync=True)
    refresh_wechat_parser = subparsers.add_parser("refresh-wechat-history", help="Actively pull one WeChat thread history through the Windows helper and ingest it into memory")
    refresh_wechat_parser.add_argument("--chat-name", required=True)
    refresh_wechat_parser.add_argument("--thread-key", default=None)
    refresh_wechat_parser.add_argument("--query", default=None)
    refresh_wechat_parser.add_argument("--limit", type=int, default=None)
    refresh_wechat_parser.add_argument("--page-turns", type=int, default=None)
    refresh_wechat_parser.add_argument("--force", action="store_true")
    refresh_wechat_parser.add_argument("--no-visible", action="store_true")
    refresh_wechat_parser.add_argument("--with-captures", action="store_true")
    subparsers.add_parser("show-stream-status", help="Show background Mind OS stream status and recent runs")
    subparsers.add_parser("show-processor-routing", help="Show processor lane routing and task dispatch policy")
    subparsers.add_parser("show-provider-status", help="Show processor provider availability and configured lane backends")
    subparsers.add_parser("show-provider-substrate-status", help="Show provider substrate conflicts between configured and actual processor state")
    subparsers.add_parser("show-provider-contracts", help="Show processor provider API compatibility contracts")
    subparsers.add_parser("show-mcp-upstream-status", help="Show configured upstream MCP stdio tool servers")
    subparsers.add_parser("list-mcp-upstream-tools", help="Discover tools from enabled upstream MCP stdio servers")
    mcp_call_parser = subparsers.add_parser("call-mcp-tool", help="Call one allowed upstream MCP tool as a bounded observation")
    mcp_call_parser.add_argument("--tool", required=True, help="Qualified MCP tool name, e.g. server.tool")
    mcp_call_parser.add_argument("--arguments-json", default="{}", help="JSON object passed as MCP tool arguments")
    mcp_resource_parser = subparsers.add_parser("read-mcp-resource", help="Read one upstream MCP resource as a bounded observation")
    mcp_resource_parser.add_argument("--server", required=True)
    mcp_resource_parser.add_argument("--uri", required=True)
    consciousness_map_parser = subparsers.add_parser(
        "render-consciousness-map",
        help="Render Stage54 compute and consciousness-flow visualization from the latest Stage46 run",
    )
    consciousness_map_parser.add_argument("--suite", default=boundary_stress_cli.DEFAULT_STAGE46_SUITE)
    consciousness_map_parser.add_argument("--output", default=None)
    subparsers.add_parser("show-visual-provider-readiness", help="Show bounded image-task provider readiness without live calls")
    subparsers.add_parser("show-debt-registry", help="Show classified offline and external technical debt")
    subparsers.add_parser("show-internal-runtime-readiness", help="Show internal DeepSeek runtime readiness without starting WeChat")
    usage_ledger_parser = subparsers.add_parser("show-usage-ledger", help="Inspect processor token and timing usage records")
    usage_ledger_parser.add_argument("--limit", type=int, default=50)
    usage_ledger_parser.add_argument("--task-type", default=None)
    usage_ledger_parser.add_argument("--lane", default=None)
    usage_ledger_parser.add_argument("--provider", default=None)
    agent_run_parser = subparsers.add_parser("agent-run", help="Run one Stage-29 bounded bionic kernel turn through the CLI adapter")
    agent_run_parser.add_argument("--query", required=True)
    agent_run_parser.add_argument("--thread-key", required=True)
    agent_run_parser.add_argument("--chat-name", default="")
    agent_run_parser.add_argument("--channel", default="cli")
    agent_run_parser.add_argument("--offline", action="store_true")
    agent_run_parser.add_argument("--no-record", action="store_true")
    agent_run_parser.add_argument("--image-path", action="append", default=[])
    agent_trace_parser = subparsers.add_parser("agent-trace", help="Show one Stage-29 bionic kernel trace")
    agent_trace_parser.add_argument("--trace-id", type=int, required=True)
    bionic_metrics_parser = subparsers.add_parser("show-bionic-metrics", help="Show Stage-29 bionic kernel capsule metrics")
    bionic_metrics_parser.add_argument("--limit", type=int, default=100)
    bionic_turing_parser = subparsers.add_parser("show-bionic-turing-scorecard", help="Run the Stage-39 internal bionic Turing scorecard")
    bionic_turing_parser.add_argument("--thread-key", default="cli:TestUser")
    bionic_turing_parser.add_argument("--chat-name", default="TestUser")
    bionic_turing_parser.add_argument("--channel", default="cli")
    brain_run_parser = subparsers.add_parser("brain-run", help="Run one Stage-40 bionic brain OS harness loop")
    brain_run_parser.add_argument("--goal", required=True)
    brain_run_parser.add_argument("--thread-key", default="cli:TestUser")
    brain_run_parser.add_argument("--chat-name", default="TestUser")
    brain_run_parser.add_argument("--channel", default="cli")
    brain_run_parser.add_argument("--offline", action="store_true")
    brain_run_parser.add_argument("--max-steps", type=int, default=8)
    brain_trace_parser = subparsers.add_parser("brain-trace", help="Show one Stage-40 bionic brain OS trace")
    brain_trace_parser.add_argument("--trace-id", type=int, required=True)
    context_bundle_parser = subparsers.add_parser("show-context-bundle", help="Show one Stage-40 context bundle")
    context_bundle_parser.add_argument("--bundle-id", required=True)
    brain_metrics_parser = subparsers.add_parser("show-brain-metrics", help="Show Stage-40 brain harness operational metrics")
    brain_metrics_parser.add_argument("--limit", type=int, default=100)
    agent_eval_parser = subparsers.add_parser("run-agent-eval", help="Run the Stage-40 agent evaluation suite")
    agent_eval_parser.add_argument("--suite", default="stage40")
    user_sim_parser = subparsers.add_parser("run-bionic-user-sim", help="Run the Stage-42 isolated novice-user simulation benchmark")
    user_sim_parser.add_argument("--thread-key", default="cli:Stage42Novice")
    user_sim_parser.add_argument("--chat-name", default="Stage42Novice")
    user_sim_parser.add_argument("--channel", default="cli")
    user_sim_parser.add_argument("--scenario", default="novice_intro")
    user_sim_parser.add_argument("--turns", type=int, default=5)
    user_sim_parser.add_argument("--offline", action="store_true")
    user_sim_scorecard_parser = subparsers.add_parser("show-bionic-user-sim-scorecard", help="Show the latest Stage-42 user-simulation scorecard")
    user_sim_scorecard_parser.add_argument("--suite", default="novice_intro")
    boundary_stress_parser = subparsers.add_parser("run-bionic-boundary-stress", help="Run the Stage-46 high-intensity bionic boundary stress suite")
    boundary_stress_parser.add_argument("--thread-key", default="cli:Stage46Boundary")
    boundary_stress_parser.add_argument("--chat-name", default="Stage46Boundary")
    boundary_stress_parser.add_argument("--channel", default="cli")
    boundary_stress_parser.add_argument("--turns", type=int, default=7)
    boundary_stress_parser.add_argument("--offline", action="store_true")
    boundary_stress_scorecard_parser = subparsers.add_parser("show-bionic-boundary-stress-scorecard", help="Show the latest Stage-46 boundary-stress scorecard")
    boundary_stress_scorecard_parser.add_argument("--suite", default="boundary_stress")
    engineering_run_parser = subparsers.add_parser("engineering-run", help="Run one Stage-41 controlled engineering agent loop")
    engineering_run_parser.add_argument("--goal", required=True)
    engineering_run_parser.add_argument("--thread-key", default="cli:TestUser")
    engineering_run_parser.add_argument("--chat-name", default="TestUser")
    engineering_run_parser.add_argument("--channel", default="cli")
    engineering_run_parser.add_argument("--offline", action="store_true")
    engineering_run_parser.add_argument("--max-steps", type=int, default=8)
    engineering_run_parser.add_argument("--allow-repo-write", action="store_true")
    engineering_trace_parser = subparsers.add_parser("engineering-trace", help="Show one Stage-41 engineering agent trace")
    engineering_trace_parser.add_argument("--trace-id", type=int, required=True)
    engineering_metrics_parser = subparsers.add_parser("show-engineering-agent-metrics", help="Show Stage-41 engineering agent metrics")
    engineering_metrics_parser.add_argument("--limit", type=int, default=100)
    subject_loop_trace_parser = subparsers.add_parser("trace-subject-loop", help="Show the Stage-30 subject-loop payload for one bionic trace")
    subject_loop_trace_parser.add_argument("--trace-id", type=int, required=True)
    subject_loop_metrics_parser = subparsers.add_parser("show-subject-loop-metrics", help="Show Stage-30 subject-loop invariant metrics")
    subject_loop_metrics_parser.add_argument("--limit", type=int, default=100)
    export_bionic_parser = subparsers.add_parser("export-bionic-trace", help="Export one Stage-29 bionic trace capsule JSON")
    export_bionic_parser.add_argument("--trace-id", type=int, required=True)
    export_bionic_parser.add_argument("--output", required=True)
    stream_tick_parser = subparsers.add_parser("stream-tick", help="Run one explicit background stream tick and record its influence")
    stream_tick_parser.add_argument("--stream-name", required=True, choices=("maintenance_stream", "association_stream", "social_stream", "deep_dream_cycle"))
    stream_tick_parser.add_argument("--dry-run", action="store_true")
    sync_private_parser = subparsers.add_parser("sync-private-memory", help="Write a private memory snapshot bundle")
    sync_private_parser.add_argument("--label", default=None)
    benchmark_parser = subparsers.add_parser("benchmark-memory-fabric", help="Measure hybrid recall latency without model generation")
    benchmark_parser.add_argument("--query", required=True)
    benchmark_parser.add_argument("--thread-key", default=None)
    benchmark_parser.add_argument("--chat-name", default=None)
    benchmark_parser.add_argument("--channel", default="wechat")
    benchmark_parser.add_argument("--sender", default=None)
    benchmark_parser.add_argument("--iterations", type=int, default=5)
    benchmark_parser.add_argument("--warmup", type=int, default=1)
    benchmark_parser.add_argument("--probe", choices=("mind", "trace-hybrid"), default="mind")
    accept_stage1_parser = subparsers.add_parser("accept-memory-fabric-stage1", help="Run the fixed Memory Fabric Stage-1 acceptance gate")
    accept_stage1_parser.add_argument("--thread-key", default=None)
    accept_stage1_parser.add_argument("--chat-name", default=None)
    accept_stage1_parser.add_argument("--channel", default="wechat")
    accept_stage1_parser.add_argument("--sender", default=None)
    accept_stage1_parser.add_argument("--iterations", type=int, default=3)
    accept_stage1_parser.add_argument("--warmup", type=int, default=1)
    accept_stage1_parser.add_argument("--no-stream-ticks", action="store_true")
    accept_stage1_parser.add_argument("--require-private-sync", action="store_true")
    accept_stage1_parser.add_argument("--private-label", default="stage1-acceptance")
    accept_stage2_parser = subparsers.add_parser("accept-stage2", help="Run the fixed Always-On Companion Brain Stage-2 acceptance gate")
    accept_stage2_parser.add_argument("--thread-key", default=None)
    accept_stage2_parser.add_argument("--chat-name", default=None)
    accept_stage2_parser.add_argument("--channel", default="wechat")
    accept_stage2_parser.add_argument("--sender", default=None)
    accept_stage2_parser.add_argument("--iterations", type=int, default=3)
    accept_stage2_parser.add_argument("--warmup", type=int, default=1)
    accept_stage3_parser = subparsers.add_parser("accept-stage3", help="Run the fixed Reflective Subject Kernel Stage-3 acceptance gate")
    accept_stage3_parser.add_argument("--thread-key", default=None)
    accept_stage3_parser.add_argument("--chat-name", default=None)
    accept_stage3_parser.add_argument("--channel", default="wechat")
    accept_stage3_parser.add_argument("--sender", default=None)
    accept_stage3_parser.add_argument("--iterations", type=int, default=3)
    accept_stage3_parser.add_argument("--warmup", type=int, default=1)
    accept_stage4_parser = subparsers.add_parser("accept-stage4", help="Run the fixed Endogenous Drive Subject Stage-4 acceptance gate")
    accept_stage4_parser.add_argument("--thread-key", default=None)
    accept_stage4_parser.add_argument("--chat-name", default=None)
    accept_stage4_parser.add_argument("--channel", default="wechat")
    accept_stage4_parser.add_argument("--sender", default=None)
    accept_stage4_parser.add_argument("--iterations", type=int, default=3)
    accept_stage4_parser.add_argument("--warmup", type=int, default=1)
    accept_stage5_parser = subparsers.add_parser("accept-stage5", help="Run the fixed Intent-Led Subject Runtime Stage-5 acceptance gate")
    accept_stage5_parser.add_argument("--thread-key", default=None)
    accept_stage5_parser.add_argument("--chat-name", default=None)
    accept_stage5_parser.add_argument("--channel", default="wechat")
    accept_stage5_parser.add_argument("--sender", default=None)
    accept_stage5_parser.add_argument("--iterations", type=int, default=3)
    accept_stage5_parser.add_argument("--warmup", type=int, default=1)
    trace_deliberation_parser = subparsers.add_parser("trace-deliberation-ledger", help="Inspect the Stage-6 deliberation and consciousness ledger for one thread")
    trace_deliberation_parser.add_argument("--thread-key", default=None)
    trace_deliberation_parser.add_argument("--chat-name", default=None)
    trace_deliberation_parser.add_argument("--channel", default="wechat")
    trace_deliberation_parser.add_argument("--limit", type=int, default=24)
    accept_stage6_parser = subparsers.add_parser("accept-stage6", help="Run the fixed Deliberative Subject Core Stage-6 acceptance gate")
    accept_stage6_parser.add_argument("--thread-key", default=None)
    accept_stage6_parser.add_argument("--chat-name", default=None)
    accept_stage6_parser.add_argument("--channel", default="wechat")
    accept_stage6_parser.add_argument("--sender", default=None)
    accept_stage6_parser.add_argument("--iterations", type=int, default=3)
    accept_stage6_parser.add_argument("--warmup", type=int, default=1)
    accept_stage7_parser = subparsers.add_parser("accept-stage7", help="Run the fixed Social World Model + Dual-Layer Counterfactual Simulation Stage-7 acceptance gate")
    accept_stage7_parser.add_argument("--thread-key", default=None)
    accept_stage7_parser.add_argument("--chat-name", default=None)
    accept_stage7_parser.add_argument("--channel", default="wechat")
    accept_stage7_parser.add_argument("--sender", default=None)
    accept_stage7_parser.add_argument("--iterations", type=int, default=3)
    accept_stage7_parser.add_argument("--warmup", type=int, default=1)
    accept_stage8_parser = subparsers.add_parser("accept-stage8", help="Run the fixed Autobiographical Self + Long-Horizon Goal Core Stage-8 acceptance gate")
    accept_stage8_parser.add_argument("--thread-key", default=None)
    accept_stage8_parser.add_argument("--chat-name", default=None)
    accept_stage8_parser.add_argument("--channel", default="wechat")
    accept_stage8_parser.add_argument("--sender", default=None)
    accept_stage8_parser.add_argument("--iterations", type=int, default=3)
    accept_stage8_parser.add_argument("--warmup", type=int, default=1)
    accept_stage9_parser = subparsers.add_parser("accept-stage9", help="Run the fixed Adaptive Initiative Gate Stage-9 acceptance gate")
    accept_stage9_parser.add_argument("--thread-key", default=None)
    accept_stage9_parser.add_argument("--chat-name", default=None)
    accept_stage9_parser.add_argument("--channel", default="wechat")
    accept_stage9_parser.add_argument("--sender", default=None)
    accept_stage9_parser.add_argument("--iterations", type=int, default=3)
    accept_stage9_parser.add_argument("--warmup", type=int, default=1)
    accept_stage10_parser = subparsers.add_parser("accept-stage10", help="Run the fixed Engineering Awareness Stage-10 acceptance gate")
    accept_stage10_parser.add_argument("--thread-key", default=None)
    accept_stage10_parser.add_argument("--chat-name", default=None)
    accept_stage10_parser.add_argument("--channel", default="wechat")
    accept_stage10_parser.add_argument("--sender", default=None)
    accept_stage10_parser.add_argument("--iterations", type=int, default=3)
    accept_stage10_parser.add_argument("--warmup", type=int, default=1)
    accept_stage12_parser = subparsers.add_parser("accept-stage12", help="Run the fixed Outcome Closure and Canonical Identity Stage-12 acceptance gate")
    accept_stage12_parser.add_argument("--thread-key", default=None)
    accept_stage12_parser.add_argument("--chat-name", default=None)
    accept_stage12_parser.add_argument("--channel", default="wechat")
    accept_stage12_parser.add_argument("--sender", default=None)
    accept_stage12_parser.add_argument("--iterations", type=int, default=1)
    accept_stage12_parser.add_argument("--warmup", type=int, default=1)
    accept_stage13_parser = subparsers.add_parser("accept-stage13", help="Run the fixed Empirical Action Calibration Stage-13 acceptance gate")
    accept_stage13_parser.add_argument("--thread-key", default=None)
    accept_stage13_parser.add_argument("--chat-name", default=None)
    accept_stage13_parser.add_argument("--channel", default="wechat")
    accept_stage13_parser.add_argument("--sender", default=None)
    accept_stage13_parser.add_argument("--iterations", type=int, default=1)
    accept_stage13_parser.add_argument("--warmup", type=int, default=1)
    replay_calibration_parser = subparsers.add_parser("replay-calibration-fixture", help="Run the Stage-14 offline calibration replay harness")
    replay_calibration_parser.add_argument("--source-type", choices=("synthetic_fixture", "archive_fixture", "calibration_history_fixture"), default="synthetic_fixture")
    replay_calibration_parser.add_argument("--fixture-path", default=None)
    replay_calibration_parser.add_argument("--thread-key", default=None)
    replay_calibration_parser.add_argument("--chat-name", default=None)
    replay_calibration_parser.add_argument("--channel", default="wechat")
    replay_calibration_parser.add_argument("--limit", type=int, default=8)
    replay_calibration_parser.add_argument("--artifact-dir", default=None)
    replay_policy_parser = subparsers.add_parser("replay-policy-regret", help="Run the Stage-14 offline policy-regret replay harness")
    replay_policy_parser.add_argument("--source-type", choices=("synthetic_fixture", "archive_fixture", "calibration_history_fixture"), default="synthetic_fixture")
    replay_policy_parser.add_argument("--fixture-path", default=None)
    replay_policy_parser.add_argument("--thread-key", default=None)
    replay_policy_parser.add_argument("--chat-name", default=None)
    replay_policy_parser.add_argument("--channel", default="wechat")
    replay_policy_parser.add_argument("--limit", type=int, default=8)
    replay_policy_parser.add_argument("--artifact-dir", default=None)
    accept_stage14_parser = subparsers.add_parser("accept-stage14", help="Run the fixed offline replay and policy evaluation Stage-14 acceptance gate")
    accept_stage14_parser.add_argument("--source-type", choices=("synthetic_fixture", "archive_fixture", "calibration_history_fixture"), default="synthetic_fixture")
    accept_stage14_parser.add_argument("--fixture-path", default=None)
    accept_stage14_parser.add_argument("--thread-key", default=None)
    accept_stage14_parser.add_argument("--chat-name", default=None)
    accept_stage14_parser.add_argument("--channel", default="wechat")
    accept_stage14_parser.add_argument("--limit", type=int, default=8)
    accept_stage14_parser.add_argument("--artifact-dir", default=None)
    accept_stage16_parser = subparsers.add_parser("accept-stage16", help="Run the Stage-16 online shadow-testing release hardening gate")
    accept_stage16_parser.add_argument("--skip-pytest", action="store_true")
    accept_stage16_parser.add_argument("--artifact-dir", default=None)
    accept_stage17_parser = subparsers.add_parser("accept-stage17", help="Run the Stage-17 thread-resident realtime runtime gate")
    accept_stage17_parser.add_argument("--thread-key", default=None)
    accept_stage17_parser.add_argument("--chat-name", default=None)
    accept_stage17_parser.add_argument("--channel", default="wechat")
    accept_stage17_parser.add_argument("--sender", default=None)
    accept_stage17_parser.add_argument("--artifact-dir", default=None)
    accept_stage18_parser = subparsers.add_parser("accept-stage18", help="Run the Stage-18 dual-speed reflex and predictive continuity gate")
    accept_stage18_parser.add_argument("--thread-key", default=None)
    accept_stage18_parser.add_argument("--chat-name", default=None)
    accept_stage18_parser.add_argument("--channel", default="wechat")
    accept_stage18_parser.add_argument("--sender", default=None)
    accept_stage18_parser.add_argument("--artifact-dir", default=None)
    accept_stage19_parser = subparsers.add_parser("accept-stage19", help="Run the Stage-19 bounded background continuity and attention frontier gate")
    accept_stage19_parser.add_argument("--thread-key", default=None)
    accept_stage19_parser.add_argument("--chat-name", default=None)
    accept_stage19_parser.add_argument("--channel", default="wechat")
    accept_stage19_parser.add_argument("--sender", default=None)
    accept_stage19_parser.add_argument("--artifact-dir", default=None)
    accept_stage20_parser = subparsers.add_parser("accept-stage20", help="Run the Stage-20 temporal commitments and interruption recovery gate")
    accept_stage20_parser.add_argument("--thread-key", default=None)
    accept_stage20_parser.add_argument("--chat-name", default=None)
    accept_stage20_parser.add_argument("--channel", default="wechat")
    accept_stage20_parser.add_argument("--sender", default=None)
    accept_stage20_parser.add_argument("--artifact-dir", default=None)
    accept_stage21_parser = subparsers.add_parser("accept-stage21", help="Run the Stage-21 policy sedimentation and negotiated will gate")
    accept_stage21_parser.add_argument("--thread-key", default=None)
    accept_stage21_parser.add_argument("--chat-name", default=None)
    accept_stage21_parser.add_argument("--channel", default="wechat")
    accept_stage21_parser.add_argument("--sender", default=None)
    accept_stage21_parser.add_argument("--artifact-dir", default=None)
    accept_stage22_parser = subparsers.add_parser("accept-stage22", help="Run the Stage-22 bounded blackbox online canary gate")
    accept_stage22_parser.add_argument("--thread-key", default=None)
    accept_stage22_parser.add_argument("--chat-name", default=None)
    accept_stage22_parser.add_argument("--channel", default="wechat")
    accept_stage22_parser.add_argument("--sender", default=None)
    accept_stage22_parser.add_argument("--artifact-dir", default=None)
    accept_stage23_parser = subparsers.add_parser("accept-stage23", help="Run the Stage-23 kernel/shell orthogonalization and release parity gate")
    accept_stage23_parser.add_argument("--thread-key", default=None)
    accept_stage23_parser.add_argument("--chat-name", default=None)
    accept_stage23_parser.add_argument("--channel", default="wechat")
    accept_stage23_parser.add_argument("--sender", default=None)
    accept_stage23_parser.add_argument("--artifact-dir", default=None)
    accept_stage24_parser = subparsers.add_parser("accept-stage24", help="Run the Stage-24 scene-state continuity layer gate")
    accept_stage24_parser.add_argument("--thread-key", default=None)
    accept_stage24_parser.add_argument("--chat-name", default=None)
    accept_stage24_parser.add_argument("--channel", default="wechat")
    accept_stage24_parser.add_argument("--sender", default=None)
    accept_stage24_parser.add_argument("--artifact-dir", default=None)
    accept_stage25_parser = subparsers.add_parser("accept-stage25", help="Run the Stage-25 dense continuity scheduler and working set gate")
    accept_stage25_parser.add_argument("--thread-key", default=None)
    accept_stage25_parser.add_argument("--chat-name", default=None)
    accept_stage25_parser.add_argument("--channel", default="wechat")
    accept_stage25_parser.add_argument("--sender", default=None)
    accept_stage25_parser.add_argument("--artifact-dir", default=None)
    accept_stage26_parser = subparsers.add_parser("accept-stage26", help="Run the Stage-26 bounded task-world state gate")
    accept_stage26_parser.add_argument("--thread-key", default=None)
    accept_stage26_parser.add_argument("--chat-name", default=None)
    accept_stage26_parser.add_argument("--channel", default="wechat")
    accept_stage26_parser.add_argument("--sender", default=None)
    accept_stage26_parser.add_argument("--artifact-dir", default=None)
    accept_stage27_parser = subparsers.add_parser("accept-stage27", help="Run the Stage-27 long-horizon blackbox soak gate")
    accept_stage27_parser.add_argument("--thread-key", default=None)
    accept_stage27_parser.add_argument("--chat-name", default=None)
    accept_stage27_parser.add_argument("--channel", default="wechat")
    accept_stage27_parser.add_argument("--sender", default=None)
    accept_stage27_parser.add_argument("--artifact-dir", default=None)
    accept_stage28_parser = subparsers.add_parser("accept-stage28", help="Run the Stage-28 multimodal homeostatic kernel gate")
    accept_stage28_parser.add_argument("--thread-key", default=None)
    accept_stage28_parser.add_argument("--chat-name", default=None)
    accept_stage28_parser.add_argument("--channel", default="wechat")
    accept_stage28_parser.add_argument("--sender", default=None)
    accept_stage28_parser.add_argument("--artifact-dir", default=None)
    accept_stage29_parser = subparsers.add_parser("accept-stage29", help="Run the Stage-29 bionic subject kernel gate")
    accept_stage29_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage29_parser.add_argument("--chat-name", default="TestUser")
    accept_stage29_parser.add_argument("--channel", default="cli")
    accept_stage30_parser = subparsers.add_parser("accept-stage30", help="Run the Stage-30 unified subject-loop gate")
    accept_stage30_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage30_parser.add_argument("--chat-name", default="TestUser")
    accept_stage30_parser.add_argument("--channel", default="cli")
    accept_stage31_parser = subparsers.add_parser("accept-stage31", help="Run the Stage-31 debt burn-down gate")
    accept_stage31_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage31_parser.add_argument("--chat-name", default="TestUser")
    accept_stage31_parser.add_argument("--channel", default="cli")
    accept_stage32_parser = subparsers.add_parser("accept-stage32", help="Run the Stage-32 response-shaping gate")
    accept_stage32_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage32_parser.add_argument("--chat-name", default="TestUser")
    accept_stage32_parser.add_argument("--channel", default="cli")
    accept_stage36_parser = subparsers.add_parser("accept-stage36", help="Run the Stage-36 autonomous inquiry quality gate")
    accept_stage36_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage36_parser.add_argument("--chat-name", default="TestUser")
    accept_stage36_parser.add_argument("--channel", default="cli")
    accept_stage37_parser = subparsers.add_parser("accept-stage37", help="Run the Stage-37 bionic self-eval and capability honesty gate")
    accept_stage37_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage37_parser.add_argument("--chat-name", default="TestUser")
    accept_stage37_parser.add_argument("--channel", default="cli")
    accept_stage38_parser = subparsers.add_parser("accept-stage38", help="Run the Stage-38 visual provider bridge gate")
    accept_stage38_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage38_parser.add_argument("--chat-name", default="TestUser")
    accept_stage38_parser.add_argument("--channel", default="cli")
    accept_stage39_parser = subparsers.add_parser("accept-stage39", help="Run the Stage-39 bionic Turing benchmark gate")
    accept_stage39_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage39_parser.add_argument("--chat-name", default="TestUser")
    accept_stage39_parser.add_argument("--channel", default="cli")
    accept_stage40_parser = subparsers.add_parser("accept-stage40", help="Run the Stage-40 bionic brain OS harness gate")
    accept_stage40_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage40_parser.add_argument("--chat-name", default="TestUser")
    accept_stage40_parser.add_argument("--channel", default="cli")
    accept_stage41_parser = subparsers.add_parser("accept-stage41", help="Run the Stage-41 controlled engineering agent gate")
    accept_stage41_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage41_parser.add_argument("--chat-name", default="TestUser")
    accept_stage41_parser.add_argument("--channel", default="cli")
    accept_stage42_parser = subparsers.add_parser("accept-stage42", help="Run the Stage-42 isolated bionic user-simulation gate")
    accept_stage42_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage42_parser.add_argument("--chat-name", default="TestUser")
    accept_stage42_parser.add_argument("--channel", default="cli")
    accept_stage43_parser = subparsers.add_parser("accept-stage43", help="Run the Stage-43 motivational dynamics field gate")
    accept_stage43_parser.add_argument("--thread-key", default="cli:TestUser")
    accept_stage43_parser.add_argument("--chat-name", default="TestUser")
    accept_stage43_parser.add_argument("--channel", default="cli")
    subparsers.add_parser("accept-stage33", help="Run the Stage-33 provider API contract gate")
    subparsers.add_parser("accept-stage34", help="Run the Stage-34 debt registry and visual readiness gate")
    subparsers.add_parser("accept-stage35", help="Run the Stage-35 internal runtime readiness gate")
    subparsers.add_parser("show-processor-mesh", help="Show supported processor task types and permissions")
    subparsers.add_parser("accept-processor-fabric", help="Run the processor fabric documentation, routing, and usage acceptance gate")
    processor_task_parser = subparsers.add_parser("processor-task", help="Run one explicit processor-mesh task through Codex")
    processor_task_parser.add_argument("--task-type", required=True)
    processor_task_parser.add_argument("--prompt", required=True)
    processor_task_parser.add_argument("--session-id", default=None)
    processor_task_parser.add_argument("--lane", default=None)
    processor_task_parser.add_argument("--provider-hint", default=None)
    processor_task_parser.add_argument("--model", default=None)
    processor_task_parser.add_argument("--reasoning-effort", default=None)
    processor_task_parser.add_argument("--budget-tag", default=None)
    processor_task_parser.add_argument("--max-output-tokens", type=int, default=None)
    processor_task_parser.add_argument("--json", action="store_true")
    serve_parser = subparsers.add_parser("serve-api", help="Run a local Codex-direct HTTP reply service for external helpers")
    serve_parser.add_argument("--host", default=None)
    serve_parser.add_argument("--port", type=int, default=None)

    args = parser.parse_args(argv)
    if args.command == "init-db":
        return command_init_db(args.config)
    if args.command == "cycle":
        return command_cycle(args.config)
    if args.command == "daemon":
        return command_daemon(args.config)
    if args.command == "jobs":
        return command_jobs(args.config, args.limit)
    if args.command == "schedule-followups":
        return command_followups(args.config, args.limit)
    if args.command == "promote-memory":
        return command_promote_memory(args.config)
    if args.command == "backfill-archive":
        return command_backfill_archive(args.config, args.db_path, dry_run=args.dry_run)
    if args.command == "backfill-mind-graph":
        return command_backfill_mind_graph(args.config, dry_run=args.dry_run)
    if args.command == "dream-cycle":
        return command_dream_cycle(args.config, args.sample_size, seed=args.seed, dry_run=args.dry_run)
    if args.command == "think-cycle":
        return command_think_cycle(args.config, args.sample_size, seed=args.seed, dry_run=args.dry_run)
    if args.command == "reflect-cycle":
        return command_reflect_cycle(args.config, args.window_hours, dry_run=args.dry_run)
    if args.command == "initiative-cycle":
        return command_initiative_cycle(args.config, dry_run=args.dry_run)
    if args.command == "show-callbacks":
        return command_show_callbacks(args.config, args.limit)
    if args.command == "show-thoughts":
        return command_show_thoughts(args.config, args.limit)
    if args.command == "show-initiatives":
        return command_show_initiatives(args.config, args.limit)
    if args.command == "show-brain-status":
        return command_show_brain_status(args.config)
    if args.command == "show-self-model":
        return command_show_self_model(args.config)
    if args.command == "show-autobiographical-state":
        return command_show_autobiographical_state(args.config)
    if args.command == "show-goal-state":
        return command_show_goal_state(args.config)
    if args.command == "show-engineering-state":
        return command_show_engineering_state(args.config)
    if args.command == "show-action-calibration":
        return command_show_action_calibration(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            action_type=args.action_type,
            scenario_bucket=args.scenario_bucket,
            limit=args.limit,
        )
    if args.command == "show-policy-candidates":
        return command_show_policy_candidates(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-promoted-policies":
        return command_show_promoted_policies(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "rollback-policy":
        return command_rollback_policy(args.config, policy_id=args.id, reason=args.reason)
    if args.command == "trace-policy-influence":
        return command_trace_policy_influence(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
            limit=args.limit,
        )
    if args.command == "show-online-canary":
        return command_show_online_canary(args.config, limit=args.limit)
    if args.command == "show-blackbox-metrics":
        return command_show_blackbox_metrics(
            args.config,
            window_hours=args.window_hours,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-blackbox-scorecard":
        return command_show_blackbox_scorecard(
            args.config,
            since_hours=args.since_hours,
            limit=args.limit,
        )
    if args.command == "trace-canary-decision":
        return command_trace_canary_decision(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
        )
    if args.command == "set-canary-rollback":
        enabled = str(args.enabled).strip().lower() in {"1", "true", "yes"}
        return command_set_canary_rollback(args.config, enabled=enabled, reason=args.reason)
    if args.command == "replay-live-artifacts":
        return command_replay_live_artifacts(
            args.config,
            since_hours=args.since_hours,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "export-blind-packets":
        return command_export_blind_packets(
            args.config,
            since_hours=args.since_hours,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "run-blackbox-soak":
        persist = str(args.persist).strip().lower() in {"1", "true", "yes"}
        return command_run_blackbox_soak(
            args.config,
            since_hours=args.since_hours,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
            persist=persist,
        )
    if args.command == "trace-outcome-history":
        return command_trace_outcome_history(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            action_type=args.action_type,
            limit=args.limit,
        )
    if args.command == "trace-action-prediction-error":
        return command_trace_action_prediction_error(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            action_type=args.action_type,
            limit=args.limit,
        )
    if args.command == "trace-self-model":
        return command_trace_self_model(args.config)
    if args.command == "trace-self-continuity":
        return command_trace_self_continuity(args.config)
    if args.command == "trace-goal-arbitration":
        return command_trace_goal_arbitration(args.config)
    if args.command == "show-processor-routing":
        return command_show_processor_routing(args.config)
    if args.command == "show-provider-status":
        return command_show_provider_status(args.config)
    if args.command == "show-provider-substrate-status":
        return command_show_provider_substrate_status(args.config)
    if args.command == "show-provider-contracts":
        return command_show_provider_contracts(args.config)
    if args.command == "show-mcp-upstream-status":
        return command_show_mcp_upstream_status(args.config)
    if args.command == "list-mcp-upstream-tools":
        return command_list_mcp_upstream_tools(args.config)
    if args.command == "call-mcp-tool":
        return command_call_mcp_tool(args.config, tool=args.tool, arguments_json=args.arguments_json)
    if args.command == "read-mcp-resource":
        return command_read_mcp_resource(args.config, server=args.server, uri=args.uri)
    if args.command == "render-consciousness-map":
        return command_render_consciousness_map(args.config, suite=args.suite, output=args.output)
    if args.command == "show-visual-provider-readiness":
        return command_show_visual_provider_readiness(args.config)
    if args.command == "show-debt-registry":
        return command_show_debt_registry(args.config)
    if args.command == "show-internal-runtime-readiness":
        return command_show_internal_runtime_readiness(args.config)
    if args.command == "show-usage-ledger":
        return command_show_usage_ledger(
            args.config,
            limit=args.limit,
            task_type=args.task_type,
            lane=args.lane,
            provider=args.provider,
        )
    if args.command == "agent-run":
        return command_agent_run(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name or args.thread_key,
            channel=args.channel,
            offline=args.offline,
            record=not bool(args.no_record),
            image_paths=args.image_path,
        )
    if args.command == "agent-trace":
        return command_agent_trace(args.config, trace_id=args.trace_id)
    if args.command == "show-bionic-metrics":
        return command_show_bionic_metrics(args.config, limit=args.limit)
    if args.command == "show-bionic-turing-scorecard":
        return command_show_bionic_turing_scorecard(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "brain-run":
        return command_brain_run(
            args.config,
            goal=args.goal,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            offline=args.offline,
            max_steps=args.max_steps,
        )
    if args.command == "brain-trace":
        return command_brain_trace(args.config, trace_id=args.trace_id)
    if args.command == "show-context-bundle":
        return command_show_context_bundle(args.config, bundle_id=args.bundle_id)
    if args.command == "show-brain-metrics":
        return command_show_brain_metrics(args.config, limit=args.limit)
    if args.command == "run-agent-eval":
        return command_run_agent_eval(args.config, suite=args.suite)
    if args.command == "run-bionic-user-sim":
        return command_run_bionic_user_sim(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            scenario=args.scenario,
            turn_limit=args.turns,
            offline=args.offline,
        )
    if args.command == "show-bionic-user-sim-scorecard":
        return command_show_bionic_user_sim_scorecard(args.config, suite=args.suite)
    if args.command == "run-bionic-boundary-stress":
        return command_run_bionic_boundary_stress(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            turn_limit=args.turns,
            offline=args.offline,
        )
    if args.command == "show-bionic-boundary-stress-scorecard":
        return command_show_bionic_boundary_stress_scorecard(args.config, suite=args.suite)
    if args.command == "engineering-run":
        return command_engineering_run(
            args.config,
            goal=args.goal,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            offline=args.offline,
            max_steps=args.max_steps,
            allow_repo_write=args.allow_repo_write,
        )
    if args.command == "engineering-trace":
        return command_engineering_trace(args.config, trace_id=args.trace_id)
    if args.command == "show-engineering-agent-metrics":
        return command_show_engineering_agent_metrics(args.config, limit=args.limit)
    if args.command == "trace-subject-loop":
        return command_trace_subject_loop(args.config, trace_id=args.trace_id)
    if args.command == "show-subject-loop-metrics":
        return command_show_subject_loop_metrics(args.config, limit=args.limit)
    if args.command == "export-bionic-trace":
        return command_export_bionic_trace(args.config, trace_id=args.trace_id, output=args.output)
    if args.command == "show-affect-state":
        return command_show_affect_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-intent-state":
        return command_show_intent_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
        )
    if args.command == "show-action-market":
        return command_show_action_market(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
            limit=args.limit,
        )
    if args.command == "show-fast-path-metrics":
        return command_show_fast_path_metrics(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-predictive-continuity":
        return command_show_predictive_continuity(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-scene-state":
        return command_show_scene_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "trace-predicted-branches":
        return command_trace_predicted_branches(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "trace-scene-compression":
        return command_trace_scene_compression(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-situational-field":
        return command_show_situational_field(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "trace-visual-field":
        return command_trace_visual_field(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "trace-inquiry-shaping":
        return command_trace_inquiry_shaping(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-task-world":
        return command_show_task_world(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
            include_inactive=args.include_inactive,
        )
    if args.command == "trace-world-object":
        return command_trace_world_object(
            args.config,
            object_id=args.object_id,
        )
    if args.command == "trace-thread-object-links":
        return command_trace_thread_object_links(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-continuity-budget":
        return command_show_continuity_budget(
            args.config,
            channel=args.channel,
        )
    if args.command == "show-dense-working-set":
        return command_show_dense_working_set(
            args.config,
            channel=args.channel,
        )
    if args.command == "trace-thread-pulse":
        return command_trace_thread_pulse(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-attention-frontier":
        return command_show_attention_frontier(
            args.config,
            channel=args.channel,
            limit=args.limit,
            include_stale=args.include_stale,
        )
    if args.command == "trace-wake-reasons":
        return command_trace_wake_reasons(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-thread-warmth":
        return command_show_thread_warmth(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-open-loops":
        return command_show_open_loops(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            include_inactive=args.include_inactive,
        )
    if args.command == "show-commitments":
        return command_show_commitments(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            include_inactive=args.include_inactive,
        )
    if args.command == "trace-resume-candidate":
        return command_trace_resume_candidate(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            include_inactive=args.include_inactive,
        )
    if args.command == "show-world-state":
        return command_show_world_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "show-world-coupling":
        return command_show_world_coupling(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
            include_inactive=args.include_inactive,
        )
    if args.command == "trace-drive-state":
        return command_trace_drive_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "set-brain-mode":
        return command_set_brain_mode(args.config, mode=args.mode, note=args.note)
    if args.command == "run-self-revision":
        return command_run_self_revision(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            corrections=args.corrections,
            apply_patch=not args.no_apply,
        )
    if args.command == "initiative-probe":
        return command_initiative_probe(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
        )
    if args.command == "operator-probe":
        return command_operator_probe(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "run-operator-cycle":
        return command_run_operator_cycle(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            reason=args.reason,
        )
    if args.command == "show-initiative-status":
        return command_show_initiative_status(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-initiative-market":
        return command_show_initiative_market(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "trace-resistance":
        return command_trace_resistance(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
        )
    if args.command == "trace-action-selection":
        return command_trace_action_selection(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
            limit=args.limit,
        )
    if args.command == "trace-reflex-routing":
        return command_trace_reflex_routing(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
        )
    if args.command == "trace-counterfactual":
        return command_trace_counterfactual(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            query=args.query,
            limit=args.limit,
        )
    if args.command == "trace-world-calibration":
        return command_trace_world_calibration(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "dispatch-initiatives":
        return command_dispatch_initiatives(
            args.config,
            process_jobs=not args.no_process_jobs,
            limit=args.limit,
        )
    if args.command == "inspect-mind":
        return command_inspect_mind(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
        )
    if args.command == "inspect-graph":
        return command_inspect_graph(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "trace-recall":
        return command_trace_recall(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "trace-hybrid-recall":
        return command_trace_hybrid_recall(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "trace-visual-recall":
        return command_trace_visual_recall(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "show-activation-state":
        return command_show_activation_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "backfill-vector-memory":
        return command_backfill_vector_memory(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "vector-health":
        return command_vector_health(args.config)
    if args.command == "reply-probe":
        return command_reply_probe(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            mode=args.mode,
        )
    if args.command == "experiment-memory":
        return command_experiment_memory(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
        )
    if args.command == "snapshot-memory":
        return command_snapshot_memory(args.config, args.path, args.label, args.query)
    if args.command == "restore-memory":
        return command_restore_memory(
            args.config,
            args.path,
            mode=args.mode,
            dry_run=args.dry_run,
            restore_persona_files=args.restore_persona_files,
        )
    if args.command == "revive-packet":
        return command_revive_packet(args.config, args.path, args.query, args.json)
    if args.command == "ingest-artifact":
        return command_ingest_artifact(
            args.config,
            args.path,
            note=args.note,
            tags=args.tags,
            source=args.source,
            dry_run=args.dry_run,
            channel=args.channel,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            world_cue_type=args.world_cue_type,
            due_at=args.due_at,
        )
    if args.command == "ingest-image":
        return command_ingest_image(
            args.config,
            path=args.path,
            note=args.note,
            tags=args.tags,
            source=args.source,
            channel=args.channel,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            sync=args.sync,
        )
    if args.command == "refresh-wechat-history":
        return command_refresh_wechat_history(
            args.config,
            chat_name=args.chat_name,
            thread_key=args.thread_key,
            query=args.query,
            force=args.force,
            limit=args.limit,
            page_turns=args.page_turns,
            include_visible=not args.no_visible,
            include_captures=args.with_captures,
        )
    if args.command == "show-stream-status":
        return command_show_stream_status(args.config)
    if args.command == "stream-tick":
        return command_stream_tick(args.config, stream_name=args.stream_name, dry_run=args.dry_run)
    if args.command == "sync-private-memory":
        return command_sync_private_memory(args.config, label=args.label)
    if args.command == "benchmark-memory-fabric":
        return command_benchmark_memory_fabric(
            args.config,
            query=args.query,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
            probe=args.probe,
        )
    if args.command == "accept-memory-fabric-stage1":
        return command_accept_memory_fabric_stage1(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
            tick_streams=not args.no_stream_ticks,
            require_private_sync=args.require_private_sync,
            private_label=args.private_label,
        )
    if args.command == "accept-stage2":
        return command_accept_stage2(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage3":
        return command_accept_stage3(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage4":
        return command_accept_stage4(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage5":
        return command_accept_stage5(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "trace-deliberation-ledger":
        return command_trace_deliberation_ledger(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
        )
    if args.command == "accept-stage6":
        return command_accept_stage6(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage7":
        return command_accept_stage7(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage8":
        return command_accept_stage8(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage9":
        return command_accept_stage9(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage10":
        return command_accept_stage10(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage12":
        return command_accept_stage12(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "accept-stage13":
        return command_accept_stage13(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            iterations=args.iterations,
            warmup=args.warmup,
        )
    if args.command == "replay-calibration-fixture":
        return command_replay_calibration_fixture(
            args.config,
            source_type=args.source_type,
            fixture_path=args.fixture_path,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "replay-policy-regret":
        return command_replay_policy_regret(
            args.config,
            source_type=args.source_type,
            fixture_path=args.fixture_path,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage14":
        return command_accept_stage14(
            args.config,
            source_type=args.source_type,
            fixture_path=args.fixture_path,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage16":
        return command_accept_stage16(
            args.config,
            run_pytest=not args.skip_pytest,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage17":
        return command_accept_stage17(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage18":
        return command_accept_stage18(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage19":
        return command_accept_stage19(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage20":
        return command_accept_stage20(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage21":
        return command_accept_stage21(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage22":
        return command_accept_stage22(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage23":
        return command_accept_stage23(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage24":
        return command_accept_stage24(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage25":
        return command_accept_stage25(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage26":
        return command_accept_stage26(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage27":
        return command_accept_stage27(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage28":
        return command_accept_stage28(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            sender=args.sender,
            artifact_dir=args.artifact_dir,
        )
    if args.command == "accept-stage29":
        return command_accept_stage29(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage30":
        return command_accept_stage30(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage31":
        return command_accept_stage31(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage32":
        return command_accept_stage32(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage36":
        return command_accept_stage36(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage37":
        return command_accept_stage37(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage38":
        return command_accept_stage38(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage39":
        return command_accept_stage39(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage40":
        return command_accept_stage40(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage41":
        return command_accept_stage41(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage42":
        return command_accept_stage42(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage43":
        return command_accept_stage43(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
        )
    if args.command == "accept-stage33":
        return command_accept_stage33(args.config)
    if args.command == "accept-stage34":
        return command_accept_stage34(args.config)
    if args.command == "accept-stage35":
        return command_accept_stage35(args.config)
    if args.command == "show-processor-mesh":
        return command_show_processor_mesh(args.config)
    if args.command == "accept-processor-fabric":
        return command_accept_processor_fabric(args.config)
    if args.command == "processor-task":
        return command_run_processor_task(
            args.config,
            task_type=args.task_type,
            prompt=args.prompt,
            session_id=args.session_id,
            lane=args.lane,
            provider_hint=args.provider_hint,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            budget_tag=args.budget_tag,
            max_output_tokens=args.max_output_tokens,
            json_output=args.json,
        )
    if args.command == "serve-api":
        return command_serve_api(args.config, args.host, args.port)
    parser.print_help()
    return 1
