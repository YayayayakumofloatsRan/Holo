from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .biomimetic_consciousness_observatory import (
    BIOMIMETIC_BOUNDARY,
    _as_dict,
    _esc,
    _load_plotting_stack,
    _num,
    _plot_label,
)


STAGE73_NAME = "stage73-biomimetic-provider-progress"

STAGE73_BOUNDARY = {
    **BIOMIMETIC_BOUNDARY,
    "provider_comparison_only": True,
    "counterfactual_headroom_observational_only": True,
    "runtime_mutation_allowed": False,
}


def load_biomimetic_provider_progress_json(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser()
    payload = json.loads(source.read_text(encoding="utf-8"))
    return dict(payload) if isinstance(payload, dict) else {}


def build_biomimetic_provider_progress(
    before_report: dict[str, Any],
    after_report: dict[str, Any],
    *,
    before_trace: dict[str, Any] | None = None,
    after_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    before = dict(before_report or {})
    after = dict(after_report or {})
    absolute = _absolute_progress(before, after)
    residual = _residual_headroom(before, after)
    noise = _provider_noise(before_trace, after_trace)
    invalidators = _stage73_invalidators(before, after)
    decision = _hypothesis_decision(
        absolute,
        residual,
        before=before,
        after=after,
        invalidators=invalidators,
    )
    return {
        "ok": not any(str(item.get("severity", "")) == "p0" for item in invalidators),
        "stage": STAGE73_NAME,
        "source_stage": "stage71-biomimetic-causal-ablation-lab",
        "comparison": {
            "before_stage": before.get("stage", ""),
            "after_stage": after.get("stage", ""),
            "before_decision": _decision(before),
            "after_decision": _decision(after),
        },
        "absolute_progress": absolute,
        "residual_headroom": residual,
        "provider_noise": noise,
        "hypothesis_decision": decision,
        "publication_claims": _publication_claims(decision),
        "run_invalidators": invalidators,
        "boundary_flags": invalidators,
        "evidence_gate": {
            "surrogate_only": not (_real_provider_trace(before) and _real_provider_trace(after)),
            "real_provider_trace": _real_provider_trace(before) and _real_provider_trace(after),
            "do_not_claim_real_consciousness": True,
            "do_not_claim_real_manifold": True,
            "causal_language_bounded": True,
            "separates_absolute_from_residual": True,
            "source_reports_are_stage71_counterfactuals": True,
            "reason": "stage73_separates_real_provider_absolute_progress_from_residual_counterfactual_headroom",
        },
        "boundary": dict(STAGE73_BOUNDARY),
    }


def write_biomimetic_provider_progress_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_biomimetic_provider_progress_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_provider_progress.png")
    _write_progress_png(report, png_path)
    return {"html": html_path, "json": json_path, "progress_png": png_path}


def render_biomimetic_provider_progress_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    absolute = _as_dict(payload.get("absolute_progress", {}))
    residual = _as_dict(payload.get("residual_headroom", {}))
    decision = _as_dict(payload.get("hypothesis_decision", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    noise = _as_dict(payload.get("provider_noise", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage73 Biomimetic Provider Progress</title>
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
    <h1>Stage73 Biomimetic Provider Progress</h1>
    <p class="note">Read-only comparison of real-provider absolute progress against residual Stage71 counterfactual headroom.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Decision", decision.get("decision", ""))}
      {_metric("Provider Interpretation", decision.get("provider_interpretation", ""))}
      {_metric("Hippocampal Baseline Delta", absolute.get("baseline_hippocampal_reactivation_delta", 0))}
      {_metric("Correction Baseline Delta", absolute.get("baseline_correction_survival_proxy_delta", 0))}
      {_metric("Residual Replay Change", residual.get("hippocampal_reactivation_headroom_change", 0))}
      {_metric("Latency Outlier", noise.get("after_latency_outlier", False))}
    </section>
    <section>
      <h2>Absolute Provider Progress</h2>
      {_absolute_table(absolute)}
    </section>
    <section>
      <h2>Residual Counterfactual Headroom</h2>
      {_residual_table(residual)}
    </section>
    <section>
      <h2>Provider Noise</h2>
      {_provider_noise_table(noise)}
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


def _absolute_progress(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "baseline_biomimetic_score": (
            _baseline_biomimetic_score(before),
            _baseline_biomimetic_score(after),
        ),
        "baseline_hippocampal_reactivation": (
            _baseline_dimension(before, "hippocampal_reactivation"),
            _baseline_dimension(after, "hippocampal_reactivation"),
        ),
        "baseline_correction_survival_proxy": (
            _baseline_metric(before, "correction_survival_proxy"),
            _baseline_metric(after, "correction_survival_proxy"),
        ),
        "baseline_flow_to_reply_coupling_proxy": (
            _baseline_metric(before, "flow_to_reply_coupling_proxy"),
            _baseline_metric(after, "flow_to_reply_coupling_proxy"),
        ),
        "baseline_prompt_cost_proxy": (
            _baseline_metric(before, "prompt_cost_proxy"),
            _baseline_metric(after, "prompt_cost_proxy"),
        ),
    }
    result: dict[str, Any] = {}
    metrics: list[dict[str, Any]] = []
    for key, (before_value, after_value) in keys.items():
        result[f"{key}_before"] = round(before_value, 6)
        result[f"{key}_after"] = round(after_value, 6)
        result[f"{key}_delta"] = round(after_value - before_value, 6)
        metrics.append(
            {
                "key": key,
                "before": round(before_value, 6),
                "after": round(after_value, 6),
                "delta": round(after_value - before_value, 6),
            }
        )
    result["metrics"] = metrics
    return result


def _residual_headroom(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    h_before = _effect_estimate(before, "hippocampal_reactivation_delta")
    h_after = _effect_estimate(after, "hippocampal_reactivation_delta")
    c_before = _effect_estimate(before, "correction_survival_proxy_delta")
    c_after = _effect_estimate(after, "correction_survival_proxy_delta")
    f_before = _effect_estimate(before, "flow_to_reply_coupling_delta")
    f_after = _effect_estimate(after, "flow_to_reply_coupling_delta")
    flow_loss_before = abs(min(0.0, f_before))
    flow_loss_after = abs(min(0.0, f_after))
    return {
        "hippocampal_reactivation_headroom_before": round(h_before, 6),
        "hippocampal_reactivation_headroom_after": round(h_after, 6),
        "hippocampal_reactivation_headroom_change": round(h_after - h_before, 6),
        "correction_survival_headroom_before": round(c_before, 6),
        "correction_survival_headroom_after": round(c_after, 6),
        "correction_survival_headroom_change": round(c_after - c_before, 6),
        "flow_to_reply_coupling_ablation_delta_before": round(f_before, 6),
        "flow_to_reply_coupling_ablation_delta_after": round(f_after, 6),
        "flow_to_reply_coupling_ablation_delta_change": round(f_after - f_before, 6),
        "flow_to_reply_coupling_loss_before": round(flow_loss_before, 6),
        "flow_to_reply_coupling_loss_after": round(flow_loss_after, 6),
        "flow_to_reply_coupling_loss_reduction": round(flow_loss_before - flow_loss_after, 6),
        "residual_counterfactual_headroom_present": (
            h_after > 0.005 or c_after > 0.005 or f_after < -0.03
        ),
        "metrics": [
            {
                "key": "hippocampal_reactivation_headroom",
                "before": round(h_before, 6),
                "after": round(h_after, 6),
                "change": round(h_after - h_before, 6),
            },
            {
                "key": "correction_survival_headroom",
                "before": round(c_before, 6),
                "after": round(c_after, 6),
                "change": round(c_after - c_before, 6),
            },
            {
                "key": "flow_to_reply_coupling_loss",
                "before": round(flow_loss_before, 6),
                "after": round(flow_loss_after, 6),
                "change": round(flow_loss_after - flow_loss_before, 6),
            },
        ],
    }


def _provider_noise(
    before_trace: dict[str, Any] | None,
    after_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    before = _trace_summary(dict(before_trace or {}))
    after = _trace_summary(dict(after_trace or {}))
    return {
        "before_run_count": before["run_count"],
        "after_run_count": after["run_count"],
        "before_turn_count": before["turn_count"],
        "after_turn_count": after["turn_count"],
        "before_observed_total_tokens": before["observed_total_tokens"],
        "after_observed_total_tokens": after["observed_total_tokens"],
        "observed_total_tokens_delta": after["observed_total_tokens"] - before["observed_total_tokens"],
        "before_max_latency_ms": before["max_latency_ms"],
        "after_max_latency_ms": after["max_latency_ms"],
        "max_latency_ms_delta": round(after["max_latency_ms"] - before["max_latency_ms"], 6),
        "before_latency_outlier": before["max_latency_ms"] >= 60_000.0,
        "after_latency_outlier": after["max_latency_ms"] >= 60_000.0,
        "real_provider_trace": before["real_provider_trace"] and after["real_provider_trace"],
    }


def _hypothesis_decision(
    absolute: dict[str, Any],
    residual: dict[str, Any],
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    invalidators: list[dict[str, Any]],
) -> dict[str, Any]:
    p0 = any(str(item.get("severity", "")) == "p0" for item in invalidators)
    h_delta = _num(absolute.get("baseline_hippocampal_reactivation_delta"), 0.0)
    c_delta = _num(absolute.get("baseline_correction_survival_proxy_delta"), 0.0)
    score_delta = _num(absolute.get("baseline_biomimetic_score_delta"), 0.0)
    residual_present = bool(residual.get("residual_counterfactual_headroom_present", False))
    real_provider = _real_provider_trace(before) and _real_provider_trace(after)
    absolute_improved = h_delta > 0.0 and c_delta > 0.0 and score_delta >= 0.0
    absolute_regressed = h_delta < -0.01 or c_delta < -0.01 or score_delta < -0.01
    if p0:
        decision = "invalidated"
        interpretation = "provider_progress_invalidated_by_boundary_or_source_error"
    elif not real_provider:
        decision = "needs_real_provider"
        interpretation = "provider_progress_requires_two_real_provider_stage71_reports"
    elif absolute_regressed:
        decision = "absolute_regressed"
        interpretation = "provider_regressed_on_core_reactivation_metrics"
    elif absolute_improved and residual_present:
        decision = "absolute_improved_residual_partial"
        interpretation = "provider_improved_but_counterfactual_headroom_remains"
    elif absolute_improved:
        decision = "absolute_improved_residual_reduced"
        interpretation = "provider_improved_and_counterfactual_headroom_reduced"
    else:
        decision = "no_material_absolute_progress"
        interpretation = "provider_progress_not_detected_at_stage73_thresholds"
    return {
        "target": "provider_correction_reactivation_progress",
        "decision": decision,
        "provider_interpretation": interpretation,
        "absolute_improved": absolute_improved,
        "residual_counterfactual_headroom_present": residual_present,
        "before_stage71_decision": _decision(before),
        "after_stage71_decision": _decision(after),
        "next_experiment": (
            "run matched longer Stage59/60 DeepSeek provider cells with explicit correction probes, "
            "then rerun Stage71 and Stage73 to test whether residual replay headroom compresses"
        ),
        "rationale": (
            f"baseline_hippocampal_delta={round(h_delta, 6)} "
            f"baseline_correction_delta={round(c_delta, 6)} "
            f"baseline_score_delta={round(score_delta, 6)} "
            f"residual_headroom_present={residual_present}"
        ),
    }


def _publication_claims(decision: dict[str, Any]) -> list[dict[str, Any]]:
    status = str(decision.get("decision", ""))
    return [
        {
            "claim": "explicit correction markers improved real-provider baseline reactivation metrics",
            "status": "supported" if status.startswith("absolute_improved") else "not_supported",
            "allowed_language": "real-provider trace comparison, not a consciousness claim",
        },
        {
            "claim": "residual Stage71 counterfactual headroom is still separable from absolute provider gains",
            "status": "supported" if bool(decision.get("residual_counterfactual_headroom_present", False)) else "reduced",
            "allowed_language": "counterfactual headroom estimate, not live causal proof",
        },
    ]


def _stage73_invalidators(before: dict[str, Any], after: dict[str, Any]) -> list[dict[str, Any]]:
    invalidators: list[dict[str, Any]] = []
    for label, report in (("before", before), ("after", after)):
        if str(report.get("stage", "")) != "stage71-biomimetic-causal-ablation-lab":
            invalidators.append({"key": f"{label}_not_stage71_report", "severity": "p0"})
        if not _baseline(report):
            invalidators.append({"key": f"{label}_missing_baseline_condition", "severity": "p0"})
        gate = _as_dict(report.get("evidence_gate", {}))
        if not bool(gate.get("causal_language_bounded", False)):
            invalidators.append({"key": f"{label}_unbounded_causal_language", "severity": "p0"})
        if not bool(gate.get("do_not_claim_real_consciousness", False)):
            invalidators.append({"key": f"{label}_consciousness_claim_not_blocked", "severity": "p0"})
        boundary = _as_dict(report.get("boundary", {}))
        for key in (
            "runtime_decision_authority",
            "transport_decision_authority",
            "self_memory_write_allowed",
            "policy_mutation_allowed",
            "unbounded_loop_allowed",
        ):
            if bool(boundary.get(key, False)):
                invalidators.append({"key": f"{label}_{key}", "severity": "p0"})
    if not _real_provider_trace(before):
        invalidators.append({"key": "before_not_real_provider_trace", "severity": "p1"})
    if not _real_provider_trace(after):
        invalidators.append({"key": "after_not_real_provider_trace", "severity": "p1"})
    return invalidators


def _baseline(report: dict[str, Any]) -> dict[str, Any]:
    paired = _as_dict(report.get("paired_conditions", {}))
    index = _as_dict(paired.get("condition_index", {}))
    return _as_dict(index.get("baseline_observed", {}))


def _baseline_biomimetic_score(report: dict[str, Any]) -> float:
    baseline = _baseline(report)
    scorecard = _as_dict(baseline.get("scorecard", {}))
    stage70 = _as_dict(report.get("baseline_stage70", {}))
    return _num(
        stage70.get("biomimetic_consciousness_score"),
        _num(scorecard.get("biomimetic_consciousness_score"), 0.0),
    )


def _baseline_dimension(report: dict[str, Any], key: str) -> float:
    baseline = _baseline(report)
    return _num(_as_dict(baseline.get("dimension_scores", {})).get(key), 0.0)


def _baseline_metric(report: dict[str, Any], key: str) -> float:
    baseline = _baseline(report)
    return _num(_as_dict(baseline.get("metrics", {})).get(key), 0.0)


def _effect_estimate(report: dict[str, Any], key: str) -> float:
    effects = _as_dict(report.get("causal_effects", {}))
    effect_index = _as_dict(effects.get("effect_index", {}))
    return _num(_as_dict(effect_index.get(key, {})).get("estimate"), 0.0)


def _real_provider_trace(report: dict[str, Any]) -> bool:
    evidence = _as_dict(report.get("evidence_gate", {}))
    return bool(evidence.get("real_provider_trace", False)) and not bool(evidence.get("surrogate_only", True))


def _decision(report: dict[str, Any]) -> str:
    return str(_as_dict(report.get("hypothesis_decision", {})).get("decision", ""))


def _trace_summary(trace: dict[str, Any]) -> dict[str, Any]:
    runs = [
        dict(item)
        for item in list(trace.get("stage46_compatible_runs", []) or [])
        if isinstance(item, dict)
    ]
    turns = [
        dict(turn)
        for run in runs
        for turn in list(run.get("turns", []) or [])
        if isinstance(turn, dict)
    ]
    provider = _as_dict(trace.get("provider_trace_set", {}))
    budget = _as_dict(trace.get("budget_guard", {}))
    latencies = [_num(turn.get("latency_ms"), 0.0) for turn in turns]
    max_latency = max(latencies) if latencies else _num(trace.get("max_latency_ms"), 0.0)
    observed_total_tokens = int(_num(budget.get("observed_total_tokens"), 0.0))
    if observed_total_tokens <= 0:
        observed_total_tokens = int(sum(_turn_total_tokens(turn) for turn in turns))
    return {
        "run_count": int(_num(provider.get("collected_run_count"), len(runs))),
        "turn_count": int(_num(provider.get("collected_turn_count"), len(turns))),
        "observed_total_tokens": observed_total_tokens,
        "max_latency_ms": round(max_latency, 6),
        "real_provider_trace": bool(provider.get("real_provider_trace", False)),
    }


def _turn_total_tokens(turn: dict[str, Any]) -> float:
    usage = _as_dict(turn.get("processor_usage", {}))
    return _num(
        usage.get("total_tokens"),
        _num(usage.get("turn_total_tokens"), _num(turn.get("total_tokens"), 0.0)),
    )


def _write_progress_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    absolute = _as_dict(report.get("absolute_progress", {}))
    residual = _as_dict(report.get("residual_headroom", {}))
    absolute_items = [
        ("hippocampal", _num(absolute.get("baseline_hippocampal_reactivation_delta"), 0.0)),
        ("correction", _num(absolute.get("baseline_correction_survival_proxy_delta"), 0.0)),
        ("flow coupling", _num(absolute.get("baseline_flow_to_reply_coupling_proxy_delta"), 0.0)),
        ("score", _num(absolute.get("baseline_biomimetic_score_delta"), 0.0)),
    ]
    residual_items = [
        ("replay headroom", _num(residual.get("hippocampal_reactivation_headroom_after"), 0.0)),
        ("correction headroom", _num(residual.get("correction_survival_headroom_after"), 0.0)),
        ("flow loss", _num(residual.get("flow_to_reply_coupling_loss_after"), 0.0)),
    ]

    fig, axes = pyplot.subplots(1, 2, figsize=(13.5, 5.4), dpi=150)
    labels = [_plot_label(label) for label, _ in absolute_items]
    values = numpy.array([value for _, value in absolute_items], dtype=float)
    x = numpy.arange(len(labels))
    colors = ["#2f7d68" if value >= 0 else "#9b4d3a" for value in values]
    axes[0].bar(x, values, color=colors, edgecolor="#172026", linewidth=0.8)
    axes[0].axhline(0.0, color="#172026", linewidth=0.8)
    axes[0].set_title("Absolute Provider Deltas")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels(labels, rotation=25, ha="right")
    axes[0].grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)

    r_labels = [_plot_label(label) for label, _ in residual_items]
    r_values = numpy.array([value for _, value in residual_items], dtype=float)
    y = numpy.arange(len(r_labels))
    axes[1].barh(y, r_values, color="#b88424", edgecolor="#172026", linewidth=0.8)
    axes[1].set_xlim(0.0, max(0.06, float(r_values.max()) * 1.16 if len(r_values) else 0.06))
    axes[1].set_title("Residual Headroom After")
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(r_labels)
    axes[1].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)

    decision = _as_dict(report.get("hypothesis_decision", {})).get("decision", "")
    fig.suptitle(f"Stage73 Biomimetic Provider Progress | decision={decision}", fontsize=13, y=0.99)
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.23, top=0.82, wspace=0.38)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _absolute_table(absolute: dict[str, Any]) -> str:
    rows = ["<table><tr><th>metric</th><th>before</th><th>after</th><th>delta</th></tr>"]
    for item in list(absolute.get("metrics", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('before', 0))}</td>"
            f"<td>{_esc(item.get('after', 0))}</td>"
            f"<td>{_esc(item.get('delta', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _residual_table(residual: dict[str, Any]) -> str:
    rows = ["<table><tr><th>metric</th><th>before</th><th>after</th><th>change</th></tr>"]
    for item in list(residual.get("metrics", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('before', 0))}</td>"
            f"<td>{_esc(item.get('after', 0))}</td>"
            f"<td>{_esc(item.get('change', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _provider_noise_table(noise: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "before_turn_count",
        "after_turn_count",
        "before_observed_total_tokens",
        "after_observed_total_tokens",
        "observed_total_tokens_delta",
        "before_max_latency_ms",
        "after_max_latency_ms",
        "after_latency_outlier",
        "real_provider_trace",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(noise.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _gate_table(gate: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "surrogate_only",
        "real_provider_trace",
        "do_not_claim_real_consciousness",
        "do_not_claim_real_manifold",
        "causal_language_bounded",
        "separates_absolute_from_residual",
        "source_reports_are_stage71_counterfactuals",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "comparison": report.get("comparison", {}),
        "absolute_progress": report.get("absolute_progress", {}),
        "residual_headroom": report.get("residual_headroom", {}),
        "provider_noise": report.get("provider_noise", {}),
        "hypothesis_decision": report.get("hypothesis_decision", {}),
        "evidence_gate": report.get("evidence_gate", {}),
    }


def _metric(label: str, value: Any) -> str:
    return f'<div class="metric"><span>{_esc(label)}</span><strong>{_esc(value)}</strong></div>'
