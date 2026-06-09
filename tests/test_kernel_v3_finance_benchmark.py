import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.bench import (
    FinanceBenchmarkItem,
    convert_public_finance_benchmark,
    load_finance_benchmark_items,
    run_finance_benchmark,
    run_finance_benchmark_parallel,
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


def test_finance_benchmark_sentinel_scoring_accepts_corrected_actual_value() -> None:
    item = FinanceBenchmarkItem(
        item_id="adv-actual-1",
        question="What was Google's operating cash flow for fiscal year 2024?",
        gold_answer="INCORRECT_PREMISE — actual FY2024 operating cash flow was $125.3 billion",
    )

    score = score_finance_answer(item, answer="The 2024 operating cash flow was 1252.99亿美元.")

    assert score["status"] == "passed"
    assert score["gold_sentinel"] is True
    assert score["corrected_actual_value"] is True
    assert score["numeric"]["passed"] is True


def test_finance_benchmark_gold_numeric_scoring_handles_approximate_text() -> None:
    item = FinanceBenchmarkItem(
        item_id="fe-approx",
        question="What was Salesforce revenue?",
        gold_answer="approximately $34.8 billion (implied from fiscal 2025 revenue of $37.9 billion)",
    )

    score = score_finance_answer(item, answer="Salesforce total revenue was $34,857,000,000.")

    assert score["status"] == "passed"
    assert score["reason"] == "numeric_within_tolerance"
    assert score["numeric"]["expected"] == 34_800_000_000


def test_finance_benchmark_sentinel_actual_value_does_not_score_year_as_target() -> None:
    item = FinanceBenchmarkItem(
        item_id="adv-year",
        question="What was operating cash flow?",
        gold_answer="INCORRECT_PREMISE — actual FY2024 operating cash flow was $125.3 billion",
    )

    score = score_finance_answer(item, answer="Operating cash flow was $125.299 billion in FY2024.")

    assert score["status"] == "passed"
    assert score["numeric"]["expected"] == 125_300_000_000
    assert score["numeric"]["matched_value"] == 125_299_000_000


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


def test_public_finance_agent_benchmark_import_keeps_gold_out_of_prompt(tmp_path: Path) -> None:
    source = tmp_path / "fab.csv"
    output = tmp_path / "normalized.jsonl"
    manifest = tmp_path / "manifest.json"
    source.write_text(
        "Question,Answer,Question Type,Expert time (mins),Rubric\n"
        '"What was ExampleCo revenue?","$10 million",fact_extraction,5,"Must cite filing."\n',
        encoding="utf-8",
    )

    summary = convert_public_finance_benchmark(
        benchmark="finance_agent_benchmark",
        input_path=source,
        output_path=output,
        manifest_path=manifest,
    )
    items = load_finance_benchmark_items(output)
    runtime = _StaticChatRuntime(JournalStore.in_memory())

    run_finance_benchmark(items=items, runtime=runtime)

    assert summary.item_count == 1
    assert items[0].source == "finance_agent_benchmark"
    assert items[0].metadata["rubric"] == "Must cite filing."
    assert "What was ExampleCo revenue?" in runtime.seen_prompts[0]
    assert "$10 million" not in runtime.seen_prompts[0]
    assert "Must cite filing." not in runtime.seen_prompts[0]
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["prompt_policy"]["gold_answer_in_prompt"] is False


def test_secque_import_uses_context_without_gold(tmp_path: Path) -> None:
    source = tmp_path / "secque.jsonl"
    output = tmp_path / "secque.normalized.jsonl"
    source.write_text(
        json.dumps(
            {
                "id": "S1",
                "question": "What was revenue?",
                "answer": "$20 million",
                "context": "Filing excerpt: revenue was reported in the income statement.",
                "accession": "0000000000-24-000001",
                "section": "Item 8",
                "question_type": "fact",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    convert_public_finance_benchmark(benchmark="secque", input_path=source, output_path=output)
    items = load_finance_benchmark_items(output)
    runtime = _StaticChatRuntime(JournalStore.in_memory())

    run_finance_benchmark(items=items, runtime=runtime)

    prompt = runtime.seen_prompts[0]
    assert "Filing excerpt: revenue was reported" in prompt
    assert "$20 million" not in prompt
    assert items[0].metadata["source_refs"][0]["accession"] == "0000000000-24-000001"


def test_financeqa_import_never_prompts_reference_cot(tmp_path: Path) -> None:
    source = tmp_path / "financeqa.json"
    output = tmp_path / "financeqa.normalized.jsonl"
    source.write_text(
        json.dumps(
            [
                {
                    "question": "Why did margin improve?",
                    "answer": "Because costs declined.",
                    "context": "Management said costs declined.",
                    "chain_of_thought": "Hidden reference reasoning that must not be prompted.",
                    "question_type": "conceptual",
                    "company": "ExampleCo",
                    "file_link": "https://example.com/filing.pdf",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    convert_public_finance_benchmark(benchmark="financeqa", input_path=source, output_path=output)
    items = load_finance_benchmark_items(output)
    runtime = _StaticChatRuntime(JournalStore.in_memory())

    run_finance_benchmark(items=items, runtime=runtime)

    prompt = runtime.seen_prompts[0]
    assert "Management said costs declined." in prompt
    assert "Hidden reference reasoning" not in prompt
    assert "Because costs declined" not in prompt
    assert items[0].metadata["reference_reasoning_available"] is True


def test_finance_benchmark_parallel_runner_isolates_and_orders_workers() -> None:
    seen: list[tuple[int, str, str]] = []

    def factory(index: int, item: FinanceBenchmarkItem) -> _StaticChatRuntime:
        journal = JournalStore.in_memory()
        runtime = _StaticChatRuntime(journal)
        runtime.answer = f"{item.item_id} revenue was $10 million."
        runtime.on_receive = lambda prompt, thread_id, index=index, item=item: seen.append((index, item.item_id, thread_id))
        return runtime

    items = [
        FinanceBenchmarkItem(item_id="Q1", question="Q1 revenue?", gold_answer="$10 million"),
        FinanceBenchmarkItem(item_id="Q2", question="Q2 revenue?", gold_answer="$10 million"),
        FinanceBenchmarkItem(item_id="Q3", question="Q3 revenue?", gold_answer="$10 million"),
    ]

    results = run_finance_benchmark_parallel(
        items=items,
        runtime_factory=factory,
        max_workers=3,
        thread_prefix="parallel-smoke",
        question_prefix="Do not see gold.",
    )

    assert [result.item_id for result in results] == ["Q1", "Q2", "Q3"]
    assert [result.status for result in results] == ["passed", "passed", "passed"]
    assert sorted(index for index, _, _ in seen) == [1, 2, 3]
    assert all(thread_id.startswith("parallel-smoke-") for _, _, thread_id in seen)


def test_finance_benchmark_parallel_runner_reports_item_progress() -> None:
    progress: list[tuple[int, str, str]] = []

    def factory(index: int, item: FinanceBenchmarkItem) -> _StaticChatRuntime:
        journal = JournalStore.in_memory()
        runtime = _StaticChatRuntime(journal)
        runtime.answer = f"{item.item_id} revenue was $10 million."
        return runtime

    items = [
        FinanceBenchmarkItem(item_id="Q1", question="Q1 revenue?", gold_answer="$10 million"),
        FinanceBenchmarkItem(item_id="Q2", question="Q2 revenue?", gold_answer="$10 million"),
    ]

    results = run_finance_benchmark_parallel(
        items=items,
        runtime_factory=factory,
        max_workers=2,
        thread_prefix="progress-smoke",
        result_callback=lambda index, item, result: progress.append((index, item.item_id, result.status)),
    )

    assert [result.item_id for result in results] == ["Q1", "Q2"]
    assert sorted(progress) == [(1, "Q1", "passed"), (2, "Q2", "passed")]


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


def test_finance_benchmark_cli_imports_public_dataset(tmp_path: Path) -> None:
    source = tmp_path / "finance_agent.csv"
    output = tmp_path / "normalized.jsonl"
    manifest = tmp_path / "manifest.json"
    source.write_text(
        "Question,Answer,Question Type,Rubric\n"
        '"What was revenue?","$10 million",fact_extraction,"Score numeric value and citation."\n',
        encoding="utf-8",
    )

    code = cli.main(
        [
            "bench",
            "finance-import",
            "--benchmark",
            "finance_agent_benchmark",
            "--input",
            str(source),
            "--output",
            str(output),
            "--manifest-output",
            str(manifest),
        ]
    )

    assert code == 0
    items = load_finance_benchmark_items(output)
    assert len(items) == 1
    assert items[0].question == "What was revenue?"
    assert items[0].gold_answer == "$10 million"
    assert json.loads(manifest.read_text(encoding="utf-8"))["benchmark"] == "finance_agent_benchmark"


class _StaticChatRuntime:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal
        self.seen_prompts: list[str] = []
        self.answer = "ExampleCo revenue was $10 million."
        self.on_receive = None

    def receive(self, text: str, *, thread_id: str = "default") -> ChatRuntimeResult:
        self.seen_prompts.append(text)
        if self.on_receive is not None:
            self.on_receive(text, thread_id)
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
                "answer": self.answer,
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
