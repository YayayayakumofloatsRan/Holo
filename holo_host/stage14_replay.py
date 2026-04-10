from __future__ import annotations

import json
import tempfile
import time
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from .memory_bridge import MemoryBridge


class Stage14ReplayHarness:
    def __init__(self, bridge: MemoryBridge):
        self.bridge = bridge

    @staticmethod
    def canonical_thread_key(channel: str, thread_key: str, chat_name: str) -> str:
        current_channel = str(channel or "wechat").strip() or "wechat"
        current_thread_key = str(thread_key or chat_name or "").strip()
        current_chat_name = str(chat_name or thread_key or current_thread_key).strip()
        if current_channel == "wechat" and current_thread_key and not current_thread_key.startswith("wechat:") and not current_thread_key.endswith("@chatroom") and not current_thread_key.startswith("wxid_"):
            return f"wechat:{current_thread_key}"
        if not current_thread_key and current_channel == "wechat" and current_chat_name and not current_chat_name.endswith("@chatroom") and not current_chat_name.startswith("wxid_"):
            return f"wechat:{current_chat_name}"
        return current_thread_key or current_chat_name

    def fixture_root(self) -> Path:
        return (self.bridge.repo_root / "tests" / "fixtures" / "stage14").resolve()

    def artifact_root(self) -> Path:
        return (self.bridge.repo_root / "artifacts" / "replays" / "stage14").resolve()

    @staticmethod
    def metric_round(value: float, places: int = 4) -> float:
        quant = Decimal("1").scaleb(-int(places))
        return float(Decimal(str(float(value))).quantize(quant, rounding=ROUND_HALF_UP))

    @staticmethod
    def read_fixture_file(path: Path) -> list[dict[str, Any]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            if isinstance(payload.get("fixtures"), list):
                return [dict(item) for item in payload.get("fixtures", []) if isinstance(item, dict)]
            return [dict(payload)]
        if isinstance(payload, list):
            return [dict(item) for item in payload if isinstance(item, dict)]
        raise ValueError(f"Unsupported fixture payload in {path}")

    def default_intent_state(self, query: str, metadata: dict[str, Any]) -> dict[str, Any]:
        signal = self.bridge._query_signal(query)
        return {
            "reply_pull": 0.62 if not signal["low_signal"] else 0.18,
            "resistance_pull": 0.18 if not signal["defer_requested"] else 0.54,
            "continuity_pull": 0.34,
            "internal_pressure": 0.2,
            "expansion_pressure": 0.22 if signal["question_like"] else 0.12,
            "low_signal": bool(signal["low_signal"]),
            "question_like": bool(signal["question_like"]),
            "defer_requested": bool(signal["defer_requested"]),
            "visual_requested": bool(signal["visual_requested"]),
            "search_requested": bool(signal["search_requested"]),
            "local_memory_requested": bool(signal["local_memory_requested"]),
            "factual_lookup": bool(signal["factual_lookup"]),
            "lookup_ready": bool(metadata.get("lookup_ready", signal["factual_lookup"])),
            "tier": str(metadata.get("tier", "fast") or "fast"),
            "query_focus": str(metadata.get("query_focus", "recent") or "recent"),
        }

    def normalize_fixture(self, fixture: dict[str, Any], *, source_type: str) -> dict[str, Any]:
        prior_state = dict(fixture.get("prior_state", {})) if isinstance(fixture.get("prior_state", {}), dict) else {}
        realized = dict(fixture.get("realized_evidence", {})) if isinstance(fixture.get("realized_evidence", {}), dict) else {}
        top_metadata = dict(fixture.get("metadata", {})) if isinstance(fixture.get("metadata", {}), dict) else {}
        realized_metadata = dict(realized.get("metadata", {})) if isinstance(realized.get("metadata", {}), dict) else {}
        metadata = {**top_metadata, **realized_metadata}
        channel = str(fixture.get("channel", metadata.get("channel", "wechat")) or "wechat").strip() or "wechat"
        chat_name = str(fixture.get("chat_name", metadata.get("chat_name", fixture.get("thread_key", ""))) or "").strip()
        thread_key = self.canonical_thread_key(
            channel,
            str(fixture.get("thread_key", metadata.get("thread_key", chat_name)) or "").strip(),
            chat_name,
        )
        normalized_chat_name = str(chat_name or thread_key.replace("wechat:", "", 1)).strip() or thread_key
        query = str(fixture.get("query", metadata.get("query", "")) or "").strip()
        selected_action = str(realized.get("selected_action", fixture.get("selected_action", "reply_once")) or "reply_once").strip() or "reply_once"
        expected_best_action = str(fixture.get("expected_best_action", metadata.get("expected_best_action", selected_action)) or selected_action).strip() or selected_action
        candidate_actions: list[str] = []
        for raw in list(fixture.get("candidate_actions", [])) + [selected_action, expected_best_action]:
            action_type = str(raw.get("action_type", raw) if isinstance(raw, dict) else raw).strip()
            if action_type and action_type not in candidate_actions:
                candidate_actions.append(action_type)
        if not candidate_actions:
            candidate_actions = [selected_action]
        predicted_outcome = dict(realized.get("predicted_outcome", fixture.get("predicted_outcome", {}))) if isinstance(realized.get("predicted_outcome", fixture.get("predicted_outcome", {})), dict) else {}
        realized_outcome = dict(realized.get("realized_outcome", fixture.get("realized_outcome", {}))) if isinstance(realized.get("realized_outcome", fixture.get("realized_outcome", {})), dict) else {}
        return {
            "fixture_id": str(fixture.get("fixture_id", metadata.get("fixture_id", f"{source_type}:{thread_key}:{selected_action}")) or f"{source_type}:{thread_key}:{selected_action}"),
            "source_type": source_type,
            "channel": channel,
            "thread_key": thread_key,
            "chat_name": normalized_chat_name,
            "query": query,
            "expected_best_action": expected_best_action,
            "scenario_tags": [str(item).strip() for item in list(fixture.get("scenario_tags", metadata.get("scenario_tags", []))) if str(item).strip()],
            "candidate_actions": candidate_actions,
            "prior_state": {
                "intent_state": dict(prior_state.get("intent_state", self.default_intent_state(query, metadata))),
                "relationship_state": dict(prior_state.get("relationship_state", {})),
                "game_state": dict(prior_state.get("game_state", {})),
                "affect_state": dict(prior_state.get("affect_state", {})),
                "drive_state": dict(prior_state.get("drive_state", {})),
                "value_state": dict(prior_state.get("value_state", {})),
                "conflict_state": dict(prior_state.get("conflict_state", {})),
                "world_state": dict(prior_state.get("world_state", {})),
                "calibration_rows": [dict(item) for item in list(prior_state.get("calibration_rows", [])) if isinstance(item, dict)],
            },
            "realized_evidence": {
                "selected_action": selected_action,
                "predicted_outcome": predicted_outcome,
                "realized_outcome": realized_outcome,
                "usage_total_tokens": int(realized.get("usage_total_tokens", realized_outcome.get("usage_total_tokens", 0)) or 0),
                "usage_rows": [dict(item) for item in list(realized.get("usage_rows", [])) if isinstance(item, dict)],
                "evidence_refs": [str(item).strip() for item in list(realized.get("evidence_refs", fixture.get("evidence_refs", []))) if str(item).strip()],
                "metadata": metadata,
            },
        }

    def load_archive_fixtures(self, *, thread_key: str | None, chat_name: str | None, channel: str, limit: int) -> list[dict[str, Any]]:
        context = {"thread_key": thread_key or "", "chat_name": chat_name or "", "channel": channel}
        rows = list(self.bridge.rag.thread_archive_rows(context, limit=max(1, int(limit)), include_synthetic=False))
        fixtures: list[dict[str, Any]] = []
        for index, row in enumerate(rows):
            metadata = dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}
            row_thread_key = self.canonical_thread_key(channel, str(row.get("thread_key", metadata.get("thread_key", thread_key or "")) or "").strip(), str(row.get("chat_name", metadata.get("chat_name", chat_name or "")) or "").strip())
            row_chat_name = str(row.get("chat_name", metadata.get("chat_name", chat_name or row_thread_key.replace("wechat:", "", 1))) or row_thread_key).strip()
            has_reply = bool(str(row.get("reply_text", "")) or str(metadata.get("reply_text", "")))
            response_quality = 0.76 if has_reply else 0.12
            relational_delta = 0.14 if has_reply else -0.12
            fixtures.append(
                self.normalize_fixture(
                    {
                        "fixture_id": str(row.get("id", f"archive-{index}")) or f"archive-{index}",
                        "channel": channel,
                        "thread_key": row_thread_key,
                        "chat_name": row_chat_name,
                        "query": str(row.get("user_text", metadata.get("archive_user_excerpt", "")) or "").strip(),
                        "expected_best_action": "reply_once" if has_reply else "defer_reply",
                        "scenario_tags": ["archive_fixture"],
                        "candidate_actions": ["reply_once", "defer_reply", "reply_multi", "silence"],
                        "realized_evidence": {
                            "selected_action": "reply_once" if has_reply else "defer_reply",
                            "predicted_outcome": dict(metadata.get("predicted_outcome", {})),
                            "realized_outcome": {
                                "response_quality": response_quality,
                                "relational_delta": relational_delta,
                                "identity_delta": 0.06 if has_reply else 0.0,
                                "risk": 0.18 if has_reply else 0.58,
                                "reply_latency_seconds": float(metadata.get("reply_latency_seconds", 180.0 if has_reply else 5400.0) or (180.0 if has_reply else 5400.0)),
                                "correction_count": int(metadata.get("correction_count", 0) or 0),
                                "initiative_success": 0.0,
                                "was_ignored": 0.0 if has_reply else 0.86,
                                "was_rewarding": response_quality,
                                "future_initiative_bias": 0.42 if has_reply else 0.04,
                                "future_resistance_bias": 0.12 if has_reply else 0.48,
                                "success": bool(has_reply),
                            },
                            "usage_total_tokens": int(metadata.get("usage_total_tokens", 0) or 0),
                            "evidence_refs": [f"archive:{row.get('id', index)}"],
                            "metadata": {**metadata, "initiative_expected_open": False, "overlong_reply": False, "stiffness_overflow": False},
                        },
                    },
                    source_type="archive_fixture",
                )
            )
        return fixtures

    def load_calibration_history_fixtures(self, *, thread_key: str | None, chat_name: str | None, channel: str, limit: int) -> list[dict[str, Any]]:
        history = self.bridge.graph.trace_outcome_history(channel=channel, thread_key=thread_key, chat_name=chat_name, limit=max(1, int(limit)))
        fixtures: list[dict[str, Any]] = []
        for index, row in enumerate(list(history.get("history", []))):
            metadata = dict(row.get("metadata", {}))
            current_thread_key = self.canonical_thread_key(channel, str(row.get("thread_key", thread_key or "") or ""), str(row.get("chat_name", chat_name or "") or ""))
            current_chat_name = str(row.get("chat_name", chat_name or current_thread_key.replace("wechat:", "", 1)) or current_thread_key).strip()
            fixtures.append(
                self.normalize_fixture(
                    {
                        "fixture_id": str(row.get("action_ref", f"history-{index}")) or f"history-{index}",
                        "channel": channel,
                        "thread_key": current_thread_key,
                        "chat_name": current_chat_name,
                        "query": str(metadata.get("query", row.get("action_ref", "")) or "").strip(),
                        "expected_best_action": str(row.get("action_type", "reply_once") or "reply_once"),
                        "scenario_tags": ["calibration_history_fixture"],
                        "candidate_actions": [str(row.get("action_type", "reply_once") or "reply_once"), "reply_once", "defer_reply"],
                        "realized_evidence": {
                            "selected_action": str(row.get("action_type", "reply_once") or "reply_once"),
                            "predicted_outcome": dict(metadata.get("predicted_outcome", {})),
                            "realized_outcome": {
                                "response_quality": float(metadata.get("observed_response_quality", row.get("was_rewarding", 0.0)) or 0.0),
                                "relational_delta": float(row.get("relational_delta", 0.0) or 0.0),
                                "identity_delta": float(row.get("identity_delta", 0.0) or 0.0),
                                "risk": float(metadata.get("observed_risk", row.get("was_ignored", 0.0)) or 0.0),
                                "reply_latency_seconds": float(metadata.get("reply_latency_seconds", 0.0) or 0.0),
                                "correction_count": int(metadata.get("correction_count", 0) or 0),
                                "initiative_success": float(metadata.get("initiative_success", 0.0) or 0.0),
                                "was_ignored": float(row.get("was_ignored", 0.0) or 0.0),
                                "was_rewarding": float(row.get("was_rewarding", 0.0) or 0.0),
                                "future_initiative_bias": float(row.get("future_initiative_bias", 0.0) or 0.0),
                                "future_resistance_bias": float(row.get("future_resistance_bias", 0.0) or 0.0),
                            },
                            "usage_total_tokens": int(metadata.get("usage_total_tokens", 0) or 0),
                            "usage_rows": [dict(item) for item in list(metadata.get("usage_rows", [])) if isinstance(item, dict)],
                            "evidence_refs": [str(item).strip() for item in list(metadata.get("evidence_refs", [])) if str(item).strip()],
                            "metadata": metadata,
                        },
                    },
                    source_type="calibration_history_fixture",
                )
            )
        return fixtures

    def load_fixtures(
        self,
        *,
        source_type: str,
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        normalized_source = str(source_type or "synthetic_fixture").strip() or "synthetic_fixture"
        if normalized_source == "synthetic_fixture":
            target = Path(fixture_path).resolve() if str(fixture_path or "").strip() else self.fixture_root()
            paths = [target] if target.is_file() else sorted(target.glob("*.json"))
            fixtures: list[dict[str, Any]] = []
            for path in paths:
                for item in self.read_fixture_file(path):
                    fixtures.append(self.normalize_fixture(item, source_type="synthetic_fixture"))
            return fixtures
        if normalized_source == "archive_fixture":
            return self.load_archive_fixtures(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)
        if normalized_source == "calibration_history_fixture":
            return self.load_calibration_history_fixtures(thread_key=thread_key, chat_name=chat_name, channel=channel, limit=limit)
        raise ValueError(f"Unsupported Stage14 source_type: {source_type}")

    def seed_subject_state(self, bridge: MemoryBridge, fixture: dict[str, Any]) -> dict[str, Any]:
        baseline = bridge.graph.replay_subject_snapshot(
            thread_key=str(fixture.get("thread_key", "") or ""),
            chat_name=str(fixture.get("chat_name", "") or ""),
            channel=str(fixture.get("channel", "wechat") or "wechat"),
        )
        prior = dict(fixture.get("prior_state", {}))
        subject = bridge.graph.update_subject_state(
            channel=str(fixture.get("channel", "wechat") or "wechat"),
            thread_key=str(fixture.get("thread_key", "") or ""),
            chat_name=str(fixture.get("chat_name", "") or ""),
            affect_state=dict(prior.get("affect_state", {})),
            drive_state=dict(prior.get("drive_state", {})),
            value_state=dict(prior.get("value_state", {})),
            conflict_state=dict(prior.get("conflict_state", {})),
            world_state=dict(prior.get("world_state", {})),
            initiative_state=dict(prior.get("initiative_state", {})) if isinstance(prior.get("initiative_state", {}), dict) else None,
            metadata={"stage14_fixture_id": str(fixture.get("fixture_id", "") or "")},
            note=f"stage14_seed:{fixture.get('fixture_id', '')}",
            source="stage14_replay",
        )
        return {
            "relationship_state": {**dict(baseline.get("relationship_state", {})), **dict(prior.get("relationship_state", {}))},
            "game_state": {**dict(baseline.get("game_state", {})), **dict(prior.get("game_state", {}))},
            "affect_state": dict(subject.get("affect_state", {})),
            "drive_state": dict(subject.get("drive_state", {})),
            "value_state": dict(subject.get("value_state", {})),
            "conflict_state": dict(subject.get("conflict_state", {})),
            "world_state": dict(subject.get("world_state", {})),
            "intent_state": dict(prior.get("intent_state", self.default_intent_state(str(fixture.get("query", "") or ""), dict(fixture.get("realized_evidence", {})).get("metadata", {})))),
        }

    def seed_calibration_rows(self, bridge: MemoryBridge, fixture: dict[str, Any]) -> None:
        prior = dict(fixture.get("prior_state", {}))
        for index, row in enumerate([dict(item) for item in list(prior.get("calibration_rows", [])) if isinstance(item, dict)]):
            predicted = dict(row.get("predicted_outcome", row.get("metadata", {}).get("predicted_outcome", {}))) if isinstance(row.get("predicted_outcome", row.get("metadata", {}).get("predicted_outcome", {})), dict) else {}
            realized = dict(row.get("realized_outcome", row.get("metadata", {}).get("realized_outcome", {}))) if isinstance(row.get("realized_outcome", row.get("metadata", {}).get("realized_outcome", {})), dict) else {}
            bridge.appraise_outcome(
                channel=str(fixture.get("channel", "wechat") or "wechat"),
                thread_key=str(fixture.get("thread_key", "") or ""),
                chat_name=str(fixture.get("chat_name", "") or ""),
                action_type=str(row.get("action_type", "reply_once") or "reply_once"),
                action_ref=str(row.get("action_ref", f"{fixture.get('fixture_id', 'fixture')}:seed:{index}") or f"{fixture.get('fixture_id', 'fixture')}:seed:{index}"),
                was_rewarding=float(realized.get("was_rewarding", realized.get("response_quality", 0.0)) or 0.0),
                was_ignored=float(realized.get("was_ignored", realized.get("risk", 0.0)) or 0.0),
                relational_delta=float(realized.get("relational_delta", 0.0) or 0.0),
                identity_delta=float(realized.get("identity_delta", 0.0) or 0.0),
                future_initiative_bias=float(realized.get("future_initiative_bias", 0.0) or 0.0),
                future_resistance_bias=float(realized.get("future_resistance_bias", 0.0) or 0.0),
                metadata={
                    **(dict(row.get("metadata", {})) if isinstance(row.get("metadata", {}), dict) else {}),
                    "predicted_outcome": predicted,
                    "reply_latency_seconds": float(realized.get("reply_latency_seconds", 0.0) or 0.0),
                    "initiative_success": float(realized.get("initiative_success", 0.0) or 0.0),
                    "correction_count": int(realized.get("correction_count", 0) or 0),
                    "usage_total_tokens": int(row.get("usage_total_tokens", realized.get("usage_total_tokens", 0)) or 0),
                    "usage_rows": [dict(item) for item in list(row.get("usage_rows", [])) if isinstance(item, dict)],
                    "evidence_refs": [str(item).strip() for item in list(row.get("evidence_refs", [])) if str(item).strip()],
                    "source": "stage14_replay_seed",
                },
            )

    @staticmethod
    def successful_turn(realized: dict[str, Any]) -> bool:
        if "success" in realized:
            return bool(realized.get("success"))
        return bool(
            float(realized.get("response_quality", realized.get("was_rewarding", 0.0)) or 0.0) >= 0.55
            and float(realized.get("was_ignored", realized.get("risk", 0.0)) or 0.0) <= 0.45
        )

    @staticmethod
    def overflow_flags(realized: dict[str, Any], metadata: dict[str, Any], selected_action: str) -> tuple[bool, bool]:
        overlong = bool(metadata.get("overlong_reply", realized.get("overlong_reply", False)))
        stiffness = bool(metadata.get("stiffness_overflow", realized.get("stiffness_overflow", False)))
        if not overlong and selected_action == "reply_multi" and int(realized.get("reply_length", 0) or 0) > 2:
            overlong = True
        return overlong, stiffness

    def evaluate_fixture(self, fixture: dict[str, Any]) -> dict[str, Any]:
        channel = str(fixture.get("channel", "wechat") or "wechat")
        thread_key = str(fixture.get("thread_key", "") or "")
        chat_name = str(fixture.get("chat_name", "") or thread_key)
        realized_evidence = dict(fixture.get("realized_evidence", {}))
        realized = dict(realized_evidence.get("realized_outcome", {}))
        metadata = dict(realized_evidence.get("metadata", {}))
        with tempfile.TemporaryDirectory(prefix="holo-stage14-") as temp_dir:
            temp_path = Path(temp_dir)
            isolated = MemoryBridge(
                self.bridge.repo_root,
                graph_db_path=temp_path / "mind_graph.sqlite3",
                rag=self.bridge.rag,
                vector_backend="milvus",
                milvus_uri=str((temp_path / "vector.db").resolve()),
            )
            try:
                seeded = self.seed_subject_state(isolated, fixture)
                self.seed_calibration_rows(isolated, fixture)
                context = {"channel": channel, "thread_key": thread_key, "chat_name": chat_name}
                simulations: list[dict[str, Any]] = []
                for action_type in list(fixture.get("candidate_actions", [])):
                    simulation = isolated._simulate_action_candidate(
                        action={"action_type": action_type},
                        query=str(fixture.get("query", "") or ""),
                        intent_state=dict(seeded.get("intent_state", {})),
                        relationship_state=dict(seeded.get("relationship_state", {})),
                        game_state=dict(seeded.get("game_state", {})),
                        affect_state=dict(seeded.get("affect_state", {})),
                        drive_state=dict(seeded.get("drive_state", {})),
                        value_state=dict(seeded.get("value_state", {})),
                        conflict_state=dict(seeded.get("conflict_state", {})),
                        world_state=dict(seeded.get("world_state", {})),
                        context=context,
                    )
                    simulation["score"] = self.metric_round(float(simulation.get("recommended_bias", 0.0) or 0.0))
                    simulations.append(simulation)
                simulations.sort(key=lambda item: float(item.get("score", 0.0) or 0.0), reverse=True)
                selected_action = str(realized_evidence.get("selected_action", "reply_once") or "reply_once")
                selected_simulation = next((dict(item) for item in simulations if str(item.get("action_type", "")) == selected_action), {})
                if not selected_simulation and simulations:
                    selected_simulation = dict(simulations[0])
                    selected_action = str(selected_simulation.get("action_type", selected_action) or selected_action)
                best_simulation = dict(simulations[0]) if simulations else {}
                predicted_outcome = dict(realized_evidence.get("predicted_outcome", {}))
                if not predicted_outcome:
                    predicted_outcome = {
                        "predicted_response_quality": float(selected_simulation.get("predicted_response_quality", 0.0) or 0.0),
                        "predicted_relational_delta": float(selected_simulation.get("predicted_relational_delta", 0.0) or 0.0),
                        "predicted_identity_delta": float(selected_simulation.get("predicted_identity_delta", 0.0) or 0.0),
                        "predicted_risk": float(selected_simulation.get("predicted_risk", 0.0) or 0.0),
                    }
                bucket = dict(selected_simulation.get("calibration_bucket", {}))
                scenario_bucket = str(bucket.get("scenario_bucket", "") or "").strip() or None
                before_rows = isolated.graph.list_action_calibration(channel=channel, thread_key=thread_key, chat_name=chat_name, action_type=selected_action, scenario_bucket=scenario_bucket, limit=1)
                before_support = int(before_rows[0].get("support_count", 0) or 0) if before_rows else 0
                appraisal = isolated.appraise_outcome(
                    channel=channel,
                    thread_key=thread_key,
                    chat_name=chat_name,
                    action_type=selected_action,
                    action_ref=str(fixture.get("fixture_id", "stage14-fixture") or "stage14-fixture"),
                    was_rewarding=float(realized.get("was_rewarding", realized.get("response_quality", 0.0)) or 0.0),
                    was_ignored=float(realized.get("was_ignored", realized.get("risk", 0.0)) or 0.0),
                    relational_delta=float(realized.get("relational_delta", 0.0) or 0.0),
                    identity_delta=float(realized.get("identity_delta", 0.0) or 0.0),
                    future_initiative_bias=float(realized.get("future_initiative_bias", 0.0) or 0.0),
                    future_resistance_bias=float(realized.get("future_resistance_bias", 0.0) or 0.0),
                    metadata={
                        **metadata,
                        "predicted_outcome": predicted_outcome,
                        "reply_latency_seconds": float(realized.get("reply_latency_seconds", 0.0) or 0.0),
                        "initiative_success": float(realized.get("initiative_success", 0.0) or 0.0),
                        "correction_count": int(realized.get("correction_count", 0) or 0),
                        "usage_total_tokens": int(realized_evidence.get("usage_total_tokens", 0) or 0),
                        "usage_rows": [dict(item) for item in list(realized_evidence.get("usage_rows", [])) if isinstance(item, dict)],
                        "evidence_refs": [str(item).strip() for item in list(realized_evidence.get("evidence_refs", [])) if str(item).strip()],
                        "source": "stage14_replay",
                        "query": str(fixture.get("query", "") or ""),
                    },
                )
                after_rows = isolated.graph.list_action_calibration(channel=channel, thread_key=thread_key, chat_name=chat_name, action_type=selected_action, scenario_bucket=scenario_bucket, limit=1)
                after_support = int(after_rows[0].get("support_count", 0) or 0) if after_rows else before_support
                prediction_trace = isolated.graph.trace_action_prediction_error(channel=channel, thread_key=thread_key, chat_name=chat_name, action_type=selected_action, limit=6)
                comparison = dict(list(prediction_trace.get("comparisons", []))[0]) if list(prediction_trace.get("comparisons", [])) else {}
                overlong_reply, stiffness_overflow = self.overflow_flags(realized, metadata, selected_action)
                false_initiative_block = bool(
                    metadata.get("initiative_expected_open", False)
                    and selected_action in {"silence", "defer_reply", "history_refresh"}
                    and selected_action != "proactive_ping"
                )
                return {
                    "fixture_id": str(fixture.get("fixture_id", "") or ""),
                    "source_type": str(fixture.get("source_type", "") or ""),
                    "thread_key": thread_key,
                    "chat_name": chat_name,
                    "channel": channel,
                    "scenario_tags": list(fixture.get("scenario_tags", [])),
                    "selected_action": selected_action,
                    "selected_action_score": self.metric_round(float(selected_simulation.get("score", 0.0) or 0.0)),
                    "best_available_action": str(best_simulation.get("action_type", "") or selected_action),
                    "best_available_action_score": self.metric_round(float(best_simulation.get("score", 0.0) or 0.0)),
                    "policy_regret_vs_best_available_action": self.metric_round(max(0.0, float(best_simulation.get("score", 0.0) or 0.0) - float(selected_simulation.get("score", 0.0) or 0.0))),
                    "expected_best_action": str(fixture.get("expected_best_action", "") or ""),
                    "best_action_matches_fixture": str(best_simulation.get("action_type", "") or "") == str(fixture.get("expected_best_action", "") or ""),
                    "predicted_outcome": predicted_outcome,
                    "realized_outcome": realized,
                    "prediction_error": dict(comparison.get("prediction_error", {})),
                    "calibration_bucket": bucket,
                    "calibration_support_delta": max(0, after_support - before_support),
                    "calibration_row": dict(after_rows[0]) if after_rows else {},
                    "usage_total_tokens": int(realized_evidence.get("usage_total_tokens", 0) or 0),
                    "usage_rows": [dict(item) for item in list(realized_evidence.get("usage_rows", [])) if isinstance(item, dict)],
                    "successful_turn": self.successful_turn(realized),
                    "false_initiative_block": false_initiative_block,
                    "overlong_reply": overlong_reply,
                    "stiffness_overflow": stiffness_overflow,
                    "simulated_candidates": simulations,
                    "appraisal": appraisal,
                }
            finally:
                isolated.activation.close()
                isolated.graph.close()

    def aggregate(self, fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        response_errors = [abs(float(item.get("prediction_error", {}).get("response_quality", 0.0) or 0.0)) for item in fixtures]
        relational_errors = [abs(float(item.get("prediction_error", {}).get("relational_delta", 0.0) or 0.0)) for item in fixtures]
        risk_errors = [abs(float(item.get("prediction_error", {}).get("risk", 0.0) or 0.0)) for item in fixtures]
        successful_turns = [item for item in fixtures if bool(item.get("successful_turn", False))]
        support_counter: Counter[str] = Counter()
        for item in fixtures:
            support_counter[str(item.get("selected_action", "") or "")] += int(item.get("calibration_support_delta", 0) or 0)
        total_tokens = sum(int(item.get("usage_total_tokens", 0) or 0) for item in fixtures)
        return {
            "response_quality_mae": self.metric_round(sum(response_errors) / len(response_errors)) if response_errors else 0.0,
            "relational_delta_mae": self.metric_round(sum(relational_errors) / len(relational_errors)) if relational_errors else 0.0,
            "risk_mae": self.metric_round(sum(risk_errors) / len(risk_errors)) if risk_errors else 0.0,
            "calibration_support_by_action_type": dict(sorted(support_counter.items())),
            "false_initiative_block_rate": self.metric_round(sum(1 for item in fixtures if bool(item.get("false_initiative_block", False))) / len(fixtures)) if fixtures else 0.0,
            "overlong_reply_rate": self.metric_round(sum(1 for item in fixtures if bool(item.get("overlong_reply", False))) / len(fixtures)) if fixtures else 0.0,
            "stiffness_overflow_rate": self.metric_round(sum(1 for item in fixtures if bool(item.get("stiffness_overflow", False))) / len(fixtures)) if fixtures else 0.0,
            "cost_per_successful_turn": self.metric_round(total_tokens / len(successful_turns)) if successful_turns else 0.0,
            "policy_regret_vs_best_available_action": self.metric_round(sum(float(item.get("policy_regret_vs_best_available_action", 0.0) or 0.0) for item in fixtures) / len(fixtures)) if fixtures else 0.0,
        }

    def raw_aggregate(self, fixtures: list[dict[str, Any]]) -> dict[str, Any]:
        response_errors = [abs(float(item.get("prediction_error", {}).get("response_quality", 0.0) or 0.0)) for item in fixtures]
        relational_errors = [abs(float(item.get("prediction_error", {}).get("relational_delta", 0.0) or 0.0)) for item in fixtures]
        risk_errors = [abs(float(item.get("prediction_error", {}).get("risk", 0.0) or 0.0)) for item in fixtures]
        successful_turns = [item for item in fixtures if bool(item.get("successful_turn", False))]
        total_tokens = sum(int(item.get("usage_total_tokens", 0) or 0) for item in fixtures)
        return {
            "response_quality_mae": sum(response_errors) / len(response_errors) if response_errors else 0.0,
            "relational_delta_mae": sum(relational_errors) / len(relational_errors) if relational_errors else 0.0,
            "risk_mae": sum(risk_errors) / len(risk_errors) if risk_errors else 0.0,
            "false_initiative_block_rate": sum(1 for item in fixtures if bool(item.get("false_initiative_block", False))) / len(fixtures) if fixtures else 0.0,
            "overlong_reply_rate": sum(1 for item in fixtures if bool(item.get("overlong_reply", False))) / len(fixtures) if fixtures else 0.0,
            "stiffness_overflow_rate": sum(1 for item in fixtures if bool(item.get("stiffness_overflow", False))) / len(fixtures) if fixtures else 0.0,
            "cost_per_successful_turn": total_tokens / len(successful_turns) if successful_turns else 0.0,
            "policy_regret_vs_best_available_action": sum(float(item.get("policy_regret_vs_best_available_action", 0.0) or 0.0) for item in fixtures) / len(fixtures) if fixtures else 0.0,
        }

    def write_artifact(self, report: dict[str, Any], *, artifact_dir: str | None = None) -> dict[str, Any]:
        root = Path(artifact_dir).resolve() if str(artifact_dir or "").strip() else self.artifact_root() / time.strftime("%Y%m%d-%H%M%S")
        root.mkdir(parents=True, exist_ok=True)
        json_path = root / "summary.json"
        md_path = root / "summary.md"
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        aggregate = dict(report.get("aggregate_metrics", {}))
        lines = [
            "# Stage14 Replay Summary",
            "",
            f"- run_id: `{report.get('run_id', '')}`",
            f"- source_type: `{report.get('source_type', '')}`",
            f"- fixture_count: `{report.get('fixture_count', 0)}`",
            f"- response_quality_mae: `{aggregate.get('response_quality_mae', 0.0)}`",
            f"- relational_delta_mae: `{aggregate.get('relational_delta_mae', 0.0)}`",
            f"- risk_mae: `{aggregate.get('risk_mae', 0.0)}`",
            f"- false_initiative_block_rate: `{aggregate.get('false_initiative_block_rate', 0.0)}`",
            f"- overlong_reply_rate: `{aggregate.get('overlong_reply_rate', 0.0)}`",
            f"- stiffness_overflow_rate: `{aggregate.get('stiffness_overflow_rate', 0.0)}`",
            f"- cost_per_successful_turn: `{aggregate.get('cost_per_successful_turn', 0.0)}`",
            f"- policy_regret_vs_best_available_action: `{aggregate.get('policy_regret_vs_best_available_action', 0.0)}`",
            "",
            "## Fixtures",
            "",
        ]
        for item in list(report.get("fixtures", [])):
            lines.append(f"- `{item.get('fixture_id', '')}`: selected=`{item.get('selected_action', '')}` best=`{item.get('best_available_action', '')}` regret=`{item.get('policy_regret_vs_best_available_action', 0.0)}` tokens=`{item.get('usage_total_tokens', 0)}`")
        md_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return {"artifact_dir": str(root), "summary_json": str(json_path), "summary_md": str(md_path)}

    def run(
        self,
        *,
        source_type: str = "synthetic_fixture",
        fixture_path: str | None = None,
        thread_key: str | None = None,
        chat_name: str | None = None,
        channel: str = "wechat",
        limit: int = 8,
        artifact_dir: str | None = None,
        mode: str = "all",
    ) -> dict[str, Any]:
        fixtures = self.load_fixtures(
            source_type=source_type,
            fixture_path=fixture_path,
            thread_key=thread_key,
            chat_name=chat_name,
            channel=channel,
            limit=limit,
        )
        evaluated = [self.evaluate_fixture(dict(item)) for item in fixtures]
        report = {
            "run_id": f"stage14-{int(time.time())}",
            "source_type": source_type,
            "mode": mode,
            "fixture_count": len(evaluated),
            "fixtures": evaluated,
            "aggregate_metrics": self.aggregate(evaluated),
            "raw_aggregate_metrics": self.raw_aggregate(evaluated),
        }
        report["artifacts"] = self.write_artifact(report, artifact_dir=artifact_dir)
        if mode == "calibration":
            report["fixtures"] = [
                {
                    key: value
                    for key, value in item.items()
                    if key in {"fixture_id", "source_type", "thread_key", "chat_name", "channel", "selected_action", "predicted_outcome", "realized_outcome", "prediction_error", "calibration_bucket", "calibration_support_delta", "calibration_row", "usage_total_tokens"}
                }
                for item in evaluated
            ]
        elif mode == "policy":
            report["fixtures"] = [
                {
                    key: value
                    for key, value in item.items()
                    if key in {"fixture_id", "source_type", "thread_key", "chat_name", "channel", "selected_action", "selected_action_score", "best_available_action", "best_available_action_score", "policy_regret_vs_best_available_action", "expected_best_action", "best_action_matches_fixture", "false_initiative_block", "overlong_reply", "stiffness_overflow", "usage_total_tokens", "simulated_candidates"}
                }
                for item in evaluated
            ]
        return report
