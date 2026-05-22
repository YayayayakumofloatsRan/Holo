from __future__ import annotations

import json

from holo_host import cli
from holo_host.stage111_category_simulation import (
    BASE_CATEGORY_FIXTURES,
    run_stage111_category_simulation,
)


def test_stage111_base_categories_cover_core_biomimetic_units() -> None:
    report = run_stage111_category_simulation()

    assert report["schema"] == "holo.stage111.category_simulation.v1"
    assert report["stage"] == 111
    assert report["coverage"]["category_count"] >= 12
    assert report["coverage"]["route_counts"]["multi_packet"] >= 3
    assert report["coverage"]["route_counts"]["single_packet"] >= 2
    assert report["coverage"]["route_counts"]["tool_first"] >= 2
    assert report["coverage"]["route_counts"]["stop"] >= 1
    assert "memory" in report["coverage"]["domain_tags"]
    assert "affect" in report["coverage"]["domain_tags"]
    assert "tool_grounding" in report["coverage"]["domain_tags"]
    assert "inhibition" in report["coverage"]["domain_tags"]


def test_stage111_each_case_runs_full_stage105_to_110_chain() -> None:
    report = run_stage111_category_simulation()

    assert len(report["cases"]) == len(BASE_CATEGORY_FIXTURES)
    for case in report["cases"]:
        assert case["stage105"]["stage"] == 105
        assert case["stage107"]["stage"] == 107
        assert case["stage108"]["stage"] == 108
        assert case["stage109"]["stage"] == 109
        assert case["stage110"]["stage"] == 110
        assert case["observed_route"] in {"multi_packet", "single_packet", "tool_first", "stop"}
        assert case["matched_expectation"] is True


def test_stage111_outputs_combination_and_self_extension_candidates() -> None:
    report = run_stage111_category_simulation()

    candidates = report["combination_candidates"]
    assert candidates
    assert any("affect" in item["source_tags"] and "memory" in item["source_tags"] for item in candidates)
    assert any("tool_grounding" in item["source_tags"] and "memory" in item["source_tags"] for item in candidates)

    extension = report["self_extension_policy"]
    assert extension["can_add_new_categories"] is True
    assert extension["candidate_schema"]["required_fields"] == [
        "category_id",
        "query",
        "mind_packet",
        "domain_tags",
        "expected_route",
        "promotion_evidence",
    ]
    assert "novel_route_mismatch" in extension["promotion_triggers"]


def test_stage111_cli_dry_run_outputs_report(capsys) -> None:
    result = cli.main(["stage111-category-simulation"])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 111
    assert payload["coverage"]["category_count"] >= 12
    assert payload["source"] == "dry_run"
