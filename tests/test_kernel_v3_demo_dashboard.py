from __future__ import annotations

from kernel_v3.demo_dashboard import _chat_result_answer_text, console_state, finance_debug_state, loop_topology_state


def test_demo_dashboard_prefers_structured_final_answer_text() -> None:
    text = _chat_result_answer_text(
        {
            "answer": "BROKEN TOP LEVEL ANSWER",
            "final_answer": {"answer": "Structured final answer is authoritative."},
        }
    )

    assert text == "Structured final answer is authoritative."


def test_demo_dashboard_finance_debug_summarizes_slots_formulas_and_cache() -> None:
    records = [
        _record(
            "finance_fact_ledger",
            {
                "fact_count": 2,
                "citation_count": 1,
                "evidence_count": 1,
                "facts": [
                    {
                        "fact_id": "fact-revenue",
                        "metric": "revenue",
                        "period": "FY2022",
                        "value": "34229000000",
                        "unit": "USD",
                        "citation_ref": "cite-1",
                        "metadata": {"source": "html_table_fact"},
                    },
                    {
                        "fact_id": "fact-ppe",
                        "metric": "property plant and equipment net",
                        "period": "FY2022",
                        "value": "9178000000",
                        "unit": "USD",
                        "citation_ref": "cite-1",
                        "metadata": {"source": "html_table_fact"},
                    },
                ],
            },
        ),
        _record(
            "finance_slot_bind",
            {
                "status": "ready",
                "decision": "ready",
                "reason_summary": "Bound revenue and PP&E net from the 10-K table.",
                "slot_bindings": [
                    {"slot_name": "revenue", "variable_name": "revenue", "fact_id": "fact-revenue"},
                    {
                        "slot_name": "property_plant_and_equipment_net",
                        "variable_name": "ppe",
                        "fact_id": "fact-ppe",
                    },
                ],
                "missing_slots": ["assets"],
                "formula_request_count": 1,
                "accepted_formula_plan_count": 1,
            },
        ),
        _record(
            "processor_result",
            {
                "task_type": "finance.slot_bind",
                "status": "ok",
                "duration_ms": 1200,
                "usage": {
                    "total_tokens": 1000,
                    "prompt_cache_hit_tokens": 900,
                    "prompt_cache_miss_tokens": 100,
                },
            },
        ),
        _record(
            "calculator_result",
            {
                "status": "ok",
                "content": {
                    "formula_trace": {
                        "formula_name": "ppe_to_revenue",
                        "expression": "ppe / revenue",
                        "input_fact_ids": ["fact-ppe", "fact-revenue"],
                        "result_value": "0.2681",
                        "unit": "ratio",
                    }
                },
            },
        ),
    ]

    debug = finance_debug_state(records)

    assert debug["status"] == "needs_more_work"
    assert debug["facts"]["fact_count"] == 2
    assert debug["missing_slots"] == ["assets"]
    assert debug["slots"][1]["slot"] == "property_plant_and_equipment_net"
    assert debug["formulas"][0]["result"] == "0.2681"
    assert debug["model"]["cache_hit_ratio"] == 0.9
    assert "Missing slots" in debug["headline"]


def test_demo_dashboard_topology_counts_finance_specific_events() -> None:
    records = [
        _record("chat_turn", {"text": "finance task"}),
        _record("finance_fact_ledger", {"fact_count": 1}),
        _record("finance_slot_bind", {"decision": "ready"}),
        _record("calculator_result", {"status": "ok", "content": {"result_value": "1.0"}}),
        _record("finance_numeric_verification", {"status": "passed"}),
    ]

    by_label = {row["label"]: row for row in loop_topology_state(records)}

    assert by_label["Evidence"]["value"] == 2
    assert by_label["Tools"]["value"] == 1
    assert by_label["Verify"]["value"] == 1


def test_demo_dashboard_console_state_exposes_graph_delta_tool_diagnostics() -> None:
    records = [
        _record("chat_turn", {"thread_id": "demo-thread", "text": "verify this finance answer"}),
        _record(
            "observation",
            {
                "source": "tool:finance.verify_numeric",
                "content": {
                    "verifier_status": "failed",
                    "issue_count": 1,
                    "missing_value_count": 1,
                    "repair_guidance": {
                        "schema": "holo.kernel_v3.finance.numeric_repair_guidance.v1",
                        "issue_codes": ["missing_formula_input"],
                        "repair_options": ["retrieve the missing input and rerun calculator"],
                        "missing_value_examples": [
                            {"slot": "average_inventory", "value": "", "unit": "USD"}
                        ],
                        "host_boundary": "Host exposes diagnostics; LLM still chooses repair.",
                    },
                },
            },
        ),
    ]

    state = console_state(records, "demo-thread", [])

    diagnostic_deltas = [
        row
        for row in state["graph_deltas"]
        if row.get("metadata", {}).get("observation_diagnostics")
    ]
    assert diagnostic_deltas
    diagnostics = diagnostic_deltas[-1]["metadata"]["observation_diagnostics"]
    assert diagnostics["verifier_status"] == "failed"
    assert diagnostics["issue_codes"] == ["missing_formula_input"]
    assert diagnostics["repair_options"] == ["retrieve the missing input and rerun calculator"]
    assert "content" not in diagnostic_deltas[-1]["metadata"]


def _record(kind: str, data: dict) -> dict:
    return {
        "kind": kind,
        "task_id": "task-demo",
        "run_id": "run-demo",
        "record_id": f"rec-{kind}",
        "recorded_at_ms": 1,
        "data": data,
    }
