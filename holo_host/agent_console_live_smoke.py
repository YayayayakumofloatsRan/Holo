from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path
from typing import Any

from .capabilities import CapabilityBroker
from .common import compact_text, stable_digest, utc_now
from .config import load_config
from .interactive_cli import InteractiveCliSession
from .kernel_metadata_sanitizer import assert_no_private_reasoning, sanitize_public_metadata
from .models import CodexResult, ProcessorTaskResult
from .reply_api import HoloReplyService
from .store import QueueStore

STAGE208_AGENT_CONSOLE_LIVE_SMOKE_SCHEMA = "holo.stage208.agent_console_live_smoke.v1"
STAGE208_AGENT_CONSOLE_LIVE_SMOKE_RESULT_SCHEMA = "holo.stage208.agent_console_live_smoke_result.v1"
STAGE208_AGENT_CONSOLE_SCORECARD_SCHEMA = "holo.stage208.agent_console_scorecard.v1"

DEFAULT_OUTPUT = Path("artifacts") / "stage208" / "stage208_agent_console_live_smoke.html"


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in list(value or []) if isinstance(item, dict)] if isinstance(value, list) else []


def _source_urls_from_crawler(crawler: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for url in list(crawler.get("source_urls", []) or []):
        text = str(url or "").strip()
        if text and text not in urls:
            urls.append(text)
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


class _SmokeRunner:
    def __init__(self, reply_text: str = "I will search this now.") -> None:
        self.reply_text = reply_text
        self.calls: list[tuple[str, str]] = []
        self.task_calls: list[dict[str, Any]] = []

    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        self.calls.append((prompt, session_id))
        return CodexResult(reply_text=self.reply_text, session_id="stage208-smoke-session", returncode=0)

    def run_task(self, request: Any) -> ProcessorTaskResult:
        self.task_calls.append(request.to_dict() if hasattr(request, "to_dict") else dict(request or {}))
        return ProcessorTaskResult(
            task_type=str(getattr(request, "task_type", "") or "smoke"),
            text=json.dumps({"summary": "stage208 local deterministic task runner"}, ensure_ascii=False),
            session_id="stage208-smoke-task",
            returncode=0,
            output_schema=str(getattr(request, "output_schema", "") or ""),
        )


class _SmokeMemory:
    def __init__(self) -> None:
        self.observed_records: list[dict[str, Any]] = []
        self.archived_records: list[dict[str, Any]] = []
        self.action_records: list[dict[str, Any]] = []
        self.consciousness_records: list[dict[str, Any]] = []
        self.recall_records: list[dict[str, Any]] = []

    def sidecar_packet(self, query: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        action = {"action_type": "reply_once", "score": 0.74, "reason": "stage208_smoke_reply_path"}
        return {
            "tier": "smoke",
            "selected_action": action,
            "action_market": [action, {"action_type": "external_lookup", "score": 0.31}],
            "intent_state": {"intent_type": "web_lookup", "confidence": 0.8},
            "expression_budget": 1,
            "selected_memory_ids": [],
            "relevant_memories": [],
            "recall_reconstruction": {"summary": ""},
            "graph_trace_summary": "",
            "retrieval_mode": "stage208_smoke",
            "graph_confidence": 0.0,
        }

    def record_action_selection(self, **kwargs: Any) -> dict[str, Any]:
        self.action_records.append(dict(kwargs))
        return {"status": "recorded", "source": "stage208_smoke_memory"}

    def record_consciousness_entry(self, **kwargs: Any) -> dict[str, Any]:
        self.consciousness_records.append(dict(kwargs))
        return {"status": "recorded", "source": "stage208_smoke_memory"}

    def update_active_thread_state(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "updated", "source": "stage208_smoke_memory", "summary": _compact(kwargs.get("text", ""))}

    def record_recall(self, selected_ids: list[Any], *, success: bool = False) -> dict[str, Any]:
        row = {"selected_ids": list(selected_ids or []), "success": bool(success)}
        self.recall_records.append(row)
        return {"status": "recorded", **row}

    def repair_reply(self, user_text: str, reply_text: str, *, max_passes: int = 2) -> dict[str, Any]:
        return {"final_draft": str(reply_text or ""), "outcome": "clean_pass", "max_passes": int(max_passes)}

    def appraise_outcome(self, **kwargs: Any) -> dict[str, Any]:
        return {"status": "recorded", "source": "stage208_smoke_memory", "metadata": sanitize_public_metadata(kwargs)}

    def observe_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        row = {
            "status": "observed",
            "user_text": user_text,
            "assistant_text": assistant_text,
            "source": source,
            "tags": list(tags or []),
            "turn_id": turn_id,
            "metadata": sanitize_public_metadata(metadata),
        }
        self.observed_records.append(row)
        return row

    def archive_turn(
        self,
        user_text: str,
        assistant_text: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        row = {
            "status": "archived",
            "user_text": user_text,
            "assistant_text": assistant_text,
            "source": source,
            "tags": list(tags or []),
            "turn_id": turn_id,
            "metadata": sanitize_public_metadata(metadata),
        }
        self.archived_records.append(row)
        return row


class _Stage208CrawlerBroker(CapabilityBroker):
    def __init__(self, config: Any, *, search_mode: str = "ok") -> None:
        super().__init__(config)
        self.search_mode = search_mode

    def _external_lookup(self, text: str) -> dict[str, Any]:
        query = str(text or "")
        if self.search_mode == "fail":
            return {
                "query": query,
                "status": "error",
                "provider": "stage208_mock_search",
                "results": [],
                "source_urls": [],
                "error": "simulated_search_failure",
            }
        if self.search_mode == "weak_then_official":
            lowered = query.lower()
            if "official" not in lowered and "docs" not in lowered and "documentation" not in lowered:
                return {
                    "query": query,
                    "status": "ok",
                    "provider": "stage208_mock_search",
                    "results": [
                        {
                            "title": "Weak Codex overview",
                            "url": "https://example.com/codex-overview",
                            "snippet": "A weak third-party overview.",
                        }
                    ],
                    "source_urls": ["https://example.com/codex-overview"],
                }
        if "official" not in query.lower() and "docs" not in query.lower() and "codex" not in query.lower():
            return {
                "query": query,
                "status": "ok",
                "provider": "stage208_mock_search",
                "results": [
                    {
                        "title": "Weak Codex overview",
                        "url": "https://example.com/codex-overview",
                        "snippet": "A weak third-party overview.",
                    }
                ],
                "source_urls": ["https://example.com/codex-overview"],
            }
        return {
            "query": query,
            "status": "ok",
            "provider": "stage208_mock_search",
            "results": [
                {
                    "title": "OpenAI Codex CLI documentation",
                    "url": "https://developers.openai.com/codex/cli",
                    "snippet": "Official Codex CLI documentation for a terminal coding agent.",
                }
            ],
            "source_urls": ["https://developers.openai.com/codex/cli"],
        }

    def _open_page_for_crawler(self, url: str) -> dict[str, Any]:
        if "developers.openai.com/codex/cli" in str(url):
            return {
                "url": str(url),
                "status": "ok",
                "provider": "stage208_mock_page",
                "html": (
                    "<html><title>Codex CLI</title><body>"
                    "Codex CLI is OpenAI official documentation for a terminal coding agent. "
                    "It can inspect code, edit files, run commands, and show auditable progress."
                    "</body></html>"
                ),
            }
        return {
            "url": str(url),
            "status": "ok",
            "provider": "stage208_mock_page",
            "html": "<html><title>Weak</title><body>Weak third-party overview.</body></html>",
        }


def _close_service(service: HoloReplyService) -> None:
    try:
        service.store.close()
    finally:
        for handler in list(service.logger.handlers):
            handler.close()
            service.logger.removeHandler(handler)


def _service(
    state_dir: Path,
    *,
    network_enabled: bool,
    search_mode: str,
    runner_text: str,
) -> HoloReplyService:
    config = load_config(repo_root=state_dir)
    config.runtime.network_enabled = bool(network_enabled)
    config.memory.auto_observe = False
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    service = HoloReplyService(config, store=store, runner=_SmokeRunner(runner_text), memory=_SmokeMemory())
    service.capabilities = _Stage208CrawlerBroker(config, search_mode=search_mode)
    return service


def default_agent_console_live_smoke_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "stage208-codex-cli-docs",
            "thread_key": "holo_cli:stage208",
            "chat_name": "HoloCLI",
            "channel": "holo_cli",
            "user_text": "search official Codex CLI docs and cite sources",
            "runner_text": "I will search this now.",
            "search_mode": "ok",
            "expected_source_url": "https://developers.openai.com/codex/cli",
            "expected_status": "passed",
        }
    ]


def _check(passed: bool, *, score: float, reason: str = "") -> dict[str, Any]:
    return {"passed": bool(passed), "score": round(max(0.0, min(1.0, float(score or 0.0))), 4), "reason": reason}


def build_agent_console_live_smoke_scorecard(result: dict[str, Any]) -> dict[str, Any]:
    crawler = _dict(result.get("stage186_live_crawler_search", {}))
    console = str(result.get("rendered_console", "") or "")
    final_text = str(result.get("final_text", "") or "")
    expected_url = str(result.get("expected_source_url", "") or "")
    source_urls = _source_urls_from_crawler(crawler)
    final_lower = final_text.lower()
    ok, private_paths = assert_no_private_reasoning(result)
    crawler_status = str(crawler.get("status", "") or "")
    expected_status = str(result.get("expected_status", "passed") or "passed")
    is_failure_fixture = expected_status == "failed"
    checks = {
        "reply_path_ran": _check(bool(result.get("reply_result")), score=1.0 if result.get("reply_result") else 0.0, reason="reply_result_missing"),
        "crawler_executed": _check(bool(crawler), score=1.0 if crawler else 0.0, reason="stage186_crawler_missing"),
        "crawler_sufficient": _check(
            crawler_status == "sufficient" if not is_failure_fixture else crawler_status == "failed",
            score=1.0 if ((crawler_status == "sufficient" and not is_failure_fixture) or (crawler_status == "failed" and is_failure_fixture)) else 0.0,
            reason=f"unexpected_crawler_status:{crawler_status}",
        ),
        "source_url_present": _check(
            bool(is_failure_fixture or (expected_url and expected_url in source_urls and expected_url in final_text)),
            score=1.0 if is_failure_fixture or (expected_url and expected_url in source_urls and expected_url in final_text) else 0.0,
            reason="expected_source_url_missing",
        ),
        "console_crawl_trace": _check(
            "[crawl:query]" in console and "[crawl:stop]" in console,
            score=1.0 if "[crawl:query]" in console and "[crawl:stop]" in console else 0.0,
            reason="crawl_trace_missing",
        ),
        "final_no_future_intent": _check(
            "will search" not in final_lower and "need to complete web_search" not in final_lower,
            score=1.0 if "will search" not in final_lower and "need to complete web_search" not in final_lower else 0.0,
            reason="future_intent_overclaim",
        ),
        "failure_reports_attempt": _check(
            (not is_failure_fixture) or ("attempted web_search" in final_lower and "simulated_search_failure" in final_lower),
            score=1.0 if (not is_failure_fixture) or ("attempted web_search" in final_lower and "simulated_search_failure" in final_lower) else 0.0,
            reason="failed_search_not_reported",
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
        "schema": STAGE208_AGENT_CONSOLE_SCORECARD_SCHEMA,
        "score": score,
        "passed": all(bool(row["passed"]) for row in checks.values()),
        "checks": checks,
    }


def evaluate_agent_console_live_smoke_fixture(
    fixture: dict[str, Any],
    *,
    state_dir: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool = True,
) -> dict[str, Any]:
    source = dict(fixture or {})
    fixture_id = str(source.get("fixture_id", "") or "stage208-smoke")
    state_root = Path(state_dir) if state_dir is not None else Path(tempfile.mkdtemp(prefix="stage208_smoke_"))
    state_root.mkdir(parents=True, exist_ok=True)
    user_text = str(source.get("user_text", "") or "search official Codex CLI docs and cite sources")
    service = _service(
        state_root,
        network_enabled=bool(network_enabled),
        search_mode=str(source.get("search_mode", "ok") or "ok") if dry_run else str(source.get("search_mode", "ok") or "ok"),
        runner_text=str(source.get("runner_text", "") or "I will search this now."),
    )
    try:
        reply_result = service.handle_reply(
            {
                "chat_name": str(source.get("chat_name", "") or "HoloCLI"),
                "sender": str(source.get("sender", "") or "Operator"),
                "text": user_text,
                "channel": str(source.get("channel", "") or "holo_cli"),
                "thread_key": str(source.get("thread_key", "") or "holo_cli:stage208"),
                "message_id": fixture_id + ":" + stable_digest(user_text, limit=10),
            }
        )
    finally:
        _close_service(service)
    public_reply = sanitize_public_metadata(reply_result)
    session = InteractiveCliSession(
        thread_key=str(source.get("thread_key", "") or "holo_cli:stage208"),
        chat_name=str(source.get("chat_name", "") or "HoloCLI"),
        channel=str(source.get("channel", "") or "holo_cli"),
    )
    session.record_turn(public_reply, user_text=user_text, transport="stage208_smoke_reply_path")
    rendered_console = session.render_console_turn(use_ansi=False)
    crawler = _dict(public_reply.get("stage186_live_crawler_search", {}))
    expected_status = str(source.get("expected_status", "passed") or "passed")
    result = {
        "schema": STAGE208_AGENT_CONSOLE_LIVE_SMOKE_RESULT_SCHEMA,
        "fixture_id": fixture_id,
        "status": "unknown",
        "expected_status": expected_status,
        "user_text": user_text,
        "final_text": str(public_reply.get("text", "") or ""),
        "canonical_stop_reason": str(public_reply.get("canonical_stop_reason", "") or ""),
        "canonical_stop_source": str(public_reply.get("canonical_stop_source", "") or ""),
        "expected_source_url": str(source.get("expected_source_url", "") or ""),
        "reply_result": public_reply,
        "stage153_agent_event_stream": _dict(session.last_event_stream),
        "stage191_public_thought_stream": _dict(public_reply.get("stage191_public_thought_stream", {})),
        "stage207_agent_console": _dict(public_reply.get("stage207_agent_console", {})),
        "stage186_live_crawler_search": crawler,
        "web_observation_ledger": list(public_reply.get("web_observation_ledger", []) or []),
        "rendered_console": rendered_console,
        "created_at": utc_now(),
    }
    scorecard = build_agent_console_live_smoke_scorecard(result)
    result["scorecard"] = scorecard
    result["status"] = "passed" if scorecard["passed"] and expected_status == "passed" else "failed"
    if expected_status == "failed":
        result["status"] = "failed" if not scorecard["passed"] or str(crawler.get("status", "") or "") == "failed" else "passed"
    result["failure_reasons"] = [
        str(row.get("reason", "") or key)
        for key, row in dict(scorecard.get("checks", {})).items()
        if isinstance(row, dict) and not bool(row.get("passed", False))
    ]
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
                "<title>Stage208 Agent Console Live Smoke</title>",
                "<style>body{font-family:system-ui,Segoe UI,sans-serif;max-width:1100px;margin:32px auto;line-height:1.45}"
                "pre{white-space:pre-wrap;background:#f6f8fa;border:1px solid #d0d7de;padding:12px;border-radius:6px}"
                "section{border-top:1px solid #d0d7de;padding-top:18px;margin-top:18px}</style>",
                "<h1>Stage208 Agent Console Live Smoke</h1>",
                f"<p>Status: <b>{html.escape(str(bundle.get('status', '')))}</b> | Score: {html.escape(str(bundle.get('score', '')))}</p>",
                *rows,
            ]
        ),
        encoding="utf-8",
    )


def run_agent_console_live_smoke(
    *,
    output: str | Path | None = None,
    state_dir: str | Path | None = None,
    dry_run: bool = True,
    network_enabled: bool = True,
    fail_under: float | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_agent_console_live_smoke_fixtures())
    output_path = Path(output) if output is not None else DEFAULT_OUTPUT
    state_root = Path(state_dir) if state_dir is not None else output_path.with_suffix("").parent / "stage208_state"
    results = [
        evaluate_agent_console_live_smoke_fixture(
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
        "schema": STAGE208_AGENT_CONSOLE_LIVE_SMOKE_SCHEMA,
        "status": "passed" if all(str(row.get("status", "")) == str(row.get("expected_status", "passed")) for row in results) else "failed",
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
