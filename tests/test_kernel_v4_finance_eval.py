from __future__ import annotations

import asyncio
import json

from kernel_v4.contracts import ModelEvent
from kernel_v4.contracts import ToolCall
from kernel_v4.finance_costs import estimate_deepseek_cost_usd
from kernel_v4.finance_eval import (
    resolve_eval_slice,
    run_finance_eval_rows,
)


class FinalAnswerModel:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests = []

    async def stream(self, *, messages, tools, system_prompt, context):
        self.requests.append(
            {
                "messages": messages,
                "tools": tools,
                "system_prompt": system_prompt,
                "context": context,
            }
        )
        yield ModelEvent(event_type="text_delta", text=self.answer)
        yield ModelEvent(event_type="message_stop")


class SleepingModel:
    async def stream(self, *, messages, tools, system_prompt, context):
        await asyncio.sleep(10)
        yield ModelEvent(event_type="message_stop")


class TransientNetworkModel:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests = []
        self.calls = 0

    async def stream(self, *, messages, tools, system_prompt, context):
        self.calls += 1
        self.requests.append(
            {
                "messages": messages,
                "tools": tools,
                "system_prompt": system_prompt,
                "context": context,
            }
        )
        if self.calls == 1:
            raise RuntimeError("deepseek network error: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF")
        yield ModelEvent(event_type="text_delta", text=self.answer)
        yield ModelEvent(event_type="message_stop")


class ToolThenSleepingModel:
    async def stream(self, *, messages, tools, system_prompt, context):
        yield ModelEvent(
            event_type="tool_call",
            tool_call=ToolCall(
                tool_call_id="call-timeout-calculator",
                name="calculator.compute",
                input={"expression": "1+1"},
            ),
        )
        await asyncio.sleep(10)
        yield ModelEvent(event_type="message_stop")


def test_finance_eval_resolves_debug50_and_test100_slices() -> None:
    assert resolve_eval_slice(split="debug50", start_index=None, limit=None, row_count=150) == (0, 50)
    assert resolve_eval_slice(split="test100", start_index=None, limit=None, row_count=150) == (50, 100)
    assert resolve_eval_slice(split="debug50", start_index=2, limit=3, row_count=150) == (2, 3)


def test_finance_eval_deepseek_cost_estimate_uses_cache_hit_pricing() -> None:
    estimate = estimate_deepseek_cost_usd(
        {
            "prompt_cache_hit_tokens": 1000,
            "prompt_cache_miss_tokens": 2000,
            "completion_tokens": 3000,
        },
        provider="deepseek",
        model="deepseek-v4-flash",
    )

    assert estimate["model_pricing_family"] == "deepseek-v4-flash"
    assert estimate["tokens"] == {"input_cache_hit": 1000, "input_cache_miss": 2000, "output": 3000}
    assert estimate["total_usd"] == (1000 * 0.0028 + 2000 * 0.14 + 3000 * 0.28) / 1_000_000


def test_finance_eval_live_summary_is_redacted_and_model_packet_is_no_gold(tmp_path) -> None:
    model = FinalAnswerModel("The answer is 127.40 per transaction.")
    rows = [
        {
            "id": "finqa-eval-1",
            "dataset": "finqa",
            "question": "What is the average payment volume per transaction?",
            "oracle_context": "Payment volume was 637 and total transactions were 5.0.",
            "answer": "do-not-send-this-answer",
            "gold_program": "divide(637,5.0)",
        }
    ]
    annotations = {
        "finqa-eval-1": {
            "item_id": "finqa-eval-1",
            "source": "finqa",
            "expected_numeric": [{"name": "gold_numeric_1", "value": 127.4, "tolerance": 1.274}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="debug50",
            start_index=0,
            output_dir=tmp_path,
            benchmark_family="finqa",
            model=model,
            provider_summary={"provider": "scripted", "model": "final-answer"},
            allow_network=False,
        )
    )
    dumped_summary = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    request_text = "\n".join(message.content for message in model.requests[0]["messages"])

    assert summary["schema"] == "holo.kernel_v4.finance_live_eval_summary.v1"
    assert summary["status"] == "completed"
    assert summary["split"] == "debug50"
    assert summary["item_count"] == 1
    assert summary["passed_count"] == 1
    assert summary["pass_rate"] == 1.0
    assert summary["experiment_metrics"]["turns"]["count"] == 1
    assert summary["experiment_metrics"]["tool_calls"]["count"] == 1
    assert summary["experiment_metrics"]["duration_seconds"]["count"] == 1
    assert summary["experiment_metrics"]["chart_files"] == {"items_csv": "items.csv", "items_jsonl": "items.jsonl"}
    assert summary["debug_tuning_score"] is True
    assert summary["held_out_test_score"] is False
    assert summary["gold_reference_material_used_for_scoring_only"] is True
    assert summary["gold_reference_material_in_model_context"] is False
    assert summary["items"][0]["passed"] is True
    assert "score_details" not in summary["items"][0]
    assert "127.4" not in dumped_summary
    assert "gold_numeric_1" not in dumped_summary
    assert "divide(637" not in request_text
    assert "do-not-send-this-answer" not in request_text
    assert "gold_program" not in request_text

    score_payload = json.loads((tmp_path / "items" / "000_finqa-eval-1.score.json").read_text(encoding="utf-8"))
    assert score_payload["numeric_matches"][0]["expected"] == 127.4
    csv_text = (tmp_path / "items.csv").read_text(encoding="utf-8")
    jsonl_text = (tmp_path / "items.jsonl").read_text(encoding="utf-8")
    assert "offset,item_id,passed,run_status,score_reason" in csv_text
    assert "finqa-eval-1" in csv_text
    assert "finqa-eval-1" in jsonl_text


def test_finance_eval_marks_test100_as_held_out(tmp_path) -> None:
    model = FinalAnswerModel("The answer is 20%.")
    rows = [
        {
            "id": "fb-eval-1",
            "dataset": "financebench",
            "question": "Compute the percentage.",
            "context": "The values are 20 and 100.",
            "gold_answer": "20%",
        }
    ]
    annotations = {
        "fb-eval-1": {
            "item_id": "fb-eval-1",
            "source": "financebench",
            "expected_numeric": [{"name": "pct", "value": 0.2, "tolerance": 0.001}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="test100",
            start_index=50,
            output_dir=tmp_path,
            benchmark_family="financebench",
            model=model,
            provider_summary={"provider": "scripted", "model": "final-answer"},
            allow_network=False,
        )
    )

    assert summary["held_out_test_score"] is True
    assert summary["debug_tuning_score"] is False
    assert "held-out FinanceBench offsets 50-149" in summary["split_policy"]


def test_finance_eval_sparse_row_offsets_are_preserved(tmp_path) -> None:
    model = FinalAnswerModel("The answer is 1.")
    rows = [
        {"id": "row-a", "dataset": "financebench", "question": "Compute one."},
        {"id": "row-b", "dataset": "financebench", "question": "Compute one again."},
    ]
    annotations = {
        "row-a": {"item_id": "row-a", "expected_numeric": [{"name": "n", "value": 1.0, "tolerance": 0.0}]},
        "row-b": {"item_id": "row-b", "expected_numeric": [{"name": "n", "value": 1.0, "tolerance": 0.0}]},
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="all150",
            start_index=7,
            row_offsets=[7, 11],
            output_dir=tmp_path,
            benchmark_family="financebench",
            model=model,
            provider_summary={"provider": "scripted", "model": "final-answer"},
            allow_network=False,
        )
    )

    assert summary["row_offsets"] == [7, 11]
    assert [item["offset"] for item in summary["items"]] == [7, 11]
    assert (tmp_path / "items" / "007_row-a.run.json").exists()
    assert (tmp_path / "items" / "011_row-b.run.json").exists()


def test_finance_eval_retries_transient_model_stream_network_errors(tmp_path) -> None:
    model = TransientNetworkModel("The answer is 127.40 per transaction.")
    rows = [
        {
            "id": "finqa-retry-1",
            "dataset": "finqa",
            "question": "What is the average payment volume per transaction?",
            "oracle_context": "Payment volume was 637 and total transactions were 5.0.",
            "answer": "do-not-send-this-answer",
        }
    ]
    annotations = {
        "finqa-retry-1": {
            "item_id": "finqa-retry-1",
            "source": "finqa",
            "expected_numeric": [{"name": "gold_numeric_1", "value": 127.4, "tolerance": 1.274}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="debug50",
            start_index=0,
            output_dir=tmp_path,
            benchmark_family="finqa",
            model=model,
            provider_summary={"provider": "scripted", "model": "transient-network"},
            allow_network=False,
            item_run_retries=1,
        )
    )

    run_payload = json.loads((tmp_path / "items" / "000_finqa-retry-1.run.json").read_text(encoding="utf-8"))
    request_text = "\n".join(
        message.content
        for request in model.requests
        for message in request["messages"]
    )

    assert model.calls == 2
    assert summary["passed_count"] == 1
    assert summary["items"][0]["passed"] is True
    assert summary["items"][0]["item_run_retry_count"] == 1
    assert summary["items"][0]["item_run_attempt_count"] == 2
    assert "model_stream_error" in summary["items"][0]["item_run_attempt_reasons"][0]
    assert run_payload["retry_info"]["retry_count"] == 1
    assert run_payload["retry_info"]["attempts"][0]["retryable_transport_failure"] is True
    assert run_payload["retry_info"]["attempts"][1]["status"] == "completed"
    assert "do-not-send-this-answer" not in request_text


def test_finance_eval_counts_completed_wrong_answer_as_failed_item(tmp_path) -> None:
    model = FinalAnswerModel("The answer is 20%.")
    rows = [
        {
            "id": "fb-eval-wrong",
            "dataset": "financebench",
            "question": "Compute the percentage.",
            "context": "The values are 20 and 100.",
            "gold_answer": "99%",
        }
    ]
    annotations = {
        "fb-eval-wrong": {
            "item_id": "fb-eval-wrong",
            "source": "financebench",
            "expected_numeric": [{"name": "pct", "value": 0.99, "tolerance": 0.001}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="test100",
            start_index=50,
            output_dir=tmp_path,
            benchmark_family="financebench",
            model=model,
            provider_summary={"provider": "scripted", "model": "final-answer"},
            allow_network=False,
        )
    )

    assert summary["completed_count"] == 1
    assert summary["run_failed_count"] == 0
    assert summary["passed_count"] == 0
    assert summary["failed_count"] == 1
    assert summary["pass_rate"] == 0.0
    assert summary["failure_reasons"] == {"numeric_outside_tolerance": 1}


def test_finance_eval_item_timeout_records_failure_and_continues(tmp_path) -> None:
    rows = [
        {
            "id": "timeout-row",
            "dataset": "financebench",
            "question": "Compute the value.",
            "context": "The value is 1.",
        }
    ]
    annotations = {
        "timeout-row": {
            "item_id": "timeout-row",
            "source": "financebench",
            "expected_numeric": [{"name": "value", "value": 1.0, "tolerance": 0.01}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="debug50",
            start_index=0,
            output_dir=tmp_path,
            benchmark_family="financebench",
            model=SleepingModel(),
            provider_summary={"provider": "scripted", "model": "sleeping"},
            allow_network=False,
            item_timeout_seconds=0.01,
        )
    )

    assert summary["status"] == "completed"
    assert summary["item_count"] == 1
    assert summary["passed_count"] == 0
    assert summary["failed_count"] == 1
    assert summary["run_failed_count"] == 1
    assert summary["items"][0]["run_status"] == "failed"
    assert summary["items"][0]["run_reason"].startswith("item_timeout:")
    assert summary["failure_reasons"] == {"run_not_completed": 1}


def test_finance_eval_timeout_preserves_partial_workflow_trace(tmp_path) -> None:
    rows = [
        {
            "id": "timeout-after-tool-row",
            "dataset": "financebench",
            "question": "Compute the value.",
            "context": "The value is 2.",
        }
    ]
    annotations = {
        "timeout-after-tool-row": {
            "item_id": "timeout-after-tool-row",
            "source": "financebench",
            "expected_numeric": [{"name": "value", "value": 2.0, "tolerance": 0.01}],
        }
    }

    summary = asyncio.run(
        run_finance_eval_rows(
            rows=rows,
            annotations=annotations,
            split="debug50",
            start_index=0,
            output_dir=tmp_path,
            benchmark_family="financebench",
            model=ToolThenSleepingModel(),
            provider_summary={"provider": "scripted", "model": "tool-then-sleeping"},
            allow_network=False,
            item_timeout_seconds=0.01,
        )
    )

    run_payload = json.loads((tmp_path / "items" / "000_timeout-after-tool-row.run.json").read_text(encoding="utf-8"))

    assert summary["items"][0]["run_status"] == "failed"
    assert summary["items"][0]["tool_call_count"] == 1
    assert summary["items"][0]["turn_count"] == 1
    assert run_payload["tool_trace_summary"]["call_count"] == 1
    assert run_payload["tool_trace_summary"]["by_tool"] == {"calculator.compute": 1}
