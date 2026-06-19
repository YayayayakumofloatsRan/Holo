from __future__ import annotations

import asyncio
import json

from kernel_v4.contracts import ChatMessage, LoopResult, ToolCall
from kernel_v4.finance_run import build_parser, load_row_from_args, main, run_finance_cli
from kernel_v4.finance_run import _transcript_preview


def test_finance_run_dry_run_row_json_is_no_gold_packet_summary() -> None:
    args = build_parser().parse_args(
        [
            "--row-json",
            json.dumps(
                {
                    "id": "finqa-dry",
                    "dataset": "finqa",
                    "question": "Compute revenue growth.",
                    "oracle_context": "Revenue was 100 then 120.",
                    "answer": "20%",
                    "reference_answer": "20 percent",
                    "gold_program": "divide(subtract(120,100),100)",
                }
            ),
            "--benchmark-family",
            "finqa",
            "--dry-run",
        ]
    )

    payload = asyncio.run(run_finance_cli(args))
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema"] == "holo.kernel_v4.finance_run_dry_run.v1"
    assert payload["status"] == "dry_run"
    assert payload["task"]["task_id"] == "finqa-dry"
    assert payload["task"]["benchmark_family"] == "finqa"
    assert payload["task"]["provided_context_chars"] == len("Revenue was 100 then 120.")
    assert payload["task"]["excluded_gold_reference_field_count"] == 3
    assert payload["gold_reference_material_included"] is False
    assert payload["capability_claim"] is False
    assert "20 percent" not in dumped
    assert "divide(subtract" not in dumped
    assert "reference_answer" not in dumped
    assert "gold_program" not in dumped


def test_finance_run_loads_jsonl_row_by_index(tmp_path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps({"id": "row-0", "question": "First?"}),
                json.dumps({"id": "row-1", "question": "Second?", "context": "Context two."}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    args = build_parser().parse_args(["--row-jsonl", str(path), "--index", "1", "--dry-run"])

    row = load_row_from_args(args)

    assert row["id"] == "row-1"
    assert row["question"] == "Second?"
    assert row["context"] == "Context two."


def test_finance_run_main_writes_dry_run_output_without_gold(tmp_path) -> None:
    output = tmp_path / "finance-run.json"
    row = {
        "id": "fb-dry",
        "dataset": "financebench",
        "question": "Compute capex divided by revenue.",
        "context": "Revenue 10 and capex 1.",
        "reference": "10%",
        "rubric": {"answer": "10%"},
    }

    code = main(["--row-json", json.dumps(row), "--dry-run", "--output", str(output)])
    payload = json.loads(output.read_text(encoding="utf-8"))
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert code == 0
    assert payload["status"] == "dry_run"
    assert payload["task"]["excluded_gold_reference_field_count"] == 2
    assert "10%" not in dumped
    assert "rubric" not in dumped


def test_finance_run_closure_audit_is_no_provider_no_gold(tmp_path) -> None:
    output = tmp_path / "closure-audit.json"
    row = {
        "id": "finqa-closure-cli",
        "dataset": "finqa",
        "question": "What is the average payment volume per transaction?",
        "oracle_context": "Payment volume was 637 and total transactions were 5.0.",
        "answer": "127.40",
        "gold_program": "divide(637,5.0)",
    }

    code = main(
        [
            "--row-json",
            json.dumps(row),
            "--benchmark-family",
            "finqa",
            "--closure-audit",
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert code == 0
    assert payload["schema"] == "holo.kernel_v4.finance_question_closure_audit.v1"
    assert payload["status"] == "ok"
    assert payload["audit_mode"] == "no_network_fqa"
    assert "provided_context_fqa_finqa" in payload["workbench"]["selected_profile_families"]
    assert "127.40" not in dumped
    assert "divide(637" not in dumped
    assert "gold_program" not in dumped


def test_finance_run_closure_audit_batch_covers_rows_without_gold(tmp_path) -> None:
    rows = [
        {
            "id": "finqa-batch",
            "dataset": "finqa",
            "question": "What is the average payment volume per transaction?",
            "oracle_context": "Payment volume was 637 and total transactions were 5.0.",
            "answer": "127.40",
            "gold_program": "divide(637,5.0)",
        },
        {
            "id": "fb-batch",
            "dataset": "financebench",
            "question": "Is 3M capital intensive based on FY2022 capex PP&E assets revenue ROA?",
            "gold_answer": "No.",
            "ticker": "MMM",
            "fiscal_year": 2022,
        },
    ]
    path = tmp_path / "rows.jsonl"
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    args = build_parser().parse_args(
        [
            "--row-jsonl",
            str(path),
            "--closure-audit",
            "--allow-network",
            "--limit",
            "2",
        ]
    )

    payload = asyncio.run(run_finance_cli(args))
    dumped = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    assert payload["schema"] == "holo.kernel_v4.finance_closure_audit_batch.v1"
    assert payload["status"] == "ok"
    assert payload["item_count"] == 2
    assert payload["ok_count"] == 2
    assert payload["failed_count"] == 0
    assert payload["benchmark_progress_claim"] is False
    assert payload["capability_claim"] is False
    assert payload["gold_reference_material_included"] is False
    assert payload["items"][0]["audit_mode"] == "no_network_fqa"
    assert "provided_context_fqa_finqa" in payload["items"][0]["selected_profile_families"]
    assert payload["items"][1]["audit_mode"] == "full"
    assert "capital_intensity_asset_intensity" in payload["items"][1]["selected_profile_families"]
    assert "127.40" not in dumped
    assert "divide(637" not in dumped
    assert "gold_answer" not in dumped


def test_finance_run_requires_exactly_one_input_source() -> None:
    args = build_parser().parse_args(["--row-json", "{}", "--row-file", "rows.json", "--dry-run"])

    try:
        load_row_from_args(args)
    except ValueError as exc:
        assert "exactly one" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_transcript_preview_is_bounded_and_includes_tool_metadata() -> None:
    result = LoopResult(
        status="completed",
        answer="done",
        messages=(
            ChatMessage(role="assistant", content="using tool", tool_calls=(ToolCall(tool_call_id="c1", name="alpha.read", input={"q": "x"}),)),
            ChatMessage(role="tool", name="alpha.read", tool_call_id="c1", content="x" * 1000, metadata={"is_error": True}),
        ),
        events=(),
    )

    rows = _transcript_preview(result, max_chars=250)

    assert rows[0]["tool_calls"] == [{"tool_call_id": "c1", "name": "alpha.read", "input": {"q": "x"}}]
    assert rows[1]["name"] == "alpha.read"
    assert rows[1]["metadata"]["is_error"] is True
    assert len(rows[1]["content_preview"]) == 250
