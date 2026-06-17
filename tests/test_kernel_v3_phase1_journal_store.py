import hashlib
import json
from pathlib import Path

from kernel_v3.journal import Journal, JournalStore


def _canonical_hash(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def test_journal_store_writes_canonical_jsonl_and_sqlite_index():
    journal_path = Path("kernel_v3/.test-phase1-journal.jsonl")
    index_path = Path("kernel_v3/.test-phase1-journal.sqlite")
    _unlink(journal_path, index_path)
    try:
        store = JournalStore(journal_path=journal_path, index_path=index_path)

        record = store.append(
            task_id="task-1",
            run_id="run-1",
            step_id="step-1",
            kind="observation",
            data={"z": 2, "a": {"nested": True}},
            event_ref="evt-1",
            action_ref="act-1",
            observation_ref="obs-1",
            feedback_ref=None,
            state_delta={"status": "observed"},
            artifact_refs=["artifact://obs-1"],
        )

        line = journal_path.read_text(encoding="utf-8").strip()
        decoded = json.loads(line)
        assert line == json.dumps(decoded, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert decoded["schema_version"] == JournalStore.SCHEMA_VERSION
        assert decoded["artifact_refs"] == ["artifact://obs-1"]
        assert decoded["payload_hash"] == _canonical_hash(decoded["data"])

        reloaded = JournalStore(journal_path=journal_path, index_path=index_path)
        assert reloaded.records(task_id="task-1") == [record]
        assert reloaded.records(kind="observation") == [record]
        assert reloaded.records(run_id="run-1", kind="observation") == [record]
    finally:
        _unlink(journal_path, index_path)


def test_journal_store_replaces_lone_surrogates_before_hashing_and_writing():
    journal_path = Path("kernel_v3/.test-phase1-surrogate-journal.jsonl")
    _unlink(journal_path)
    try:
        store = JournalStore(journal_path=journal_path)

        record = store.append(
            task_id="task-surrogate",
            run_id="run-surrogate",
            step_id=None,
            kind="chat_turn",
            data={"text": "bad\udce6", "nested": {"key\ud800": "value\udfff"}},
        )

        line = journal_path.read_text(encoding="utf-8").strip()
        decoded = json.loads(line)
        assert record.data["text"] == "bad?"
        assert decoded["data"]["text"] == "bad?"
        assert decoded["data"]["nested"]["key?"] == "value?"
        assert decoded["payload_hash"] == _canonical_hash(decoded["data"])
    finally:
        _unlink(journal_path)


def test_journal_store_skips_partial_jsonl_rows_and_records_load_warning(tmp_path: Path):
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"
    seed = JournalStore(journal_path=journal_path)
    record = seed.append(
        task_id="task-1",
        run_id="run-1",
        step_id=None,
        kind="event",
        data={"ok": True},
    )
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write('{"schema_version":1,"record_id":"partial"\n')

    reloaded = JournalStore(journal_path=journal_path, index_path=index_path)

    assert reloaded.records() == [record]
    assert reloaded.load_warnings[0]["line_number"] == 2
    assert reloaded.load_warnings[0]["error"] == "JSONDecodeError"
    assert "partial" in reloaded.load_warnings[0]["preview"]


def test_phase0_journal_alias_uses_durable_store():
    journal_path = Path("kernel_v3/.test-phase1-journal-alias.jsonl")
    _unlink(journal_path)
    try:
        journal = Journal(journal_path)

        record = journal.append(
            task_id="task-1",
            run_id="run-1",
            step_id=None,
            kind="event",
            data={"event_id": "evt-1"},
            event_ref="evt-1",
        )

        assert record.schema_version == JournalStore.SCHEMA_VERSION
        assert Journal(journal_path).records(task_id="task-1") == [record]
    finally:
        _unlink(journal_path)


def _unlink(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink()
