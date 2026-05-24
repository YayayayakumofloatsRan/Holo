from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .common import atomic_write_text, stable_digest, utc_now
from .stage121_conscious_packet_scheduler import build_stage121_packet_policy
from .stage132_progressive_conscious_stream import plan_stage132_progressive_stream

STAGE133_SCHEMA = "holo.stage133.core_problem_research_loop.v1"
DEFAULT_OUTPUT_DIR = Path("artifacts") / "stage133"

CORE_PROBLEM = (
    "When an LLM already has strong language-processing ability, what outer "
    "cognitive architecture can organize finite provider calls into a continuous, "
    "memorable, actionable, self-correcting, observable human-like mind process?"
)

SUBPROBLEMS: list[dict[str, Any]] = [
    {
        "id": "state_representation",
        "question": "How should Holo represent the current state across turn context, working memory, durable memory, affect, visual observation, tool results, and commitments?",
        "probes": [
            {"label": "thread_state_fusion", "memory": 0.62, "working": 0.76, "affect": 0.42, "tool": 0.12, "visual": 0.16, "uncertainty": 0.52, "risk": 0.18, "feedback": 0.35},
            {"label": "ambiguous_current_state", "memory": 0.48, "working": 0.58, "affect": 0.5, "tool": 0.18, "visual": 0.25, "uncertainty": 0.72, "risk": 0.22, "feedback": 0.28},
        ],
    },
    {
        "id": "packet_scheduling",
        "question": "How should Holo decide packet length, model tier, cache-stable prefix, continuation, and stop timing?",
        "probes": [
            {"label": "long_context_research_turn", "memory": 0.54, "working": 0.68, "affect": 0.36, "tool": 0.3, "visual": 0.08, "uncertainty": 0.82, "risk": 0.24, "feedback": 0.3},
            {"label": "brief_ack_low_pressure", "memory": 0.16, "working": 0.28, "affect": 0.24, "tool": 0.0, "visual": 0.0, "uncertainty": 0.12, "risk": 0.05, "feedback": 0.1},
        ],
    },
    {
        "id": "memory_coordination",
        "question": "How should short-term working memory and long-term memory cooperate without losing the user's immediate constraints?",
        "probes": [
            {"label": "recent_constraint_recall", "memory": 0.64, "working": 0.88, "affect": 0.32, "tool": 0.18, "visual": 0.05, "uncertainty": 0.56, "risk": 0.18, "feedback": 0.62},
            {"label": "deep_origin_recall", "memory": 0.86, "working": 0.52, "affect": 0.45, "tool": 0.18, "visual": 0.04, "uncertainty": 0.69, "risk": 0.25, "feedback": 0.44},
        ],
    },
    {
        "id": "action_loop",
        "question": "How should tools, file reads, command execution, visual observation, and memory writes re-enter the same cognitive loop?",
        "probes": [
            {"label": "readonly_workspace_check", "memory": 0.34, "working": 0.62, "affect": 0.3, "tool": 0.78, "visual": 0.0, "uncertainty": 0.66, "risk": 0.28, "feedback": 0.4},
            {"label": "camera_scene_delta", "memory": 0.42, "working": 0.5, "affect": 0.34, "tool": 0.52, "visual": 0.82, "uncertainty": 0.7, "risk": 0.36, "feedback": 0.32},
        ],
    },
    {
        "id": "expression_stream",
        "question": "How should visible A-prime, A-double-prime, and later segments be emitted only when they add semantic function?",
        "probes": [
            {"label": "fast_then_deep_needed", "memory": 0.5, "working": 0.7, "affect": 0.44, "tool": 0.15, "visual": 0.06, "uncertainty": 0.74, "risk": 0.18, "feedback": 0.38},
            {"label": "suppress_duplicate_followup", "memory": 0.18, "working": 0.28, "affect": 0.18, "tool": 0.0, "visual": 0.0, "uncertainty": 0.16, "risk": 0.04, "feedback": 0.2},
        ],
    },
    {
        "id": "learning_feedback",
        "question": "How should corrections, failures, tool errors, and memory conflicts sediment into reaction-kernel parameters and scheduling policy?",
        "probes": [
            {"label": "operator_style_correction", "memory": 0.46, "working": 0.82, "affect": 0.52, "tool": 0.08, "visual": 0.0, "uncertainty": 0.42, "risk": 0.2, "feedback": 0.9},
            {"label": "memory_conflict_repair", "memory": 0.8, "working": 0.72, "affect": 0.48, "tool": 0.32, "visual": 0.0, "uncertainty": 0.78, "risk": 0.42, "feedback": 0.86},
        ],
    },
    {
        "id": "observability",
        "question": "How should researchers see state motion, semantic vectors, memory activation, tool loops, and continuation gates in real time?",
        "probes": [
            {"label": "ct_trace_request", "memory": 0.56, "working": 0.64, "affect": 0.38, "tool": 0.4, "visual": 0.35, "uncertainty": 0.64, "risk": 0.18, "feedback": 0.48},
            {"label": "replayable_ablation_frame", "memory": 0.44, "working": 0.5, "affect": 0.3, "tool": 0.34, "visual": 0.28, "uncertainty": 0.58, "risk": 0.14, "feedback": 0.52},
        ],
    },
]


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        current = float(value)
    except (TypeError, ValueError):
        current = 0.0
    return max(low, min(high, current))


def _mean(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _state_values(probe: dict[str, Any]) -> dict[str, float]:
    memory = _clamp(probe.get("memory"))
    working = _clamp(probe.get("working"))
    affect = _clamp(probe.get("affect"))
    tool = _clamp(probe.get("tool"))
    visual = _clamp(probe.get("visual"))
    uncertainty = _clamp(probe.get("uncertainty"))
    risk = _clamp(probe.get("risk"))
    feedback = _clamp(probe.get("feedback"))
    return {
        "state_pressure": round(working * 0.32 + memory * 0.24 + affect * 0.14 + uncertainty * 0.2 + risk * 0.1, 4),
        "working_memory": working,
        "long_memory": memory,
        "affect": affect,
        "tool_need": tool,
        "visual_need": visual,
        "uncertainty": uncertainty,
        "risk": risk,
        "feedback_pressure": feedback,
        "observability_need": round(max(visual, tool * 0.6, uncertainty * 0.72, feedback * 0.7), 4),
    }


def _projection(values: dict[str, float]) -> dict[str, float]:
    return {
        "x": round(_clamp(values["long_memory"] * 0.42 + values["working_memory"] * 0.24 + values["feedback_pressure"] * 0.18), 4),
        "y": round(_clamp(values["uncertainty"] * 0.34 + values["tool_need"] * 0.22 + values["visual_need"] * 0.2 + values["risk"] * 0.24), 4),
        "z": round(_clamp(values["affect"] * 0.28 + (1.0 - values["risk"]) * 0.22 + values["observability_need"] * 0.22 + values["state_pressure"] * 0.28), 4),
    }


def _distance(left: dict[str, float], right: dict[str, float]) -> float:
    return math.sqrt(
        (float(left.get("x", 0.0)) - float(right.get("x", 0.0))) ** 2
        + (float(left.get("y", 0.0)) - float(right.get("y", 0.0))) ** 2
        + (float(left.get("z", 0.0)) - float(right.get("z", 0.0))) ** 2
    )


def _tool_requests(values: dict[str, float], subproblem_id: str) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if values["long_memory"] >= 0.55:
        requests.append({"name": "memory_recall", "reason": "long_memory_pressure", "payload": {"mode": "readonly"}})
    if values["tool_need"] >= 0.5:
        requests.append({"name": "workspace_inspect", "reason": "tool_need", "payload": {"mode": "readonly"}})
    if values["visual_need"] >= 0.5:
        requests.append({"name": "visual_scene_delta", "reason": "visual_grounding", "payload": {"mode": "summary_only"}})
    if values["feedback_pressure"] >= 0.75:
        requests.append({"name": "feedback_update_candidate", "reason": "learning_feedback", "payload": {"mode": "proposal_only"}})
    if subproblem_id == "observability":
        requests.append({"name": "trace_export", "reason": "research_observability", "payload": {"mode": "redacted"}})
    return requests


def _probe_text(subproblem: dict[str, Any], probe: dict[str, Any]) -> str:
    return f"{subproblem['id']}::{probe['label']} | {subproblem['question']}"


def _semantic_novelty(values: dict[str, float], deep_needed: bool) -> float:
    if not deep_needed:
        return round(0.25 + values["state_pressure"] * 0.28, 4)
    novelty = 0.42 + values["uncertainty"] * 0.18 + values["tool_need"] * 0.14 + values["long_memory"] * 0.14 + values["feedback_pressure"] * 0.12
    return round(_clamp(novelty), 4)


def _simulate_probe(subproblem: dict[str, Any], probe: dict[str, Any], *, context_window_tokens: int) -> dict[str, Any]:
    values = _state_values(probe)
    tools = _tool_requests(values, str(subproblem["id"]))
    query = _probe_text(subproblem, probe)
    prompt = "\n".join(
        [
            CORE_PROBLEM,
            str(subproblem["question"]),
            f"probe={probe['label']}",
            "state=" + json.dumps(values, sort_keys=True),
        ]
    )
    packet_policy = build_stage121_packet_policy(
        prompt=prompt,
        query=query,
        tool_requests=tools,
        uncertainty_level=values["uncertainty"],
        selected_action_type="reply_once",
        lane_name="subject_main",
        lane_max_output_tokens=4096,
        context_window_tokens=context_window_tokens,
    )
    stream_mode = str(packet_policy["continuity"]["stream_mode"])
    deep_needed = stream_mode != "compact_reply_packet" or bool(tools) or values["feedback_pressure"] >= 0.7
    fast_packet = {
        "intent": str(subproblem["id"]),
        "scene": str(probe["label"]),
        "deep_packet_needed": deep_needed,
        "shallow_reply": f"fast triage: {probe['label']}",
        "speak_now": True,
        "continue_until": "new semantic function is exhausted" if deep_needed else "fast answer is enough",
    }
    stream_plan = plan_stage132_progressive_stream(
        fast_packet=fast_packet,
        continuation_lane="subject_main",
        continuation_lane_reason="stage133_v2_core_problem_simulation",
        selected_action_type="reply_once",
        uncertainty_level=values["uncertainty"],
        channel="research_simulation",
        expression_budget=3,
        agent_tool_requests=tools,
        fast_context_frame={
            "cache_hint": "stage133:" + stable_digest(str(subproblem["id"]), str(probe["label"]), limit=12),
            "line_count": 7 + len(tools),
            "char_count": len(prompt),
        },
    )
    novelty = _semantic_novelty(values, deep_needed)
    return {
        "probe_id": f"{subproblem['id']}:{probe['label']}",
        "subproblem_id": str(subproblem["id"]),
        "subproblem_question": str(subproblem["question"]),
        "probe_label": str(probe["label"]),
        "query": query,
        "state_values": values,
        "projection": _projection(values),
        "tool_requests": tools,
        "stage121_packet_policy": {
            "stream_mode": stream_mode,
            "target_input_tokens": packet_policy["target_input_tokens"],
            "observed_prompt_tokens": packet_policy["observed_prompt_tokens"],
            "expansion_budget_tokens": packet_policy["expansion_budget_tokens"],
            "output_budget_tokens": packet_policy["output_budget_tokens"],
            "cache": packet_policy["cache"],
            "tool_loop": packet_policy["tool_loop"],
        },
        "stage132_stream_plan": stream_plan,
        "semantic_novelty": novelty,
        "continuation_decision": {
            "fast_packet_always_first": True,
            "deep_packet_needed": bool(stream_plan["deep_packet_needed"]),
            "round_count": int(stream_plan["round_count"]),
            "tool_loop_expected": bool(stream_plan["tool_loop_expected"]),
            "stop_reason": str(stream_plan.get("stop_reason", "")),
        },
        "expression_segments": [
            {"role": "fast_reaction", "visible": True, "semantic_function": "intent_triage"},
            *(
                [{"role": "deep_continuation", "visible": True, "semantic_function": "state_delta_or_tool_grounded_answer"}]
                if deep_needed
                else []
            ),
        ],
    }


def _select_probes(probes_per_subproblem: int) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    count = max(1, int(probes_per_subproblem))
    for subproblem in SUBPROBLEMS:
        options = [dict(item) for item in subproblem["probes"]]
        for index in range(count):
            base = dict(options[index % len(options)])
            if index >= len(options):
                base["label"] = f"{base['label']}_variant_{index + 1}"
                base["uncertainty"] = _clamp(base.get("uncertainty", 0.4) + 0.03 * (index + 1))
            selected.append((subproblem, base))
    return selected


def _metrics(probes: list[dict[str, Any]]) -> dict[str, Any]:
    subproblem_counts = Counter(str(item["subproblem_id"]) for item in probes)
    routes = Counter(
        "deep" if item["continuation_decision"]["deep_packet_needed"] else "fast_only"
        for item in probes
    )
    tool_loop_count = sum(1 for item in probes if item["continuation_decision"]["tool_loop_expected"])
    projections = [dict(item["projection"]) for item in probes]
    deltas = [_distance(projections[index - 1], projections[index]) for index in range(1, len(projections))]
    novelty = [float(item["semantic_novelty"]) for item in probes]
    target_tokens = [int(item["stage121_packet_policy"]["target_input_tokens"]) for item in probes]
    observed_tokens = [int(item["stage121_packet_policy"]["observed_prompt_tokens"]) for item in probes]
    fill_ratios = [
        min(1.0, observed / max(1, target))
        for observed, target in zip(observed_tokens, target_tokens)
    ]
    return {
        "probe_count": len(probes),
        "subproblem_count": len(subproblem_counts),
        "subproblem_counts": dict(sorted(subproblem_counts.items())),
        "route_counts": dict(routes),
        "deep_rate": round(routes.get("deep", 0) / max(1, len(probes)), 4),
        "fast_only_rate": round(routes.get("fast_only", 0) / max(1, len(probes)), 4),
        "tool_loop_rate": round(tool_loop_count / max(1, len(probes)), 4),
        "mean_round_count": _mean([float(item["continuation_decision"]["round_count"]) for item in probes]),
        "mean_semantic_novelty": _mean(novelty),
        "mean_context_fill_ratio": _mean(fill_ratios),
        "continuity": {
            "mean_delta": _mean([round(delta, 4) for delta in deltas]),
            "max_delta": round(max(deltas), 4) if deltas else 0.0,
            "large_jump_threshold": 0.42,
            "large_jump_count": sum(1 for delta in deltas if delta > 0.42),
        },
    }


def _order_probes_by_continuity(probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order probes as a smooth state-space walk while preserving full coverage."""

    remaining = [dict(item) for item in probes]
    if len(remaining) <= 2:
        return remaining
    start = min(
        remaining,
        key=lambda item: (
            float(dict(item.get("state_values", {})).get("state_pressure", 0.0)),
            float(dict(item.get("state_values", {})).get("uncertainty", 0.0)),
        ),
    )
    ordered = [start]
    remaining.remove(start)
    while remaining:
        current = dict(ordered[-1].get("projection", {}))
        next_item = min(
            remaining,
            key=lambda item: (
                _distance(current, dict(item.get("projection", {}))),
                str(item.get("subproblem_id", "")),
            ),
        )
        ordered.append(next_item)
        remaining.remove(next_item)
    for index, item in enumerate(ordered):
        item["trajectory_index"] = index
    return ordered


def _scorecard(metrics: dict[str, Any], probes: list[dict[str, Any]]) -> dict[str, Any]:
    route_counts = dict(metrics.get("route_counts", {}))
    has_tool_probe = any(item["tool_requests"] for item in probes)
    has_visual_probe = any(float(item["state_values"]["visual_need"]) >= 0.5 for item in probes)
    checks = {
        "covers_all_v2_subproblems": int(metrics.get("subproblem_count", 0)) == len(SUBPROBLEMS),
        "has_fast_only_and_deep_paths": route_counts.get("fast_only", 0) > 0 and route_counts.get("deep", 0) > 0,
        "tool_and_visual_paths_observed": has_tool_probe and has_visual_probe,
        "continuity_jumps_bounded": int(dict(metrics.get("continuity", {})).get("large_jump_count", 0)) <= 1,
        "semantic_novelty_above_floor": float(metrics.get("mean_semantic_novelty", 0.0)) >= 0.48,
        "no_raw_provider_content": True,
    }
    return {
        "status": "pass" if all(checks.values()) else "needs_iteration",
        "checks": checks,
        "next_iteration_targets": [
            "replace deterministic probes with live provider-return traces",
            "compare simulated stream decisions against CLI chat failures",
            "connect Stage133 probes to Stage131 CT and Stage100 topology playback",
        ],
    }


def build_stage133_research_payload(
    *,
    probes_per_subproblem: int = 2,
    context_window_tokens: int = 65536,
) -> dict[str, Any]:
    unordered_probes = [
        _simulate_probe(subproblem, probe, context_window_tokens=context_window_tokens)
        for subproblem, probe in _select_probes(probes_per_subproblem)
    ]
    probes = _order_probes_by_continuity(unordered_probes)
    metrics = _metrics(probes)
    return {
        "schema": STAGE133_SCHEMA,
        "stage": 133,
        "generated_at": utc_now(),
        "title": "Stage133 V2 core-problem research loop",
        "core_problem": CORE_PROBLEM,
        "subproblems": [
            {"id": str(item["id"]), "question": str(item["question"])}
            for item in SUBPROBLEMS
        ],
        "probes": probes,
        "metrics": metrics,
        "scorecard": _scorecard(metrics, probes),
        "privacy": {
            "raw_provider_content_included": False,
            "raw_memory_text_included": False,
            "simulation_only": True,
        },
    }


def render_stage133_research_html(payload: dict[str, Any]) -> str:
    data = json.dumps(payload, ensure_ascii=False)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stage133 V2 Core Problem Research Loop</title>
  <style>
    body {{ margin:0; background:#f6f7f4; color:#17201f; font:14px/1.45 system-ui, -apple-system, "Microsoft YaHei", sans-serif; }}
    header {{ padding:18px 22px; background:white; border-bottom:1px solid #d7dfda; }}
    h1 {{ margin:0 0 6px; font-size:24px; }}
    main {{ display:grid; grid-template-columns:320px 1fr; gap:0; min-height:calc(100vh - 82px); }}
    aside {{ background:white; border-right:1px solid #d7dfda; padding:14px; overflow:auto; }}
    section {{ padding:14px; display:grid; gap:12px; grid-template-columns:1.1fr .9fr; }}
    .panel {{ background:white; border:1px solid #d7dfda; border-radius:6px; padding:12px; min-width:0; }}
    .wide {{ grid-column:1 / -1; }}
    canvas {{ width:100%; display:block; border:1px solid #d7dfda; border-radius:4px; background:#fff; }}
    .metric {{ display:grid; grid-template-columns:1fr auto; gap:10px; padding:7px 0; border-bottom:1px solid #edf1ee; }}
    .small {{ color:#62706b; font-size:12px; }}
    select, input {{ width:100%; margin:6px 0 12px; }}
    .pill {{ display:inline-block; border:1px solid #cbd7d1; border-radius:99px; padding:2px 8px; }}
    pre {{ white-space:pre-wrap; background:#f4f7f6; border:1px solid #d7dfda; padding:10px; border-radius:4px; max-height:320px; overflow:auto; }}
    @media (max-width: 980px) {{ main, section {{ grid-template-columns:1fr; }} aside {{ border-right:0; border-bottom:1px solid #d7dfda; }} }}
  </style>
</head>
<body>
<header>
  <h1>Stage133 V2 Core Problem Research Loop</h1>
  <div class="small">finite provider packets -> state continuity -> tool/memory/action loop -> observable research trace</div>
</header>
<main>
<aside>
  <label>probe <input id="probeSlider" type="range" value="0" min="0"></label>
  <label>subproblem <select id="subproblemSelect"><option value="all">all</option></select></label>
  <div id="summary"></div>
</aside>
<section>
  <div class="panel wide"><h2>Core Problem Trajectory</h2><canvas id="trajectory" width="1200" height="420"></canvas></div>
  <div class="panel"><h2>State Slice</h2><canvas id="slice" width="620" height="520"></canvas></div>
  <div class="panel"><h2>Probe Trace</h2><pre id="trace"></pre></div>
</section>
</main>
<script id="payload" type="application/json">{data}</script>
<script>
const payload = JSON.parse(document.getElementById("payload").textContent);
const probes = payload.probes || [];
let index = 0;
let filter = "all";
const slider = document.getElementById("probeSlider");
const select = document.getElementById("subproblemSelect");
slider.max = Math.max(0, probes.length - 1);
[...new Set(probes.map(p => p.subproblem_id))].forEach(id => {{
  const option = document.createElement("option");
  option.value = id; option.textContent = id; select.appendChild(option);
}});
function n(value) {{ const x = Number(value); return Number.isFinite(x) ? x : 0; }}
function ctx(canvas) {{
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || canvas.width;
  const height = Math.max(260, Math.round(width * canvas.height / canvas.width));
  canvas.style.height = height + "px"; canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
  const c = canvas.getContext("2d"); c.setTransform(ratio,0,0,ratio,0,0); return {{c,width,height}};
}}
function color(id, alpha=.72) {{
  const palette = ["53,111,138","182,83,79","77,127,83","108,94,151","176,123,45","75,122,116","151,82,110"];
  let h = 0; String(id || "x").split("").forEach(ch => h = (h * 31 + ch.charCodeAt(0)) >>> 0);
  return `rgba(${{palette[h % palette.length]}},${{alpha}})`;
}}
function visible() {{ return probes.filter(p => filter === "all" || p.subproblem_id === filter); }}
function drawTrajectory() {{
  const {{c,width,height}} = ctx(document.getElementById("trajectory"));
  c.clearRect(0,0,width,height);
  const pad=38, w=width-pad*2, h=height-pad*2;
  c.strokeStyle="#d7dfda"; c.strokeRect(pad,pad,w,h);
  const list = visible();
  c.beginPath();
  list.forEach((p,i) => {{
    const x = pad + n(p.projection.x) * w;
    const y = height - pad - n(p.projection.y) * h;
    if (i === 0) c.moveTo(x,y); else c.lineTo(x,y);
  }});
  c.strokeStyle="#356f8a"; c.lineWidth=2; c.stroke();
  list.forEach(p => {{
    const x = pad + n(p.projection.x) * w;
    const y = height - pad - n(p.projection.y) * h;
    const active = p.probe_id === (probes[index] || {{}}).probe_id;
    c.beginPath(); c.arc(x,y, active ? 7 : 4, 0, Math.PI*2);
    c.fillStyle = active ? "#b6534f" : color(p.subproblem_id, .56); c.fill();
  }});
  c.fillStyle="#62706b"; c.fillText("memory / working-state pressure", pad, height-12);
}}
function drawSlice() {{
  const p = probes[index] || {{}};
  const values = p.state_values || {{}};
  const keys = Object.keys(values);
  const {{c,width,height}} = ctx(document.getElementById("slice"));
  c.clearRect(0,0,width,height);
  const cols = 8, gap = 7, cell = Math.min((width-44-cols*gap)/cols, 38);
  keys.forEach((key, k) => {{
    for (let i=0;i<8;i++) {{
      const x = 22 + (i % cols) * (cell + gap);
      const y = 36 + k * (cell + gap);
      const activity = Math.min(1, n(values[key]) * .72 + Math.sin(index*.3+i+k)*.08 + .12);
      c.fillStyle = `rgba(182,83,79,${{activity}})`;
      c.fillRect(x,y,cell,cell);
    }}
    c.fillStyle="#17201f"; c.fillText(key + " " + n(values[key]).toFixed(2), 22 + cols*(cell+gap) + 4, 36 + k*(cell+gap) + cell*.7);
  }});
}}
function update() {{
  index = Math.max(0, Math.min(probes.length - 1, index));
  slider.value = index;
  const p = probes[index] || {{}};
  document.getElementById("summary").innerHTML = `
    <div class="metric"><span>scorecard</span><strong class="pill">${{payload.scorecard.status}}</strong></div>
    <div class="metric"><span>probes</span><strong>${{payload.metrics.probe_count}}</strong></div>
    <div class="metric"><span>subproblems</span><strong>${{payload.metrics.subproblem_count}}</strong></div>
    <div class="metric"><span>deep rate</span><strong>${{n(payload.metrics.deep_rate).toFixed(2)}}</strong></div>
    <div class="metric"><span>tool loop rate</span><strong>${{n(payload.metrics.tool_loop_rate).toFixed(2)}}</strong></div>
    <div class="metric"><span>current</span><strong>${{p.probe_id || ""}}</strong></div>`;
  document.getElementById("trace").textContent = JSON.stringify({{
    probe_id: p.probe_id,
    question: p.subproblem_question,
    continuation: p.continuation_decision,
    stream_mode: (p.stage121_packet_policy || {{}}).stream_mode,
    tool_requests: p.tool_requests,
    semantic_novelty: p.semantic_novelty,
    segments: p.expression_segments
  }}, null, 2);
  drawTrajectory(); drawSlice();
}}
slider.addEventListener("input", e => {{ index = Number(e.target.value); update(); }});
select.addEventListener("change", e => {{ filter = e.target.value; update(); }});
window.addEventListener("resize", update);
update();
</script>
</body></html>
"""


def write_stage133_research_artifacts(
    repo_root: Path | str,
    *,
    output_dir: Path | str | None = None,
    probes_per_subproblem: int = 2,
    context_window_tokens: int = 65536,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    target = Path(output_dir) if output_dir is not None else root / DEFAULT_OUTPUT_DIR
    if not target.is_absolute():
        target = root / target
    target.mkdir(parents=True, exist_ok=True)
    payload = build_stage133_research_payload(
        probes_per_subproblem=probes_per_subproblem,
        context_window_tokens=context_window_tokens,
    )
    json_path = target / "stage133_core_problem_research_loop_payload.json"
    html_path = target / "stage133_core_problem_research_loop.html"
    atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(html_path, render_stage133_research_html(payload))
    return {
        "status": "ok",
        "schema": STAGE133_SCHEMA,
        "stage": 133,
        "html_path": str(html_path),
        "payload_path": str(json_path),
        "probe_count": payload["metrics"]["probe_count"],
        "subproblem_count": payload["metrics"]["subproblem_count"],
        "scorecard": payload["scorecard"],
        "privacy": payload["privacy"],
    }
