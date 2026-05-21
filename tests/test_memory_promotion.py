from __future__ import annotations

import json
from types import SimpleNamespace

from holo_host import cli
from holo_host.memory_promotion import plan_ready_candidates


class FakeRag:
    MATCH_REINFORCE_THRESHOLD = 0.82

    def __init__(self) -> None:
        self.candidate_rows = [
            {
                "id": "candidate-1",
                "kind": "preference",
                "text": "private candidate text",
                "tags": ["style"],
                "confidence": 0.93,
                "importance": 0.8,
                "last_seen_at": "2026-05-21T00:00:00Z",
                "explicit_user_signal": True,
            },
            {
                "id": "candidate-2",
                "kind": "noise",
                "text": "private skipped text",
                "confidence": 0.1,
                "importance": 0.1,
            },
        ]
        self.durable_rows = [{"id": "durable-1", "kind": "preference"}]

    def load_rows(self, store: str) -> list[dict]:
        if store == "candidate":
            return list(self.candidate_rows)
        if store == "durable":
            return list(self.durable_rows)
        return []

    def can_promote(self, row: dict) -> tuple[bool, str]:
        return (row["id"] == "candidate-1", "low_confidence")

    def find_best_match(self, durable_rows: list[dict], kind: str, text: str, tags: list[str]) -> tuple[float, dict | None]:
        return 0.91, durable_rows[0]


def test_plan_ready_candidates_is_redacted_and_non_mutating() -> None:
    rag = FakeRag()

    report = plan_ready_candidates(rag, limit=8)

    assert report["status"] == "plan"
    assert report["dry_run"] is True
    assert report["candidate_count"] == 2
    assert report["would_apply"] == [
        {
            "candidate_id": "candidate-1",
            "action": "merge_existing",
            "target_id": "durable-1",
            "match_score": 0.91,
            "kind": "preference",
            "confidence": 0.93,
            "importance": 0.8,
            "explicit_user_signal": True,
        }
    ]
    assert report["would_skip"] == [{"candidate_id": "candidate-2", "reason": "low_confidence"}]
    assert "private candidate text" not in json.dumps(report, ensure_ascii=False)
    assert "private skipped text" not in json.dumps(report, ensure_ascii=False)


def test_promote_memory_cli_dry_run_uses_plan(monkeypatch, capsys) -> None:
    calls: list[str] = []

    class FakeMemory:
        def plan_ready_candidates(self, limit: int = 8) -> dict:
            calls.append(f"plan:{limit}")
            return {"status": "plan", "privacy": {"raw_text_included": False}}

        def promote_ready_candidates(self, limit: int = 8) -> dict:
            calls.append(f"write:{limit}")
            return {"status": "write"}

    monkeypatch.setattr(
        cli,
        "build_daemon",
        lambda config_path=None: SimpleNamespace(memory=FakeMemory(), config=SimpleNamespace(memory=SimpleNamespace(promote_batch_size=3))),
    )

    result = cli.main(["promote-memory", "--dry-run"])

    assert result == 0
    assert calls == ["plan:3"]
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "plan"
    assert payload["privacy"]["raw_text_included"] is False
