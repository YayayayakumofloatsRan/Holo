from __future__ import annotations

import html
import json
import statistics
from pathlib import Path
from typing import Any

from .common import atomic_write_text, utc_now
from .stage146_biomimetic_replay import (
    _dict,
    _float,
    _int,
    _list_dicts,
    _packet_cost,
    _status,
    safe_stage146_output_path,
    synthetic_replay_rows,
)

STAGE146_BENCHMARK_SCHEMA = "holo.stage146.benchmark_bundle.v1"

BENCHMARK_LABELS = (
    "single-call baseline",
    "simple RAG baseline",
    "fixed two-bubble baseline",
    "multi-packet without Stage142/143/144/145",
    "full current RK-CSM stack",
)


def _metric_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(statistics.fmean(values), 4)


def _condition_rows(label: str) -> list[dict[str, Any]]:
    rows = synthetic_replay_rows(f"benchmark:{label}", limit=6)
    if label == "single-call baseline":
        for row in rows:
            row["packet_budget"] = {"packet_count": 1, "sent_count": 1, "total_estimated_tokens": 520, "stop_reason": "single_call_done"}
            row["semantic_novelty"] = {"status": "baseline_no_gate", "candidate_count": 1, "suppressed_count": 0}
            row["context_economy"] = {"context_waste_score": 0.34, "context_sufficiency_score": 0.48}
            row["outcome_appraisal"] = {"prediction_error": 0.46}
    elif label == "simple RAG baseline":
        for index, row in enumerate(rows):
            row["memory_alignment"] = {"status": "aligned" if index % 2 == 0 else "weakly_aligned"}
            row["semantic_novelty"] = {"status": "baseline_no_gate", "candidate_count": 1, "suppressed_count": 0}
            row["context_economy"] = {"context_waste_score": 0.42, "context_sufficiency_score": 0.6}
            row["outcome_appraisal"] = {"prediction_error": 0.38}
    elif label == "fixed two-bubble baseline":
        for index, row in enumerate(rows):
            row["semantic_novelty"] = {
                "status": "suppressed_duplicate" if index % 2 == 0 else "passed",
                "candidate_count": 2,
                "emitted_count": 2,
                "suppressed_count": 1 if index % 2 == 0 else 0,
                "evaluations": [
                    {"novelty_score": 0.62, "should_emit": True},
                    {"novelty_score": 0.14 if index % 2 == 0 else 0.48, "should_emit": True},
                ],
            }
            row["context_economy"] = {"context_waste_score": 0.68 if index % 2 == 0 else 0.46, "context_sufficiency_score": 0.55}
            row["outcome_appraisal"] = {"prediction_error": 0.5 if index % 2 == 0 else 0.34}
    elif label == "multi-packet without Stage142/143/144/145":
        for index, row in enumerate(rows):
            row["stage143_packet_budget"] = {}
            row["semantic_novelty"] = {"status": "missing_gate", "candidate_count": 2, "suppressed_count": 0}
            row["context_economy"] = {}
            row["outcome_appraisal"] = {"prediction_error": 0.44}
            if index == 1:
                row["tool_grounding"] = {"status": "ungrounded_tool_claim"}
    else:
        rows = synthetic_replay_rows("benchmark:full_current", limit=6)
        for index, row in enumerate(rows):
            if index == 1:
                row["semantic_novelty"]["status"] = "suppressed_duplicate"
                row["semantic_novelty"]["suppressed_count"] = 1
                row["context_economy"]["context_waste_score"] = 0.62
            elif index == 2:
                row["tool_grounding"]["status"] = "grounded"
                row["memory_alignment"]["status"] = "aligned"
                row["context_economy"]["context_waste_score"] = 0.28
                row["outcome_appraisal"]["prediction_error"] = 0.22
    return rows


def _novelty_score(row: dict[str, Any]) -> float:
    novelty = _dict(row.get("semantic_novelty"))
    scores = [
        _float(item.get("novelty_score"), 0.0)
        for item in _list_dicts(novelty.get("evaluations"))
        if item.get("novelty_score") is not None
    ]
    if scores:
        return _metric_mean(scores)
    status = _status(novelty)
    if status == "passed":
        return 0.64
    if status == "suppressed_duplicate":
        return 0.22
    return 0.42


def compute_benchmark_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = max(1, len(rows))
    duplicate_count = sum(1 for row in rows if _status(row.get("semantic_novelty")) == "suppressed_duplicate")
    unsupported_count = sum(
        1
        for row in rows
        if _status(row.get("tool_grounding")) == "ungrounded_tool_claim"
        or _status(row.get("memory_alignment")) in {"unsupported_memory_detail", "contradicted_memory_detail"}
        or _status(row.get("memory_grounding")) in {"ungrounded_memory_claim", "contradicted_memory_claim", "weak_memory_source"}
    )
    aligned_count = sum(1 for row in rows if _status(row.get("memory_alignment")) == "aligned")
    prediction_errors = [_float(_dict(row.get("outcome_appraisal")).get("prediction_error"), 0.0) for row in rows]
    context_waste = [_float(_dict(row.get("context_economy")).get("context_waste_score"), 0.0) for row in rows]
    packet_cost = sum(_packet_cost(_dict(row.get("packet_budget"))) for row in rows)
    correction_adoption = 1.0 - _metric_mean(prediction_errors)
    return {
        "semantic_novelty": _metric_mean([_novelty_score(row) for row in rows]),
        "duplicate_rate": round(duplicate_count / total, 4),
        "unsupported_claim_rate": round(unsupported_count / total, 4),
        "memory_alignment_support_rate": round(aligned_count / total, 4),
        "context_waste": _metric_mean(context_waste),
        "packet_cost_estimate": packet_cost,
        "prediction_error": _metric_mean(prediction_errors),
        "correction_adoption_proxy": round(max(0.0, min(1.0, correction_adoption)), 4),
    }


def build_biomimetic_benchmark_bundle(*, source: str = "deterministic_fixture") -> dict[str, Any]:
    conditions: list[dict[str, Any]] = []
    for label in BENCHMARK_LABELS:
        rows = _condition_rows(label)
        conditions.append(
            {
                "label": label,
                "row_count": len(rows),
                "metrics": compute_benchmark_metrics(rows),
                "sample_rows": rows[:3],
            }
        )
    return {
        "schema": STAGE146_BENCHMARK_SCHEMA,
        "source": source,
        "generated_at": utc_now(),
        "conditions": conditions,
        "metric_definitions": {
            "semantic_novelty": "Average deterministic novelty proxy from Stage142 evaluations or fixture status.",
            "duplicate_rate": "Share of turns where duplicate continuation would be or was suppressed.",
            "unsupported_claim_rate": "Share of turns with ungrounded tool or unsupported memory claim reports.",
            "memory_alignment_support_rate": "Share of turns with aligned memory detail support.",
            "context_waste": "Average Stage144 context waste score.",
            "packet_cost_estimate": "Sum of estimated packet tokens.",
            "prediction_error": "Average Stage145 prediction-error proxy.",
            "correction_adoption_proxy": "Bounded inverse prediction-error proxy.",
        },
    }


def render_benchmark_html(payload: dict[str, Any]) -> str:
    rows: list[str] = []
    for condition in _list_dicts(payload.get("conditions")):
        metrics = _dict(condition.get("metrics"))
        metric_cells = "".join(f"<td>{html.escape(str(metrics.get(key, '')))}</td>" for key in metrics)
        rows.append(
            f"<tr><th>{html.escape(str(condition.get('label', '')))}</th>"
            f"<td>{condition.get('row_count', 0)}</td>{metric_cells}</tr>"
        )
    metric_keys = list(_dict(_list_dicts(payload.get("conditions"))[0].get("metrics")).keys()) if _list_dicts(payload.get("conditions")) else []
    header = "".join(f"<th>{html.escape(key)}</th>" for key in metric_keys)
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'><head><meta charset='utf-8'>",
            "<title>Stage146 Biomimetic Benchmark Bundle</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;background:#f7f8fa;color:#15171a}table{border-collapse:collapse;background:white}td,th{border:1px solid #d8dde6;padding:8px;text-align:left}pre{white-space:pre-wrap;background:#111827;color:#f9fafb;padding:12px;border-radius:6px}</style>",
            "</head><body>",
            "<h1>Stage146 Biomimetic Benchmark Bundle</h1>",
            "<p>Deterministic fixture comparison of packet/gate conditions.</p>",
            f"<table><thead><tr><th>condition</th><th>rows</th>{header}</tr></thead><tbody>{''.join(rows)}</tbody></table>",
            "<h2>Metric Definitions</h2>",
            f"<pre>{html.escape(json.dumps(payload.get('metric_definitions', {}), ensure_ascii=False, sort_keys=True, indent=2))}</pre>",
            "</body></html>",
        ]
    )


def _artifact_paths(output: str | Path, *, repo_root: str | Path | None = None) -> dict[str, Path]:
    html_path = safe_stage146_output_path(output, repo_root=repo_root)
    return {
        "html": html_path,
        "json": html_path.with_suffix(".json"),
        "jsonl": html_path.with_suffix(".jsonl"),
    }


def write_benchmark_artifacts(
    payload: dict[str, Any],
    *,
    output: str | Path,
    repo_root: str | Path | None = None,
) -> dict[str, str]:
    paths = _artifact_paths(output, repo_root=repo_root)
    atomic_write_text(paths["html"], render_benchmark_html(payload))
    atomic_write_text(paths["json"], json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2))
    jsonl = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in _list_dicts(payload.get("conditions"))) + "\n"
    atomic_write_text(paths["jsonl"], jsonl)
    return {key: str(value) for key, value in paths.items()}


def run_biomimetic_benchmark(
    *,
    output: str | Path = "artifacts/stage146/stage146_benchmark.html",
    dry_run: bool = False,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = build_biomimetic_benchmark_bundle(source="deterministic_fixture:dry_run" if dry_run else "deterministic_fixture")
    paths = write_benchmark_artifacts(payload, output=output, repo_root=repo_root)
    return {
        "schema": STAGE146_BENCHMARK_SCHEMA,
        "dry_run": bool(dry_run),
        "condition_count": len(payload["conditions"]),
        "paths": paths,
        "conditions": [
            {"label": item["label"], "metrics": item["metrics"]}
            for item in _list_dicts(payload.get("conditions"))
        ],
    }
