from __future__ import annotations

from holo_host.tool_grounding import (
    evaluate_tool_grounding,
    normalize_tool_observation_ledger,
    repair_ungrounded_tool_claims,
)


def test_normalize_tool_observation_ledger_tags_executed_and_rejected_tools() -> None:
    ledger = normalize_tool_observation_ledger(
        {
            "observations": [
                {
                    "provider_call_id": "call_workspace",
                    "tool": "workspace_inspect",
                    "status": "ok",
                    "summary": "workspace list_dir: docs, holo_host",
                    "data": {"entries": [], "path": "/repo"},
                }
            ],
            "skipped": [
                {
                    "provider_call_id": "call_shell",
                    "tool": "shell_exec",
                    "reason": "unknown_tool",
                }
            ],
        }
    )

    assert ledger == [
        {
            "provider_call_id": "call_workspace",
            "tool": "workspace_inspect",
            "status": "ok",
            "summary": "workspace list_dir: docs, holo_host",
            "data_keys": ["entries", "path"],
            "grounding_tags": ["workspace"],
        },
        {
            "provider_call_id": "call_shell",
            "tool": "shell_exec",
            "status": "rejected",
            "summary": "tool rejected: unknown_tool",
            "data_keys": ["reason"],
            "grounding_tags": [],
        },
    ]


def test_tool_grounding_flags_workspace_claim_without_observation() -> None:
    report = evaluate_tool_grounding("I checked the project directory and saw docs.", [])

    assert report["status"] == "ungrounded_tool_claim"
    assert report["missing_families"] == ["workspace"]
    repaired = repair_ungrounded_tool_claims("I checked the project directory and saw docs.", report, channel="holo_cli")
    assert "not executed" in repaired
    assert "workspace" in repaired


def test_tool_grounding_allows_claim_with_matching_observation() -> None:
    report = evaluate_tool_grounding(
        "I checked the project directory and saw docs.",
        [
            {
                "provider_call_id": "call_workspace",
                "tool": "workspace_inspect",
                "status": "ok",
                "summary": "workspace list_dir: docs",
                "data_keys": ["entries"],
                "grounding_tags": ["workspace"],
            }
        ],
    )

    assert report["status"] == "grounded"
    assert report["missing_families"] == []

