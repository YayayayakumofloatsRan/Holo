from __future__ import annotations

import json

from holo_host import cli
from holo_host.stage112_system_taxonomy import (
    SYSTEM_CATEGORY_FIXTURES,
    run_stage112_system_taxonomy,
)


ROLE_MARKERS = ("Holo", "WeChat", "operator", "Operator", "user", "User")


def test_stage112_expands_role_agnostic_system_categories() -> None:
    report = run_stage112_system_taxonomy()

    assert report["schema"] == "holo.stage112.system_category_taxonomy.v1"
    assert report["stage"] == 112
    assert report["abstraction"]["role_agnostic"] is True
    assert report["coverage"]["category_count"] >= 30
    assert len(SYSTEM_CATEGORY_FIXTURES) == report["coverage"]["category_count"]
    assert report["coverage"]["all_expectations_matched"] is True
    assert report["coverage"]["role_marker_violations"] == []

    for fixture in SYSTEM_CATEGORY_FIXTURES:
        surface = json.dumps(
            {
                "category_id": fixture["category_id"],
                "label": fixture["label"],
                "query": fixture["query"],
                "domain_tags": fixture["domain_tags"],
            },
            ensure_ascii=False,
        )
        assert not any(marker in surface for marker in ROLE_MARKERS)
        assert fixture["system_level"] is True


def test_stage112_route_and_family_coverage_is_broad() -> None:
    report = run_stage112_system_taxonomy()
    routes = report["coverage"]["route_counts"]
    families = report["coverage"]["family_counts"]

    assert routes["multi_packet"] >= 14
    assert routes["single_packet"] >= 5
    assert routes["tool_first"] >= 7
    assert routes["stop"] >= 4

    for family in (
        "memory",
        "affect",
        "reasoning",
        "tool_grounding",
        "inhibition",
        "timing",
        "perception",
        "metacognition",
        "action",
    ):
        assert families[family] >= 1


def test_stage112_tool_call_probe_exercises_allowed_and_rejected_tools() -> None:
    report = run_stage112_system_taxonomy()
    probe = report["tool_call_probe"]

    assert probe["passed"] is True
    assert probe["adapter"]["tool_count"] == 2
    assert probe["adapter"]["exposed_tools"] == ["external_lookup", "memory_recall"]
    assert probe["adapter"]["rejected_tools"] == ["shell_exec"]
    assert probe["provider_tool_calls"]["accepted_names"] == ["external_lookup", "memory_recall"]
    assert probe["provider_tool_calls"]["rejected_errors"] == ["unknown_tool"]
    assert probe["interaction_loop"]["status"] == "awaiting_tool_execution"
    assert probe["interaction_loop"]["next_action"] == "execute_tool_locally"
    assert probe["authority"]["provider_may_execute_tools"] is False


def test_stage112_cli_outputs_system_taxonomy(capsys) -> None:
    result = cli.main(["stage112-system-taxonomy"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 112
    assert payload["coverage"]["category_count"] >= 30
    assert payload["source"] == "dry_run"
    assert payload["tool_call_probe"]["passed"] is True
