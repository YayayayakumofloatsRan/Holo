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


def command_show_processor_mesh(config_path: str | None) -> int:
    daemon = build_daemon(config_path)
    print(json.dumps({"tasks": daemon.runner.supported_tasks()}, ensure_ascii=False, indent=2))
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
    json_output: bool,
) -> int:
    daemon = build_daemon(config_path)
    result = daemon.runner.run_task(
        ProcessorTaskRequest(
            task_type=task_type,
            prompt=prompt,
            session_id=str(session_id or ""),
            model_override=str(model or ""),
            reasoning_effort_override=str(reasoning_effort or ""),
            output_schema="json" if json_output else "plain_text",
        )
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
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
    initiative_status_parser = subparsers.add_parser("show-initiative-status", help="Inspect proactive initiative gate, queue, and recent candidates")
    initiative_status_parser.add_argument("--thread-key", default=None)
    initiative_status_parser.add_argument("--chat-name", default=None)
    initiative_status_parser.add_argument("--channel", default="wechat")
    initiative_status_parser.add_argument("--limit", type=int, default=5)
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
    subparsers.add_parser("show-processor-mesh", help="Show supported processor task types and permissions")
    processor_task_parser = subparsers.add_parser("processor-task", help="Run one explicit processor-mesh task through Codex")
    processor_task_parser.add_argument("--task-type", required=True)
    processor_task_parser.add_argument("--prompt", required=True)
    processor_task_parser.add_argument("--session-id", default=None)
    processor_task_parser.add_argument("--model", default=None)
    processor_task_parser.add_argument("--reasoning-effort", default=None)
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
    if args.command == "show-initiative-status":
        return command_show_initiative_status(
            args.config,
            thread_key=args.thread_key,
            chat_name=args.chat_name,
            channel=args.channel,
            limit=args.limit,
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
    if args.command == "show-processor-mesh":
        return command_show_processor_mesh(args.config)
    if args.command == "processor-task":
        return command_run_processor_task(
            args.config,
            task_type=args.task_type,
            prompt=args.prompt,
            session_id=args.session_id,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            json_output=args.json,
        )
    if args.command == "serve-api":
        return command_serve_api(args.config, args.host, args.port)
    parser.print_help()
    return 1
