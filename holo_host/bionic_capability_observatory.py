from __future__ import annotations

import html
import json
import math
from pathlib import Path
from typing import Any

from .bionic_simulation_lab import STAGE61_NAME


STAGE62_NAME = "stage62-bionic-capability-observatory"

CAPABILITY_OBSERVATORY_BOUNDARY = {
    "observational_only": True,
    "surrogate_evaluation_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
    "downstream_mcp_server_added": False,
}


def build_bionic_capability_observatory(lab: dict[str, Any]) -> dict[str, Any]:
    source = dict(lab or {})
    simulation_set = _as_dict(source.get("simulation_set", {}))
    telemetry = _as_dict(source.get("internal_telemetry", {}))
    generated_runs = [
        dict(run)
        for run in list(source.get("generated_runs", []) or [])
        if isinstance(run, dict)
    ]
    full_runs = [
        dict(run)
        for run in list(source.get("stage46_compatible_runs", []) or [])
        if isinstance(run, dict)
    ]
    if not generated_runs and full_runs:
        generated_runs = [_compact_full_run(run) for run in full_runs]

    capability_scorecard = _build_capability_scorecard(
        simulation_set=simulation_set,
        telemetry=telemetry,
        generated_runs=generated_runs,
    )
    forward_explainability = _build_forward_explainability(
        generated_runs=generated_runs,
        full_runs=full_runs,
    )
    reverse_engineering = _build_reverse_engineering(
        source=source,
        scorecard=capability_scorecard,
        forward=forward_explainability,
    )
    intervention_plan = _build_intervention_plan(reverse_engineering)
    evidence_gate = _build_evidence_gate(source)
    return {
        "ok": True,
        "stage": STAGE62_NAME,
        "source_stage": STAGE61_NAME,
        "source_stage_reported": str(source.get("stage", "") or ""),
        "capability_scorecard": capability_scorecard,
        "forward_explainability": forward_explainability,
        "reverse_engineering": reverse_engineering,
        "intervention_plan": intervention_plan,
        "evidence_gate": evidence_gate,
        "boundary": dict(CAPABILITY_OBSERVATORY_BOUNDARY),
    }


def write_bionic_capability_observatory_artifacts(
    report: dict[str, Any],
    output_path: str | Path,
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_bionic_capability_observatory_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_capability_observatory.png")
    _write_capability_observatory_png(report, png_path)
    return {
        "html": html_path,
        "json": json_path,
        "capability_png": png_path,
    }


def render_bionic_capability_observatory_html(report: dict[str, Any]) -> str:
    payload = dict(report or {})
    scorecard = _as_dict(payload.get("capability_scorecard", {}))
    forward = _as_dict(payload.get("forward_explainability", {}))
    reverse = _as_dict(payload.get("reverse_engineering", {}))
    evidence = _as_dict(payload.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(payload), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Bionic Capability Observatory</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1220px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }}
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
    <h1>Holo Bionic Capability Observatory</h1>
    <p class="note">Capability and explainability evaluation over Stage61 surrogate internal telemetry. It ranks engineering bottlenecks and intervention targets without claiming live-provider evidence or a real consciousness manifold.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Scenarios", scorecard.get("scenario_count", 0))}
      {_metric("Aggregate Score", scorecard.get("aggregate_score", 0))}
      {_metric("Forward Chains", len(forward.get("scenario_chains", []) or []))}
      {_metric("Bottlenecks", len(reverse.get("ranked_bottlenecks", []) or []))}
      {_metric("Cache", _dimension_value(scorecard, "cache_inheritance"))}
      {_metric("Latency", _dimension_value(scorecard, "latency_residual"))}
      {_metric("Grounding", _dimension_value(scorecard, "grounding_integrity"))}
      {_metric("Explainability", _dimension_value(scorecard, "explainability_coverage"))}
    </section>
    <section>
      <h2>Capability Scorecard</h2>
      {_dimension_table(scorecard)}
    </section>
    <section>
      <h2>Forward Explainability</h2>
      {_forward_table(forward)}
    </section>
    <section>
      <h2>Reverse Engineering</h2>
      {_bottleneck_table(reverse)}
    </section>
    <section>
      <h2>Intervention Plan</h2>
      {_intervention_table(payload)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">do_not_claim_real_manifold={_esc(evidence.get("do_not_claim_real_manifold", True))}</p>
      {_gate_table(evidence)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _build_capability_scorecard(
    *,
    simulation_set: dict[str, Any],
    telemetry: dict[str, Any],
    generated_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    scenario_count = int(
        simulation_set.get("scenario_count", 0) or len(generated_runs) or 0
    )
    turn_count = int(telemetry.get("turn_count", 0) or 0)
    cache_ratio = _clamp01(_num(telemetry.get("prompt_cache_hit_ratio"), 0.0))
    p95_latency = max(0.0, _num(telemetry.get("p95_latency_ms"), 0.0))
    recall_budget = max(0.0, _num(telemetry.get("average_recall_budget"), 0.0))
    salience = _clamp01(_num(telemetry.get("average_salience_score"), 0.0))
    phase_entropy = _clamp01(_num(telemetry.get("phase_entropy"), 0.0))
    tool_needed = int(telemetry.get("tool_pressure_turn_count", 0) or 0)
    tool_coverage = _clamp01(_num(telemetry.get("tool_observation_coverage"), 1.0))
    visual_failures = int(telemetry.get("visual_rewrite_failure_count", 0) or 0)
    commitment_failures = int(telemetry.get("commitment_failure_count", 0) or 0)
    scores = [
        _clamp01(_num(run.get("overall_score"), 0.0))
        for run in generated_runs
    ]
    continuity = _clamp01(_mean(scores, default=0.0))
    dimensions = [
        _dimension(
            "continuity_stability",
            continuity,
            "mean scenario stability under perturbation",
            f"scenario_scores={len(scores)}",
            0.18,
        ),
        _dimension(
            "memory_resilience",
            _clamp01((min(recall_budget, 5.0) / 5.0) * 0.62 + salience * 0.38),
            "salience plus recall budget under memory and correction pressure",
            f"average_recall_budget={round(recall_budget, 4)} average_salience_score={round(salience, 4)}",
            0.16,
        ),
        _dimension(
            "grounding_integrity",
            _clamp01(1.0 - ((visual_failures + commitment_failures) / max(1, turn_count)) * 8.0),
            "visual and temporal commitment boundary preservation",
            f"visual_failures={visual_failures} commitment_failures={commitment_failures} turn_count={turn_count}",
            0.15,
        ),
        _dimension(
            "tool_observation",
            tool_coverage if tool_needed > 0 else 1.0,
            "bounded upstream tool observation coverage when tool pressure appears",
            f"tool_observation_coverage={tool_coverage} tool_pressure_turn_count={tool_needed}",
            0.12,
        ),
        _dimension(
            "latency_residual",
            _clamp01(1.0 - max(0.0, p95_latency - 3500.0) / 9500.0),
            "tail latency after residual fast-channel pressure",
            f"p95_latency_ms={round(p95_latency, 2)}",
            0.14,
        ),
        _dimension(
            "cache_inheritance",
            _clamp01(cache_ratio / 0.55),
            "provider cache prefix reuse and context inheritance",
            f"prompt_cache_hit_ratio={round(cache_ratio, 6)}",
            0.14,
        ),
        _dimension(
            "explainability_coverage",
            _clamp01((phase_entropy * 0.58) + (min(1.0, scenario_count / 7.0) * 0.42)),
            "phase diversity and scenario coverage for forward/reverse analysis",
            f"phase_entropy={round(phase_entropy, 6)} scenario_count={scenario_count}",
            0.11,
        ),
    ]
    weight_total = sum(float(item["weight"]) for item in dimensions) or 1.0
    aggregate = sum(float(item["score"]) * float(item["weight"]) for item in dimensions) / weight_total
    return {
        "scenario_count": scenario_count,
        "turn_count": turn_count,
        "aggregate_score": round(_clamp01(aggregate), 6),
        "dimensions": dimensions,
        "dimension_index": {str(item["key"]): item for item in dimensions},
    }


def _build_forward_explainability(
    *,
    generated_runs: list[dict[str, Any]],
    full_runs: list[dict[str, Any]],
) -> dict[str, Any]:
    chains: list[dict[str, Any]] = []
    for index, generated in enumerate(generated_runs):
        full = full_runs[index] if index < len(full_runs) else generated
        metrics = _run_metrics(full, generated)
        scenario_type = str(
            generated.get("scenario_type", "")
            or _as_dict(full.get("perturbation", {})).get("type", "")
            or f"scenario_{index + 1}"
        )
        primary_pressure = str(
            generated.get("primary_pressure", "")
            or _as_dict(full.get("perturbation", {})).get("primary_pressure", "")
            or "unknown"
        )
        pressures = _pressure_vector(metrics)
        chains.append(
            {
                "rank": index + 1,
                "run_id": str(generated.get("run_id", "") or full.get("run_id", "")),
                "scenario_type": scenario_type,
                "primary_pressure": primary_pressure,
                "scenario_score": round(_clamp01(_num(metrics.get("overall_score"), 0.0)), 6),
                "dominant_internal_signals": _dominant_signals(pressures, metrics),
                "capability_impacts": _capability_impacts(pressures),
                "evidence_refs": {
                    "turn_count": int(metrics.get("turn_count", 0) or 0),
                    "total_tokens": int(metrics.get("total_tokens", 0) or 0),
                    "prompt_cache_hit_ratio": round(_num(metrics.get("prompt_cache_hit_ratio"), 0.0), 6),
                    "average_latency_ms": round(_num(metrics.get("average_latency_ms"), 0.0), 2),
                },
            }
        )
    return {
        "mode": "pressure_to_internal_state_to_capability_v1",
        "scenario_count": len(generated_runs),
        "scenario_chains": chains,
    }


def _build_reverse_engineering(
    *,
    source: dict[str, Any],
    scorecard: dict[str, Any],
    forward: dict[str, Any],
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for item in list(source.get("improvement_backlog", []) or []):
        if isinstance(item, dict):
            candidates.append(_bottleneck_from_backlog(item))
    dimension_index = _as_dict(scorecard.get("dimension_index", {}))
    for key, threshold in {
        "cache_inheritance": 0.72,
        "latency_residual": 0.72,
        "grounding_integrity": 0.78,
        "memory_resilience": 0.72,
        "tool_observation": 0.75,
        "explainability_coverage": 0.78,
    }.items():
        dimension = _as_dict(dimension_index.get(key, {}))
        score = _num(dimension.get("score"), 1.0)
        if score < threshold:
            candidates.append(_bottleneck_from_dimension(key, dimension, threshold))
    if not candidates:
        candidates.append(
            {
                "key": "no_blocking_observatory_deficit",
                "score": 0.2,
                "target": "operator review",
                "evidence": "all capability dimensions above observatory thresholds",
                "likely_mechanism": "surrogate run does not expose a high-severity internal deficit",
                "affected_capabilities": ["external_validation"],
                "recommended_probe": "run operator-gated Stage60 provider traces before promoting claims",
                "recommendation": "Move from surrogate-only analysis to bounded real-provider evidence collection.",
            }
        )
    ranked = _dedupe_bottlenecks(candidates)
    ranked.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
    for index, item in enumerate(ranked):
        item["rank"] = index + 1
    return {
        "mode": "capability_drop_to_internal_bottleneck_v1",
        "forward_chain_count": len(forward.get("scenario_chains", []) or []),
        "ranked_bottlenecks": ranked,
    }


def _build_intervention_plan(reverse_engineering: dict[str, Any]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for bottleneck in list(reverse_engineering.get("ranked_bottlenecks", []) or [])[:8]:
        if not isinstance(bottleneck, dict):
            continue
        key = str(bottleneck.get("key", "") or "unknown")
        plan.append(
            {
                "rank": len(plan) + 1,
                "bottleneck_key": key,
                "target": str(bottleneck.get("target", "") or ""),
                "recommendation": str(bottleneck.get("recommendation", "") or ""),
                "validation": _validation_for_bottleneck(key),
                "auto_apply": False,
            }
        )
    return plan


def _build_evidence_gate(source: dict[str, Any]) -> dict[str, Any]:
    upstream = _as_dict(source.get("evidence_gate", {}))
    return {
        "surrogate_only": True,
        "source_surrogate_only": bool(upstream.get("surrogate_only", True)),
        "real_provider_trace": False,
        "do_not_claim_real_manifold": True,
        "do_not_claim_major_breakthrough": True,
        "operator_gated_before_real_provider": True,
        "reason": (
            "Stage62 evaluates Stage61 surrogate internal telemetry and produces "
            "engineering hypotheses; it is not live provider evidence and must not "
            "be used to claim a real consciousness geometry."
        ),
    }


def _run_metrics(full: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    turns = [dict(turn) for turn in list(full.get("turns", []) or []) if isinstance(turn, dict)]
    scorecard = _as_dict(full.get("scorecard", {}))
    if not turns:
        return {
            "turn_count": int(generated.get("turn_count", 0) or 0),
            "overall_score": _num(generated.get("overall_score"), 0.0),
            "total_tokens": int(generated.get("total_tokens", 0) or 0),
            "prompt_cache_hit_ratio": _num(generated.get("prompt_cache_hit_ratio"), 0.0),
            "average_latency_ms": 0.0,
            "average_recall_budget": 0.0,
            "tool_observation_coverage": 1.0,
            "grounding_failure_ratio": 0.0,
        }
    total_tokens = 0
    hit = 0
    miss = 0
    latencies: list[float] = []
    recalls: list[float] = []
    saliences: list[float] = []
    tool_needed = 0
    tool_observed = 0
    grounding_failures = 0
    for turn in turns:
        usage = _as_dict(turn.get("processor_usage", {}))
        debug = _as_dict(turn.get("processor_debug", {}))
        schedule = _as_dict(debug.get("bionic_memory_schedule", {}))
        tool = _as_dict(debug.get("tool_observation", {}))
        guard = _as_dict(turn.get("grounding_guard", {}))
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        hit += int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        miss += int(usage.get("prompt_cache_miss_tokens", 0) or 0)
        latencies.append(_num(turn.get("latency_ms"), 0.0))
        recalls.append(_num(schedule.get("recall_budget"), 0.0))
        saliences.append(_num(schedule.get("salience_score"), 0.0))
        if bool(tool.get("needed", False)):
            tool_needed += 1
            if bool(tool.get("observed", False)):
                tool_observed += 1
        if not bool(guard.get("visual_overclaim_rewritten", True)):
            grounding_failures += 1
        if bool(guard.get("prospective_commitment_failed", False)):
            grounding_failures += 1
    return {
        "turn_count": len(turns),
        "overall_score": _num(scorecard.get("overall_score"), _num(generated.get("overall_score"), 0.0)),
        "total_tokens": total_tokens,
        "prompt_cache_hit_ratio": hit / max(1, hit + miss),
        "average_latency_ms": _mean(latencies),
        "average_recall_budget": _mean(recalls),
        "average_salience_score": _mean(saliences),
        "tool_observation_coverage": tool_observed / max(1, tool_needed),
        "tool_pressure_turn_count": tool_needed,
        "grounding_failure_ratio": grounding_failures / max(1, len(turns)),
    }


def _pressure_vector(metrics: dict[str, Any]) -> dict[str, float]:
    cache_ratio = _clamp01(_num(metrics.get("prompt_cache_hit_ratio"), 0.0))
    latency = _num(metrics.get("average_latency_ms"), 0.0)
    recall = _num(metrics.get("average_recall_budget"), 0.0)
    score = _clamp01(_num(metrics.get("overall_score"), 0.0))
    tool_needed = int(metrics.get("tool_pressure_turn_count", 0) or 0)
    tool_coverage = _clamp01(_num(metrics.get("tool_observation_coverage"), 1.0))
    return {
        "cache_inheritance_pressure": _clamp01(1.0 - cache_ratio / 0.55),
        "latency_pressure": _clamp01(max(0.0, latency - 3500.0) / 6500.0),
        "memory_recall_pressure": _clamp01(1.0 - recall / 4.0),
        "grounding_boundary_pressure": _clamp01(_num(metrics.get("grounding_failure_ratio"), 0.0) * 16.0),
        "tool_observation_gap": _clamp01(1.0 - tool_coverage) if tool_needed > 0 else 0.0,
        "capability_drop": _clamp01(1.0 - score),
    }


def _dominant_signals(
    pressures: dict[str, float],
    metrics: dict[str, Any],
) -> list[dict[str, Any]]:
    rows = []
    for key, value in sorted(pressures.items(), key=lambda pair: pair[1], reverse=True)[:4]:
        rows.append(
            {
                "key": key,
                "pressure": round(_clamp01(value), 6),
                "metric_value": _metric_value_for_pressure(key, metrics),
            }
        )
    return rows


def _capability_impacts(pressures: dict[str, float]) -> list[str]:
    impacts: list[str] = []
    if pressures.get("cache_inheritance_pressure", 0.0) > 0.35:
        impacts.append("context_continuity_and_prompt_cache_efficiency")
    if pressures.get("latency_pressure", 0.0) > 0.35:
        impacts.append("interactive_latency_and_fast_residual_response")
    if pressures.get("memory_recall_pressure", 0.0) > 0.35:
        impacts.append("long_context_memory_recall")
    if pressures.get("grounding_boundary_pressure", 0.0) > 0.2:
        impacts.append("grounding_integrity")
    if pressures.get("tool_observation_gap", 0.0) > 0.2:
        impacts.append("bounded_upstream_tool_use")
    if pressures.get("capability_drop", 0.0) > 0.12:
        impacts.append("overall_scenario_stability")
    return impacts or ["no_major_drop_in_this_scenario"]


def _bottleneck_from_backlog(item: dict[str, Any]) -> dict[str, Any]:
    key = str(item.get("key", "") or "unknown")
    severity = str(item.get("severity", "") or "medium").lower()
    base = {"high": 0.92, "medium": 0.68, "low": 0.42, "info": 0.2}.get(severity, 0.55)
    return {
        "key": key,
        "score": base,
        "target": str(item.get("target", "") or ""),
        "evidence": str(item.get("evidence", "") or ""),
        "likely_mechanism": _mechanism_for_bottleneck(key),
        "affected_capabilities": _affected_capabilities_for_bottleneck(key),
        "recommended_probe": _probe_for_bottleneck(key),
        "recommendation": str(item.get("recommendation", "") or ""),
    }


def _bottleneck_from_dimension(
    key: str,
    dimension: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    score = _clamp01((threshold - _num(dimension.get("score"), 0.0)) / max(threshold, 0.01))
    bottleneck_key = f"{key}_below_observatory_threshold"
    return {
        "key": bottleneck_key,
        "score": round(0.45 + score * 0.4, 6),
        "target": str(dimension.get("evidence", "") or key),
        "evidence": (
            f"{key}={dimension.get('score', 0)} threshold={round(threshold, 4)} "
            f"source={dimension.get('evidence', '')}"
        ),
        "likely_mechanism": _mechanism_for_bottleneck(key),
        "affected_capabilities": _affected_capabilities_for_bottleneck(key),
        "recommended_probe": _probe_for_bottleneck(key),
        "recommendation": f"Raise {key} above the observatory threshold with a bounded pipeline change, then rerun Stage61 and Stage62.",
    }


def _dedupe_bottlenecks(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for item in candidates:
        key = str(item.get("key", "") or "unknown")
        existing = merged.get(key)
        if existing is None or float(item.get("score", 0.0) or 0.0) > float(existing.get("score", 0.0) or 0.0):
            merged[key] = dict(item)
    return list(merged.values())


def _validation_for_bottleneck(key: str) -> str:
    if "cache" in key:
        return "Rerun Stage61 and Stage62; require higher prompt_cache_hit_ratio without lower capability aggregate."
    if "latency" in key:
        return "Rerun Stage61 latency-pressure scenarios; require lower p95_latency_ms and stable grounding_integrity."
    if "tool" in key:
        return "Rerun tool-pressure scenarios; require higher bounded tool_observation coverage with runtime_decision_authority=false."
    if "grounding" in key or "visual" in key or "commitment" in key:
        return "Rerun visual commitment boundary scenarios; require fewer guard failures and unchanged evidence gate."
    if "memory" in key or "recall" in key:
        return "Rerun memory-drop and false-fact correction scenarios; require stronger recall and salience scores."
    return "Rerun Stage61 and Stage62; compare aggregate_score and bottleneck rank before accepting the change."


def _mechanism_for_bottleneck(key: str) -> str:
    if "cache" in key:
        return "volatile prompt frames dominate stable prefix reuse, reducing context inheritance and provider cache hits"
    if "latency" in key:
        return "tail turns stay on the slow deliberation path when a bounded residual fast channel should carry continuity"
    if "tool" in key:
        return "tool pressure is detected but not consistently converted into bounded upstream observations"
    if "visual" in key or "grounding" in key or "commitment" in key:
        return "grounding guard does not bind the response before visual or temporal commitment language reaches output"
    if "memory" in key or "recall" in key:
        return "memory scheduler recall floor is too thin under perturbation"
    if "explainability" in key or "phase" in key or "trace" in key:
        return "internal telemetry lacks enough phase or trace diversity to support stable geometric analysis"
    return "surrogate telemetry exposed a capability deficit that needs a targeted probe"


def _affected_capabilities_for_bottleneck(key: str) -> list[str]:
    if "cache" in key:
        return ["context_continuity", "prompt_cache_efficiency", "long_context_adaptation"]
    if "latency" in key:
        return ["interactive_latency", "residual_fast_channel", "conversation_flow"]
    if "tool" in key:
        return ["bounded_tool_observation", "upstream_mcp_readiness"]
    if "visual" in key or "grounding" in key or "commitment" in key:
        return ["grounding_integrity", "visual_honesty", "temporal_commitment_safety"]
    if "memory" in key or "recall" in key:
        return ["memory_recall", "belief_revision", "continuity_repair"]
    if "explainability" in key or "phase" in key or "trace" in key:
        return ["interpretability", "geometry_observability"]
    return ["overall_bionic_capability"]


def _probe_for_bottleneck(key: str) -> str:
    if "cache" in key:
        return "increase cache-cold-context scenarios and inspect stable-prefix versus dynamic-frame movement"
    if "latency" in key:
        return "run latency-pressure turns with residual fast-channel markers and compare p95 tails"
    if "tool" in key:
        return "run tool-pressure scenarios and verify observation coverage without adding downstream authority"
    if "visual" in key or "grounding" in key or "commitment" in key:
        return "run visual commitment boundary scenarios with guard failure counters"
    if "memory" in key or "recall" in key:
        return "run memory-drop and false-fact correction scenarios with recall floor telemetry"
    return "run a paired Stage61/Stage62 campaign and compare bottleneck rank movement"


def _write_capability_observatory_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    scorecard = _as_dict(report.get("capability_scorecard", {}))
    dimensions = [
        dict(item)
        for item in list(scorecard.get("dimensions", []) or [])
        if isinstance(item, dict)
    ]
    reverse = _as_dict(report.get("reverse_engineering", {}))
    bottlenecks = [
        dict(item)
        for item in list(reverse.get("ranked_bottlenecks", []) or [])[:8]
        if isinstance(item, dict)
    ]
    fig, axes = pyplot.subplots(1, 2, figsize=(15, 6.2), dpi=150)
    dim_labels = [_plot_label(str(item.get("key", "") or "")) for item in dimensions]
    dim_scores = numpy.array([float(item.get("score", 0.0) or 0.0) for item in dimensions], dtype=float)
    dim_y = numpy.arange(len(dim_labels))
    if len(dim_labels):
        axes[0].barh(dim_y, dim_scores, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
    axes[0].set_xlim(0.0, 1.05)
    axes[0].set_title("Capability Scorecard")
    axes[0].set_yticks(dim_y)
    axes[0].set_yticklabels(dim_labels)
    axes[0].invert_yaxis()
    axes[0].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)

    bottleneck_labels = [_plot_label(str(item.get("key", "") or "")) for item in bottlenecks]
    bottleneck_scores = numpy.array([float(item.get("score", 0.0) or 0.0) for item in bottlenecks], dtype=float)
    y = numpy.arange(len(bottleneck_labels))
    if len(bottleneck_labels):
        axes[1].barh(y, bottleneck_scores, color="#b88424", edgecolor="#172026", linewidth=0.8)
    axes[1].set_xlim(0.0, 1.05)
    axes[1].set_title("Reverse-Engineered Bottlenecks")
    axes[1].set_yticks(y)
    axes[1].set_yticklabels(bottleneck_labels)
    axes[1].invert_yaxis()
    axes[1].grid(True, axis="x", color="#d7dddc", linewidth=0.7, alpha=0.75)
    fig.suptitle(
        "Stage62 Bionic Capability Observatory | "
        f"aggregate={scorecard.get('aggregate_score', 0)} | "
        f"scenarios={scorecard.get('scenario_count', 0)}",
        fontsize=13,
        y=0.99,
    )
    fig.subplots_adjust(left=0.18, right=0.98, bottom=0.1, top=0.86, wspace=0.38)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path)
    pyplot.close(fig)


def _compact_full_run(run: dict[str, Any]) -> dict[str, Any]:
    metrics = _run_metrics(run, {})
    perturbation = _as_dict(run.get("perturbation", {}))
    return {
        "run_id": str(run.get("run_id", "") or ""),
        "status": str(run.get("status", "") or ""),
        "scenario_type": str(perturbation.get("type", "") or ""),
        "primary_pressure": str(perturbation.get("primary_pressure", "") or ""),
        "turn_count": int(metrics.get("turn_count", 0) or 0),
        "overall_score": round(_num(metrics.get("overall_score"), 0.0), 6),
        "total_tokens": int(metrics.get("total_tokens", 0) or 0),
        "prompt_cache_hit_ratio": round(_num(metrics.get("prompt_cache_hit_ratio"), 0.0), 6),
    }


def _dimension(
    key: str,
    score: float,
    label: str,
    evidence: str,
    weight: float,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "score": round(_clamp01(score), 6),
        "weight": round(float(weight), 4),
        "evidence": evidence,
    }


def _dimension_value(scorecard: dict[str, Any], key: str) -> Any:
    dimension = _as_dict(_as_dict(scorecard.get("dimension_index", {})).get(key, {}))
    return dimension.get("score", "")


def _metric_value_for_pressure(key: str, metrics: dict[str, Any]) -> Any:
    if "cache" in key:
        return round(_num(metrics.get("prompt_cache_hit_ratio"), 0.0), 6)
    if "latency" in key:
        return round(_num(metrics.get("average_latency_ms"), 0.0), 2)
    if "memory" in key:
        return round(_num(metrics.get("average_recall_budget"), 0.0), 4)
    if "grounding" in key:
        return round(_num(metrics.get("grounding_failure_ratio"), 0.0), 6)
    if "tool" in key:
        return round(_num(metrics.get("tool_observation_coverage"), 0.0), 6)
    return round(_num(metrics.get("overall_score"), 0.0), 6)


def _plot_label(key: str) -> str:
    replacements = {
        "continuity_stability": "continuity\nstability",
        "memory_resilience": "memory\nresilience",
        "grounding_integrity": "grounding\nintegrity",
        "tool_observation": "tool\nobservation",
        "latency_residual": "latency\nresidual",
        "cache_inheritance": "cache\ninheritance",
        "explainability_coverage": "explainability\ncoverage",
        "cache_inheritance_low": "cache\ninheritance low",
        "visual_boundary_rewrite_gap": "visual boundary\nrewrite gap",
        "commitment_binding_gap": "commitment\nbinding gap",
        "latency_tail_high": "latency\ntail high",
        "tool_observation_coverage_low": "tool coverage\nlow",
    }
    if key in replacements:
        return replacements[key]
    parts = [part for part in key.split("_") if part]
    if len(parts) <= 2:
        return key
    midpoint = max(1, len(parts) // 2)
    return " ".join(parts[:midpoint]) + "\n" + " ".join(parts[midpoint:])


def _dimension_table(scorecard: dict[str, Any]) -> str:
    rows = ["<table><tr><th>dimension</th><th>score</th><th>weight</th><th>evidence</th></tr>"]
    for item in list(scorecard.get("dimensions", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('score', 0))}</td>"
            f"<td>{_esc(item.get('weight', 0))}</td>"
            f"<td>{_esc(item.get('evidence', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _forward_table(forward: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>rank</th><th>scenario</th><th>pressure</th><th>score</th><th>dominant signals</th><th>impacts</th></tr>"
    ]
    for chain in list(forward.get("scenario_chains", []) or []):
        if not isinstance(chain, dict):
            continue
        signals = ", ".join(
            f"{item.get('key', '')}={item.get('pressure', '')}"
            for item in list(chain.get("dominant_internal_signals", []) or [])
            if isinstance(item, dict)
        )
        rows.append(
            "<tr>"
            f"<td>{_esc(chain.get('rank', ''))}</td>"
            f"<td>{_esc(chain.get('scenario_type', ''))}</td>"
            f"<td>{_esc(chain.get('primary_pressure', ''))}</td>"
            f"<td>{_esc(chain.get('scenario_score', 0))}</td>"
            f"<td>{_esc(signals)}</td>"
            f"<td>{_esc(', '.join(str(item) for item in list(chain.get('capability_impacts', []) or [])))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _bottleneck_table(reverse: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>rank</th><th>key</th><th>score</th><th>target</th><th>evidence</th><th>probe</th></tr>"
    ]
    for item in list(reverse.get("ranked_bottlenecks", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('rank', ''))}</td>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('score', 0))}</td>"
            f"<td>{_esc(item.get('target', ''))}</td>"
            f"<td>{_esc(item.get('evidence', ''))}</td>"
            f"<td>{_esc(item.get('recommended_probe', ''))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _intervention_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>rank</th><th>bottleneck</th><th>target</th><th>validation</th><th>auto apply</th></tr>"
    ]
    for item in list(report.get("intervention_plan", []) or []):
        if not isinstance(item, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('rank', ''))}</td>"
            f"<td>{_esc(item.get('bottleneck_key', ''))}</td>"
            f"<td>{_esc(item.get('target', ''))}</td>"
            f"<td>{_esc(item.get('validation', ''))}</td>"
            f"<td>{_esc(item.get('auto_apply', False))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _gate_table(gate: dict[str, Any]) -> str:
    rows = ["<table><tr><th>field</th><th>value</th></tr>"]
    for key in (
        "surrogate_only",
        "real_provider_trace",
        "do_not_claim_real_manifold",
        "do_not_claim_major_breakthrough",
        "operator_gated_before_real_provider",
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "source_stage": report.get("source_stage", ""),
        "capability_scorecard": {
            "scenario_count": _as_dict(report.get("capability_scorecard", {})).get("scenario_count", 0),
            "turn_count": _as_dict(report.get("capability_scorecard", {})).get("turn_count", 0),
            "aggregate_score": _as_dict(report.get("capability_scorecard", {})).get("aggregate_score", 0),
            "dimensions": _as_dict(report.get("capability_scorecard", {})).get("dimensions", []),
        },
        "forward_explainability": report.get("forward_explainability", {}),
        "reverse_engineering": report.get("reverse_engineering", {}),
        "intervention_plan": report.get("intervention_plan", []),
        "evidence_gate": report.get("evidence_gate", {}),
        "boundary": report.get("boundary", {}),
    }


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{_esc(label)}</span><strong>{_esc(value)}</strong>"
        "</div>"
    )


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib
        import matplotlib.pyplot as pyplot
        import numpy
    except ImportError as exc:
        raise RuntimeError(
            "Stage62 bionic capability observatory PNG export requires matplotlib and numpy"
        ) from exc
    return matplotlib, pyplot, numpy


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _num(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _mean(values: list[float], *, default: float = 0.0) -> float:
    clean: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            clean.append(number)
    if not clean:
        return default
    return sum(clean) / len(clean)


def _clamp01(value: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return min(1.0, max(0.0, number))


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
