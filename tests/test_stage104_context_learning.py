from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import holo_memory_library.rag_memory as rm

from holo_host import cli
from holo_host.stage104_context_learning import (
    inject_stage104_context,
    stage104_candidate_plan,
    stage104_context_learning_report,
    stage104_context_packet,
)


BROAD_RECALL_QUERY = "\u56de\u5fc6\u4efb\u4f55\u4e8b\u60c5\uff1f"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _seed_stage104_repo(root: Path) -> None:
    memory_dir = root / "holo_memory_library" / "memories"
    _write_jsonl(
        memory_dir / "memory_store.jsonl",
        [
            {
                "id": "memory-1",
                "kind": "summary",
                "text": "old durable memory",
                "created_at": "2026-04-07T00:00:00Z",
                "tags": ["old"],
            }
        ],
    )
    _write_jsonl(
        memory_dir / "conversation_archive.jsonl",
        [
            {
                "id": "archive-1",
                "created_at": "2026-05-21T10:00:00Z",
                "channel": "holo_cli",
                "thread_key": "holo_cli:main",
                "user_text": "Stage100+ biomimetic agent work needs semantic space, topology, affective components, and visualization.",
                "reply_text": "The complex network and semantic vector changes must become visible.",
            },
            {
                "id": "archive-2",
                "created_at": "2026-05-21T11:00:00Z",
                "channel": "holo_cli",
                "thread_key": "holo_cli:main",
                "user_text": "Provider API calls are stateless context packets, so local context learning and compression are mandatory.",
                "reply_text": "Working memory should be filtered into long-term memory.",
            },
            {
                "id": "archive-3",
                "created_at": "2026-05-21T12:00:00Z",
                "channel": "holo_cli",
                "thread_key": "holo_cli:main",
                "user_text": "RAG is poor because durable semantic memory has not consolidated the real project direction.",
                "reply_text": "Broad recall must stop echoing only the most recent test question.",
            },
        ],
    )
    _write_jsonl(
        memory_dir / "working_store.jsonl",
        [
            {
                "id": "working-1",
                "created_at": "2026-05-21T13:00:00Z",
                "text": "Stage104 should build the compression gate from working memory into durable semantic memory.",
                "tags": ["stage104", "context_learning"],
            }
        ],
    )
    _write_jsonl(
        memory_dir / "thought_stream.jsonl",
        [
            {
                "id": "thought-1",
                "created_at": "2026-05-21T14:00:00Z",
                "text": "A conscious-like system may have high-dimensional attractors and special semantic topology.",
                "motif": "semantic_attractor",
            }
        ],
    )


def test_stage104_extracts_context_attractors_and_durability_gap(tmp_path: Path) -> None:
    _seed_stage104_repo(tmp_path)

    report = stage104_context_learning_report(tmp_path, query=BROAD_RECALL_QUERY, recent_limit=16)
    labels = {item["label"] for item in report["attractors"]}
    lines = "\n".join(report["prompt_lines"])

    assert report["schema"] == "holo.stage104.context_learning.v1"
    assert report["stage"] == 104
    assert report["durability_gap"]["status"] == "critical"
    assert report["durability_gap"]["staleness_days"] >= 40
    assert {"project_stage", "memory_consolidation", "provider_context_learning", "biomimetic_topology"} <= labels
    assert "Stage100+" in lines
    assert "durable semantic memory" in lines


def test_stage104_candidate_plan_writes_context_attractor_candidates(tmp_path: Path) -> None:
    _seed_stage104_repo(tmp_path)

    dry_run = stage104_candidate_plan(tmp_path, apply=False, query=BROAD_RECALL_QUERY)
    assert dry_run["dry_run"] is True
    assert dry_run["would_apply"]
    assert not (tmp_path / "holo_memory_library" / "memories" / "candidate_store.jsonl").exists()

    applied = stage104_candidate_plan(tmp_path, apply=True, query=BROAD_RECALL_QUERY)
    candidate_rows = [
        json.loads(line)
        for line in (tmp_path / "holo_memory_library" / "memories" / "candidate_store.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert applied["dry_run"] is False
    assert applied["applied_count"] >= 3
    assert {row["kind"] for row in candidate_rows} == {"context_attractor"}
    assert all("stage104" in row["tags"] for row in candidate_rows)
    assert any("Stage100+" in row["text"] for row in candidate_rows)
    assert "context_attractor" in rm.PROMPT_MEMORY_KINDS
    assert any(rm.can_promote(row)[0] for row in candidate_rows)


def test_stage104_context_packet_injects_attractors_before_recent_echoes(tmp_path: Path) -> None:
    _seed_stage104_repo(tmp_path)
    context_packet = stage104_context_packet(tmp_path, query=BROAD_RECALL_QUERY, limit=4)
    packet = {
        "thread_recall_lines": ["user: recall anything | holo: you just asked the same recall test"],
        "selected_memory_ids": ["archive:recent-echo"],
    }

    injected = inject_stage104_context(packet, context_packet)

    assert injected["stage104"]["context_learning_visible"] is True
    assert injected["thread_recall_lines"][0].startswith("Stage104 attractor:")
    assert "Stage100+" in injected["thread_recall_lines"][0]
    assert "archive:recent-echo" in injected["selected_memory_ids"]
    assert any(item.startswith("stage104:") for item in injected["selected_memory_ids"])


def test_stage104_cli_dry_run_dispatches_report(monkeypatch, capsys, tmp_path: Path) -> None:
    _seed_stage104_repo(tmp_path)
    monkeypatch.setattr(
        cli,
        "load_config",
        lambda config_path=None, repo_root=None: SimpleNamespace(runtime=SimpleNamespace(repo_root=tmp_path)),
    )

    result = cli.main(["stage104-context-learning", "--dry-run", "--query", BROAD_RECALL_QUERY])

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["stage"] == 104
    assert payload["dry_run"] is True
    assert payload["candidate_plan"]["would_apply"]
