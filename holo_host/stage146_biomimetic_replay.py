from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any

from .common import atomic_write_text, compact_text, json_dumps, stable_digest, utc_now

STAGE146_REPLAY_SCHEMA = "holo.stage146.biomimetic_replay.v1"

REPLAY_ROW_FIELDS = (
    "turn_id",
    "time",
    "input_summary",
    "packet_budget",
    "tool_grounding",
    "memory_grounding",
    "memory_alignment",
    "semantic_novelty",
    "context_economy",
    "outcome_appraisal",
    "reaction_kernel_shadow",
    "visible_bubbles",
    "state_delta_summary",
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return int(default)


def _status(report: Any) -> str:
    return str(_dict(report).get("status", "") or "").strip()


def _metadata_from_message(row: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except json.JSONDecodeError:
        payload = {}
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    return dict(metadata) if isinstance(metadata, dict) else {}


def _metadata_report(metadata: dict[str, Any], key: str) -> dict[str, Any]:
    if isinstance(metadata.get(key), dict):
        return dict(metadata[key])
    for container_key in ("debug", "reply_debug", "reply_plan_debug"):
        container = _dict(metadata.get(container_key))
        if isinstance(container.get(key), dict):
            return dict(container[key])
    return {}


def _metadata_list(metadata: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = metadata.get(key)
    if isinstance(value, list):
        return _list_dicts(value)
    for container_key in ("debug", "reply_debug", "reply_plan_debug"):
        container = _dict(metadata.get(container_key))
        value = container.get(key)
        if isinstance(value, list):
            return _list_dicts(value)
    return []


def _visible_bubbles(metadata: dict[str, Any], body_text: str) -> list[dict[str, Any]]:
    candidates = _list_dicts(metadata.get("reply_bubbles")) or _list_dicts(metadata.get("bubbles"))
    if candidates:
        bubbles = []
        for index, item in enumerate(candidates):
            text = str(item.get("text", "") or item.get("body", "") or "").strip()
            if not text:
                continue
            bubbles.append(
                {
                    "index": index,
                    "text": compact_text(text, 260),
                    "purpose": str(item.get("purpose", "") or item.get("semantic_role", "") or "visible_reply"),
                }
            )
        if bubbles:
            return bubbles

    lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
    if not lines and str(body_text or "").strip():
        lines = [str(body_text).strip()]
    return [
        {
            "index": index,
            "text": compact_text(line, 260),
            "purpose": "fast_reaction" if index == 0 else "deep_continuation",
        }
        for index, line in enumerate(lines[:4])
    ]


def _packet_cost(packet_budget: dict[str, Any]) -> int:
    total = _int(packet_budget.get("total_estimated_tokens"), 0)
    if total > 0:
        return total
    return sum(_int(packet.get("estimated_tokens"), 0) for packet in _list_dicts(packet_budget.get("packets")))


def _state_delta_summary(row: dict[str, Any]) -> str:
    packet = _dict(row.get("packet_budget"))
    novelty = _dict(row.get("semantic_novelty"))
    tool = _dict(row.get("tool_grounding"))
    memory_alignment = _dict(row.get("memory_alignment"))
    outcome = _dict(row.get("outcome_appraisal"))
    kernel = _dict(row.get("reaction_kernel_shadow"))
    deltas = [
        str(item.get("parameter", "") or "")
        for item in _list_dicts(kernel.get("kernel_delta_candidates"))
        if str(item.get("parameter", "") or "")
    ]
    parts = [
        f"stop={packet.get('stop_reason')}" if packet.get("stop_reason") else "",
        f"novelty={_status(novelty)}" if _status(novelty) else "",
        f"tool={_status(tool)}" if _status(tool) else "",
        f"memory_alignment={_status(memory_alignment)}" if _status(memory_alignment) else "",
        f"prediction_error={outcome.get('prediction_error')}" if outcome.get("prediction_error") is not None else "",
        f"kernel_delta={','.join(deltas)}" if deltas else "",
    ]
    return compact_text("; ".join(part for part in parts if part), 320)


def _normalise_row(row: dict[str, Any]) -> dict[str, Any]:
    normalized = {field: row.get(field) for field in REPLAY_ROW_FIELDS}
    normalized["turn_id"] = str(normalized.get("turn_id") or "turn_" + stable_digest(json_dumps(row), limit=10))
    normalized["time"] = str(normalized.get("time") or utc_now())
    normalized["input_summary"] = compact_text(str(normalized.get("input_summary") or ""), 240)
    normalized["packet_budget"] = _dict(normalized.get("packet_budget"))
    normalized["tool_grounding"] = _dict(normalized.get("tool_grounding"))
    normalized["memory_grounding"] = _dict(normalized.get("memory_grounding"))
    normalized["memory_alignment"] = _dict(normalized.get("memory_alignment"))
    normalized["semantic_novelty"] = _dict(normalized.get("semantic_novelty"))
    normalized["context_economy"] = _dict(normalized.get("context_economy"))
    normalized["outcome_appraisal"] = _dict(normalized.get("outcome_appraisal"))
    normalized["reaction_kernel_shadow"] = _dict(normalized.get("reaction_kernel_shadow"))
    normalized["visible_bubbles"] = _list_dicts(normalized.get("visible_bubbles"))
    normalized["state_delta_summary"] = compact_text(
        str(normalized.get("state_delta_summary") or _state_delta_summary(normalized)),
        360,
    )
    return normalized


def row_from_stored_outbound(row: dict[str, Any], *, prior_input: str = "") -> dict[str, Any]:
    metadata = _metadata_from_message(row)
    body_text = str(row.get("body_text", "") or "")
    replay_row = {
        "turn_id": str(row.get("message_id") or f"message_{row.get('id', '')}" or stable_digest(body_text, limit=10)),
        "time": str(row.get("created_at", "") or utc_now()),
        "input_summary": compact_text(prior_input, 240),
        "packet_budget": _metadata_report(metadata, "stage143_packet_budget"),
        "tool_grounding": _metadata_report(metadata, "tool_grounding"),
        "memory_grounding": _metadata_report(metadata, "memory_grounding"),
        "memory_alignment": _metadata_report(metadata, "memory_alignment"),
        "semantic_novelty": _metadata_report(metadata, "stage142_semantic_novelty"),
        "context_economy": _metadata_report(metadata, "stage144_context_economy"),
        "outcome_appraisal": _metadata_report(metadata, "stage145_outcome_appraisal"),
        "reaction_kernel_shadow": _metadata_report(metadata, "stage145_reaction_kernel_shadow"),
        "visible_bubbles": _visible_bubbles(metadata, body_text),
    }
    replay_row["state_delta_summary"] = _state_delta_summary(replay_row)
    return _normalise_row(replay_row)


def load_replay_rows_from_store(
    store: Any,
    *,
    thread_key: str,
    limit: int = 20,
    channel: str = "holo_cli",
) -> list[dict[str, Any]]:
    thread = store.find_thread(channel=channel, thread_key=thread_key)
    if not thread:
        return []
    messages = list(reversed(store.recent_thread_messages(int(thread["id"]), max(2, int(limit or 20) * 3))))
    rows: list[dict[str, Any]] = []
    prior_input = ""
    for message in messages:
        direction = str(message.get("direction", "") or "")
        if direction == "inbound":
            prior_input = str(message.get("body_text", "") or "")
            continue
        if direction != "outbound":
            continue
        row = row_from_stored_outbound(message, prior_input=prior_input)
        if any(row.get(key) for key in ("packet_budget", "semantic_novelty", "context_economy", "outcome_appraisal")):
            rows.append(row)
    return rows[-max(1, int(limit or 20)) :]


def _synthetic_row(index: int, *, thread_key: str, duplicate: bool = False, unsupported: bool = False) -> dict[str, Any]:
    novelty_status = "suppressed_duplicate" if duplicate else "passed"
    memory_status = "unsupported_memory_detail" if unsupported else "aligned"
    tool_status = "ungrounded_tool_claim" if unsupported else "grounded"
    row = {
        "turn_id": f"synthetic_{index}_{stable_digest(thread_key, str(index), limit=8)}",
        "time": f"2026-05-24T00:0{index}:00Z",
        "input_summary": [
            "Ask for a grounded memory answer",
            "Ask for a continuation that risks repetition",
            "Ask for tool-backed status without evidence",
        ][min(index, 2)],
        "packet_budget": {
            "schema": "holo.stage143.packet_budget.v1",
            "packet_count": 2,
            "sent_count": 2,
            "skipped_count": 0,
            "continued_count": 1,
            "stop_reason": f"stage142:{novelty_status}" if duplicate else "deep_packet_completed",
            "total_estimated_tokens": 740 + index * 60,
            "total_elapsed_ms": 180 + index * 30,
            "packets": [
                {"packet_id": "packet_0_fast", "packet_type": "fast", "sent": True, "estimated_tokens": 280 + index * 10},
                {"packet_id": "packet_1_deep", "packet_type": "deep", "sent": True, "estimated_tokens": 460 + index * 50},
            ],
        },
        "tool_grounding": {"schema": "holo.tool_grounding.v1", "status": tool_status},
        "memory_grounding": {"schema": "holo.memory_grounding.v1", "status": "grounded"},
        "memory_alignment": {
            "schema": "holo.memory_alignment.v1",
            "status": memory_status,
            "claim_count": 1,
            "aligned_claim_count": 0 if unsupported else 1,
            "unsupported_claim_count": 1 if unsupported else 0,
        },
        "semantic_novelty": {
            "schema": "holo.stage142.semantic_novelty_gate.v1",
            "status": novelty_status,
            "candidate_count": 2,
            "emitted_count": 1 if duplicate else 2,
            "suppressed_count": 1 if duplicate else 0,
            "evaluations": [
                {"bubble_index": 0, "semantic_role": "answer", "novelty_score": 0.7, "should_emit": True},
                {"bubble_index": 1, "semantic_role": "answer", "novelty_score": 0.16 if duplicate else 0.64, "should_emit": not duplicate},
            ],
        },
        "context_economy": {
            "schema": "holo.stage144.context_economy.v1",
            "working_set_slots": [
                {"slot_id": "current:synthetic", "slot_type": "current_user_constraint", "summary": "current user turn", "priority": 0.9},
                {"slot_id": "packet:synthetic", "slot_type": "packet_budget", "summary": "fast and deep packet reported", "priority": 0.7},
            ],
            "context_sufficiency_score": 0.48 if unsupported else 0.78,
            "context_waste_score": 0.72 if duplicate else (0.5 if unsupported else 0.24),
            "recommended_deep_policy": "tool_first" if unsupported else ("skip" if duplicate else "keep"),
            "shadow_only": True,
        },
        "outcome_appraisal": {
            "schema": "holo.stage145.outcome_appraisal.v1",
            "predicted_user_need": "verified_tool_observation" if unsupported else "direct_answer_with_enough_context",
            "prediction_error": 0.7 if unsupported else (0.52 if duplicate else 0.18),
            "observed_stage142_status": novelty_status,
            "observed_grounding_status": tool_status,
            "observed_memory_alignment_status": memory_status,
            "shadow_only": True,
        },
        "reaction_kernel_shadow": {
            "schema": "holo.stage145.reaction_kernel_shadow.v1",
            "kernel_delta_candidates": [
                {"parameter": "novelty_threshold", "delta": 0.06, "applied": False}
            ]
            if duplicate
            else ([{"parameter": "tool_preference", "delta": 0.08, "applied": False}] if unsupported else []),
            "shadow_only": True,
            "applied": False,
        },
        "visible_bubbles": [
            {"index": 0, "text": "Fast reaction with grounded context.", "purpose": "fast_reaction"},
            {
                "index": 1,
                "text": "Deep continuation adds new evidence." if not duplicate else "Fast reaction with grounded context.",
                "purpose": "deep_continuation",
            },
        ],
    }
    row["state_delta_summary"] = _state_delta_summary(row)
    return _normalise_row(row)


def synthetic_replay_rows(thread_key: str = "cli:Stage146Fixture", limit: int = 20) -> list[dict[str, Any]]:
    fixtures = [
        _synthetic_row(0, thread_key=thread_key),
        _synthetic_row(1, thread_key=thread_key, duplicate=True),
        _synthetic_row(2, thread_key=thread_key, unsupported=True),
    ]
    requested = max(1, int(limit or 20))
    if requested <= len(fixtures):
        return fixtures[:requested]
    rows = list(fixtures)
    for index in range(len(fixtures), requested):
        rows.append(_synthetic_row(index % 3, thread_key=f"{thread_key}:{index}", duplicate=index % 5 == 0, unsupported=index % 7 == 0))
    return rows[:requested]


def _replay_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "turn_count": 0,
            "packet_count": 0,
            "sent_packet_count": 0,
            "suppressed_duplicate_count": 0,
            "unsupported_tool_claim_count": 0,
            "unsupported_memory_claim_count": 0,
            "average_prediction_error": 0.0,
            "total_packet_cost_estimate": 0,
        }
    packet_count = sum(_int(_dict(row.get("packet_budget")).get("packet_count"), 0) for row in rows)
    sent_count = sum(_int(_dict(row.get("packet_budget")).get("sent_count"), 0) for row in rows)
    duplicate_count = sum(1 for row in rows if _status(row.get("semantic_novelty")) == "suppressed_duplicate")
    unsupported_tool = sum(1 for row in rows if _status(row.get("tool_grounding")) == "ungrounded_tool_claim")
    unsupported_memory_statuses = {"unsupported_memory_detail", "contradicted_memory_detail", "weakly_aligned"}
    unsupported_memory_grounding = {"ungrounded_memory_claim", "weak_memory_source", "contradicted_memory_claim"}
    unsupported_memory = sum(
        1
        for row in rows
        if _status(row.get("memory_alignment")) in unsupported_memory_statuses
        or _status(row.get("memory_grounding")) in unsupported_memory_grounding
    )
    prediction_errors = [_float(_dict(row.get("outcome_appraisal")).get("prediction_error"), 0.0) for row in rows]
    return {
        "turn_count": len(rows),
        "packet_count": packet_count,
        "sent_packet_count": sent_count,
        "suppressed_duplicate_count": duplicate_count,
        "unsupported_tool_claim_count": unsupported_tool,
        "unsupported_memory_claim_count": unsupported_memory,
        "average_prediction_error": round(statistics.fmean(prediction_errors), 4),
        "total_packet_cost_estimate": sum(_packet_cost(_dict(row.get("packet_budget"))) for row in rows),
    }


def build_biomimetic_replay(
    rows: list[dict[str, Any]],
    *,
    thread_key: str,
    source: str = "runtime_store",
) -> dict[str, Any]:
    normalized_rows = [_normalise_row(row) for row in rows]
    return {
        "schema": STAGE146_REPLAY_SCHEMA,
        "thread_key": str(thread_key or ""),
        "source": str(source or "runtime_store"),
        "generated_at": utc_now(),
        "rows": normalized_rows,
        "summary": _replay_summary(normalized_rows),
    }


def safe_stage146_output_path(output: str | Path, *, repo_root: str | Path | None = None) -> Path:
    root = Path(repo_root or Path.cwd()).resolve()
    candidate = Path(output)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Stage146 output path is outside the public artifact root: {resolved}") from exc
    if resolved.suffix.lower() != ".html":
        resolved = resolved.with_suffix(".html")
    return resolved


def _artifact_paths(output: str | Path, *, repo_root: str | Path | None = None) -> dict[str, Path]:
    html_path = safe_stage146_output_path(output, repo_root=repo_root)
    return {
        "html": html_path,
        "json": html_path.with_suffix(".json"),
        "jsonl": html_path.with_suffix(".jsonl"),
    }


def _render_json_block(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def render_replay_html(payload: dict[str, Any]) -> str:
    rows = _list_dicts(payload.get("rows"))
    summary = _dict(payload.get("summary"))
    items: list[str] = []
    for row in rows:
        bubbles = _list_dicts(row.get("visible_bubbles"))
        bubble_html = "".join(
            f"<li><strong>{html.escape(str(item.get('purpose', '')))}</strong>: {html.escape(str(item.get('text', '')))}</li>"
            for item in bubbles
        )
        kernel_deltas = _list_dicts(_dict(row.get("reaction_kernel_shadow")).get("kernel_delta_candidates"))
        delta_html = ", ".join(
            html.escape(f"{item.get('parameter')} {item.get('delta')}")
            for item in kernel_deltas
        ) or "none"
        items.append(
            "\n".join(
                [
                    "<section class='turn'>",
                    f"<h2>{html.escape(str(row.get('turn_id', 'turn')))}</h2>",
                    f"<p><strong>Input</strong>: {html.escape(str(row.get('input_summary', '')))}</p>",
                    f"<p><strong>Packet Timeline</strong>: stop={html.escape(str(_dict(row.get('packet_budget')).get('stop_reason', '')))}, cost={_packet_cost(_dict(row.get('packet_budget')))}</p>",
                    f"<p><strong>A'/A'' Gating</strong>: {html.escape(str(_status(row.get('semantic_novelty')) or 'unknown'))}</p>",
                    f"<p><strong>Tool/Memory Observations</strong>: tool={html.escape(_status(row.get('tool_grounding')))}, memory={html.escape(_status(row.get('memory_grounding')))}, alignment={html.escape(_status(row.get('memory_alignment')))}</p>",
                    f"<p><strong>Context Slots</strong>: {len(_list_dicts(_dict(row.get('context_economy')).get('working_set_slots')))}</p>",
                    f"<p><strong>Prediction Error</strong>: {html.escape(str(_dict(row.get('outcome_appraisal')).get('prediction_error', '')))}</p>",
                    f"<p><strong>Reaction-Kernel Delta</strong>: {delta_html}</p>",
                    f"<p><strong>State Delta</strong>: {html.escape(str(row.get('state_delta_summary', '')))}</p>",
                    f"<ul>{bubble_html}</ul>",
                    "<details><summary>ledger json</summary>",
                    f"<pre>{_render_json_block(row)}</pre>",
                    "</details>",
                    "</section>",
                ]
            )
        )
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'>",
            "<head>",
            "<meta charset='utf-8'>",
            "<title>Stage146 Biomimetic Replay</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;background:#f7f8fa;color:#15171a}.summary,.turn{background:white;border:1px solid #d8dde6;border-radius:8px;padding:16px;margin:12px 0}pre{white-space:pre-wrap;overflow:auto;background:#111827;color:#f9fafb;padding:12px;border-radius:6px}</style>",
            "</head>",
            "<body>",
            "<h1>Stage146 Biomimetic Replay</h1>",
            f"<p>Thread: {html.escape(str(payload.get('thread_key', '')))} | Source: {html.escape(str(payload.get('source', '')))}</p>",
            "<section class='summary'><h2>Summary</h2>",
            f"<pre>{_render_json_block(summary)}</pre></section>",
            "<h2>Turn Timeline</h2>",
            *items,
            "</body></html>",
        ]
    )


def write_replay_artifacts(
    payload: dict[str, Any],
    *,
    output: str | Path,
    repo_root: str | Path | None = None,
) -> dict[str, str]:
    paths = _artifact_paths(output, repo_root=repo_root)
    atomic_write_text(paths["html"], render_replay_html(payload))
    atomic_write_text(paths["json"], json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    jsonl = "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(payload.get("rows"))) + "\n"
    atomic_write_text(paths["jsonl"], jsonl)
    return {key: str(value) for key, value in paths.items()}


def export_biomimetic_replay(
    *,
    thread_key: str,
    limit: int = 20,
    output: str | Path = "artifacts/stage146/stage146_replay.html",
    dry_run: bool = False,
    store: Any | None = None,
    channel: str = "holo_cli",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    source = "synthetic_fixture"
    rows: list[dict[str, Any]] = []
    if not dry_run and store is not None:
        rows = load_replay_rows_from_store(store, thread_key=thread_key, limit=limit, channel=channel)
        source = "runtime_store" if rows else "synthetic_fixture:no_runtime_rows"
    if not rows:
        rows = synthetic_replay_rows(thread_key, limit=limit)
    payload = build_biomimetic_replay(rows, thread_key=thread_key, source=source)
    paths = write_replay_artifacts(payload, output=output, repo_root=repo_root)
    return {
        "schema": STAGE146_REPLAY_SCHEMA,
        "thread_key": thread_key,
        "dry_run": bool(dry_run),
        "source": source,
        "row_count": len(payload["rows"]),
        "paths": paths,
        "summary": payload["summary"],
    }
