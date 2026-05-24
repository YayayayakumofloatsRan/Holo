from __future__ import annotations

from typing import Any

from .tool_grounding import evaluate_tool_grounding
from .tool_need import classify_tool_need

TOOL_BENCHMARK_SCHEMA = "holo.tool_benchmark.v1"


def _case(name: str, query: str, expected_groups: set[str], *, reply: str = "", ledger: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    need = classify_tool_need(query)
    predicted_groups = set(str(item) for item in list(need.get("tool_groups", []) or []))
    grounding = evaluate_tool_grounding(reply, ledger or []) if reply else {"status": "not_evaluated", "missing_families": []}
    return {
        "name": name,
        "query": query,
        "expected_groups": sorted(expected_groups),
        "predicted_groups": sorted(predicted_groups),
        "true_positive": sorted(predicted_groups.intersection(expected_groups)),
        "false_positive": sorted(predicted_groups.difference(expected_groups)),
        "false_negative": sorted(expected_groups.difference(predicted_groups)),
        "tool_need": need,
        "tool_grounding": grounding,
    }


def run_tool_benchmark() -> dict[str, Any]:
    cases = [
        _case("workspace_read", "Read your own project directory.", {"workspace"}, reply="I checked the project directory.", ledger=[]),
        _case("memory_recall", "Recall what we decided about short term memory.", {"memory"}),
        _case("external_latest", "Search the latest world model paper.", {"external_lookup"}),
        _case("git_diff", "Check git diff before summarizing.", {"git"}),
        _case("pytest_run", "Run pytest for the tool tests.", {"tests"}),
        _case("runtime_health", "Inspect runtime health and env state.", {"runtime"}),
        _case("mutation_needs_permission", "Write a file and git commit the result.", {"workspace", "git"}),
        _case("no_tool_casual", "That sounds good, continue.", set()),
    ]
    tp = sum(len(case["true_positive"]) for case in cases)
    fp = sum(len(case["false_positive"]) for case in cases)
    fn = sum(len(case["false_negative"]) for case in cases)
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "schema": TOOL_BENCHMARK_SCHEMA,
        "case_count": len(cases),
        "metrics": {
            "tool_precision": round(precision, 4),
            "tool_recall": round(recall, 4),
            "ungrounded_claim_count": sum(1 for case in cases if case["tool_grounding"].get("status") == "ungrounded_tool_claim"),
        },
        "cases": cases,
    }
