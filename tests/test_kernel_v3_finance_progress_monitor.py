from __future__ import annotations

import json
from types import SimpleNamespace

from kernel_v3.cli import _finance_progress_command_from_path, _render_finance_progress
from kernel_v3.contracts import LedgerRecord


def _record_payload(record_id: str, task_id: str, kind: str, data: dict[str, object]) -> dict[str, object]:
    return LedgerRecord(
        schema_version=1,
        record_id=record_id,
        task_id=task_id,
        run_id="run-1",
        step_id="step-1",
        kind=kind,
        data=data,
        recorded_at_ms=1,
        event_ref=None,
        action_ref=None,
        observation_ref=None,
        feedback_ref=None,
        state_delta={},
        artifact_refs=[],
        payload_hash=f"hash-{record_id}",
    ).to_dict()


def test_finance_progress_uses_tail_scan_and_run_root_status(tmp_path) -> None:
    journal = tmp_path / "global.jsonl"
    old_line = json.dumps(
        _record_payload("ledger-old", "task-old", "chat_turn", {"thread_id": "finance-bench-old-item"}),
        ensure_ascii=False,
        sort_keys=True,
    )
    request = _record_payload(
        "ledger-1",
        "task-new",
        "processor_request",
        {
            "thread_id": "finance-bench-0001-item",
            "request_id": "request-1",
            "task_type": "task.compile",
            "prompt": {"chars": 1234},
        },
    )
    slot_frame = _record_payload(
        "ledger-2",
        "task-new",
        "slot_frame",
        {"thread_id": "finance-bench-0001-item", "task_type": "disclosure_analysis", "missing_slots": []},
    )
    journal.write_text(
        old_line
        + "\n"
        + ("x" * 8192)
        + "\n"
        + json.dumps(request, ensure_ascii=False, sort_keys=True)
        + "\n"
        + json.dumps(slot_frame, ensure_ascii=False, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    run_root = tmp_path / "run"
    (run_root / "http-cache" / "a").mkdir(parents=True)
    (run_root / "http-cache" / "a" / "body.txt").write_text("sec filing", encoding="utf-8")
    (run_root / "results.jsonl").write_text(json.dumps({"status": "passed"}) + "\n", encoding="utf-8")
    (run_root / "summary.json").write_text(
        json.dumps(
            {
                "item_count": 1,
                "passed_count": 1,
                "failed_count": 0,
                "pass_rate": 1.0,
                "average_total_tokens": 448778,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    payload = _finance_progress_command_from_path(
        SimpleNamespace(
            journal=str(journal),
            task_id=None,
            thread_id=None,
            thread_prefix="finance-bench-0001",
            tail_bytes=4096,
            run_root=str(run_root),
            limit_events=4,
        )
    )

    assert payload["status"] == "ok"
    assert payload["task_id"] == "task-new"
    assert payload["tail_scan"]["tail_truncated"] is True
    assert payload["open_processor"]["processor"] == "task.compile"
    assert payload["run_status"]["files"]["results_jsonl"]["line_count"] == 1
    assert payload["run_status"]["files"]["summary_json"]["summary"]["passed_count"] == 1
    assert payload["run_status"]["files"]["http_cache"]["file_count"] == 1

    rendered = _render_finance_progress(payload)
    assert "run_root=" in rendered
    assert "open_processor=task.compile" in rendered
    assert "avg_tokens=448778" in rendered
