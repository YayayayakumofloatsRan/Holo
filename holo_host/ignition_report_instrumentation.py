from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    _as_dict,
    _clamp01,
    _compact_for_html,
    _esc,
    _gate_table,
    _load_plotting_stack,
    _metric as _html_metric,
    _num,
    _plot_label,
)


STAGE85_NAME = "stage85-ignition-report-instrumentation"

STAGE85_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "source_trace_only": True,
    "runtime_mutation_allowed": False,
    "provider_call_allowed": False,
    "schema_repair_only": True,
}


def load_ignition_report_instrumentation_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_ignition_report_instrumentation(
    stream_lattice_report: dict[str, Any],
    trace_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    stream = dict(stream_lattice_report or {})
    traces = [dict(item) for item in list(trace_reports or []) if isinstance(item, dict)]
    turn_reports = _turn_reports(traces)
    cell_reports = [_cell_report(trace, index) for index, trace in enumerate(traces)]
    summary = _instrumentation_summary(stream, traces, turn_reports, cell_reports)
    invalidators = _invalidators(stream, traces, turn_reports)
    decision = _hypothesis_decision(summary, invalidators)
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE85_NAME,
        "source_stage": str(stream.get("stage", "")),
        "instrumentation_summary": summary,
        "cell_reports": cell_reports,
        "turn_evidence_sample": turn_reports[:120],
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(summary, decision),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "real_provider_trace": bool(summary.get("all_trace_reports_real_provider", False)),
            "stream_lattice_precondition_supported": bool(
                summary.get("stage84_stream_lattice_precondition_supported", False)
            ),
            "gnw_language_bounded": True,
            "gnw_remains_partial_until_focused_cell_replication": bool(
                summary.get("current_trace_instrumentation_gap", False)
                or _num(summary.get("observed_ignition_report_transfer"), 0.0) < 0.5
            ),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_subjective_report": True,
            "causal_language_bounded": True,
            "reason": "stage85_repaired_trace_schema_for_structured_ignition_report_observation",
        },
        "boundary": dict(STAGE85_BOUNDARY),
    }


def write_ignition_report_instrumentation_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_ignition_report_instrumentation_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_ignition_report.png")
    _write_ignition_report_png(report, png_path)
    return {"html": html_path, "json": json_path, "ignition_report_png": png_path}


def render_ignition_report_instrumentation_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    summary = _as_dict(payload.get("instrumentation_summary", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage85 Ignition Report Instrumentation</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid #d7dddc; background: #f7f8f5; border-radius: 6px; padding: 10px 12px; }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d7dddc; margin: 10px 0; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid #d7dddc; text-align: left; font-size: 12px; vertical-align: top; }}
    pre {{ overflow: auto; background: #172026; color: #e8f0ec; padding: 14px; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
    .warn {{ color: #8a4f00; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>Stage85 Ignition Report Instrumentation</h1>
    <p class="note">Schema-level GNW observability repair. It separates legacy trace-field gaps from bounded ignition-to-report transfer in traces that expose Stage77 structured flow fields.</p>
  </header>
  <main>
    <section class="summary">
      {_html_metric("Decision", decision.get("decision", ""))}
      {_html_metric("Turns", summary.get("total_turn_count", 0))}
      {_html_metric("Structured Ignition", summary.get("structured_ignition_turn_count", 0))}
      {_html_metric("Structured Coupling", summary.get("structured_coupling_turn_count", 0))}
      {_html_metric("Observed Transfer", summary.get("observed_ignition_report_transfer", 0))}
      {_html_metric("Trace Gap", summary.get("current_trace_instrumentation_gap", False))}
    </section>
    <section>
      <h2>Cell Reports</h2>
      {_cell_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">do_not_claim_real_consciousness={_esc(evidence.get("do_not_claim_real_consciousness", True))}</p>
      {_gate_table(evidence)}
    </section>
    <section>
      <h2>Compact JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _turn_reports(traces: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    global_index = 0
    for trace_index, trace in enumerate(traces):
        cell_label = _cell_label(trace, trace_index)
        runs = [dict(run) for run in list(trace.get("stage46_compatible_runs", []) or []) if isinstance(run, dict)]
        for run_index, run in enumerate(runs):
            for turn_index, turn in enumerate(list(run.get("turns", []) or [])):
                if not isinstance(turn, dict):
                    continue
                reports.append(
                    _turn_report(
                        dict(turn),
                        cell_label=cell_label,
                        run_id=str(run.get("run_id", f"run_{run_index + 1}") or ""),
                        turn_index=turn_index,
                        global_index=global_index,
                    )
                )
                global_index += 1
    return reports


def _turn_report(
    turn: dict[str, Any],
    *,
    cell_label: str,
    run_id: str,
    turn_index: int,
    global_index: int,
) -> dict[str, Any]:
    debug = _as_dict(turn.get("processor_debug", {}))
    lifecycle = _as_dict(debug.get("bionic_memory_lifecycle", {}))
    flow = _as_dict(debug.get("bionic_consciousness_flow", {}))
    ignition_state = _as_dict(flow.get("global_workspace_ignition", {}))
    coupling_state = _as_dict(flow.get("ignition_to_reply_coupling", {}))
    selected_action = _as_dict(turn.get("selected_action", {}))
    structured_ignition = bool(ignition_state)
    structured_coupling = bool(coupling_state)
    ignition = _clamp01(_num(ignition_state.get("score"), 0.0)) if structured_ignition else 0.0
    coupling = _clamp01(_num(coupling_state.get("coupling_strength"), 0.0)) if structured_coupling else 0.0
    action_score = _clamp01(_num(selected_action.get("score"), 0.0))
    ignited = structured_ignition and ignition >= 0.65
    reportable = ignited and structured_coupling and coupling >= 0.5 and action_score >= 0.5
    return {
        "index": global_index,
        "cell_label": cell_label,
        "run_id": run_id,
        "turn_index_in_run": turn_index,
        "turn_id": str(turn.get("turn_id", "") or f"turn_{turn_index + 1}"),
        "structured_ignition": structured_ignition,
        "structured_coupling": structured_coupling,
        "ignition": round(ignition, 6),
        "reply_coupling_strength": round(coupling, 6),
        "action_score": round(action_score, 6),
        "ignited": bool(ignited),
        "reportable": bool(reportable),
        "reply_target": str(coupling_state.get("reply_target", "") or ""),
        "dominant_phase": str(flow.get("dominant_phase", "") or ""),
        "self_memory_write": bool(lifecycle.get("self_memory_write", False)),
    }


def _cell_report(trace: dict[str, Any], index: int) -> dict[str, Any]:
    label = _cell_label(trace, index)
    turns = [item for item in _turn_reports([trace]) if str(item.get("cell_label", "")) == label]
    return {
        "cell_label": label,
        "source_stage": str(trace.get("stage", "")),
        "real_provider_trace": _report_real_provider_trace(trace),
        "turn_count": len(turns),
        "structured_ignition_turn_count": sum(1 for item in turns if bool(item.get("structured_ignition", False))),
        "structured_coupling_turn_count": sum(1 for item in turns if bool(item.get("structured_coupling", False))),
        "ignited_turn_count": sum(1 for item in turns if bool(item.get("ignited", False))),
        "reportable_turn_count": sum(1 for item in turns if bool(item.get("reportable", False))),
        "ignition_report_transfer": _ignition_report_transfer(turns),
    }


def _instrumentation_summary(
    stream: dict[str, Any],
    traces: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    cell_reports: list[dict[str, Any]],
) -> dict[str, Any]:
    stream_summary = _as_dict(stream.get("stream_summary", {}))
    structured_ignition = sum(1 for item in turns if bool(item.get("structured_ignition", False)))
    structured_coupling = sum(1 for item in turns if bool(item.get("structured_coupling", False)))
    total_turns = len(turns)
    observed_transfer = _ignition_report_transfer(turns)
    current_gap = total_turns > 0 and (
        structured_ignition < total_turns or structured_coupling < total_turns
    )
    stage84_transfer = _num(stream_summary.get("ignition_report_transfer"), 0.0)
    return {
        "stage84_stream_lattice_precondition_supported": _stage84_supported(stream),
        "trace_count": len(traces),
        "real_provider_cell_count": sum(1 for item in cell_reports if bool(item.get("real_provider_trace", False))),
        "all_trace_reports_real_provider": bool(cell_reports)
        and all(bool(item.get("real_provider_trace", False)) for item in cell_reports),
        "total_turn_count": total_turns,
        "structured_ignition_turn_count": structured_ignition,
        "structured_coupling_turn_count": structured_coupling,
        "structured_ignition_ratio": round(structured_ignition / total_turns, 6) if total_turns else 0.0,
        "structured_coupling_ratio": round(structured_coupling / total_turns, 6) if total_turns else 0.0,
        "ignited_turn_count": sum(1 for item in turns if bool(item.get("ignited", False))),
        "reportable_turn_count": sum(1 for item in turns if bool(item.get("reportable", False))),
        "observed_ignition_report_transfer": round(observed_transfer, 6),
        "stage84_legacy_ignition_report_transfer": round(stage84_transfer, 6),
        "transfer_delta_vs_stage84": round(observed_transfer - stage84_transfer, 6),
        "current_trace_instrumentation_gap": bool(current_gap),
        "trace_export_schema_status": "legacy_traces_missing_stage77_flow_fields"
        if current_gap
        else "structured_stage77_flow_fields_observable",
        "focused_provider_cell_required": bool(current_gap or observed_transfer < 0.5),
        "mechanism_change": "preserve_global_workspace_ignition_and_ignition_to_reply_coupling_in_stage46_stage59_trace_debug",
        "bounded_publication_scope": "GNW ignition-to-report observability proxy over structured Stage77 flow fields",
    }


def _invalidators(
    stream: dict[str, Any],
    traces: list[dict[str, Any]],
    turns: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    if not _stage84_supported(stream):
        invalidators.append({"key": "stage84_stream_lattice_precondition_not_supported", "severity": "p0"})
    if not traces:
        invalidators.append({"key": "missing_stage59_or_stage60_trace", "severity": "p0"})
    for index, trace in enumerate(traces):
        if not _report_real_provider_trace(trace):
            invalidators.append(
                {
                    "key": "ignition_report_instrumentation_requires_real_provider_trace",
                    "severity": "p0",
                    "cell": _cell_label(trace, index),
                }
            )
        boundary = _as_dict(trace.get("boundary", {}))
        for key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(key, False)):
                invalidators.append({"key": f"trace_source_{key}", "severity": "p0"})
    if not turns:
        invalidators.append({"key": "ignition_report_instrumentation_has_no_turns", "severity": "p0"})
    if any(bool(item.get("self_memory_write", False)) for item in turns):
        invalidators.append({"key": "ignition_report_source_self_memory_write", "severity": "p0"})
    return invalidators


def _hypothesis_decision(
    summary: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    if any(str(item.get("severity", "")) == "p0" for item in invalidators):
        decision = "invalidated"
        scope = "none"
        requires_focused = True
    elif bool(summary.get("current_trace_instrumentation_gap", False)):
        decision = "instrumentation_gap_blocks_gnw_upgrade"
        scope = "diagnostic_trace_schema_repair"
        requires_focused = True
    elif _num(summary.get("observed_ignition_report_transfer"), 0.0) >= 0.5:
        decision = "bounded_ignition_report_instrumentation_supported"
        scope = "structured_gnw_ignition_report_proxy"
        requires_focused = False
    else:
        decision = "ignition_report_transfer_needs_focused_provider_cell"
        scope = "insufficient_ignition_report_transfer"
        requires_focused = True
    return {
        "target": "gnw_ignition_to_report_observability",
        "decision": decision,
        "supported_scope": scope,
        "requires_focused_provider_cell": requires_focused,
        "next_experiment": (
            "run one focused Stage59/60 provider cell after the trace-schema repair and rerun Stage84/85 "
            "before any broad observational provider repeat"
        ),
        "rationale": (
            f"structured_ignition={summary.get('structured_ignition_turn_count', 0)} "
            f"structured_coupling={summary.get('structured_coupling_turn_count', 0)} "
            f"transfer={summary.get('observed_ignition_report_transfer', 0)} "
            f"gap={summary.get('current_trace_instrumentation_gap', False)}"
        ),
    }


def _publication_claims(summary: dict[str, Any], decision: dict[str, Any]) -> list[dict[str, Any]]:
    supported = str(decision.get("decision", "")) == "bounded_ignition_report_instrumentation_supported"
    return [
        {
            "claim": "Structured Stage77 ignition fields can support a bounded GNW ignition-to-report proxy",
            "status": "supported" if supported else "pending_focused_provider_cell",
            "allowed_language": "instrumented ignition-to-report proxy, not subjective report or phenomenal consciousness",
        },
        {
            "claim": "Legacy Stage77 traces explain the Stage84 zero-transfer result as a trace-schema gap",
            "status": "supported" if bool(summary.get("current_trace_instrumentation_gap", False)) else "not_applicable",
            "allowed_language": "observability gap in archived traces, not a negative biological result",
        },
    ]


def _ignition_report_transfer(turns: list[dict[str, Any]]) -> float:
    ignited = [item for item in turns if bool(item.get("ignited", False))]
    if not ignited:
        return 0.0
    reportable = [item for item in ignited if bool(item.get("reportable", False))]
    return len(reportable) / len(ignited)


def _stage84_supported(stream: dict[str, Any]) -> bool:
    summary = _as_dict(stream.get("stream_summary", {}))
    decision = _as_dict(stream.get("hypothesis_decision", {}))
    evidence = _as_dict(stream.get("evidence_gate", {}))
    return (
        bool(stream.get("ok", False))
        and str(stream.get("stage", "")) == "stage84-consciousness-stream-lattice"
        and bool(summary.get("stage83_publication_precondition_supported", False))
        and bool(summary.get("all_trace_reports_real_provider", False))
        and bool(summary.get("marker_control_narrows_reactivation", False))
        and str(decision.get("decision", "")) == "stream_lattice_supports_bounded_consciousness_flow_proxy"
        and bool(evidence.get("do_not_claim_real_consciousness", False))
    )


def _report_real_provider_trace(report: dict[str, Any]) -> bool:
    gates = (
        _as_dict(report.get("evidence_gate", {})),
        _as_dict(report.get("provider_evidence_gate", {})),
        _as_dict(report.get("provider_trace_set", {})),
    )
    return any(bool(item.get("real_provider_trace", False)) for item in gates)


def _cell_label(report: dict[str, Any], index: int) -> str:
    for key in ("cell_label", "model", "model_label", "source_model"):
        value = str(report.get(key, "") or "")
        if value:
            return value
    return f"cell_{index + 1}"


def _write_ignition_report_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    cells = [dict(item) for item in list(report.get("cell_reports", []) or []) if isinstance(item, dict)]
    labels = [_plot_label(str(item.get("cell_label", ""))) for item in cells]
    transfer = numpy.array([_num(item.get("ignition_report_transfer"), 0.0) for item in cells])
    structured = numpy.array(
        [
            _num(item.get("structured_coupling_turn_count"), 0.0) / max(1.0, _num(item.get("turn_count"), 0.0))
            for item in cells
        ]
    )
    x = numpy.arange(len(labels))

    fig, axes = pyplot.subplots(1, 2, figsize=(14, 5.4), dpi=150)
    if len(labels):
        axes[0].bar(x, transfer, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[0].set_title("Ignition-to-Report Transfer")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=18, ha="right")
    axes[0].set_ylim(0, 1.05)
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    if len(labels):
        axes[1].bar(x, structured, color="#8a6f2a", edgecolor="#172026", linewidth=0.8)
    axes[1].set_title("Structured Coupling Coverage")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(labels, rotation=18, ha="right")
    axes[1].set_ylim(0, 1.05)
    axes[1].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage85 Ignition Report Instrumentation | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.24, top=0.82, wspace=0.26)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _cell_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>cell</th><th>turns</th><th>structured ignition</th><th>structured coupling</th><th>ignited</th><th>reportable</th><th>transfer</th></tr>"
    ]
    for item in list(report.get("cell_reports", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('cell_label', ''))}</td>"
            f"<td>{_esc(item.get('turn_count', 0))}</td>"
            f"<td>{_esc(item.get('structured_ignition_turn_count', 0))}</td>"
            f"<td>{_esc(item.get('structured_coupling_turn_count', 0))}</td>"
            f"<td>{_esc(item.get('ignited_turn_count', 0))}</td>"
            f"<td>{_esc(item.get('reportable_turn_count', 0))}</td>"
            f"<td>{_esc(item.get('ignition_report_transfer', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)
