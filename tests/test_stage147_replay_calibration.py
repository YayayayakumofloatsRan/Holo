from __future__ import annotations

import json
from pathlib import Path

import pytest

from holo_host import cli
from holo_host.stage146_biomimetic_replay import synthetic_replay_rows
from holo_host.stage147_replay_calibration import (
    STAGE147_SCHEMA,
    build_stage147_replay_calibration,
    evaluate_replay_calibration,
)


def _row(
    *,
    turn_id: str,
    recommendation: str,
    novelty_status: str = "passed",
    waste: float = 0.22,
    tool_status: str = "grounded",
    memory_alignment_status: str = "aligned",
    deltas: list[str] | None = None,
) -> dict[str, object]:
    return {
        "turn_id": turn_id,
        "time": "2026-05-24T00:00:00Z",
        "input_summary": turn_id,
        "packet_budget": {"stop_reason": f"stage142:{novelty_status}" if novelty_status != "passed" else "deep_packet_completed"},
        "tool_grounding": {"status": tool_status},
        "memory_grounding": {"status": "grounded"},
        "memory_alignment": {"status": memory_alignment_status},
        "semantic_novelty": {"status": novelty_status, "suppressed_count": 1 if novelty_status == "suppressed_duplicate" else 0},
        "context_economy": {"recommended_deep_policy": recommendation, "context_waste_score": waste},
        "outcome_appraisal": {"prediction_error": 0.7 if novelty_status != "passed" else 0.14},
        "reaction_kernel_shadow": {
            "kernel_delta_candidates": [
                {"parameter": parameter, "delta": 0.06 if parameter != "memory_trust" else -0.07, "applied": False}
                for parameter in (deltas or [])
            ],
            "shadow_only": True,
            "applied": False,
        },
        "visible_bubbles": [],
        "state_delta_summary": "",
    }


def _candidate(report: dict[str, object], target: str) -> dict[str, object] | None:
    for item in report["promotion_candidates"]:  # type: ignore[index]
        if item["target"] == target:  # type: ignore[index]
            return dict(item)
    return None


def test_synthetic_replay_supports_skip_after_duplicate_suppression() -> None:
    report = build_stage147_replay_calibration(
        [
            _row(
                turn_id="duplicate_skip",
                recommendation="skip",
                novelty_status="suppressed_duplicate",
                waste=0.74,
                deltas=["novelty_threshold"],
            )
        ]
    )

    assert report["schema"] == STAGE147_SCHEMA
    assert report["do_not_apply_live"] is True
    assert report["policy_recommendation_accuracy"] == 1.0
    finding = report["calibration_findings"][0]
    assert finding["support_status"] == "supported"
    assert finding["stage144_recommendation"] == "skip"
    assert _candidate(report, "packet_policy:skip")["support_count"] == 1  # type: ignore[index]


def test_synthetic_replay_supports_memory_first_after_unsupported_memory_detail() -> None:
    report = build_stage147_replay_calibration(
        [
            _row(
                turn_id="memory_first",
                recommendation="memory_first",
                memory_alignment_status="unsupported_memory_detail",
                deltas=["memory_trust", "correction_sensitivity"],
            )
        ]
    )

    assert report["policy_recommendation_accuracy"] == 1.0
    assert _candidate(report, "packet_policy:memory_first")["support_count"] == 1  # type: ignore[index]
    assert _candidate(report, "reaction_kernel_parameter:memory_trust")["support_count"] == 1  # type: ignore[index]
    assert _candidate(report, "reaction_kernel_parameter:correction_sensitivity")["support_count"] == 1  # type: ignore[index]


def test_synthetic_replay_supports_tool_first_after_ungrounded_tool_claim() -> None:
    report = build_stage147_replay_calibration(
        [
            _row(
                turn_id="tool_first",
                recommendation="tool_first",
                tool_status="ungrounded_tool_claim",
                deltas=["tool_preference"],
            )
        ]
    )

    assert report["policy_recommendation_accuracy"] == 1.0
    assert _candidate(report, "packet_policy:tool_first")["support_count"] == 1  # type: ignore[index]
    assert report["calibration_findings"][0]["support_status"] == "supported"


def test_clean_rows_do_not_produce_strong_promotion_candidates() -> None:
    report = build_stage147_replay_calibration(
        [
            _row(turn_id="clean_1", recommendation="keep"),
            _row(turn_id="clean_2", recommendation="keep"),
        ]
    )

    assert report["policy_recommendation_accuracy"] == 0.0
    assert report["kernel_delta_support_rate"] == 0.0
    assert report["promotion_candidates"] == []
    assert {finding["support_status"] for finding in report["calibration_findings"]} == {"inconclusive"}


def test_reaction_kernel_delta_support_rate_is_computed() -> None:
    report = build_stage147_replay_calibration(
        [
            _row(turn_id="delta_supported", recommendation="skip", novelty_status="suppressed_duplicate", deltas=["novelty_threshold"]),
            _row(turn_id="delta_counterexample", recommendation="keep", deltas=["verbosity_bias"]),
        ]
    )

    assert report["kernel_delta_support_rate"] == 0.5
    assert _candidate(report, "reaction_kernel_parameter:novelty_threshold")["support_count"] == 1  # type: ignore[index]
    assert _candidate(report, "reaction_kernel_parameter:verbosity_bias") is None


def test_cli_dry_run_writes_html_json_jsonl_without_live_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_config", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("load_config should not run")))
    monkeypatch.setattr(cli, "QueueStore", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("QueueStore should not run")))

    exit_code = cli.main(
        [
            "evaluate-replay-calibration",
            "--output",
            "artifacts/stage147/stage147_calibration.html",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    html_path = tmp_path / "artifacts" / "stage147" / "stage147_calibration.html"
    json_path = tmp_path / "artifacts" / "stage147" / "stage147_calibration.json"
    jsonl_path = tmp_path / "artifacts" / "stage147" / "stage147_calibration.jsonl"
    assert html_path.exists()
    assert json_path.exists()
    assert jsonl_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema"] == STAGE147_SCHEMA
    assert payload["do_not_apply_live"] is True
    assert "shadow-only" in html_path.read_text(encoding="utf-8").lower()


def test_missing_replay_json_uses_deterministic_stage146_synthetic_rows(tmp_path: Path) -> None:
    output = tmp_path / "artifacts" / "stage147" / "missing_replay.html"
    report = evaluate_replay_calibration(
        replay_json=tmp_path / "missing.json",
        output=output,
        dry_run=False,
        repo_root=tmp_path,
    )

    assert report["row_count"] == len(synthetic_replay_rows("cli:Stage146Fixture", limit=20))
    assert Path(report["paths"]["html"]).exists()
    assert report["do_not_apply_live"] is True
