from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now
from .kernel_metadata_sanitizer import sanitize_public_metadata

STAGE178_EVIDENCE_ACTION_REMEDIATION_SCHEMA = "holo.stage178.evidence_action_remediation.v1"
STAGE178_EVIDENCE_ACTION_REMEDIATION_BUNDLE_SCHEMA = "holo.stage178.evidence_action_remediation_bundle.v1"
STAGE178_EVIDENCE_ACTION_REMEDIATION_ACTION_SCHEMA = "holo.stage178.evidence_action_remediation_action.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _compact(value: Any, limit: int = 260) -> str:
    return compact_text(" ".join(str(value or "").split()), limit)


def _public(value: Any) -> Any:
    clean = sanitize_public_metadata(value)
    if isinstance(clean, dict):
        return {str(key): _public(item) for key, item in clean.items() if str(key) != "reasoning_content_retained_count"}
    if isinstance(clean, list):
        return [_public(item) for item in clean]
    return clean


def _action(
    *,
    issue: dict[str, Any],
    action_type: str,
    required_tool: str,
    reason: str,
    success_criteria: list[str],
    priority: str = "high",
    canonical_stop_reason: str = "evidence_exhausted",
) -> dict[str, Any]:
    issue_id = str(issue.get("issue_id", "") or stable_digest(json.dumps(issue, ensure_ascii=False), limit=10))
    return {
        "schema": STAGE178_EVIDENCE_ACTION_REMEDIATION_ACTION_SCHEMA,
        "action_id": "stage178:" + stable_digest(issue_id, action_type, required_tool, limit=12),
        "issue_id": issue_id,
        "domain": str(issue.get("domain", "") or "general"),
        "issue_type": str(issue.get("issue_type", "") or "unknown"),
        "action_type": action_type,
        "required_tool": required_tool,
        "priority": priority,
        "reason": _compact(reason, 420),
        "required_evidence": [str(item) for item in list(issue.get("required_evidence", []) or []) if str(item).strip()],
        "success_criteria": list(success_criteria),
        "canonical_stop_reason": canonical_stop_reason,
    }


def _actions_for_issue(issue: dict[str, Any]) -> list[dict[str, Any]]:
    issue_type = str(issue.get("issue_type", "") or "unknown").strip()
    domain = str(issue.get("domain", "") or "general").strip()
    claim = _compact(issue.get("claim", ""), 180)
    if issue_type == "source_missing":
        action_type = "primary_literature_search" if "literature" in domain else "primary_source_search"
        return [
            _action(
                issue=issue,
                action_type=action_type,
                required_tool="web_search",
                reason=f"External source evidence is missing for claim: {claim}",
                success_criteria=["primary source retrieved", "source authority classified", "citation usable"],
            )
        ]
    if issue_type in {"derivation_gap", "math_gap"}:
        return [
            _action(
                issue=issue,
                action_type="derive_or_request_assumptions",
                required_tool="answer_direct",
                reason=f"The reasoning chain has a derivation gap for claim: {claim}",
                success_criteria=["assumptions listed", "intermediate lemma or counterexample identified", "final answer bounded"],
                canonical_stop_reason="needs_user_clarification",
            )
        ]
    if issue_type == "experiment_failed":
        return [
            _action(
                issue=issue,
                action_type="inspect_experiment_artifacts",
                required_tool="file_read",
                reason="Experiment status is failed or unverified; inspect logs, metrics, and checkpoints before claiming progress.",
                success_criteria=["logs inspected", "failure reason identified", "last valid metric recorded"],
                canonical_stop_reason="tool_failure_report",
            ),
            _action(
                issue=issue,
                action_type="plan_experiment_retry",
                required_tool="project_state_update",
                reason="A failed experiment needs a bounded retry or rollback plan before autonomous continuation.",
                success_criteria=["retry parameters recorded", "expected artifact named", "stop condition defined"],
                canonical_stop_reason="tool_failure_report",
            ),
        ]
    if issue_type == "memory_unsupported":
        return [
            _action(
                issue=issue,
                action_type="run_memory_recall",
                required_tool="memory_recall",
                reason=f"Visible memory detail is unsupported for claim: {claim}",
                success_criteria=["memory observation ledger exists", "selected ids or bounded missing-source answer recorded"],
            )
        ]
    if issue_type == "tool_unexecuted":
        return [
            _action(
                issue=issue,
                action_type="execute_required_tool_or_repair_claim",
                required_tool="tool_decision_loop",
                reason=f"A tool-backed claim lacks an executed tool ledger: {claim}",
                success_criteria=["tool ledger exists or claim removed", "final answer states evidence boundary"],
            )
        ]
    if issue_type in {"metric_conflict", "evidence_conflict"}:
        return [
            _action(
                issue=issue,
                action_type="compare_conflicting_evidence",
                required_tool="market_research_report" if "market" in domain else "answer_direct",
                reason=f"Evidence conflicts for claim: {claim}",
                success_criteria=["conflict rows listed", "source snippets compared", "no settled claim until resolved"],
                canonical_stop_reason="evidence_exhausted",
            )
        ]
    if issue_type in {"period_mismatch", "scope_mismatch"}:
        return [
            _action(
                issue=issue,
                action_type="clarify_or_refetch_scope",
                required_tool="web_search",
                reason=f"Requested scope or period does not match current evidence for claim: {claim}",
                success_criteria=["requested scope explicit", "evidence scope aligned", "mismatch resolved or clarified"],
                canonical_stop_reason="needs_user_clarification",
            )
        ]
    return [
        _action(
            issue=issue,
            action_type="diagnose_evidence_gap",
            required_tool="answer_direct",
            reason=f"Unclassified evidence gap requires explicit diagnosis before finalization: {claim}",
            success_criteria=["gap classified", "next observation named", "final answer bounded"],
        )
    ]


def _operator_message(issues: list[dict[str, Any]], actions: list[dict[str, Any]]) -> str:
    if not issues:
        return "No evidence-action remediation is required; the answer can finalize if other gates are clean."
    domains = sorted({str(issue.get("domain", "") or "general") for issue in issues})
    action_names = ", ".join(str(action.get("action_type", "")) for action in actions[:5])
    return _compact(
        f"Cannot finalize without remediation. Domains: {', '.join(domains)}. Next actions: {action_names}.",
        700,
    )


def _recommended_stop_reason(actions: list[dict[str, Any]]) -> str:
    if not actions:
        return "final_answer_ready"
    reasons = [str(action.get("canonical_stop_reason", "") or "") for action in actions]
    if "tool_failure_report" in reasons:
        return "tool_failure_report"
    if "needs_user_clarification" in reasons:
        return "needs_user_clarification"
    return "needs_evidence_action"


def _canonical_stop_reason(recommended: str) -> str:
    if recommended in {"final_answer_ready", "tool_failure_report", "needs_user_clarification"}:
        return recommended
    return "evidence_exhausted"


def build_evidence_action_remediation(
    issues: list[dict[str, Any]] | None,
    *,
    source_stage: str = "direct",
) -> dict[str, Any]:
    normalized_issues = _list_dicts(issues or [])
    actions: list[dict[str, Any]] = []
    for issue in normalized_issues:
        actions.extend(_actions_for_issue(issue))
    can_finalize = not normalized_issues and not actions
    recommended = _recommended_stop_reason(actions)
    report = {
        "schema": STAGE178_EVIDENCE_ACTION_REMEDIATION_SCHEMA,
        "source_stage": source_stage,
        "status": "ready_to_finalize" if can_finalize else "remediation_required",
        "can_finalize": bool(can_finalize),
        "issue_count": len(normalized_issues),
        "action_count": len(actions),
        "issues": normalized_issues,
        "actions": actions,
        "operator_message": _operator_message(normalized_issues, actions),
        "recommended_stop_reason": recommended,
        "canonical_stop_reason": _canonical_stop_reason(recommended),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    public = _dict(_public(report))
    public.setdefault("issues", [])
    public.setdefault("actions", [])
    return public


def build_evidence_action_remediation_from_stage177(stage177_result: dict[str, Any]) -> dict[str, Any]:
    result = _dict(stage177_result)
    issues: list[dict[str, Any]] = []
    for action in _list_dicts(result.get("remediation_actions", [])):
        action_type = str(action.get("action_type", "") or "")
        issue_type = {
            "retry_primary_source_search": "source_missing",
            "request_filing_text_or_open_primary_url": "source_missing",
            "retrieve_complete_filing_text": "source_missing",
            "produce_metric_conflict_report": "metric_conflict",
            "clarify_or_refetch_period": "period_mismatch",
        }.get(action_type, "unknown")
        issues.append(
            {
                "issue_id": str(action.get("action_id", "") or stable_digest(action_type, limit=10)),
                "domain": "market_research",
                "issue_type": issue_type,
                "claim": str(action.get("reason", "") or result.get("operator_message", "") or ""),
                "required_evidence": list(action.get("required_evidence", []) or []),
            }
        )
    return build_evidence_action_remediation(issues, source_stage="stage177")


def default_evidence_action_remediation_fixtures() -> list[dict[str, Any]]:
    return [
        {
            "fixture_id": "literature-source-gap",
            "issues": [
                {
                    "issue_id": "lit-1",
                    "domain": "literature_research",
                    "issue_type": "source_missing",
                    "claim": "A paper claim lacks primary source evidence",
                    "required_evidence": ["primary paper", "publication metadata"],
                }
            ],
        },
        {
            "fixture_id": "math-derivation-gap",
            "issues": [
                {
                    "issue_id": "math-1",
                    "domain": "math_research",
                    "issue_type": "derivation_gap",
                    "claim": "A proof step lacks assumptions",
                    "required_evidence": ["assumptions", "intermediate lemma"],
                }
            ],
        },
        {
            "fixture_id": "gpu-experiment-failed",
            "issues": [
                {
                    "issue_id": "gpu-1",
                    "domain": "gpu_experiment",
                    "issue_type": "experiment_failed",
                    "claim": "A training job was claimed as converged",
                    "required_evidence": ["logs", "metrics", "checkpoint"],
                }
            ],
        },
        {
            "fixture_id": "memory-unsupported",
            "issues": [
                {
                    "issue_id": "mem-1",
                    "domain": "agent_memory",
                    "issue_type": "memory_unsupported",
                    "claim": "A memory preference lacks memory ledger support",
                    "required_evidence": ["memory_observation_ledger"],
                }
            ],
        },
        {"fixture_id": "clean-finalizable", "issues": []},
    ]


def _summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    action_count = sum(int(row.get("action_count", 0) or 0) for row in results)
    blocked = [row for row in results if not bool(row.get("can_finalize", False))]
    finalizable = [row for row in results if bool(row.get("can_finalize", False))]
    domains: dict[str, int] = {}
    for row in results:
        for issue in _list_dicts(row.get("issues", [])):
            domain = str(issue.get("domain", "") or "general")
            domains[domain] = domains.get(domain, 0) + 1
    return {
        "result_count": len(results),
        "blocked_count": len(blocked),
        "finalizable_count": len(finalizable),
        "action_count": action_count,
        "domain_issue_counts": dict(sorted(domains.items())),
    }


def _html_report(bundle: dict[str, Any]) -> str:
    summary = _dict(bundle.get("summary", {}))
    rows: list[str] = []
    for result in _list_dicts(bundle.get("results", [])):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(result.get('fixture_id', '')))}</td>"
            f"<td>{html.escape(str(result.get('status', '')))}</td>"
            f"<td>{html.escape(str(result.get('issue_count', 0)))}</td>"
            f"<td>{html.escape(str(result.get('action_count', 0)))}</td>"
            f"<td>{html.escape(str(result.get('recommended_stop_reason', '')))}</td>"
            "</tr>"
        )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Stage178 Evidence Action Remediation</title>"
        "<style>body{font:14px system-ui;margin:24px;color:#17211e}table{border-collapse:collapse;width:100%}"
        "td,th{border:1px solid #ccd6d1;padding:8px;text-align:left}.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:16px 0}"
        ".card{border:1px solid #ccd6d1;padding:10px;border-radius:6px}</style></head><body>"
        "<h1>Stage178 Evidence Action Remediation</h1>"
        "<p>Domain-independent evidence gap to action-plan controller. This is offline diagnostics; it does not execute tools or call providers.</p>"
        "<div class=\"summary\">"
        f"<div class=\"card\">results<br><b>{summary.get('result_count', 0)}</b></div>"
        f"<div class=\"card\">blocked<br><b>{summary.get('blocked_count', 0)}</b></div>"
        f"<div class=\"card\">finalizable<br><b>{summary.get('finalizable_count', 0)}</b></div>"
        f"<div class=\"card\">actions<br><b>{summary.get('action_count', 0)}</b></div>"
        "</div><table><thead><tr><th>Fixture</th><th>Status</th><th>Issues</th><th>Actions</th><th>Stop</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></body></html>"
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
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in _list_dicts(bundle.get("results", []))) + "\n",
        encoding="utf-8",
    )
    return {"html": str(html_path), "json": str(json_path), "jsonl": str(jsonl_path)}


def run_evidence_action_remediation(
    *,
    output: str | Path | None = None,
    dry_run: bool = True,
    fixtures: list[dict[str, Any]] | None = None,
    fail_under: float | None = None,
) -> dict[str, Any]:
    rows = list(fixtures if fixtures is not None else default_evidence_action_remediation_fixtures())
    results: list[dict[str, Any]] = []
    for fixture in rows:
        report = build_evidence_action_remediation(_list_dicts(fixture.get("issues", [])))
        report["fixture_id"] = str(fixture.get("fixture_id", "") or stable_digest(json.dumps(fixture, ensure_ascii=False), limit=10))
        results.append(report)
    summary = _summary(results)
    bundle = {
        "schema": STAGE178_EVIDENCE_ACTION_REMEDIATION_BUNDLE_SCHEMA,
        "generated_at": utc_now(),
        "dry_run": bool(dry_run),
        "status": "passed",
        "result_count": len(results),
        "results": results,
        "summary": summary,
        "fail_under": fail_under,
        "fail_under_triggered": bool(fail_under is not None and summary["finalizable_count"] / max(1, len(results)) < float(fail_under)),
        "authority_boundary": {
            "provider_model_calls": False,
            "network_fetches_executed": False,
            "tool_execution": False,
            "memory_writes": False,
            "wechat_start": False,
            "transport_authority_widened": False,
        },
    }
    if output is not None:
        bundle["artifacts"] = _write_artifacts(bundle, output)
    return _dict(_public(bundle))
