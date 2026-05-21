from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Iterable

MEMORY_DIR = Path("holo_memory_library") / "memories"
RUNTIME_DIR = Path(".holo_runtime")
DEFAULT_STORES = (
    "memory_store.jsonl",
    "working_store.jsonl",
    "candidate_store.jsonl",
    "conversation_archive.jsonl",
    "thought_stream.jsonl",
    "emotion_trace.jsonl",
    "callback_candidates.jsonl",
    "initiative_candidates.jsonl",
)
STORE_ROLES = {
    "memory_store.jsonl": "durable semantic memory",
    "working_store.jsonl": "fast working memory",
    "candidate_store.jsonl": "semantic promotion candidates",
    "conversation_archive.jsonl": "episodic archive",
    "thought_stream.jsonl": "offline thought stream",
    "emotion_trace.jsonl": "affective trace",
    "callback_candidates.jsonl": "callback/proactive memory",
    "initiative_candidates.jsonl": "initiative queue memory",
}
TEXT_KEYS = (
    "text",
    "user_text",
    "reply_text",
    "prompt",
    "reason",
    "summary",
    "motif",
    "guidance",
    "query_excerpt",
    "reply_excerpt",
    "content",
)
TIMESTAMP_KEYS = ("created_at", "updated_at", "timestamp", "ts", "last_seen_at")
SQLITE_TABLES = {
    "mind_graph.sqlite3": (
        "mind_nodes",
        "mind_edges",
        "mind_thread_state",
        "active_thread_state",
        "consciousness_ledger",
        "mind_activation_events",
        "brain_loop_runs",
    ),
    "holo_host.sqlite3": (
        "threads",
        "messages",
        "processor_usage_ledger",
        "online_canary_traces",
        "jobs",
    ),
}


def _parse_timestamp(raw: Any) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _timestamp_text(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.isoformat().replace("+00:00", "Z")


def _record_timestamp(record: dict[str, Any]) -> datetime | None:
    for key in TIMESTAMP_KEYS:
        parsed = _parse_timestamp(record.get(key))
        if parsed is not None:
            return parsed
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in TIMESTAMP_KEYS:
            parsed = _parse_timestamp(metadata.get(key))
            if parsed is not None:
                return parsed
    return None


def _iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any] | None, str | None]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, raw in enumerate(handle, start=1):
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as exc:
                yield line_number, None, exc.msg
                continue
            if not isinstance(payload, dict):
                yield line_number, None, "row is not a JSON object"
                continue
            yield line_number, payload, None


def _compact_text(value: Any, limit: int) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)]}..."


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="replace")).hexdigest()[:12]


def _field_payload(key: str, value: Any, *, include_raw: bool, max_chars: int) -> dict[str, Any]:
    text = str(value or "")
    payload: dict[str, Any] = {"key": key, "chars": len(text), "sha256_12": _stable_hash(text)}
    if include_raw:
        payload["text"] = _compact_text(text, max_chars)
    return payload


def _text_fields(record: dict[str, Any], *, include_raw: bool, max_chars: int) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []
    for key in TEXT_KEYS:
        value = record.get(key)
        if value not in (None, ""):
            fields.append(_field_payload(key, value, include_raw=include_raw, max_chars=max_chars))
    metadata = record.get("metadata")
    if isinstance(metadata, dict):
        for key in TEXT_KEYS:
            value = metadata.get(key)
            if value not in (None, ""):
                fields.append(_field_payload(f"metadata.{key}", value, include_raw=include_raw, max_chars=max_chars))
    return fields


def _sample_record(line_number: int, record: dict[str, Any], *, include_raw: bool, max_chars: int) -> dict[str, Any]:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    payload = {
        "line": line_number,
        "id": str(record.get("id", "") or record.get("memory_id", "") or record.get("turn_id", "") or ""),
        "timestamp": _timestamp_text(_record_timestamp(record)),
        "channel": str(record.get("channel", "") or metadata.get("channel", "") or ""),
        "thread_key": str(record.get("thread_key", "") or metadata.get("thread_key", "") or ""),
        "chat_name": str(record.get("chat_name", "") or metadata.get("chat_name", "") or ""),
        "kind": str(record.get("kind", "") or record.get("source", "") or record.get("type", "") or ""),
        "confidence": record.get("confidence"),
        "importance": record.get("importance"),
        "text_fields": _text_fields(record, include_raw=include_raw, max_chars=max_chars),
    }
    if include_raw:
        payload["tags"] = record.get("tags", [])
        payload["selected_memory_ids"] = metadata.get("selected_memory_ids", [])
        payload["route"] = metadata.get("route") or metadata.get("memory_route") or metadata.get("retrieval_mode", "")
    return payload


def _audit_store(path: Path, *, include_raw: bool, sample_limit: int, max_chars: int) -> dict[str, Any]:
    valid: list[tuple[int, dict[str, Any]]] = []
    invalid: list[dict[str, Any]] = []
    channels: Counter[str] = Counter()
    thread_keys: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    first_seen: datetime | None = None
    last_seen: datetime | None = None

    for line_number, record, error in _iter_jsonl(path):
        if error or record is None:
            if len(invalid) < 8:
                invalid.append({"line": line_number, "error": error or "invalid"})
            continue
        valid.append((line_number, record))
        for key, counter in (("channel", channels), ("thread_key", thread_keys), ("kind", kinds)):
            value = str(record.get(key, "") or record.get("source", "") if key == "kind" else record.get(key, "") or "").strip()
            if value:
                counter[value] += 1
        timestamp = _record_timestamp(record)
        if timestamp is not None:
            first_seen = timestamp if first_seen is None else min(first_seen, timestamp)
            last_seen = timestamp if last_seen is None else max(last_seen, timestamp)

    limit = max(0, int(sample_limit))
    first_records = valid[:limit]
    latest_records = valid[-limit:] if limit and len(valid) > limit else []

    return {
        "exists": path.exists(),
        "path": str(path),
        "role": STORE_ROLES.get(path.name, "memory store"),
        "bytes": path.stat().st_size if path.exists() else 0,
        "valid_rows": len(valid),
        "invalid_rows": len(invalid),
        "invalid_examples": invalid,
        "first_timestamp": _timestamp_text(first_seen),
        "last_timestamp": _timestamp_text(last_seen),
        "top_channels": [{"key": key, "count": count} for key, count in channels.most_common(8)],
        "top_thread_keys": [{"key": key, "count": count} for key, count in thread_keys.most_common(8)],
        "top_kinds": [{"key": key, "count": count} for key, count in kinds.most_common(8)],
        "samples": {
            "first": [_sample_record(line, row, include_raw=include_raw, max_chars=max_chars) for line, row in first_records],
            "latest": [_sample_record(line, row, include_raw=include_raw, max_chars=max_chars) for line, row in latest_records],
        },
    }


def _sqlite_counts(db_path: Path, table_names: Iterable[str]) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(db_path), "exists": db_path.exists(), "bytes": db_path.stat().st_size if db_path.exists() else 0, "tables": {}}
    if not db_path.exists():
        return payload
    try:
        with sqlite3.connect(db_path) as connection:
            known = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
            for table in table_names:
                if table not in known:
                    payload["tables"][table] = {"exists": False, "rows": 0}
                    continue
                rows = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                payload["tables"][table] = {"exists": True, "rows": int(rows)}
    except sqlite3.Error as exc:
        payload["error"] = str(exc)
    return payload


def _line_list(value: Any, *, include_raw: bool, max_chars: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in value:
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False, sort_keys=True)
        rows.append(_field_payload("line", text, include_raw=include_raw, max_chars=max_chars))
    return rows


def _hit_samples(value: Any, *, include_raw: bool, max_chars: int, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    samples: list[dict[str, Any]] = []
    for item in value[: max(0, int(limit))]:
        if not isinstance(item, dict):
            samples.append(_field_payload("hit", item, include_raw=include_raw, max_chars=max_chars))
            continue
        text = item.get("text") or item.get("summary") or item.get("content") or item.get("line") or item.get("label") or ""
        sample = {
            "id": str(item.get("id", "") or item.get("node_id", "") or item.get("memory_id", "") or ""),
            "score": item.get("score", item.get("final_score", item.get("confidence"))),
            "kind": str(item.get("kind", "") or item.get("type", "") or ""),
            "text": _field_payload("text", text, include_raw=include_raw, max_chars=max_chars),
        }
        samples.append(sample)
    return samples


def _rag_summary(
    *,
    doctor: dict[str, Any] | None,
    inspect_mind: dict[str, Any] | None,
    trace_hybrid: dict[str, Any] | None,
    reply_probe: dict[str, Any] | None,
    include_raw: bool,
    max_chars: int,
    sample_limit: int,
) -> dict[str, Any]:
    inspect_mind = inspect_mind if isinstance(inspect_mind, dict) else {}
    trace_hybrid = trace_hybrid if isinstance(trace_hybrid, dict) else {}
    reply_probe = reply_probe if isinstance(reply_probe, dict) else {}
    return {
        "doctor_health": dict((doctor or {}).get("biomimetic_health", {})),
        "inspect_mind": {
            "tier": inspect_mind.get("tier"),
            "build_ms": inspect_mind.get("build_ms"),
            "recall_reason": inspect_mind.get("recall_reason"),
            "selected_memory_count": len(inspect_mind.get("selected_memory_ids") or []),
            "selected_memory_ids": list(inspect_mind.get("selected_memory_ids") or [])[: max(0, int(sample_limit))],
            "episodic_lines": _line_list(inspect_mind.get("episodic_lines"), include_raw=include_raw, max_chars=max_chars),
            "thread_recall_lines": _line_list(inspect_mind.get("thread_recall_lines"), include_raw=include_raw, max_chars=max_chars),
            "consciousness_lines": _line_list(inspect_mind.get("consciousness_lines"), include_raw=include_raw, max_chars=max_chars),
            "vector_hits": _hit_samples(inspect_mind.get("vector_hits"), include_raw=include_raw, max_chars=max_chars, limit=sample_limit),
        },
        "trace_hybrid": {
            "tier": trace_hybrid.get("tier"),
            "memory_route": trace_hybrid.get("memory_route"),
            "retrieval_mode": trace_hybrid.get("retrieval_mode"),
            "recall_confidence": trace_hybrid.get("recall_confidence"),
            "build_ms": trace_hybrid.get("build_ms"),
            "graph_confidence": trace_hybrid.get("graph_confidence"),
            "graph_hits": _hit_samples(trace_hybrid.get("graph_hits"), include_raw=include_raw, max_chars=max_chars, limit=sample_limit),
            "vector_hits": _hit_samples(trace_hybrid.get("vector_hits"), include_raw=include_raw, max_chars=max_chars, limit=sample_limit),
            "retrieval_trace_keys": sorted((trace_hybrid.get("retrieval_trace") or {}).keys()) if isinstance(trace_hybrid.get("retrieval_trace"), dict) else [],
        },
        "reply_probe": {
            "selected_action": reply_probe.get("selected_action"),
            "action_rationale": _field_payload(
                "action_rationale",
                reply_probe.get("action_rationale", ""),
                include_raw=include_raw,
                max_chars=max_chars,
            ),
            "expression_budget": reply_probe.get("expression_budget", {}),
        },
    }


def memory_warehouse_report(
    repo_root: str | Path,
    *,
    include_raw: bool = False,
    sample_limit: int = 8,
    max_chars: int = 320,
    doctor: dict[str, Any] | None = None,
    inspect_mind: dict[str, Any] | None = None,
    trace_hybrid: dict[str, Any] | None = None,
    reply_probe: dict[str, Any] | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    stores: dict[str, Any] = {}
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    for name in DEFAULT_STORES:
        store = _audit_store(root / MEMORY_DIR / name, include_raw=include_raw, sample_limit=sample_limit, max_chars=max_chars)
        stores[name] = store
        first_seen = min(filter(None, [first_seen, _parse_timestamp(store.get("first_timestamp"))]), default=first_seen)
        last_seen = max(filter(None, [last_seen, _parse_timestamp(store.get("last_timestamp"))]), default=last_seen)

    sqlite = {
        db_name: _sqlite_counts(root / RUNTIME_DIR / db_name, tables)
        for db_name, tables in SQLITE_TABLES.items()
    }
    return {
        "schema": "holo.memory_warehouse.v1",
        "repo_root": str(root),
        "generated_at": _timestamp_text(datetime.now(timezone.utc)),
        "warehouse_start": _timestamp_text(first_seen),
        "warehouse_latest": _timestamp_text(last_seen),
        "privacy": {
            "raw_text_included": bool(include_raw),
            "text_policy": "raw local excerpts included" if include_raw else "text hashes and lengths only",
        },
        "stores": stores,
        "sqlite": sqlite,
        "rag": _rag_summary(
            doctor=doctor,
            inspect_mind=inspect_mind,
            trace_hybrid=trace_hybrid,
            reply_probe=reply_probe,
            include_raw=include_raw,
            max_chars=max_chars,
            sample_limit=sample_limit,
        ),
    }


def _html_text_field(field: dict[str, Any]) -> str:
    label = escape(str(field.get("key", "")))
    if "text" in field:
        return f"<div><strong>{label}</strong>: {escape(str(field.get('text', '')))}</div>"
    return f"<div><strong>{label}</strong>: {field.get('chars', 0)} chars, hash {escape(str(field.get('sha256_12', '')))}</div>"


def _html_samples(samples: list[dict[str, Any]]) -> str:
    if not samples:
        return "<p class=\"muted\">No samples.</p>"
    rows = []
    for item in samples:
        text_fields = "".join(_html_text_field(field) for field in item.get("text_fields", []))
        rows.append(
            "<tr>"
            f"<td>{escape(str(item.get('line', '')))}</td>"
            f"<td>{escape(str(item.get('timestamp', '')))}</td>"
            f"<td>{escape(str(item.get('id', '')))}</td>"
            f"<td>{escape(str(item.get('channel', '')))}</td>"
            f"<td>{escape(str(item.get('thread_key', '')))}</td>"
            f"<td>{escape(str(item.get('kind', '')))}</td>"
            f"<td>{text_fields}</td>"
            "</tr>"
        )
    return "<table><thead><tr><th>line</th><th>time</th><th>id</th><th>channel</th><th>thread</th><th>kind</th><th>text</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>"


def _html_hit_list(hits: list[dict[str, Any]]) -> str:
    if not hits:
        return "<p class=\"muted\">No hits.</p>"
    items = []
    for hit in hits:
        text = _html_text_field(dict(hit.get("text", {})))
        items.append(
            f"<li><span class=\"mono\">{escape(str(hit.get('id', '')))}</span> "
            f"score={escape(str(hit.get('score', '')))} kind={escape(str(hit.get('kind', '')))} {text}</li>"
        )
    return "<ul>" + "".join(items) + "</ul>"


def render_memory_warehouse_html(report: dict[str, Any]) -> str:
    store_sections = []
    for name, store in report.get("stores", {}).items():
        store_sections.append(
            "<section>"
            f"<h2>{escape(str(name))}</h2>"
            f"<p>{escape(str(store.get('role', '')))} | rows={store.get('valid_rows', 0)} | "
            f"first={escape(str(store.get('first_timestamp', '')))} | latest={escape(str(store.get('last_timestamp', '')))}</p>"
            "<h3>First Rows</h3>"
            + _html_samples(store.get("samples", {}).get("first", []))
            + "<h3>Latest Rows</h3>"
            + _html_samples(store.get("samples", {}).get("latest", []))
            + "</section>"
        )
    rag = report.get("rag", {})
    inspect = rag.get("inspect_mind", {})
    trace = rag.get("trace_hybrid", {})
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Holo Memory Warehouse</title>
<style>
body {{ margin: 0; font: 14px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; background: #f6f7f9; color: #1f2933; }}
header {{ padding: 24px 32px; background: #10202f; color: white; }}
main {{ padding: 24px 32px 48px; }}
section {{ margin: 0 0 24px; padding: 18px; background: white; border: 1px solid #d9dee7; border-radius: 8px; }}
h1, h2, h3 {{ margin: 0 0 10px; }}
table {{ width: 100%; border-collapse: collapse; margin: 8px 0 16px; table-layout: fixed; }}
th, td {{ border-bottom: 1px solid #e5e9f0; padding: 7px; vertical-align: top; word-break: break-word; }}
th {{ text-align: left; color: #3d4a5c; background: #f1f4f8; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }}
.metric {{ padding: 12px; background: #fff; border: 1px solid #d9dee7; border-radius: 8px; }}
.mono {{ font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }}
.muted {{ color: #667085; }}
ul {{ margin-top: 4px; }}
</style>
</head>
<body>
<header>
<h1>Holo Memory Warehouse</h1>
<p>repo={escape(str(report.get("repo_root", "")))} | generated={escape(str(report.get("generated_at", "")))} | raw={report.get("privacy", {}).get("raw_text_included")}</p>
</header>
<main>
<section>
<h2>Warehouse Range</h2>
<div class="grid">
<div class="metric"><strong>First memory timestamp</strong><br>{escape(str(report.get("warehouse_start", "")))}</div>
<div class="metric"><strong>Latest memory timestamp</strong><br>{escape(str(report.get("warehouse_latest", "")))}</div>
<div class="metric"><strong>Privacy mode</strong><br>{escape(str(report.get("privacy", {}).get("text_policy", "")))}</div>
</div>
</section>
<section>
<h2>RAG Packet Observation</h2>
<p>inspect tier={escape(str(inspect.get("tier", "")))} build_ms={escape(str(inspect.get("build_ms", "")))} selected_memory_count={escape(str(inspect.get("selected_memory_count", "")))}</p>
<p>trace tier={escape(str(trace.get("tier", "")))} route={escape(str(trace.get("memory_route", "")))} confidence={escape(str(trace.get("recall_confidence", "")))}</p>
<h3>Inspect Mind Lines</h3>
{_html_hit_list([{"id": "", "score": "", "kind": "episodic", "text": line} for line in inspect.get("episodic_lines", []) + inspect.get("thread_recall_lines", []) + inspect.get("consciousness_lines", [])])}
<h3>Graph Hits</h3>
{_html_hit_list(trace.get("graph_hits", []))}
<h3>Vector Hits</h3>
{_html_hit_list(trace.get("vector_hits", []))}
</section>
{''.join(store_sections)}
</main>
</body>
</html>
"""
    return html


def write_memory_warehouse_artifacts(report: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "holo_memory_warehouse.json"
    html_path = out / "holo_memory_warehouse.html"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(render_memory_warehouse_html(report), encoding="utf-8")
    return {"json": str(json_path), "html": str(html_path)}
