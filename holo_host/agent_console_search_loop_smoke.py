from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .agent_console_live_smoke import evaluate_agent_console_live_smoke_fixture
from .common import utc_now
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata

STAGE209_AGENT_CONSOLE_SEARCH_LOOP_SMOKE_SCHEMA = "holo.stage209.agent_console_search_loop_smoke.v1"
STAGE209_AGENT_CONSOLE_SEARCH_LOOP_RESULT_SCHEMA = "holo.stage209.agent_console_search_loop_result.v1"
STAGE209_AGENT_CONSOLE_SEARCH_LOOP_SCORECARD_SCHEMA = "holo.stage209.agent_console_search_loop_scorecard.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage209" / "stage209_agent_console_search_loop_smoke.html"
WEAK_URL = "https://example.com/codex-overview"
OFFICIAL_CODEX_URL = "https://developers.openai.com/codex/cli"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _source_urls_from_crawler(crawler: dict[str, Any]) -> list[str]:
    return [str(url) for url in list(crawler.get("source_urls", []) or []) if str(url or "").strip()]


def _observed_urls(crawler: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for row in _list_dicts(crawler.get("web_observation_ledger", [])):
        for url in list(row.get("source_urls", []) or []):
            text = str(url or "").strip()
            if text and text not in urls:
                urls.append(text)
        for result in _list_dicts(row.get("results", [])):
            text = str(result.get("url", "") or "").strip()
            if text and text not in urls:
                urls.append(text)
    return urls


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def default_agent_console_search_loop_smoke_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage209-codex-cli-multistep",
            "thread_key": "holo_cli:stage209",
            "chat_name": "HoloCLI",
            "channel": "holo_cli",
            "user_text": "search official Codex CLI docs and cite sources",
            "runner_text": "I will search this now.",
            "search_mode": "weak_then_official",
            "expected_source_url": OFFICIAL_CODEX_URL,
            "expected_status": "passed",
        }
    ]


def build_agent_console_search_loop_smoke_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    crawler = _dict(result.get("stage186_live_crawler_search", {}))
    console = str(result.get("rendered_console", "") or "")
    final_text = str(result.get("final_text", "") or "")
    source_urls = _source_urls_from_crawler(crawler)
    observed_urls = _observed_urls(crawler)
    query_count = int(crawler.get("query_count", 0) or 0)
    ok, private_paths = assert_no_private_reasoning(result)
    checks = {
        "reply_path_ran": _check(bool(result.get("reply_result")), score=1.0 if result.get("reply_result") else 0.0, reason="reply_result_missing"),
        "continued_after_weak_source": _check(
            query_count >= 2 and WEAK_URL in observed_urls and OFFICIAL_CODEX_URL in source_urls,
            score=1.0 if query_count >= 2 and WEAK_URL in observed_urls and OFFICIAL_CODEX_URL in source_urls else 0.0,
            reason="crawler_did_not_continue_from_weak_source",
        ),
        "weak_source_not_promoted": _check(
            WEAK_URL not in source_urls and WEAK_URL not in final_text,
            score=1.0 if WEAK_URL not in source_urls and WEAK_URL not in final_text else 0.0,
            reason="weak_source_promoted",
        ),
        "official_source_in_final": _check(
            OFFICIAL_CODEX_URL in source_urls and OFFICIAL_CODEX_URL in final_text,
            score=1.0 if OFFICIAL_CODEX_URL in source_urls and OFFICIAL_CODEX_URL in final_text else 0.0,
            reason="official_source_missing",
        ),
        "console_multistep_crawl_trace": _check(
            console.count("[crawl:query]") >= 2 and "[crawl:stop] status=sufficient reason=sufficient_evidence" in console,
            score=1.0 if console.count("[crawl:query]") >= 2 and "[crawl:stop] status=sufficient reason=sufficient_evidence" in console else 0.0,
            reason="multistep_crawl_trace_missing",
        ),
        "model_decision_matches_crawler_action": _check(
            "[model_decide] selected=web_search" in console
            and "[model_decide] selected=answer_direct need=web_observation_ledger" not in console,
            score=1.0
            if "[model_decide] selected=web_search" in console
            and "[model_decide] selected=answer_direct need=web_observation_ledger" not in console
            else 0.0,
            reason="model_decide_misreported_as_answer_direct",
        ),
        "stop_reason_known": _check(
            str(result.get("canonical_stop_reason", "") or "") not in {"", "unknown"},
            score=1.0 if str(result.get("canonical_stop_reason", "") or "") not in {"", "unknown"} else 0.0,
            reason="stop_reason_unknown",
        ),
        "privacy": _check(ok, score=1.0 if ok else 0.0, reason="private_reasoning:" + ",".join(private_paths[:3])),
    }
    score = round(sum(float(row["score"]) for row in checks.values()) / max(1, len(checks)), 4)
    return {
        "schema": STAGE209_AGENT_CONSOLE_SEARCH_LOOP_SCORECARD_SCHEMA,
        "score": score,
        "passed": all(bool(row["passed"]) for row in checks.values()),
        "checks": checks,
    }


def evaluate_agent_console_search_loop_smoke_fixture(
    fixture: dict[str, Any],
    *,
    state_dir: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool = True,
) -> dict[str, Any]:
    source = dict(fixture or {})
    source.setdefault("search_mode", "weak_then_official")
    source.setdefault("expected_source_url", OFFICIAL_CODEX_URL)
    result = dict(
        evaluate_agent_console_live_smoke_fixture(
            source,
            state_dir=state_dir,
            dry_run=dry_run,
            network_enabled=network_enabled,
        )
    )
    result["schema"] = STAGE209_AGENT_CONSOLE_SEARCH_LOOP_RESULT_SCHEMA
    scorecard = build_agent_console_search_loop_smoke_scorecard(result)
    result["scorecard"] = scorecard
    result["status"] = "passed" if scorecard["passed"] else "failed"
    result["failure_reasons"] = [
        str(row.get("reason", "") or key)
        for key, row in dict(scorecard.get("checks", {})).items()
        if isinstance(row, dict) and not bool(row.get("passed", False))
    ]
    result["created_at"] = utc_now()
    return sanitize_public_metadata(result)


def _write_artifacts(bundle: dict[str, Any], output: str | Path) -> None:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_path.with_suffix(".json")
    jsonl_path = output_path.with_suffix(".jsonl")
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    jsonl_path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in list(bundle.get("results", []) or [])) + "\n",
        encoding="utf-8",
    )
    rows = []
    for result in list(bundle.get("results", []) or []):
        rows.append(
            "<section>"
            f"<h2>{html.escape(str(result.get('fixture_id', '')))} - {html.escape(str(result.get('status', '')))}</h2>"
            f"<p><b>Score:</b> {html.escape(str(_dict(result.get('scorecard', {})).get('score', '')))}</p>"
            f"<p><b>Stop:</b> {html.escape(str(result.get('canonical_stop_reason', '')))}</p>"
            f"<pre>{html.escape(str(result.get('rendered_console', '') or ''))}</pre>"
            "</section>"
        )
    output_path.write_text(
        "\n".join(
            [
                "<!doctype html><meta charset='utf-8'>",
                "<title>Stage209 Agent Console Search Loop Smoke</title>",
                "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:1100px;margin:32px auto;line-height:1.45}"
                "pre{white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;padding:12px;border-radius:6px}"
                "section{border-top:1px solid #d0d7de;padding-top:18px;margin-top:18px}</style>",
                "<h1>Stage209 Agent Console Search Loop Smoke</h1>",
                f"<p>Status: <b>{html.escape(str(bundle.get('status', '')))}</b> | Score: {html.escape(str(bundle.get('score', '')))}</p>",
                *rows,
            ]
        ),
        encoding="utf-8",
    )


def run_agent_console_search_loop_smoke(
    *,
    output: str | Path | None = None,
    state_dir: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool = True,
    fail_under: float | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_agent_console_search_loop_smoke_fixtures())
    output_path = Path(output) if output is not None else DEFAULT_OUTPUT
    state_root = Path(state_dir) if state_dir is not None else output_path.with_suffix("").parent / "stage209_state"
    results = [
        evaluate_agent_console_search_loop_smoke_fixture(
            row,
            state_dir=state_root / str(row.get("fixture_id", "fixture")),
            dry_run=dry_run,
            network_enabled=network_enabled,
        )
        for row in rows
    ]
    score = round(
        sum(float(_dict(result.get("scorecard", {})).get("score", 0.0) or 0.0) for result in results)
        / max(1, len(results)),
        4,
    )
    bundle = {
        "schema": STAGE209_AGENT_CONSOLE_SEARCH_LOOP_SMOKE_SCHEMA,
        "status": "passed" if all(str(row.get("status", "")) == "passed" for row in results) else "failed",
        "score": score,
        "fixture_count": len(results),
        "dry_run": bool(dry_run),
        "network_enabled": bool(network_enabled),
        "results": results,
        "created_at": utc_now(),
    }
    if fail_under is not None:
        bundle["fail_under"] = float(fail_under)
        bundle["fail_under_triggered"] = score < float(fail_under)
    else:
        bundle["fail_under_triggered"] = False
    if output is not None:
        _write_artifacts(bundle, output_path)
    return sanitize_public_metadata(bundle)
