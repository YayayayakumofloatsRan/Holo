from __future__ import annotations

from collections import Counter

from kernel_v3.contracts import JsonObject
from kernel_v3.journal import JournalStore


def retrieval_behavior_benchmark(journal: JournalStore, task_id: str) -> JsonObject:
    records = journal.records(task_id=task_id)
    retrieval_reports = [record.data for record in records if record.kind == "retrieval_report"]
    search_attempts = [record.data for record in records if record.kind == "retrieval_search_attempt"]
    fetch_attempts = [record.data for record in records if record.kind == "retrieval_fetch_attempt"]
    evidence = [record.data for record in records if record.kind == "retrieval_evidence"]
    citations = [record.data for record in records if record.kind == "retrieval_citation"]
    critics = [record.data for record in records if record.kind == "retrieval_operator_critic"]
    final_answers = [record.data for record in records if record.kind == "agent_final_answer"]
    failure_reports = [record.data for record in records if record.kind == "agent_failure_report"]

    queries = [str(item.get("query") or "") for item in search_attempts if item.get("query")]
    unique_queries = sorted(set(queries))
    fetch_status_counts = Counter(str(item.get("status") or "unknown") for item in fetch_attempts)
    search_status_counts = Counter(str(item.get("status") or "unknown") for item in search_attempts)
    source_ids = [str(item.get("source_id") or "") for item in fetch_attempts if item.get("source_id")]
    unique_source_ids = set(source_ids)
    latest_report = retrieval_reports[-1] if retrieval_reports else {}
    latest_report_diagnostics = latest_report.get("diagnostics") if isinstance(latest_report.get("diagnostics"), dict) else {}
    latest_critic = critics[-1] if critics else {}
    final_text = _latest_answer_text(final_answers)
    return {
        "schema": "holo.kernel_v3.retrieval_behavior_benchmark.v1",
        "task_id": task_id,
        "status": _benchmark_status(retrieval_reports=retrieval_reports, final_answers=final_answers, failure_reports=failure_reports),
        "retrieval_run_count": len(retrieval_reports),
        "search_attempt_count": len(search_attempts),
        "query_count": len(queries),
        "unique_query_count": len(unique_queries),
        "query_repetition_rate": _repetition_rate(len(queries), len(unique_queries)),
        "fetch_attempt_count": len(fetch_attempts),
        "successful_fetch_count": fetch_status_counts.get("ok", 0),
        "fetch_success_rate": _rate(fetch_status_counts.get("ok", 0), len(fetch_attempts)),
        "unique_fetch_source_count": len(unique_source_ids),
        "fetch_source_repetition_rate": _repetition_rate(len(source_ids), len(unique_source_ids)),
        "evidence_count": len(evidence),
        "citation_count": len(citations),
        "final_answer_chars": len(final_text),
        "latest_report_status": latest_report.get("status"),
        "latest_failure_mode": _nested_string(latest_report_diagnostics, "failure_attribution", "primary_failure_mode"),
        "latest_next_strategy_hint": _nested_string(latest_report_diagnostics, "failure_attribution", "next_strategy_hint"),
        "latest_next_tool_actions": _bounded_actions(latest_report_diagnostics.get("next_tool_actions")),
        "latest_research_graph_summary": latest_report_diagnostics.get("research_graph", {}).get("diagnostics")
        if isinstance(latest_report_diagnostics.get("research_graph"), dict)
        else {},
        "latest_operator_critic": {
            "primary_failure_mode": latest_critic.get("primary_failure_mode"),
            "next_strategy_hint": latest_critic.get("next_strategy_hint"),
            "next_tool_action_count": len(latest_critic.get("next_tool_actions") or [])
            if isinstance(latest_critic.get("next_tool_actions"), list)
            else 0,
        },
        "search_status_counts": dict(search_status_counts),
        "fetch_status_counts": dict(fetch_status_counts),
        "queries": unique_queries[:64],
    }


def _benchmark_status(*, retrieval_reports: list[JsonObject], final_answers: list[JsonObject], failure_reports: list[JsonObject]) -> str:
    if final_answers:
        return "final_answer"
    if failure_reports:
        return "failure_report"
    if retrieval_reports:
        latest = retrieval_reports[-1]
        return "retrieval_" + str(latest.get("status") or "unknown")
    return "missing"


def _latest_answer_text(final_answers: list[JsonObject]) -> str:
    if not final_answers:
        return ""
    latest = final_answers[-1]
    answer = latest.get("answer")
    if isinstance(answer, str):
        return answer
    payload = latest.get("final_answer")
    if isinstance(payload, dict) and isinstance(payload.get("answer"), str):
        return str(payload["answer"])
    return ""


def _repetition_rate(total: int, unique: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0, total - unique) / total, 4)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _nested_string(data: JsonObject, *path: str) -> str | None:
    current: object = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return str(current) if isinstance(current, str) and current else None


def _bounded_actions(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value[:24] if isinstance(item, dict)]
