from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from .mind_graph import MindGraph

GRAPH_MEMORY_LANES = (
    "relationship_state",
    "episodic_recall",
    "recent_dialogue_window",
    "consciousness_stream",
)
GRAPH_REPLY_MIN_CONFIDENCE = 0.34


def stream_cadences_from_config(config: Any) -> dict[str, int]:
    memory = getattr(config, "memory", None)
    if memory is None:
        return {}
    return {
        "maintenance_stream": int(getattr(memory, "maintenance_stream_interval_seconds", getattr(memory, "promote_interval_seconds", 300))),
        "association_stream": int(getattr(memory, "association_stream_interval_seconds", getattr(memory, "thought_interval_seconds", 900))),
        "social_stream": int(getattr(memory, "social_stream_interval_seconds", getattr(memory, "initiative_interval_seconds", 1800))),
        "deep_dream_cycle": int(getattr(memory, "deep_dream_cycle_interval_seconds", getattr(memory, "dream_interval_seconds", 21600))),
    }


class MemoryBridge:
    def __init__(
        self,
        repo_root: Path,
        *,
        top_k: int = 4,
        graph_db_path: str | Path | None = None,
        stream_cadences: dict[str, int] | None = None,
        graph_led_reply: bool = True,
        graph_fallback: bool = True,
        deep_recall_on_memory_queries: bool = True,
    ):
        self.repo_root = Path(repo_root)
        self.top_k = top_k
        self.graph_led_reply = bool(graph_led_reply)
        self.graph_fallback = bool(graph_fallback)
        self.deep_recall_on_memory_queries = bool(deep_recall_on_memory_queries)
        self.rag = self._load_rag_memory()
        self.graph = MindGraph(
            self.repo_root,
            db_path=graph_db_path,
            rag=self.rag,
            stream_cadences=stream_cadences,
        )

    def _load_rag_memory(self) -> ModuleType:
        path = self.repo_root / "holo_memory_library" / "rag_memory.py"
        spec = importlib.util.spec_from_file_location("holo_runtime_rag_memory", path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load rag_memory from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    @staticmethod
    def _unique_strings(lines: list[str]) -> list[str]:
        seen: set[str] = set()
        unique: list[str] = []
        for raw in lines:
            text = str(raw or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            unique.append(text)
        return unique

    @staticmethod
    def _lane_has_content(name: str, value: Any) -> bool:
        if name == "relationship_state":
            payload = dict(value or {})
            return bool(str(payload.get("summary", "")).strip() or list(payload.get("lines", [])))
        if name == "consciousness_stream":
            payload = dict(value or {})
            return bool(str(payload.get("thread_summary", "")).strip() or list(payload.get("lines", [])))
        payload = dict(value or {})
        return bool(list(payload.get("lines", [])))

    def legacy_sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        packet = self.rag.sidecar_packet(query, top_k=self.top_k, context=context)
        packet["mind_graph"] = {
            "available": True,
            "db_path": str(self.graph.db_path),
        }
        packet.setdefault("mind_packet_version", "v2")
        packet.setdefault("retrieval_mode", "legacy")
        packet.setdefault("graph_confidence", 0.0)
        packet.setdefault("fallback_lanes", [])
        packet.setdefault("activation_trace_ids", [])
        packet.setdefault("graph_trace_summary", "")
        if context and bool(context.get("include_graph_trace", False)):
            packet["mind_graph"]["trace"] = self.graph.trace_recall(
                query,
                thread_key=str(context.get("thread_key", "") or ""),
                chat_name=str(context.get("chat_name", "") or ""),
                channel=str(context.get("channel", "wechat") or "wechat"),
                limit=int(context.get("graph_trace_limit", 8) or 8),
                record=False,
            )
        return packet

    def _graph_sidecar_packet(self, query: str, *, context: dict[str, Any], legacy_packet: dict[str, Any]) -> dict[str, Any]:
        channel = str(context.get("channel", "wechat") or "wechat")
        thread_key = str(context.get("thread_key", "") or "")
        chat_name = str(context.get("chat_name", "") or "")
        limits = dict(legacy_packet.get("limits", {}))
        relationship_limit = int(limits.get("relationship_k", 3) or 3)
        history_limit = int(limits.get("history_messages", 4) or 4)
        episodic_limit = int(limits.get("episodic_k", 2) or 2)
        consciousness_limit = int(limits.get("consciousness_k", 1) or 1)
        trace_limit = max(
            int(context.get("graph_trace_limit", 8) or 8),
            relationship_limit + history_limit + episodic_limit + consciousness_limit + 2,
        )
        trace = self.graph.trace_recall(
            query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=trace_limit,
            record=False,
        )
        relationship = self.graph.relationship_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=relationship_limit,
        )
        query_focus = str(trace.get("query_focus", "") or "")
        if query_focus == "origin":
            recent_window = self.graph.origin_dialogue_window(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=history_limit,
            )
        else:
            recent_window = self.graph.recent_dialogue_window(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=history_limit,
            )
        consciousness = self.graph.consciousness_snapshot(
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=consciousness_limit,
        )
        if thread_key and not (
            list(relationship.get("recurring_motifs", []))
            or list(relationship.get("unfinished_threads", []))
            or str(relationship.get("tone_tendency", "")).strip()
        ):
            self.graph.sync_thread(channel=channel, thread_key=thread_key, chat_name=chat_name)
            trace = self.graph.trace_recall(
                query,
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=trace_limit,
                record=False,
            )
            relationship = self.graph.relationship_snapshot(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=relationship_limit,
            )
            if query_focus == "origin":
                recent_window = self.graph.origin_dialogue_window(
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=history_limit,
                )
            else:
                recent_window = self.graph.recent_dialogue_window(
                    thread_key=thread_key,
                    chat_name=chat_name,
                    channel=channel,
                    limit=history_limit,
                )
            consciousness = self.graph.consciousness_snapshot(
                thread_key=thread_key,
                chat_name=chat_name,
                channel=channel,
                limit=consciousness_limit,
            )
        episodic_items = [
            {
                "id": str(item.get("node_id", "")),
                "text": str(item.get("text", "")),
                "source_store": str(item.get("source_store", "")),
                "source_id": str(item.get("source_id", "")),
                "source_kind": str(item.get("source_kind", "")),
            }
            for item in trace.get("trace", [])
            if str(item.get("memory_class", "")) == "episodic_memory"
        ][: max(1, episodic_limit)]
        episodic_lines = self._unique_strings([str(item.get("text", "")) for item in episodic_items])
        consciousness_lines = self._unique_strings(
            list(consciousness.get("lines", []))
            + [
                str(item.get("text", ""))
                for item in trace.get("trace", [])
                if str(item.get("memory_class", "")) in {"dream_residue", "initiative_seed"}
            ]
        )[: max(1, consciousness_limit)]
        relationship_lines = self._unique_strings(list(relationship.get("lines", [])))[: max(1, relationship_limit)]
        graph_trace_summary = " | ".join(self._unique_strings(
            [str(trace.get("thread_summary", "")).strip()]
            + [str(item.get("text", "")) for item in trace.get("trace", [])[:3]]
        ))
        return {
            "tier": str(trace.get("tier", legacy_packet.get("tier", "fast"))),
            "query_focus": query_focus or "recent",
            "graph_confidence": float(trace.get("confidence", 0.0) or 0.0),
            "graph_trace_summary": graph_trace_summary,
            "activation_trace_ids": list(trace.get("activated_node_ids", [])),
            "selected_memory_ids": list(trace.get("activated_node_ids", [])),
            "relationship_state": {
                "summary": str(relationship.get("summary", "") or trace.get("relationship_summary", "")),
                "lines": relationship_lines,
                "items": list(relationship.get("items", [])),
                "relationship_score": float(relationship.get("relationship_score", 0.0) or 0.0),
                "last_message_at": str(relationship.get("last_message_at", "") or ""),
                "recurring_motifs": list(relationship.get("recurring_motifs", [])),
                "unfinished_threads": list(relationship.get("unfinished_threads", [])),
                "anchor_lines": list(relationship.get("anchor_lines", [])),
                "tone_tendency": str(relationship.get("tone_tendency", "") or ""),
                "trust_score": float(relationship.get("trust_score", 0.0) or 0.0),
                "closeness_score": float(relationship.get("closeness_score", 0.0) or 0.0),
                "continuity_score": float(relationship.get("continuity_score", 0.0) or 0.0),
            },
            "recent_dialogue_window": recent_window,
            "episodic_recall": {
                "lines": episodic_lines,
                "items": episodic_items,
            },
            "consciousness_stream": {
                "thread_summary": str(consciousness.get("thread_summary", "") or trace.get("thread_summary", "")),
                "lines": consciousness_lines,
                "items": list(consciousness.get("items", [])),
            },
            "mind_graph": {
                "available": True,
                "db_path": str(self.graph.db_path),
                "trace": trace,
            },
        }

    def sidecar_packet(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        normalized_context = dict(context or {})
        legacy_packet = self.legacy_sidecar_packet(query, context=normalized_context)
        if not self.graph_led_reply:
            return legacy_packet

        graph_packet = self._graph_sidecar_packet(query, context=normalized_context, legacy_packet=legacy_packet)
        packet = dict(legacy_packet)
        packet["mind_packet_version"] = "v3"
        packet["mind_graph"] = dict(graph_packet.get("mind_graph", packet.get("mind_graph", {})))
        packet["query_focus"] = str(graph_packet.get("query_focus", packet.get("query_focus", "recent")) or "recent")
        packet["graph_confidence"] = float(graph_packet.get("graph_confidence", 0.0) or 0.0)
        packet["activation_trace_ids"] = list(graph_packet.get("activation_trace_ids", []))
        packet["graph_trace_summary"] = str(graph_packet.get("graph_trace_summary", "") or "")

        fallback_lanes: list[str] = []
        use_graph_lanes = packet["graph_confidence"] >= GRAPH_REPLY_MIN_CONFIDENCE
        for lane in GRAPH_MEMORY_LANES:
            graph_value = graph_packet.get(lane)
            if use_graph_lanes and self._lane_has_content(lane, graph_value):
                packet[lane] = graph_value
                continue
            if self.graph_fallback:
                fallback_lanes.append(lane)
                continue
            packet[lane] = graph_value

        if self.deep_recall_on_memory_queries and str(graph_packet.get("tier", "")).strip():
            packet["tier"] = str(graph_packet.get("tier", packet.get("tier", "fast")))
            if packet["tier"] == "deep_recall":
                packet["recall_reason"] = "graph_deep_recall"

        if fallback_lanes and self.graph_fallback:
            if len(fallback_lanes) == len(GRAPH_MEMORY_LANES):
                packet["retrieval_mode"] = "legacy-fallback"
            else:
                packet["retrieval_mode"] = "graph-led+fallback"
        else:
            packet["retrieval_mode"] = "graph-led"
        packet["fallback_lanes"] = fallback_lanes

        combined_memory_ids = self._unique_strings(
            list(graph_packet.get("selected_memory_ids", []))
            + list(legacy_packet.get("selected_memory_ids", []))
        )
        packet["selected_memory_ids"] = combined_memory_ids
        if not packet.get("thread_recall_lines"):
            packet["thread_recall_lines"] = list(graph_packet.get("episodic_recall", {}).get("lines", []))[:3]
        return packet

    def inspect_mind(self, query: str, *, context: dict[str, Any] | None = None) -> dict[str, Any]:
        enriched_context = dict(context or {})
        enriched_context["include_graph_trace"] = True
        packet = self.sidecar_packet(query, context=enriched_context)
        graph_trace = dict(packet.get("mind_graph", {}).get("trace", {}))
        return {
            "query": packet.get("query", query),
            "tier": packet.get("tier", "fast"),
            "query_focus": packet.get("query_focus", "recent"),
            "recall_reason": packet.get("recall_reason", "none"),
            "selected_memory_ids": list(packet.get("selected_memory_ids", [])),
            "thread_recall_lines": list(packet.get("thread_recall_lines", [])),
            "episodic_lines": list(packet.get("episodic_recall", {}).get("lines", [])),
            "consciousness_lines": list(packet.get("consciousness_stream", {}).get("lines", [])),
            "thread_summary": str(packet.get("consciousness_stream", {}).get("thread_summary", "")),
            "relationship_summary": str(packet.get("relationship_state", {}).get("summary", "")),
            "graph_trace": graph_trace,
            "activated_node_ids": list(graph_trace.get("activated_node_ids", [])),
            "graph_thread_summary": str(graph_trace.get("thread_summary", "")),
            "graph_relationship_summary": str(graph_trace.get("relationship_summary", "")),
            "mind_packet": packet,
        }

    def record_recall(self, selected_ids: list[str], *, success: bool = True) -> dict[str, Any]:
        rag_result = self.rag.record_memory_recall(selected_ids, success=success)
        graph_result = self.graph.record_recall(selected_ids, success=success)
        return {"rag": rag_result, "mind_graph": graph_result}

    def repair_reply(self, query: str, draft: str, *, max_passes: int = 2) -> dict[str, Any]:
        return self.rag.reply_loop_result(query, draft, max_passes=max_passes)

    def observe_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = self.rag.auto_observe_turn(
            user_text,
            reply=reply,
            source=source,
            tags=tags,
            turn_id=turn_id,
            metadata=metadata,
        )
        if isinstance(result, dict):
            result["mind_graph_sync"] = self.graph.sync_archive_entry(result.get("archive_entry"))
        return result

    def archive_turn(
        self,
        user_text: str,
        reply: str,
        *,
        source: str,
        tags: list[str],
        turn_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any] | None:
        result = self.rag.archive_turn(
            user_text,
            reply,
            source=source,
            tags=tags,
            turn_id=turn_id,
            metadata=metadata,
            dry_run=dry_run,
        )
        if dry_run or not isinstance(result, dict):
            return result
        result["mind_graph_sync"] = self.graph.sync_archive_entry(result)
        return result

    def show_archive(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_archive(limit=limit)

    def backfill_archive(self, *, db_path: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.backfill_archive_result(db_path=db_path, dry_run=dry_run)

    def backfill_mind_graph(self, *, dry_run: bool = False) -> dict[str, Any]:
        return self.graph.rebuild(dry_run=dry_run)

    def inspect_graph(
        self,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 12,
    ) -> dict[str, Any]:
        return self.graph.inspect_graph(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)

    def trace_recall(
        self,
        query: str,
        *,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        record: bool = True,
    ) -> dict[str, Any]:
        trace = self.graph.trace_recall(
            query,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
            record=record,
        )
        packet = self.sidecar_packet(
            query,
            context={
                "thread_key": thread_key or "",
                "chat_name": chat_name or "",
                "channel": channel,
                "graph_trace_limit": limit,
            },
        )
        trace["retrieval_mode"] = str(packet.get("retrieval_mode", "legacy"))
        trace["graph_confidence"] = float(packet.get("graph_confidence", 0.0) or 0.0)
        trace["fallback_lanes"] = list(packet.get("fallback_lanes", []))
        trace["activation_trace_ids"] = list(packet.get("activation_trace_ids", []))
        return trace

    def stream_status(self) -> dict[str, Any]:
        return self.graph.stream_status()

    def record_stream_run(self, stream_name: str, *, status: str, note: str = "", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.graph.record_stream_run(stream_name, status=status, note=note, payload=payload)

    def run_dream_cycle(self, *, sample_size: int = 6, seed: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.dream_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)

    def run_think_cycle(self, *, sample_size: int = 4, seed: str | None = None, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.think_cycle_result(sample_size=sample_size, seed=seed, dry_run=dry_run)

    def run_reflect_cycle(self, *, window_hours: float = 12.0, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.reflect_cycle_result(window_hours=window_hours, dry_run=dry_run)

    def run_initiative_cycle(self, *, dry_run: bool = False) -> dict[str, Any]:
        return self.rag.initiative_cycle_result(dry_run=dry_run)

    def list_callback_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_callback_candidates(limit=limit)

    def list_thoughts(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_thought_stream(limit=limit)

    def list_initiative_candidates(self, *, limit: int = 12) -> list[dict[str, Any]]:
        return self.rag.load_initiative_candidates(limit=limit)

    def ingest_artifact(
        self,
        path: str,
        *,
        note: str | None = None,
        source: str,
        tags: list[str],
        dry_run: bool = False,
    ) -> dict[str, Any]:
        return self.rag.ingest_artifact_result(path, note=note, source=source, tags=tags, dry_run=dry_run)

    def promote_ready_candidates(self, limit: int = 8) -> dict[str, Any]:
        candidate_rows = self.rag.load_rows("candidate")
        if not candidate_rows:
            return {"promoted": [], "skipped": [], "remaining_candidates": 0}

        durable_rows = self.rag.load_rows("durable")
        ordered = sorted(
            candidate_rows,
            key=lambda row: (
                bool(row.get("explicit_user_signal", False)),
                float(row.get("confidence", 0.0)),
                float(row.get("importance", 0.0)),
                row.get("last_seen_at", ""),
            ),
            reverse=True,
        )
        selected_ids: set[str] = set()
        promoted: list[str] = []
        skipped: list[str] = []
        remaining: list[dict[str, Any]] = []

        for row in ordered:
            if len(selected_ids) >= limit:
                break
            promotable, reason = self.rag.can_promote(row)
            if promotable:
                selected_ids.add(str(row["id"]))
            else:
                skipped.append(f"{row['id']}: {reason}")

        for row in candidate_rows:
            row_id = str(row["id"])
            if row_id not in selected_ids:
                remaining.append(row)
                continue

            score, match = self.rag.find_best_match(
                durable_rows,
                str(row.get("kind", "")),
                str(row.get("text", "")),
                row.get("tags", []),
            )
            if match and score >= self.rag.MATCH_REINFORCE_THRESHOLD:
                self.rag.merge_row_signal(
                    match,
                    tags=row.get("tags", []),
                    source=str(row.get("source", "host.promote")),
                    importance=float(row.get("importance", 0.7)),
                    confidence=float(row.get("confidence", 0.7)),
                    derived_from=list(row.get("derived_from", [])) + [row_id],
                    explicit_user_signal=bool(row.get("explicit_user_signal", False)),
                    bump=0.04,
                )
                match["supersedes"] = self.rag.unique_strings(list(match.get("supersedes", [])) + [row_id])
                promoted.append(f"merged {row_id} into {match['id']}")
                continue

            new_row = self.rag.prepare_row(row, "candidate")
            new_row["id"] = self.rag.next_id("durable", durable_rows)
            new_row["status"] = "durable"
            new_row["last_seen_at"] = self.rag.now_utc()
            new_row["supersedes"] = self.rag.unique_strings(list(new_row.get("supersedes", [])) + [row_id])
            durable_rows.append(new_row)
            promoted.append(f"promoted {row_id} -> {new_row['id']}")

        self.rag.write_rows("durable", durable_rows)
        self.rag.write_rows("candidate", remaining)
        return {"promoted": promoted, "skipped": skipped, "remaining_candidates": len(remaining)}

    def export_snapshot(self, *, path: str | None = None, label: str | None = None, query: str | None = None) -> dict[str, Any]:
        return self.rag.export_snapshot_payload(path=path, label=label, query=query)

    def import_snapshot(
        self,
        path: str,
        *,
        mode: str = "merge",
        dry_run: bool = False,
        restore_persona: bool = False,
    ) -> dict[str, Any]:
        return self.rag.import_snapshot_payload(path, mode=mode, dry_run=dry_run, restore_persona=restore_persona)

    def revive_packet(self, *, query: str | None = None, snapshot_path: str | None = None) -> dict[str, Any]:
        return self.rag.revive_packet_payload(query=query, snapshot_path=snapshot_path)
