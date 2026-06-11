from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.json_repair import parse_json_object
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.workbench import retrieval_workbench_packet, validate_workbench_output


def test_retrieval_operator_journals_model_workbench_decision() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench",
        query="Find ExampleCo FY2024 revenue from the annual report",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=3,
        metadata={
            "workflow_type": "filing_document_qa",
            "required_slots": ["revenue", "period", "source"],
        },
    )
    source = SearchSource(
        source_id="source-annual-report",
        provider="fake",
        uri="https://example.com/exampleco-2024-annual-report",
        title="ExampleCo 2024 Annual Report",
        snippet="Annual report with revenue.",
        metadata={"source_kind": "annual_report", "source_family": "company_ir", "authority_level": "primary"},
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "continue",
                "reason_summary": "Revenue evidence exists, but operating income remains missing.",
                "accepted_evidence_ids": ["evidence-span-doc-goal-workbench-1-1"],
                "rescued_evidence_ids": [],
                "rejected_evidence_ids": [],
                "source_roles": [
                    {
                        "source_id": "source-annual-report",
                        "role": "annual_report",
                        "confidence": 0.91,
                        "reason": "Primary annual report source.",
                    }
                ],
                "slot_assessments": [
                    {
                        "slot": "revenue",
                        "status": "filled",
                        "supporting_evidence_ids": ["evidence-span-doc-goal-workbench-1-1"],
                        "reason": "The span states FY2024 revenue.",
                    },
                    {
                        "slot": "operating_income",
                        "status": "missing",
                        "supporting_evidence_ids": [],
                        "reason": "No operating income span is present.",
                    },
                ],
                "covered_slots": ["revenue"],
                "missing_slots": ["operating_income"],
                "assumptions_needed": [],
                "next_queries": ["ExampleCo FY2024 operating income annual report"],
                "next_source_families": ["company_ir"],
                "next_document_targets": ["FY2024 annual report income statement"],
                "limitations": ["Only one revenue span was extracted."],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "ExampleCo FY2024 revenue was $10 million in the annual report."}),
        processor_fabric=fabric,
    )

    report = operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench",
        run_id="run-workbench",
    )

    workbench_records = journal.records(task_id="task-workbench", kind="retrieval_workbench_decision")
    assert len(workbench_records) == 1
    workbench = workbench_records[0].data
    assert workbench["decision"] == "continue"
    assert workbench["missing_slots"] == ["operating_income"]
    assert workbench["source_roles"][0]["role"] == "annual_report"
    assert report.diagnostics["retrieval_workbench"]["next_queries"] == ["ExampleCo FY2024 operating income annual report"]
    processor_requests = journal.records(task_id="task-workbench", kind="processor_request")
    assert any(record.data["task_type"] == "retrieval.workbench" for record in processor_requests)


def test_retrieval_workbench_host_validation_drops_invented_ids() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench-invalid",
        query="Find ExampleCo FY2024 revenue",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=3,
    )
    source = SearchSource(
        source_id="source-example",
        provider="fake",
        uri="https://example.com/report",
        title="ExampleCo Report",
        snippet="Revenue.",
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "sufficient",
                "reason_summary": "The model tried to cite invented IDs.",
                "accepted_evidence_ids": ["invented-evidence"],
                "rescued_evidence_ids": ["invented-rescue"],
                "rejected_evidence_ids": [],
                "source_roles": [{"source_id": "invented-source", "role": "annual_report", "confidence": 0.9, "reason": "bad"}],
                "slot_assessments": [],
                "covered_slots": [],
                "missing_slots": [],
                "assumptions_needed": [],
                "next_queries": [],
                "next_source_families": [],
                "next_document_targets": [],
                "limitations": [],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "ExampleCo FY2024 revenue was $10 million."}),
        processor_fabric=fabric,
    )

    operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench-invalid",
        run_id="run-workbench-invalid",
    )

    workbench = journal.records(task_id="task-workbench-invalid", kind="retrieval_workbench_decision")[0].data
    assert workbench["accepted_evidence_ids"] == []
    assert workbench["rescued_evidence_ids"] == []
    assert workbench["source_roles"] == []
    assert workbench["diagnostics"]["host_validation"]["valid"] is False
    assert workbench["diagnostics"]["host_validation"]["invalid_references"]["evidence_ids"] == [
        "invented-evidence",
        "invented-rescue",
    ]


def test_retrieval_workbench_rescues_citable_evidence_from_threshold_rejection() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench-rescue",
        query="ExampleCo revenue",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=4,
        metadata={"max_evidence_items": 1},
    )
    source = SearchSource(
        source_id="source-example-rescue",
        provider="fake",
        uri="https://example.com/report-rescue",
        title="ExampleCo Report",
        snippet="Revenue.",
    )
    rescued_id = "evidence-span-doc-goal-workbench-rescue-1-2"
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "sufficient",
                "reason_summary": "The compacted-out second revenue span is relevant and should be cited.",
                "accepted_evidence_ids": [rescued_id],
                "rescued_evidence_ids": [rescued_id],
                "rejected_evidence_ids": [],
                "source_roles": [
                    {
                        "source_id": "source-example-rescue",
                        "role": "annual_report",
                        "confidence": 0.8,
                        "reason": "Citable company report.",
                    }
                ],
                "slot_assessments": [
                    {
                        "slot": "revenue",
                        "status": "filled",
                        "supporting_evidence_ids": [rescued_id],
                        "reason": "The span states a revenue figure.",
                    }
                ],
                "covered_slots": ["revenue"],
                "missing_slots": [],
                "assumptions_needed": [],
                "next_queries": [],
                "next_source_families": [],
                "next_document_targets": [],
                "limitations": [],
            }
        },
        journal=journal,
    )
    body = (
        "ExampleCo revenue was $10 million in FY2023. " + ("padding " * 40)
        + "ExampleCo revenue was $12 million in FY2024. " + ("padding " * 40)
        + "ExampleCo revenue guidance was not audited."
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: body}),
        processor_fabric=fabric,
    )

    report = operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench-rescue",
        run_id="run-workbench-rescue",
    )

    evidence = journal.records(task_id="task-workbench-rescue", kind="retrieval_evidence")
    citations = journal.records(task_id="task-workbench-rescue", kind="retrieval_citation")
    rescue = journal.records(task_id="task-workbench-rescue", kind="retrieval_workbench_rescue")[0].data
    assert report.diagnostics["workbench_rescue"]["rescued_count"] == 1
    assert rescue["rescued"][0]["evidence_id"] == rescued_id
    assert any(record.data["evidence_id"] == rescued_id for record in evidence)
    assert any(record.data["evidence_id"] == rescued_id for record in citations)
    assert report.diagnostics["citation_count"] == 2


def test_retrieval_workbench_next_query_becomes_tool_action_when_evidence_missing() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench-next-query",
        query="ExampleCo operating income",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=2,
    )
    source = SearchSource(
        source_id="source-example-next-query",
        provider="fake",
        uri="https://example.com/irrelevant",
        title="ExampleCo Empty Page",
        snippet="No useful evidence.",
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "continue",
                "reason_summary": "No operating income evidence was extracted; target the income statement.",
                "accepted_evidence_ids": [],
                "rescued_evidence_ids": [],
                "rejected_evidence_ids": [],
                "source_roles": [
                    {
                        "source_id": "source-example-next-query",
                        "role": "irrelevant",
                        "confidence": 0.9,
                        "reason": "The fetched page did not include the requested metric.",
                    }
                ],
                "slot_assessments": [
                    {
                        "slot": "operating_income",
                        "status": "missing",
                        "supporting_evidence_ids": [],
                        "reason": "No span was extracted.",
                    }
                ],
                "covered_slots": [],
                "missing_slots": ["operating_income"],
                "assumptions_needed": [],
                "next_queries": ["ExampleCo FY2024 operating income income statement annual report"],
                "next_source_families": ["company_ir"],
                "next_document_targets": ["annual report income statement"],
                "limitations": [],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "This page only says hello."}),
        processor_fabric=fabric,
    )

    report = operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench-next-query",
        run_id="run-workbench-next-query",
    )

    actions = report.diagnostics["next_tool_actions"]
    assert any(action["action"] == "model_guided_query" for action in actions)
    model_action = next(action for action in actions if action["action"] == "model_guided_query")
    assert model_action["payload_hint"]["query"] == "ExampleCo FY2024 operating income income statement annual report"
    assert model_action["payload_hint"]["missing_slots"] == ["operating_income"]


def test_retrieval_workbench_direct_document_target_becomes_tool_action() -> None:
    journal = JournalStore.in_memory()
    goal = SearchGoal(
        goal_id="goal-workbench-target",
        query="ExampleCo capital expenditure",
        max_sources=3,
        max_fetches=1,
        max_spans_per_document=2,
    )
    source = SearchSource(
        source_id="source-example-target",
        provider="fake",
        uri="https://example.com/search",
        title="ExampleCo Search Page",
        snippet="No useful evidence.",
    )
    fabric = fake_fabric(
        {
            "retrieval.workbench": {
                "decision": "continue",
                "reason_summary": "Fetch the exact filing document next.",
                "accepted_evidence_ids": [],
                "rescued_evidence_ids": [],
                "rejected_evidence_ids": [],
                "source_roles": [],
                "slot_assessments": [],
                "covered_slots": [],
                "missing_slots": ["capital_expenditure"],
                "assumptions_needed": [],
                "next_queries": [],
                "next_source_families": ["company_ir"],
                "next_document_targets": ["https://example.com/exampleco-2024-10k.htm"],
                "limitations": [],
            }
        },
        journal=journal,
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({goal.query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: "This page only says hello."}),
        processor_fabric=fabric,
    )

    report = operator.run(
        goal,
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-workbench-target",
        run_id="run-workbench-target",
    )

    action = next(item for item in report.diagnostics["next_tool_actions"] if item["action"] == "model_guided_document_target")
    assert action["payload_hint"]["query"] == "https://example.com/exampleco-2024-10k.htm"
    assert action["payload_hint"]["prefer_direct_url"] is True
    assert action["payload_hint"]["missing_slots"] == ["capital_expenditure"]


def test_retrieval_workbench_accepts_live_alias_output_shape() -> None:
    goal = SearchGoal(
        goal_id="goal-workbench-alias",
        query="3M FY2018 capital expenditure",
        metadata={"required_slots": ["capital_expenditure"]},
    )
    source = SearchSource(
        source_id="direct-url-source",
        provider="direct_url_search",
        uri="https://investors.3m.com/report.pdf",
        title="3M 2018 10-K PDF",
        snippet="Target filing.",
    )
    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[source],
        fetch_summaries=[],
        documents=[],
        spans=[],
        evidence=[],
        citations=[],
        rejected_evidence=[],
    )

    decision = validate_workbench_output(
        {
            "evidence_sufficiency": "insufficient",
            "filled_slots": [],
            "missing_slots": ["capital_expenditure_fy2018"],
            "key_source_roles": {"direct-url-source": "primary_target_document"},
            "next_acquisition_moves": [
                {
                    "action": "fetch_direct_url",
                    "target": "https://investors.3m.com/report.pdf",
                    "source_family": "company_filing",
                }
            ],
        },
        packet=packet,
    )

    assert decision.status == "ok"
    assert decision.decision == "continue"
    assert decision.missing_slots == ["capital_expenditure_fy2018"]
    assert decision.source_roles[0]["role"] == "primary_filing"
    assert decision.next_queries == ["https://investors.3m.com/report.pdf"]
    assert decision.next_document_targets == ["https://investors.3m.com/report.pdf"]


def test_retrieval_workbench_normalizes_object_query_items() -> None:
    goal = SearchGoal(goal_id="goal-workbench-object-query", query="3M FY2018 capital expenditure")
    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[],
        fetch_summaries=[],
        documents=[],
        spans=[],
        evidence=[],
        citations=[],
        rejected_evidence=[],
    )

    decision = validate_workbench_output(
        {
            "decision": "continue",
            "reason_summary": "Need cash flow statement evidence.",
            "next_queries": [
                {
                    "query": "3M 2018 10-K capital expenditures cash flow statement",
                    "source_family": "company_ir",
                }
            ],
            "next_source_families": [{"source_family": "company_ir"}],
            "next_document_targets": [{"url": "https://www.sec.gov/Archives/example/mmm-20181231x10k.htm"}],
        },
        packet=packet,
    )

    assert decision.next_queries == ["3M 2018 10-K capital expenditures cash flow statement"]
    assert decision.next_source_families == ["company_ir"]
    assert decision.next_document_targets == ["https://www.sec.gov/Archives/example/mmm-20181231x10k.htm"]


def test_json_repair_accepts_python_literal_object() -> None:
    result = parse_json_object(
        "{'decision': 'continue', 'next_queries': [{'query': '3M capex'}],}",
        max_repair_attempts=1,
    )

    assert result.value == {"decision": "continue", "next_queries": [{"query": "3M capex"}]}
    assert result.repaired is True


def test_pdf_document_reader_diagnostics_are_exposed_on_spans() -> None:
    goal = SearchGoal(
        goal_id="goal-pdf-reader",
        query="capital expenditures 1577",
        max_spans_per_document=2,
    )
    document = FetchedDocument(
        document_id="doc-pdf-reader",
        goal_id=goal.goal_id,
        source_id="source-pdf-reader",
        uri="https://example.com/report.pdf",
        title="ExampleCo PDF Report",
        artifact_id="artifact-pdf-reader",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "application/pdf"},
    )
    body = "%PDF-1.4\n1 0 obj <<>> stream\n(Capital expenditures were 1577 in FY2018.) Tj\nendstream\n%%EOF"

    spans = extract_spans(goal=goal, document=document, body=body)

    assert spans
    reader = spans[0].metadata["document_reader"]
    assert reader["parser_used"] in {"pdf_text_literals", "pdf_text_pypdf", "pdf_text_pdfminer"}
    assert reader["chars_extracted"] > 0
