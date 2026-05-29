import os

import pytest

from kernel_v3.journal import JournalStore
from kernel_v3.processors import (
    DEEPSEEK_V4_FLASH,
    DEEPSEEK_V4_PRO,
    DeepSeekProvider,
    ProcessorFabric,
    deepseek_v4_router,
    run_semantic_scenarios,
    scenario_report_payload,
)


def test_phase5_deepseek_v4_semantic_scenarios_are_actual_model_calls():
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live model scenarios")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live DeepSeek scenarios")

    journal = JournalStore.in_memory()
    provider = DeepSeekProvider(enabled=True)
    fabric = ProcessorFabric(
        providers={"deepseek": provider},
        router=deepseek_v4_router(profile="balanced"),
        journal=journal,
    )

    results = run_semantic_scenarios(
        fabric,
        task_id="task-live-scenarios",
        run_id="run-live-scenarios",
        context_id="ctx-live-scenarios",
        provider="deepseek",
    )
    report = scenario_report_payload(results)

    assert report["status"] == "ok", report
    assert report["scenario_count"] == 5
    assert report["passed"] == 5
    assert {result.model for result in results} == {DEEPSEEK_V4_FLASH, DEEPSEEK_V4_PRO}
    assert len(journal.records(task_id="task-live-scenarios", kind="processor_request")) == 5
    assert len(journal.records(task_id="task-live-scenarios", kind="processor_result")) == 5
