import json
import os

import pytest

from kernel_v3.journal import JournalStore
from kernel_v3.processors import (
    PLANNER_SCHEMA,
    PLANNER_PROMPT_CONTRACT,
    DeepSeekProvider,
    ProcessorFabric,
    ProcessorRouter,
)


def test_phase5_deepseek_live_smoke_is_explicitly_gated():
    if os.environ.get("HOLO_V3_LIVE_MODEL") != "1":
        pytest.skip("set HOLO_V3_LIVE_MODEL=1 for live model smoke")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("set DEEPSEEK_API_KEY for live DeepSeek smoke")

    journal = JournalStore.in_memory()
    fabric = ProcessorFabric(
        providers={"deepseek": DeepSeekProvider(enabled=True)},
        router=ProcessorRouter(default_provider="deepseek", default_model="deepseek-chat"),
        journal=journal,
    )

    outcome = fabric.run_json(
        task_type="planner.propose",
        task_id="task-live-smoke",
        run_id="run-live-smoke",
        context_id="ctx-live-smoke",
        prompt=json.dumps(
            {
                "contract": PLANNER_PROMPT_CONTRACT,
                "task": "Return exactly one JSON object matching planner.propose.",
                "required_action": {
                    "action_id": "act-live-smoke",
                    "kind": "respond",
                    "name": None,
                    "description": "respond through host",
                    "payload": {"text": "live smoke ok"},
                    "score": 1.0,
                    "reasons": ["live provider smoke"],
                    "side_effect_class": "none",
                },
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        schema=PLANNER_SCHEMA,
    )

    assert outcome.result.status == "ok"
    assert outcome.parsed is not None
