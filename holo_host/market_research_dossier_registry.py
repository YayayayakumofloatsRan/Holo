from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any, Callable

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata
from .market_research_dossier_resume import resume_market_research_from_dossier

STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY_SCHEMA = "holo.stage201.market_research_dossier_registry.v1"
STAGE201_MARKET_RESEARCH_DOSSIER_RECORD_SCHEMA = "holo.stage201.market_research_dossier_record.v1"
STAGE201_MARKET_RESEARCH_DOSSIER_LOOKUP_SCHEMA = "holo.stage201.market_research_dossier_lookup.v1"
STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY_BUNDLE_SCHEMA = "holo.stage201.market_research_dossier_registry_bundle.v1"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _registry_root(state_dir: str | Path) -> Path:
    root = Path(state_dir).resolve() / "market_research_dossiers"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_scope_key(*, thread_key: str = "", project_key: str = "") -> str:
    raw = str(thread_key or project_key or "default").strip() or "default"
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("._-")[:60] or "default"
    digest = stable_digest(str(thread_key or ""), str(project_key or ""), limit=12)
    return f"{slug}-{digest}"


def _scope_path(state_dir: str | Path, *, thread_key: str = "", project_key: str = "") -> Path:
    root = _registry_root(state_dir)
    path = (root / f"{_safe_scope_key(thread_key=thread_key, project_key=project_key)}.jsonl").resolve()
    if not str(path).startswith(str(root.resolve())):
        raise ValueError("market_research_dossier_registry_path_escape")
    return path


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text:
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _latest_row(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    return dict(rows[-1]) if rows else {}


def _latest_matching_row(state_dir: str | Path, *, thread_key: str = "", project_key: str = "") -> tuple[dict[str, Any], Path | None]:
    root = _registry_root(state_dir)
    matches: list[tuple[str, Path, dict[str, Any]]] = []
    for path in sorted(root.glob("*.jsonl")):
        for row in _read_rows(path):
            if thread_key and str(row.get("thread_key", "") or "") != str(thread_key):
                continue
            if project_key and str(row.get("project_key", "") or "") != str(project_key):
                continue
            matches.append((str(row.get("recorded_at", "") or ""), path, row))
    if not matches:
        return {}, None
    matches.sort(key=lambda item: (item[0], int(item[2].get("record_index", 0) or 0)))
    _, path, row = matches[-1]
    return dict(row), path


def record_market_research_dossier(
    *,
    state_dir: str | Path,
    thread_key: str = "",
    project_key: str = "",
    dossier: dict[str, Any] | None = None,
    resume_report: dict[str, Any] | None = None,
    source_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = _scope_path(state_dir, thread_key=thread_key, project_key=project_key)
    rows = _read_rows(path)
    clean_dossier = sanitize_public_metadata(_dict(dossier))
    clean_resume = sanitize_public_metadata(_dict(resume_report))
    record = {
        "schema": STAGE201_MARKET_RESEARCH_DOSSIER_RECORD_SCHEMA,
        "record_id": "stage201_dossier_record:" + stable_digest(thread_key, project_key, json.dumps(clean_dossier, ensure_ascii=False, sort_keys=True), limit=12),
        "record_index": len(rows) + 1,
        "recorded_at": utc_now(),
        "thread_key": str(thread_key or ""),
        "project_key": str(project_key or ""),
        "dossier_id": str(clean_dossier.get("dossier_id", "") or ""),
        "dossier_status": str(clean_dossier.get("status", "") or ""),
        "question": _compact(clean_dossier.get("question", ""), 260),
        "source_count": int(clean_dossier.get("source_count", 0) or 0),
        "metric_count": int(clean_dossier.get("metric_count", 0) or 0),
        "next_action_count": len(list(clean_dossier.get("next_actions", []) or [])),
        "dossier": clean_dossier,
        "stage200_market_research_dossier_resume": clean_resume,
        "source_metadata": sanitize_public_metadata(_dict(source_metadata)),
        "path": str(path),
        "hidden_reasoning_exposed": False,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    return sanitize_public_metadata(record)


def load_latest_market_research_dossier(
    *,
    state_dir: str | Path,
    thread_key: str = "",
    project_key: str = "",
    question: str = "",
) -> dict[str, Any]:
    path = _scope_path(state_dir, thread_key=thread_key, project_key=project_key)
    record = _latest_row(path)
    if not record and (thread_key or project_key):
        record, matched_path = _latest_matching_row(state_dir, thread_key=thread_key, project_key=project_key)
        if matched_path is not None:
            path = matched_path
    if not record:
        return {
            "schema": STAGE201_MARKET_RESEARCH_DOSSIER_LOOKUP_SCHEMA,
            "status": "missing",
            "thread_key": str(thread_key or ""),
            "project_key": str(project_key or ""),
            "question": _compact(question, 260),
            "path": str(path),
            "dossier": {},
            "record": {},
            "canonical_stop_reason": "needs_user_clarification",
            "hidden_reasoning_exposed": False,
            "looked_up_at": utc_now(),
        }
    return sanitize_public_metadata(
        {
            "schema": STAGE201_MARKET_RESEARCH_DOSSIER_LOOKUP_SCHEMA,
            "status": "found",
            "thread_key": str(thread_key or record.get("thread_key", "") or ""),
            "project_key": str(project_key or record.get("project_key", "") or ""),
            "question": _compact(question or record.get("question", ""), 260),
            "path": str(path),
            "dossier": _dict(record.get("dossier", {})),
            "record": record,
            "canonical_stop_reason": "final_answer_ready",
            "hidden_reasoning_exposed": False,
            "looked_up_at": utc_now(),
        }
    )


def resume_latest_market_research_dossier(
    *,
    state_dir: str | Path,
    thread_key: str = "",
    project_key: str = "",
    question: str = "",
    network_enabled: bool = False,
    web_search_fn: Callable[[str], dict[str, Any]] | None = None,
    fallback_search_fns: list[tuple[str, Callable[[str], dict[str, Any]]]] | None = None,
    open_page_fn: Callable[[str], dict[str, Any]] | None = None,
    max_actions: int = 1,
) -> dict[str, Any]:
    lookup = load_latest_market_research_dossier(state_dir=state_dir, thread_key=thread_key, project_key=project_key, question=question)
    if str(lookup.get("status", "") or "") != "found":
        missing_report = sanitize_public_metadata(
            {
                "schema": STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY_SCHEMA,
                "status": "missing",
                "thread_key": str(thread_key or ""),
                "project_key": str(project_key or ""),
                "lookup": lookup,
                "canonical_stop_reason": "needs_user_clarification",
                "public_summary": "No persisted market research dossier was available for this thread or project.",
                "hidden_reasoning_exposed": False,
                "created_at": utc_now(),
            }
        )
        if isinstance(missing_report, dict):
            missing_report["stage200_market_research_dossier_resume"] = {}
        return missing_report

    resume = resume_market_research_from_dossier(
        stage199_market_research_task_dossier=_dict(lookup.get("dossier", {})),
        question=question or str(_dict(lookup.get("dossier", {})).get("question", "") or ""),
        network_enabled=bool(network_enabled),
        web_search_fn=web_search_fn,
        fallback_search_fns=fallback_search_fns,
        open_page_fn=open_page_fn,
        max_actions=max_actions,
    )
    updated_dossier = _dict(resume.get("updated_stage199_market_research_task_dossier", {}))
    record = {}
    if updated_dossier:
        record = record_market_research_dossier(
            state_dir=state_dir,
            thread_key=thread_key or str(lookup.get("thread_key", "") or ""),
            project_key=project_key or str(lookup.get("project_key", "") or ""),
            dossier=updated_dossier,
            resume_report=resume,
            source_metadata={"source": "stage201_resume_latest"},
        )
    status = str(resume.get("status", "") or "missing")
    return sanitize_public_metadata(
        {
            "schema": STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY_SCHEMA,
            "status": status,
            "thread_key": str(thread_key or lookup.get("thread_key", "") or ""),
            "project_key": str(project_key or lookup.get("project_key", "") or ""),
            "lookup": lookup,
            "record": record,
            "stage200_market_research_dossier_resume": resume,
            "canonical_stop_reason": str(resume.get("canonical_stop_reason", "") or "final_answer_ready"),
            "public_summary": _compact(f"registry lookup={lookup.get('status', '')}; resume={status}; action={resume.get('selected_action', '')}", 260),
            "hidden_reasoning_exposed": False,
            "created_at": utc_now(),
            "authority_boundary": {
                "provider_model_calls": False,
                "memory_writes": False,
                "wechat_start": False,
                "transport_authority_widened": False,
            },
        }
    )


def _html_report(bundle: dict[str, Any]) -> str:
    reports = []
    for row in _list_dicts(bundle.get("registry_reports", [])):
        resume = _dict(row.get("stage200_market_research_dossier_resume", {}))
        reports.append(
            "<section class=\"registry\">"
            f"<h2>{html.escape(str(row.get('thread_key', '') or row.get('project_key', '') or 'market research'))}</h2>"
            f"<p><b>Status:</b> {html.escape(str(row.get('status', '')))} | "
            f"<b>Lookup:</b> {html.escape(str(_dict(row.get('lookup', {})).get('status', '')))} | "
            f"<b>Action:</b> {html.escape(str(resume.get('selected_action', '') or 'none'))}</p>"
            f"<p>{html.escape(str(row.get('public_summary', '')))}</p>"
            "</section>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage201 Market Research Dossier Registry</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}.registry{border:1px solid #ccd6d1;border-radius:6px;padding:14px;margin:14px 0}"
        "h1,h2{margin-bottom:8px}</style></head><body>"
        "<h1>Stage201 Market Research Dossier Registry</h1>"
        "<p>Persisted thread/project market research dossiers and latest-resume state.</p>"
        f"{''.join(reports)}</body></html>"
    )


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> dict[str, str]:
    html_path = Path(output)
    if html_path.suffix.lower() != ".html":
        html_path = html_path.with_suffix(".html")
    html_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = html_path.with_suffix(".json")
    jsonl_path = html_path.with_suffix(".jsonl")
    html_path.write_text(_html_report(bundle), encoding="utf-8")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("registry_reports", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_market_research_dossier_registry_bundle(
    *,
    state_dir: str | Path,
    thread_key: str = "",
    project_key: str = "",
    output: str | Path | None = None,
    dry_run: bool = True,
    fail_under: float | None = None,
) -> dict[str, Any]:
    report = resume_latest_market_research_dossier(
        state_dir=state_dir,
        thread_key=thread_key,
        project_key=project_key,
        network_enabled=False,
        max_actions=0 if dry_run else 1,
    )
    found_count = 1 if str(_dict(report.get("lookup", {})).get("status", "") or "") == "found" else 0
    bundle = {
        "schema": STAGE201_MARKET_RESEARCH_DOSSIER_REGISTRY_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed" if found_count else "missing",
        "registry_reports": [report],
        "summary": {"found_count": found_count, "report_count": 1},
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and found_count < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return sanitize_public_metadata(bundle)
