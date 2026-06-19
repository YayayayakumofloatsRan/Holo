from __future__ import annotations

import asyncio
import json
import ssl
import urllib.error

import pytest

from kernel_v4.context import ToolUseContext
from kernel_v4.contracts import ModelEvent, ToolCall
from kernel_v4.finance_tools import (
    DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    V4_DOCUMENT_TEXT_EXTRACT,
    V4_SEC_EDGAR_FILING_DOCUMENTS,
    _hydrate_v3_payload,
    _target_filing_openbb_guard,
)
from kernel_v4.finance_run import _usage_summary
from kernel_v4.finance_runner import (
    FinanceQuestionSpec,
    _initial_finance_metadata,
    audit_finance_question_closure,
    build_finance_registry,
    run_finance_question,
)


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
    assert "finance.workbench.open" in message
    assert "The answer is 20%." not in message
    assert "subtract(120, 100)" not in message
    assert "expected_numeric" not in message
    assert "reference_answer" not in message
    assert "never send empty arguments for tools with required fields" in message
    assert "provided_context.parse use {'context_ref': 'task_provided_context'}" in message
    assert "do not repeat the same tool call with the same input" in message
    assert "do not call market/OpenBB" in message
    assert "what does the company sell" in message
    assert "margin-change or driver-analysis questions" in message
    assert "what drove revenue/sales" in message
    assert "yes/no disclosure questions" in message
    assert "percent change from the prior/base value" in message
    assert "revenue-threshold category questions" in message
    assert "list every category that meets the threshold" in message
    assert "store-count" in message
    assert "ownership percentage is not a substitute for cash consideration" in message
    assert "segment-growth or M&A-exclusion questions" in message
    assert "gross-margin profile questions" in message
    assert "directly reported gross profit/subtotal" in message
    assert "normalize whether cost rows are positive cost magnitudes or signed negative expenses" in message
    assert "document.text.extract" in message
    assert "shareholder vote, board nominee" in message
    assert "Votes Against" in message
    assert "primary-customer, customer-concentration, major-customer" in message
    assert "disclosed revenue share, concentration percentage" in message
    assert "legal battle, legal proceedings, litigation" in message
    assert "settlement amounts, accruals, or loss ranges" in message
    assert "Do not rely only on table-of-contents entries" in message
    assert "capital-intensity or asset-intensity questions" in message
    assert "PP&E/revenue" in message
    assert "operating/non-cash working capital" in message
    assert "liability rollforward or composition table" in message
    assert "dominant component's percentage of the total" in message
    assert "common-shareholder payment questions" in message
    assert "quarterly cash dividend" in message
    assert "Do not confuse subsidiary dividends" in message
    assert "prefer net income / total assets" in message
    assert "Do not introduce unsourced generic threshold numbers" in message
    assert "self-edit the final answer" in message
    assert "gold_reference_material_included" in message
    assert "excluded_gold_reference_field_count" in message
    assert spec.excluded_gold_reference_fields == (
        "answer",
        "expected_numeric",
        "gold_program",
        "reference_answer",
    )


def test_initial_finance_metadata_enables_high_threshold_checkpoints_for_live_finance() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "fb-store-count",
            "question": "Was there any change in the number of stores between Q2 FY2024 and FY2023?",
        },
        benchmark_family="financebench",
    )

    metadata = _initial_finance_metadata(spec)

    assert metadata["enable_endgame_checkpoint"] is True
    assert metadata["enable_calculation_checkpoint"] is True
    assert metadata["enable_repeated_source_checkpoint"] is True
    assert metadata["endgame_evidence_success_threshold"] == 32
    assert metadata["calculation_evidence_success_threshold"] == 6
    assert metadata["repeated_source_success_threshold"] == 6
    assert metadata["repeated_source_error_threshold"] == 4
    assert metadata["source_saturation_evidence_success_threshold"] == 20


def test_finance_question_spec_uses_nested_prompt_context_without_gold() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "V/2008/page_17.pdf-1",
            "source": "finqa",
            "question": "what is the average payment volume per transaction for american express?",
            "gold_answer": "127.40",
            "metadata": {
                "benchmark": "finqa",
                "prompt_context": "table: american express payments volume 637; total transactions 5.0.",
                "reference_program_available": True,
                "company": "Visa Inc.",
            },
        },
        benchmark_family="finqa",
    )

    message = spec.to_user_message()

    assert spec.provided_context == "table: american express payments volume 637; total transactions 5.0."
    assert "american express payments volume 637" in message
    assert "Visa Inc." in message
    assert "127.40" not in message
    assert "gold_answer" not in message


def test_provided_context_parse_accepts_task_context_ref() -> None:
    registry = build_finance_registry(allow_network=False)

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-context-ref",
                name="provided_context.parse",
                input={"context_ref": "task_provided_context"},
            ),
            ToolUseContext(
                run_id="run-context-ref",
                thread_key="test",
                metadata={"task_provided_context": "Revenue was 100 in 2023 and 120 in 2024."},
            ),
        )
    )

    assert message.is_error is False
    assert "Revenue was 100" in str(message.content)


def test_sec_company_filings_payload_hydrates_target_fiscal_year_from_safe_metadata() -> None:
    context = ToolUseContext(
        run_id="run-target-period",
        thread_key="test",
        metadata={
            "task_question": "Does Adobe have an improving Free cashflow conversion as of FY2022?",
            "task_safe_metadata": {
                "company": "Adobe",
                "doc_period": "2022",
                "doc_type": "10k",
                "doc_link": "https://www.sec.gov/example/adbe-2022-10k.htm",
            },
        },
    )

    hydrated = _hydrate_v3_payload(
        manifest_name=SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        payload={"ticker": "ADBE"},
        context=context,
    )

    assert hydrated["ticker"] == "ADBE"
    assert hydrated["fiscal_year"] == 2022
    assert hydrated["period"] == "FY2022"


def test_sec_company_filings_payload_preserves_model_selected_period() -> None:
    context = ToolUseContext(
        run_id="run-target-period-preserve",
        thread_key="test",
        metadata={
            "task_question": "Compare FY2022 and FY2021.",
            "task_safe_metadata": {"doc_period": "2022"},
        },
    )

    hydrated = _hydrate_v3_payload(
        manifest_name=SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
        payload={"ticker": "ADBE", "fiscal_year": 2021, "period": "FY2021"},
        context=context,
    )

    assert hydrated["fiscal_year"] == 2021
    assert hydrated["period"] == "FY2021"


def test_sec_financials_payload_hydrates_target_period_to_avoid_latest_filing_drift() -> None:
    context = ToolUseContext(
        run_id="run-target-period-financials-open",
        thread_key="test",
        metadata={
            "task_question": "Does Adobe have an improving Free cashflow conversion as of FY2022?",
            "task_safe_metadata": {"doc_period": "2022"},
        },
    )

    hydrated = _hydrate_v3_payload(
        manifest_name=SEC_EDGAR_FINANCIALS_TOOL_NAME,
        payload={"ticker": "ADBE"},
        context=context,
    )

    assert hydrated == {"ticker": "ADBE", "fiscal_year": 2022, "period": "FY2022"}


def test_sec_financials_payload_preserves_model_selected_period() -> None:
    context = ToolUseContext(
        run_id="run-target-period-financials-preserve",
        thread_key="test",
        metadata={
            "task_question": "Compare FY2022 and FY2021.",
            "task_safe_metadata": {"doc_period": "2022"},
        },
    )

    hydrated = _hydrate_v3_payload(
        manifest_name=SEC_EDGAR_FINANCIALS_TOOL_NAME,
        payload={"ticker": "ADBE", "fiscal_year": 2021, "period": "FY2021"},
        context=context,
    )

    assert hydrated == {"ticker": "ADBE", "fiscal_year": 2021, "period": "FY2021"}


def test_target_filing_openbb_guard_blocks_unqualified_latest_period_calls() -> None:
    context = ToolUseContext(
        run_id="run-openbb-target-filing-guard",
        thread_key="test",
        metadata={
            "task_question": "What drove operating margin change as of FY22 for AMD?",
            "task_safe_metadata": {
                "company": "AMD",
                "doc_period": "2022",
                "doc_type": "10k",
                "doc_link": "https://ir.amd.com/sec-filings/content/0000002488-23-000047/0000002488-23-000047.pdf",
            },
        },
    )

    blocked = _target_filing_openbb_guard(
        payload={"route": "equity.fundamental.income", "kwargs": {"symbol": "AMD"}},
        context=context,
    )

    assert blocked is not None
    assert blocked["status"] == "blocked"
    assert blocked["content"]["error"] == "target_filing_openbb_period_required"


def test_target_filing_openbb_guard_allows_explicit_period_or_market_intent() -> None:
    target_context = ToolUseContext(
        run_id="run-openbb-target-filing-period",
        thread_key="test",
        metadata={
            "task_question": "What drove operating margin change as of FY22 for AMD?",
            "task_safe_metadata": {
                "doc_period": "2022",
                "doc_link": "https://ir.amd.com/sec-filings/content/example.pdf",
            },
        },
    )
    market_context = ToolUseContext(
        run_id="run-openbb-market-intent",
        thread_key="test",
        metadata={
            "task_question": "What was AMD's stock price return in FY2022?",
            "task_safe_metadata": {
                "doc_period": "2022",
                "doc_link": "https://ir.amd.com/sec-filings/content/example.pdf",
            },
        },
    )

    assert (
        _target_filing_openbb_guard(
            payload={"route": "equity.fundamental.income", "kwargs": {"symbol": "AMD", "fiscal_year": 2022}},
            context=target_context,
        )
        is None
    )
    assert (
        _target_filing_openbb_guard(
            payload={"route": "equity.price.historical", "kwargs": {"symbol": "AMD"}},
            context=market_context,
        )
        is None
    )


def test_finance_question_spec_keeps_nested_financebench_doc_metadata_safe() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "financebench_id_03029",
            "source": "financebench",
            "question": "What is the FY2018 capital expenditure amount for 3M?",
            "gold_answer": "$1577.00",
            "metadata": {
                "company": "3M",
                "doc_name": "3M_2018_10K",
                "doc_period": "2018",
                "doc_type": "10k",
                "doc_link": "https://investors.3m.com/example.pdf",
                "prompt_context": "FinanceBench target document metadata follows. Use it to acquire evidence; it is not answer evidence by itself.",
            },
        },
        benchmark_family="financebench",
    )

    message = spec.to_user_message()

    assert spec.metadata["company"] == "3M"
    assert spec.metadata["doc_name"] == "3M_2018_10K"
    assert spec.metadata["doc_link"] == "https://investors.3m.com/example.pdf"
    assert "target document metadata" in message
    assert "$1577.00" not in message
    assert "gold_answer" not in message


def test_finance_question_closure_audit_maps_finqa_context_row_without_gold() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "finqa-closure-1",
            "dataset": "finqa",
            "question": "What is the average payment volume per transaction?",
            "oracle_context": "Payment volume was 637 and total transactions were 5.0.",
            "answer": "127.40",
            "gold_program": "divide(637,5.0)",
            "reference_answer": "127.40",
        },
        benchmark_family="finqa",
    )

    audit = asyncio.run(audit_finance_question_closure(spec, allow_network=False))
    dumped = json.dumps(audit, ensure_ascii=False, sort_keys=True)

    assert audit["schema"] == "holo.kernel_v4.finance_question_closure_audit.v1"
    assert audit["status"] == "ok"
    assert audit["audit_mode"] == "no_network_fqa"
    assert audit["toolchain_audit"]["status"] == "ok"
    assert "provided_context_fqa_finqa" in audit["workbench"]["selected_profile_families"]
    assert audit["workbench"]["selected_missing_tools"] == {}
    assert audit["gold_reference_material_included"] is False
    assert audit["capability_claim"] is False
    assert audit["benchmark_progress_claim"] is False
    assert "127.40" not in dumped
    assert "divide(637" not in dumped
    assert "reference_answer" not in dumped


def test_finance_question_closure_audit_maps_financebench_public_filing_row_without_gold() -> None:
    spec = FinanceQuestionSpec.from_mapping(
        {
            "id": "financebench-capital-intensive",
            "dataset": "financebench",
            "question": "Is 3M a capital-intensive business based on FY2022 capex, PP&E, assets, revenue, and ROA?",
            "gold_answer": "No, not strongly capital-intensive.",
            "ticker": "MMM",
            "fiscal_year": 2022,
        },
        benchmark_family="financebench",
    )

    audit = asyncio.run(audit_finance_question_closure(spec, allow_network=True))
    dumped = json.dumps(audit, ensure_ascii=False, sort_keys=True)

    assert audit["status"] == "ok"
    assert audit["audit_mode"] == "full"
    assert audit["toolchain_audit"]["status"] == "ok"
    assert "capital_intensity_asset_intensity" in audit["workbench"]["selected_profile_families"]
    assert audit["toolchain_audit"]["coverage_profiles_missing_from_describe"] == []
    assert audit["workbench"]["selected_missing_tools"] == {}
    assert "No, not strongly" not in dumped
    assert "gold_answer" not in dumped


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
    assert "Legal battle, legal proceedings, litigation" in request["system_prompt"]
    assert "Do not rely only on a table of contents entry" in request["system_prompt"]
    assert "Dividend, shareholder-distribution" in request["system_prompt"]
    assert "Do not confuse dividends paid by regulated subsidiaries" in request["system_prompt"]
    assert "document.text.extract" in request["system_prompt"]
    assert "Shareholder vote, board nominee" in request["system_prompt"]
    tool_names = {tool.name for tool in request["tools"]}
    assert {
        "finance.workbench.open",
        "finance.toolchain.describe",
        "tool.workbench",
        "sec.edgar.financials",
        "document.text.extract",
        "document.search.hybrid",
        "provided_context.parse",
        "market.openbb.fetch",
        "data.table.query",
        "calendar.days_between",
        "calculator.compute",
        "finance.verify_numeric",
        "tool.discovery",
        "artifact.inspect",
        "artifact.search",
        "artifact.read",
    }.issubset(tool_names)
    first_context = request["context"]
    assert isinstance(first_context, dict)
    assert first_context == {}


def test_build_finance_registry_can_make_no_network_fqa_surface() -> None:
    registry = build_finance_registry(allow_network=False)
    tool_names = {manifest.name for manifest in registry.all_manifests()}

    assert "finance.workbench.open" in tool_names
    assert "tool.workbench" in tool_names
    assert "provided_context.parse" in tool_names
    assert "data.table.query" in tool_names
    assert "calculator.compute" in tool_names
    assert "finance.verify_numeric" in tool_names
    assert "tool.discovery" in tool_names
    assert "artifact.inspect" in tool_names
    assert "artifact.search" in tool_names
    assert "artifact.read" in tool_names
    assert V4_DOCUMENT_TEXT_EXTRACT not in tool_names
    assert "sec.edgar.financials" not in tool_names


def test_document_text_extract_writes_searchable_artifact(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return (
                b"<html><body><h1>Item 5.07</h1>"
                b"<p>Proposal 1 Board of Directors Votes For Votes Against Abstentions Broker Non-Votes.</p>"
                b"<p>Richard A. Johnson 54,484,293 16,105,005 77,685 6,884,223.</p>"
                b"</body></html>"
            )

        def geturl(self):
            return "https://example.test/foot-locker-8k"

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", lambda request, timeout=45: FakeResponse())
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-document-text-extract", thread_key="test")

    extracted = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-text-extract",
                name=V4_DOCUMENT_TEXT_EXTRACT,
                input={
                    "source": "https://example.test/foot-locker-8k",
                    "focus_terms": ["Votes Against", "Richard A. Johnson"],
                },
            ),
            context,
        )
    )

    assert extracted.is_error is False
    artifact_id = extracted.content["artifact_id"]
    assert extracted.content["status"] == "ok"
    assert extracted.content["focus_snippets"]
    assert artifact_id in context.metadata["v3_artifacts"]

    searched = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-search-text-artifact",
                name="artifact.search",
                input={"artifact_id": artifact_id, "query": "Votes Against Richard Johnson", "max_matches": 5},
            ),
            context,
        )
    )

    assert searched.is_error is False
    assert searched.content["matches"]


def test_document_text_extract_focus_terms_search_full_text_before_truncation(monkeypatch) -> None:
    long_prefix = "intro " * 2_000
    target = "Consolidated statement Sales to customers 94,943 Cost of products sold 30,000 Gross profit 64,943."

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return f"<html><body><p>{long_prefix}</p><p>{target}</p></body></html>".encode()

        def geturl(self):
            return "https://example.test/long-10k"

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", lambda request, timeout=45: FakeResponse())
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-document-text-focus-window", thread_key="test")

    extracted = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-text-extract-long",
                name=V4_DOCUMENT_TEXT_EXTRACT,
                input={
                    "source": "https://example.test/long-10k",
                    "focus_terms": ["Cost of products sold", "Gross profit"],
                    "max_chars": 2_000,
                },
            ),
            context,
        )
    )

    assert extracted.is_error is False
    assert extracted.content["full_text_chars"] > extracted.content["text_chars"]
    assert any("Cost of products sold" in item["snippet"] for item in extracted.content["focus_snippets"])

    searched = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-search-focused-text",
                name="artifact.search",
                input={
                    "artifact_id": extracted.content["artifact_id"],
                    "query": "Cost of products sold Gross profit",
                    "max_matches": 5,
                },
            ),
            context,
        )
    )

    assert searched.is_error is False
    assert searched.content["matches"]
    assert "Cost of products sold" in searched.content["matches"][0]["snippet"]


def test_document_text_extract_allows_large_requested_windows(monkeypatch) -> None:
    long_body = "alpha " * 90_000

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return f"<html><body><p>{long_body}</p></body></html>".encode()

        def geturl(self):
            return "https://example.test/large-10k"

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", lambda request, timeout=45: FakeResponse())
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-document-text-large-window", thread_key="test")

    extracted = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-text-extract-large",
                name=V4_DOCUMENT_TEXT_EXTRACT,
                input={"source": "https://example.test/large-10k", "max_chars": 400_000},
            ),
            context,
        )
    )

    assert extracted.is_error is False
    assert extracted.content["text_chars"] == 400_000
    assert extracted.content["full_text_chars"] > 400_000


def test_document_text_extract_expands_legal_focus_windows(monkeypatch) -> None:
    long_prefix = "intro " * 90_000
    legal_section = (
        "Legal and Regulatory Proceedings. Usual and Customary Pricing Litigation. "
        "The company disclosed a settlement amount of $625 million and an additional $4.3 billion framework."
    )

    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return f"<html><body><p>{long_prefix}</p><p>{legal_section}</p></body></html>".encode()

        def geturl(self):
            return "https://example.test/legal-10k"

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", lambda request, timeout=45: FakeResponse())
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-document-text-legal-focus-window", thread_key="test")

    extracted = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-text-extract-legal-focus",
                name=V4_DOCUMENT_TEXT_EXTRACT,
                input={
                    "source": "https://example.test/legal-10k",
                    "focus_terms": ["Legal and Regulatory Proceedings", "settlement"],
                },
            ),
            context,
        )
    )

    assert extracted.is_error is False
    assert extracted.content["legal_focus_expanded"] is True
    assert extracted.content["text_chars"] > 500_000

    searched = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-search-legal-amounts",
                name="artifact.search",
                input={"artifact_id": extracted.content["artifact_id"], "query": "$625 million $4.3 billion"},
            ),
            context,
        )
    )

    assert searched.is_error is False
    assert searched.content["matches"]


def test_document_text_extract_retries_ssl_unexpected_eof_with_fallback(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return b"<html><body><p>Adjusted diluted EPS was expected to grow in fiscal 2023.</p></body></html>"

        def geturl(self):
            return "https://example.test/static-file"

    calls: list[dict[str, object]] = []

    def fake_urlopen(request, **kwargs):
        calls.append(dict(kwargs))
        if len(calls) == 1:
            raise urllib.error.URLError(ssl.SSLError("UNEXPECTED_EOF_WHILE_READING"))
        assert "context" in kwargs
        return FakeResponse()

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", fake_urlopen)
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-document-text-ssl-fallback", thread_key="test")

    extracted = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-text-extract-ssl-fallback",
                name=V4_DOCUMENT_TEXT_EXTRACT,
                input={
                    "source": "https://example.test/static-file",
                    "focus_terms": ["Adjusted diluted EPS"],
                    "max_chars": 2_000,
                },
            ),
            context,
        )
    )

    assert extracted.is_error is False
    assert extracted.content["status"] == "ok"
    assert len(calls) == 2
    assert "Adjusted diluted EPS" in extracted.content["preview"]


def test_sec_edgar_filing_documents_expands_official_exhibit_urls(monkeypatch) -> None:
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit=-1):
            del limit
            return json.dumps(
                {
                    "directory": {
                        "item": [
                            {"name": "jnj-20230124.htm", "type": "10-K", "size": "12000"},
                            {"name": "jnj-20230124xex99d1.htm", "type": "EX-99.1", "description": "Earnings release"},
                            {"name": "primary_doc.xml", "type": "XML"},
                        ]
                    }
                }
            ).encode()

        def geturl(self):
            return "https://www.sec.gov/Archives/edgar/data/200406/000020040623000006/index.json"

    requested_urls: list[str] = []

    def fake_urlopen(request, **kwargs):
        del kwargs
        requested_urls.append(request.full_url)
        return FakeResponse()

    monkeypatch.setattr("kernel_v4.finance_tools.urllib.request.urlopen", fake_urlopen)
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-sec-filing-documents", thread_key="test")

    result = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-sec-docs",
                name=V4_SEC_EDGAR_FILING_DOCUMENTS,
                input={
                    "identifier": "JNJ",
                    "accession_number": "0000200406-23-000006",
                    "query": "earnings release exhibit 99.1",
                },
            ),
            context,
        )
    )

    assert result.is_error is False
    assert result.content["status"] == "ok"
    assert requested_urls == ["https://www.sec.gov/Archives/edgar/data/200406/000020040623000006/index.json"]
    assert result.content["documents"][0]["name"] == "jnj-20230124xex99d1.htm"
    assert result.content["documents"][0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/200406/000020040623000006/jnj-20230124xex99d1.htm"
    )
    assert result.content["artifact_id"] in context.metadata["v3_artifacts"]


def test_finance_workbench_all_profiles_reference_registered_tools_in_full_registry() -> None:
    registry = build_finance_registry(allow_network=True)
    registered = {manifest.name for manifest in registry.all_manifests()}
    context = ToolUseContext(run_id="run-full-workbench-contract", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-workbench-all",
                name="finance.workbench.open",
                input={"query": "", "max_profiles": 32},
            ),
            context,
        )
    )

    assert message.is_error is False
    profiles = message.content["selected_profiles"]
    families = {profile["family"] for profile in profiles}
    assert {
        "public_filing_evidence",
        "provided_context_fqa_finqa",
        "table_ranking_aggregation",
        "finance_transforms",
        "cash_flow_conversion",
        "multi_company_comparison",
        "inventory_efficiency_dio",
        "liquidity_quick_ratio",
        "liquidation_per_share_recovery",
        "capital_intensity_asset_intensity",
        "margin_driver_bridge",
        "segment_growth_mna_exclusion",
        "dividend_stability_trend",
        "legal_proceedings_disclosure",
        "shareholder_vote_results",
        "debt_securities_terms",
        "fiscal_dates",
        "market_data",
        "numeric_verification",
    }.issubset(families)
    missing: dict[str, set[str]] = {}
    for profile in profiles:
        tools = set(profile.get("primary_tools", [])) | set(profile.get("support_tools", []))
        absent = {tool for tool in tools if tool not in registered}
        if absent:
            missing[profile["family"]] = absent
        assert profile.get("required_evidence"), profile["family"]
        assert profile.get("workflow"), profile["family"]
    assert missing == {}


def test_finance_toolchain_describe_and_audit_cover_all_workbench_profiles() -> None:
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-toolchain-audit", thread_key="test")

    describe = asyncio.run(
        registry.execute(
            ToolCall(tool_call_id="call-describe", name="finance.toolchain.describe", input={}),
            context,
        )
    )
    audit = asyncio.run(
        registry.execute(
            ToolCall(tool_call_id="call-audit", name="finance.toolchain.audit", input={}),
            context,
        )
    )
    workbench = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-workbench-all-for-describe",
                name="finance.workbench.open",
                input={"query": "", "max_profiles": 32},
            ),
            context,
        )
    )

    assert describe.is_error is False
    assert audit.is_error is False
    assert workbench.is_error is False
    describe_families = {item["family"] for item in describe.content["coverage_families"]}
    workbench_families = {item["family"] for item in workbench.content["selected_profiles"]}
    assert describe_families == workbench_families
    assert audit.content["schema"] == "holo.kernel_v4.finance_toolchain_audit.v1"
    assert audit.content["status"] == "ok"
    assert audit.content["profile_count"] == len(workbench_families)
    assert audit.content["missing_tools_by_profile"] == {}
    assert audit.content["missing_core_tools"] == []
    assert audit.content["forbidden_legacy_tools_present"] == []
    assert audit.content["coverage_profiles_missing_from_describe"] == []
    assert audit.content["describe_families_without_profile"] == []
    assert "gold/reference material is not read" in audit.content["no_gold_policy"]
    assert "does not solve tasks" in audit.content["host_boundary"]


@pytest.mark.parametrize(
    ("query", "expected_family"),
    [
        ("retrieve exact FY2024 revenue line item from a 10-K filing and cite source", "public_filing_evidence"),
        ("FinQA provided context table: calculate average payment volume per transaction", "provided_context_fqa_finqa"),
        ("rank rows in a table and identify the highest aggregate value", "table_ranking_aggregation"),
        ("calculate revenue growth margin bps and ratio from observed inputs", "finance_transforms"),
        ("does free cashflow conversion improve using operating cash flow capex and net income", "cash_flow_conversion"),
        ("compare two companies on the same metric and explain which is more efficient", "multi_company_comparison"),
        ("compare inventory efficiency using days inventory outstanding DIO and COGS", "inventory_efficiency_dio"),
        ("quick ratio liquidity current assets inventories current liabilities", "liquidity_quick_ratio"),
        ("bankruptcy liquidation pay shareholders tangible book value per share", "liquidation_per_share_recovery"),
        ("is the company capital intensive based on capex PP&E assets net income ROA", "capital_intensity_asset_intensity"),
        ("what drove operating margin change based on MD&A and bridge table", "margin_driver_bridge"),
        ("which segment dragged growth excluding M&A acquisitions divestitures organic sales", "segment_growth_mna_exclusion"),
        ("paid dividends to common shareholders in Q2 quarterly cash dividend common stock", "dividend_stability_trend"),
        ("reported materially important ongoing legal battles Legal Proceedings litigation contingencies", "legal_proceedings_disclosure"),
        ("Item 5.07 board nominee votes against broker non-votes annual meeting", "shareholder_vote_results"),
        ("debt securities notes coupon maturity principal amount terms", "debt_securities_terms"),
        ("actual fiscal days between period start date and end date", "fiscal_dates"),
        ("market price quote ticker non-filing market data", "market_data"),
        ("verify final numeric claim rounding formula inputs", "numeric_verification"),
    ],
)
def test_finance_workbench_routes_representative_queries_to_expected_profiles(query: str, expected_family: str) -> None:
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id=f"run-route-{expected_family}", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id=f"call-route-{expected_family}",
                name="finance.workbench.open",
                input={"query": query, "max_profiles": 5},
            ),
            context,
        )
    )

    assert message.is_error is False
    families = {profile["family"] for profile in message.content["selected_profiles"]}
    assert expected_family in families


def test_finance_workbench_returns_full_capability_matrix_without_semantic_answer() -> None:
    registry = build_finance_registry(allow_network=True)
    context = ToolUseContext(run_id="run-capability-matrix", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-capability-matrix",
                name="finance.workbench.open",
                input={"query": "FinanceBench and FinQA hard task", "max_profiles": 3},
            ),
            context,
        )
    )

    assert message.is_error is False
    matrix = message.content["capability_matrix"]
    layers = {item["layer"] for item in matrix}
    assert {
        "task_intake_no_gold",
        "source_or_context_acquisition",
        "document_artifact_context",
        "table_and_transform_compute",
        "numeric_verification",
        "answer_synthesis",
    }.issubset(layers)
    assert "Benchmark gold/reference answers are never model context" in message.content["global_contract"]["no_gold_policy"]
    assert "semantic decisions remain with the model" in message.content["host_boundary"]
    assert "answer" not in message.content


def test_finance_workbench_no_network_fqa_profile_uses_available_tools_only() -> None:
    registry = build_finance_registry(allow_network=False)
    registered = {manifest.name for manifest in registry.all_manifests()}
    context = ToolUseContext(run_id="run-fqa-workbench-contract", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-workbench-fqa",
                name="finance.workbench.open",
                input={"task_family": "provided_context_fqa_finqa", "max_profiles": 1},
            ),
            context,
        )
    )

    assert message.is_error is False
    profile = message.content["selected_profiles"][0]
    assert profile["family"] == "provided_context_fqa_finqa"
    tools = set(profile.get("primary_tools", [])) | set(profile.get("support_tools", []))
    assert tools.issubset(registered)
    assert "provided_context.parse" in tools
    assert "data.table.query" in tools
    assert "calculator.compute" in tools


def test_finance_toolchain_audit_no_network_fqa_mode_is_ok_without_sec_tools() -> None:
    registry = build_finance_registry(allow_network=False)
    context = ToolUseContext(run_id="run-no-network-fqa-audit", thread_key="test")

    message = asyncio.run(
        registry.execute(
            ToolCall(
                tool_call_id="call-audit-no-network",
                name="finance.toolchain.audit",
                input={"mode": "no_network_fqa"},
            ),
            context,
        )
    )

    assert message.is_error is False
    assert message.content["status"] == "ok"
    assert message.content["allow_network"] is False
    assert message.content["profile_count"] == 4
    families = {row["family"] for row in message.content["profile_rows"]}
    assert families == {
        "provided_context_fqa_finqa",
        "table_ranking_aggregation",
        "finance_transforms",
        "numeric_verification",
    }
    assert message.content["missing_tools_by_profile"] == {}
    assert message.content["missing_core_tools"] == []
    assert message.content["no_network_fqa_missing_tools"] == []


def test_finance_run_usage_summary_reports_cache_hit_rate() -> None:
    class Result:
        events = [
            type(
                "Event",
                (),
                {
                    "event_type": "model_usage",
                    "data": {
                        "prompt_tokens": 100,
                        "completion_tokens": 10,
                        "total_tokens": 110,
                        "cache": {
                            "prompt_cache_hit_tokens": 60,
                            "prompt_cache_miss_tokens": 40,
                            "cache_hit_rate": 0.6,
                        },
                    },
                },
            )()
        ]

    summary = _usage_summary(Result())

    assert summary["model_usage_event_count"] == 1
    assert summary["prompt_tokens"] == 100
    assert summary["prompt_cache_hit_tokens"] == 60
    assert summary["prompt_cache_miss_tokens"] == 40
    assert summary["cache_hit_rate"] == 0.6
    assert summary["cache_hit_rate_available"] is True


def test_finance_v4_wrapper_defaults_document_search_to_compact_budget() -> None:
    context = ToolUseContext(run_id="run-compact-search-defaults", thread_key="test")

    hydrated = _hydrate_v3_payload(
        manifest_name=DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        payload={"artifact_id": "artifact-1", "query": "net revenue"},
        context=context,
    )
    explicit = _hydrate_v3_payload(
        manifest_name=DOCUMENT_SEARCH_HYBRID_TOOL_NAME,
        payload={"artifact_id": "artifact-1", "query": "net revenue", "max_chars": 16_000, "max_matches": 12},
        context=context,
    )

    assert hydrated["max_chars"] == 8_000
    assert hydrated["max_matches"] == 8
    assert explicit["max_chars"] == 16_000
    assert explicit["max_matches"] == 12
