from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import atomic_write_text, compact_text, utc_now
from .stage146_biomimetic_replay import (
    _dict,
    _float,
    _list_dicts,
    _status,
    safe_stage146_output_path,
    synthetic_replay_rows,
)

STAGE147_SCHEMA = "holo.stage147.replay_calibration.v1"

MEMORY_FAILURE_STATUSES = {"unsupported_memory_detail", "contradicted_memory_detail"}
TOOL_FAILURE_STATUSES = {"ungrounded_tool_claim"}
DUPLICATE_STATUSES = {"suppressed_duplicate"}
NOVELTY_DELTA_PARAMETERS = {"novelty_threshold", "continuation_threshold"}
MEMORY_DELTA_PARAMETERS = {"memory_trust", "correction_sensitivity"}


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value or 0.0))), 4)


def _stage144_recommendation(row: dict[str, Any]) -> str:
    return str(_dict(row.get("context_economy")).get("recommended_deep_policy", "") or "").strip()


def _context_waste(row: dict[str, Any]) -> float:
    return _float(_dict(row.get("context_economy")).get("context_waste_score"), 0.0)


def _delta_parameters(row: dict[str, Any]) -> list[str]:
    kernel = _dict(row.get("reaction_kernel_shadow"))
    return [
        str(item.get("parameter", "") or "").strip()
        for item in _list_dicts(kernel.get("kernel_delta_candidates"))
        if str(item.get("parameter", "") or "").strip()
    ]


def _policy_support(row: dict[str, Any], recommendation: str) -> tuple[str, str, str]:
    novelty_status = _status(row.get("semantic_novelty"))
    memory_alignment_status = _status(row.get("memory_alignment"))
    tool_status = _status(row.get("tool_grounding"))
    waste = _context_waste(row)

    if recommendation == "skip":
        if novelty_status in DUPLICATE_STATUSES or waste >= 0.65:
            return "supported", "duplicate_or_high_waste", "Stage142 suppressed duplicate or Stage144 waste was high."
        if novelty_status == "passed" and waste <= 0.35:
            return "unsupported", "clean_low_waste", "A clean low-waste turn does not support skipping deep packets."
        return "inconclusive", "weak_skip_signal", "Skip recommendation lacks a clear duplicate or waste outcome."
    if recommendation == "memory_first":
        if memory_alignment_status in MEMORY_FAILURE_STATUSES:
            return "supported", "memory_alignment_failed", "Memory alignment failed, supporting memory-first retrieval."
        if memory_alignment_status == "aligned":
            return "unsupported", "memory_already_aligned", "Memory was already aligned, so memory-first is not supported by this row."
        return "inconclusive", "memory_signal_missing", "Memory evidence is not strong enough to judge memory-first."
    if recommendation == "tool_first":
        if tool_status in TOOL_FAILURE_STATUSES:
            return "supported", "tool_claim_ungrounded", "Tool grounding failed, supporting tool-first observation."
        if tool_status == "grounded":
            return "unsupported", "tool_already_grounded", "Tool evidence was already grounded, so tool-first is not supported by this row."
        return "inconclusive", "tool_signal_missing", "Tool evidence is not strong enough to judge tool-first."
    if recommendation in {"keep", "defer", ""}:
        return "inconclusive", "no_calibration_trigger", "No explicit Stage147 packet-policy calibration trigger fired."
    return "inconclusive", "unknown_policy", f"Unknown recommendation `{recommendation}` has no deterministic support rule."


def _delta_support(row: dict[str, Any], parameter: str) -> tuple[str, str]:
    novelty_status = _status(row.get("semantic_novelty"))
    memory_alignment_status = _status(row.get("memory_alignment"))
    tool_status = _status(row.get("tool_grounding"))

    if parameter in NOVELTY_DELTA_PARAMETERS:
        if novelty_status in DUPLICATE_STATUSES:
            return "supported", "Duplicate suppression supports raising novelty or continuation thresholds."
        if novelty_status == "passed" and memory_alignment_status == "aligned" and tool_status == "grounded":
            return "unsupported", "Clean grounded turn is a counterexample for novelty or continuation threshold changes."
        return "inconclusive", "No duplicate suppression outcome supports this novelty-related delta."
    if parameter in MEMORY_DELTA_PARAMETERS:
        if memory_alignment_status in MEMORY_FAILURE_STATUSES:
            return "supported", "Memory alignment failure supports changing memory trust or correction sensitivity."
        if memory_alignment_status == "aligned" and tool_status == "grounded":
            return "unsupported", "Clean aligned memory is a counterexample for memory-trust related changes."
        return "inconclusive", "No memory failure outcome supports this memory-related delta."
    if tool_status == "ungrounded_tool_claim" and parameter in {"tool_preference", "risk_aversion"}:
        return "supported", "Ungrounded tool claim supports tool preference or risk-aversion changes."
    if novelty_status == "passed" and memory_alignment_status == "aligned" and tool_status == "grounded":
        return "unsupported", "Clean grounded turn produced a delta, so it is a counterexample."
    return "inconclusive", "No Stage147 support rule matched this delta parameter."


def _finding(row: dict[str, Any]) -> dict[str, Any]:
    recommendation = _stage144_recommendation(row)
    policy_status, observed_issue, policy_reason = _policy_support(row, recommendation)
    delta_parameters = _delta_parameters(row)
    delta_statuses = [_delta_support(row, parameter)[0] for parameter in delta_parameters]
    support_status = policy_status
    if support_status == "inconclusive" and "supported" in delta_statuses:
        support_status = "supported"
    elif support_status == "inconclusive" and "unsupported" in delta_statuses:
        support_status = "unsupported"

    delta_reasons = [
        f"{parameter}: {_delta_support(row, parameter)[1]}"
        for parameter in delta_parameters
    ]
    return {
        "turn_id": str(row.get("turn_id", "") or ""),
        "observed_issue": observed_issue,
        "stage144_recommendation": recommendation,
        "stage145_delta_parameters": delta_parameters,
        "later_or_fixture_outcome": compact_text(
            "; ".join(
                part
                for part in [
                    f"stage142={_status(row.get('semantic_novelty')) or 'unknown'}",
                    f"tool={_status(row.get('tool_grounding')) or 'unknown'}",
                    f"memory_alignment={_status(row.get('memory_alignment')) or 'unknown'}",
                    f"waste={_context_waste(row):.2f}",
                ]
                if part
            ),
            300,
        ),
        "support_status": support_status,
        "reason": compact_text("; ".join([policy_reason, *delta_reasons]), 420),
    }


def _record_candidate(
    candidates: dict[str, dict[str, Any]],
    *,
    target: str,
    candidate_type: str,
    recommended_change: str,
    support_status: str,
) -> None:
    if support_status not in {"supported", "unsupported"}:
        return
    item = candidates.setdefault(
        target,
        {
            "target": target,
            "candidate_type": candidate_type,
            "recommended_change": recommended_change,
            "support_count": 0,
            "counterexample_count": 0,
            "confidence": 0.0,
            "shadow_only": True,
        },
    )
    if support_status == "supported":
        item["support_count"] = int(item.get("support_count", 0)) + 1
    else:
        item["counterexample_count"] = int(item.get("counterexample_count", 0)) + 1


def _promotion_candidates(rows: list[dict[str, Any]], findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    by_turn = {str(finding.get("turn_id", "")): finding for finding in findings}
    for row in rows:
        turn_id = str(row.get("turn_id", "") or "")
        finding = _dict(by_turn.get(turn_id))
        recommendation = _stage144_recommendation(row)
        if recommendation in {"skip", "memory_first", "tool_first"}:
            _record_candidate(
                candidates,
                target=f"packet_policy:{recommendation}",
                candidate_type="packet_policy",
                recommended_change=f"prefer `{recommendation}` under matching replay conditions",
                support_status=str(finding.get("support_status", "inconclusive")),
            )
        for parameter in _delta_parameters(row):
            support_status, _ = _delta_support(row, parameter)
            _record_candidate(
                candidates,
                target=f"reaction_kernel_parameter:{parameter}",
                candidate_type="reaction_kernel_parameter",
                recommended_change=f"consider shadow adjustment to `{parameter}` when replay support recurs",
                support_status=support_status,
            )
    kept: list[dict[str, Any]] = []
    for item in candidates.values():
        support = int(item.get("support_count", 0))
        counter = int(item.get("counterexample_count", 0))
        if support <= 0 or support <= counter:
            continue
        item["confidence"] = _clamp(support / max(1, support + counter))
        item["shadow_only"] = True
        kept.append(item)
    return sorted(kept, key=lambda item: (int(item.get("support_count", 0)), float(item.get("confidence", 0.0))), reverse=True)


def build_stage147_replay_calibration(rows: list[dict[str, Any]]) -> dict[str, Any]:
    normalized_rows = [dict(row) for row in rows if isinstance(row, dict)]
    findings = [_finding(row) for row in normalized_rows]
    policy_judged = [
        finding
        for finding in findings
        if str(finding.get("stage144_recommendation", "")) in {"skip", "memory_first", "tool_first"}
        and str(finding.get("support_status", "")) in {"supported", "unsupported"}
    ]
    policy_supported = [finding for finding in policy_judged if finding.get("support_status") == "supported"]
    delta_judgments: list[str] = []
    for row in normalized_rows:
        for parameter in _delta_parameters(row):
            status, _ = _delta_support(row, parameter)
            if status in {"supported", "unsupported"}:
                delta_judgments.append(status)
    delta_supported = [status for status in delta_judgments if status == "supported"]
    return {
        "schema": STAGE147_SCHEMA,
        "row_count": len(normalized_rows),
        "policy_recommendation_accuracy": _clamp(len(policy_supported) / max(1, len(policy_judged))) if policy_judged else 0.0,
        "kernel_delta_support_rate": _clamp(len(delta_supported) / max(1, len(delta_judgments))) if delta_judgments else 0.0,
        "calibration_findings": findings,
        "promotion_candidates": _promotion_candidates(normalized_rows, findings),
        "do_not_apply_live": True,
        "generated_at": utc_now(),
    }


def _load_rows_from_replay_json(replay_json: str | Path | None) -> list[dict[str, Any]]:
    if not replay_json:
        return []
    path = Path(replay_json)
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows", []) if isinstance(payload, dict) else []
    return _list_dicts(rows)


def _artifact_paths(output: str | Path, *, repo_root: str | Path | None = None) -> dict[str, Path]:
    html_path = safe_stage146_output_path(output, repo_root=repo_root)
    return {
        "html": html_path,
        "json": html_path.with_suffix(".json"),
        "jsonl": html_path.with_suffix(".jsonl"),
    }


def _render_json(value: Any) -> str:
    return html.escape(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def render_stage147_calibration_html(report: dict[str, Any]) -> str:
    findings = _list_dicts(report.get("calibration_findings"))
    candidates = _list_dicts(report.get("promotion_candidates"))
    supported = [finding for finding in findings if finding.get("support_status") == "supported"]
    counterexamples = [finding for finding in findings if finding.get("support_status") == "unsupported"]
    finding_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('turn_id', '')))}</td>"
        f"<td>{html.escape(str(item.get('support_status', '')))}</td>"
        f"<td>{html.escape(str(item.get('stage144_recommendation', '')))}</td>"
        f"<td>{html.escape(', '.join(str(p) for p in item.get('stage145_delta_parameters', [])))}</td>"
        f"<td>{html.escape(str(item.get('reason', '')))}</td>"
        "</tr>"
        for item in findings
    )
    candidate_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(item.get('target', '')))}</td>"
        f"<td>{html.escape(str(item.get('candidate_type', '')))}</td>"
        f"<td>{html.escape(str(item.get('recommended_change', '')))}</td>"
        f"<td>{html.escape(str(item.get('support_count', '')))}</td>"
        f"<td>{html.escape(str(item.get('counterexample_count', '')))}</td>"
        f"<td>{html.escape(str(item.get('confidence', '')))}</td>"
        "</tr>"
        for item in candidates
    )
    return "\n".join(
        [
            "<!doctype html>",
            "<html lang='en'><head><meta charset='utf-8'>",
            "<title>Stage147 Replay-Driven Calibration</title>",
            "<style>body{font-family:Arial,sans-serif;margin:32px;background:#f7f8fa;color:#15171a}.warning,.summary,section{background:white;border:1px solid #d8dde6;border-radius:8px;padding:16px;margin:12px 0}.warning{border-color:#b91c1c}table{border-collapse:collapse;background:white;width:100%}td,th{border:1px solid #d8dde6;padding:8px;text-align:left;vertical-align:top}pre{white-space:pre-wrap;background:#111827;color:#f9fafb;padding:12px;border-radius:6px}</style>",
            "</head><body>",
            "<h1>Stage147 Replay-Driven Calibration</h1>",
            "<section class='warning'><strong>Shadow-only warning:</strong> this report does not apply live policy, mutate memory, call providers, execute tools, or start transport.</section>",
            "<section class='summary'><h2>Summary Metrics</h2>",
            f"<pre>{_render_json({key: report.get(key) for key in ('row_count', 'policy_recommendation_accuracy', 'kernel_delta_support_rate', 'do_not_apply_live')})}</pre>",
            "</section>",
            f"<section><h2>Supported Findings ({len(supported)})</h2><p>Supported replay rows are included in the full findings table.</p></section>",
            f"<section><h2>Counterexamples ({len(counterexamples)})</h2><p>Unsupported replay rows are included in the full findings table.</p></section>",
            "<section><h2>Promotion Candidates</h2>",
            f"<table><thead><tr><th>target</th><th>type</th><th>recommended change</th><th>support</th><th>counterexamples</th><th>confidence</th></tr></thead><tbody>{candidate_rows}</tbody></table>",
            "</section>",
            "<section><h2>Calibration Findings</h2>",
            f"<table><thead><tr><th>turn</th><th>support</th><th>Stage144</th><th>Stage145 deltas</th><th>reason</th></tr></thead><tbody>{finding_rows}</tbody></table>",
            "</section>",
            "<section><h2>Raw Report</h2>",
            f"<pre>{_render_json(report)}</pre>",
            "</section>",
            "</body></html>",
        ]
    )


def write_stage147_calibration_artifacts(
    report: dict[str, Any],
    *,
    output: str | Path,
    repo_root: str | Path | None = None,
) -> dict[str, str]:
    paths = _artifact_paths(output, repo_root=repo_root)
    atomic_write_text(paths["html"], render_stage147_calibration_html(report))
    atomic_write_text(paths["json"], json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    jsonl = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in _list_dicts(report.get("calibration_findings"))) + "\n"
    atomic_write_text(paths["jsonl"], jsonl)
    return {key: str(value) for key, value in paths.items()}


def evaluate_replay_calibration(
    *,
    replay_json: str | Path | None = None,
    output: str | Path = "artifacts/stage147/stage147_calibration.html",
    dry_run: bool = False,
    repo_root: str | Path | None = None,
    synthetic_thread_key: str = "cli:Stage146Fixture",
    synthetic_limit: int = 20,
) -> dict[str, Any]:
    rows = [] if dry_run else _load_rows_from_replay_json(replay_json)
    source = "replay_json" if rows else "synthetic_stage146_rows"
    if not rows:
        rows = synthetic_replay_rows(synthetic_thread_key, limit=synthetic_limit)
    report = build_stage147_replay_calibration(rows)
    report["source"] = source
    paths = write_stage147_calibration_artifacts(report, output=output, repo_root=repo_root)
    return {
        "schema": STAGE147_SCHEMA,
        "row_count": int(report.get("row_count", 0)),
        "policy_recommendation_accuracy": report.get("policy_recommendation_accuracy", 0.0),
        "kernel_delta_support_rate": report.get("kernel_delta_support_rate", 0.0),
        "promotion_candidate_count": len(_list_dicts(report.get("promotion_candidates"))),
        "do_not_apply_live": True,
        "source": source,
        "paths": paths,
    }
