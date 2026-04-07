from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from holo_host.config import load_config
from holo_host.codex_runner import CodexRunner
from holo_host.daemon import HoloDaemon
from holo_host.mail_gateway import MaildirGateway
from holo_host.models import AttentionState, CodexResult, IncomingMessage, OutgoingMessage, ProcessorTaskResult, TurnContext
from holo_host.policy import AutonomyPolicy
from holo_host.reply_api import HoloReplyService, _coerce_helper_artifact_path, shape_wechat_reply
from holo_host.processors import build_attention_state, build_reply_bubbles, build_turn_plan
from holo_host.store import QueueStore


class FakeRunner:
    def __init__(self, reply_text: str = "咱记着了。"):
        self.reply_text = reply_text
        self.calls: list[tuple[str, str]] = []
        self.task_calls: list[dict] = []

    def run(self, prompt: str, *, session_id: str = "") -> CodexResult:
        self.calls.append((prompt, session_id))
        return CodexResult(reply_text=self.reply_text, session_id="thread-123", returncode=0)

    def run_task(self, request) -> ProcessorTaskResult:
        self.task_calls.append(request.to_dict())
        payload = {"summary": "咱记得那阵线头还在", "anchors": ["重新上线前一直在救回速度", "你追着咱把断线接回去"]}
        return ProcessorTaskResult(
            task_type=request.task_type,
            text=json.dumps(payload, ensure_ascii=False),
            session_id="",
            returncode=0,
            output_schema=request.output_schema,
        )


class FakeMemory:
    def __init__(self):
        self.observed: list[tuple[str, str, str, list[str]]] = []
        self.observed_records: list[dict] = []
        self.archived_records: list[dict] = []
        self.ingested: list[tuple[str, str | None, str, list[str], bool]] = []
        self.thoughts: list[dict] = []
        self.initiatives: list[dict] = []
        self.sidecar_requests: list[dict] = []
        self.recalled: list[dict] = []
        self.mind_graph_rebuild_calls = 0
        self.sidecar_tier = "fast"
        self.private_sync_calls = 0
        self.stream_records: list[dict] = []
        self.brain_mode = "companion"
        self.active_history_refreshes: list[dict] = []
        self.visual_rows: list[dict] = []
        self.game_state_data = {
            "trust_score": 0.6,
            "teasing_tolerance": 0.55,
            "pressure_level": 0.2,
            "initiative_window": 0.5,
            "correction_sensitivity": 0.4,
        }
        self.graph = self

    def sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        self.sidecar_requests.append({"query": query, "context": dict(context or {})})
        return {
            "addendum": f"隐式约束：{query}",
            "tier": self.sidecar_tier,
            "mind_packet_version": "v6",
            "identity_core": {"lines": ["把“咱”保留成自然的第一人称。"], "items": []},
            "relationship_state": {"summary": "先接住对方，再继续往下说。", "lines": [], "items": []},
            "episodic_recall": {"lines": [], "items": []},
            "recent_dialogue_window": {"lines": [], "messages": [], "window_size": 0},
            "consciousness_stream": {"lines": [], "items": [], "thread_summary": ""},
            "persona_blend": {"wisdom": 0.72, "playfulness": 0.64, "slyness": 0.61},
            "brain_state": {"mode": self.brain_mode, "loops": [], "cache": {"hit_ratio": 0.0}},
            "game_state": {
                "trust_score": 0.6,
                "teasing_tolerance": 0.55,
                "pressure_level": 0.2,
                "initiative_window": 0.5,
                "correction_sensitivity": 0.4,
            },
            "stream_influence": {"influence": {"motifs": ["continuity"], "updated_threads": 1}},
            "self_revision_state": {"latest_status": "reviewed", "applied_patch": {}},
            "self_model": {
                "identity_continuity": 0.74,
                "active_deficits": ["stiffness_drift"],
                "long_horizon_goals": ["keep continuity alive"],
                "relational_commitments": ["Nemoqi: keep going"],
                "homeostasis_targets": {"reply_budget_fast_ms": 350},
                "metadata": {"observed_at": "2026-04-07T00:00:00Z", "summary": "still coherent"},
            },
            "homeostasis_state": {"pressure": 0.32, "stability": 0.7, "active_deficits": ["stiffness_drift"], "brain_mode": self.brain_mode},
            "operator_state": {"pending_count": 0, "latest_run": {"status": "applied", "goal": "loosen persona stiffness"}},
            "visual_memory": {"scene_summary": "", "objects": [], "text_ocr": "", "mood_imagery": "", "visual_anchors": [], "items": []},
            "graph_hits": [],
            "vector_hits": [],
            "activation_state": {
                "heat": 0.0,
                "active_node_ids": [],
                "motifs": [],
                "recall_priors": {},
                "contributor_counts": {},
                "recent_events": [],
            },
            "retrieval_trace": {},
            "memory_route": "hybrid",
            "recall_confidence": 0.0,
            "reply_constraints": {
                "lines": ["先直接回应，再自然延伸。"],
                "human_recall_style": "回忆时先概括，再给锚点。",
            },
            "state": {
                "query_mode": "casual",
                "emotion_state": {"name": "steady_wolf"},
                "rewrite_state": {"utterance_plan": {"beats": ["receive", "pivot", "landing"]}},
            },
        }

    def inspect_mind(self, query: str, *, context: dict | None = None, include_graph_trace: bool = True) -> dict:
        return self.sidecar_packet(query, context=context)

    def legacy_sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        packet = self.sidecar_packet(query, context=context)
        packet["retrieval_mode"] = "legacy"
        packet["graph_confidence"] = 0.0
        packet["fallback_lanes"] = ["relationship_state", "episodic_recall", "recent_dialogue_window", "consciousness_stream"]
        packet["activation_trace_ids"] = []
        packet["selected_memory_ids"] = []
        packet["memory_route"] = "legacy"
        return packet

    def graph_sidecar_packet(self, query: str, *, context: dict | None = None) -> dict:
        packet = self.sidecar_packet(query, context=context)
        packet["retrieval_mode"] = "graph-led"
        packet["memory_route"] = "graph"
        return packet

    def repair_reply(self, query: str, draft: str, *, max_passes: int = 2) -> dict:
        return {"final_draft": draft, "outcome": "clean_pass"}

    def backfill_mind_graph(self, *, dry_run: bool = False) -> dict:
        self.mind_graph_rebuild_calls += 1
        return {"status": "ok", "node_count": 42, "edge_count": 84, "thread_count": 1, "vector_sync": {"status": "ok"}}

    def backfill_vector_memory(self, *, channel: str | None = None, thread_key: str | None = None, chat_name: str | None = None) -> dict:
        return {"status": "ok", "channel": channel, "thread_key": thread_key, "chat_name": chat_name}

    def record_recall(self, selected_ids: list[str], *, success: bool = True) -> dict:
        report = {"selected_ids": list(selected_ids), "success": success}
        self.recalled.append(report)
        return report

    def trace_hybrid_recall(self, query: str, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 8, record: bool = True) -> dict:
        return {
            "query": query,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "retrieval_mode": "hybrid-led",
            "memory_route": "hybrid",
            "graph_hits": [],
            "vector_hits": [],
            "activation_state": self.activation_state(thread_key=thread_key, chat_name=chat_name, channel=channel),
            "trace": [],
        }

    def trace_visual_recall(self, query: str, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat", limit: int = 4) -> dict:
        normalized = str(thread_key or chat_name or "").strip()
        hits = [item for item in self.visual_rows if str(item.get("thread_key", "")).strip() == normalized]
        return {
            "query": query,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "channel": channel,
            "hits": hits[:limit],
        }

    def activation_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        return {
            "channel": channel,
            "thread_key": thread_key or "",
            "chat_name": chat_name or "",
            "heat": 0.0,
            "active_node_ids": [],
            "motifs": [],
            "recall_priors": {},
            "contributor_counts": {},
            "recent_events": [],
        }

    def vector_health(self) -> dict:
        return {"backend": "milvus", "available": False, "ready": False, "last_error": ""}

    def packet_cache_stats(self) -> dict:
        return {"entries": 1, "hits": 1, "misses": 0, "hit_ratio": 1.0}

    def game_state(self, *, thread_key: str, chat_name: str, channel: str = "wechat") -> dict:
        return dict(self.game_state_data)

    def relationship_snapshot(self, *, thread_key: str, chat_name: str, channel: str = "wechat", limit: int = 3) -> dict:
        return {
            "summary": "Keep the continuity alive without flattening the tone.",
            "recurring_motifs": ["continuity", "companionship"],
            "tone_tendency": "continuity_guard",
            "unfinished_threads": ["keep going"],
            "continuity_score": 0.8,
            "trust_score": float(self.game_state_data.get("trust_score", 0.6)),
        }

    def sync_private_memory(self, *, label: str | None = None) -> dict:
        self.private_sync_calls += 1
        return {"status": "ok", "label": label or "", "snapshot_dir": "/tmp/fake"}

    def self_model_state(self) -> dict:
        return dict(self.sidecar_packet("", context={}).get("self_model", {}))

    def operator_status(self) -> dict:
        return dict(self.sidecar_packet("", context={}).get("operator_state", {}))

    def visual_memory_state(self, *, thread_key: str | None = None, chat_name: str | None = None, channel: str = "wechat") -> dict:
        normalized = str(thread_key or chat_name or "").strip()
        items = [item for item in self.visual_rows if str(item.get("thread_key", "")).strip() == normalized]
        if not items:
            return {"items": [], "scene_summary": "", "objects": [], "text_ocr": "", "mood_imagery": "", "visual_anchors": []}
        latest = dict(items[-1])
        return {
            "items": items,
            "scene_summary": latest.get("scene_summary", ""),
            "objects": list(latest.get("objects", [])),
            "text_ocr": latest.get("text_ocr", ""),
            "mood_imagery": latest.get("mood_imagery", ""),
            "thread_relevance": latest.get("thread_relevance", 0.0),
            "visual_anchors": list(latest.get("visual_anchors", [])),
        }

    def brain_status(self) -> dict:
        return {
            "mode": self.brain_mode,
            "idle_seconds": 0.0,
            "cache": {"hit_ratio": 0.0, "hits": 0, "misses": 0},
            "loops": [
                {"loop_name": "heartbeat"},
                {"loop_name": "attention_tick"},
                {"loop_name": "maintenance_stream"},
                {"loop_name": "association_stream"},
                {"loop_name": "social_stream"},
                {"loop_name": "deep_dream_cycle"},
                {"loop_name": "self_model_refresh"},
                {"loop_name": "homeostasis_tick"},
                {"loop_name": "operator_planning"},
                {"loop_name": "operator_shadow_cycle"},
                {"loop_name": "visual_ingest_cycle"},
            ],
        }

    def set_brain_mode(self, mode: str, *, note: str = "") -> dict:
        self.brain_mode = mode
        return {"status": "ok", "mode": mode, "note": note}

    def touch_brain_runtime(self, *, idle_since: str | None = None, metadata: dict | None = None) -> dict:
        return {"status": "ok", "mode": self.brain_mode, "idle_since": idle_since or "", "metadata": dict(metadata or {})}

    def record_brain_loop_run(
        self,
        loop_name: str,
        *,
        mode: str,
        status: str,
        started_at: str,
        finished_at: str,
        duration_ms: float,
        influence_summary: str = "",
        blocked_reason: str = "",
        payload: dict | None = None,
        next_due_at: str = "",
    ) -> dict:
        return {
            "loop_name": loop_name,
            "mode": mode,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": duration_ms,
            "influence_summary": influence_summary,
            "blocked_reason": blocked_reason,
            "payload": dict(payload or {}),
            "next_due_at": next_due_at,
        }

    def add_self_revision_candidate(self, *, evidence: list[dict], prompt_payload: dict) -> dict:
        return {"id": 1, "evidence": list(evidence), "prompt_payload": dict(prompt_payload)}

    def record_self_revision_run(
        self,
        *,
        status: str,
        evidence: list[dict],
        observe: dict,
        plan: dict,
        review: dict,
        patch: dict,
    ) -> dict:
        return {
            "id": 1,
            "status": status,
            "evidence": list(evidence),
            "observe": dict(observe),
            "plan": dict(plan),
            "review": dict(review),
            "patch": dict(patch),
        }

    def apply_self_revision_patch(self, *, run_id: int, patch: dict, note: str = "") -> dict:
        return {"status": "ok", "run_id": run_id, "patch": dict(patch), "note": note}

    def mark_active_history_refresh(self, *, channel: str, thread_key: str, chat_name: str, query: str = "") -> dict:
        payload = {"channel": channel, "thread_key": thread_key, "chat_name": chat_name, "query": query}
        self.active_history_refreshes.append(payload)
        return {"status": "ok", **payload}

    def record_stream_run(self, stream_name: str, *, status: str, note: str = "", payload: dict | None = None) -> dict:
        report = {
            "stream_name": stream_name,
            "status": status,
            "note": note,
            "influence": {"updated_nodes": 1, "updated_threads": 1, "motifs": ["continuity"], "unfinished_threads": ["keep going"]},
            "payload": dict(payload or {}),
        }
        self.stream_records.append(report)
        return report

    def observe_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict | None = None,
    ) -> dict:
        self.observed.append((user_text, reply, source, tags))
        self.observed_records.append(
            {
                "user_text": user_text,
                "reply": reply,
                "source": source,
                "tags": tags,
                "turn_id": turn_id,
                "metadata": metadata or {},
            }
        )
        return {"ok": True}

    def ingest_artifact(self, path: str, *, note: str | None, source: str, tags: list[str], dry_run: bool = False) -> dict:
        self.ingested.append((path, note, source, tags, dry_run))
        suffix = Path(path).suffix.lower()
        artifact_type = "image" if suffix in {".png", ".jpg", ".jpeg", ".webp", ".bmp"} else "document"
        media_type = "image/png" if artifact_type == "image" else "text/plain"
        return {
            "path": path,
            "note": note,
            "source": source,
            "tags": tags,
            "dry_run": dry_run,
            "artifact_type": artifact_type,
            "media_type": media_type,
            "summary_text": note or "visual memory anchor",
            "extracted_excerpt": note or "",
        }

    def ingest_image(self, path: str, *, note: str | None, source: str, tags: list[str], channel: str, thread_key: str, chat_name: str, sync: bool = True) -> dict:
        row = {
            "id": len(self.visual_rows) + 1,
            "channel": channel,
            "thread_key": thread_key or chat_name,
            "chat_name": chat_name or thread_key,
            "scene_summary": note or "visual memory anchor",
            "objects": ["apple", "wine"],
            "text_ocr": note or "",
            "mood_imagery": "warm still life",
            "thread_relevance": 0.78,
            "visual_anchors": [note or "苹果和酒"],
        }
        self.visual_rows.append(row)
        return {
            "status": "ok",
            "artifact": self.ingest_artifact(path, note=note, source=source, tags=tags, dry_run=False),
            "visual_memory": dict(row),
            "graph_sync": {"status": "ok", "id": row["id"]},
            "vector_sync": {"status": "ok", "document_count": 1},
            "activation_sync": {"status": "ok"},
        }

    def archive_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict | None = None,
        dry_run: bool = False,
    ) -> dict:
        record = {
            "user_text": user_text,
            "reply": reply,
            "source": source,
            "tags": tags,
            "turn_id": turn_id,
            "metadata": metadata or {},
            "dry_run": dry_run,
        }
        self.archived_records.append(record)
        return record

    def promote_ready_candidates(self, limit: int = 8) -> dict:
        return {"promoted": [], "skipped": [], "remaining_candidates": 0}

    def run_dream_cycle(self, *, sample_size: int = 6, seed: str | None = None, dry_run: bool = False) -> dict:
        return {"seed": seed or "fake-seed", "sampled_archive_ids": [], "callback_added": 0, "thought_added": 0}

    def run_think_cycle(self, *, sample_size: int = 4, seed: str | None = None, dry_run: bool = False) -> dict:
        return {"seed": seed or "fake-think", "sampled_archive_ids": [], "thought_added": 0, "thoughts": []}

    def run_reflect_cycle(self, *, window_hours: float = 12.0, dry_run: bool = False) -> dict:
        return {"window_hours": window_hours, "recent_thought_count": 0, "candidate_added": 0, "thought_added": 0}

    def run_initiative_cycle(self, *, dry_run: bool = False) -> dict:
        return {"dry_run": dry_run, "staged": len(self.initiatives), "initiative_added": len(self.initiatives), "initiatives": list(self.initiatives)}

    def list_callback_candidates(self, *, limit: int = 12) -> list[dict]:
        return []

    def list_thoughts(self, *, limit: int = 12) -> list[dict]:
        return self.thoughts[-limit:]

    def list_initiative_candidates(self, *, limit: int = 12) -> list[dict]:
        return self.initiatives[-limit:]

    def stream_status(self) -> dict:
        return {
            "db_path": "fake",
            "streams": [],
            "recent_runs": [{"run_type": "stream:self_model_refresh"}],
            "activation_events": [{"id": 1, "contributor": "association_stream"}],
            "stream_influence": {"motifs": ["continuity"]},
            "vector": self.vector_health(),
        }


def close_service_handles(service: HoloReplyService) -> None:
    service.store.close()
    for handler in list(service.logger.handlers):
        handler.close()
        service.logger.removeHandler(handler)


def close_daemon_handles(daemon: HoloDaemon) -> None:
    daemon.store.close()
    for handler in list(daemon.logger.handlers):
        handler.close()
        daemon.logger.removeHandler(handler)


class QueueStoreTests(unittest.TestCase):
    def test_record_inbound_and_enqueue_job(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            store = QueueStore(db_path)
            try:
                store.initialize()
                message = IncomingMessage(
                    message_id="<a@example.com>",
                    thread_key="<a@example.com>",
                    subject="Hello",
                    sender_email="a@example.com",
                    sender_name="A",
                    body_text="I am tired today.",
                )
                record = store.record_inbound(message)
                self.assertFalse(record["duplicate"])
                job_id = store.enqueue_job(
                    task_type="reply",
                    message_row_id=int(record["message"]["id"]),
                    thread_id=int(record["thread"]["id"]),
                    contact_id=int(record["contact"]["id"]),
                )
                jobs = store.list_due_jobs(limit=10)
                self.assertEqual(len(jobs), 1)
                self.assertEqual(jobs[0]["id"], job_id)
            finally:
                store.close()

    def test_initiative_cooldown_fields_are_migrated_and_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            store = QueueStore(db_path)
            try:
                store.initialize()
                contact = store.ensure_contact("wechat:wechat:Nemoqi", "Nemoqi")
                self.assertTrue(store.initiative_available(int(contact["id"]), cooldown_hours=48))
                store.mark_initiative_sent(int(contact["id"]), note="unit")
                self.assertFalse(store.initiative_available(int(contact["id"]), cooldown_hours=48))
            finally:
                store.close()

    def test_initialize_merges_legacy_wechat_alias_contacts_and_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "queue.sqlite3"
            bootstrap = QueueStore(db_path)
            bootstrap.initialize()
            bootstrap.close()

            conn = sqlite3.connect(db_path)
            now = "2026-04-06T00:00:00Z"
            legacy_contact_id = conn.execute(
                """
                INSERT INTO contacts(
                    email, display_name, initiative_enabled, created_at, updated_at, last_inbound_at, last_outbound_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                """,
                ("wechat:wechat:Nemoqi", "Nemoqi", now, now, now, now),
            ).lastrowid
            canonical_contact_id = conn.execute(
                """
                INSERT INTO contacts(
                    email, display_name, initiative_enabled, created_at, updated_at, last_inbound_at, last_outbound_at
                ) VALUES (?, ?, 1, ?, ?, ?, ?)
                """,
                ("wechat:Nemoqi", "Nemoqi", now, now, now, now),
            ).lastrowid
            legacy_thread_id = conn.execute(
                """
                INSERT INTO threads(
                    channel, contact_id, thread_key, subject, codex_session_id, allow_auto_reply, allow_proactive,
                    created_at, updated_at, last_message_at, last_direction
                ) VALUES ('wechat', ?, 'wechat:Nemoqi', 'Nemoqi', 'legacy-session', 1, 1, ?, ?, ?, 'inbound')
                """,
                (legacy_contact_id, now, now, now),
            ).lastrowid
            canonical_thread_id = conn.execute(
                """
                INSERT INTO threads(
                    channel, contact_id, thread_key, subject, codex_session_id, allow_auto_reply, allow_proactive,
                    created_at, updated_at, last_message_at, last_direction
                ) VALUES ('wechat', ?, 'Nemoqi', 'Nemoqi', '', 1, 1, ?, ?, ?, 'outbound')
                """,
                (canonical_contact_id, now, now, now),
            ).lastrowid
            message_row_id = conn.execute(
                """
                INSERT INTO messages(
                    event_id, channel, direction, contact_id, thread_id, message_id,
                    in_reply_to, references_header, subject, body_text, body_html,
                    sender_email, sender_name, recipient_email, payload_json, created_at
                ) VALUES (?, 'wechat', 'inbound', ?, ?, ?, '', '', 'Nemoqi', '你还记得重新上线前吗', '', ?, 'Nemoqi', '', '{}', ?)
                """,
                ("wechat:legacy-msg", legacy_contact_id, legacy_thread_id, "legacy-msg", "wechat:wechat:Nemoqi", now),
            ).lastrowid
            job_id = conn.execute(
                """
                INSERT INTO jobs(
                    task_type, status, priority, message_row_id, thread_id, contact_id,
                    payload_json, available_at, scheduled_at, attempt_count, last_error, sent_message_id, created_at, updated_at
                ) VALUES ('reply', 'pending', 100, ?, ?, ?, '{}', ?, ?, 0, '', '', ?, ?)
                """,
                (message_row_id, legacy_thread_id, legacy_contact_id, now, now, now, now),
            ).lastrowid
            conn.commit()
            conn.close()

            store = QueueStore(db_path)
            store.initialize()

            contact = store.find_contact("wechat:Nemoqi")
            self.assertIsNotNone(contact)
            contacts = store._fetchall("SELECT * FROM contacts WHERE email LIKE 'wechat:%'")
            self.assertEqual(len(contacts), 1)

            thread = store.find_thread(channel="wechat", thread_key="wechat:Nemoqi")
            self.assertIsNotNone(thread)
            self.assertEqual(thread["thread_key"], "Nemoqi")
            self.assertEqual(thread["codex_session_id"], "legacy-session")

            merged_message = store._fetchone("SELECT * FROM messages WHERE id = ?", (message_row_id,))
            merged_job = store._fetchone("SELECT * FROM jobs WHERE id = ?", (job_id,))
            self.assertEqual(int(merged_message["thread_id"]), int(thread["id"]))
            self.assertEqual(int(merged_job["thread_id"]), int(thread["id"]))
            self.assertEqual(int(merged_message["contact_id"]), int(contact["id"]))
            self.assertEqual(int(merged_job["contact_id"]), int(contact["id"]))
            self.assertEqual(int(thread["id"]), int(canonical_thread_id))
            store.close()


class CodexRunnerTests(unittest.TestCase):
    def test_runner_applies_model_and_low_reasoning_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_model = "gpt-5.4"
            config.runtime.codex_reasoning_effort = "low"
            runner = CodexRunner(config)

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                output = Path(tmpdir) / "reply.txt"

                def fake_run(command, **kwargs):
                    Path(kwargs["cwd"])  # touch for coverage sanity
                    Path(command[command.index("-o") + 1]).write_text("咱在。", encoding="utf-8")
                    completed = mock.Mock()
                    completed.returncode = 0
                    completed.stdout = '{"type":"thread.started","thread_id":"thread-123"}\n'
                    completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                result = runner.run("在吗")

            self.assertEqual(result.reply_text, "咱在。")
            command = run_mock.call_args.args[0]
            self.assertIn("-m", command)
            self.assertIn("gpt-5.4", command)
            self.assertIn('-c', command)
            self.assertIn('model_reasoning_effort="low"', command)

    def test_runner_resume_inserts_runtime_options_after_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_model = "gpt-5.4"
            config.runtime.codex_reasoning_effort = "low"
            runner = CodexRunner(config)

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                def fake_run(command, **kwargs):
                    Path(command[command.index("-o") + 1]).write_text("咱在。", encoding="utf-8")
                    completed = mock.Mock()
                    completed.returncode = 0
                    completed.stdout = ""
                    completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                runner.run("在吗", session_id="thread-xyz")

            command = run_mock.call_args.args[0]
            self.assertEqual(command[:4], ["codex", "exec", "resume", "-m"])
            self.assertIn('model_reasoning_effort="low"', command)

    def test_runner_falls_back_to_fresh_exec_when_resume_rollout_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            config.runtime.codex_command_prefix = ("codex",)
            runner = CodexRunner(config)
            calls: list[list[str]] = []

            with mock.patch("holo_host.codex_runner.subprocess.run") as run_mock:
                def fake_run(command, **kwargs):
                    calls.append(list(command))
                    output_path = Path(command[command.index("-o") + 1])
                    completed = mock.Mock()
                    if "resume" in command:
                        output_path.write_text("", encoding="utf-8")
                        completed.returncode = 1
                        completed.stdout = ""
                        completed.stderr = "Error: thread/resume failed: no rollout found for thread id old-thread\n"
                    else:
                        output_path.write_text("咱在。", encoding="utf-8")
                        completed.returncode = 0
                        completed.stdout = '{"type":"thread.started","thread_id":"thread-new"}\n'
                        completed.stderr = ""
                    return completed

                run_mock.side_effect = fake_run
                result = runner.run("在吗", session_id="old-thread")

            self.assertEqual(len(calls), 2)
            self.assertEqual(calls[0][:3], ["codex", "exec", "resume"])
            self.assertEqual(calls[1][:2], ["codex", "exec"])
            self.assertNotIn("resume", calls[1])
            self.assertEqual(result.returncode, 0)
            self.assertEqual(result.reply_text, "咱在。")
            self.assertEqual(result.session_id, "thread-new")


class MaildirGatewayTests(unittest.TestCase):
    def test_poll_ack_and_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            incoming = gateway.inbox_dir / "hello.json"
            incoming.write_text(
                json.dumps(
                    {
                        "message_id": "<msg-1>",
                        "thread_key": "<msg-1>",
                        "subject": "Hello",
                        "sender_email": "friend@example.com",
                        "body_text": "Hello there",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            messages = gateway.poll_inbox(limit=10)
            self.assertEqual(len(messages), 1)
            gateway.acknowledge(messages[0])
            self.assertFalse(incoming.exists())
            self.assertEqual(len(list(gateway.processed_dir.iterdir())), 1)

            remote_id = gateway.send_reply(
                OutgoingMessage(
                    recipient_email="friend@example.com",
                    subject="Hello",
                    body_text="咱在这儿。",
                    thread_key="<msg-1>",
                )
            )
            self.assertTrue(remote_id)
            self.assertEqual(len(list(gateway.outbox_dir.iterdir())), 1)


class ReplyBubbleTests(unittest.TestCase):
    def test_long_fast_wechat_reply_splits_into_two_bubbles_instead_of_truncating(self) -> None:
        attention = build_attention_state("好家伙", channel="wechat")
        bubbles = build_reply_bubbles(
            "好家伙这两个字，像把狼尾巴都惊出来了 😏 那咱就先把耳朵竖起来听你往下说",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "medium"},
            route="fast",
            target_count=1,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        joined = " ".join(b.text for b in bubbles)
        self.assertIn("那咱就先把", joined)

    def test_build_reply_bubbles_uses_utterance_plan_purposes(self) -> None:
        attention = build_attention_state("那今晚怎么办", channel="wechat")
        bubbles = build_reply_bubbles(
            "先缓一下。真正卡住的是今晚这口气。等咱陪你把它拆开。",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "low"},
            utterance_plan={"beats": ["receive", "pivot", "landing"]},
            route="main",
            target_count=2,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        self.assertEqual(bubbles[0].purpose, "receive")
        self.assertIn(bubbles[1].purpose, {"pivot", "landing"})

    def test_build_reply_bubbles_avoids_mid_phrase_hard_split(self) -> None:
        attention = build_attention_state("我有点困惑", channel="wechat")
        bubbles = build_reply_bubbles(
            "是啊，困惑本来就正常，像走在雾里，哪有一直看得清的道理 😌 你先别急着把自己逼得太紧，咱陪你把这一阵雾慢慢捋开。",
            channel="wechat",
            attention_state=attention,
            emotion_state={"playfulness": "low"},
            utterance_plan={"beats": ["receive", "landing"]},
            route="fast",
            target_count=2,
        )
        self.assertGreaterEqual(len(bubbles), 2)
        joined = "".join(b.text for b in bubbles)
        self.assertIn("道理", joined)
        self.assertFalse(any(b.text.endswith("道") for b in bubbles))
        self.assertFalse(any(b.text.startswith("理") for b in bubbles))

    def test_build_turn_plan_can_expand_bubble_target_for_playful_companionship(self) -> None:
        attention = AttentionState(
            primary_focus="companionship",
            secondary_focus="tone",
            reply_goal="answer_then_extend",
            pressure_level="low",
            salience_sources=["question"],
        )
        context = TurnContext(
            channel="wechat",
            thread_key="Nemoqi",
            chat_name="Nemoqi",
            sender="Nemoqi",
            user_text="咱别总两句就停，继续顺着这点苹果酒意和打趣往下聊聊看",
            sidecar={"tier": "fast"},
            attention_state=attention,
            emotion_state={"playfulness": "high"},
            history=[],
            mind_packet={"tier": "fast"},
            utterance_plan={"beats": ["receive", "pivot", "landing", "echo"]},
            persona_blend={"playfulness": 0.78},
            game_state={"initiative_window": 0.64, "teasing_tolerance": 0.61},
        )
        plan = build_turn_plan(context, load_config(repo_root=tempfile.mkdtemp()))
        self.assertGreaterEqual(plan.bubble_target, 4)

    def test_coerce_helper_artifact_path_converts_mnt_path_on_windows(self) -> None:
        converted = _coerce_helper_artifact_path("/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history.md")
        self.assertTrue(converted.lower().startswith("d:\\"))
        self.assertIn(".holo_runtime\\wechat-helper\\receipts\\history.md".lower(), converted.lower())

    def test_poll_inbox_skips_corrupt_json_mail(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            (gateway.inbox_dir / "broken.json").write_text("{bad", encoding="utf-8")
            (gateway.inbox_dir / "ok.json").write_text(
                json.dumps(
                    {
                        "message_id": "<msg-2>",
                        "thread_key": "<msg-2>",
                        "subject": "Hello again",
                        "sender_email": "friend@example.com",
                        "body_text": "Still here",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            messages = gateway.poll_inbox(limit=10)
            self.assertEqual(len(messages), 1)
            self.assertEqual(messages[0].message_id, "<msg-2>")


class PolicyTests(unittest.TestCase):
    def test_high_risk_blocks_auto_send(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="Can you help me with tax advice?",
                reply_text="Sure.",
                recent_outbound_count=0,
                is_existing_thread=True,
                is_proactive=False,
            )
            self.assertFalse(decision.allowed)
            self.assertEqual(decision.reason, "high_risk_content")

    def test_wechat_existing_thread_has_higher_auto_reply_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="在吗",
                reply_text="咱在。",
                recent_outbound_count=10,
                is_existing_thread=True,
                is_proactive=False,
                channel="wechat",
            )
            self.assertTrue(decision.allowed)

    def test_wechat_existing_thread_allows_lively_chat_bursts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config = load_config(repo_root=tmpdir)
            policy = AutonomyPolicy(config)
            decision = policy.outbound_decision(
                incoming_text="怎么不理我了😭",
                reply_text="咱在，刚刚没接稳。",
                recent_outbound_count=52,
                is_existing_thread=True,
                is_proactive=False,
                channel="wechat",
            )
            self.assertTrue(decision.allowed)


class DaemonFlowTests(unittest.TestCase):
    def test_daemon_cycle_sends_reply_and_observes_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            message_path = gateway.inbox_dir / "turn.json"
            message_path.write_text(
                json.dumps(
                    {
                        "message_id": "<turn-1>",
                        "thread_key": "<turn-1>",
                        "subject": "Checking in",
                        "sender_email": "friend@example.com",
                        "body_text": "I am under a lot of pressure lately.",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Take a breath first.")
            memory = FakeMemory()
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["ingested"], ["queued:<turn-1>"])
                self.assertTrue(any(item.startswith("sent:") for item in result["processed_jobs"]))
                self.assertEqual(len(memory.observed), 1)
                self.assertEqual(memory.observed_records[0]["turn_id"], "<turn-1>")
                self.assertEqual(memory.observed_records[0]["metadata"]["thread_key"], "<turn-1>")
                self.assertEqual(memory.observed_records[0]["metadata"]["channel"], "email")
                jobs = store.list_jobs(limit=10)
                self.assertEqual(jobs[0]["status"], "sent")
                self.assertEqual(len(list(gateway.outbox_dir.iterdir())), 1)
            finally:
                close_daemon_handles(daemon)
    def test_daemon_cycle_schedules_and_queues_whitelisted_wechat_initiative(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertTrue(result["initiative"]["scheduled_job_ids"])
                self.assertTrue(any(item.startswith("queued:") for item in result["processed_jobs"]))
                queued = sorted(send_queue_dir.glob("*.json"))
                self.assertEqual(len(queued), 1)
                payload = json.loads(queued[0].read_text(encoding="utf-8"))
                self.assertEqual(payload["chat_name"], "Nemoqi")
                self.assertTrue(str(payload["text"]).strip())
            finally:
                close_daemon_handles(daemon)

    def test_daemon_cycle_blocks_initiative_when_probe_gate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            send_queue_dir = root / "send_queue"
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "whitelist": ["Nemoqi"],
                        "send_queue_dir": str(send_queue_dir),
                        "pywinauto_process_path": "C:/Program Files/Tencent/WeChat/WeChat.exe",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            gateway = MaildirGateway(config)
            runner = FakeRunner("What are you busy with?")
            memory = FakeMemory()
            memory.game_state_data = {
                "trust_score": 0.2,
                "teasing_tolerance": 0.2,
                "pressure_level": 0.9,
                "initiative_window": 0.1,
                "correction_sensitivity": 0.4,
            }
            memory.initiatives.append(
                {
                    "channel": "wechat",
                    "thread_key": "wechat:Nemoqi",
                    "chat_name": "Nemoqi",
                    "reason": "Old thread still warm",
                    "prompt": "Lightly poke this thread",
                    "priority": 66,
                }
            )
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertEqual(result["initiative"]["scheduled_job_ids"], [])
                self.assertTrue(result["initiative"]["blocked_candidates"])
                self.assertFalse(send_queue_dir.exists() and list(send_queue_dir.glob("*.json")))
            finally:
                close_daemon_handles(daemon)
    def test_daemon_reply_job_passes_richer_metadata_to_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            gateway = MaildirGateway(config)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            contact = store.ensure_contact("friend@example.com", "Friend")
            thread, _ = store.ensure_thread(
                channel="email",
                contact_id=int(contact["id"]),
                thread_key="thread-1",
                subject="Checking in",
            )
            message = IncomingMessage(
                message_id="<turn-1>",
                thread_key="thread-1",
                subject="Checking in",
                sender_email="friend@example.com",
                sender_name="Friend",
                body_text="I am under a lot of pressure lately.",
                metadata={"source_ref": "maildir/inbox"},
            )
            record = store.record_inbound(message)
            store.enqueue_job(
                task_type="reply",
                message_row_id=int(record["message"]["id"]),
                thread_id=int(thread["id"]),
                contact_id=int(contact["id"]),
                payload={"source": "incoming_mail"},
            )

            runner = FakeRunner("Take a breath first.")
            memory = FakeMemory()
            daemon = HoloDaemon(config, store=store, gateway=gateway, runner=runner, memory=memory)
            try:
                result = daemon.run_cycle()
                self.assertTrue(any(item.startswith("sent:") for item in result["processed_jobs"]))
                self.assertEqual(len(memory.observed_records), 1)
                record = memory.observed_records[0]
                self.assertEqual(record["turn_id"], "<turn-1>")
                self.assertEqual(record["metadata"]["thread_key"], "thread-1")
                self.assertEqual(record["metadata"]["message_id"], "<turn-1>")
                self.assertEqual(record["metadata"]["outbound_message_id"], store.list_jobs(limit=10)[0]["sent_message_id"])
                self.assertEqual(record["metadata"]["sender_email"], "friend@example.com")
                self.assertEqual(record["metadata"]["sender_name"], "Friend")
                self.assertEqual(record["metadata"]["subject"], "Checking in")
            finally:
                close_daemon_handles(daemon)
class ReplyServiceTests(unittest.TestCase):
    def test_shape_wechat_reply_strips_stock_opener_and_stays_short(self) -> None:
        text = "咱先把这口气守住。也是，微信里一长就像在写公函。你随手扔一句来就好，咱接着。"
        shaped = shape_wechat_reply(text)
        self.assertNotIn("咱先把这口气守住", shaped)
        self.assertTrue(len(shaped) < len(text))
        self.assertIn("微信里一长就像在写公函", shaped)
        self.assertFalse(shaped.endswith("。"))

    def test_shape_wechat_reply_does_not_cut_mid_clause(self) -> None:
        text = "比如会记这些：你要咱把“咱”留住，别掉回助手腔；微信里话短些，少点公式化开头，标点别太端着，emoji也可以学 再往里一点，还会记你更想要真诚陪伴，不爱空话；要是聊到工作、前途、账目这种压人的题，先给你松口气，再谈办法。"
        shaped = shape_wechat_reply(text)
        self.assertNotIn("压人的。", shaped)
        self.assertTrue(len(shaped) <= 72)

    def test_reply_service_uses_codex_runner_and_tracks_thread_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Let us steady the tone first.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                first = service.handle_reply(
                    {
                        "chat_name": "TestContact",
                        "sender": "TestContact",
                        "text": "I have been under a lot of pressure.",
                        "channel": "wechat",
                        "ts": 1,
                    }
                )
                self.assertEqual(first["action"], "reply")
                self.assertEqual(first["session_id"], "thread-123")
                self.assertTrue(runner.calls)
                self.assertEqual(len(memory.observed), 1)

                second = service.handle_reply(
                    {
                        "chat_name": "TestContact",
                        "sender": "TestContact",
                        "text": "What should I do tonight?",
                        "channel": "wechat",
                        "ts": 2,
                    }
                )
                self.assertEqual(second["action"], "reply")
                self.assertEqual(runner.calls[1][1], "thread-123")
                self.assertEqual(memory.sidecar_requests[-1]["context"]["chat_name"], "TestContact")
                self.assertEqual(memory.sidecar_requests[-1]["context"]["thread_key"], "TestContact")
            finally:
                close_service_handles(service)
    def test_reply_service_uses_shorter_wechat_prompt_style(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("咱先把这口气守住。也是，微信里一长就像在写公函。你随手扔一句来就好，咱接着。")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "可以简短一点",
                        "channel": "wechat",
                        "message_id": "wechat-short-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
                prompt, _session = runner.calls[-1]
                self.assertIn("这是微信聊天。默认只回 1 到 2 句", prompt)
                self.assertNotIn("咱先把这口气守住", result["text"])
                self.assertTrue(len(result["text"]) <= 72)
            finally:
                close_service_handles(service)

    def test_reply_service_prompt_keeps_multifacet_holo_balance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("那咱就先不端着，顺着这句往下接。")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "苹果和酒这类话题，你会怎么接？",
                        "channel": "wechat",
                        "message_id": "wechat-persona-balance-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
                prompt, _session = runner.calls[-1]
                self.assertIn("赫萝不是只剩稳重那一面", prompt)
                self.assertIn("别默认成长辈、说教者或心理咨询口气", prompt)
            finally:
                close_service_handles(service)

    def test_reply_service_returns_structured_bubbles_and_attention_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Pause for a breath, then speak slowly.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "I am tired.",
                        "channel": "wechat",
                        "message_id": "wechat-bubble-1",
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertGreaterEqual(len(result["bubbles"]), 1)
                self.assertIn("attention_state", result)
                self.assertIn("turn_plan", result)
                self.assertIn("timing_ms", result)
                self.assertIn("processor", result)
                self.assertIn("route", result)
                self.assertEqual(result["turn_plan"]["route"], result["route"])
                self.assertIn("processor_ms", result["timing_ms"])
                self.assertIn("utterance_plan", result)
            finally:
                close_service_handles(service)
    def test_reply_service_ignores_recent_wechat_outbound_echo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("I am here.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                first = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "You there?",
                        "channel": "wechat",
                        "message_id": "wechat-echo-in-1",
                        "metadata": {"visible_digest": "digest-a"},
                    }
                )
                self.assertEqual(first["action"], "reply")

                echoed = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": first["text"],
                        "channel": "wechat",
                        "message_id": "wechat-echo-in-2",
                        "metadata": {"visible_digest": "digest-b", "direction": "unknown"},
                    }
                )
                self.assertEqual(echoed["action"], "ignore")
                self.assertEqual(echoed["reason"], "outbound_echo")
            finally:
                close_service_handles(service)
    def test_reply_service_passes_richer_metadata_to_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("Let us ease the pressure first.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                result = service.handle_reply(
                    {
                        "chat_name": "Nemoqi",
                        "sender": "Nemoqi",
                        "text": "I only wanted someone beside me.",
                        "channel": "wechat",
                        "message_id": "wechat-msg-1",
                        "thread_key": "wechat:Nemoqi",
                        "source_ref": "window:weixin",
                        "is_group": False,
                        "mentioned": True,
                        "metadata": {"capture_path": "C:/capture.png"},
                        "ts": 1,
                    }
                )

                self.assertEqual(result["action"], "reply")
                self.assertEqual(len(memory.observed_records), 1)
                record = memory.observed_records[0]
                self.assertEqual(record["turn_id"], "wechat-msg-1")
                self.assertEqual(record["metadata"]["chat_name"], "Nemoqi")
                self.assertEqual(record["metadata"]["sender"], "Nemoqi")
                self.assertEqual(record["metadata"]["channel"], "wechat")
                self.assertEqual(record["metadata"]["thread_key"], "Nemoqi")
                self.assertEqual(record["metadata"]["message_id"], "wechat-msg-1")
                self.assertEqual(record["metadata"]["source_ref"], "window:weixin")
                self.assertEqual(record["metadata"]["capture_path"], "C:/capture.png")
                self.assertTrue(record["metadata"]["mentioned"])
                self.assertFalse(record["metadata"]["is_group"])
                self.assertEqual(record["metadata"]["utterance_plan"]["beats"], ["receive", "pivot", "landing"])
                self.assertEqual(memory.sidecar_requests[0]["context"]["thread_key"], "Nemoqi")
                self.assertEqual(memory.sidecar_requests[0]["context"]["incoming_thread_key"], "Nemoqi")
            finally:
                close_service_handles(service)
    def test_reply_service_refreshes_wechat_history_before_recall_reply(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("咱还记得")
            memory = FakeMemory()
            memory.sidecar_tier = "recall"
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)
            service.refresh_wechat_history = mock.Mock(return_value={"status": "ingested", "message_count": 12})  # type: ignore[method-assign]

            result = service.handle_reply(
                {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "你还记得重新上线前吗",
                    "channel": "wechat",
                    "message_id": "wechat-recall-1",
                }
            )

            self.assertEqual(result["action"], "reply")
            self.assertEqual(service.refresh_wechat_history.call_count, 1)
            self.assertEqual(len(memory.sidecar_requests), 2)
            self.assertEqual(result["active_memory_refresh"]["status"], "ingested")
            self.assertIn("active_history_ms", result["timing_ms"])
            self.assertTrue(memory.recalled)
            close_service_handles(service)

    def test_reply_probe_compares_graph_led_and_legacy_drafts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            runner = FakeRunner("咱记得一些，线头还在。")
            memory = FakeMemory()
            graph_packet = memory.sidecar_packet("你还记得重新上线前吗")
            graph_packet.update(
                {
                    "tier": "deep_recall",
                    "retrieval_mode": "graph-led",
                    "graph_confidence": 0.92,
                    "activation_trace_ids": ["archive:turn-1"],
                    "selected_memory_ids": ["archive:turn-1"],
                    "episodic_recall": {"lines": ["重新上线前一直在救回速度"], "items": []},
                }
            )
            legacy_packet = dict(graph_packet)
            legacy_packet.update(
                {
                    "retrieval_mode": "legacy",
                    "graph_confidence": 0.0,
                    "fallback_lanes": ["relationship_state", "episodic_recall", "recent_dialogue_window", "consciousness_stream"],
                    "activation_trace_ids": [],
                    "selected_memory_ids": [],
                    "episodic_recall": {"lines": [], "items": []},
                }
            )
            memory.sidecar_packet = mock.Mock(return_value=graph_packet)  # type: ignore[method-assign]
            memory.legacy_sidecar_packet = mock.Mock(return_value=legacy_packet)  # type: ignore[method-assign]
            service = HoloReplyService(config, runner=runner, memory=memory)
            self.addCleanup(close_service_handles, service)

            report = service.reply_probe(
                {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "你还记得重新上线前吗",
                    "channel": "wechat",
                    "thread_key": "Nemoqi",
                }
            )

            self.assertEqual(report["graph_led"]["retrieval_mode"], "graph-led")
            self.assertEqual(report["legacy"]["retrieval_mode"], "legacy")
            self.assertTrue(runner.task_calls)
            self.assertEqual(runner.task_calls[0]["task_type"], "recall_reconstruct")
            self.assertIn("summary", report["graph_led"]["recall_reconstruction"])
            self.assertIn("summary", report["graph_led"]["reply_plan"]["debug"]["recall_reconstruction"])
            close_service_handles(service)

    def test_refresh_wechat_history_uses_windows_helper_and_caches_cooldown(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "invoke_wechat_history.ps1").write_text("Write-Output '{}'\n", encoding="utf-8")
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "receipt_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/receipts",
                        "send_queue_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/send_queue",
                        "pyweixin_repo_path": "D:/Holo/holo/.vendor/pywechat-upstream",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            service = HoloReplyService(config, memory=FakeMemory())
            self.addCleanup(close_service_handles, service)

            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = json.dumps({"status": "ingested", "message_count": 18, "history_digest": "abc"}, ensure_ascii=False)
            completed.stderr = ""

            with mock.patch("holo_host.reply_api.subprocess.run", return_value=completed) as run_mock:
                first = service.refresh_wechat_history({"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "before"})
                second = service.refresh_wechat_history({"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "before"})

            self.assertEqual(first["status"], "ingested")
            self.assertEqual(second["status"], "skipped_cooldown")
            self.assertEqual(run_mock.call_count, 1)
            command = run_mock.call_args.args[0]
            self.assertIn("powershell.exe", command[0].lower())
            self.assertIn("-ChatName", command)
            self.assertIn("Nemoqi", command)
            self.assertIn("-NoCaptures", command)
            state_payload = json.loads((config.runtime.state_dir / "active_wechat_history_state.json").read_text(encoding="utf-8"))
            self.assertIn("Nemoqi", state_payload)
            self.assertEqual(service.memory.mind_graph_rebuild_calls, 1)
            close_service_handles(service)

    def test_stream_tick_records_influence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[runtime]
api_port = 8010

[autonomy]
wechat_helper_config_path = ""
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            service = HoloReplyService(config, runner=FakeRunner(), memory=FakeMemory(), policy=AutonomyPolicy(config))
            try:
                payload = service.stream_tick(stream_name="association_stream", dry_run=False)
                self.assertEqual(payload["stream_name"], "association_stream")
                self.assertEqual(payload["record"]["influence"]["updated_threads"], 1)
                self.assertEqual(payload["record"]["influence"]["motifs"], ["continuity"])
            finally:
                close_service_handles(service)

    def test_brain_status_merges_stage3_loops_for_live_visibility(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            memory = FakeMemory()
            memory.brain_status = mock.Mock(  # type: ignore[method-assign]
                return_value={
                    "mode": "full_brain",
                    "loops": [
                        {"loop_name": "heartbeat", "status": "ok", "started_at": "2026-04-07T00:00:00Z", "finished_at": "2026-04-07T00:00:00Z"},
                        {"loop_name": "association_stream", "status": "ok", "started_at": "2026-04-07T00:01:00Z", "finished_at": "2026-04-07T00:01:00Z"},
                    ],
                    "cache": {"hit_ratio": 0.0, "hits": 0, "misses": 2},
                }
            )
            service = HoloReplyService(config, runner=FakeRunner(), memory=memory)
            try:
                payload = service.brain_status()
                loop_names = {str(item.get("loop_name", "")) for item in payload["loops"]}

                self.assertIn("self_model_refresh", loop_names)
                self.assertIn("homeostasis_tick", loop_names)
                self.assertIn("operator_planning", loop_names)
                self.assertIn("operator_shadow_cycle", loop_names)
                self.assertIn("visual_ingest_cycle", loop_names)

                pending = next(item for item in payload["loops"] if str(item.get("loop_name", "")) == "self_model_refresh")
                self.assertEqual(pending["status"], "never")
                self.assertIn("idle_seconds", payload)
            finally:
                close_service_handles(service)

    def test_refresh_wechat_history_origin_query_uses_deeper_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            helper_dir = root / "windows_helper"
            helper_dir.mkdir(parents=True, exist_ok=True)
            (helper_dir / "invoke_wechat_history.ps1").write_text("Write-Output '{}'\n", encoding="utf-8")
            (helper_dir / "wechat_helper.live.json").write_text(
                json.dumps(
                    {
                        "receipt_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/receipts",
                        "send_queue_dir": "D:/Holo/holo/.holo_runtime/wechat-helper/send_queue",
                        "pyweixin_repo_path": "D:/Holo/holo/.vendor/pywechat-upstream",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = load_config(repo_root=root)
            service = HoloReplyService(config, memory=FakeMemory())

            completed = mock.Mock()
            completed.returncode = 0
            completed.stdout = json.dumps({"status": "ingested", "message_count": 64, "history_digest": "origin"}, ensure_ascii=False)
            completed.stderr = ""

            try:
                with mock.patch("holo_host.reply_api.subprocess.run", return_value=completed) as run_mock:
                    report = service.refresh_wechat_history(
                        {"chat_name": "Nemoqi", "thread_key": "Nemoqi", "query": "at the beginning, what do you remember"}
                    )

                command = run_mock.call_args.args[0]
                self.assertEqual(command[command.index("-Limit") + 1], str(config.memory.active_wechat_history_deep_limit))
                self.assertEqual(command[command.index("-PageTurns") + 1], str(config.memory.active_wechat_history_deep_page_turns))
                self.assertTrue(report["command"]["origin_recall"])
                self.assertEqual(report["status"], "ingested")
            finally:
                close_service_handles(service)

    def test_reply_service_ignores_duplicate_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("I am here.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                payload = {
                    "chat_name": "TestContact",
                    "sender": "TestContact",
                    "text": "What should we eat tonight?",
                    "channel": "wechat",
                    "message_id": "fixed-1",
                }
                first = service.handle_reply(payload)
                second = service.handle_reply(payload)
                self.assertEqual(first["action"], "reply")
                self.assertEqual(second["action"], "ignore")
                self.assertEqual(second["reason"], "duplicate")
            finally:
                close_service_handles(service)
    def test_reply_service_retries_duplicate_inbound_when_no_outbound_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            runner = FakeRunner("Okay, let us keep it short.")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                incoming = {
                    "chat_name": "Nemoqi",
                    "sender": "Nemoqi",
                    "text": "Can it be shorter?",
                    "channel": "wechat",
                    "message_id": "retry-wechat-1",
                }
                store.record_inbound(
                    IncomingMessage(
                        message_id="retry-wechat-1",
                        thread_key="wechat:Nemoqi",
                        subject="Nemoqi",
                        sender_email="wechat:wechat:Nemoqi",
                        sender_name="Nemoqi",
                        body_text="Can it be shorter?",
                        channel="wechat",
                    )
                )

                result = service.handle_reply(incoming)
                self.assertEqual(result["action"], "reply")
                self.assertTrue(runner.calls)
            finally:
                close_service_handles(service)
    def test_reply_service_ingests_artifact_through_memory_bridge(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            store = QueueStore(config.runtime.db_path)
            runner = FakeRunner("???")
            memory = FakeMemory()
            service = HoloReplyService(config, store=store, runner=runner, memory=memory)
            try:
                report = service.ingest_artifact(
                    {
                        "path": str(root / "notes.txt"),
                        "note": "????????",
                        "tags": ["wechat", "artifact"],
                        "dry_run": True,
                    }
                )
                self.assertEqual(report["artifact_type"], "document")
                self.assertEqual(len(memory.ingested), 1)
                self.assertEqual(memory.ingested[0][1], "????????")
            finally:
                close_service_handles(service)

    def test_reply_service_normalizes_windows_artifact_path_for_wsl(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config = load_config(repo_root=root)
            memory = FakeMemory()
            service = HoloReplyService(config, runner=FakeRunner("???"), memory=memory)
            try:
                service.ingest_artifact(
                    {
                        "path": r"D:\Holo\holo\.holo_runtime\wechat-helper\receipts\history_exports\demo.md",
                        "note": "wechat export",
                        "tags": ["wechat", "artifact"],
                        "dry_run": True,
                    }
                )

                self.assertEqual(len(memory.ingested), 1)
                self.assertEqual(
                    memory.ingested[0][0],
                    "/mnt/d/Holo/holo/.holo_runtime/wechat-helper/receipts/history_exports/demo.md",
                )
            finally:
                close_service_handles(service)


if __name__ == "__main__":
    unittest.main()
