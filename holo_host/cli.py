from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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
            "reply_once",
            "reply_multi",
            "push_back",
            "counter_offer",
            "continuity_defense",
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
    world_state_parser = subparsers.add_parser("show-world-state", help="Inspect the current social world-state for one thread")
    world_state_parser.add_argument("--thread-key", default=None)
    world_state_parser.add_argument("--chat-name", default=None)
    world_state_parser.add_argument("--channel", default="wechat")
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
    usage_ledger_parser = subparsers.add_parser("show-usage-ledger", help="Inspect processor token and timing usage records")
    usage_ledger_parser.add_argument("--limit", type=int, default=50)
    usage_ledger_parser.add_argument("--task-type", default=None)
    usage_ledger_parser.add_argument("--lane", default=None)
    usage_ledger_parser.add_argument("--provider", default=None)
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
    if args.command == "show-usage-ledger":
        return command_show_usage_ledger(
            args.config,
            limit=args.limit,
            task_type=args.task_type,
            lane=args.lane,
            provider=args.provider,
        )
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
    if args.command == "show-world-state":
        return command_show_world_state(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
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
