from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .common import compact_text

MEMORY_DIR = Path("holo_memory_library") / "memories"
STAGE104_SCHEMA = "holo.stage104.context_learning.v1"
STAGE104_CONFIRMATION = "APPLY_STAGE104_CONTEXT_LEARNING_FROM_WSL"

THEMES: tuple[dict[str, Any], ...] = (
    {
        "label": "project_stage",
        "title": "Stage100+ biomimetic research direction",
        "keywords": (
            "stage",
            "stage100",
            "stage101",
            "stage102",
            "stage103",
            "stage104",
            "\u9636\u6bb5",
            "\u63a8\u8fdb",
        ),
        "line": "Holo is in the Stage100+ biomimetic-agent research arc: the previous stages must become usable cognitive substrate, not more labels.",
        "tags": ("stage104", "project_stage", "biomimetic_agent"),
        "weight": 1.0,
        "prompt_priority": 10,
    },
    {
        "label": "memory_consolidation",
        "title": "working memory to durable semantic memory",
        "keywords": (
            "memory",
            "rag",
            "durable",
            "semantic memory",
            "working memory",
            "long-term memory",
            "consolidation",
            "compression",
            "\u8bb0\u5fc6",
            "\u957f\u671f\u8bb0\u5fc6",
            "\u5de5\u4f5c\u8bb0\u5fc6",
            "\u56fa\u5316",
            "\u538b\u7f29",
        ),
        "line": "The current bottleneck is memory consolidation: working memory and archive are current, but durable semantic memory must receive compressed long-term self-memory.",
        "tags": ("stage104", "context_learning", "semantic_consolidation", "rag"),
        "weight": 1.25,
        "prompt_priority": 20,
    },
    {
        "label": "provider_context_learning",
        "title": "provider API context packet discipline",
        "keywords": (
            "provider",
            "api",
            "context",
            "context learning",
            "packet",
            "model",
            "compression",
            "\u4e0a\u4e0b\u6587",
            "\u53d1\u5305",
            "\u6a21\u578b",
            "\u538b\u7f29",
        ),
        "line": "Provider calls are stateless inference; Holo's learning must happen locally by compressing, selecting, and sending a better context packet.",
        "tags": ("stage104", "provider_api", "context_packet", "context_learning"),
        "weight": 1.05,
        "prompt_priority": 30,
    },
    {
        "label": "biomimetic_topology",
        "title": "semantic-affective attractor topology",
        "keywords": (
            "biomimetic",
            "semantic",
            "affective",
            "topology",
            "vector",
            "attractor",
            "high-dimensional",
            "visualization",
            "\u4eff\u751f",
            "\u610f\u8bc6",
            "\u60c5\u611f",
            "\u8bed\u4e49",
            "\u62d3\u6251",
            "\u5411\u91cf",
            "\u5438\u5f15\u5b50",
            "\u9ad8\u7ef4",
            "\u53ef\u89c6\u5316",
            "\u7f51\u7edc",
        ),
        "line": "The biomimetic hypothesis is that repeated semantic-affective themes form high-dimensional attractors; Stage104 makes those attractors explicit and usable in recall.",
        "tags": ("stage104", "biomimetic", "semantic_topology", "attractor"),
        "weight": 1.15,
        "prompt_priority": 40,
    },
    {
        "label": "experience_deficit",
        "title": "experience must improve, not just observability",
        "keywords": (
            "experience",
            "improve",
            "performance",
            "recall",
            "boring",
            "boundary",
            "\u4f53\u9a8c",
            "\u957f\u8fdb",
            "\u6ca1\u8bb0\u4f4f",
            "\u589e\u76ca",
            "\u6beb\u65e0",
            "\u8fb9\u754c",
            "\u6027\u80fd",
            "\u63d0\u5347",
        ),
        "line": "The operator's acceptance bar is experiential improvement: Holo must recall the real project direction and act less like a recent-log echo.",
        "tags": ("stage104", "operator_feedback", "experience_gate"),
        "weight": 1.1,
        "prompt_priority": 50,
    },
)

BROAD_RECALL_HINTS = (
    "\u56de\u5fc6",
    "\u8bb0\u5f97",
    "\u4efb\u4f55\u4e8b\u60c5",
    "\u60f3\u8d77",
    "remember",
    "memory",
    "before",
    "earlier",
)


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


def _iter_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            text = raw.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                yield payload


def _record_timestamp(row: dict[str, Any]) -> datetime | None:
    for key in ("created_at", "updated_at", "timestamp", "ts", "last_seen_at"):
        parsed = _parse_timestamp(row.get(key))
        if parsed is not None:
            return parsed
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        for key in ("created_at", "updated_at", "timestamp", "ts", "last_seen_at"):
            parsed = _parse_timestamp(metadata.get(key))
            if parsed is not None:
                return parsed
    return None


def _text_for_row(row: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("text", "user_text", "reply_text", "summary", "motif", "prompt", "reason", "query_excerpt", "reply_excerpt"):
        value = str(row.get(key, "") or "").strip()
        if value:
            parts.append(value)
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        for key in ("text", "summary", "motif", "prompt", "reason", "query_excerpt", "reply_excerpt"):
            value = str(metadata.get(key, "") or "").strip()
            if value:
                parts.append(value)
    return " ".join(parts)


def _memory_rows(repo_root: str | Path, store_name: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    rows = list(_iter_jsonl(Path(repo_root) / MEMORY_DIR / store_name))
    rows.sort(key=lambda row: _record_timestamp(row) or datetime.min.replace(tzinfo=timezone.utc))
    if limit is not None and limit >= 0:
        return rows[-limit:]
    return rows


def _stable_digest(*parts: Any, limit: int = 16) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:limit]


def _is_broad_recall_query(query: str | None) -> bool:
    text = str(query or "").strip().lower()
    if not text:
        return False
    return any(hint.lower() in text for hint in BROAD_RECALL_HINTS)


def _keyword_hits(text: str, keywords: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(1 for keyword in keywords if str(keyword).lower() in lowered)


def _timestamps(rows: Iterable[dict[str, Any]]) -> list[datetime]:
    return [timestamp for row in rows if (timestamp := _record_timestamp(row)) is not None]


def _collect_evidence(repo_root: str | Path, *, recent_limit: int) -> dict[str, Any]:
    archive = _memory_rows(repo_root, "conversation_archive.jsonl", limit=recent_limit)
    working = _memory_rows(repo_root, "working_store.jsonl", limit=min(recent_limit, 64))
    thoughts = _memory_rows(repo_root, "thought_stream.jsonl", limit=min(recent_limit, 64))
    durable = _memory_rows(repo_root, "memory_store.jsonl", limit=None)
    latest_sources = archive + working + thoughts
    latest_ts = max(_timestamps(latest_sources), default=None)
    durable_latest_ts = max(_timestamps(durable), default=None)
    first_ts = min(_timestamps(latest_sources + durable), default=None)
    return {
        "archive": archive,
        "working": working,
        "thoughts": thoughts,
        "durable": durable,
        "latest_timestamp": latest_ts,
        "durable_latest_timestamp": durable_latest_ts,
        "first_timestamp": first_ts,
    }


def _durability_gap(evidence: dict[str, Any]) -> dict[str, Any]:
    latest = evidence.get("latest_timestamp")
    durable_latest = evidence.get("durable_latest_timestamp")
    if not isinstance(latest, datetime) or not isinstance(durable_latest, datetime):
        return {
            "status": "unknown",
            "staleness_days": None,
            "latest_activity": _timestamp_text(latest if isinstance(latest, datetime) else None),
            "latest_durable": _timestamp_text(durable_latest if isinstance(durable_latest, datetime) else None),
        }
    staleness_days = max(0, (latest - durable_latest).days)
    if staleness_days >= 30:
        status = "critical"
    elif staleness_days >= 7:
        status = "warn"
    else:
        status = "ok"
    return {
        "status": status,
        "staleness_days": staleness_days,
        "latest_activity": _timestamp_text(latest),
        "latest_durable": _timestamp_text(durable_latest),
    }


def _extract_attractors(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    rows = list(evidence.get("archive", [])) + list(evidence.get("working", [])) + list(evidence.get("thoughts", []))
    attractors: list[dict[str, Any]] = []
    for theme in THEMES:
        scored_rows: list[tuple[int, dict[str, Any], str]] = []
        for row in rows:
            text = _text_for_row(row)
            hits = _keyword_hits(text, theme["keywords"])
            if hits:
                scored_rows.append((hits, row, text))
        if not scored_rows:
            continue
        scored_rows.sort(
            key=lambda item: (
                item[0],
                _record_timestamp(item[1]) or datetime.min.replace(tzinfo=timezone.utc),
            ),
            reverse=True,
        )
        support_count = len(scored_rows)
        latest_ts = max(_timestamps(item[1] for item in scored_rows), default=None)
        source_ids = [
            str(item[1].get("id", "") or item[1].get("turn_id", "") or "")
            for item in scored_rows[:8]
            if str(item[1].get("id", "") or item[1].get("turn_id", "") or "").strip()
        ]
        source_excerpt = compact_text(scored_rows[0][2], 240)
        score = round(min(1.0, float(theme["weight"]) * (0.22 + support_count * 0.12 + sum(item[0] for item in scored_rows[:5]) * 0.04)), 4)
        line = str(theme["line"])
        attractors.append(
            {
                "id": f"stage104:{theme['label']}:{_stable_digest(theme['label'], source_ids, _timestamp_text(latest_ts), limit=10)}",
                "label": str(theme["label"]),
                "title": str(theme["title"]),
                "score": score,
                "support_count": support_count,
                "latest_timestamp": _timestamp_text(latest_ts),
                "source_ids": source_ids,
                "source_excerpt": source_excerpt,
                "semantic_line": line,
                "prompt_line": f"Stage104 attractor: {line}",
                "tags": list(theme["tags"]),
                "prompt_priority": int(theme.get("prompt_priority", 100)),
                "topology": {
                    "node": f"attractor:{theme['label']}",
                    "source_nodes": [f"memory:{source_id}" for source_id in source_ids[:6]],
                    "edge_type": "semantic_consolidation_support",
                },
            }
        )
    attractors.sort(key=lambda item: (float(item.get("score", 0.0)), int(item.get("support_count", 0))), reverse=True)
    return attractors


def stage104_context_learning_report(
    repo_root: str | Path,
    *,
    query: str | None = None,
    recent_limit: int = 96,
    attractor_limit: int = 8,
) -> dict[str, Any]:
    evidence = _collect_evidence(repo_root, recent_limit=max(1, int(recent_limit)))
    attractors = _extract_attractors(evidence)[: max(1, int(attractor_limit))]
    gap = _durability_gap(evidence)
    return {
        "schema": STAGE104_SCHEMA,
        "stage": 104,
        "generated_at": _timestamp_text(datetime.now(timezone.utc)),
        "repo_root": str(Path(repo_root).resolve()),
        "query": str(query or ""),
        "broad_recall_query": _is_broad_recall_query(query),
        "warehouse_start": _timestamp_text(evidence.get("first_timestamp") if isinstance(evidence.get("first_timestamp"), datetime) else None),
        "durability_gap": gap,
        "source_counts": {
            "archive_recent": len(evidence.get("archive", [])),
            "working_recent": len(evidence.get("working", [])),
            "thought_recent": len(evidence.get("thoughts", [])),
            "durable_total": len(evidence.get("durable", [])),
        },
        "attractors": attractors,
        "prompt_lines": [str(item.get("prompt_line", "")) for item in attractors if str(item.get("prompt_line", "")).strip()],
        "acceptance": {
            "context_learning_local": True,
            "provider_weights_changed": False,
            "durable_gap_visible": gap.get("status") in {"warn", "critical"},
            "semantic_attractor_count": len(attractors),
        },
    }


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return list(_iter_jsonl(path))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _candidate_key(row: dict[str, Any]) -> str:
    return _stable_digest(str(row.get("kind", "")), str(row.get("text", "")), limit=18)


def _candidate_from_attractor(attractor: dict[str, Any], *, existing_rows: list[dict[str, Any]]) -> dict[str, Any]:
    now = _timestamp_text(datetime.now(timezone.utc))
    text = str(attractor.get("semantic_line", "") or "").strip()
    row = {
        "id": f"candidate-stage104-{_stable_digest(text, attractor.get('label', ''), limit=14)}",
        "status": "candidate",
        "kind": "context_attractor",
        "text": text,
        "tags": sorted(set(["stage104", "context_learning", *list(attractor.get("tags", []))])),
        "source": "stage104.context_learning",
        "importance": round(min(0.98, 0.72 + float(attractor.get("score", 0.0)) * 0.22), 4),
        "confidence": round(min(0.98, 0.76 + min(0.18, int(attractor.get("support_count", 0)) * 0.03)), 4),
        "explicit_user_signal": True,
        "derived_from": list(attractor.get("source_ids", []))[:8],
        "created_at": now,
        "last_seen_at": str(attractor.get("latest_timestamp", "") or now),
        "metadata": {
            "stage": 104,
            "attractor_id": str(attractor.get("id", "")),
            "label": str(attractor.get("label", "")),
            "support_count": int(attractor.get("support_count", 0) or 0),
            "topology": dict(attractor.get("topology", {})) if isinstance(attractor.get("topology", {}), dict) else {},
        },
    }
    existing_ids = {str(item.get("id", "")) for item in existing_rows}
    if row["id"] in existing_ids:
        row["id"] = f"{row['id']}-{_stable_digest(len(existing_rows), now, limit=6)}"
    return row


def stage104_candidate_plan(
    repo_root: str | Path,
    *,
    apply: bool = False,
    query: str | None = None,
    recent_limit: int = 96,
    attractor_limit: int = 8,
) -> dict[str, Any]:
    root = Path(repo_root)
    report = stage104_context_learning_report(root, query=query, recent_limit=recent_limit, attractor_limit=attractor_limit)
    candidate_path = root / MEMORY_DIR / "candidate_store.jsonl"
    durable_path = root / MEMORY_DIR / "memory_store.jsonl"
    candidate_rows = _load_jsonl(candidate_path)
    durable_rows = _load_jsonl(durable_path)
    existing_keys = {_candidate_key(row) for row in candidate_rows + durable_rows}
    staged: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for attractor in report["attractors"]:
        row = _candidate_from_attractor(attractor, existing_rows=candidate_rows + staged)
        key = _candidate_key(row)
        if key in existing_keys:
            skipped.append({"attractor_id": attractor["id"], "reason": "already_present"})
            continue
        existing_keys.add(key)
        staged.append(row)
    if apply and staged:
        _write_jsonl(candidate_path, candidate_rows + staged)
    return {
        "schema": STAGE104_SCHEMA,
        "stage": 104,
        "status": "applied" if apply else "plan",
        "dry_run": not bool(apply),
        "candidate_path": str(candidate_path),
        "would_apply": [
            {
                "candidate_id": row["id"],
                "kind": row["kind"],
                "label": row["metadata"]["label"],
                "confidence": row["confidence"],
                "importance": row["importance"],
                "derived_from_count": len(row["derived_from"]),
            }
            for row in staged
        ],
        "would_skip": skipped,
        "applied_count": len(staged) if apply else 0,
        "report": report,
        "privacy": {
            "raw_text_included": False,
            "policy": "candidate text is derived semantic summary, not verbatim archive export",
        },
    }


def stage104_context_packet(
    repo_root: str | Path,
    *,
    query: str | None = None,
    limit: int = 4,
    recent_limit: int = 96,
) -> dict[str, Any]:
    report = stage104_context_learning_report(repo_root, query=query, recent_limit=recent_limit, attractor_limit=max(1, int(limit)))
    attractors = sorted(
        list(report.get("attractors", [])),
        key=lambda item: (int(item.get("prompt_priority", 100)), -float(item.get("score", 0.0) or 0.0)),
    )[: max(1, int(limit))]
    return {
        "schema": STAGE104_SCHEMA,
        "stage": 104,
        "context_learning_visible": bool(attractors),
        "broad_recall_query": bool(report.get("broad_recall_query", False)),
        "durability_gap": dict(report.get("durability_gap", {})),
        "attractors": attractors,
        "prompt_lines": [str(item.get("prompt_line", "")) for item in attractors if str(item.get("prompt_line", "")).strip()],
        "selected_memory_ids": [str(item.get("id", "")) for item in attractors if str(item.get("id", "")).strip()],
    }


def inject_stage104_context(packet: dict[str, Any], context_packet: dict[str, Any], *, limit: int = 4) -> dict[str, Any]:
    injected = dict(packet)
    prompt_lines = [str(line).strip() for line in list(context_packet.get("prompt_lines", [])) if str(line).strip()][: max(1, int(limit))]
    if not prompt_lines:
        injected["stage104"] = {
            "context_learning_visible": False,
            "semantic_attractor_count": 0,
            "durability_gap": dict(context_packet.get("durability_gap", {})) if isinstance(context_packet.get("durability_gap", {}), dict) else {},
        }
        return injected
    existing_lines = [str(line) for line in list(injected.get("thread_recall_lines", [])) if str(line).strip()]
    injected["thread_recall_lines"] = [*prompt_lines, *[line for line in existing_lines if line not in prompt_lines]][:8]
    episodic = dict(injected.get("episodic_recall", {})) if isinstance(injected.get("episodic_recall", {}), dict) else {}
    episodic_lines = [str(line) for line in list(episodic.get("lines", [])) if str(line).strip()]
    episodic["lines"] = [*prompt_lines, *[line for line in episodic_lines if line not in prompt_lines]][:8]
    injected["episodic_recall"] = episodic
    injected["semantic_attractor_lines"] = prompt_lines
    injected["selected_memory_ids"] = [
        *[str(item) for item in list(context_packet.get("selected_memory_ids", [])) if str(item).strip()],
        *[str(item) for item in list(injected.get("selected_memory_ids", [])) if str(item).strip()],
    ]
    seen: set[str] = set()
    injected["selected_memory_ids"] = [item for item in injected["selected_memory_ids"] if not (item in seen or seen.add(item))]
    injected["stage104"] = {
        "context_learning_visible": True,
        "semantic_attractor_count": len(prompt_lines),
        "broad_recall_query": bool(context_packet.get("broad_recall_query", False)),
        "durability_gap": dict(context_packet.get("durability_gap", {})) if isinstance(context_packet.get("durability_gap", {}), dict) else {},
        "top_attractor_labels": [str(item.get("label", "")) for item in list(context_packet.get("attractors", []))[: len(prompt_lines)] if isinstance(item, dict)],
    }
    return injected
