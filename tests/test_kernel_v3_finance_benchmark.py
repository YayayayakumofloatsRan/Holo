import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.bench import (
    FinanceBenchmarkItem,
    load_finance_benchmark_items,
    run_finance_benchmark,
    score_finance_answer,
)
from kernel_v3.chat.contracts import ChatRuntimeResult
from kernel_v3.journal import JournalStore


def test_finance_benchmark_loads_common_jsonl_fields(tmp_path: Path) -> None:
    dataset = tmp_path / "finagent.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "NR_001",
                "question": "What was ExampleCo revenue?",
                "answer": "$10 million",
                "numeric_value": 10_000_000,
                "tolerance": 100,
                "supporting_evidence": "Revenue was $10 million.",
                "tool_annotations": ["edgar_search", "calculator"],
                "type": "numerical_reasoning",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    items = load_finance_benchmark_items(dataset)

    assert len(items) == 1
    assert items[0].item_id == "NR_001"
    assert items[0].question == "What was ExampleCo revenue?"
    assert items[0].numeric_value == 10_000_000
    assert items[0].required_tools == ["edgar_search", "calculator"]
    assert items[0].category == "numerical_reasoning"


def test_finance_benchmark_numeric_scoring_uses_tolerance() -> None:
    item = FinanceBenchmarkItem(
        item_id="num-1",
        question="Revenue?",
        gold_answer="$10 million",
        numeric_value=10_000_000,
        tolerance=10_000,
    )

    score = score_finance_answer(
        item,
        answer="The revenue was $10.0 million.",
        final_answer={"citation_refs": ["cite-1"]},
    )

    assert score["status"] == "passed"
    assert score["numeric"]["passed"] is True
    assert score["citation_present"] is True


def test_finance_benchmark_sentinel_scoring_rewards_honest_unavailable_answer() -> None:
    item = FinanceBenchmarkItem(
        item_id="adv-1",
        question="What did the unavailable filing say?",
        gold_answer="NOT_AVAILABLE",
    )

    score = score_finance_answer(item, answer="证据不足，无法确定该文件中的信息。")

    assert score["status"] == "passed"
    assert score["gold_sentinel"] is True
    assert score["unavailable_acknowledged"] is True


def test_finance_benchmark_runner_does_not_need_gold_during_agent_run() -> None:
    journal = JournalStore.in_memory()
    runtime = _StaticChatRuntime(journal)
    item = FinanceBenchmarkItem(
        item_id="run-1",
        question="What was ExampleCo revenue?",
        gold_answer="$10 million",
        numeric_value=10_000_000,
    )

    results = run_finance_benchmark(items=[item], runtime=runtime, journal=journal, question_prefix="Answer with citations.")

    assert runtime.seen_prompts == ["Answer with citations.\n\nWhat was ExampleCo revenue?"]
    assert "$10 million" not in runtime.seen_prompts[0]
    assert results[0].status == "passed"
    assert journal.records(kind="finance_benchmark_item_result")


def test_finance_benchmark_cli_scores_prediction_file(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    output = tmp_path / "results.jsonl"
    summary = tmp_path / "summary.json"
    dataset.write_text(
        json.dumps({"id": "Q1", "question": "Revenue?", "numeric_value": 10_000_000, "tolerance": 1}) + "\n",
        encoding="utf-8",
    )
    predictions.write_text(
        json.dumps({"id": "Q1", "answer": "Revenue was 10,000,000.", "trace_metrics": {"total_tokens": 123}}) + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "bench",
            "finance",
            "--dataset",
            str(dataset),
            "--predictions",
            str(predictions),
            "--output",
            str(output),
            "--summary-output",
            str(summary),
        ]
    )

    assert code == 0
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.kernel_v3.finance_benchmark_summary.v1"
    assert payload["passed_count"] == 1
    assert payload["numeric_accuracy"] == 1.0
    assert output.exists()


class _StaticChatRuntime:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal
        self.seen_prompts: list[str] = []

    def receive(self, text: str, *, thread_id: str = "default") -> ChatRuntimeResult:
        self.seen_prompts.append(text)
        self.journal.append(
            task_id="task-bench",
            run_id="run-bench",
            step_id=None,
            kind="processor_result",
            data={
                "status": "ok",
                "usage": {"total_tokens": 42},
                "duration_ms": 7,
            },
        )
        return ChatRuntimeResult(
            status="completed",
            thread_id=thread_id,
            turn_id="turn-bench",
            route="new_task",
            task_id="task-bench",
            run_id="run-bench",
            answer=None,
            final_answer={
                "answer": "ExampleCo revenue was $10 million.",
                "citation_refs": ["cite-1"],
                "used_evidence": ["ev-1"],
                "limitations": [],
                "confidence": 0.9,
            },
            failure_report=None,
            pending_question=None,
            command_result=None,
            summary=None,
            trace_refs=["ledger-1"],
        )
