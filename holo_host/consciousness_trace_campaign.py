from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable, Sequence

from .common import stable_digest, utc_now
from .consciousness_provider_trace import (
    DEFAULT_STAGE59_SUITE,
    STAGE59_NAME,
    run_provider_longform_trace,
    shadow_config_for_provider_trace,
    write_provider_trace_artifacts,
)


STAGE60_NAME = "stage60-longrun-provider-campaign"
DEFAULT_STAGE60_CAMPAIGN_ID = "stage60_provider_campaign"
DEFAULT_STAGE60_MODELS = ("deepseek-v4-pro", "deepseek-v4-flash")

TraceRunner = Callable[..., dict[str, Any]]
TraceArtifactWriter = Callable[[dict[str, Any], str | Path], dict[str, Path]]


def run_provider_trace_campaign(
    *,
    execute: bool = False,
    config: Any | None = None,
    output_root: str | Path | None = None,
    campaign_id: str = DEFAULT_STAGE60_CAMPAIGN_ID,
    suite: str = DEFAULT_STAGE59_SUITE,
    models: str | Sequence[str] | None = None,
    runs_per_model: int = 1,
    turns: int = 24,
    max_total_tokens_per_cell: int = 20_000,
    provider_hint: str = "deepseek",
    lane: str = "auto",
    max_output_tokens: int | None = 240,
    resume: bool = True,
    allow_provider_fallback: bool = False,
    use_live_state: bool = False,
    trace_runner: TraceRunner = run_provider_longform_trace,
    artifact_writer: TraceArtifactWriter = write_provider_trace_artifacts,
) -> dict[str, Any]:
    safe_campaign_id = _slug(str(campaign_id or DEFAULT_STAGE60_CAMPAIGN_ID))
    safe_models = _parse_models(models)
    safe_runs = max(1, min(1000, int(runs_per_model or 1)))
    safe_turns = max(1, min(100_000, int(turns or 1)))
    safe_budget = max(1, int(max_total_tokens_per_cell or 20_000))
    root = _campaign_root(
        output_root=output_root, config=config, campaign_id=safe_campaign_id
    )
    root.mkdir(parents=True, exist_ok=True)
    event_path = root / "campaign_events.jsonl"
    manifest_path = root / "campaign_manifest.json"
    if event_path.exists() and not resume:
        event_path.unlink()
    _append_event(
        event_path,
        {
            "type": "campaign_start",
            "campaign_id": safe_campaign_id,
            "execute": bool(execute),
            "model_count": len(safe_models),
        },
    )
    cells: list[dict[str, Any]] = []
    for index, model in enumerate(safe_models):
        model_slug = _slug(model)
        cell_id = f"{index + 1:02d}_{model_slug}"
        cell_dir = root / "cells" / cell_id
        cell_dir.mkdir(parents=True, exist_ok=True)
        output_path = cell_dir / "provider_trace.html"
        journal_path = cell_dir / "provider_trace_turns.jsonl"
        selected_lane = _infer_lane(model=model, lane=lane)
        trace_config = config
        state_isolation = "dry_run_no_state"
        state_root = ""
        if execute and use_live_state:
            state_isolation = "live_runtime"
            state_root = str(getattr(getattr(config, "runtime", None), "state_dir", ""))
        elif execute and config is not None:
            shadow_root = cell_dir / "shadow_runtime"
            trace_config = shadow_config_for_provider_trace(config, shadow_root)
            state_isolation = "shadow_runtime"
            state_root = str(shadow_root)
        elif execute:
            state_isolation = "injected_runner_state"
        trace_report: dict[str, Any] | None = None
        artifacts: dict[str, Path] = {}
        error = ""
        try:
            trace_report = trace_runner(
                execute=execute,
                config=trace_config,
                suite=suite or DEFAULT_STAGE59_SUITE,
                runs=safe_runs,
                turns=safe_turns,
                max_total_tokens=safe_budget,
                provider_hint=provider_hint,
                model=model,
                lane=selected_lane,
                max_output_tokens=max_output_tokens,
                thread_key_prefix=(
                    f"cli:Stage60ProviderCampaign:{safe_campaign_id}:{cell_id}"
                ),
                chat_name_prefix=f"Stage60Campaign-{cell_id[:36]}",
                channel="cli",
                checkpoint_path=journal_path if execute else None,
                resume=bool(resume),
                allow_provider_fallback=allow_provider_fallback,
                state_isolation=state_isolation,
                state_root=state_root,
            )
            artifacts = artifact_writer(trace_report, output_path)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
        cell = _compact_cell(
            index=index,
            cell_id=cell_id,
            model=model,
            lane=selected_lane,
            output_path=output_path,
            journal_path=journal_path if execute else None,
            artifacts=artifacts,
            report=trace_report,
            error=error,
            state_isolation=state_isolation,
            state_root=state_root,
        )
        cells.append(cell)
        _append_event(
            event_path,
            {
                "type": "cell_complete",
                "campaign_id": safe_campaign_id,
                "cell_id": cell_id,
                "model": model,
                "status": cell["status"],
                "ok": bool(cell.get("ok", False)),
                "observed_total_tokens": int(cell.get("observed_total_tokens", 0) or 0),
            },
        )
        _write_json(
            manifest_path,
            _assemble_campaign_report(
                campaign_id=safe_campaign_id,
                execute=execute,
                output_root=root,
                suite=suite,
                provider_hint=provider_hint,
                lane=lane,
                max_output_tokens=max_output_tokens,
                runs_per_model=safe_runs,
                turns=safe_turns,
                max_total_tokens_per_cell=safe_budget,
                resume=resume,
                allow_provider_fallback=allow_provider_fallback,
                use_live_state=use_live_state,
                cells=cells,
                status_override="running",
            ),
        )
    report = _assemble_campaign_report(
        campaign_id=safe_campaign_id,
        execute=execute,
        output_root=root,
        suite=suite,
        provider_hint=provider_hint,
        lane=lane,
        max_output_tokens=max_output_tokens,
        runs_per_model=safe_runs,
        turns=safe_turns,
        max_total_tokens_per_cell=safe_budget,
        resume=resume,
        allow_provider_fallback=allow_provider_fallback,
        use_live_state=use_live_state,
        cells=cells,
    )
    _write_json(manifest_path, report)
    _append_event(
        event_path,
        {
            "type": "campaign_complete",
            "campaign_id": safe_campaign_id,
            "status": report["status"],
            "ok": bool(report.get("ok", False)),
            "observed_total_tokens": int(
                dict(report.get("aggregate", {})).get("observed_total_tokens", 0) or 0
            ),
        },
    )
    return report


def write_provider_trace_campaign_artifacts(
    report: dict[str, Any], output_path: str | Path
) -> dict[str, Path]:
    html_path = Path(output_path).expanduser()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(render_provider_trace_campaign_html(report), encoding="utf-8")
    json_path = html_path.with_suffix(".json")
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    png_path = html_path.with_name(f"{html_path.stem}_campaign.png")
    _write_campaign_png(report, png_path)
    return {"html": html_path, "json": json_path, "campaign_png": png_path}


def render_provider_trace_campaign_html(report: dict[str, Any]) -> str:
    aggregate = _as_dict(report.get("aggregate", {}))
    ranking = _as_dict(report.get("ranking", {}))
    gate = _as_dict(report.get("breakthrough_gate", {}))
    serialized = html.escape(json.dumps(_compact_for_html(report), ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Stage60 Provider Trace Campaign</title>
  <style>
    body {{ margin: 0; font-family: Arial, sans-serif; color: #172026; background: #f6f7f4; }}
    main {{ max-width: 1180px; margin: 0 auto; padding: 28px; }}
    h1, h2 {{ letter-spacing: 0; }}
    section {{ margin-top: 22px; padding-top: 14px; border-top: 1px solid #d7dddc; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .metric {{ background: #ffffff; border: 1px solid #d7dddc; border-radius: 6px; padding: 12px; }}
    .metric span {{ display: block; color: #5f6c72; font-size: 12px; }}
    .metric strong {{ display: block; margin-top: 6px; font-size: 20px; }}
    table {{ width: 100%; border-collapse: collapse; background: #ffffff; }}
    th, td {{ border: 1px solid #d7dddc; padding: 8px; text-align: left; font-size: 13px; }}
    th {{ background: #e9eeeb; }}
    pre {{ white-space: pre-wrap; background: #ffffff; border: 1px solid #d7dddc; border-radius: 6px; padding: 12px; }}
    .warn {{ color: #8a4f00; font-weight: 700; }}
  </style>
</head>
<body>
  <main>
    <h1>Stage60 Provider Trace Campaign</h1>
    <div class="grid">
      {_metric("Campaign", report.get("campaign_id", ""))}
      {_metric("Status", report.get("status", ""))}
      {_metric("Cells", aggregate.get("planned_cell_count", 0))}
      {_metric("Real Provider Cells", aggregate.get("real_provider_cell_count", 0))}
      {_metric("Collected Turns", aggregate.get("collected_turn_count", 0))}
      {_metric("Observed Tokens", aggregate.get("observed_total_tokens", 0))}
      {_metric("Top Model", ranking.get("top_model", ""))}
      {_metric("Top Score", ranking.get("top_score", 0.0))}
    </div>
    <section>
      <h2>Breakthrough Gate</h2>
      <p class="warn">do_not_claim_major_breakthrough={_esc(gate.get("do_not_claim_major_breakthrough", True))}</p>
      {_reason_table(gate)}
    </section>
    <section>
      <h2>Campaign Cells</h2>
      {_cell_table(report)}
    </section>
    <section>
      <h2>Source Summary JSON</h2>
      <pre>{serialized}</pre>
    </section>
  </main>
</body>
</html>
"""


def _assemble_campaign_report(
    *,
    campaign_id: str,
    execute: bool,
    output_root: Path,
    suite: str,
    provider_hint: str,
    lane: str,
    max_output_tokens: int | None,
    runs_per_model: int,
    turns: int,
    max_total_tokens_per_cell: int,
    resume: bool,
    allow_provider_fallback: bool,
    use_live_state: bool,
    cells: list[dict[str, Any]],
    status_override: str | None = None,
) -> dict[str, Any]:
    aggregate = _aggregate_cells(cells)
    ranking = _rank_cells(cells)
    breakthrough = _breakthrough_gate(
        execute=execute, aggregate=aggregate, ranking=ranking, cells=cells
    )
    if status_override:
        status = status_override
    elif not execute:
        status = "dry_run"
    elif any(not bool(cell.get("ok", False)) for cell in cells):
        status = "failed"
    else:
        status = "complete"
    return {
        "ok": status in {"dry_run", "running", "complete"},
        "stage": STAGE60_NAME,
        "source_stage": STAGE59_NAME,
        "campaign_id": campaign_id,
        "status": status,
        "created_at": utc_now(),
        "execution_gate": {
            "requires_execute_flag": True,
            "execute": bool(execute),
            "dry_run_only": not bool(execute),
            "allow_provider_fallback": bool(allow_provider_fallback),
            "use_live_state": bool(use_live_state),
        },
        "campaign_plan": {
            "suite": str(suite or DEFAULT_STAGE59_SUITE),
            "provider_hint": str(provider_hint or ""),
            "models": [str(cell.get("model", "") or "") for cell in cells],
            "lane_policy": str(lane or "auto"),
            "max_output_tokens": int(max_output_tokens or 0),
            "runs_per_model": int(runs_per_model or 0),
            "turns_per_run": int(turns or 0),
            "max_total_tokens_per_cell": int(max_total_tokens_per_cell or 0),
            "output_root": str(output_root),
            "resume": bool(resume),
            "new_thread_per_cell_and_run": True,
            "cell_state_isolation": (
                "shadow_runtime_by_default_when_executed"
                if not use_live_state
                else "live_runtime_requested"
            ),
        },
        "cells": cells,
        "aggregate": aggregate,
        "ranking": ranking,
        "breakthrough_gate": breakthrough,
        "boundary": {
            "observational_only": True,
            "provider_calls_operator_gated": True,
            "campaign_orchestration_only": True,
            "runtime_decision_authority": False,
            "transport_decision_authority": False,
            "wechat_transport_used": False,
            "self_memory_write_allowed": False,
            "policy_mutation_allowed": False,
            "unbounded_loop_allowed": False,
        },
    }


def _compact_cell(
    *,
    index: int,
    cell_id: str,
    model: str,
    lane: str,
    output_path: Path,
    journal_path: Path | None,
    artifacts: dict[str, Path],
    report: dict[str, Any] | None,
    error: str,
    state_isolation: str,
    state_root: str,
) -> dict[str, Any]:
    report = _as_dict(report or {})
    trace_set = _as_dict(report.get("provider_trace_set", {}))
    budget = _as_dict(report.get("budget_guard", {}))
    provenance = _as_dict(report.get("provider_provenance", {}))
    evidence = _as_dict(report.get("provider_evidence_gate", {}))
    scorecard = _as_dict(report.get("scorecard", {}))
    calibration = _as_dict(report.get("stage57_calibration", {}))
    predictive = _as_dict(calibration.get("predictive_probe", {}))
    usage = _run_usage_totals(report)
    hit_ratio = (
        usage["prompt_cache_hit_tokens"]
        / max(1, usage["prompt_cache_hit_tokens"] + usage["prompt_cache_miss_tokens"])
    )
    return {
        "index": index,
        "cell_id": cell_id,
        "model": model,
        "lane": lane,
        "ok": bool(report.get("ok", False)) and not error,
        "status": str(report.get("status", "error") or "error") if not error else "error",
        "error": error,
        "output_path": str(artifacts.get("html", output_path)),
        "json_path": str(artifacts.get("json", output_path.with_suffix(".json"))),
        "provider_trace_png_path": str(
            artifacts.get(
                "provider_trace_png",
                output_path.with_name(f"{output_path.stem}_provider_trace.png"),
            )
        ),
        "journal_path": str(journal_path or ""),
        "state_isolation": {"mode": state_isolation, "state_root": state_root},
        "planned_total_turns": int(trace_set.get("planned_total_turns", 0) or 0),
        "collected_turn_count": int(trace_set.get("collected_turn_count", 0) or 0),
        "observed_total_tokens": int(budget.get("observed_total_tokens", 0) or 0),
        "max_total_tokens": int(budget.get("max_total_tokens", 0) or 0),
        "stopped_reason": str(budget.get("stopped_reason", "") or ""),
        "real_provider_trace": bool(trace_set.get("real_provider_trace", False)),
        "actual_providers": _string_list(provenance.get("actual_providers", [])),
        "actual_models": _string_list(provenance.get("actual_models", [])),
        "trace_depth_sufficient": bool(
            evidence.get("trace_depth_sufficient", False)
        ),
        "predictive_gate_passed": bool(
            evidence.get("predictive_gate_passed", False)
        ),
        "do_not_claim_real_manifold": bool(
            evidence.get("do_not_claim_real_manifold", True)
        ),
        "overall_score": float(scorecard.get("overall_score", 0.0) or 0.0),
        "geometry_score_correlation": float(
            predictive.get("geometry_score_correlation", 0.0) or 0.0
        ),
        "prompt_cache_hit_tokens": usage["prompt_cache_hit_tokens"],
        "prompt_cache_miss_tokens": usage["prompt_cache_miss_tokens"],
        "prompt_cache_hit_ratio": round(hit_ratio, 6),
    }


def _aggregate_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    hit = sum(int(cell.get("prompt_cache_hit_tokens", 0) or 0) for cell in cells)
    miss = sum(int(cell.get("prompt_cache_miss_tokens", 0) or 0) for cell in cells)
    actual_providers = sorted(
        {
            provider
            for cell in cells
            for provider in _string_list(cell.get("actual_providers", []))
        }
    )
    actual_models = sorted(
        {model for cell in cells for model in _string_list(cell.get("actual_models", []))}
    )
    return {
        "planned_cell_count": len(cells),
        "completed_cell_count": sum(1 for cell in cells if bool(cell.get("ok", False))),
        "real_provider_cell_count": sum(
            1 for cell in cells if bool(cell.get("real_provider_trace", False))
        ),
        "planned_total_turns": sum(
            int(cell.get("planned_total_turns", 0) or 0) for cell in cells
        ),
        "collected_turn_count": sum(
            int(cell.get("collected_turn_count", 0) or 0) for cell in cells
        ),
        "observed_total_tokens": sum(
            int(cell.get("observed_total_tokens", 0) or 0) for cell in cells
        ),
        "max_total_tokens": sum(int(cell.get("max_total_tokens", 0) or 0) for cell in cells),
        "actual_providers": actual_providers,
        "actual_models": actual_models,
        "trace_depth_sufficient_cell_count": sum(
            1 for cell in cells if bool(cell.get("trace_depth_sufficient", False))
        ),
        "predictive_gate_passed_cell_count": sum(
            1 for cell in cells if bool(cell.get("predictive_gate_passed", False))
        ),
        "do_not_claim_real_manifold_cell_count": sum(
            1 for cell in cells if bool(cell.get("do_not_claim_real_manifold", True))
        ),
        "prompt_cache_hit_tokens": hit,
        "prompt_cache_miss_tokens": miss,
        "prompt_cache_hit_ratio": round(hit / max(1, hit + miss), 6),
        "stopped_reasons": sorted(
            {
                str(cell.get("stopped_reason", "") or "")
                for cell in cells
                if str(cell.get("stopped_reason", "") or "")
            }
        ),
    }


def _rank_cells(cells: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [
        {
            "model": str(cell.get("model", "") or ""),
            "cell_id": str(cell.get("cell_id", "") or ""),
            "overall_score": float(cell.get("overall_score", 0.0) or 0.0),
            "geometry_score_correlation": float(
                cell.get("geometry_score_correlation", 0.0) or 0.0
            ),
            "observed_total_tokens": int(cell.get("observed_total_tokens", 0) or 0),
            "prompt_cache_hit_ratio": float(
                cell.get("prompt_cache_hit_ratio", 0.0) or 0.0
            ),
        }
        for cell in cells
    ]
    scored.sort(
        key=lambda item: (
            item["overall_score"],
            item["geometry_score_correlation"],
            item["observed_total_tokens"],
        ),
        reverse=True,
    )
    top = scored[0] if scored else {}
    return {
        "top_model": str(top.get("model", "") or ""),
        "top_cell_id": str(top.get("cell_id", "") or ""),
        "top_score": float(top.get("overall_score", 0.0) or 0.0),
        "model_scores": scored,
    }


def _breakthrough_gate(
    *,
    execute: bool,
    aggregate: dict[str, Any],
    ranking: dict[str, Any],
    cells: list[dict[str, Any]],
) -> dict[str, Any]:
    reasons: list[str] = []
    if not execute:
        reasons.append("dry_run_has_no_provider_evidence")
    if int(aggregate.get("real_provider_cell_count", 0) or 0) < min(2, max(1, len(cells))):
        reasons.append("requires_replicated_real_provider_cells")
    if int(aggregate.get("collected_turn_count", 0) or 0) < 48:
        reasons.append("trace_depth_below_breakthrough_floor")
    if int(aggregate.get("predictive_gate_passed_cell_count", 0) or 0) < 2:
        reasons.append("predictive_gate_not_replicated")
    if int(aggregate.get("trace_depth_sufficient_cell_count", 0) or 0) < 2:
        reasons.append("trace_depth_not_replicated")
    if float(ranking.get("top_score", 0.0) or 0.0) < 0.82:
        reasons.append("stability_score_below_breakthrough_floor")
    if float(aggregate.get("prompt_cache_hit_ratio", 0.0) or 0.0) < 0.2:
        reasons.append("cache_inheritance_weak")
    if int(aggregate.get("do_not_claim_real_manifold_cell_count", 0) or 0) > 0:
        reasons.append("stage57_cell_gate_blocks_claim")
    return {
        "mode": "conservative_operator_scientific_gate_v1",
        "do_not_claim_major_breakthrough": bool(reasons),
        "reasons": reasons,
        "minimum_real_provider_cells": 2,
        "minimum_collected_turns": 48,
        "minimum_predictive_passed_cells": 2,
        "minimum_top_score": 0.82,
        "minimum_prompt_cache_hit_ratio": 0.2,
    }


def _run_usage_totals(report: dict[str, Any]) -> dict[str, int]:
    totals = {
        "prompt_cache_hit_tokens": 0,
        "prompt_cache_miss_tokens": 0,
    }
    for run in list(report.get("generated_runs", []) or []):
        if not isinstance(run, dict):
            continue
        for key in totals:
            totals[key] += int(run.get(key, 0) or 0)
    return totals


def _campaign_root(
    *,
    output_root: str | Path | None,
    config: Any | None,
    campaign_id: str,
) -> Path:
    if output_root:
        return Path(output_root).expanduser()
    repo_root = getattr(getattr(config, "runtime", None), "repo_root", None)
    if repo_root:
        return Path(repo_root) / "artifacts" / "stage60" / campaign_id
    return Path("artifacts") / "stage60" / campaign_id


def _parse_models(models: str | Sequence[str] | None) -> list[str]:
    if models is None:
        values = list(DEFAULT_STAGE60_MODELS)
    elif isinstance(models, str):
        values = [item.strip() for item in models.split(",")]
    else:
        values = [str(item).strip() for item in models]
    values = [item for item in values if item]
    return values or list(DEFAULT_STAGE60_MODELS)


def _infer_lane(*, model: str, lane: str) -> str:
    requested = str(lane or "auto")
    if requested and requested != "auto":
        return requested
    lower = model.lower()
    if "flash" in lower or "lite" in lower:
        return "micro_fast"
    if "pro" in lower or "reasoner" in lower or "r1" in lower:
        return "kernel_xhigh"
    return "subject_main"


def _slug(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-").lower()
    if safe:
        return safe
    return stable_digest(STAGE60_NAME, value, utc_now(), limit=12)


def _append_event(path: Path, payload: dict[str, Any]) -> None:
    row = {"stage": STAGE60_NAME, "written_at": utc_now(), **payload}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_campaign_png(report: dict[str, Any], output_path: Path) -> None:
    matplotlib, pyplot, numpy = _load_plotting_stack()
    matplotlib.use("Agg")
    cells = [
        dict(cell)
        for cell in list(report.get("cells", []) or [])
        if isinstance(cell, dict)
    ]
    labels = [
        str(cell.get("model", "") or f"cell {index + 1}")
        for index, cell in enumerate(cells)
    ]
    tokens = numpy.array(
        [float(cell.get("observed_total_tokens", 0) or 0) for cell in cells],
        dtype=float,
    )
    scores = numpy.array(
        [float(cell.get("overall_score", 0.0) or 0.0) for cell in cells],
        dtype=float,
    )
    cache = numpy.array(
        [float(cell.get("prompt_cache_hit_ratio", 0.0) or 0.0) for cell in cells],
        dtype=float,
    )
    fig, axes = pyplot.subplots(1, 3, figsize=(16, 5.5), dpi=150)
    x = numpy.arange(len(labels))
    if len(labels):
        axes[0].bar(x, tokens, color="#2f7d68", edgecolor="#172026", linewidth=0.8)
        axes[1].plot(x, scores, marker="o", color="#b88424", linewidth=2)
        axes[2].bar(x, cache, color="#5e7fa7", edgecolor="#172026", linewidth=0.8)
    for axis in axes:
        axis.set_xticks(x)
        axis.set_xticklabels(labels, rotation=35, ha="right")
        axis.grid(True, axis="y", color="#d7dddc", linewidth=0.7, alpha=0.75)
    axes[0].set_title("Observed Tokens")
    axes[1].set_ylim(0.0, 1.05)
    axes[1].set_title("Bionic Stability Score")
    axes[2].set_ylim(0.0, 1.05)
    axes[2].set_title("Prompt Cache Hit Ratio")
    aggregate = _as_dict(report.get("aggregate", {}))
    gate = _as_dict(report.get("breakthrough_gate", {}))
    fig.suptitle(
        "Stage60 Long-Run Provider Campaign | "
        f"tokens={aggregate.get('observed_total_tokens', 0)} | "
        f"do_not_claim={gate.get('do_not_claim_major_breakthrough', True)}",
        fontsize=13,
        y=0.99,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    pyplot.close(fig)


def _load_plotting_stack() -> tuple[Any, Any, Any]:
    try:
        import matplotlib
        import matplotlib.pyplot as pyplot
        import numpy
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "matplotlib and numpy are required to export Stage60 PNG artifacts"
        ) from exc
    return matplotlib, pyplot, numpy


def _compact_for_html(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "stage": report.get("stage", ""),
        "campaign_id": report.get("campaign_id", ""),
        "status": report.get("status", ""),
        "execution_gate": report.get("execution_gate", {}),
        "campaign_plan": report.get("campaign_plan", {}),
        "aggregate": report.get("aggregate", {}),
        "ranking": report.get("ranking", {}),
        "breakthrough_gate": report.get("breakthrough_gate", {}),
        "cells": report.get("cells", []),
        "boundary": report.get("boundary", {}),
    }


def _metric(label: str, value: Any) -> str:
    return (
        '<div class="metric">'
        f"<span>{_esc(label)}</span><strong>{_esc(value)}</strong>"
        "</div>"
    )


def _reason_table(gate: dict[str, Any]) -> str:
    reasons = [str(item) for item in list(gate.get("reasons", []) or [])]
    if not reasons:
        return "<p>No blocking reasons. Operator scientific review is still required.</p>"
    rows = ["<table><tr><th>blocking reason</th></tr>"]
    for reason in reasons:
        rows.append(f"<tr><td>{_esc(reason)}</td></tr>")
    rows.append("</table>")
    return "\n".join(rows)


def _cell_table(report: dict[str, Any]) -> str:
    cells = [
        dict(cell)
        for cell in list(report.get("cells", []) or [])
        if isinstance(cell, dict)
    ]
    if not cells:
        return "<p>No campaign cells were planned.</p>"
    rows = [
        "<table><tr><th>cell</th><th>model</th><th>lane</th><th>status</th>"
        "<th>turns</th><th>tokens</th><th>score</th><th>cache hit</th>"
        "<th>predictive</th><th>trace gate</th></tr>"
    ]
    for cell in cells:
        rows.append(
            "<tr>"
            f"<td>{_esc(cell.get('cell_id', ''))}</td>"
            f"<td>{_esc(cell.get('model', ''))}</td>"
            f"<td>{_esc(cell.get('lane', ''))}</td>"
            f"<td>{_esc(cell.get('status', ''))}</td>"
            f"<td>{_esc(cell.get('collected_turn_count', 0))}</td>"
            f"<td>{_esc(cell.get('observed_total_tokens', 0))}</td>"
            f"<td>{_esc(cell.get('overall_score', 0.0))}</td>"
            f"<td>{_esc(cell.get('prompt_cache_hit_ratio', 0.0))}</td>"
            f"<td>{_esc(cell.get('predictive_gate_passed', False))}</td>"
            f"<td>{_esc(cell.get('do_not_claim_real_manifold', True))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "\n".join(rows)


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _esc(value: Any) -> str:
    return html.escape(str(value))
