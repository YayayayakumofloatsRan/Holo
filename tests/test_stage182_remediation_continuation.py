from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path

from holo_host import cli
from holo_host.evidence_action_remediation import build_evidence_action_remediation
from holo_host.kernel_metadata_sanitizer import assert_no_private_reasoning
from holo_host.live_remediation_loop import build_live_remediation_loop
from holo_host.stage135_i_state_topology import build_stage135_i_state_topology


def _stage182():
    assert importlib.util.find_spec("holo_host.live_remediation_continuation") is not None
    return importlib.import_module("holo_host.live_remediation_continuation")


def _remediation(issues: list[dict]) -> dict:
    return build_evidence_action_remediation(issues)


def test_continuation_executes_remaining_memory_after_first_web_round() -> None:
    stage182 = _stage182()
    remediation = _remediation(
        [
            {"issue_id": "src-1", "domain": "literature_research", "issue_type": "source_missing", "claim": "source"},
            {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "memory"},
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage182.run_live_remediation_continuation(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [{"title": "source", "url": "https://example.com/source", "snippet": "source"}],
        },
        memory_recall_fn=lambda query: {
            "memory_call_id": "mem:1",
            "status": "grounded",
            "selected_ids": ["m1"],
            "summary": "grounded memory",
            "confidence": 0.9,
        },
        max_rounds=2,
        actions_per_round=1,
        sufficiency_threshold=0.45,
    )

    assert report["schema"] == "holo.stage182.remediation_continuation.v1"
    assert report["status"] == "completed"
    assert report["round_count"] == 2
    assert report["executed_count"] == 2
    assert report["remaining_action_candidates"] == []
    assert report["canonical_stop_reason"] == "final_answer_ready"
    assert report["sufficiency"]["status"] in {"sufficient", "partial"}


def test_continuation_stops_at_round_budget_with_remaining_actions() -> None:
    stage182 = _stage182()
    remediation = _remediation(
        [
            {"issue_id": "src-1", "domain": "literature_research", "issue_type": "source_missing", "claim": "source"},
            {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "memory"},
            {"issue_id": "src-2", "domain": "literature_research", "issue_type": "period_mismatch", "claim": "scope"},
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage182.run_live_remediation_continuation(
        loop,
        stage178_evidence_action_remediation=remediation,
        network_enabled=True,
        web_search_fn=lambda query: {
            "query": query,
            "status": "ok",
            "provider": "mock",
            "results": [{"title": "source", "url": "https://example.com/source", "snippet": "source"}],
        },
        max_rounds=1,
        actions_per_round=1,
    )

    assert report["status"] == "budget_exhausted"
    assert report["canonical_stop_reason"] == "budget_exhausted"
    assert len(report["remaining_action_candidates"]) == 2
    assert report["next_action_required"] is True


def test_continuation_stops_on_missing_artifact_clarification() -> None:
    stage182 = _stage182()
    remediation = _remediation(
        [
            {"issue_id": "gpu-1", "domain": "gpu_experiment", "issue_type": "experiment_failed", "claim": "training succeeded"},
            {"issue_id": "mem-1", "domain": "agent_memory", "issue_type": "memory_unsupported", "claim": "memory"},
        ]
    )
    loop = build_live_remediation_loop(remediation)

    report = stage182.run_live_remediation_continuation(
        loop,
        stage178_evidence_action_remediation=remediation,
        repo_root=Path.cwd(),
        max_rounds=3,
        actions_per_round=1,
    )

    assert report["status"] == "blocked"
    assert report["canonical_stop_reason"] == "needs_user_clarification"
    assert report["round_count"] == 1
    assert "artifact_path_required" in json.dumps(report["rounds"], ensure_ascii=False)


def test_sufficiency_score_flags_weak_web_evidence() -> None:
    stage182 = _stage182()
    score = stage182.score_remediation_sufficiency(
        {
            "web_observation_ledger": [
                {
                    "status": "ok",
                    "source_urls": ["https://example.com/blog"],
                    "source_authority": {"status": "insufficient"},
                    "search_evidence": {"status": "weak", "evidence_score": 0.3},
                }
            ],
            "action_results": [{"status": "executed", "required_tool": "web_search"}],
        },
        threshold=0.72,
    )

    assert score["status"] == "insufficient"
    assert score["score"] < 0.72
    assert "weak_web_evidence" in score["missing_evidence"]


def test_sufficiency_score_accepts_memory_and_engineering_ledgers() -> None:
    stage182 = _stage182()
    score = stage182.score_remediation_sufficiency(
        {
            "memory_observation_ledger": [{"status": "grounded", "confidence": 0.9, "selected_ids": ["m1"]}],
            "engineering_action_ledger": [{"action_type": "file_read", "status": "ok", "files_read": ["runs/train.log"]}],
            "action_results": [
                {"status": "executed", "required_tool": "memory_recall"},
                {"status": "executed", "required_tool": "file_read"},
            ],
        },
        threshold=0.72,
    )

    assert score["status"] == "sufficient"
    assert score["score"] >= 0.72


def test_cli_writes_stage182_continuation_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "stage182_remediation_continuation.html"

    code = cli.main(["run-remediation-continuation", "--output", str(output), "--dry-run"])

    assert code == 0
    payload = json.loads(output.with_suffix(".json").read_text(encoding="utf-8"))
    assert payload["schema"] == "holo.stage182.remediation_continuation_bundle.v1"
    assert payload["status"] == "passed"


def test_stage135_topology_includes_stage182_continuation_node() -> None:
    topology = build_stage135_i_state_topology(
        user_text="stage182 continuation",
        stage182_remediation_continuation={
            "schema": "holo.stage182.remediation_continuation.v1",
            "status": "completed",
            "round_count": 2,
            "executed_count": 2,
            "canonical_stop_reason": "final_answer_ready",
        },
    )

    assert topology["metrics"]["remediation_continuation_node_count"] == 1
    assert topology["metrics"]["remediation_continuation_round_count"] == 2
    assert any(node["id"] == "stage182_remediation_continuation" for node in topology["nodes"])


def test_stage182_public_payload_has_no_hidden_reasoning() -> None:
    stage182 = _stage182()
    bundle = stage182.run_remediation_continuation_simulation(dry_run=True)

    ok, paths = assert_no_private_reasoning(bundle)

    assert ok, paths
    assert "reasoning_content" not in json.dumps(bundle, ensure_ascii=False)
