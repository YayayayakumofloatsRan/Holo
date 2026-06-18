from __future__ import annotations

import asyncio

from kernel_v4.contracts import ModelEvent
from kernel_v4.finance_runner import FinanceQuestionSpec, build_finance_registry, run_finance_question


class ScriptedModel:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []

    async def stream(self, *, messages, tools, system_prompt, context):
        self.requests.append(
            {
                "messages": list(messages),
                "tools": list(tools),
                "system_prompt": system_prompt,
                "context": dict(context),
            }
        )
        yield ModelEvent(event_type="text_delta", text="final answer")
        yield ModelEvent(event_type="message_stop")


def test_finance_question_spec_excludes_gold_reference_fields_from_prompt() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "finqa-1",
            "dataset": "finqa",
            "question": "What is the revenue growth?",
            "oracle_context": "Revenue was 100 in 2023 and 120 in 2024.",
            "answer": "20%",
            "reference_answer": "The answer is 20%.",
            "gold_program": "subtract(120, 100)",
            "expected_numeric": 0.2,
            "company": "ExampleCo",
            "period": "FY2024",
        },
        benchmark_family="finqa",
    )

    message = spec.to_user_message()

    assert "What is the revenue growth?" in message
    assert "Revenue was 100 in 2023 and 120 in 2024." in message
    assert "ExampleCo" in message
    assert "The answer is 20%." not in message
    assert "subtract(120, 100)" not in message
    assert "expected_numeric" not in message
    assert "reference_answer" not in message
    assert "gold_reference_material_included" in message
    assert "excluded_gold_reference_field_count" in message
    assert spec.excluded_gold_reference_fields == (
        "answer",
        "expected_numeric",
        "gold_program",
        "reference_answer",
    )


def test_finance_runner_passes_no_gold_task_packet_and_full_tool_surface_to_model() -> None:
    model = ScriptedModel()
    spec = FinanceQuestionSpec.from_mapping(
        {
            "benchmark_id": "fb-1",
            "dataset": "financebench",
            "question": "For 3M FY2022, compute capex / revenue.",
            "context": "3M net sales were 34.229B and capex was 1.749B.",
            "reference": "5.11%",
            "rubric": {"expected": "5.11%"},
            "ticker": "MMM",
            "fiscal_year": 2022,
        },
        benchmark_family="financebench",
    )

    result = asyncio.run(run_finance_question(spec, model=model, allow_network=True))

    assert result.status == "completed"
    request = model.requests[0]
    user_message = request["messages"][0].content
    assert "For 3M FY2022, compute capex / revenue." in user_message
    assert "3M net sales were 34.229B and capex was 1.749B." in user_message
    assert "5.11%" not in user_message
    assert "rubric" not in user_message
    assert "Benchmark gold/reference answers are never part of your context" in request["system_prompt"]
    tool_names = {tool.name for tool in request["tools"]}
    assert {
        "finance.toolchain.describe",
        "sec.edgar.financials",
        "document.search.hybrid",
        "provided_context.parse",
        "data.table.query",
        "calendar.days_between",
        "calculator.compute",
        "finance.verify_numeric",
        "tool.discovery",
        "artifact.read",
    }.issubset(tool_names)


def test_build_finance_registry_can_make_no_network_fqa_surface() -> None:
    registry = build_finance_registry(allow_network=False)
    tool_names = {manifest.name for manifest in registry.all_manifests()}

    assert "provided_context.parse" in tool_names
    assert "data.table.query" in tool_names
    assert "calculator.compute" in tool_names
    assert "finance.verify_numeric" in tool_names
    assert "tool.discovery" in tool_names
    assert "artifact.read" in tool_names
    assert "sec.edgar.financials" not in tool_names
