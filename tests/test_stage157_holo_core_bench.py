from __future__ import annotations

from holo_host.holo_core_bench import (
    HOLO_CORE_BENCH_SCHEMA,
    render_holo_core_bench,
    run_holo_core_bench,
)


def test_core_bench_runs_deterministic_kernel_categories() -> None:
    report = run_holo_core_bench(dry_run=True)

    assert report["schema"] == HOLO_CORE_BENCH_SCHEMA
    assert report["status"] == "passed"
    category_ids = {item["category_id"] for item in report["categories"]}
    assert {
        "interactive_cli",
        "tool_loop",
        "engineering_actions",
        "project_state",
        "context_compiler",
        "domain_scaffold",
    }.issubset(category_ids)


def test_core_bench_render_is_cli_readable() -> None:
    rendered = render_holo_core_bench(run_holo_core_bench(dry_run=True))

    assert "Stage157 Holo Core Bench" in rendered
    assert "interactive_cli" in rendered
    assert "context_compiler" in rendered
