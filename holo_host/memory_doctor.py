from __future__ import annotations

import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MEMORY_DIR = Path("holo_memory_library") / "memories"
RUNTIME_DIR = Path(".holo_runtime")
DEFAULT_JSONL_STORES = (
    "memory_store.jsonl",
    "working_store.jsonl",
    "candidate_store.jsonl",
    "conversation_archive.jsonl",
    "emotion_trace.jsonl",
    "callback_candidates.jsonl",
    "thought_stream.jsonl",
    "initiative_candidates.jsonl",
)
TEXTLIKE_KEYS = {
    "text",
    "content",
    "message",
    "prompt",
    "reply",
    "response",
    "input",
    "output",
    "bubbles",
    "reply_bubbles",
    "raw",
    "raw_text",
}
ROUTE_LOG_RE = re.compile(r"reply\s+route=(?P<route>\S+)\s+processor=(?P<processor>\S+)\s+total_ms=(?P<total_ms>\d+)")


def _top(counter: Counter[str], limit: int = 8) -> list[dict[str, Any]]:
    return [{"key": key, "count": count} for key, count in counter.most_common(limit)]


def _safe_json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, sort_keys=True))
    except (TypeError, ValueError):
        return 0


def _parse_timestamp(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _timestamp_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat().replace("+00:00", "Z")


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil((percentile / 100.0) * len(ordered)) - 1))
    return int(ordered[index])


def _stats(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "min_ms": 0, "max_ms": 0, "p50_ms": 0, "p95_ms": 0, "avg_ms": 0}
    return {
        "count": len(values),
        "min_ms": int(min(values)),
        "max_ms": int(max(values)),
        "p50_ms": int(_percentile(values, 50)),
        "p95_ms": int(_percentile(values, 95)),
        "avg_ms": int(round(sum(values) / len(values))),
    }


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any] | None, str | None]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                yield line_number, None, None
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                yield line_number, None, str(exc)
                continue
            if not isinstance(payload, dict):
                yield line_number, None, "row is not a JSON object"
                continue
            yield line_number, payload, None


def _record_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "updated_at", "timestamp", "ts"):
        parsed = _parse_timestamp(record.get(key))
        if parsed is not None:
            return parsed
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in ("created_at", "updated_at", "timestamp", "ts"):
            parsed = _parse_timestamp(metadata.get(key))
            if parsed is not None:
                return parsed
    return None


def audit_jsonl_store(path: Path | str) -> dict[str, Any]:
    store_path = Path(path)
    valid_rows = 0
    blank_rows = 0
    invalid_rows = 0
    invalid_examples: list[dict[str, Any]] = []
    exact_hashes: Counter[str] = Counter()
    ids: Counter[str] = Counter()
    channels: Counter[str] = Counter()
    thread_keys: Counter[str] = Counter()
    row_kinds: Counter[str] = Counter()
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    max_metadata_bytes = 0
    metadata_rows = 0

    if not store_path.exists():
        return {
            "exists": False,
            "path": str(store_path),
            "bytes": 0,
            "valid_rows": 0,
            "blank_rows": 0,
            "invalid_rows": 0,
            "invalid_examples": [],
            "exact_duplicate_rows": 0,
            "duplicate_ids": {},
            "top_channels": [],
            "top_thread_keys": [],
            "top_kinds": [],
            "first_timestamp": "",
            "last_timestamp": "",
            "metadata_rows": 0,
            "max_metadata_bytes": 0,
        }

    with store_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                blank_rows += 1
                continue
            exact_hashes[text] += 1
            try:
                record = json.loads(text)
            except json.JSONDecodeError as exc:
                invalid_rows += 1
                if len(invalid_examples) < 5:
                    invalid_examples.append({"line": line_number, "error": exc.msg})
                continue
            if not isinstance(record, dict):
                invalid_rows += 1
                if len(invalid_examples) < 5:
                    invalid_examples.append({"line": line_number, "error": "row is not a JSON object"})
                continue
            valid_rows += 1
            record_id = str(record.get("id", "") or record.get("memory_id", "") or "").strip()
            if record_id:
                ids[record_id] += 1
            channel = str(record.get("channel", "") or "").strip()
            if channel:
                channels[channel] += 1
            thread_key = str(record.get("thread_key", "") or "").strip()
            if thread_key:
                thread_keys[thread_key] += 1
            kind = str(record.get("kind", "") or record.get("type", "") or record.get("source", "") or "").strip()
            if kind:
                row_kinds[kind] += 1
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                metadata_rows += 1
                max_metadata_bytes = max(max_metadata_bytes, _safe_json_size(_redact_metadata_values(metadata)))
            timestamp = _record_timestamp(record)
            if timestamp is not None:
                first_seen = timestamp if first_seen is None else min(first_seen, timestamp)
                last_seen = timestamp if last_seen is None else max(last_seen, timestamp)

    duplicate_ids = {key: count for key, count in sorted(ids.items()) if count > 1}
    duplicate_rows = sum(count - 1 for count in exact_hashes.values() if count > 1)
    return {
        "exists": True,
        "path": str(store_path),
        "bytes": store_path.stat().st_size,
        "valid_rows": valid_rows,
        "blank_rows": blank_rows,
        "invalid_rows": invalid_rows,
        "invalid_examples": invalid_examples,
        "exact_duplicate_rows": duplicate_rows,
        "duplicate_ids": duplicate_ids,
        "top_channels": _top(channels),
        "top_thread_keys": _top(thread_keys),
        "top_kinds": _top(row_kinds),
        "first_timestamp": _timestamp_text(first_seen),
        "last_timestamp": _timestamp_text(last_seen),
        "metadata_rows": metadata_rows,
        "max_metadata_bytes": max_metadata_bytes,
    }


def _redact_metadata_values(metadata: dict[str, Any]) -> dict[str, Any]:
    redacted: dict[str, Any] = {}
    for key, value in metadata.items():
        if key in TEXTLIKE_KEYS:
            redacted[key] = {"redacted": True, "type": type(value).__name__}
        elif isinstance(value, dict):
            redacted[key] = _redact_metadata_values(value)
        elif isinstance(value, list):
            redacted[key] = {"type": "list", "count": len(value)}
        else:
            redacted[key] = value
    return redacted


def _canonical_thread_key(channel: str, thread_key: str, chat_name: str) -> str:
    current_channel = str(channel or "").strip()
    current_thread_key = str(thread_key or chat_name or "").strip()
    current_chat_name = str(chat_name or thread_key or "").strip()
    if current_channel == "wechat":
        candidate = current_thread_key or current_chat_name
        if candidate and not candidate.startswith("wechat:") and not candidate.endswith("@chatroom") and not candidate.startswith("wxid_"):
            return f"wechat:{candidate}"
    return current_thread_key or current_chat_name


def _collect_thread_records(memory_dir: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for store_path in sorted(memory_dir.glob("*.jsonl")):
        for _line, record, error in _iter_jsonl(store_path):
            if error or record is None:
                continue
            channel = str(record.get("channel", "") or "").strip()
            thread_key = str(record.get("thread_key", "") or "").strip()
            chat_name = str(record.get("chat_name", "") or "").strip()
            metadata = record.get("metadata")
            if isinstance(metadata, dict):
                channel = channel or str(metadata.get("channel", "") or "").strip()
                thread_key = thread_key or str(metadata.get("thread_key", "") or "").strip()
                chat_name = chat_name or str(metadata.get("chat_name", "") or "").strip()
            if not channel and not thread_key and not chat_name:
                continue
            records.append(
                {
                    "store": store_path.name,
                    "channel": channel,
                    "thread_key": thread_key,
                    "chat_name": chat_name,
                    "canonical_key": _canonical_thread_key(channel, thread_key, chat_name),
                }
            )
    return records


def thread_fragmentation_report(memory_dir: Path | str) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for record in _collect_thread_records(Path(memory_dir)):
        canonical_key = str(record["canonical_key"])
        if not canonical_key:
            continue
        group = groups.setdefault(
            canonical_key,
            {"canonical_key": canonical_key, "count": 0, "raw_thread_keys": Counter(), "channels": Counter(), "stores": Counter()},
        )
        group["count"] += 1
        raw_key = str(record.get("thread_key") or record.get("chat_name") or "")
        if raw_key:
            group["raw_thread_keys"][raw_key] += 1
        channel = str(record.get("channel") or "")
        if channel:
            group["channels"][channel] += 1
        group["stores"][str(record.get("store") or "")] += 1

    candidates = []
    for group in groups.values():
        if len(group["raw_thread_keys"]) <= 1:
            continue
        candidates.append(
            {
                "canonical_key": group["canonical_key"],
                "count": group["count"],
                "raw_thread_keys": _top(group["raw_thread_keys"]),
                "channels": _top(group["channels"]),
                "stores": _top(group["stores"]),
            }
        )
    candidates.sort(key=lambda item: item["count"], reverse=True)
    return {
        "thread_groups": len(groups),
        "fragmentation_candidates": candidates[:12],
        "fragmentation_candidate_count": len(candidates),
    }


def route_latency_summary(log_path: Path | str) -> dict[str, Any]:
    path = Path(log_path)
    by_route: dict[str, list[int]] = defaultdict(list)
    by_processor: dict[str, list[int]] = defaultdict(list)
    total_records = 0
    scanned_lines = 0
    deduped = 0
    previous_line = ""
    if not path.exists():
        return {
            "exists": False,
            "path": str(path),
            "scanned_lines": 0,
            "total_records": 0,
            "deduped_adjacent_records": 0,
            "by_route": {},
            "by_processor": {},
        }

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            scanned_lines += 1
            line = raw.strip()
            if not line:
                continue
            if line == previous_line:
                deduped += 1
                continue
            previous_line = line
            match = ROUTE_LOG_RE.search(line)
            if not match:
                continue
            total_ms = int(match.group("total_ms"))
            route = match.group("route")
            processor = match.group("processor")
            by_route[route].append(total_ms)
            by_processor[processor].append(total_ms)
            total_records += 1

    return {
        "exists": True,
        "path": str(path),
        "scanned_lines": scanned_lines,
        "total_records": total_records,
        "deduped_adjacent_records": deduped,
        "by_route": {key: _stats(values) for key, values in sorted(by_route.items())},
        "by_processor": {key: _stats(values) for key, values in sorted(by_processor.items())},
    }


def sqlite_health(path: Path | str) -> dict[str, Any]:
    db_path = Path(path)
    if not db_path.exists():
        return {"exists": False, "path": str(db_path), "bytes": 0, "integrity": "missing", "table_counts": {}}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2.0) as connection:
            connection.row_factory = sqlite3.Row
            integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
            integrity = str(integrity_row[0]) if integrity_row else "unknown"
            table_rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
            table_counts: dict[str, int] = {}
            for row in table_rows:
                table = str(row["name"])
                try:
                    table_counts[table] = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
                except sqlite3.Error:
                    table_counts[table] = -1
    except sqlite3.Error as exc:
        return {
            "exists": True,
            "path": str(db_path),
            "bytes": db_path.stat().st_size,
            "integrity": "error",
            "error": str(exc),
            "table_counts": {},
        }
    return {
        "exists": True,
        "path": str(db_path),
        "bytes": db_path.stat().st_size,
        "integrity": integrity,
        "table_counts": table_counts,
    }


def archive_metadata_summary(path: Path | str) -> dict[str, Any]:
    archive_path = Path(path)
    metadata_keys: Counter[str] = Counter()
    route_counts: Counter[str] = Counter()
    timing_totals: list[int] = []
    oversized_metadata_rows = 0
    largest_timing_rows: list[dict[str, Any]] = []
    metadata_rows = 0
    if not archive_path.exists():
        return {
            "exists": False,
            "metadata_rows": 0,
            "top_metadata_keys": [],
            "route_counts": {},
            "timing": _stats([]),
            "oversized_metadata_rows": 0,
            "largest_timing_rows": [],
        }

    for line_number, record, error in _iter_jsonl(archive_path):
        if error or record is None:
            continue
        metadata = record.get("metadata")
        if not isinstance(metadata, dict):
            continue
        metadata_rows += 1
        for key in metadata:
            metadata_keys[key] += 1
        redacted_size = _safe_json_size(_redact_metadata_values(metadata))
        if redacted_size > 8192:
            oversized_metadata_rows += 1
        route = str(metadata.get("route", "") or record.get("route", "") or "").strip()
        if route:
            route_counts[route] += 1
        timing = metadata.get("timing_ms")
        total_ms = 0
        if isinstance(timing, dict):
            try:
                total_ms = int(timing.get("total_ms", 0) or 0)
            except (TypeError, ValueError):
                total_ms = 0
        if total_ms > 0:
            timing_totals.append(total_ms)
            largest_timing_rows.append(
                {
                    "line": line_number,
                    "id": str(record.get("id", "") or ""),
                    "route": route,
                    "total_ms": total_ms,
                    "metadata_bytes_redacted": redacted_size,
                }
            )
    largest_timing_rows.sort(key=lambda row: row["total_ms"], reverse=True)
    return {
        "exists": True,
        "metadata_rows": metadata_rows,
        "top_metadata_keys": _top(metadata_keys, limit=16),
        "route_counts": dict(sorted(route_counts.items())),
        "timing": _stats(timing_totals),
        "oversized_metadata_rows": oversized_metadata_rows,
        "largest_timing_rows": largest_timing_rows[:8],
    }


def _vector_static_health(repo_root: Path, vector_health: dict[str, Any] | None) -> dict[str, Any]:
    db_path = repo_root / RUNTIME_DIR / "milvus" / "memory_fabric.db"
    payload = {
        "static_probe": {
            "path": str(db_path),
            "exists": db_path.exists(),
            "bytes": db_path.stat().st_size if db_path.exists() else 0,
        },
        "open_probe": vector_health if vector_health is not None else {"status": "not_requested"},
    }
    return payload


def _status(status: str, reason: str, **extra: Any) -> dict[str, Any]:
    payload = {"status": status, "reason": reason}
    payload.update(extra)
    return payload


def _jsonl_total_invalid(jsonl_reports: dict[str, dict[str, Any]]) -> int:
    return sum(int(report.get("invalid_rows", 0) or 0) for report in jsonl_reports.values())


def biomimetic_health(
    *,
    jsonl_reports: dict[str, dict[str, Any]],
    route_summary: dict[str, Any],
    thread_report: dict[str, Any],
    metadata_report: dict[str, Any],
    vector_report: dict[str, Any],
    sqlite_reports: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    archive = jsonl_reports.get("conversation_archive.jsonl", {})
    durable = jsonl_reports.get("memory_store.jsonl", {})
    archive_rows = int(archive.get("valid_rows", 0) or 0)
    durable_rows = int(durable.get("valid_rows", 0) or 0)
    archive_latest = _parse_timestamp(archive.get("last_timestamp"))
    durable_latest = _parse_timestamp(durable.get("last_timestamp"))

    if archive_rows and durable_rows == 0:
        semantic = _status("critical", "episodic archive has no durable semantic consolidation", archive_rows=archive_rows, durable_rows=durable_rows)
    elif archive_latest and durable_latest:
        staleness_days = max(0, (archive_latest - durable_latest).days)
        if staleness_days > 30:
            semantic = _status("critical", "durable semantic memory is more than 30 days behind archive", staleness_days=staleness_days)
        elif staleness_days > 7:
            semantic = _status("warn", "durable semantic memory is more than 7 days behind archive", staleness_days=staleness_days)
        else:
            semantic = _status("ok", "semantic consolidation is recent enough", staleness_days=staleness_days)
    elif archive_rows and durable_rows:
        semantic = _status("warn", "timestamps are incomplete; consolidation freshness cannot be trusted")
    else:
        semantic = _status("ok", "no archive pressure detected")

    ratio = float(archive_rows) / max(1, durable_rows)
    if ratio > 100:
        balance = _status("critical", "episodic archive overwhelms durable semantic memory", archive_to_durable_ratio=round(ratio, 2))
    elif ratio > 25:
        balance = _status("warn", "episodic archive is much larger than durable semantic memory", archive_to_durable_ratio=round(ratio, 2))
    else:
        balance = _status("ok", "episodic and semantic stores are within a manageable ratio", archive_to_durable_ratio=round(ratio, 2))

    deep = dict(route_summary.get("by_route", {}).get("deep_recall", {}))
    deep_p50 = int(deep.get("p50_ms", 0) or 0)
    if deep_p50 > 300_000:
        deep_status = _status("critical", "deep recall median latency is too high for embodied conversation", p50_ms=deep_p50)
    elif deep_p50 > 60_000:
        deep_status = _status("warn", "deep recall median latency is above conversational tolerance", p50_ms=deep_p50)
    elif deep.get("count", 0):
        deep_status = _status("ok", "deep recall pressure is visible but bounded", p50_ms=deep_p50)
    else:
        deep_status = _status("unknown", "no deep recall route samples found")

    fast = dict(route_summary.get("by_route", {}).get("fast", {}))
    if fast.get("count", 0):
        fast_lane = _status("ok", "fast lane has route evidence", count=int(fast.get("count", 0) or 0), p50_ms=int(fast.get("p50_ms", 0) or 0))
    else:
        fast_lane = _status("warn", "no fast-lane route evidence found in reply log")

    fragment_count = int(thread_report.get("fragmentation_candidate_count", 0) or 0)
    thread_continuity = (
        _status("warn", "thread identity split can fracture autobiographical continuity", fragmentation_candidates=fragment_count)
        if fragment_count
        else _status("ok", "no obvious thread identity split detected", fragmentation_candidates=0)
    )

    invalid_rows = _jsonl_total_invalid(jsonl_reports)
    sqlite_bad = [name for name, report in sqlite_reports.items() if report.get("exists") and report.get("integrity") != "ok"]
    if invalid_rows or sqlite_bad:
        substrate = _status("critical", "memory substrate has parse or SQLite integrity failures", invalid_rows=invalid_rows, sqlite_bad=sqlite_bad)
    else:
        substrate = _status("ok", "memory substrate parses cleanly", invalid_rows=0)

    oversized = int(metadata_report.get("oversized_metadata_rows", 0) or 0)
    if oversized > 0:
        metadata_pressure = _status("warn", "archive carries oversized operational metadata", oversized_metadata_rows=oversized)
    else:
        metadata_pressure = _status("ok", "archive metadata size is bounded", oversized_metadata_rows=0)

    vector_static = dict(vector_report.get("static_probe", {}))
    if vector_static.get("exists"):
        vector_status = _status("ok", "vector substrate file exists", bytes=int(vector_static.get("bytes", 0) or 0))
    else:
        vector_status = _status("warn", "vector substrate file is missing or not initialized")

    return {
        "substrate_integrity": substrate,
        "semantic_consolidation": semantic,
        "episodic_semantic_balance": balance,
        "deep_recall_pressure": deep_status,
        "active_thread_fast_lane": fast_lane,
        "thread_continuity": thread_continuity,
        "archive_metadata_pressure": metadata_pressure,
        "vector_index": vector_status,
    }


def _recommendations(health: dict[str, Any]) -> list[str]:
    recommendations: list[str] = []
    if health["semantic_consolidation"]["status"] in {"warn", "critical"}:
        recommendations.append("Run a bounded consolidation pass from episodic archive into durable semantic memory before widening recall.")
    if health["episodic_semantic_balance"]["status"] in {"warn", "critical"}:
        recommendations.append("Introduce a promotion budget that keeps durable semantic memory aligned with the fast-growing conversation archive.")
    if health["deep_recall_pressure"]["status"] in {"warn", "critical"}:
        recommendations.append("Put recall reconstruction behind a stricter budget and prefer active-thread summaries for ordinary continuity turns.")
    if health["thread_continuity"]["status"] in {"warn", "critical"}:
        recommendations.append("Backfill canonical thread keys so autobiographical continuity does not split across aliases.")
    if health["archive_metadata_pressure"]["status"] in {"warn", "critical"}:
        recommendations.append("Move heavy timing/debug payloads into an operational ledger and keep archive rows as distilled episodic records.")
    if health["vector_index"]["status"] in {"warn", "critical"}:
        recommendations.append("Rebuild vector memory after validating JSONL and SQLite stores.")
    if not recommendations:
        recommendations.append("Use this report as the baseline before adding affective consolidation or semantic-vector movement metrics.")
    return recommendations


def memory_doctor_report(repo_root: Path | str, *, vector_health: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    memory_dir = root / MEMORY_DIR
    runtime_dir = root / RUNTIME_DIR
    jsonl_reports = {
        name: audit_jsonl_store(memory_dir / name)
        for name in DEFAULT_JSONL_STORES
    }
    archive_report = archive_metadata_summary(memory_dir / "conversation_archive.jsonl")
    thread_report = thread_fragmentation_report(memory_dir)
    route_report = route_latency_summary(runtime_dir / "logs" / "reply_api.log")
    sqlite_reports = {
        "mind_graph.sqlite3": sqlite_health(runtime_dir / "mind_graph.sqlite3"),
        "holo_host.sqlite3": sqlite_health(runtime_dir / "holo_host.sqlite3"),
    }
    vector_report = _vector_static_health(root, vector_health)
    health = biomimetic_health(
        jsonl_reports=jsonl_reports,
        route_summary=route_report,
        thread_report=thread_report,
        metadata_report=archive_report,
        vector_report=vector_report,
        sqlite_reports=sqlite_reports,
    )
    return {
        "schema": "holo.memory_doctor.v1",
        "repo_root": str(root),
        "privacy": {
            "raw_text_included": False,
            "redaction_policy": "content-bearing fields are counted or typed but not emitted",
        },
        "jsonl_stores": jsonl_reports,
        "sqlite": sqlite_reports,
        "vector": vector_report,
        "reply_route_latency": route_report,
        "archive_metadata": archive_report,
        "thread_identity": thread_report,
        "biomimetic_health": health,
        "recommendations": _recommendations(health),
    }
