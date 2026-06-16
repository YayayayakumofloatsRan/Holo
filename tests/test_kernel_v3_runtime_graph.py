from __future__ import annotations

import json

from kernel_v3.runtime_graph import (
    records_until_terminal,
    runtime_graph_delta_stream,
    runtime_stage_for_kind,
    runtime_topology_projection,
)


def test_runtime_stage_for_kind_maps_core_agent_loop_events() -> None:
    assert runtime_stage_for_kind("semantic_intake") == "Intake"
    assert runtime_stage_for_kind("processor_request") == "Plan"
    assert runtime_stage_for_kind("policy_decision") == "Policy"
    assert runtime_stage_for_kind("retrieval_search_attempt") == "Search"
    assert runtime_stage_for_kind("finance_slot_bind") == "Evidence"
    assert runtime_stage_for_kind("finance_numeric_judge") == "Verify"
    assert runtime_stage_for_kind("chat_agent_result") == "Answer"


def test_runtime_topology_freezes_at_terminal_record() -> None:
    records = [
        _record("chat_turn", {"text": "finance task"}),
        _record("processor_request", {"task_type": "planner.propose", "prompt": "secret sk-live"}),
        _record("retrieval_search_attempt", {"query": "AAPL 10-K"}),
        _record("chat_agent_result", {"final_answer": {"answer": "done"}}),
        _record("processor_request", {"task_type": "post.final.diagnostic"}),
    ]

    visible = records_until_terminal(records)
    projection = runtime_topology_projection(records)
    by_label = {row["label"]: row for row in projection.nodes}

    assert len(visible) == 4
    assert projection.terminal is True
    assert projection.latest_stage == "Answer"
    assert by_label["Answer"]["state"] == "closed"
    assert by_label["Plan"]["value"] == 1
    assert projection.diagnostics["raw_record_count"] == 5
    assert projection.diagnostics["record_count"] == 4
    assert projection.diagnostics["ignored_post_terminal_record_count"] == 1
    assert projection.diagnostics["ignored_post_terminal_record_kind_counts"] == {"processor_request": 1}
    assert projection.diagnostics["frozen_at_record_id"].startswith("rec-chat_agent_result")
    assert projection.diagnostics["stage_counts"]["Plan"] == 1


def test_runtime_graph_delta_stream_is_typed_and_redacted_to_metadata() -> None:
    records = [
        _record("chat_turn", {"text": "question"}),
        _record("processor_request", {"request_id": "req-1", "task_type": "finance.slot_bind", "prompt": "sk-secret"}),
        _record("processor_result", {"request_id": "req-1", "task_type": "finance.slot_bind", "status": "ok"}),
        _record("retrieval_search_attempt", {"query": "gold_answer should not be here"}),
        _record("agent_failure_report", {"reason": "missing evidence"}),
        _record("retrieval_search_attempt", {"query": "late post-final event"}),
    ]

    deltas = runtime_graph_delta_stream(records)
    payload = json.dumps(deltas, ensure_ascii=False)

    assert [delta["stage"] for delta in deltas] == ["Intake", "Plan", "Plan", "Search", "Answer"]
    assert deltas[-1]["terminal"] is True
    assert deltas[-1]["node_updates"][0]["state"] == "failed"
    assert deltas[1]["metadata"] == {
        "request_id": "req-1",
        "task_type": "finance.slot_bind",
        "stage_index": 1,
        "loop_iteration": 1,
    }
    assert deltas[1]["node_updates"][0]["stage_index"] == 1
    assert deltas[1]["node_updates"][0]["loop_iteration"] == 1
    assert deltas[3]["edge_updates"][0]["loop_iteration"] == 1
    assert "runtime_transition" in {edge["edge_type"] for delta in deltas for edge in delta["edge_updates"]}
    assert "sk-secret" not in payload
    assert "gold_answer should not be here" not in payload
    assert "late post-final event" not in payload


def test_runtime_graph_delta_stream_projects_tool_observation_diagnostics_without_raw_body() -> None:
    records = [
        _record(
            "observation",
            {
                "source": "tool:finance.verify_numeric",
                "status": "ok",
                "observation_id": "obs-verify",
                "action_id": "act-verify",
                "content": {
                    "verifier_status": "failed",
                    "issue_count": 2,
                    "missing_value_count": 1,
                    "verification": {
                        "raw_large_body": "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK",
                        "issues": [{"code": "unsupported_answer_number"}],
                    },
                    "repair_guidance": {
                        "schema": "holo.kernel_v3.finance_numeric_repair_guidance.v1",
                        "issue_codes": ["unsupported_answer_number", "ledger_extraction_gap"],
                        "repair_options": ["ask synthesis to remove unsupported answer numbers"],
                        "missing_value_examples": [
                            {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": "revenue"}
                        ],
                        "host_boundary": "diagnostic verifier guidance only; model still owns semantic repair",
                    },
                },
            },
        )
    ]

    deltas = runtime_graph_delta_stream(records)
    payload = json.dumps(deltas, ensure_ascii=False)

    diagnostics = deltas[0]["metadata"]["observation_diagnostics"]
    assert deltas[0]["node_updates"][0]["observation_diagnostics"] == diagnostics
    assert diagnostics["verifier_status"] == "failed"
    assert diagnostics["issue_codes"] == ["unsupported_answer_number", "ledger_extraction_gap"]
    assert diagnostics["repair_options"] == ["ask synthesis to remove unsupported answer numbers"]
    assert diagnostics["missing_value_examples"] == [
        {"raw": "$12 million", "value": "12000000", "unit": "million", "slot": "revenue"}
    ]
    assert "model still owns semantic repair" in diagnostics["host_boundary"]
    assert "RAW_PROVIDER_BODY_SHOULD_NOT_LEAK" not in payload


def _record(kind: str, data: dict) -> dict:
    return {
        "kind": kind,
        "task_id": "task-runtime-graph",
        "run_id": "run-runtime-graph",
        "step_id": "step-1",
        "record_id": f"rec-{kind}-{len(str(data))}",
        "recorded_at_ms": len(str(data)),
        "data": data,
    }
