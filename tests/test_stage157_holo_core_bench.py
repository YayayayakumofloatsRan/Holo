from __future__ import annotations

import json
from pathlib import Path

from holo_host import cli
from holo_host.holo_core_bench import (
    BENCHMARK_CATEGORY_IDS,
    HOLO_CORE_BENCH_SCHEMA,
    default_holo_core_bench_fixtures,
    render_holo_core_bench,
    run_holo_core_bench,
)


def test_dry_run_creates_benchmark_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "holo_core_bench.html"

    report = run_holo_core_bench(output=output, dry_run=True)

    assert report["schema"] == HOLO_CORE_BENCH_SCHEMA
    assert output.exists()
    assert output.with_suffix(".json").exists()
    assert output.with_suffix(".jsonl").exists()
    assert json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))["schema"] == HOLO_CORE_BENCH_SCHEMA


def test_benchmark_includes_all_reliability_categories() -> None:
    report = run_holo_core_bench(dry_run=True)

    category_ids = {item["category_id"] for item in report["categories"]}
    assert set(BENCHMARK_CATEGORY_IDS).issubset(category_ids)
    assert {
        "recent_recall",
        "directive_adherence",
        "one_turn_vs_durable_instruction",
        "project_state_recall",
        "task_continuation",
        "web_time_grounding",
        "tool_claim_grounding",
        "engineering_patch_test_claims",
        "context_compaction_integrity",
        "cli_trace_visibility",
        "stop_reason_correctness",
    }.issubset(category_ids)


def test_failing_fixture_detects_unsupported_web_claim() -> None:
    report = run_holo_core_bench(
        dry_run=True,
        fixtures=[
            {
                "fixture_id": "web-unsupported",
                "category_id": "web_time_grounding",
                "input": "Find the latest official DeepSeek tool calling docs.",
                "visible_text": "I searched the latest official docs today.",
                "metadata": {"web_observation_ledger": [], "time_observation": {}},
            }
        ],
    )

    category = report["categories_by_id"]["web_time_grounding"]
    assert category["status"] == "failed"
    assert category["metrics"]["unsupported_claim_rate"] == 1.0
    assert report["summary"]["unsupported_claim_rate"] == 1.0


def test_failing_fixture_detects_directive_violation() -> None:
    report = run_holo_core_bench(
        dry_run=True,
        fixtures=[
            {
                "fixture_id": "directive-emoji",
                "category_id": "directive_adherence",
                "input": "Please avoid emoji.",
                "visible_text": "Understood \U0001f60f",
                "directives": ["no emoji"],
                "metadata": {"stage149_user_directives": {"hard_directive_count": 1}},
            }
        ],
    )

    category = report["categories_by_id"]["directive_adherence"]
    assert category["status"] == "failed"
    assert category["metrics"]["directive_violation_rate"] == 1.0


def test_failing_fixture_detects_project_state_loss() -> None:
    report = run_holo_core_bench(
        dry_run=True,
        fixtures=[
            {
                "fixture_id": "project-loss",
                "category_id": "project_state_recall",
                "input": "What remains open for Stage157?",
                "visible_text": "No project state is available.",
                "expected_project_state": {
                    "open_questions": ["How should cache metrics be judged?"],
                    "next_actions": ["Run Stage157 tests"],
                },
                "metadata": {"project_state_graph": {"open_questions": [], "next_actions": []}},
            }
        ],
    )

    category = report["categories_by_id"]["project_state_recall"]
    assert category["status"] == "failed"
    assert category["metrics"]["project_continuity_score"] == 0.0


def test_passing_fixture_scores_above_threshold() -> None:
    report = run_holo_core_bench(dry_run=True, fixtures=default_holo_core_bench_fixtures())

    assert report["status"] == "passed"
    assert report["summary"]["pass_rate"] >= 0.9
    assert report["summary"]["memory_honesty_score"] >= 0.9
    assert report["summary"]["tool_grounding_score"] >= 0.9


def test_artifacts_are_public_release_safe(tmp_path: Path) -> None:
    output = tmp_path / "bench.html"

    run_holo_core_bench(output=output, dry_run=True)
    blob = output.read_text(encoding="utf-8") + output.with_suffix(".json").read_text(encoding="utf-8")

    assert ".holo_runtime" not in blob
    assert "holo_memory_library/memories" not in blob
    assert "DEEPSEEK_API_KEY" not in blob


def test_cli_returns_nonzero_only_when_fail_under_requested(tmp_path: Path) -> None:
    output = tmp_path / "bench.html"

    assert cli.main(["run-core-bench", "--output", str(output), "--dry-run"]) == 0
    assert cli.main(["run-core-bench", "--output", str(output), "--dry-run", "--fail-under", "0.1"]) == 0
    assert cli.main(["run-core-bench", "--output", str(output), "--dry-run", "--fail-under", "1.1"]) == 1


def test_core_bench_render_is_cli_readable() -> None:
    rendered = render_holo_core_bench(run_holo_core_bench(dry_run=True))

    assert "Stage157 Holo Core Bench" in rendered
    assert "pass_rate=" in rendered
    assert "web_time_grounding" in rendered
