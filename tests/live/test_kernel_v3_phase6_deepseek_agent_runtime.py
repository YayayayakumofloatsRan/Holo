import os

import pytest

from kernel_v3.agent import AgentRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.processors import DeepSeekProvider, ProcessorFabric, deepseek_v4_router


def test_phase6_deepseek_agent_runtime_direct_and_retrieval_flows():
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live agent runtime")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live agent runtime")

    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=True)},
        router=deepseek_v4_router(profile="balanced", thinking="disabled", reasoning_effort="high"),
        journal=journal,
    )
    runtime = AgentRuntime(journal=journal, processor_fabric=fabric)

    direct = runtime.run("明确一下你的角色", mode="direct", planner_mode="model")
    retrieval = runtime.run(
        "检索 Holo Kernel v3 agent runtime 的证据",
        mode="retrieval",
        planner_mode="model",
        evaluator_mode="model",
        synthesizer_mode="model",
    )

    assert direct.status == "completed"
    assert direct.final_answer is not None
    assert "Holo" in str(direct.final_answer["answer"]) or "host" in str(direct.final_answer["answer"]).lower()
    assert retrieval.status == "completed"
    assert retrieval.final_answer is not None
    assert retrieval.final_answer["citation_refs"]
    assert retrieval.final_answer["used_evidence"]
    assert journal.records(task_id=retrieval.task_id, kind="processor_request")
    assert journal.records(task_id=retrieval.task_id, kind="retrieval_report")

