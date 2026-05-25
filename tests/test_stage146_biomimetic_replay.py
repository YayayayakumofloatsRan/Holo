from __future__ import annotations

import json
from pathlib import Path

import pytest

from holo_host import cli
from holo_host.config import load_config
from holo_host.models import IncomingMessage, OutgoingMessage
from holo_host.stage146_benchmark_bundle import (
    BENCHMARK_LABELS,
    build_biomimetic_benchmark_bundle,
    run_biomimetic_benchmark,
)
from holo_host.stage146_biomimetic_replay import (
    build_biomimetic_replay,
    export_biomimetic_replay,
    load_replay_rows_from_store,
    synthetic_replay_rows,
)
from holo_host.store import QueueStore


def _turn_metadata(*, duplicate: bool = False, unsupported: bool = False) -> dict[str, object]:
    stage142_status = "suppressed_duplicate" if duplicate else "passed"
    memory_alignment_status = "unsupported_memory_detail" if unsupported else "aligned"
    tool_status = "ungrounded_tool_claim" if unsupported else "grounded"
    return {
        "stage143_packet_budget": {
            "schema": "holo.stage143.packet_budget.v1",
            "packet_count": 2,
            "sent_count": 2,
            "skipped_count": 0,
            "continued_count": 1,
            "stop_reason": f"stage142:{stage142_status}" if duplicate else "deep_packet_completed",
            "total_estimated_tokens": 880,
            "total_elapsed_ms": 240,
            "packets": [
                {"packet_id": "packet_0_fast", "packet_type": "fast", "sent": True, "estimated_tokens": 320},
                {"packet_id": "packet_1_deep", "packet_type": "deep", "sent": True, "estimated_tokens": 560},
            ],
        },
        "tool_grounding": {"schema": "holo.tool_grounding.v1", "status": tool_status},
        "memory_grounding": {"schema": "holo.memory_grounding.v1", "status": "grounded"},
        "memory_alignment": {
            "schema": "holo.memory_alignment.v1",
            "status": memory_alignment_status,
            "claim_count": 1,
            "unsupported_claim_count": 1 if unsupported else 0,
            "aligned_claim_count": 0 if unsupported else 1,
        },
        "stage142_semantic_novelty": {
            "schema": "holo.stage142.semantic_novelty_gate.v1",
            "status": stage142_status,
            "candidate_count": 2,
            "emitted_count": 1 if duplicate else 2,
            "suppressed_count": 1 if duplicate else 0,
            "evaluations": [
                {"bubble_index": 0, "semantic_role": "answer", "novelty_score": 0.72, "should_emit": True},
                {"bubble_index": 1, "semantic_role": "answer", "novelty_score": 0.12 if duplicate else 0.62, "should_emit": not duplicate},
            ],
        },
        "stage144_context_economy": {
            "schema": "holo.stage144.context_economy.v1",
            "working_set_slots": [
                {"slot_id": "current:test", "slot_type": "current_user_constraint", "summary": "current request", "priority": 0.9},
                {"slot_id": "packet:test", "slot_type": "packet_budget", "summary": "two sent packets", "priority": 0.7},
            ],
            "context_sufficiency_score": 0.42 if unsupported else 0.82,
            "context_waste_score": 0.74 if duplicate else 0.22,
            "recommended_deep_policy": "memory_first" if unsupported else "keep",
            "shadow_only": True,
        },
        "stage145_outcome_appraisal": {
            "schema": "holo.stage145.outcome_appraisal.v1",
            "predicted_user_need": "grounded_memory_recall" if unsupported else "direct_answer_with_enough_context",
            "prediction_error": 0.68 if unsupported else 0.16,
            "observed_stage142_status": stage142_status,
            "observed_memory_alignment_status": memory_alignment_status,
            "observed_grounding_status": tool_status,
            "shadow_only": True,
        },
        "stage145_reaction_kernel_shadow": {
            "schema": "holo.stage145.reaction_kernel_shadow.v1",
            "kernel_delta_candidates": [
                {"parameter": "memory_trust", "delta": -0.08, "applied": False}
            ]
            if unsupported
            else [],
            "shadow_only": True,
            "applied": False,
        },
        "reply_bubbles": [
            {"text": "Fast answer.", "purpose": "fast_reaction"},
            {"text": "Deeper answer with concrete state.", "purpose": "deep_continuation"},
        ],
    }


def test_replay_builds_multi_turn_rows_from_stored_metadata(tmp_path: Path) -> None:
    config = load_config(repo_root=tmp_path)
    store = QueueStore(config.runtime.db_path)
    store.initialize()
    try:
        inbound = store.record_inbound(
            IncomingMessage(
                message_id="stage146-in-1",
                thread_key="cli:Stage146Fixture",
                subject="Stage146",
                sender_email="operator@example.test",
                sender_name="Operator",
                body_text="show the replay trajectory",
                channel="holo_cli",
            )
        )
        store.record_outbound(
            thread_id=int(inbound["thread"]["id"]),
            contact_id=int(inbound["contact"]["id"]),
            remote_message_id="stage146-out-1",
            outgoing=OutgoingMessage(
                recipient_email="operator@example.test",
                subject="Stage146",
                body_text="Fast answer.\nDeeper answer with concrete state.",
                thread_key="cli:Stage146Fixture",
                channel="holo_cli",
                metadata=_turn_metadata(),
            ),
        )

        rows = load_replay_rows_from_store(store, thread_key="cli:Stage146Fixture", limit=20, channel="holo_cli")
    finally:
        store.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["turn_id"]
    assert row["input_summary"] == "show the replay trajectory"
    assert row["packet_budget"]["sent_count"] == 2
    assert row["semantic_novelty"]["status"] == "passed"
    assert row["context_economy"]["working_set_slots"]
    assert row["outcome_appraisal"]["prediction_error"] == 0.16
    assert len(row["visible_bubbles"]) == 2


def test_replay_exports_html_json_and_jsonl(tmp_path: Path) -> None:
    output = tmp_path / "artifacts" / "stage146" / "replay.html"
    report = export_biomimetic_replay(
        thread_key="cli:Stage146Fixture",
        limit=20,
        output=output,
        dry_run=True,
        repo_root=tmp_path,
    )

    assert Path(report["paths"]["html"]).exists()
    assert Path(report["paths"]["json"]).exists()
    assert Path(report["paths"]["jsonl"]).exists()
    assert report["row_count"] >= 3
    payload = json.loads(Path(report["paths"]["json"]).read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage146.biomimetic_replay.v1"
    assert payload["rows"][0]["packet_budget"]
    assert "Reaction-Kernel Delta" in Path(report["paths"]["html"]).read_text(encoding="utf-8")


def test_benchmark_computes_metrics_for_all_baseline_labels() -> None:
    bundle = build_biomimetic_benchmark_bundle()

    labels = [condition["label"] for condition in bundle["conditions"]]
    assert labels == list(BENCHMARK_LABELS)
    for condition in bundle["conditions"]:
        metrics = condition["metrics"]
        assert {
            "semantic_novelty",
            "duplicate_rate",
            "unsupported_claim_rate",
            "memory_alignment_support_rate",
            "context_waste",
            "packet_cost_estimate",
            "prediction_error",
            "correction_adoption_proxy",
        } <= set(metrics)


def test_full_stack_beats_fixed_two_bubble_on_duplicate_rate() -> None:
    bundle = build_biomimetic_benchmark_bundle()
    by_label = {condition["label"]: condition["metrics"] for condition in bundle["conditions"]}

    assert by_label["full current RK-CSM stack"]["duplicate_rate"] < by_label["fixed two-bubble baseline"]["duplicate_rate"]


def test_unsupported_memory_and_tool_claims_are_counted() -> None:
    replay = build_biomimetic_replay(
        synthetic_replay_rows("cli:Stage146Fixture", limit=4)
        + [
            {
                "turn_id": "turn_unsupported",
                "time": "2026-05-24T00:00:00Z",
                "input_summary": "unsupported test",
                "packet_budget": {},
                "tool_grounding": {"status": "ungrounded_tool_claim"},
                "memory_grounding": {"status": "grounded"},
                "memory_alignment": {"status": "unsupported_memory_detail", "unsupported_claim_count": 1},
                "semantic_novelty": {"status": "blocked_ungrounded_claim", "suppressed_count": 1},
                "context_economy": {"context_waste_score": 0.66},
                "outcome_appraisal": {"prediction_error": 0.72},
                "reaction_kernel_shadow": {"kernel_delta_candidates": []},
                "visible_bubbles": [],
                "state_delta_summary": "unsupported claims counted",
            }
        ],
        thread_key="cli:Stage146Fixture",
        source="test_fixture",
    )

    assert replay["summary"]["unsupported_tool_claim_count"] >= 1
    assert replay["summary"]["unsupported_memory_claim_count"] >= 1


def test_cli_dry_run_works_without_provider_network_or_wechat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.chdir(tmp_path)

    replay_code = cli.main(
        [
            "export-biomimetic-replay",
            "--thread-key",
            "cli:Stage146Fixture",
            "--limit",
            "20",
            "--output",
            "artifacts/stage146/replay.html",
            "--dry-run",
        ]
    )
    benchmark_code = cli.main(
        [
            "run-biomimetic-benchmark",
            "--output",
            "artifacts/stage146/benchmark.html",
            "--dry-run",
        ]
    )

    assert replay_code == 0
    assert benchmark_code == 0
    assert (tmp_path / "artifacts" / "stage146" / "replay.html").exists()
    assert (tmp_path / "artifacts" / "stage146" / "benchmark.html").exists()
    assert "provider" not in capsys.readouterr().err.lower()


def test_public_artifact_paths_are_safe(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outside"):
        export_biomimetic_replay(
            thread_key="cli:Stage146Fixture",
            output=tmp_path / ".." / "outside.html",
            dry_run=True,
            repo_root=tmp_path,
        )

    with pytest.raises(ValueError, match="outside"):
        run_biomimetic_benchmark(
            output=tmp_path / ".." / "outside.html",
            dry_run=True,
            repo_root=tmp_path,
        )
