import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.processors.json_repair import parse_json_object
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.extract import extract_spans
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, ExtractedSpan, FetchedDocument
from kernel_v3.retrieval.http_provider import HttpFetchProvider, HttpTransportResponse
from kernel_v3.retrieval.workbench import _workbench_prompt, retrieval_workbench_packet, validate_workbench_output


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


def test_retrieval_workbench_packet_exposes_target_document_binding() -> None:
    binding = {
        "company": "3M",
        "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
        "doc_period": "2018",
        "required_statement": "cash_flow_statement",
        "required_line_item": "capital expenditures",
        "primary_source_required": True,
    }
    goal = SearchGoal(
        goal_id="goal-workbench-binding",
        query="3M FY2018 capital expenditures",
        metadata={
            "target_document_binding": binding,
            "required_statement": "cash_flow_statement",
            "required_line_item": "capital expenditures",
        },
    )
    source = SearchSource(
        source_id="source-target-doc",
        provider="direct_url_search",
        uri=binding["doc_link"],
        title="3M 2018 10-K",
        snippet="Target filing.",
        metadata={"source_kind": "sec_primary_filing_document"},
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

    assert packet["target_document_binding"]["doc_period"] == "2018"
    assert packet["target_document_binding"]["required_line_item"] == "capital expenditures"
    assert packet["required_statement"] == "cash_flow_statement"
    assert packet["required_line_item"] == "capital expenditures"


def test_retrieval_workbench_packet_exposes_compiled_task_hint_for_llm_judgment() -> None:
    goal = SearchGoal(
        goal_id="goal-workbench-compiled-hint",
        query="3M FY2018 capital expenditures",
        metadata={
            "compiled_task_hint": {
                "schema": "holo.kernel_v3.compiled_task_hint.v1",
                "domain": "finance",
                "task_spec": {
                    "task_type": "compute",
                    "target_entities": ["3M"],
                    "target_periods": ["2018"],
                    "success_criteria": ["final answer must pass verifier gate"],
                    "objective": "drop this long raw objective from packet",
                },
                "evidence_specs": [
                    {
                        "slot_name": "capital_expenditures",
                        "accepted_attributes": ["capital expenditures", "purchases of property plant and equipment"],
                        "source_role": "primary_filing",
                        "required_source_families": ["sec_filings", "company_filing"],
                        "target_period": "2018",
                        "statement": "cash_flow_statement",
                        "line_item": "capital expenditures",
                        "required": True,
                        "diagnostics": {"large": "not needed"},
                    }
                ],
                "transform_specs": [
                    {
                        "name": "capital_intensity_capex_revenue",
                        "required_slots": ["capital_expenditures", "revenue"],
                        "expression": "capital_expenditures / revenue",
                        "output_unit": "percent",
                        "output_attribute": "capex_to_revenue",
                    }
                ],
                "missing_slots": ["capital_expenditures", "revenue"],
                "tool_chain_plan": {
                    "schema": "holo.kernel_v3.tool_chain_plan.v1",
                    "decision_owner": "model",
                    "host_role": "verify_provenance_policy_budget_and_numeric_support",
                    "task_type": "compute",
                    "formula_status": "missing_facts",
                    "formula_name": "capital_intensity",
                    "missing_slots": ["capital_expenditures", "revenue"],
                    "available_tools": [
                        {"name": "retrieval.run", "use_for": "source acquisition"},
                        {"name": "calculator.compute", "use_for": "deterministic transforms"},
                    ],
                    "recommended_steps": [
                        {"step": "acquire_or_read_evidence", "tool": "retrieval.run", "decision_owner": "model"}
                    ],
                    "next_action_candidates": [
                        {"tool": "retrieval.run", "reason": "fill_missing_evidence_slots"}
                    ],
                },
                "diagnostics": {"source": "finance_task_compiler_pre_retrieval", "evidence_spec_count": 1},
            }
        },
    )

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

    hint = packet["compiled_task_hint"]
    assert hint["task_spec"]["task_type"] == "compute"
    assert hint["task_spec"]["target_entities"] == ["3M"]
    assert hint["evidence_specs"][0]["slot_name"] == "capital_expenditures"
    assert hint["evidence_specs"][0]["statement"] == "cash_flow_statement"
    assert hint["transform_specs"][0]["required_slots"] == ["capital_expenditures", "revenue"]
    assert hint["tool_chain_plan"]["decision_owner"] == "model"
    assert hint["tool_chain_plan"]["next_action_candidates"][0]["tool"] == "retrieval.run"
    assert "objective" not in hint["task_spec"]


def test_retrieval_workbench_packet_compacts_but_preserves_target_and_task_relevant_evidence() -> None:
    source_url = (
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf"
    )
    sec_text_url = "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt"
    goal = SearchGoal(
        goal_id="goal-workbench-compact",
        query="What drove operating margin change as of FY2022 for 3M?",
        metadata={
            "benchmark_doc_retrieval": True,
            "workflow_type": "source_grounded_research",
            "source_url": source_url,
            "source_urls": [source_url, sec_text_url],
            "target_document_binding": {"company": "3M", "doc_link": source_url, "doc_period": "2022"},
            "compiled_task_hint": {
                "schema": "holo.kernel_v3.compiled_task_hint.v1",
                "domain": "finance",
                "task_spec": {"task_type": "source_grounded_research", "target_entities": ["3M"], "target_periods": ["2022"]},
                "evidence_specs": [
                    {
                        "slot_name": "operating_margin_driver",
                        "accepted_attributes": ["operating income margin", "cost of sales", "results of operations"],
                        "source_role": "primary_filing",
                        "target_period": "2022",
                    }
                ],
                "transform_specs": [],
            },
        },
    )
    evidence = [
        EvidenceItem(
            evidence_id=f"evidence-noise-{index}",
            goal_id=goal.goal_id,
            span_id=f"span-noise-{index}",
            document_id=f"doc-noise-{index}",
            source_id=f"source-noise-{index}",
            artifact_id=f"artifact-noise-{index}",
            uri=f"https://example.com/noise-{index}",
            title="Unrelated market page",
            text="This page discusses unrelated product news with no filing table.",
            score=0.01,
            payload_hash=f"hash-noise-{index}",
        )
        for index in range(70)
    ]
    evidence.append(
        EvidenceItem(
            evidence_id="evidence-target-mdna",
            goal_id=goal.goal_id,
            span_id="span-target-mdna",
            document_id="doc-target",
            source_id="source-target",
            artifact_id="artifact-target",
            uri=sec_text_url,
            title="3M 2022 10-K complete submission text",
            text=(
                "RESULTS OF OPERATIONS. Operating income margin 19.1% 20.8% (1.7)%. "
                "Cost of sales increased primarily due to litigation and raw materials."
            ),
            score=0.02,
            payload_hash="hash-target-mdna",
        )
    )

    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[],
        fetch_summaries=[],
        documents=[],
        spans=[],
        evidence=evidence,
        citations=[],
        rejected_evidence=[],
    )

    assert packet["selection_diagnostics"]["raw_accepted_evidence_count"] == 71
    assert packet["selection_diagnostics"]["selected_accepted_evidence_count"] == 6
    accepted_ids = {item["evidence_id"] for item in packet["accepted_evidence"]}
    assert "evidence-target-mdna" in accepted_ids
    assert packet["target_document_candidates"][0]["evidence_id"] == "evidence-target-mdna"


def test_retrieval_workbench_packet_stays_compact_on_large_candidate_sets() -> None:
    source_url = "https://investor.activision.com/static-files/32abe798-add2-4770-9c7d-4cd3a840ede2"
    goal = SearchGoal(
        goal_id="goal-workbench-large",
        query="Activision Blizzard FY2019 fixed asset turnover",
        metadata={
            "benchmark_doc_retrieval": True,
            "source_url": source_url,
            "target_document_binding": {"company": "Activision Blizzard", "doc_link": source_url, "doc_period": "2019"},
            "compiled_task_hint": {
                "schema": "holo.kernel_v3.compiled_task_hint.v1",
                "domain": "finance",
                "task_spec": {"task_type": "compute", "target_entities": ["Activision Blizzard"], "target_periods": ["2019", "2018"]},
                "evidence_specs": [
                    {"slot_name": "revenue", "accepted_attributes": ["revenue"], "source_role": "primary_filing", "target_period": "2019"},
                    {
                        "slot_name": "property_plant_and_equipment_net_current",
                        "accepted_attributes": ["property plant and equipment net"],
                        "source_role": "primary_filing",
                        "target_period": "2019",
                    },
                    {
                        "slot_name": "property_plant_and_equipment_net_prior",
                        "accepted_attributes": ["property plant and equipment net"],
                        "source_role": "primary_filing",
                        "target_period": "2018",
                    },
                ],
                "transform_specs": [
                    {
                        "name": "fixed_asset_turnover",
                        "required_slots": [
                            "revenue",
                            "property_plant_and_equipment_net_current",
                            "property_plant_and_equipment_net_prior",
                        ],
                        "expression": "revenue / ((property_plant_and_equipment_net_current + property_plant_and_equipment_net_prior) / 2)",
                    }
                ],
            },
        },
    )
    sources = [
        SearchSource(
            source_id=f"source-{index}",
            provider="fake",
            uri=source_url if index == 0 else f"https://example.com/noise-{index}",
            title="Activision Blizzard 2019 10-K" if index == 0 else "Noise source",
            snippet=("Revenue and property plant and equipment net " * 20) if index == 0 else ("market page " * 80),
        )
        for index in range(80)
    ]
    documents = [
        (
            FetchedDocument(
                document_id=f"doc-{index}",
                goal_id=goal.goal_id,
                source_id=f"source-{index}",
                uri=source_url if index == 0 else f"https://example.com/doc-{index}",
                title="Activision Blizzard 2019 10-K" if index == 0 else "Noise document",
                artifact_id=f"artifact-{index}",
                payload_hash=f"hash-{index}",
                preview="preview",
                size_bytes=1000,
            ),
            ("Consolidated statements of operations revenue 6,489. Consolidated balance sheets property and equipment 272 263. " * 80)
            if index == 0
            else ("unrelated text " * 300),
        )
        for index in range(40)
    ]
    spans = [
        ExtractedSpan(
            span_id=f"span-{index}",
            goal_id=goal.goal_id,
            document_id="doc-0" if index == 0 else f"doc-{index % 40}",
            source_id="source-0" if index == 0 else f"source-{index % 80}",
            text=(
                "Revenue 6,489. Property and equipment, net 272 263. "
                if index == 0
                else "unrelated numeric 1 2 3 " * 20
            ),
            start_offset=0,
            end_offset=100,
            score=0.1,
            metadata={"source_uri": source_url if index == 0 else f"https://example.com/span-{index}"},
        )
        for index in range(160)
    ]
    rejected = [
        {
            "evidence_id": f"evidence-rejected-{index}",
            "source_id": "source-0" if index == 0 else f"source-{index % 80}",
            "document_id": "doc-0" if index == 0 else f"doc-{index % 40}",
            "uri": source_url if index == 0 else f"https://example.com/rejected-{index}",
            "title": "Activision target filing" if index == 0 else "Noise rejected",
            "reason": "missing_finance_fact_in_span",
            "preview": ("Revenue and PP&E row " * 100) if index == 0 else ("noise " * 200),
        }
        for index in range(140)
    ]

    packet = retrieval_workbench_packet(
        goal=goal,
        sources=sources,
        fetch_summaries=[],
        documents=documents,
        spans=spans,
        evidence=[],
        citations=[],
        rejected_evidence=rejected,
    )

    assert packet["selection_diagnostics"]["selected_source_count"] == 10
    assert packet["selection_diagnostics"]["selected_document_count"] == 3
    assert packet["selection_diagnostics"]["selected_span_count"] == 8
    assert packet["selection_diagnostics"]["selected_rejected_evidence_count"] == 6
    assert packet["document_summaries"][0]["is_target_document"] is True
    assert packet["target_document_candidates"][0]["evidence_id"] == "evidence-rejected-0"
    assert len(json.dumps(packet, ensure_ascii=False, sort_keys=True)) < 25_000


def test_retrieval_workbench_prompt_keeps_stable_contract_before_dynamic_packet() -> None:
    goal = SearchGoal(
        goal_id="goal-workbench-cache",
        query="Compare FY2024 DIO for HD and LOW from public filings",
        metadata={
            "workflow_type": "finance_compute",
            "required_slots": ["inventory_begin", "inventory_end", "cogs", "fiscal_days"],
            "compiled_task_hint": {
                "domain": "finance",
                "task_spec": {"task_type": "compare_compute", "target_entities": ["HD", "LOW"], "target_periods": ["FY2024"]},
                "evidence_specs": [
                    {"slot_name": "inventory_begin", "source_role": "primary_filing", "target_period": "FY2024"},
                    {"slot_name": "inventory_end", "source_role": "primary_filing", "target_period": "FY2024"},
                    {"slot_name": "cogs", "source_role": "primary_filing", "target_period": "FY2024"},
                ],
                "transform_specs": [{"name": "days_inventory_outstanding", "required_slots": ["inventory_begin", "inventory_end", "cogs", "fiscal_days"]}],
            },
        },
    )
    evidence = [
        EvidenceItem(
            evidence_id=f"evidence-{index}",
            goal_id=goal.goal_id,
            span_id=f"span-{index}",
            document_id=f"doc-{index}",
            source_id=f"source-{index}",
            artifact_id=f"artifact-{index}",
            uri=f"https://www.sec.gov/example-{index}",
            title="Annual report",
            text="Inventory and cost of sales evidence " * 20,
            score=0.8,
            payload_hash=f"hash-{index}",
            diagnostics={},
        )
        for index in range(10)
    ]
    citations = [
        CitationItem(
            citation_id=f"citation-{index}",
            goal_id=goal.goal_id,
            evidence_id=f"evidence-{index % 10}",
            artifact_id=f"artifact-{index % 10}",
            uri=f"https://www.sec.gov/example-{index % 10}",
            title="Annual report",
            quote="A long citation quote about inventory, cost of sales, fiscal year, and numeric table rows. " * 12,
            span_start=0,
            span_end=100,
        )
        for index in range(40)
    ]

    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[],
        fetch_summaries=[],
        documents=[],
        spans=[],
        evidence=evidence,
        citations=citations,
        rejected_evidence=[],
    )
    prompt = _workbench_prompt(packet)
    payload = json.loads(prompt)

    assert prompt.index('"contract"') < prompt.index('"packet"')
    assert "Finance workbench behavior" in payload["contract"]
    assert len(payload["packet"]["current_citations"]) == 8
    assert all(len(item["quote"]) <= 163 for item in payload["packet"]["current_citations"])
    assert "calculator.compute" in payload["contract"]
    assert len(prompt) < 11_000


def test_retrieval_workbench_packet_exposes_target_document_candidates_for_llm_judgment() -> None:
    source_url = (
        "https://investors.3m.com/financials/sec-filings/content/0000066740-23-000014/"
        "0000066740-23-000014.pdf"
    )
    sec_text_url = "https://www.sec.gov/Archives/edgar/data/66740/000006674023000014/0000066740-23-000014.txt"
    goal = SearchGoal(
        goal_id="goal-workbench-target-candidate",
        query="What drove operating margin change as of FY2022 for 3M?",
        metadata={
            "benchmark_doc_retrieval": True,
            "workflow_type": "source_grounded_research",
            "source_url": source_url,
            "source_urls": [sec_text_url, source_url],
            "target_document_binding": {"company": "3M", "doc_link": source_url, "doc_period": "2022"},
        },
    )
    rejected = [
        {
            "evidence_id": "evidence-span-target-mdna",
            "source_id": "source-target",
            "document_id": "doc-target",
            "uri": sec_text_url,
            "title": "3M 2022 10-K complete submission text",
            "reason": "missing_finance_fact_in_span",
            "preview": "Operating income margin 19.1% 20.8% (1.7)%. Cost of sales increased primarily due to litigation.",
        }
    ]

    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[],
        fetch_summaries=[],
        documents=[
            (
                FetchedDocument(
                    document_id="doc-target",
                    goal_id=goal.goal_id,
                    source_id="source-target",
                    uri=sec_text_url,
                    title="3M 2022 10-K complete submission text",
                    artifact_id="artifact-target",
                    payload_hash="hash-target",
                    preview="Operating income margin...",
                    size_bytes=1000,
                ),
                "Operating income margin 19.1% 20.8% (1.7)%.",
            )
        ],
        spans=[],
        evidence=[],
        citations=[],
        rejected_evidence=rejected,
    )

    assert packet["target_document_contract"]["required_for_final_citation"] is True
    assert sec_text_url in packet["target_document_contract"]["target_urls"]
    assert packet["document_summaries"][0]["is_target_document"] is True
    assert packet["rejected_evidence"][0]["is_target_document"] is True
    assert packet["rejected_evidence"][0]["review_hint"]
    assert packet["target_document_candidates"][0]["evidence_id"] == "evidence-span-target-mdna"
    assert packet["target_document_candidates"][0]["rescuable"] is True


def test_retrieval_workbench_packet_exposes_reader_diagnostics_and_table_snippets() -> None:
    doc_link = "https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm"
    binding = {
        "company": "3M",
        "doc_link": doc_link,
        "doc_period": "2018",
        "required_statement": "cash_flow_statement",
        "required_line_item": "capital expenditures",
    }
    goal = SearchGoal(
        goal_id="goal-workbench-reader-table",
        query="3M FY2018 capital expenditures",
        metadata={
            "benchmark_doc_retrieval": True,
            "source_url": doc_link,
            "target_document_binding": binding,
            "compiled_task_hint": {
                "schema": "holo.kernel_v3.compiled_task_hint.v1",
                "domain": "finance",
                "task_spec": {"task_type": "compute", "target_entities": ["3M"], "target_periods": ["2018"]},
                "evidence_specs": [
                    {
                        "slot_name": "capital_expenditures",
                        "accepted_attributes": ["capital expenditures", "purchases of property plant and equipment"],
                        "source_role": "primary_filing",
                        "target_period": "2018",
                        "statement": "cash_flow_statement",
                        "line_item": "capital expenditures",
                    }
                ],
                "transform_specs": [
                    {
                        "name": "capital_intensity_capex_revenue",
                        "required_slots": ["capital_expenditures", "revenue"],
                        "expression": "capital_expenditures / revenue",
                    }
                ],
            },
        },
    )
    document = FetchedDocument(
        document_id="doc-workbench-reader-table",
        goal_id=goal.goal_id,
        source_id="source-workbench-reader-table",
        uri=doc_link,
        title="3M 2018 10-K",
        artifact_id="artifact-workbench-reader-table",
        payload_hash="hash",
        preview="",
        size_bytes=2_000,
        metadata={"mime_type": "text/plain", "target_document_binding": binding},
    )
    body = "\n".join(
        [
            "3M Company annual report",
            "Consolidated Statement of Cash Flows Years ended December 31 (Millions)",
            "2018 2017 2016",
            "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)",
            "Proceeds from sale of PP&E and other assets 262 49 58",
        ]
    )
    span = ExtractedSpan(
        span_id="span-workbench-reader-table-1",
        goal_id=goal.goal_id,
        document_id=document.document_id,
        source_id=document.source_id,
        text="Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)",
        start_offset=0,
        end_offset=80,
        score=12.0,
        metadata={
            "source_uri": doc_link,
            "text_mode": "plain_text",
            "document_reader": {
                "parser_used": "plain_text",
                "pages_extracted": 1,
                "chars_extracted": len(body),
                "table_like_blocks": 2,
            },
        },
    )

    packet = retrieval_workbench_packet(
        goal=goal,
        sources=[],
        fetch_summaries=[],
        documents=[(document, body)],
        spans=[span],
        evidence=[],
        citations=[],
        rejected_evidence=[],
    )

    summary = packet["document_summaries"][0]
    assert summary["document_reader"]["parser_used"] == "plain_text"
    assert summary["document_reader"]["table_like_blocks"] == 2
    assert summary["is_target_document"] is True
    snippets = summary["table_like_snippets"]
    assert snippets
    assert any("Purchases of property, plant and equipment" in item["text"] for item in snippets)
    assert any("1,577" in item["text"] for item in snippets)


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


def test_target_document_binding_extracts_cash_flow_ppe_purchase_row() -> None:
    binding = {
        "company": "3M",
        "doc_link": "https://investors.3m.com/financials/sec-filings/content/0001558370-19-000470/0001558370-19-000470.pdf",
        "doc_period": "2018",
        "required_statement": "cash_flow_statement",
        "required_line_item": "capital expenditures",
        "primary_source_required": True,
    }
    goal = SearchGoal(
        goal_id="goal-target-binding-extract",
        query="3M FY2018 capital expenditures",
        max_spans_per_document=2,
        metadata={"target_document_binding": binding},
    )
    document = FetchedDocument(
        document_id="doc-target-binding-extract",
        goal_id=goal.goal_id,
        source_id="source-target-binding-extract",
        uri=binding["doc_link"],
        title="3M 2018 10-K",
        artifact_id="artifact-target-binding-extract",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "text/plain", "target_document_binding": binding},
    )
    body = (
        "3M Company annual report. "
        "Consolidated Statement of Cash Flows Years ended December 31 (Millions) "
        "2018 2017 2016 Cash Flows from Investing Activities "
        "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420) "
        "Proceeds from sale of PP&E and other assets 262 49 58"
    )

    spans = extract_spans(goal=goal, document=document, body=body)

    assert spans
    assert spans[0].metadata["target_document_binding"]["doc_period"] == "2018"
    assert spans[0].metadata["target_line_item"] == "capital expenditures"
    assert "Consolidated Statement of Cash Flows" in spans[0].text
    assert "Purchases of property, plant and equipment" in spans[0].text
    assert "1,577" in spans[0].text


def test_compiled_evidence_specs_drive_target_document_table_span_extraction() -> None:
    doc_link = "https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm"
    binding = {
        "company": "3M",
        "doc_link": doc_link,
        "doc_period": "2018",
        "doc_type": "10k",
        "primary_source_required": True,
    }
    goal = SearchGoal(
        goal_id="goal-compiled-spec-target-extract",
        query="3M FY2018 capital intensity",
        max_spans_per_document=4,
        metadata={
            "target_document_binding": binding,
            "compiled_task_hint": {
                "schema": "holo.kernel_v3.compiled_task_hint.v1",
                "domain": "finance",
                "task_spec": {"task_type": "compute", "target_entities": ["3M"], "target_periods": ["2018"]},
                "evidence_specs": [
                    {
                        "slot_name": "revenue",
                        "accepted_attributes": ["revenue", "net sales"],
                        "source_role": "primary_filing",
                        "target_period": "2018",
                        "statement": "income_statement",
                        "line_item": "revenue",
                    },
                    {
                        "slot_name": "capital_expenditures",
                        "accepted_attributes": ["capital expenditures", "purchases of property plant and equipment"],
                        "source_role": "primary_filing",
                        "target_period": "2018",
                        "statement": "cash_flow_statement",
                        "line_item": "capital expenditures",
                    },
                ],
                "transform_specs": [
                    {
                        "name": "capital_intensity_capex_revenue",
                        "required_slots": ["capital_expenditures", "revenue"],
                        "expression": "capital_expenditures / revenue",
                    }
                ],
            },
        },
    )
    document = FetchedDocument(
        document_id="doc-compiled-spec-target-extract",
        goal_id=goal.goal_id,
        source_id="source-compiled-spec-target-extract",
        uri=doc_link,
        title="3M 2018 10-K",
        artifact_id="artifact-compiled-spec-target-extract",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "text/plain", "target_document_binding": binding},
    )
    body = "\n".join(
        [
            "3M Company annual report",
            "Consolidated Statement of Income Years ended December 31 (Millions)",
            "2018 2017 2016",
            "Net sales 32765 31657 30109",
            "Consolidated Statement of Cash Flows Years ended December 31 (Millions)",
            "Purchases of property, plant and equipment (PP&E) (1,577) (1,373) (1,420)",
        ]
    )

    spans = extract_spans(goal=goal, document=document, body=body)
    target_slots = {str(span.metadata.get("target_slot") or "") for span in spans}
    target_line_items = {str(span.metadata.get("target_line_item") or "") for span in spans}

    assert "revenue" in target_slots
    assert "capital_expenditures" in target_slots
    assert "revenue" in target_line_items
    assert "capital expenditures" in target_line_items
    assert any("Net sales" in span.text for span in spans)
    assert any("Purchases of property, plant and equipment" in span.text for span in spans)


def test_sec_companyfacts_reader_uses_target_binding_when_query_is_source_url() -> None:
    binding = {
        "company": "3M",
        "doc_link": "https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm",
        "doc_period": "2018",
        "doc_type": "10k",
        "required_statement": "cash_flow_statement",
        "required_line_item": "capital expenditures",
        "primary_source_required": True,
    }
    goal = SearchGoal(
        goal_id="goal-companyfacts-target-binding",
        query=binding["doc_link"],
        max_spans_per_document=3,
        metadata={"target_document_binding": binding},
    )
    document = FetchedDocument(
        document_id="doc-companyfacts-target-binding",
        goal_id=goal.goal_id,
        source_id="source-companyfacts-target-binding",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
        title="SEC companyfacts JSON for CIK 0000066740",
        artifact_id="artifact-companyfacts-target-binding",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "application/json"},
    )
    body = json.dumps(
        {
            "entityName": "3M CO",
            "cik": "66740",
            "facts": {
                "us-gaap": {
                    "PaymentsToAcquirePropertyPlantAndEquipment": {
                        "label": "Payments to Acquire Property, Plant, and Equipment",
                        "units": {
                            "USD": [
                                {
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2025-02-01",
                                    "start": "2024-01-01",
                                    "end": "2024-12-31",
                                    "val": 899000000,
                                    "accn": "0000066740-25-000001",
                                },
                                {
                                    "fy": 2020,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2021-02-04",
                                    "start": "2018-01-01",
                                    "end": "2018-12-31",
                                    "val": 1577000000,
                                    "accn": "0001558370-21-000737",
                                },
                                {
                                    "fy": 2018,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2019-02-08",
                                    "start": "2018-01-01",
                                    "end": "2018-12-31",
                                    "val": 1577000000,
                                    "accn": "0001558370-19-000470",
                                },
                            ]
                        },
                    }
                }
            },
        }
    )

    spans = extract_spans(goal=goal, document=document, body=body)

    assert spans
    assert spans[0].metadata["target_document_binding"]["doc_period"] == "2018"
    assert spans[0].metadata["target_line_item"] == "capital expenditures"
    assert "period_fy=2018" in spans[0].text
    assert "value=1577000000" in spans[0].text
    assert "value=899000000" not in spans[0].text


def test_sec_companyfacts_reader_uses_target_binding_for_net_ppne() -> None:
    binding = {
        "company": "3M",
        "doc_link": "https://www.sec.gov/Archives/edgar/data/66740/000155837019000470/mmm-20181231x10k.htm",
        "doc_period": "2018",
        "doc_type": "10k",
        "required_statement": "balance_sheet",
        "required_line_item": "property plant and equipment net",
        "primary_source_required": True,
    }
    goal = SearchGoal(
        goal_id="goal-companyfacts-net-ppne",
        query=binding["doc_link"],
        max_spans_per_document=3,
        metadata={"target_document_binding": binding},
    )
    document = FetchedDocument(
        document_id="doc-companyfacts-net-ppne",
        goal_id=goal.goal_id,
        source_id="source-companyfacts-net-ppne",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
        title="SEC companyfacts JSON for CIK 0000066740",
        artifact_id="artifact-companyfacts-net-ppne",
        payload_hash="hash",
        preview="",
        size_bytes=1,
        metadata={"mime_type": "application/json"},
    )
    body = json.dumps(
        {
            "entityName": "3M CO",
            "cik": "66740",
            "facts": {
                "us-gaap": {
                    "PropertyPlantAndEquipmentNet": {
                        "label": "Property, Plant and Equipment, Net",
                        "units": {
                            "USD": [
                                {
                                    "fy": 2024,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2025-02-01",
                                    "end": "2024-12-31",
                                    "val": 7100000000,
                                    "accn": "0000066740-25-000001",
                                },
                                {
                                    "fy": 2018,
                                    "fp": "FY",
                                    "form": "10-K",
                                    "filed": "2019-02-08",
                                    "end": "2018-12-31",
                                    "val": 4366000000,
                                    "accn": "0001558370-19-000470",
                                },
                            ]
                        },
                    }
                }
            },
        }
    )

    spans = extract_spans(goal=goal, document=document, body=body)

    assert spans
    assert spans[0].metadata["target_document_binding"]["doc_period"] == "2018"
    assert spans[0].metadata["target_line_item"] == "property plant and equipment net"
    assert "metric=property plant and equipment net" in spans[0].text
    assert "period_fy=2018" in spans[0].text
    assert "value=4366000000" in spans[0].text
    assert "value=7100000000" not in spans[0].text


def test_http_fetch_provider_raises_companyfacts_byte_cap_without_expanding_generic_fetches() -> None:
    observed: list[tuple[str, int]] = []

    def transport(url: str, _headers: dict[str, str], _timeout: int, max_bytes: int) -> HttpTransportResponse:
        observed.append((url, max_bytes))
        return HttpTransportResponse(status_code=200, body=b"{}", mime_type="application/json")

    provider = HttpFetchProvider(enabled=True, allow_all_hosts=True, max_bytes=4_000_000, transport=transport)

    provider.fetch(
        SearchSource(
            source_id="source-generic-json",
            provider="direct",
            uri="https://example.com/data.json",
            title="Generic JSON",
            snippet="",
        )
    )
    provider.fetch(
        SearchSource(
            source_id="source-companyfacts-json",
            provider="sec",
            uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000066740.json",
            title="SEC companyfacts JSON",
            snippet="",
            metadata={"source_kind": "sec_companyfacts_json"},
        )
    )
    provider.fetch(
        SearchSource(
            source_id="source-companyfacts-title",
            provider="sec",
            uri="https://example.com/large-structured.json",
            title="SEC companyfacts JSON for CIK 0000078003",
            snippet="Official SEC XBRL companyfacts JSON",
        )
    )

    assert observed[0][1] == 4_000_000
    assert observed[1][1] == 32_000_000
    assert observed[2][1] == 32_000_000
