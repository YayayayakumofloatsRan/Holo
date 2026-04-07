#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from holo_memory_library import rag_memory as rm


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    return rows


def dedupe_by_id(rows: list[dict[str, Any]], prepare: Callable[[dict[str, Any]], dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        prepared = prepare(row)
        row_id = str(prepared.get("id", "")).strip()
        if not row_id:
            row_id = json.dumps(prepared, ensure_ascii=False, sort_keys=True)
        if row_id not in merged:
            ordered.append(row_id)
        merged[row_id] = prepared
    return [merged[row_id] for row_id in ordered]


def merge_rows(
    target_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    *,
    prepare: Callable[[dict[str, Any]], dict[str, Any]],
    dedupe: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    return dedupe(list(target_rows) + list(source_rows))


def merge_memory_dir(source_dir: Path, *, dry_run: bool = False) -> list[dict[str, Any]]:
    target_dir = REPO_ROOT / "holo_memory_library" / "memories"
    reports: list[dict[str, Any]] = []

    working_target = rm.load_rows("working")
    working_source = load_jsonl(source_dir / "working_store.jsonl")
    working_merged = merge_rows(
        working_target,
        working_source,
        prepare=lambda row: rm.prepare_row(row, "working"),
        dedupe=lambda rows: dedupe_by_id(rows, lambda row: rm.prepare_row(row, "working")),
    )
    reports.append({"store": "working_store.jsonl", "before": len(working_target), "source": len(working_source), "after": len(working_merged)})
    if not dry_run:
        rm.write_rows("working", working_merged)

    durable_target = rm.load_rows("durable")
    durable_source = load_jsonl(source_dir / "memory_store.jsonl")
    durable_merged = merge_rows(
        durable_target,
        durable_source,
        prepare=lambda row: rm.prepare_row(row, "durable"),
        dedupe=lambda rows: dedupe_by_id(rows, lambda row: rm.prepare_row(row, "durable")),
    )
    reports.append({"store": "memory_store.jsonl", "before": len(durable_target), "source": len(durable_source), "after": len(durable_merged)})
    if not dry_run:
        rm.write_rows("durable", durable_merged)

    candidate_target = rm.load_rows("candidate")
    candidate_source = load_jsonl(source_dir / "candidate_store.jsonl")
    candidate_merged = merge_rows(
        candidate_target,
        candidate_source,
        prepare=lambda row: rm.prepare_row(row, "candidate"),
        dedupe=lambda rows: dedupe_by_id(rows, lambda row: rm.prepare_row(row, "candidate")),
    )
    reports.append({"store": "candidate_store.jsonl", "before": len(candidate_target), "source": len(candidate_source), "after": len(candidate_merged)})
    if not dry_run:
        rm.write_rows("candidate", candidate_merged)

    archive_target = rm.load_archive()
    archive_source = load_jsonl(source_dir / "conversation_archive.jsonl")
    archive_merged = merge_rows(
        archive_target,
        archive_source,
        prepare=rm.prepare_archive_row,
        dedupe=rm.dedupe_archive_rows,
    )
    reports.append({"store": "conversation_archive.jsonl", "before": len(archive_target), "source": len(archive_source), "after": len(archive_merged)})
    if not dry_run:
        rm.write_archive(archive_merged)

    emotion_target = rm.load_emotion_trace()
    emotion_source = load_jsonl(source_dir / "emotion_trace.jsonl")
    emotion_merged = merge_rows(
        emotion_target,
        emotion_source,
        prepare=rm.prepare_emotion_trace_entry,
        dedupe=rm.dedupe_emotion_rows,
    )
    reports.append({"store": "emotion_trace.jsonl", "before": len(emotion_target), "source": len(emotion_source), "after": len(emotion_merged)})
    if not dry_run:
        rm.write_emotion_trace(emotion_merged)

    callback_target = rm.load_callback_candidates()
    callback_source = load_jsonl(source_dir / "callback_candidates.jsonl")
    callback_merged = merge_rows(
        callback_target,
        callback_source,
        prepare=rm.prepare_callback_row,
        dedupe=rm.dedupe_callback_rows,
    )
    reports.append({"store": "callback_candidates.jsonl", "before": len(callback_target), "source": len(callback_source), "after": len(callback_merged)})
    if not dry_run:
        rm.write_callback_candidates(callback_merged)

    thought_target = rm.load_thought_stream()
    thought_source = load_jsonl(source_dir / "thought_stream.jsonl")
    thought_merged = merge_rows(
        thought_target,
        thought_source,
        prepare=rm.prepare_thought_row,
        dedupe=rm.dedupe_thought_rows,
    )
    reports.append({"store": "thought_stream.jsonl", "before": len(thought_target), "source": len(thought_source), "after": len(thought_merged)})
    if not dry_run:
        rm.write_thought_stream(thought_merged)

    initiative_target = rm.load_initiative_candidates()
    initiative_source = load_jsonl(source_dir / "initiative_candidates.jsonl")
    initiative_merged = merge_rows(
        initiative_target,
        initiative_source,
        prepare=rm.prepare_initiative_row,
        dedupe=rm.dedupe_initiative_rows,
    )
    reports.append({"store": "initiative_candidates.jsonl", "before": len(initiative_target), "source": len(initiative_source), "after": len(initiative_merged)})
    if not dry_run:
        rm.write_initiative_candidates(initiative_merged)

    return reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge memory JSONL files from another Holo repo into this one.")
    parser.add_argument("--source-dir", required=True, help="Directory containing source memory JSONL files")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    source_dir = Path(args.source_dir).expanduser().resolve()
    if not source_dir.exists():
        raise SystemExit(f"source dir not found: {source_dir}")

    reports = merge_memory_dir(source_dir, dry_run=args.dry_run)
    print(json.dumps({"source_dir": str(source_dir), "dry_run": bool(args.dry_run), "reports": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
