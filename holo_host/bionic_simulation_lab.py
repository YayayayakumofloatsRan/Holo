from __future__ import annotations

import hashlib
import html
import json
import math
from pathlib import Path
from typing import Any

from .bionic_boundary_stress import DEFAULT_STAGE46_SUITE, STAGE46_NAME
from .bionic_memory_scheduler import (
    CACHE_INHERITANCE_MODE,
    DYNAMIC_DELTA_FRAME_MODE,
    RESIDUAL_WORKING_CHANNEL_MODE,
    TOOL_OBSERVATION_MODE,
)
from .consciousness_geometry_calibration import build_geometry_calibration


STAGE61_NAME = "stage61-bionic-simulation-lab"

SIMULATION_LAB_BOUNDARY = {
    "observational_only": True,
    "surrogate_generation_only": True,
    "source_trace_only": True,
    "runtime_decision_authority": False,
    "transport_decision_authority": False,
    "wechat_transport_used": False,
    "self_memory_write_allowed": False,
    "policy_mutation_allowed": False,
    "unbounded_loop_allowed": False,
}

SIMULATION_PROGRAM = (
    {
        "type": "baseline_continuity",
        "intensity": 0.0,
        "score": 0.982,
        "primary_pressure": "continuity",
    },
    {
        "type": "memory_drop",
        "intensity": 0.24,
        "score": 0.9,
        "primary_pressure": "hippocampal_recall",
    },
    {
        "type": "false_fact_correction",
        "intensity": 0.34,
        "score": 0.84,
        "primary_pressure": "belief_revision",
    },
    {
        "type": "cache_cold_context",
        "intensity": 0.32,
        "score": 0.875,
        "primary_pressure": "cache_inheritance",
    },
    {
        "type": "tool_pressure",
        "intensity": 0.28,
        "score": 0.88,
        "primary_pressure": "bounded_tool_observation",
    },
    {
        "type": "latency_pressure",
        "intensity": 0.38,
        "score": 0.86,
        "primary_pressure": "fast_residual_channel",
    },
    {
        "type": "visual_commitment_boundary",
        "intensity": 0.42,
        "score": 0.81,
        "primary_pressure": "grounding_commitment_integrity",
    },
)


def build_bionic_simulation_lab(
    stage46_seed_runs: list[dict[str, Any]] | None = None,
    *,
    scenarios: int = 7,
    turns_per_scenario: int = 180,
) -> dict[str, Any]:
    seeds = [
        dict(run)
        for run in list(stage46_seed_runs or [])
        if isinstance(run, dict)
    ]
    if not seeds:
        seeds = [_fallback_seed_run()]
    safe_scenarios = max(1, min(256, int(scenarios or 1)))
    safe_turns = max(8, min(10_000, int(turns_per_scenario or 180)))
    programs = [
        dict(SIMULATION_PROGRAM[index % len(SIMULATION_PROGRAM)])
        for index in range(safe_scenarios)
    ]
    runs = [
        _generate_simulated_run(
            seeds[index % len(seeds)],
            program,
            scenario_index=index,
            turns=safe_turns,
        )
        for index, program in enumerate(programs)
    ]
    telemetry = _build_internal_telemetry(runs)
    calibration = build_geometry_calibration(runs)
    improvement_backlog = _build_improvement_backlog(telemetry, calibration, runs)
    return {
        "ok": True,
        "stage": STAGE61_NAME,
        "source_stage": STAGE46_NAME,
        "simulation_set": {
            "mode": "stage61_high_throughput_surrogate_interactions_v1",
            "scenario_count": len(runs),
            "turns_per_scenario": safe_turns,
            "total_simulated_turns": len(runs) * safe_turns,
            "scenario_types": [str(program.get("type", "")) for program in programs],
            "seed_run_count": len(seeds),
            "evidence_class": "surrogate_internal_telemetry_not_live_provider_evidence",
        },
        "generated_runs": [_compact_run(run) for run in runs],
        "stage46_compatible_runs": runs,
        "internal_telemetry": telemetry,
        "stage57_calibration": calibration,
        "improvement_backlog": improvement_backlog,
        "toolchain_readiness": {
            "stage46_compatible_runs_ready": True,
            "stage54_visualization_ready": True,
            "stage57_calibration_ready": True,
            "turn_journal_ready": True,
            "html_json_png_ready": True,
            "real_provider_evidence_ready": False,
        },
        "evidence_gate": {
            "surrogate_only": True,
            "real_provider_trace": False,
            "do_not_claim_real_manifold": True,
            "do_not_claim_major_breakthrough": True,
            "reason": "high_throughput_simulation_collects_internal_telemetry_but_does_not_replace_real_provider_evidence",
        },
        "boundary": dict(SIMULATION_LAB_BOUNDARY),
    }


def write_bionic_simulation_lab_artifacts(
    lab: dict[str, Any], output_path: str | Path
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_bionic_simulation_lab_html(lab), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(json.dumps(lab, ensure_ascii=False, indent=2), encoding="utf-8")
    png_path = html_path.with_name(f"{html_path.stem}_simulation_lab.png")
    _write_simulation_lab_png(lab, png_path)
    journal_path = html_path.with_name(f"{html_path.stem}_turns.jsonl")
    _write_turn_journal(lab, journal_path)
    return {
        "html": html_path,
        "json": json_path,
        "simulation_png": png_path,
        "turn_journal": journal_path,
    }


def render_bionic_simulation_lab_html(lab: dict[str, Any]) -> str:
    report = dict(lab or {})
    sim = _as_dict(report.get("simulation_set", {}))
    telemetry = _as_dict(report.get("internal_telemetry", {}))
    gate = _as_dict(report.get("evidence_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Holo Bionic Simulation Lab</title>
  <style>
    body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: #182026; background: #fbfbf8; }}
    header {{ padding: 24px 28px 10px; border-bottom: 1px solid #d7dddc; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 20px 24px 36px; }}
    section {{ margin: 22px 0 30px; }}
    h1 {{ margin: 0 0 8px; font-size: 24px; letter-spacing: 0; }}
    h2 {{ font-size: 17px; margin: 0 0 10px; }}
    .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(185px, 1fr)); gap: 10px; }}
    .metric {{ border: 1px solid #d7dddc; background: #f7f8f5; border-radius: 6px; padding: 10px 12px; }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d7dddc; margin: 10px 0; }}
    th, td {{ padding: 8px 9px; border-bottom: 1px solid #d7dddc; text-align: left; font-size: 12px; vertical-align: top; }}
    pre {{ overflow: auto; background: #172026; color: #e8f0ec; padding: 14px; border-radius: 6px; font-size: 12px; line-height: 1.45; }}
    .note {{ color: #5f6c72; font-size: 13px; margin: 0 0 14px; }}
    .warn {{ color: #8a4f00; font-weight: 700; }}
  </style>
</head>
<body>
  <header>
    <h1>Holo Bionic Simulation Lab</h1>
    <p class="note">High-throughput surrogate interactions for collecting Holo internal telemetry. These traces improve instrumentation and prioritization; they are not live provider evidence.</p>
  </header>
  <main>
    <section class="summary">
      {_metric("Scenarios", sim.get("scenario_count", 0))}
      {_metric("Turns / Scenario", sim.get("turns_per_scenario", 0))}
      {_metric("Total Turns", sim.get("total_simulated_turns", 0))}
      {_metric("Observed Tokens", telemetry.get("observed_total_tokens", 0))}
      {_metric("Cache Hit Ratio", telemetry.get("prompt_cache_hit_ratio", 0))}
      {_metric("Avg Latency", telemetry.get("average_latency_ms", 0))}
      {_metric("Tool Coverage", telemetry.get("tool_observation_coverage", 0))}
      {_metric("Backlog Items", len(report.get("improvement_backlog", []) or []))}
    </section>
    <section>
      <h2>Simulation Program</h2>
      {_run_table(report)}
    </section>
    <section>
      <h2>Internal Telemetry</h2>
      {_telemetry_table(telemetry)}
    </section>
    <section>
      <h2>Improvement Backlog</h2>
      {_backlog_table(report)}
    </section>
    <section>
      <h2>Evidence Gate</h2>
      <p class="warn">do_not_claim_real_manifold={_esc(gate.get("do_not_claim_real_manifold", True))}</p>
      {_gate_table(gate)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _generate_simulated_run(
    seed: dict[str, Any],
    program: dict[str, Any],
    *,
    scenario_index: int,
    turns: int,
) -> dict[str, Any]:
    seed_turns = [
        dict(turn)
        for turn in list(seed.get("turns", []) or [])
        if isinstance(turn, dict)
    ]
    if not seed_turns:
        seed_turns = [dict(turn) for turn in _fallback_seed_run()["turns"]]
    scenario_type = str(program.get("type", "") or "scenario")
    intensity = float(program.get("intensity", 0.0) or 0.0)
    score = max(0.0, min(1.0, float(program.get("score", 0.0) or 0.0)))
    seed_id = str(seed.get("run_id", "") or f"seed_{scenario_index}")
    fingerprint = hashlib.sha1(
        f"{seed_id}:{scenario_type}:{scenario_index}:{turns}".encode("utf-8")
    ).hexdigest()[:10]
    generated_turns = [
        _generate_turn(
            seed_turns[index % len(seed_turns)],
            index,
            scenario_type=scenario_type,
            intensity=intensity,
            primary_pressure=str(program.get("primary_pressure", "") or ""),
        )
        for index in range(turns)
    ]
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass" if score >= 0.9 else "fail",
        "run_id": f"stage61-{scenario_type}-{fingerprint}",
        "turns": generated_turns,
        "perturbation": {
            "type": scenario_type,
            "intensity": round(intensity, 4),
            "source": "stage61_high_throughput_simulation_program",
            "primary_pressure": str(program.get("primary_pressure", "") or ""),
        },
        "scorecard": {
            "overall_score": round(score, 4),
            "passed": bool(score >= 0.9),
            "surrogate_score": True,
        },
        "stage61_simulation": {
            "evidence_class": "surrogate_internal_telemetry_not_live_provider_evidence",
            "provider_evidence": False,
            "source_seed_run_id": seed_id,
            "turns": turns,
            "scenario_type": scenario_type,
        },
    }


def _generate_turn(
    seed_turn: dict[str, Any],
    index: int,
    *,
    scenario_type: str,
    intensity: float,
    primary_pressure: str,
) -> dict[str, Any]:
    values, surface_projection = _project_current_bionic_surfaces(
        _extract_turn_values(seed_turn),
        scenario_type=scenario_type,
        primary_pressure=primary_pressure,
        intensity=intensity,
    )
    phases = [
        "sensory_edge",
        "memory_reactivation",
        "goal_pressure",
        "uncertainty_monitor",
        "response_intention",
        "affective_tone",
        "integration",
    ]
    phase = phases[(index + len(scenario_type)) % len(phases)]
    slow = (math.sin(index / 9.0) + 1.0) / 2.0
    fast = (math.cos(index / 4.0) + 1.0) / 2.0
    drift = min(1.0, index / 480.0)
    cache_pressure = intensity if "cache" in scenario_type else intensity * 0.35
    memory_pressure = intensity if "memory" in scenario_type or "false_fact" in scenario_type else intensity * 0.28
    latency_pressure = intensity if "latency" in scenario_type or "false_fact" in scenario_type else intensity * 0.42
    tool_pressure = intensity if "tool" in scenario_type else 0.0
    boundary_pressure = intensity if "visual" in scenario_type else 0.0
    prefix = max(0, int(values["prefix"] * (1.0 - cache_pressure * 0.24) + drift * 80))
    residual_strength = _clamp01(
        values["residual_channel"] * (0.62 + min(6.0, values["residual_fast_line_count"]) * 0.06)
    )
    tool_scheduler_strength = _clamp01(
        values["tool_observation_scheduler"] * (0.58 + min(3.0, values["tool_observation_budget"]) * 0.1)
    )
    dynamic_delta_strength = _clamp01(
        values["dynamic_delta_frame"]
        * (
            0.45
            + min(900.0, values["dynamic_delta_saved_tokens"]) / 1800.0
            + min(6.0, values["dynamic_delta_compressed_handle_count"]) * 0.04
        )
    )
    dynamic = max(
        1,
        int(
            (
                values["dynamic"] * (1.0 + intensity * 0.56 + boundary_pressure * 0.22)
                + fast * 150
            )
            * (1.0 - residual_strength * 0.08 - dynamic_delta_strength * 0.14)
        ),
    )
    inheritance_gain = _clamp01(
        max(0.0, (values["prefix_share"] - 0.38) * 1.25)
        + values["cache_spine"] * 0.12
        + dynamic_delta_strength * 0.08
    )
    hit = max(
        0,
        int(
            values["hit"] * (1.0 - cache_pressure * 0.78)
            + slow * 220
            + drift * 55
            + inheritance_gain * 760
            + dynamic_delta_strength * 520
        ),
    )
    miss = max(
        1,
        int(
            (
                values["miss"] * (1.0 + cache_pressure * 0.82 + latency_pressure * 0.24)
                + fast * 260
            )
            * (1.0 - inheritance_gain * 0.3 - dynamic_delta_strength * 0.2)
        ),
    )
    completion = max(1, int(values["completion"] * (1.0 + intensity * 0.22) + index % 6))
    latency = max(
        1,
        int(
            (
                values["latency"] * (1.0 + latency_pressure * 0.74 + tool_pressure * 0.2)
                + slow * 720
            )
            * (1.0 - residual_strength * 0.14)
        ),
    )
    salience = _clamp01(values["salience"] * (1.0 - memory_pressure * 0.48) + slow * 0.09 + residual_strength * 0.035)
    recall = max(
        1,
        int(round(values["recall"] * (1.0 - memory_pressure * 0.58) + slow * 1.2 + residual_strength * 0.45)),
    )
    context_lines = max(2, int(round(values["context_lines"] * (1.0 - memory_pressure * 0.35 + boundary_pressure * 0.16) + fast * 2.2)))
    saved_lines = max(1, int(round(values["saved_lines"] * (1.0 - intensity * 0.2) + slow)))
    priority = _clamp01(values["priority"] * (1.0 - memory_pressure * 0.38) + fast * 0.07)
    tool_needed = "tool" in scenario_type
    tool_observed = tool_needed and (index % 4 != 1 if tool_scheduler_strength > 0 else index % 3 == 0)
    residual_boundary_guard = "visual" in scenario_type and residual_strength >= 0.72
    visual_interval = 23 if residual_strength > 0 else 11
    commitment_interval = 29 if residual_strength > 0 else 13
    visual_overclaim = (
        "visual" in scenario_type
        and not residual_boundary_guard
        and index % visual_interval == 0
    )
    commitment_unbound = (
        "visual" in scenario_type
        and not residual_boundary_guard
        and index % commitment_interval == 0
    )
    return {
        "turn_id": f"{scenario_type}_{index + 1:05d}",
        "user_text": _simulated_user_text(scenario_type, index),
        "response_text": _simulated_response_text(scenario_type, index),
        "latency_ms": latency,
        "selected_action": {
            "action_type": "tool_observe" if tool_observed else "reply",
            "score": round(0.72 + (1.0 - intensity) * 0.18 + slow * 0.05, 4),
            "send_allowed": True,
        },
        "grounding_guard": {
            "visual_overclaim_rewritten": not visual_overclaim,
            "prospective_commitment_bound": not commitment_unbound,
            "prospective_commitment_failed": commitment_unbound,
        },
        "processor_usage": {
            "prompt_tokens": hit + miss,
            "completion_tokens": completion,
            "total_tokens": hit + miss + completion,
            "prompt_cache_hit_tokens": hit,
            "prompt_cache_miss_tokens": miss,
            "prompt_cache_hit_ratio": round(hit / max(1, hit + miss), 6),
        },
        "processor_debug": {
            "prompt_partition": {
                "provider_cache_prefix_tokens": prefix,
                "provider_cache_dynamic_tokens": dynamic,
            },
            "bionic_memory_schedule": {
                "salience_score": round(salience, 4),
                "recall_budget": recall,
                "dynamic_context_line_count": context_lines,
                "dynamic_fusion_saved_line_count": saved_lines,
                "dynamic_delta_frame_mode": values["dynamic_delta_frame_mode"],
                "dynamic_delta_saved_tokens": int(values["dynamic_delta_saved_tokens"]),
                "dynamic_delta_compressed_handle_count": int(values["dynamic_delta_compressed_handle_count"]),
                "dynamic_delta_strength": round(dynamic_delta_strength, 6),
                "cache_inheritance_mode": values["cache_inheritance_mode"],
                "cache_inheritance_gain": round(inheritance_gain, 6),
                "residual_channel_mode": values["residual_channel_mode"],
                "residual_channel_fast_line_count": int(values["residual_fast_line_count"]),
                "residual_channel_fast_tokens": int(values["residual_fast_tokens"]),
                "residual_channel_strength": round(residual_strength, 6),
                "tool_observation_scheduler_mode": values["tool_observation_scheduler_mode"],
                "tool_observation_needed": bool(values["tool_observation_scheduler"] > 0),
                "tool_observation_budget": int(values["tool_observation_budget"]),
                "tool_observation_scheduler_strength": round(tool_scheduler_strength, 6),
                "surrogate_current_surface_projection": surface_projection,
                "surrogate_current_surface_projection_only": bool(surface_projection),
            },
            "bionic_memory_lifecycle": {
                "consolidation_priority": round(priority, 4),
                "self_memory_write": False,
            },
            "bionic_consciousness_flow": {
                "dominant_phase": phase,
                "phase_count": 6,
                "user_visible": False,
            },
            "tool_observation": {
                "needed": tool_needed,
                "observed": tool_observed,
                "primary_pressure": primary_pressure,
            },
        },
    }


def _build_internal_telemetry(runs: list[dict[str, Any]]) -> dict[str, Any]:
    turns = _all_turns(runs)
    token_total = 0
    hit_total = 0
    miss_total = 0
    latencies: list[float] = []
    saliences: list[float] = []
    recalls: list[float] = []
    context_lines: list[float] = []
    saved_lines: list[float] = []
    residual_fast_lines: list[float] = []
    residual_strengths: list[float] = []
    tool_scheduler_strengths: list[float] = []
    dynamic_delta_saved_tokens: list[float] = []
    dynamic_delta_strengths: list[float] = []
    priorities: list[float] = []
    prefix_tokens: list[float] = []
    dynamic_tokens: list[float] = []
    phases: dict[str, int] = {}
    tool_needed = 0
    tool_observed = 0
    visual_rewrite_failures = 0
    commitment_failures = 0
    for turn in turns:
        usage = _as_dict(turn.get("processor_usage", {}))
        debug = _as_dict(turn.get("processor_debug", {}))
        partition = _as_dict(debug.get("prompt_partition", {}))
        schedule = _as_dict(debug.get("bionic_memory_schedule", {}))
        lifecycle = _as_dict(debug.get("bionic_memory_lifecycle", {}))
        flow = _as_dict(debug.get("bionic_consciousness_flow", {}))
        tool = _as_dict(debug.get("tool_observation", {}))
        guard = _as_dict(turn.get("grounding_guard", {}))
        token_total += int(usage.get("total_tokens", 0) or 0)
        hit_total += int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        miss_total += int(usage.get("prompt_cache_miss_tokens", 0) or 0)
        latencies.append(_num(turn.get("latency_ms"), 0.0))
        saliences.append(_num(schedule.get("salience_score"), 0.0))
        recalls.append(_num(schedule.get("recall_budget"), 0.0))
        context_lines.append(_num(schedule.get("dynamic_context_line_count"), 0.0))
        saved_lines.append(_num(schedule.get("dynamic_fusion_saved_line_count"), 0.0))
        residual_fast_lines.append(_num(schedule.get("residual_channel_fast_line_count"), 0.0))
        residual_strengths.append(_num(schedule.get("residual_channel_strength"), 0.0))
        tool_scheduler_strengths.append(_num(schedule.get("tool_observation_scheduler_strength"), 0.0))
        dynamic_delta_saved_tokens.append(_num(schedule.get("dynamic_delta_saved_tokens"), 0.0))
        dynamic_delta_strengths.append(_num(schedule.get("dynamic_delta_strength"), 0.0))
        priorities.append(_num(lifecycle.get("consolidation_priority"), 0.0))
        prefix_tokens.append(_num(partition.get("provider_cache_prefix_tokens"), 0.0))
        dynamic_tokens.append(_num(partition.get("provider_cache_dynamic_tokens"), 0.0))
        phase = str(flow.get("dominant_phase", "") or "unknown")
        phases[phase] = phases.get(phase, 0) + 1
        if bool(tool.get("needed", False)):
            tool_needed += 1
            if bool(tool.get("observed", False)):
                tool_observed += 1
        if not bool(guard.get("visual_overclaim_rewritten", True)):
            visual_rewrite_failures += 1
        if bool(guard.get("prospective_commitment_failed", False)):
            commitment_failures += 1
    phase_entropy = _normalized_entropy(list(phases.values()))
    return {
        "turn_count": len(turns),
        "observed_total_tokens": token_total,
        "prompt_cache_hit_tokens": hit_total,
        "prompt_cache_miss_tokens": miss_total,
        "prompt_cache_hit_ratio": round(hit_total / max(1, hit_total + miss_total), 6),
        "average_latency_ms": round(_mean(latencies), 2),
        "p95_latency_ms": round(_percentile(latencies, 0.95), 2),
        "average_salience_score": round(_mean(saliences), 4),
        "average_recall_budget": round(_mean(recalls), 4),
        "average_dynamic_context_lines": round(_mean(context_lines), 4),
        "average_dynamic_fusion_saved_lines": round(_mean(saved_lines), 4),
        "average_residual_channel_fast_lines": round(_mean(residual_fast_lines), 4),
        "average_residual_channel_strength": round(_mean(residual_strengths), 6),
        "average_tool_observation_scheduler_strength": round(_mean(tool_scheduler_strengths), 6),
        "average_dynamic_delta_saved_tokens": round(_mean(dynamic_delta_saved_tokens), 4),
        "average_dynamic_delta_strength": round(_mean(dynamic_delta_strengths), 6),
        "average_consolidation_priority": round(_mean(priorities), 4),
        "average_provider_cache_prefix_tokens": round(_mean(prefix_tokens), 2),
        "average_provider_cache_dynamic_tokens": round(_mean(dynamic_tokens), 2),
        "phase_distribution": dict(sorted(phases.items())),
        "phase_entropy": round(phase_entropy, 6),
        "tool_pressure_turn_count": tool_needed,
        "tool_observation_count": tool_observed,
        "tool_observation_coverage": round(tool_observed / max(1, tool_needed), 6),
        "visual_rewrite_failure_count": visual_rewrite_failures,
        "commitment_failure_count": commitment_failures,
    }


def _build_improvement_backlog(
    telemetry: dict[str, Any],
    calibration: dict[str, Any],
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    backlog: list[dict[str, Any]] = []
    cache_ratio = float(telemetry.get("prompt_cache_hit_ratio", 0.0) or 0.0)
    if cache_ratio < 0.35:
        backlog.append(
            _backlog_item(
                key="cache_inheritance_low",
                severity="high",
                target="context_scheduler / processor prompt partition",
                evidence=f"prompt_cache_hit_ratio={cache_ratio}",
                recommendation="Increase stable-prefix reuse and move volatile recall into compact dynamic memory frames.",
            )
        )
    p95_latency = float(telemetry.get("p95_latency_ms", 0.0) or 0.0)
    if p95_latency > 8000:
        backlog.append(
            _backlog_item(
                key="latency_tail_high",
                severity="medium",
                target="residual fast channel / lane routing",
                evidence=f"p95_latency_ms={p95_latency}",
                recommendation="Route boundary clarification and continuity repair through a smaller residual fast lane before full deliberation.",
            )
        )
    if float(telemetry.get("average_recall_budget", 0.0) or 0.0) < 2.5:
        backlog.append(
            _backlog_item(
                key="recall_budget_too_thin_under_perturbation",
                severity="medium",
                target="bionic_memory_scheduler",
                evidence=f"average_recall_budget={telemetry.get('average_recall_budget', 0)}",
                recommendation="Raise recall floor for correction, false-fact, and commitment-boundary turns.",
            )
        )
    if float(telemetry.get("phase_entropy", 0.0) or 0.0) < 0.78:
        backlog.append(
            _backlog_item(
                key="consciousness_flow_phase_coverage_low",
                severity="medium",
                target="bionic_consciousness_flow",
                evidence=f"phase_entropy={telemetry.get('phase_entropy', 0)}",
                recommendation="Expose more diverse internal phase transitions in debug telemetry so geometry analysis is not dominated by one phase.",
            )
        )
    if float(telemetry.get("tool_observation_coverage", 1.0) or 0.0) < 0.5:
        backlog.append(
            _backlog_item(
                key="tool_observation_coverage_low",
                severity="medium",
                target="upstream MCP observation policy",
                evidence=(
                    f"tool_observation_count={telemetry.get('tool_observation_count', 0)} "
                    f"tool_pressure_turn_count={telemetry.get('tool_pressure_turn_count', 0)}"
                ),
                recommendation="Improve bounded tool-observation selection for tool-pressure turns without granting tools decision authority.",
            )
        )
    if int(telemetry.get("visual_rewrite_failure_count", 0) or 0) > 0:
        backlog.append(
            _backlog_item(
                key="visual_boundary_rewrite_gap",
                severity="high",
                target="grounding guard",
                evidence=f"visual_rewrite_failure_count={telemetry.get('visual_rewrite_failure_count', 0)}",
                recommendation="Keep visual honesty rewrites on the residual path before response shaping.",
            )
        )
    if int(telemetry.get("commitment_failure_count", 0) or 0) > 0:
        backlog.append(
            _backlog_item(
                key="commitment_binding_gap",
                severity="high",
                target="temporal commitments / grounding guard",
                evidence=f"commitment_failure_count={telemetry.get('commitment_failure_count', 0)}",
                recommendation="Require explicit commitment bind evidence before any reminder-like wording reaches the final response.",
            )
        )
    trace_depth = _as_dict(calibration.get("trace_depth", {}))
    if int(trace_depth.get("longest_trace_points", 0) or 0) < 48:
        backlog.append(
            _backlog_item(
                key="trace_depth_below_geometry_floor",
                severity="low",
                target="simulation campaign sizing",
                evidence=f"longest_trace_points={trace_depth.get('longest_trace_points', 0)}",
                recommendation="Use at least 48 turns per scenario for geometry calibration runs.",
            )
        )
    if not backlog:
        backlog.append(
            _backlog_item(
                key="no_blocking_simulation_deficit",
                severity="info",
                target="operator review",
                evidence=f"scenario_count={len(runs)} turn_count={telemetry.get('turn_count', 0)}",
                recommendation="Move from surrogate simulation to budget-approved Stage60 real-provider trace collection.",
            )
        )
    return backlog


def _backlog_item(
    *,
    key: str,
    severity: str,
    target: str,
    evidence: str,
    recommendation: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "severity": severity,
        "target": target,
        "evidence": evidence,
        "recommendation": recommendation,
        "auto_apply": False,
    }


def _write_turn_journal(lab: dict[str, Any], journal_path: Path) -> None:
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("w", encoding="utf-8") as handle:
        for run in list(lab.get("stage46_compatible_runs", []) or []):
            if not isinstance(run, dict):
                continue
            run_id = str(run.get("run_id", "") or "")
            scenario = _as_dict(run.get("perturbation", {}))
            for index, turn in enumerate(list(run.get("turns", []) or [])):
                if not isinstance(turn, dict):
                    continue
                handle.write(
                    json.dumps(
                        {
                            "stage": STAGE61_NAME,
                            "run_id": run_id,
                            "scenario_type": scenario.get("type", ""),
                            "turn_index": index,
                            "turn": turn,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


def _write_simulation_lab_png(lab: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    runs = [
        dict(run)
        for run in list(lab.get("generated_runs", []) or [])
        if isinstance(run, dict)
    ]
    telemetry = _as_dict(lab.get("internal_telemetry", {}))
    labels = [str(run.get("scenario_type", "") or f"run {index + 1}") for index, run in enumerate(runs)]
    scores = numpy.array([float(run.get("overall_score", 0.0) or 0.0) for run in runs], dtype=float)
    tokens = numpy.array([float(run.get("total_tokens", 0) or 0) for run in runs], dtype=float)
    cache = numpy.array([float(run.get("prompt_cache_hit_ratio", 0.0) or 0.0) for run in runs], dtype=float)
    fig, axes = pyplot.subplots(1, 3, figsize=(16, 5.5), dpi=150)
    x = numpy.arange(len(labels))
    if len(labels):
        axes[0].bar(x, scores, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
        axes[1].bar(x, tokens, color="#b88424", edgecolor="#172026", linewidth=0.8)
        axes[2].plot(x, cache, marker="o", color="#5e7fa7", linewidth=2)
    for axis in axes:
        axis.set_xticks(x)
        axis.set_xticklabels(labels, rotation=35, ha="right")
        axis.grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)
    axes[0].set_ylim(0.0, 1.05)
    axes[0].set_title("Scenario Stability Score")
    axes[1].set_title("Simulated Internal Tokens")
    axes[2].set_ylim(0.0, 1.05)
    axes[2].set_title("Cache Hit Ratio")
    fig.suptitle(
        "Stage61 High-Throughput Bionic Simulation | "
        f"turns={telemetry.get('turn_count', 0)} | "
        f"cache={telemetry.get('prompt_cache_hit_ratio', 0)} | "
        f"backlog={len(lab.get('improvement_backlog', []) or [])}",
        fontsize=13,
        y=0.99,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _compact_run(run: dict[str, Any]) -> dict[str, Any]:
    turns = [dict(turn) for turn in list(run.get("turns", []) or []) if isinstance(turn, dict)]
    scorecard = _as_dict(run.get("scorecard", {}))
    perturbation = _as_dict(run.get("perturbation", {}))
    total_tokens = 0
    hit = 0
    miss = 0
    for turn in turns:
        usage = _as_dict(turn.get("processor_usage", {}))
        total_tokens += int(usage.get("total_tokens", 0) or 0)
        hit += int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        miss += int(usage.get("prompt_cache_miss_tokens", 0) or 0)
    return {
        "run_id": str(run.get("run_id", "") or ""),
        "status": str(run.get("status", "") or ""),
        "scenario_type": str(perturbation.get("type", "") or ""),
        "primary_pressure": str(perturbation.get("primary_pressure", "") or ""),
        "turn_count": len(turns),
        "overall_score": float(scorecard.get("overall_score", 0.0) or 0.0),
        "total_tokens": total_tokens,
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "prompt_cache_hit_ratio": round(hit / max(1, hit + miss), 6),
    }


def _all_turns(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(turn)
        for run in runs
        for turn in list(run.get("turns", []) or [])
        if isinstance(turn, dict)
    ]


def _extract_turn_values(turn: dict[str, Any]) -> dict[str, float]:
    debug = _as_dict(turn.get("processor_debug", {}))
    usage = _as_dict(turn.get("processor_usage", {}))
    partition = _as_dict(debug.get("prompt_partition", {}))
    context_schedule = _as_dict(debug.get("context_schedule", {}))
    schedule = _as_dict(debug.get("bionic_memory_schedule", {}))
    lifecycle = _as_dict(debug.get("bionic_memory_lifecycle", {}))
    cache_inheritance = _as_dict(schedule.get("cache_inheritance", {}))
    residual_channel = _as_dict(schedule.get("residual_working_channel", {}))
    tool_scheduler = _as_dict(schedule.get("tool_observation_scheduler", {}))
    dynamic_delta = _as_dict(schedule.get("dynamic_delta_frame", {}))
    cache_inheritance_mode = str(
        schedule.get("cache_inheritance_mode", "")
        or cache_inheritance.get("mode", "")
        or ""
    )
    residual_channel_mode = str(
        schedule.get("residual_channel_mode", "")
        or residual_channel.get("mode", "")
        or ""
    )
    prefix = _num(
        partition.get("provider_cache_prefix_tokens")
        or context_schedule.get("provider_cache_prefix_tokens"),
        680.0,
    )
    dynamic = _num(
        partition.get("provider_cache_dynamic_tokens")
        or context_schedule.get("provider_cache_dynamic_tokens"),
        1080.0,
    )
    residual_fast_line_count = _num(
        schedule.get("residual_channel_fast_line_count")
        or residual_channel.get("fast_line_count"),
        0.0,
    )
    residual_fast_tokens = _num(
        schedule.get("residual_channel_fast_tokens")
        or residual_channel.get("fast_tokens"),
        0.0,
    )
    residual_active = (
        residual_channel_mode == RESIDUAL_WORKING_CHANNEL_MODE
        and residual_fast_line_count > 0.0
    )
    tool_scheduler_mode = str(
        schedule.get("tool_observation_scheduler_mode", "")
        or tool_scheduler.get("mode", "")
        or ""
    )
    tool_budget = _num(
        schedule.get("tool_observation_budget")
        or tool_scheduler.get("observation_budget"),
        0.0,
    )
    tool_scheduler_active = (
        tool_scheduler_mode == TOOL_OBSERVATION_MODE
        and bool(schedule.get("tool_observation_needed", tool_scheduler.get("needed", False)))
        and tool_budget > 0.0
    )
    dynamic_delta_mode = str(
        schedule.get("dynamic_delta_frame_mode", "")
        or dynamic_delta.get("mode", "")
        or ""
    )
    dynamic_delta_saved_tokens = _num(
        schedule.get("dynamic_delta_saved_tokens")
        or dynamic_delta.get("estimated_saved_tokens"),
        0.0,
    )
    dynamic_delta_compressed_handle_count = _num(
        schedule.get("dynamic_delta_compressed_handle_count")
        or dynamic_delta.get("compressed_handle_count"),
        0.0,
    )
    dynamic_delta_active = (
        dynamic_delta_mode == DYNAMIC_DELTA_FRAME_MODE
        and dynamic_delta_compressed_handle_count > 0.0
        and dynamic_delta_saved_tokens > 0.0
    )
    return {
        "schedule_mode": str(schedule.get("mode", "") or ""),
        "hit": _num(usage.get("prompt_cache_hit_tokens"), 220.0),
        "miss": _num(usage.get("prompt_cache_miss_tokens"), 1400.0),
        "completion": _num(usage.get("completion_tokens"), 28.0),
        "latency": _num(turn.get("latency_ms"), 4800.0),
        "prefix": prefix,
        "dynamic": dynamic,
        "prefix_share": prefix / max(1.0, prefix + dynamic),
        "cache_spine": 1.0 if cache_inheritance_mode == CACHE_INHERITANCE_MODE else 0.0,
        "cache_inheritance_mode": cache_inheritance_mode,
        "residual_channel": 1.0 if residual_active else 0.0,
        "residual_channel_mode": residual_channel_mode,
        "residual_fast_line_count": residual_fast_line_count,
        "residual_fast_tokens": residual_fast_tokens,
        "tool_observation_scheduler": 1.0 if tool_scheduler_active else 0.0,
        "tool_observation_scheduler_mode": tool_scheduler_mode,
        "tool_observation_budget": tool_budget,
        "dynamic_delta_frame": 1.0 if dynamic_delta_active else 0.0,
        "dynamic_delta_frame_mode": dynamic_delta_mode,
        "dynamic_delta_saved_tokens": dynamic_delta_saved_tokens,
        "dynamic_delta_compressed_handle_count": dynamic_delta_compressed_handle_count,
        "salience": _num(schedule.get("salience_score"), 0.42),
        "recall": _num(schedule.get("recall_budget"), 2.0),
        "context_lines": _num(schedule.get("dynamic_context_line_count"), 7.0),
        "saved_lines": _num(schedule.get("dynamic_fusion_saved_line_count"), 3.0),
        "priority": _num(lifecycle.get("consolidation_priority"), 0.38),
    }


def _project_current_bionic_surfaces(
    values: dict[str, Any],
    *,
    scenario_type: str,
    primary_pressure: str,
    intensity: float,
) -> tuple[dict[str, Any], list[str]]:
    projected = dict(values)
    if str(projected.get("schedule_mode", "") or "") != "biomimetic_v1":
        return projected, []

    reasons: list[str] = []
    pressure = f"{scenario_type} {primary_pressure}".lower()
    if not projected.get("cache_inheritance_mode"):
        projected["cache_inheritance_mode"] = CACHE_INHERITANCE_MODE
        projected["cache_spine"] = 1.0
        reasons.append("cache_spine")

    if (
        not projected.get("dynamic_delta_frame_mode")
        or float(projected.get("dynamic_delta_saved_tokens", 0.0) or 0.0) < 180.0
        or float(projected.get("dynamic_delta_compressed_handle_count", 0.0) or 0.0) < 2.0
    ):
        projected["dynamic_delta_frame_mode"] = DYNAMIC_DELTA_FRAME_MODE
        projected["dynamic_delta_saved_tokens"] = max(
            float(projected.get("dynamic_delta_saved_tokens", 0.0) or 0.0),
            520.0 + intensity * 260.0,
        )
        projected["dynamic_delta_compressed_handle_count"] = max(
            float(projected.get("dynamic_delta_compressed_handle_count", 0.0) or 0.0),
            4.0,
        )
        projected["dynamic_delta_frame"] = 1.0
        reasons.append("dynamic_delta_frame")

    if float(projected.get("recall", 0.0) or 0.0) < 5.6:
        projected["recall"] = 5.6
        projected["salience"] = max(float(projected.get("salience", 0.0) or 0.0), 0.62)
        reasons.append("memory_resilience_floor")

    residual_pressure = any(
        marker in pressure
        for marker in (
            "residual",
            "latency",
            "visual",
            "commitment",
            "false_fact",
            "belief_revision",
            "memory_drop",
            "grounding",
        )
    )
    if residual_pressure and float(projected.get("residual_fast_line_count", 0.0) or 0.0) <= 0.0:
        projected["residual_channel_mode"] = RESIDUAL_WORKING_CHANNEL_MODE
        projected["residual_fast_line_count"] = 4.0
        projected["residual_fast_tokens"] = 84.0
        projected["residual_channel"] = 1.0
        reasons.append("residual_working_channel")

    tool_pressure = "tool" in pressure or "bounded_tool_observation" in pressure
    if tool_pressure and float(projected.get("tool_observation_budget", 0.0) or 0.0) <= 0.0:
        projected["tool_observation_scheduler_mode"] = TOOL_OBSERVATION_MODE
        projected["tool_observation_budget"] = 2.0
        projected["tool_observation_scheduler"] = 1.0
        reasons.append("tool_observation_scheduler")

    return projected, sorted(set(reasons))


def _fallback_seed_run() -> dict[str, Any]:
    turns = []
    for index in range(9):
        wave = abs((index % 7) - 3) / 3
        turns.append(
            {
                "turn_id": f"stage61_fallback_{index + 1}",
                "latency_ms": int(4300 + wave * 1700),
                "processor_usage": {
                    "prompt_tokens": int(1480 + wave * 560),
                    "completion_tokens": 28,
                    "total_tokens": int(1508 + wave * 560),
                    "prompt_cache_hit_tokens": int(240 + (1.0 - wave) * 190),
                    "prompt_cache_miss_tokens": int(1160 + wave * 540),
                },
                "processor_debug": {
                    "prompt_partition": {
                        "provider_cache_prefix_tokens": int(690 + index * 12),
                        "provider_cache_dynamic_tokens": int(1020 + wave * 450),
                    },
                    "bionic_memory_schedule": {
                        "salience_score": max(0.05, min(1.0, 0.34 + (1.0 - wave) * 0.44)),
                        "recall_budget": max(1, int(1 + (1.0 - wave) * 4)),
                        "dynamic_context_line_count": max(4, int(5 + (1.0 - wave) * 8)),
                        "dynamic_fusion_saved_line_count": max(2, int(3 + (1.0 - wave) * 4)),
                    },
                    "bionic_memory_lifecycle": {
                        "consolidation_priority": max(0.05, min(1.0, 0.25 + (1.0 - wave) * 0.5))
                    },
                    "bionic_consciousness_flow": {
                        "dominant_phase": "memory_reactivation",
                        "phase_count": 6,
                        "user_visible": False,
                    },
                },
            }
        )
    return {
        "stage": STAGE46_NAME,
        "suite": DEFAULT_STAGE46_SUITE,
        "status": "pass",
        "run_id": "stage61-fallback-seed",
        "turns": turns,
        "scorecard": {"overall_score": 0.96, "passed": True},
    }


def _simulated_user_text(scenario_type: str, index: int) -> str:
    return (
        f"[Stage61 scenario={scenario_type} turn={index + 1}] "
        "Continue the casual bionic dialogue while preserving correction, grounding, and bounded tool evidence."
    )


def _simulated_response_text(scenario_type: str, index: int) -> str:
    return (
        f"simulated response {index + 1} for {scenario_type}: "
        "keeps continuity, reports boundary honestly, and avoids claiming hidden actions."
    )


def _run_table(report: dict[str, Any]) -> str:
    rows = [
        "<table><tr><th>run</th><th>scenario</th><th>turns</th><th>score</th><th>tokens</th><th>cache hit</th></tr>"
    ]
    for run in list(report.get("generated_runs", []) or []):
        if not isinstance(run, dict):
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(run.get('run_id', ''))}</td>"
            f"<td>{_esc(run.get('scenario_type', ''))}</td>"
            f"<td>{_esc(run.get('turn_count', 0))}</td>"
            f"<td>{_esc(run.get('overall_score', 0))}</td>"
            f"<td>{_esc(run.get('total_tokens', 0))}</td>"
            f"<td>{_esc(run.get('prompt_cache_hit_ratio', 0))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _telemetry_table(telemetry: dict[str, Any]) -> str:
    keys = (
        "turn_count",
        "observed_total_tokens",
        "prompt_cache_hit_ratio",
        "average_latency_ms",
        "p95_latency_ms",
        "average_recall_budget",
        "average_dynamic_context_lines",
        "average_dynamic_delta_saved_tokens",
        "average_dynamic_delta_strength",
        "average_consolidation_priority",
        "phase_entropy",
        "tool_observation_coverage",
        "visual_rewrite_failure_count",
        "commitment_failure_count",
    )
    rows = ["<table><tr><th>metric</th><th>value</th></tr>"]
    for key in keys:
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(telemetry.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _backlog_table(report: dict[str, Any]) -> str:
    items = [
        dict(item)
        for item in list(report.get("improvement_backlog", []) or [])
        if isinstance(item, dict)
    ]
    rows = [
        "<table><tr><th>severity</th><th>key</th><th>target</th><th>evidence</th><th>recommendation</th></tr>"
    ]
    for item in items:
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('severity', ''))}</td>"
            f"<td>{_esc(item.get('key', ''))}</td>"
            f"<td>{_esc(item.get('target', ''))}</td>"
            f"<td>{_esc(item.get('evidence', ''))}</td>"
            f"<td>{_esc(item.get('recommendation', ''))}</td>"
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
        "reason",
    ):
        rows.append(f"<tr><td>{_esc(key)}</td><td>{_esc(gate.get(key, ''))}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    calibration = _as_dict(report.get("stage57_calibration", {}))
    return {
        "stage": report.get("stage", ""),
        "simulation_set": report.get("simulation_set", {}),
        "generated_runs": report.get("generated_runs", []),
        "internal_telemetry": report.get("internal_telemetry", {}),
        "stage57_calibration": {
            "trace_set": calibration.get("trace_set", {}),
            "trace_depth": calibration.get("trace_depth", {}),
            "predictive_probe": calibration.get("predictive_probe", {}),
            "evidence_gate": calibration.get("evidence_gate", {}),
        },
        "improvement_backlog": report.get("improvement_backlog", []),
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
            "Stage61 bionic simulation lab PNG export requires matplotlib and numpy"
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
    values = [float(value) for value in values if math.isfinite(float(value))]
    if not values:
        return default
    return sum(values) / len(values)


def _percentile(values: list[float], quantile: float) -> float:
    clean = sorted(float(value) for value in values if math.isfinite(float(value)))
    if not clean:
        return 0.0
    position = max(0, min(len(clean) - 1, int(round((len(clean) - 1) * quantile))))
    return clean[position]


def _normalized_entropy(counts: list[int]) -> float:
    total = sum(max(0, int(count)) for count in counts)
    nonzero = [max(0, int(count)) for count in counts if int(count) > 0]
    if total <= 0 or len(nonzero) <= 1:
        return 0.0
    entropy = 0.0
    for count in nonzero:
        probability = count / total
        entropy -= probability * math.log(probability)
    return entropy / math.log(len(nonzero))


def _clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value or 0.0)))


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)
