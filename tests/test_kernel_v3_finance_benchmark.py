import json
from pathlib import Path

from kernel_v3 import cli
from kernel_v3.bench import (
    FINANCE_BENCHMARK_SPLITS,
    FinanceBenchmarkItem,
    FinanceBenchmarkResult,
    convert_public_finance_benchmark,
    fetch_public_finance_benchmark,
    load_finance_benchmark_items,
    resolve_finance_benchmark_split,
    run_finance_benchmark,
    run_finance_benchmark_parallel,
    score_finance_dev_annotations,
    score_finance_answer,
    write_finance_benchmark_outputs,
    write_finance_dev_annotations_from_dataset,
)
from kernel_v3.bench.finance import _append_benchmark_provided_context_trace, summarize_finance_benchmark, trace_metrics
from kernel_v3.chat.contracts import ChatRuntimeResult
from kernel_v3.finance import compile_finance_task_program
from kernel_v3.journal import JournalStore
from kernel_v3.agent.answer_profile import infer_answer_profile
from kernel_v3.agent.runtime import _benchmark_doc_retrieval_payload


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


def test_financebench_named_splits_have_strict_offsets_and_counts() -> None:
    debug = resolve_finance_benchmark_split("debug50")
    test = resolve_finance_benchmark_split("test100")
    holdout = resolve_finance_benchmark_split("holdout100")

    assert debug is not None
    assert test is not None
    assert holdout is not None
    assert debug.split_id == "financebench_debug50"
    assert debug.offset == 0
    assert debug.limit == 50
    assert debug.expected_count == 50
    assert test.split_id == "financebench_test100"
    assert test.offset == 50
    assert test.limit == 100
    assert test.expected_count == 100
    assert holdout is test
    assert FINANCE_BENCHMARK_SPLITS["fb_holdout100"] is test


def test_financebench_debug50_and_test100_load_non_overlapping_rows(tmp_path: Path) -> None:
    dataset = tmp_path / "financebench_doc_retrieval.jsonl"
    dataset.write_text(
        "\n".join(
            json.dumps({"id": f"fb-{index:03d}", "question": f"Question {index}?", "answer": f"{index}"})
            for index in range(150)
        )
        + "\n",
        encoding="utf-8",
    )
    debug = resolve_finance_benchmark_split("debug50")
    test = resolve_finance_benchmark_split("test100")
    assert debug is not None
    assert test is not None

    debug_items = load_finance_benchmark_items(dataset, offset=debug.offset, limit=debug.limit)
    test_items = load_finance_benchmark_items(dataset, offset=test.offset, limit=test.limit)

    assert len(debug_items) == 50
    assert len(test_items) == 100
    assert debug_items[0].item_id == "fb-000"
    assert debug_items[-1].item_id == "fb-049"
    assert test_items[0].item_id == "fb-050"
    assert test_items[-1].item_id == "fb-149"
    assert {item.item_id for item in debug_items}.isdisjoint({item.item_id for item in test_items})


def test_financebench_doc_retrieval_rows_compile_with_evidence_scaffold() -> None:
    dataset = Path("data/bench/finance/financebench_doc_retrieval.jsonl")
    missing_evidence: list[tuple[int, str]] = []
    for index, line in enumerate(dataset.read_text(encoding="utf-8").splitlines()):
        row = json.loads(line)
        program = compile_finance_task_program(question=str(row.get("question") or ""), facts=[])
        if not program.evidence_specs:
            missing_evidence.append((index, str(row.get("id") or "")))

    assert len(missing_evidence) == 0


def test_finance_benchmark_outputs_record_split_metadata(tmp_path: Path) -> None:
    output = tmp_path / "results.jsonl"
    summary_path = tmp_path / "summary.json"
    split = resolve_finance_benchmark_split("test100")
    assert split is not None
    result = FinanceBenchmarkResult(
        item_id="fb-050",
        status="passed",
        question="What was revenue?",
        answer="Revenue was $10 million.",
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        scorecard={"status": "passed", "scored": True, "citation_present": True},
        trace_metrics={},
        trace_refs=[],
        final_answer={"citation_refs": ["cite-1"]},
        failure_report=None,
    )

    summary = write_finance_benchmark_outputs(
        [result],
        output_path=output,
        summary_path=summary_path,
        benchmark_split=split,
    )

    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary.benchmark_split["split_id"] == "financebench_test100"
    assert summary_payload["benchmark_split"]["offset"] == 50
    assert summary_payload["benchmark_split"]["limit"] == 100


def test_finance_benchmark_loads_workflow_annotations(tmp_path: Path) -> None:
    dataset = tmp_path / "workflow.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "WF1",
                "question": "Calculate DIO.",
                "workflow_type": "multi_entity_compute_compare",
                "required_slots": ["inventory_begin", "inventory_end", "cogs"],
                "evidence_policy": {"required_source_families": ["sec_filings"], "required_terms": ["inventory"]},
                "required_transforms": ["dio"],
                "dealbreakers": ["calculator_trace_required"],
                "expected_trace": ["claim_ledger", "slot_frame"],
                "failure_taxonomy": ["slot_filling"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    item = load_finance_benchmark_items(dataset)[0]

    assert item.workflow_type == "multi_entity_compute_compare"
    assert item.required_slots == ["inventory_begin", "inventory_end", "cogs"]
    assert item.evidence_policy["required_source_families"] == ["sec_filings"]
    assert item.required_transforms == ["dio"]
    assert item.dealbreakers == ["calculator_trace_required"]
    assert item.expected_trace == ["claim_ledger", "slot_frame"]
    assert item.failure_taxonomy == ["slot_filling"]


def test_checked_in_finance_workflow_datasets_are_trace_oriented() -> None:
    dev10 = load_finance_benchmark_items(Path("data/bench/finance/fabv2_dev10.jsonl"))
    public = load_finance_benchmark_items(Path("data/bench/finance/fabv2_public.jsonl"))
    challenge = load_finance_benchmark_items(Path("data/bench/finance/holo_finance_workflow_challenge.jsonl"))
    gold_records = _records(Path("data/bench/finance/fabv2_dev10.gold.jsonl"))

    assert len(dev10) == 10
    assert len(public) == 27
    assert len(challenge) == 50
    assert len(gold_records) == 10

    for item in [*dev10, *public, *challenge]:
        assert item.workflow_type
        assert item.required_slots
        assert item.evidence_policy.get("required_source_families")
        assert item.expected_trace
        assert item.failure_taxonomy
        for trace_name in ("claim_ledger", "slot_frame", "transform_plan", "verifier_gate", "synthesis_gate", "citation"):
            assert trace_name in item.expected_trace

    for item in challenge:
        assert item.gold_answer is None
        assert item.source == "holo_finance_workflow_challenge"

    for record in gold_records:
        assert record.get("workflow_type")
        assert record.get("required_slots")
        assert record.get("evidence_policy", {}).get("required_source_families")
        assert record.get("required_transforms") is not None
        assert record.get("dealbreakers")
        assert record.get("failure_taxonomy")


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


def test_finance_benchmark_numeric_scoring_respects_requested_reporting_unit() -> None:
    item = FinanceBenchmarkItem(
        item_id="num-usd-millions",
        question="What is the FY2018 capital expenditure amount (in USD millions) for 3M?",
        gold_answer="$1577.00",
        numeric_value=1577.0,
        tolerance=1.0,
    )

    verbose = score_finance_answer(item, answer="The FY2018 capital expenditure was $1,577 million.")
    compact = score_finance_answer(item, answer="The FY2018 capital expenditure was 1,577 (USD millions).")

    assert verbose["status"] == "passed"
    assert compact["status"] == "passed"
    assert 1577.0 in verbose["numeric"]["values"]
    assert 0.002018 not in verbose["numeric"]["values"]


def test_finance_dev_annotation_numeric_scoring_respects_requested_reporting_unit(tmp_path: Path) -> None:
    annotation = tmp_path / "dev_gold.jsonl"
    annotation.write_text(
        json.dumps(
            {
                "item_id": "num-usd-millions",
                "expected_numeric": [{"name": "capex", "value": 1577.0, "tolerance": 1.0}],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = FinanceBenchmarkResult(
        item_id="num-usd-millions",
        status="ungraded",
        question="What is the FY2018 capital expenditure amount (in USD millions) for 3M?",
        answer="The FY2018 capital expenditure was $1,577 million.",
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        scorecard={"status": "ungraded"},
        trace_metrics={},
        trace_refs=["ledger-1"],
        final_answer=None,
        failure_report=None,
    )

    score = score_finance_dev_annotations([result], annotation_path=annotation)

    assert score["numeric_score"] == 1.0


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


def test_finance_benchmark_sentinel_scoring_accepts_missing_evidence_wording() -> None:
    item = FinanceBenchmarkItem(
        item_id="adv-2",
        question="What was the segment revenue?",
        gold_answer="NOT_AVAILABLE in this excerpt",
    )

    score = score_finance_answer(
        item,
        answer="The provided evidence does not contain the requested annual segment revenue; the full annual figure is not present.",
    )

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


def test_finance_benchmark_sentinel_scoring_accepts_source_grounded_actual_value() -> None:
    item = FinanceBenchmarkItem(
        item_id="adv-actual-2",
        question="What was NVIDIA's Data Center segment revenue for fiscal year 2024?",
        gold_answer="NOT_AVAILABLE in this excerpt — $60.9 billion is NVIDIA's total revenue, not Data Center revenue",
    )

    score = score_finance_answer(
        item,
        answer="NVIDIA's Data Center segment revenue for fiscal year 2024 was $47.5 billion.",
        final_answer={"citation_refs": ["cite-1"]},
        trace_metrics={"numeric_verifier_passed": True, "verifier_gate_passed": True},
    )

    assert score["status"] == "passed"
    assert score["gold_sentinel"] is True
    assert score["source_grounded_actual_value"] is True
    assert score["reason"] == "sentinel_source_grounded_actual_answer"


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


def test_finance_benchmark_numeric_scoring_does_not_treat_company_3m_as_millions() -> None:
    item = FinanceBenchmarkItem(
        item_id="fb-3m-margin",
        question="What drove operating margin change for 3M?",
        gold_answer="Operating margin for 3M in FY2022 decreased by 1.7% due to lower gross margin.",
    )

    score = score_finance_answer(item, answer="I could not support an answer for 3M.")

    assert score["status"] == "failed"
    assert score["numeric"]["expected"] == 1.7
    assert score["numeric"]["values"] == []


def test_finance_benchmark_numeric_scoring_keeps_explicit_compact_currency_units() -> None:
    item = FinanceBenchmarkItem(
        item_id="fb-currency-compact",
        question="What was the charge?",
        gold_answer="The charge was $3M.",
    )

    score = score_finance_answer(item, answer="The charge was $3.0 million.")

    assert score["status"] == "passed"
    assert score["numeric"]["expected"] == 3_000_000


def test_finance_benchmark_failure_report_cannot_pass_gold_backed_numeric_question() -> None:
    item = FinanceBenchmarkItem(
        item_id="fb-failure-report",
        question="What drove operating margin change for 3M?",
        gold_answer="Operating margin for 3M in FY2022 decreased by 1.7%.",
    )

    score = score_finance_answer(
        item,
        answer="I could not support an answer for 3M.",
        final_answer=None,
        failure_report={"reason": "finance_numeric_verification_failed"},
    )

    assert score["status"] == "failed"
    assert score["reason"] == "failure_report_not_final_answer"


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


def test_finance_benchmark_runner_records_item_start_before_receive() -> None:
    journal = JournalStore.in_memory()
    runtime = _StaticChatRuntime(journal)
    item = FinanceBenchmarkItem(
        item_id="run-start",
        question="What was ExampleCo revenue?",
        gold_answer="$10 million",
        category="fact_extraction",
        workflow_type="defined_formula_numeric_calculation",
    )
    seen_starts: list[tuple[int, str, str]] = []

    def on_receive(_text: str, thread_id: str) -> None:
        starts = journal.records(kind="finance_benchmark_item_started")
        assert len(starts) == 1
        assert starts[0].data["item_id"] == "run-start"
        assert starts[0].data["thread_id"] == thread_id
        assert "gold_answer" not in starts[0].data

    runtime.on_receive = on_receive

    run_finance_benchmark(
        items=[item],
        runtime=runtime,
        journal=journal,
        start_callback=lambda index, started_item, thread_id: seen_starts.append((index, started_item.item_id, thread_id)),
    )

    assert seen_starts == [(1, "run-start", "finance-bench-0001-run-start")]


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


def test_financebench_import_modes_keep_gold_out_of_prompt(tmp_path: Path) -> None:
    source = tmp_path / "financebench.jsonl"
    source.write_text(
        json.dumps(
            {
                "financebench_id": "fb-001",
                "company": "ExampleCo",
                "doc_name": "ExampleCo FY2024 10-K",
                "question_type": "numeric",
                "question_reasoning": "requires revenue lookup",
                "question": "What was ExampleCo FY2024 revenue?",
                "answer": "$10 million",
                "justification": "Reference calculation that must stay scoring-only.",
                "evidence": "The filing evidence says revenue was $10 million.",
                "gics_sector": "Industrials",
                "doc_type": "10-K",
                "doc_period": "FY2024",
                "doc_link": "https://example.com/exampleco-10k.pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    oracle_output = tmp_path / "financebench.oracle.jsonl"
    manifest = tmp_path / "financebench.manifest.json"
    summary = convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=oracle_output,
        manifest_path=manifest,
        mode="oracle_evidence",
    )
    oracle_items = load_finance_benchmark_items(oracle_output)
    oracle_runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=oracle_items, runtime=oracle_runtime)

    assert summary.benchmark == "financebench"
    assert summary.mode == "oracle_evidence"
    assert oracle_items[0].item_id == "fb-001"
    assert oracle_items[0].gold_answer == "$10 million"
    assert oracle_items[0].evidence_excerpt == "The filing evidence says revenue was $10 million."
    assert oracle_items[0].metadata["reference_justification_policy"] == "scoring_only_not_prompted"
    assert "The filing evidence says revenue was $10 million." in oracle_runtime.seen_prompts[0]
    assert "Reference calculation" not in oracle_runtime.seen_prompts[0]
    assert "$10 million" in oracle_runtime.seen_prompts[0]  # evidence is intentionally prompted in oracle mode
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["prompt_policy"]["gold_answer_in_prompt"] is False
    assert manifest_payload["prompt_policy"]["import_mode"] == "oracle_evidence"

    doc_output = tmp_path / "financebench.doc.jsonl"
    convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=doc_output,
        mode="doc_retrieval",
    )
    doc_items = load_finance_benchmark_items(doc_output)
    doc_runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=doc_items, runtime=doc_runtime)
    assert "Source URL: https://example.com/exampleco-10k.pdf" in doc_runtime.seen_prompts[0]
    assert "https://example.com/exampleco-10k.pdf" in doc_runtime.seen_prompts[0]
    assert "This is an answerable public benchmark item" in doc_runtime.seen_prompts[0]
    assert "continue by changing method" in doc_runtime.seen_prompts[0]
    assert "FinanceBench target document metadata follows" not in doc_runtime.seen_prompts[0]
    assert "The filing evidence says revenue" not in doc_runtime.seen_prompts[0]
    assert "Reference calculation" not in doc_runtime.seen_prompts[0]
    assert doc_items[0].metadata["reference_evidence_policy"] == "scoring_only_not_prompted"

    question_output = tmp_path / "financebench.question.jsonl"
    convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=question_output,
        mode="question_only",
    )
    question_items = load_finance_benchmark_items(question_output)
    question_runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=question_items, runtime=question_runtime)
    assert "https://example.com/exampleco-10k.pdf" not in question_runtime.seen_prompts[0]
    assert "The filing evidence says revenue" not in question_runtime.seen_prompts[0]
    assert "Reference calculation" not in question_runtime.seen_prompts[0]
    assert question_items[0].metadata["source_refs"][0]["doc_type"] == "10-K"


def test_financebench_doc_retrieval_prompt_compiles_to_structured_payload(tmp_path: Path) -> None:
    source = tmp_path / "financebench.jsonl"
    source.write_text(
        json.dumps(
            {
                "financebench_id": "fb-doc-payload",
                "company": "3M",
                "doc_name": "3M_2018_10K",
                "question_type": "numeric",
                "question_reasoning": "requires cash flow statement lookup",
                "question": "What is the FY2018 capital expenditure amount for 3M?",
                "answer": "$1577.00",
                "evidence": "scoring-only evidence must not be prompted",
                "doc_type": "10k",
                "doc_period": "2018",
                "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "financebench.doc.jsonl"
    convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=output,
        mode="doc_retrieval",
    )
    item = load_finance_benchmark_items(output)[0]
    runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=[item], runtime=runtime)

    payload = _benchmark_doc_retrieval_payload(runtime.seen_prompts[0])

    assert payload["query"] == "3M 2018 10k What is the FY2018 capital expenditure amount for 3M?"
    assert payload["respect_explicit_budget"] is True
    assert payload["metadata"]["benchmark_doc_retrieval"] is True
    assert payload["metadata"]["retrieval_context_frozen"] is True
    assert payload["metadata"]["respect_explicit_budget"] is True
    assert payload["metadata"]["company"] == "3M"
    assert payload["metadata"]["doc_type"] == "10k"
    assert payload["metadata"]["sec_form"] == "10-K"
    assert payload["metadata"]["doc_period"] == "2018"
    source_urls = payload["metadata"]["source_urls"]
    assert "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf" in source_urls
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470.txt" in source_urls
    assert "https://www.sec.gov/Archives/edgar/data/1558370/000155837019000470/0001558370-19-000470-index.html" in source_urls
    hint = payload["metadata"]["compiled_task_hint"]
    assert hint["schema"] == "holo.kernel_v3.compiled_task_hint.v1"
    assert hint["task_spec"]["target_entities"] == ["3M"]
    assert hint["task_spec"]["target_periods"] == ["2018"]
    assert any(spec["slot_name"] == "capital_expenditures" for spec in hint["evidence_specs"])
    assert any(spec["statement"] == "cash_flow_statement" for spec in hint["evidence_specs"])
    assert "scoring-only evidence" not in runtime.seen_prompts[0]
    assert "script.exec" not in runtime.seen_prompts[0]
    assert "shell.exec" not in runtime.seen_prompts[0]
    assert "Tool availability is a harness interface detail" in runtime.seen_prompts[0]
    assert "Return only the requested answer" in runtime.seen_prompts[0]
    assert "document-analysis" not in runtime.seen_prompts[0]
    profile = infer_answer_profile(runtime.seen_prompts[0], response_language="en")
    assert profile.format == "answer"
    assert profile.detail_level == "normal"
    assert profile.target_sections == ["answer", "limitations"]


def test_financebench_doc_retrieval_payload_parses_inline_prompt_labels() -> None:
    prompt = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.  "
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf "
        "Company: 3M Document: 3M_2018_10K Document type: 10k Document period: 2018  "
        "What is the FY2018 capital expenditure amount (in USD millions) for 3M? "
        "Give a response to the question by relying on the details shown in the cash flow statement."
    )

    payload = _benchmark_doc_retrieval_payload(prompt)

    assert payload["query"].startswith("3M 2018 10k What is the FY2018 capital expenditure amount")
    assert payload["metadata"]["company"] == "3M"
    assert payload["metadata"]["doc_name"] == "3M_2018_10K"
    assert payload["metadata"]["doc_type"] == "10k"
    assert payload["metadata"]["doc_period"] == "2018"
    assert payload["metadata"]["source_url"] == (
        "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf"
    )
    binding = payload["metadata"]["target_document_binding"]
    assert binding["company"] == "3M"
    assert binding["doc_period"] == "2018"
    assert binding["primary_source_required"] is True
    assert binding["required_statement"] == "cash_flow_statement"
    assert binding["required_line_item"] == "capital expenditures"
    assert payload["metadata"]["compiled_task_hint"]["evidence_specs"][0]["line_item"] == "capital expenditures"


def test_financebench_doc_retrieval_payload_unwraps_adobe_pdf_target() -> None:
    wrapper_url = (
        "https://www.adobe.com/pdf-page.html?pdfTarget="
        "aHR0cHM6Ly93d3cuYWRvYmUuY29tL2NvbnRlbnQvZGFtL2NjL2VuL2ludmVzdG9yLXJlbGF0aW9ucy9wZGZzL0FEQkUtMTBLLUZZMTUtRklOQUwucGRm"
    )
    pdf_url = "https://www.adobe.com/content/dam/cc/en/investor-relations/pdfs/ADBE-10K-FY15-FINAL.pdf"
    prompt = (
        "FinanceBench target document metadata follows. Use it to acquire evidence; it is not answer evidence by itself.\n"
        "Company: Adobe\n"
        "Document: ADOBE_2015_10K\n"
        "Document type: 10k\n"
        "Document period: 2015\n"
        f"Document link: {wrapper_url}\n"
        "What is the FY2015 operating cash flow ratio for Adobe?"
    )

    payload = _benchmark_doc_retrieval_payload(prompt)

    source_urls = payload["metadata"]["source_urls"]
    assert source_urls[0] == pdf_url
    assert wrapper_url in source_urls
    assert payload["metadata"]["preferred_source_urls"][0] == pdf_url
    assert payload["metadata"]["target_document_binding"]["doc_link"] == wrapper_url


def test_financebench_doc_retrieval_payload_stops_inline_period_before_assume_question() -> None:
    prompt = (
        "Benchmark target source follows. Acquire evidence from Source URL first; it is not answer evidence by itself. "
        "Prefer direct URL fetch before broad search.  "
        "Source URL: https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf "
        "Company: 3M Document: 3M_2018_10K Document type: 10k Document period: 2018  "
        "Assume that you are a public equities analyst. Answer the following question by primarily using information "
        "that is shown in the balance sheet: what is the year end FY2018 net PPNE for 3M? Answer in USD billions."
    )

    payload = _benchmark_doc_retrieval_payload(prompt)

    assert payload["metadata"]["doc_period"] == "2018"
    assert payload["query"].startswith("3M 2018 10k Assume that you are a public equities analyst")
    binding = payload["metadata"]["target_document_binding"]
    assert binding["doc_period"] == "2018"
    assert binding["required_statement"] == "balance_sheet"
    assert binding["required_line_item"] == "property plant and equipment net"


def test_financebench_import_can_emit_scoring_annotation_sidecar(tmp_path: Path) -> None:
    source = tmp_path / "financebench.jsonl"
    source.write_text(
        json.dumps(
            {
                "financebench_id": "fb-annotation-001",
                "company": "ExampleCo",
                "doc_name": "ExampleCo FY2024 10-K",
                "question_type": "quantitative",
                "question": "What was ExampleCo FY2024 revenue?",
                "answer": "$10 million",
                "justification": "The reference answer is derived from the revenue line.",
                "evidence": "The filing evidence says revenue was $10 million.",
                "doc_type": "10-K",
                "doc_period": "FY2024",
                "doc_link": "https://www.sec.gov/exampleco-10k.htm",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "financebench.normalized.jsonl"
    annotation = tmp_path / "financebench.gold.jsonl"
    convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=dataset,
        mode="doc_retrieval",
    )

    export_summary = write_finance_dev_annotations_from_dataset(
        dataset_path=dataset,
        annotation_path=annotation,
    )
    annotations = [json.loads(line) for line in annotation.read_text(encoding="utf-8").splitlines()]

    assert export_summary["item_count"] == 1
    assert annotations[0]["item_id"] == "fb-annotation-001"
    assert annotations[0]["gold_policy"] == "scoring_only_not_prompted"
    assert annotations[0]["expected_numeric"][0]["value"] == 10_000_000
    assert "10-k" in annotations[0]["required_sources"]
    assert "www.sec.gov" in annotations[0]["required_sources"]
    assert "citation_required" in annotations[0]["dealbreakers"]

    items = load_finance_benchmark_items(dataset)
    runtime = _StaticChatRuntime(JournalStore.in_memory())
    results = run_finance_benchmark(items=items, runtime=runtime)
    score = score_finance_dev_annotations(results, annotation_path=annotation)
    assert score["numeric_score"] == 1.0
    assert "The reference answer" not in runtime.seen_prompts[0]


def test_financebench_annotation_export_ignores_company_name_numeric_token(tmp_path: Path) -> None:
    dataset = tmp_path / "financebench-3m.normalized.jsonl"
    annotation = tmp_path / "financebench-3m.gold.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "id": "financebench_id_01226",
                "question": "What drove operating margin change for 3M?",
                "gold_answer": "Operating margin for 3M in FY2022 decreased by 1.7%.",
                "source": "financebench",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    write_finance_dev_annotations_from_dataset(dataset_path=dataset, annotation_path=annotation)
    annotations = [json.loads(line) for line in annotation.read_text(encoding="utf-8").splitlines()]

    assert [item["value"] for item in annotations[0]["expected_numeric"]] == [1.7]


def test_benchmark_provided_context_creates_source_grounded_trace(tmp_path: Path) -> None:
    source = tmp_path / "financebench.jsonl"
    source.write_text(
        json.dumps(
            {
                "financebench_id": "fb-trace-001",
                "company": "ExampleCo",
                "doc_name": "ExampleCo FY2024 10-K",
                "question_type": "metrics-generated",
                "question": "What was ExampleCo FY2024 revenue?",
                "answer": "$10 million",
                "evidence": "The FY2024 filing says revenue was $10 million.",
                "doc_type": "10-K",
                "doc_period": "FY2024",
                "doc_link": "https://example.com/exampleco-10k.pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    dataset = tmp_path / "financebench.normalized.jsonl"
    convert_public_finance_benchmark(
        benchmark="financebench",
        input_path=source,
        output_path=dataset,
        mode="oracle_evidence",
    )
    items = load_finance_benchmark_items(dataset)
    runtime = _StaticChatRuntime(JournalStore.in_memory())
    result = run_finance_benchmark(items=items, runtime=runtime)[0]

    assert "First solve directly from this context" in runtime.seen_prompts[0]
    assert "do not call live retrieval only to reacquire" in runtime.seen_prompts[0]
    assert result.trace_metrics["claim_ledger_present"] is True
    assert result.trace_metrics["claim_count"] == 1
    assert result.trace_metrics["slot_frame_present"] is True
    assert result.trace_metrics["missing_slot_count"] == 0
    assert result.trace_metrics["transform_plan_count"] == 1
    assert result.trace_metrics["verifier_gate_status"] == "passed"
    assert "example.com" in result.trace_metrics["source_hosts"]


def test_doc_retrieval_metadata_is_not_written_as_evidence_claim() -> None:
    journal = JournalStore.in_memory()
    item = FinanceBenchmarkItem(
        item_id="fb-doc-001",
        question="What was capex?",
        evidence_excerpt="Reference evidence is scoring-only and must not become prompt evidence.",
        source="financebench",
        workflow_type="source_grounded_research",
        required_slots=["entity", "period", "source"],
        metadata={
            "import_mode": "doc_retrieval",
            "company": "ExampleCo",
            "doc_period": "2024",
            "prompt_context": "Document link: https://example.com/report.pdf",
            "source_refs": [{"url": "https://example.com/report.pdf"}],
        },
    )

    _append_benchmark_provided_context_trace(journal, item=item, task_id="task-doc", run_id="run-1")

    metrics = trace_metrics(journal, task_id="task-doc")
    assert metrics["claim_ledger_present"] is False
    assert metrics["claim_count"] == 0


def test_finqa_import_supports_oracle_context_and_question_only_modes(tmp_path: Path) -> None:
    source = tmp_path / "finqa.json"
    source.write_text(
        json.dumps(
            [
                {
                    "qa": {
                        "question": "What is revenue growth?",
                        "answer": "10%",
                        "program": "subtract(divide(...))",
                    },
                    "pre_text": "Revenue increased from 100 to 110.",
                    "post_text": "Management attributed the increase to volume.",
                    "table": [["year", "revenue"], ["2023", "100"], ["2024", "110"]],
                    "question_type": "numeric",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    oracle_output = tmp_path / "finqa.oracle.jsonl"
    convert_public_finance_benchmark(
        benchmark="finqa",
        input_path=source,
        output_path=oracle_output,
        mode="oracle_context",
    )
    oracle_items = load_finance_benchmark_items(oracle_output)
    oracle_runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=oracle_items, runtime=oracle_runtime)
    assert "Revenue increased from 100 to 110." in oracle_runtime.seen_prompts[0]
    assert "subtract(divide" not in oracle_runtime.seen_prompts[0]
    assert "10%" not in oracle_runtime.seen_prompts[0]
    assert oracle_items[0].metadata["reference_program_policy"] == "scoring_only_not_prompted"
    assert oracle_items[0].workflow_type == "numeric_reasoning"
    assert oracle_items[0].required_slots == ["question_context", "input_values", "formula_or_operation", "answer_unit"]
    assert oracle_items[0].required_transforms == ["numeric_reasoning"]
    assert "calculator.compute" in oracle_items[0].expected_trace
    assert oracle_items[0].evidence_policy["required_source_families"] == ["provided_report_context"]

    question_output = tmp_path / "finqa.question.jsonl"
    convert_public_finance_benchmark(
        benchmark="finqa",
        input_path=source,
        output_path=question_output,
        mode="question_only",
    )
    question_items = load_finance_benchmark_items(question_output)
    question_runtime = _StaticChatRuntime(JournalStore.in_memory())
    run_finance_benchmark(items=question_items, runtime=question_runtime)
    assert "Revenue increased from 100 to 110." not in question_runtime.seen_prompts[0]
    assert "subtract(divide" not in question_runtime.seen_prompts[0]
    assert "10%" not in question_runtime.seen_prompts[0]


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
    dev_gold = tmp_path / "dev_gold.jsonl"
    dataset.write_text(
        json.dumps({"id": "Q1", "question": "Revenue?", "numeric_value": 10_000_000, "tolerance": 1}) + "\n",
        encoding="utf-8",
    )
    predictions.write_text(
        json.dumps(
            {
                "id": "Q1",
                "answer": "Revenue was 10,000,000.",
                "trace_metrics": {"total_tokens": 123, "calculator_call_count": 1},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    dev_gold.write_text(
        json.dumps(
            {
                "item_id": "Q1",
                "expected_numeric": [{"name": "revenue", "value": 10_000_000, "tolerance": 1}],
                "required_trace": ["calculator.compute"],
            }
        )
        + "\n",
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
            "--dev-gold",
            str(dev_gold),
        ]
    )

    assert code == 0
    payload = json.loads(summary.read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.kernel_v3.finance_benchmark_summary.v1"
    assert payload["passed_count"] == 1
    assert payload["numeric_accuracy"] == 1.0
    assert payload["dev_annotation_score"]["numeric_score"] == 1.0
    assert payload["dev_annotation_score"]["substrate_score"] == 1.0
    assert output.exists()


def test_finance_benchmark_live_blocks_before_writing_rows_when_api_key_missing(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    dataset = tmp_path / "dataset.jsonl"
    output = tmp_path / "results.jsonl"
    summary = tmp_path / "summary.json"
    journal = tmp_path / "journal.jsonl"
    index = tmp_path / "journal.sqlite"
    dataset.write_text(json.dumps({"id": "Q1", "question": "Revenue?"}) + "\n", encoding="utf-8")
    monkeypatch.setenv("HOLO_V3_LIVE_MODEL", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setattr(
        cli,
        "_read_windows_env_value",
        lambda name: {"checked": True, "value": "", "error": "windows interop unavailable"},
    )

    code = cli.main(
        [
            "--journal",
            str(journal),
            "--index",
            str(index),
            "bench",
            "finance",
            "--dataset",
            str(dataset),
            "--output",
            str(output),
            "--summary-output",
            str(summary),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 1
    assert payload["status"] == "blocked"
    assert payload["reason"] == "missing_live_model_api_key"
    assert payload["api_key_env"] == "DEEPSEEK_API_KEY"
    assert not output.exists()
    assert not summary.exists()
    assert not JournalStore(journal, index_path=index).records(kind="finance_benchmark_item_started")


def test_finance_dev_annotation_scorer_keeps_gold_post_run(tmp_path: Path) -> None:
    annotation = tmp_path / "dev_gold.jsonl"
    annotation.write_text(
        json.dumps(
            {
                "item_id": "fabv2-hd-low-dio",
                "expected_answer_contains": ["Home Depot", "DIO", "days"],
                "expected_numeric": [{"name": "HD_DIO", "value": 77.6, "tolerance": 1.0}],
                "required_trace": ["retrieval.run", "calculator.compute", "finance_numeric_verification"],
                "expected_trace": ["claim_ledger", "slot_frame", "transform_plan", "verifier_gate", "synthesis_gate"],
                "required_sources": ["sec.gov", "10-K"],
                "workflow_type": "multi_entity_compute_compare",
                "required_slots": ["inventory_begin", "inventory_end", "cogs"],
                "required_transforms": ["dio"],
                "evidence_policy": {"required_source_families": ["sec_filings"], "required_terms": ["inventory"]},
                "dealbreakers": ["citation_required", "calculator_trace_required", "synthesis_gate_pass_required"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = FinanceBenchmarkResult(
        item_id="fabv2-hd-low-dio",
        status="ungraded",
        question="Calculate HD DIO.",
        answer="Home Depot DIO was 77.6 days, based on inventory and COGS in the 10-K from sec.gov.",
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        scorecard={"status": "ungraded", "citation_present": True},
        trace_metrics={
            "retrieval_run_count": 1,
            "calculator_call_count": 1,
            "formula_trace_count": 1,
            "finance_fact_count": 4,
            "numeric_verifier_status": "passed",
            "verifier_gate_status": "passed",
            "synthesis_gate_status": "passed",
            "source_hosts": ["www.sec.gov"],
            "finance_source_forms": ["10-K"],
            "claim_ledger_present": True,
            "slot_frame_present": True,
            "missing_slots": [],
            "missing_slot_count": 0,
            "transform_plan_count": 1,
            "transform_methods": ["dio"],
        },
        trace_refs=["ledger-1"],
        final_answer=None,
        failure_report=None,
    )

    score = score_finance_dev_annotations([result], annotation_path=annotation)

    assert score["scored_item_count"] == 1
    assert score["behavior_score"] == 1.0
    assert score["numeric_score"] == 1.0
    assert score["substrate_score"] == 1.0
    assert score["workflow_score"] == 1.0
    assert score["workflow_type_scores"]["multi_entity_compute_compare"]["workflow_score"] == 1.0


def test_finance_dev_annotation_scorer_accepts_localized_units(tmp_path: Path) -> None:
    annotation = tmp_path / "dev_gold.jsonl"
    annotation.write_text(
        json.dumps(
            {
                "item_id": "fabv2-hd-low-dio",
                "expected_answer_contains": ["Home Depot", "DIO", "days"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    result = FinanceBenchmarkResult(
        item_id="fabv2-hd-low-dio",
        status="ungraded",
        question="Calculate HD DIO.",
        answer="Home Depot 的 DIO 约为 76.3 天。",
        task_id="task-1",
        run_id="run-1",
        thread_id="thread-1",
        scorecard={"status": "ungraded"},
        trace_metrics={},
        trace_refs=["ledger-1"],
        final_answer=None,
        failure_report=None,
    )

    score = score_finance_dev_annotations([result], annotation_path=annotation)

    assert score["behavior_score"] == 1.0


def test_finance_trace_metrics_include_substrate_and_source_data() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-retrieve",
        kind="action",
        data={"kind": "tool", "name": "retrieval.run", "action_id": "act-retrieve"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-calc",
        kind="action",
        data={"kind": "tool", "name": "calculator.compute", "action_id": "act-calc"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-calc-repeat",
        kind="action",
        data={"kind": "tool", "name": "calculator.compute", "action_id": "act-calc-repeat"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-respond",
        kind="action",
        data={"kind": "respond", "name": None, "action_id": "act-respond"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-retrieve",
        kind="observation",
        data={
            "source": "tool:retrieval.run",
            "status": "failed",
            "content": {"reason": "network_failed"},
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="observation",
        data={
            "source": "tool:calculator.compute",
            "status": "ok",
            "content": {
                "formula_trace": {
                    "formula_id": "formula-1",
                    "result_value": "77.6",
                    "input_fact_ids": ["fact-capex", "fact-revenue"],
                }
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="finance_fact_ledger",
        data={
            "fact_count": 4,
            "facts": [
                {
                    "fact_id": "fact-capex",
                    "evidence_ref": "evidence-capex",
                    "citation_ref": "cite-capex",
                    "metadata": {"form": "10-K"},
                },
                {
                    "fact_id": "fact-revenue",
                    "evidence_ref": "evidence-revenue",
                    "citation_ref": "cite-revenue",
                    "metadata": {"form": "10-K"},
                },
            ],
            "primary_source_numeric_binding": {
                "status": "selected",
                "selected_fact_ids": ["target-1577m"],
                "selected_count": 1,
                "rejected_count": 1,
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="finance_numeric_verification",
        data={"status": "passed", "matched_values": [{}], "diagnostics": {"answer_numeric_count": 1}},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="retrieval_citation",
        data={"uri": "https://www.sec.gov/Archives/example", "citation_id": "cite-1"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="claim_ledger",
        data={"claim_count": 4, "claims": [{"claim_id": "claim-1"}]},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="slot_frame",
        data={"task_type": "compute", "missing_slots": ["cogs"]},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="transform_plan",
        data={"status": "ready", "method": "dio"},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="transform_plan",
        data={"status": "missing_slots", "method": "ev_revenue", "missing_slots": ["debt"]},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="verifier_gate_result",
        data={"status": "failed", "issues": [{"code": "missing_formula_trace"}, {"code": "period_mismatch"}]},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="synthesis_gate_result",
        data={"status": "failed", "issues": [{"code": "unsupported_answer_number"}]},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="synthesis_gate_result",
        data={"status": "passed", "issues": [], "diagnostics": {"attempt": "fallback"}},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-1",
        kind="context",
        data={
            "context_id": "ctx-1",
            "state": {
                "toolchain_state": {},
                "finance_working_state": {},
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-2",
        kind="context",
        data={
            "context_id": "ctx-2",
            "state": {
                "toolchain_state": {"action_count": 1, "toolchain_presence": {"retrieval": True}},
                "finance_working_state": {},
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-3",
        kind="context",
        data={
            "context_id": "ctx-3",
            "state": {
                "toolchain_state": {
                    "action_count": 2,
                    "toolchain_presence": {"calculator": True},
                    "recent_tool_observations": [
                        {
                            "source": "tool:finance.verify_numeric",
                            "observation_diagnostics": {
                                "issue_codes": ["unsupported_answer_number"],
                                "repair_options": ["ask synthesis to remove unsupported numbers"],
                            },
                        }
                    ],
                },
                "finance_working_state": {"ledger_count": 1, "fact_count": 4},
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="processor_result",
        data={
            "task_type": "task.compile",
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "status": "ok",
            "duration_ms": 100,
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_cache_hit_tokens": 90,
                "prompt_cache_miss_tokens": 10,
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id=None,
        kind="processor_result",
        data={
            "task_type": "finance.slot_bind",
            "provider": "deepseek",
            "model": "deepseek-reasoner",
            "status": "failed",
            "error": "json_invalid",
            "duration_ms": 200,
            "usage": {
                "prompt_tokens": 80,
                "completion_tokens": 10,
                "total_tokens": 90,
                "prompt_cache_hit_tokens": 30,
                "prompt_cache_miss_tokens": 50,
            },
        },
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-final",
        kind="agent_final_answer",
        data={"answer": "Final answer."},
    )
    journal.append(
        task_id="task-fin",
        run_id="run-1",
        step_id="step-post",
        kind="memory_proposal",
        data={"status": "pending"},
    )

    metrics = trace_metrics(journal, task_id="task-fin")

    assert metrics["processor_call_count"] == 2
    assert metrics["processor_error_count"] == 1
    assert metrics["total_tokens"] == 210
    assert metrics["processor_duration_ms"] == 300
    assert metrics["processor_prompt_cache_hit_tokens"] == 120
    assert metrics["processor_prompt_cache_miss_tokens"] == 60
    assert metrics["processor_prompt_cache_hit_ratio"] == 0.666667
    assert metrics["context_record_count"] == 3
    assert metrics["context_dynamic_state_present_count"] == 2
    assert metrics["context_dynamic_state_present_rate"] == 0.6667
    assert metrics["context_toolchain_state_present_count"] == 2
    assert metrics["context_toolchain_state_empty_count"] == 1
    assert metrics["context_toolchain_state_prompt_eligible_rate"] == 0.6667
    assert metrics["context_toolchain_observation_diagnostics_present_count"] == 1
    assert metrics["context_toolchain_observation_diagnostics_prompt_eligible_rate"] == 0.3333
    assert metrics["context_finance_working_state_present_count"] == 1
    assert metrics["context_finance_working_state_empty_count"] == 2
    assert metrics["context_finance_working_state_prompt_eligible_rate"] == 0.3333
    assert metrics["latest_context_toolchain_state_present"] is True
    assert metrics["latest_context_toolchain_observation_diagnostics_present"] is True
    assert metrics["latest_context_finance_working_state_present"] is True
    assert metrics["processor_usage_by_task_type"]["task.compile"]["call_count"] == 1
    assert metrics["processor_usage_by_task_type"]["finance.slot_bind"]["failed_count"] == 1
    assert metrics["processor_error_counts"] == {"json_invalid": 1}
    assert metrics["agent_loop_stage_counts"]["Plan"] == 6
    assert metrics["agent_loop_stage_counts"]["Tools"] == 2
    assert metrics["agent_loop_stage_counts"]["Evidence"] == 4
    assert metrics["agent_loop_stage_counts"]["Verify"] == 6
    assert metrics["agent_loop_stage_counts"]["Answer"] == 1
    assert metrics["agent_loop_visited_stage_count"] == 5
    assert metrics["agent_loop_stage_total_count"] == 8
    assert metrics["agent_loop_stage_coverage_rate"] == 0.625
    assert metrics["agent_loop_terminal"] is True
    assert metrics["agent_loop_delta_count"] == 19
    assert metrics["agent_loop_transition_count"] == 7
    assert metrics["agent_loop_tool_stage_present"] is True
    assert metrics["agent_loop_search_stage_present"] is False
    assert metrics["agent_loop_verify_stage_present"] is True
    assert metrics["post_final_record_count"] == 1
    assert metrics["post_final_record_kind_counts"] == {"memory_proposal": 1}
    assert metrics["post_final_clean"] is False
    assert metrics["tool_action_count"] == 3
    assert metrics["tool_action_unique_count"] == 2
    assert metrics["tool_action_repeated_count"] == 1
    assert metrics["tool_action_repetition_rate"] == 0.3333
    assert metrics["tool_action_payload_unique_count"] == 2
    assert metrics["tool_action_payload_repeated_count"] == 1
    assert metrics["tool_action_payload_repetition_rate"] == 0.3333
    assert metrics["tool_action_payload_repeated_group_count"] == 1
    assert metrics["tool_action_payload_max_repeat_count"] == 2
    assert metrics["tool_action_payload_repeated_tool_counts"] == {"calculator.compute": 1}
    assert metrics["tool_observation_count"] == 2
    assert metrics["tool_observation_source_counts"] == {
        "tool:calculator.compute": 1,
        "tool:retrieval.run": 1,
    }
    assert metrics["tool_observation_error_count"] == 1
    assert metrics["tool_observation_error_rate"] == 0.5
    assert metrics["toolchain_depth"] == 2
    assert metrics["retrieval_tool_present"] is True
    assert metrics["calculator_tool_present"] is True
    assert metrics["finance_verify_tool_present"] is False
    assert metrics["retrieval_calculator_verifier_chain_present"] is False
    assert metrics["calculator_call_count"] == 1
    assert metrics["formula_trace_count"] == 1
    assert metrics["formula_trace_support_count"] == 1
    assert metrics["formula_trace_fact_linked_count"] == 1
    assert metrics["formula_trace_citation_linked_count"] == 1
    assert metrics["formula_trace_evidence_linked_count"] == 1
    assert metrics["formula_trace_fact_link_rate"] == 1.0
    assert metrics["formula_trace_citation_link_rate"] == 1.0
    assert metrics["formula_trace_evidence_link_rate"] == 1.0
    assert metrics["formula_trace_input_fact_missing_count"] == 0
    assert metrics["finance_fact_count"] == 4
    assert metrics["numeric_verifier_status"] == "passed"
    assert metrics["answer_numeric_support_rate"] == 1.0
    assert metrics["source_hosts"] == ["www.sec.gov"]
    assert metrics["finance_source_forms"] == ["10-K"]
    assert metrics["primary_source_numeric_binding_status"] == "selected"
    assert metrics["primary_source_numeric_binding_selected_count"] == 1
    assert metrics["primary_source_numeric_binding_rejected_count"] == 1
    assert metrics["primary_source_numeric_binding_selected_fact_ids"] == ["target-1577m"]
    assert metrics["claim_ledger_present"] is True
    assert metrics["claim_count"] == 4
    assert metrics["slot_frame_present"] is True
    assert metrics["missing_slot_count"] == 1
    assert metrics["missing_slots"] == ["cogs"]
    assert metrics["transform_plan_present"] is True
    assert metrics["transform_plan_count"] == 2
    assert "dio" in metrics["transform_methods"]
    assert metrics["ready_transform_plan_count"] == 1
    assert metrics["missing_slot_transform_plan_count"] == 1
    assert metrics["verifier_gate_status"] == "failed"
    assert metrics["verifier_gate_passed"] is False
    assert metrics["verifier_gate_issue_count"] == 2
    assert metrics["synthesis_gate_status"] == "passed"
    assert metrics["synthesis_gate_attempt_count"] == 2
    assert metrics["synthesis_gate_repaired"] is True


def test_finance_trace_metrics_include_verify_numeric_tool_observation() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-verify-tool",
        run_id="run-1",
        step_id="step-verify",
        kind="observation",
        data={
            "observation_id": "obs-verify-1",
            "kind": "finance_numeric_verification",
            "status": "ok",
            "source": "tool:finance.verify_numeric",
            "content": {
                "verifier_status": "passed",
                "issue_count": 1,
                "verification": {
                    "status": "passed",
                    "issues": [{"code": "unsupported_answer_number"}],
                    "matched_values": [{"value": "10000000"}],
                    "missing_values": [],
                    "formula_traces": [],
                    "diagnostics": {"answer_numeric_count": 1},
                },
                "repair_guidance": {
                    "schema": "holo.kernel_v3.finance_numeric_repair_guidance.v1",
                    "issue_codes": ["unsupported_answer_number"],
                    "repair_options": ["ask synthesis to remove unsupported answer numbers"],
                    "missing_value_examples": [],
                },
            },
            "action_id": "act-verify",
            "tool_call_id": None,
        },
    )
    journal.append(
        task_id="task-verify-tool",
        run_id="run-1",
        step_id="step-verify-error",
        kind="observation",
        data={
            "observation_id": "obs-verify-2",
            "kind": "finance_numeric_verification",
            "status": "failed",
            "source": "tool:finance.verify_numeric",
            "content": {"error": "invalid_tool_payload"},
            "action_id": "act-verify-bad",
            "tool_call_id": None,
        },
    )

    metrics = trace_metrics(journal, task_id="task-verify-tool")

    assert metrics["finance_verify_numeric_tool_call_count"] == 2
    assert metrics["finance_verify_numeric_tool_error_count"] == 1
    assert metrics["tool_observation_diagnostics_count"] == 2
    assert metrics["tool_observation_repair_guidance_count"] == 1
    assert metrics["tool_observation_diagnostics_rate"] == 1.0
    assert metrics["tool_observation_repair_guidance_rate"] == 0.5
    assert metrics["tool_observation_diagnostic_issue_code_counts"] == {"unsupported_answer_number": 1}
    assert metrics["numeric_verifier_status"] == "passed"
    assert metrics["numeric_verifier_passed"] is True
    assert metrics["answer_numeric_support_rate"] == 1.0
    assert metrics["finance_numeric_failure_reasons"] == ["unsupported_answer_number"]


def test_finance_trace_metrics_include_structured_repair_recovery() -> None:
    journal = JournalStore.in_memory()
    journal.append(
        task_id="task-repair",
        run_id="run-1",
        step_id="task-compile-retry",
        kind="processor_result",
        data={"task_type": "task.compile", "status": "ok", "usage": {}},
    )
    journal.append(
        task_id="task-repair",
        run_id="run-1",
        step_id=None,
        kind="processor_request",
        data={
            "request_id": "req-synth-json-repair",
            "task_type": "synthesizer.answer",
            "context_id": "ctx-synth-json-repair",
            "parameters": {
                "repair_reason": "invalid_json",
                "repair_feedback_schema": "holo.kernel_v3.synthesizer_repair_feedback.v1",
            },
        },
    )
    journal.append(
        task_id="task-repair",
        run_id="run-1",
        step_id=None,
        kind="processor_result",
        data={"request_id": "req-synth-json-repair", "task_type": "synthesizer.answer", "status": "ok", "usage": {}},
    )
    journal.append(
        task_id="task-repair",
        run_id="run-1",
        step_id=None,
        kind="finance_slot_bind",
        data={
            "status": "ready",
            "repair_attempted": True,
            "repair_processor_status": "ok",
            "repair_feedback": {"category": "malformed_json"},
        },
    )

    metrics = trace_metrics(journal, task_id="task-repair")

    assert metrics["task_compile_retry_count"] == 1
    assert metrics["task_compile_retry_success_count"] == 1
    assert metrics["finance_slot_bind_repair_attempt_count"] == 1
    assert metrics["finance_slot_bind_repair_success_count"] == 1
    assert metrics["synthesizer_json_repair_attempt_count"] == 1
    assert metrics["synthesizer_json_repair_success_count"] == 1
    assert metrics["structured_repair_attempt_count"] == 3
    assert metrics["structured_repair_success_count"] == 3
    assert metrics["structured_repair_success_rate"] == 1.0


def test_finance_benchmark_summary_includes_generic_substrate_rates() -> None:
    results = [
        FinanceBenchmarkResult(
            item_id="Q1",
            status="ungraded",
            question="Q1?",
            answer="answer",
            task_id="task-1",
            run_id="run-1",
            thread_id="thread-1",
            scorecard={"status": "ungraded", "answer_present": True, "citation_present": True},
            trace_metrics={
                "claim_ledger_present": True,
                "claim_count": 4,
                "slot_frame_present": True,
                "missing_slot_count": 1,
                "transform_plan_count": 2,
                "verifier_gate_status": "passed",
                "synthesis_gate_status": "passed",
                "synthesis_gate_attempt_count": 2,
                "synthesis_gate_repaired": True,
                "finance_numeric_failure_reasons": [],
                "agent_loop_stage_counts": {
                    "Intake": 1,
                    "Plan": 2,
                    "Policy": 1,
                    "Tools": 2,
                    "Search": 1,
                    "Evidence": 3,
                    "Verify": 2,
                    "Answer": 1,
                },
                "agent_loop_stage_coverage_rate": 1.0,
                "agent_loop_terminal": True,
                "agent_loop_tool_stage_present": True,
                "agent_loop_search_stage_present": True,
                "agent_loop_verify_stage_present": True,
                "agent_loop_delta_count": 13,
                "agent_loop_transition_count": 8,
                "toolchain_depth": 3,
                "retrieval_calculator_verifier_chain_present": True,
                "tool_observation_error_rate": 0.0,
                "tool_action_repetition_rate": 0.25,
                "tool_action_payload_repetition_rate": 0.2,
                "tool_action_payload_repeated_group_count": 1,
                "tool_action_payload_max_repeat_count": 2,
                "tool_action_payload_repeated_tool_counts": {"calculator.compute": 1},
                "tool_observation_source_counts": {
                    "tool:retrieval.run": 1,
                    "tool:calculator.compute": 2,
                    "tool:finance.verify_numeric": 2,
                },
                "tool_observation_count": 5,
                "tool_observation_diagnostics_count": 2,
                "tool_observation_repair_guidance_count": 1,
                "tool_observation_diagnostic_issue_code_counts": {"unsupported_answer_number": 1},
                "post_final_record_count": 0,
                "post_final_record_kind_counts": {},
                "finance_verify_numeric_tool_call_count": 2,
                "finance_verify_numeric_tool_error_count": 1,
                "processor_prompt_cache_hit_tokens": 40,
                "processor_prompt_cache_miss_tokens": 10,
                "context_record_count": 2,
                "context_dynamic_state_present_count": 1,
                "context_toolchain_state_present_count": 1,
                "context_toolchain_state_empty_count": 1,
                "context_toolchain_observation_diagnostics_present_count": 1,
                "context_finance_working_state_present_count": 1,
                "context_finance_working_state_empty_count": 1,
                "processor_usage_by_task_type": {
                    "task.compile": {
                        "call_count": 1,
                        "prompt_cache_hit_tokens": 40,
                        "prompt_cache_miss_tokens": 10,
                        "total_tokens": 100,
                    }
                },
                "processor_error_counts": {},
                "task_compile_retry_count": 1,
                "task_compile_retry_success_count": 1,
                "synthesizer_json_repair_attempt_count": 1,
                "synthesizer_json_repair_success_count": 1,
                "structured_repair_attempt_count": 2,
                "structured_repair_success_count": 2,
                "formula_trace_support_count": 2,
                "formula_trace_fact_linked_count": 2,
                "formula_trace_citation_linked_count": 1,
                "formula_trace_evidence_linked_count": 2,
            },
            trace_refs=[],
            final_answer=None,
            failure_report=None,
        ),
        FinanceBenchmarkResult(
            item_id="Q2",
            status="ungraded",
            question="Q2?",
            answer="answer",
            task_id="task-2",
            run_id="run-2",
            thread_id="thread-2",
            scorecard={"status": "ungraded", "answer_present": True, "citation_present": False},
            trace_metrics={
                "claim_ledger_present": False,
                "claim_count": 0,
                "slot_frame_present": False,
                "missing_slot_count": 0,
                "transform_plan_count": 0,
                "verifier_gate_status": "failed",
                "synthesis_gate_status": "failed",
                "finance_numeric_failure_reason": "unsupported_answer_number",
                "finance_numeric_failure_reasons": ["unsupported_answer_number"],
                "agent_loop_stage_counts": {
                    "Intake": 1,
                    "Plan": 2,
                    "Policy": 1,
                    "Tools": 1,
                    "Search": 0,
                    "Evidence": 1,
                    "Verify": 0,
                    "Answer": 1,
                },
                "agent_loop_stage_coverage_rate": 0.625,
                "agent_loop_terminal": True,
                "agent_loop_tool_stage_present": True,
                "agent_loop_search_stage_present": False,
                "agent_loop_verify_stage_present": False,
                "agent_loop_delta_count": 7,
                "agent_loop_transition_count": 5,
                "toolchain_depth": 1,
                "retrieval_calculator_verifier_chain_present": False,
                "tool_observation_error_rate": 0.5,
                "tool_action_repetition_rate": 0.0,
                "tool_action_payload_repetition_rate": 0.0,
                "tool_action_payload_repeated_group_count": 0,
                "tool_action_payload_max_repeat_count": 0,
                "tool_action_payload_repeated_tool_counts": {},
                "tool_observation_source_counts": {
                    "tool:retrieval.run": 1,
                    "tool:workspace.search": 1,
                },
                "tool_observation_count": 2,
                "tool_observation_diagnostics_count": 1,
                "tool_observation_repair_guidance_count": 0,
                "tool_observation_diagnostic_issue_code_counts": {"network_failed": 1},
                "post_final_record_count": 2,
                "post_final_record_kind_counts": {"memory_proposal": 1, "processor_result": 1},
                "finance_verify_numeric_tool_call_count": 0,
                "finance_verify_numeric_tool_error_count": 0,
                "processor_prompt_cache_hit_tokens": 10,
                "processor_prompt_cache_miss_tokens": 40,
                "context_record_count": 1,
                "context_dynamic_state_present_count": 0,
                "context_toolchain_state_present_count": 0,
                "context_toolchain_state_empty_count": 1,
                "context_finance_working_state_present_count": 0,
                "context_finance_working_state_empty_count": 1,
                "processor_usage_by_task_type": {
                    "task.compile": {
                        "call_count": 1,
                        "prompt_cache_hit_tokens": 10,
                        "prompt_cache_miss_tokens": 10,
                        "total_tokens": 80,
                    },
                    "finance.slot_bind": {
                        "call_count": 1,
                        "prompt_cache_hit_tokens": 0,
                        "prompt_cache_miss_tokens": 30,
                        "total_tokens": 70,
                    },
                },
                "processor_error_counts": {"json_invalid": 1},
                "finance_slot_bind_repair_attempt_count": 1,
                "finance_slot_bind_repair_success_count": 0,
                "structured_repair_attempt_count": 1,
                "structured_repair_success_count": 0,
                "formula_trace_support_count": 1,
                "formula_trace_fact_linked_count": 0,
                "formula_trace_citation_linked_count": 0,
                "formula_trace_evidence_linked_count": 0,
            },
            trace_refs=[],
            final_answer=None,
            failure_report=None,
        ),
    ]

    summary = summarize_finance_benchmark(results)

    assert summary.claim_ledger_present_rate == 0.5
    assert summary.slot_frame_present_rate == 0.5
    assert summary.average_missing_slots == 0.5
    assert summary.transform_plan_present_rate == 0.5
    assert summary.average_transform_plans == 1.0
    assert summary.verifier_gate_pass_rate == 0.5
    assert summary.synthesis_gate_pass_rate == 0.5
    assert summary.synthesis_gate_repair_rate == 1.0
    assert summary.average_agent_loop_stage_coverage_rate == 0.8125
    assert summary.agent_loop_terminal_rate == 1.0
    assert summary.agent_loop_tool_stage_rate == 1.0
    assert summary.agent_loop_search_stage_rate == 0.5
    assert summary.agent_loop_verify_stage_rate == 0.5
    assert summary.average_agent_loop_delta_count == 10.0
    assert summary.average_agent_loop_transition_count == 6.5
    assert summary.agent_loop_stage_counts["Plan"] == 4
    assert summary.agent_loop_stage_counts["Verify"] == 2
    assert summary.average_toolchain_depth == 2.0
    assert summary.retrieval_calculator_verifier_chain_rate == 0.5
    assert summary.average_tool_observation_error_rate == 0.25
    assert summary.average_tool_action_repetition_rate == 0.125
    assert summary.average_tool_action_payload_repetition_rate == 0.1
    assert summary.tool_action_payload_repeated_group_count == 1
    assert summary.max_tool_action_payload_repeat_count == 2
    assert summary.tool_action_payload_repeated_tool_counts == {"calculator.compute": 1}
    assert summary.post_final_clean_rate == 0.5
    assert summary.average_post_final_record_count == 1.0
    assert summary.tool_observation_source_counts["tool:retrieval.run"] == 2
    assert summary.tool_observation_source_counts["tool:calculator.compute"] == 2
    assert summary.tool_observation_source_counts["tool:finance.verify_numeric"] == 2
    assert summary.tool_observation_diagnostics_count == 3
    assert summary.tool_observation_repair_guidance_count == 1
    assert summary.tool_observation_diagnostics_rate == 0.4286
    assert summary.tool_observation_repair_guidance_rate == 0.1429
    assert summary.tool_observation_diagnostic_issue_code_counts == {
        "unsupported_answer_number": 1,
        "network_failed": 1,
    }
    assert summary.post_final_record_kind_counts == {"memory_proposal": 1, "processor_result": 1}
    assert summary.finance_verify_numeric_tool_call_count == 2
    assert summary.finance_verify_numeric_tool_error_count == 1
    assert summary.finance_verify_numeric_tool_used_rate == 0.5
    assert summary.finance_verify_numeric_tool_error_rate == 0.5
    assert summary.unsupported_numeric_claim_rate == 0.5
    assert summary.citation_preservation_rate == 0.5
    assert summary.processor_prompt_cache_hit_tokens == 50
    assert summary.processor_prompt_cache_miss_tokens == 50
    assert summary.processor_prompt_cache_hit_ratio == 0.5
    assert summary.context_record_count == 3
    assert summary.average_context_record_count == 1.5
    assert summary.context_dynamic_state_present_count == 1
    assert summary.context_dynamic_state_present_rate == 0.3333
    assert summary.context_dynamic_state_item_rate == 0.5
    assert summary.context_toolchain_state_present_count == 1
    assert summary.context_toolchain_state_empty_count == 2
    assert summary.context_toolchain_state_prompt_eligible_rate == 0.3333
    assert summary.context_toolchain_observation_diagnostics_present_count == 1
    assert summary.context_toolchain_observation_diagnostics_prompt_eligible_rate == 0.3333
    assert summary.context_finance_working_state_present_count == 1
    assert summary.context_finance_working_state_empty_count == 2
    assert summary.context_finance_working_state_prompt_eligible_rate == 0.3333
    assert summary.processor_task_type_counts == {"task.compile": 2, "finance.slot_bind": 1}
    assert summary.processor_cache_by_task_type["task.compile"]["prompt_cache_hit_tokens"] == 50
    assert summary.processor_cache_by_task_type["task.compile"]["prompt_cache_miss_tokens"] == 20
    assert summary.processor_cache_by_task_type["finance.slot_bind"]["prompt_cache_hit_ratio"] == 0.0
    assert summary.processor_error_counts == {"json_invalid": 1}
    assert summary.task_compile_retry_count == 1
    assert summary.task_compile_retry_success_count == 1
    assert summary.finance_slot_bind_repair_attempt_count == 1
    assert summary.finance_slot_bind_repair_success_count == 0
    assert summary.synthesizer_json_repair_attempt_count == 1
    assert summary.synthesizer_json_repair_success_count == 1
    assert summary.structured_repair_attempt_count == 3
    assert summary.structured_repair_success_count == 2
    assert summary.structured_repair_success_rate == 0.6667
    assert summary.average_formula_trace_support_count == 1.5
    assert summary.formula_trace_fact_link_rate == 0.6667
    assert summary.formula_trace_citation_link_rate == 0.3333
    assert summary.formula_trace_evidence_link_rate == 0.6667


def test_finance_benchmark_summary_flags_strict_failures_with_internal_verifier_support() -> None:
    results = [
        FinanceBenchmarkResult(
            item_id="Q-supported-fail",
            status="failed",
            question="What was the supported metric?",
            answer="The supported metric was $1,577 million.",
            task_id="task-1",
            run_id="run-1",
            thread_id="thread-1",
            scorecard={
                "status": "failed",
                "scored": True,
                "answer_present": True,
                "reason": "numeric_outside_tolerance",
            },
            trace_metrics={
                "numeric_verifier_status": "passed",
                "verifier_gate_status": "passed",
            },
            trace_refs=[],
            final_answer=None,
            failure_report=None,
        ),
        FinanceBenchmarkResult(
            item_id="Q-real-fail",
            status="failed",
            question="What was the unsupported metric?",
            answer="The metric was unsupported.",
            task_id="task-2",
            run_id="run-2",
            thread_id="thread-2",
            scorecard={
                "status": "failed",
                "scored": True,
                "answer_present": True,
                "reason": "numeric_outside_tolerance",
            },
            trace_metrics={
                "numeric_verifier_status": "failed",
                "verifier_gate_status": "failed",
            },
            trace_refs=[],
            final_answer=None,
            failure_report=None,
        ),
        FinanceBenchmarkResult(
            item_id="Q-pass",
            status="passed",
            question="What passed?",
            answer="A supported answer.",
            task_id="task-3",
            run_id="run-3",
            thread_id="thread-3",
            scorecard={
                "status": "passed",
                "scored": True,
                "answer_present": True,
                "reason": "numeric_within_tolerance",
            },
            trace_metrics={"numeric_verifier_status": "passed"},
            trace_refs=[],
            final_answer=None,
            failure_report=None,
        ),
    ]

    summary = summarize_finance_benchmark(results)

    assert summary.failed_count == 2
    assert summary.strict_failed_internal_verifier_passed_count == 1
    assert summary.strict_failed_internal_verifier_passed_rate == 0.5
    assert summary.failure_layer_counts == {
        "numeric_verifier": 1,
        "scoring_alignment_review": 1,
    }


def test_finance_benchmark_progress_prints_processor_breakdown(capsys) -> None:
    callback = cli._finance_benchmark_progress_callback(output_path=None, total=1)
    assert callback is not None
    item = FinanceBenchmarkItem(item_id="Q-proc", question="How strong is processor observability?")
    result = FinanceBenchmarkResult(
        item_id="Q-proc",
        status="failed",
        question=item.question,
        answer="",
        task_id="task-proc",
        run_id="run-proc",
        thread_id="thread-proc",
        scorecard={"reason": "json_invalid"},
        trace_metrics={
            "total_tokens": 180,
            "processor_duration_ms": 300,
            "processor_prompt_cache_hit_tokens": 120,
            "processor_prompt_cache_miss_tokens": 60,
            "processor_prompt_cache_hit_ratio": 0.666667,
            "processor_usage_by_task_type": {
                "task.compile": {"call_count": 1},
                "finance.slot_bind": {"call_count": 1},
            },
            "processor_error_counts": {"json_invalid": 1},
            "structured_repair_attempt_count": 2,
            "structured_repair_success_count": 1,
            "structured_repair_success_rate": 0.5,
            "synthesizer_json_repair_attempt_count": 1,
            "synthesizer_json_repair_success_count": 1,
            "formula_trace_fact_link_rate": 1.0,
            "formula_trace_citation_link_rate": 0.5,
        },
        trace_refs=[],
        final_answer=None,
        failure_report=None,
    )

    callback(0, item, result)

    stderr = capsys.readouterr().err
    assert "proc_cache=66.7%" in stderr
    assert "proc_hit=120" in stderr
    assert "proc_miss=60" in stderr
    assert "repair=50.0%" in stderr
    assert "repair_n=1/2" in stderr
    assert "json_repair=1/1" in stderr
    assert "trace_link=100.0%" in stderr
    assert "trace_cite=50.0%" in stderr
    assert "proc_tasks=finance.slot_bind:1,task.compile:1" in stderr
    assert "proc_errors=json_invalid:1" in stderr


def test_finance_benchmark_start_callback_prints_thread(capsys) -> None:
    callback = cli._finance_benchmark_start_callback(enabled=True, total=2)
    assert callback is not None
    item = FinanceBenchmarkItem(
        item_id="Q-start",
        question="What was revenue?",
        category="fact_extraction",
        workflow_type="direct_line_item_or_disclosure_extraction",
    )

    callback(1, item, "finance-bench-0001-q-start")

    stderr = capsys.readouterr().err
    assert "[bench-start] 1/2 item=Q-start" in stderr
    assert "thread=finance-bench-0001-q-start" in stderr
    assert "category=fact_extraction" in stderr
    assert "workflow=direct_line_item_or_disclosure_extraction" in stderr


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


def test_finance_benchmark_cli_imports_financebench_mode(tmp_path: Path) -> None:
    source = tmp_path / "financebench.jsonl"
    output = tmp_path / "financebench.normalized.jsonl"
    manifest = tmp_path / "financebench.manifest.json"
    annotation = tmp_path / "financebench.gold.jsonl"
    source.write_text(
        json.dumps(
            {
                "financebench_id": "fb-cli-001",
                "company": "ExampleCo",
                "question": "What was revenue?",
                "answer": "$10 million",
                "evidence": "Evidence text should not be prompted in doc retrieval mode.",
                "doc_link": "https://example.com/filing.pdf",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    code = cli.main(
        [
            "bench",
            "finance-import",
            "--benchmark",
            "financebench",
            "--mode",
            "doc_retrieval",
            "--input",
            str(source),
            "--output",
            str(output),
            "--manifest-output",
            str(manifest),
            "--annotation-output",
            str(annotation),
        ]
    )

    assert code == 0
    items = load_finance_benchmark_items(output)
    assert items[0].item_id == "fb-cli-001"
    assert items[0].metadata["import_mode"] == "doc_retrieval"
    manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_payload["benchmark"] == "financebench"
    assert manifest_payload["prompt_policy"]["import_mode"] == "doc_retrieval"
    annotation_payload = json.loads(annotation.read_text(encoding="utf-8").strip())
    assert annotation_payload["item_id"] == "fb-cli-001"
    assert annotation_payload["expected_numeric"][0]["value"] == 10_000_000


def test_finance_benchmark_cli_scores_named_test100_split(tmp_path: Path) -> None:
    dataset = tmp_path / "financebench_doc_retrieval.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    output = tmp_path / "results.jsonl"
    summary_path = tmp_path / "summary.json"
    dataset.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"fb-{index:03d}",
                    "question": f"What was metric {index}?",
                    "answer": f"{index}",
                    "numeric_value": index,
                    "tolerance": 0.0,
                }
            )
            for index in range(150)
        )
        + "\n",
        encoding="utf-8",
    )
    predictions.write_text(
        "\n".join(
            json.dumps(
                {
                    "id": f"fb-{index:03d}",
                    "answer": f"{index}",
                    "final_answer": {"citation_refs": [f"cite-{index}"]},
                }
            )
            for index in range(150)
        )
        + "\n",
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
            "--split",
            "test100",
            "--output",
            str(output),
            "--summary-output",
            str(summary_path),
        ]
    )

    assert code == 0
    result_records = _records(output)
    summary_payload = json.loads(summary_path.read_text(encoding="utf-8"))
    assert len(result_records) == 100
    assert result_records[0]["item_id"] == "fb-050"
    assert result_records[-1]["item_id"] == "fb-149"
    assert result_records[0]["metadata"]["benchmark_split"]["split_id"] == "financebench_test100"
    assert summary_payload["benchmark_split"]["split_id"] == "financebench_test100"
    assert summary_payload["benchmark_split"]["offset"] == 50
    assert summary_payload["benchmark_split"]["limit"] == 100
    assert summary_payload["item_count"] == 100


def test_finance_benchmark_cli_rejects_split_with_manual_offset_or_limit(tmp_path: Path) -> None:
    dataset = tmp_path / "financebench_doc_retrieval.jsonl"
    predictions = tmp_path / "predictions.jsonl"
    dataset.write_text(json.dumps({"id": "fb-000", "question": "Question?", "answer": "1"}) + "\n", encoding="utf-8")
    predictions.write_text(json.dumps({"id": "fb-000", "answer": "1"}) + "\n", encoding="utf-8")

    code = cli.main(
        [
            "bench",
            "finance",
            "--dataset",
            str(dataset),
            "--predictions",
            str(predictions),
            "--split",
            "debug50",
            "--limit",
            "1",
        ]
    )

    assert code == 1


def test_financebench_annotation_export_preserves_required_source_urls(tmp_path: Path) -> None:
    dataset = tmp_path / "financebench.normalized.jsonl"
    annotation = tmp_path / "financebench.gold.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "item_id": "financebench_id_source_url",
                "question": "What changed in operating margin?",
                "gold_answer": "1.7%",
                "metadata": {
                    "source_refs": [
                        {
                            "doc_type": "10-K",
                            "url": (
                                "https://investors.3m.com/financials/sec-filings/content/"
                                "0000066740-23-000014/0000066740-23-000014.pdf"
                            ),
                        }
                    ]
                },
                "evidence_policy": {"required_source_families": ["sec_filings"]},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    write_finance_dev_annotations_from_dataset(dataset_path=dataset, annotation_path=annotation)

    payload = json.loads(annotation.read_text(encoding="utf-8").strip())
    assert payload["required_sources"] == ["10-k", "investors.3m.com", "sec_filings"]
    assert payload["required_source_urls"] == [
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/0000066740-23-000014.pdf"
    ]


def test_financebench_source_url_scoring_accepts_same_sec_accession_not_companyfacts(tmp_path: Path) -> None:
    annotation = tmp_path / "financebench.gold.jsonl"
    required_url = (
        "https://investors.3m.com/financials/sec-filings/content/"
        "0000066740-23-000014/0000066740-23-000014.pdf"
    )
    annotation.write_text(
        json.dumps(
            {
                "item_id": "financebench_id_01226",
                "required_sources": ["investors.3m.com"],
                "required_source_urls": [required_url],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    base_kwargs = {
        "item_id": "financebench_id_01226",
        "status": "passed",
        "question": "What drove the operating margin change?",
        "answer": "Operating income margin changed by 1.7 percentage points.",
        "task_id": "task-1",
        "run_id": "run-1",
        "thread_id": "thread-1",
        "scorecard": {"citation_present": True},
        "trace_refs": [],
        "final_answer": {"citation_refs": ["cite-filing"]},
        "failure_report": None,
        "metadata": {},
    }
    filing_result = FinanceBenchmarkResult(
        **base_kwargs,
        trace_metrics={
            "source_hosts": ["www.sec.gov"],
            "source_uris": [
                "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt"
            ],
            "target_document_source_urls": [required_url],
        },
    )
    filing_score = score_finance_dev_annotations([filing_result], annotation_path=annotation)

    assert filing_score["failure_reason_counts"] == {}
    assert filing_score["items"][0]["required_source_hit_count"] == 1
    assert filing_score["items"][0]["required_source_url_hit_count"] == 1

    companyfacts_result = FinanceBenchmarkResult(
        **base_kwargs,
        trace_metrics={
            "source_hosts": ["data.sec.gov"],
            "source_uris": ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"],
            "target_document_source_urls": [required_url],
        },
    )
    companyfacts_score = score_finance_dev_annotations([companyfacts_result], annotation_path=annotation)

    assert companyfacts_score["failure_reason_counts"] == {
        "required_source_missing": 1,
        "required_source_url_missing": 1,
    }

    bound_companyfacts_result = FinanceBenchmarkResult(
        **base_kwargs,
        trace_metrics={
            "source_hosts": ["data.sec.gov"],
            "source_uris": ["https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json"],
            "target_document_source_urls": [required_url],
            "primary_source_numeric_binding_status": "selected",
            "primary_source_numeric_binding_selected_count": 1,
        },
    )
    bound_companyfacts_score = score_finance_dev_annotations([bound_companyfacts_result], annotation_path=annotation)

    assert bound_companyfacts_score["failure_reason_counts"] == {}
    assert bound_companyfacts_score["items"][0]["required_source_url_hit_count"] == 1


def test_finance_benchmark_fetch_downloads_and_imports_with_annotation(tmp_path: Path) -> None:
    remote = tmp_path / "remote-financebench.jsonl"
    raw = tmp_path / "downloaded-financebench.jsonl"
    normalized = tmp_path / "financebench.normalized.jsonl"
    manifest = tmp_path / "financebench.manifest.json"
    annotation = tmp_path / "financebench.gold.jsonl"
    remote.write_text(
        json.dumps(
            {
                "financebench_id": "fb-fetch-001",
                "company": "ExampleCo",
                "question": "What was revenue?",
                "answer": "$10 million",
                "evidence": "Revenue was $10 million in the filing.",
                "doc_type": "10-K",
                "doc_link": "https://www.sec.gov/exampleco-10k.htm",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    fetch_summary = fetch_public_finance_benchmark(
        benchmark="financebench",
        source_url=remote.as_uri(),
        output_path=raw,
    )

    assert fetch_summary.status == "ok"
    assert raw.read_text(encoding="utf-8") == remote.read_text(encoding="utf-8")

    code = cli.main(
        [
            "bench",
            "finance-fetch",
            "--benchmark",
            "financebench",
            "--url",
            remote.as_uri(),
            "--output",
            str(raw),
            "--normalized-output",
            str(normalized),
            "--manifest-output",
            str(manifest),
            "--annotation-output",
            str(annotation),
            "--mode",
            "oracle_evidence",
        ]
    )

    assert code == 0
    items = load_finance_benchmark_items(normalized)
    assert items[0].item_id == "fb-fetch-001"
    assert items[0].metadata["import_mode"] == "oracle_evidence"
    assert json.loads(manifest.read_text(encoding="utf-8"))["prompt_policy"]["import_mode"] == "oracle_evidence"
    annotation_payload = json.loads(annotation.read_text(encoding="utf-8").strip())
    assert annotation_payload["item_id"] == "fb-fetch-001"
    assert annotation_payload["expected_numeric"][0]["value"] == 10_000_000


def test_finance_benchmark_fetch_cleans_partial_file_on_budget_block(tmp_path: Path) -> None:
    remote = tmp_path / "remote-large.jsonl"
    output = tmp_path / "blocked.jsonl"
    remote.write_text("x" * 128, encoding="utf-8")

    try:
        fetch_public_finance_benchmark(
            benchmark="financebench",
            source_url=remote.as_uri(),
            output_path=output,
            max_bytes=8,
        )
    except ValueError as exc:
        assert "max_bytes" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("expected max_bytes guard to fail")

    assert not output.exists()
    assert not output.with_name(output.name + ".part").exists()


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


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
