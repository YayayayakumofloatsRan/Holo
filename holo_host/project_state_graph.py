from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .common import compact_text, stable_digest, utc_now

PROJECT_STATE_GRAPH_SCHEMA = "holo.stage155.project_state_graph.v1"

NODE_TYPES = {
    "Project",
    "Goal",
    "Task",
    "Subtask",
    "Decision",
    "OpenQuestion",
    "Artifact",
    "Source",
    "Assumption",
    "Risk",
    "Result",
    "NextAction",
}

EDGE_TYPES = {
    "depends_on",
    "blocks",
    "supports",
    "contradicts",
    "completed_by",
    "requires_tool",
    "verified_by",
    "reopened_by",
    "derived_from",
}

OPEN_STATUSES = {"", "open", "active", "blocked", "pending", "accepted", "available"}
CLOSED_STATUSES = {"completed", "done", "closed", "resolved", "cancelled", "canceled"}


def _json_loads(value: Any, default: Any) -> Any:
    if value in (None, ""):
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return default


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _clean_text(value: Any, *, limit: int = 240) -> str:
    return compact_text(str(value or "").strip(), limit)


def _slug_node_id(project: str, node_type: str, title: str) -> str:
    return "psg:" + stable_digest(project.lower(), node_type, title.lower(), limit=20)


def _slug_edge_id(project: str, source: str, target: str, edge_type: str) -> str:
    return "psge:" + stable_digest(project.lower(), source, target, edge_type, limit=20)


def _dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    if isinstance(row, sqlite3.Row):
        return dict(row)
    return {}


def _row_to_node(row: Any) -> dict[str, Any]:
    payload = _dict(row)
    if not payload:
        return {}
    payload["evidence"] = _json_loads(payload.pop("evidence_json", "{}"), {})
    payload["metadata"] = _json_loads(payload.pop("metadata_json", "{}"), {})
    return payload


def _row_to_edge(row: Any) -> dict[str, Any]:
    payload = _dict(row)
    if not payload:
        return {}
    payload["evidence"] = _json_loads(payload.pop("evidence_json", "{}"), {})
    payload["metadata"] = _json_loads(payload.pop("metadata_json", "{}"), {})
    return payload


def _coerce_connection(db_or_store: Any) -> tuple[sqlite3.Connection, bool]:
    if isinstance(db_or_store, sqlite3.Connection):
        db_or_store.row_factory = sqlite3.Row
        return db_or_store, False
    conn = getattr(db_or_store, "conn", None)
    if isinstance(conn, sqlite3.Connection):
        conn.row_factory = sqlite3.Row
        return conn, False
    path = Path(db_or_store)
    path.parent.mkdir(parents=True, exist_ok=True)
    owned = sqlite3.connect(path)
    owned.row_factory = sqlite3.Row
    owned.execute("PRAGMA foreign_keys = ON")
    owned.execute("PRAGMA journal_mode = WAL")
    return owned, True


class ProjectStateGraph:
    """Workspace-local graph for project continuity state.

    This graph is deliberately narrow: it stores project state evidence and
    exposes summaries. It does not call providers, execute tools, or write
    memory.
    """

    def __init__(self, db_or_store: Any):
        self.conn, self._owns_connection = _coerce_connection(db_or_store)

    def close(self) -> None:
        if self._owns_connection:
            self.conn.close()

    def ensure_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS project_state_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                node_id TEXT NOT NULL UNIQUE,
                node_type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                evidence_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_state_nodes_project_type
                ON project_state_nodes(project, node_type);
            CREATE INDEX IF NOT EXISTS idx_project_state_nodes_project_status
                ON project_state_nodes(project, status);

            CREATE TABLE IF NOT EXISTS project_state_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                edge_id TEXT NOT NULL UNIQUE,
                source_node_id TEXT NOT NULL,
                target_node_id TEXT NOT NULL,
                edge_type TEXT NOT NULL,
                evidence_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_state_edges_project_type
                ON project_state_edges(project, edge_type);
            CREATE INDEX IF NOT EXISTS idx_project_state_edges_source
                ON project_state_edges(source_node_id);
            CREATE INDEX IF NOT EXISTS idx_project_state_edges_target
                ON project_state_edges(target_node_id);
            """
        )
        self.conn.commit()

    def upsert_node(
        self,
        project: str,
        node_type: str,
        title: str,
        *,
        summary: str = "",
        status: str = "open",
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        node_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        project_name = _clean_text(project or "Holo", limit=120)
        resolved_type = node_type if node_type in NODE_TYPES else "Task"
        resolved_title = _clean_text(title, limit=260)
        if not resolved_title:
            raise ValueError("project state node title is required")
        resolved_status = _clean_text(status or "open", limit=64).lower()
        resolved_id = node_id or _slug_node_id(project_name, resolved_type, resolved_title)
        now = utc_now()
        existing = self.conn.execute(
            "SELECT * FROM project_state_nodes WHERE node_id = ?",
            (resolved_id,),
        ).fetchone()
        if existing:
            old = _row_to_node(existing)
            merged_evidence = {**dict(old.get("evidence", {})), **dict(evidence or {})}
            merged_metadata = {**dict(old.get("metadata", {})), **dict(metadata or {})}
            self.conn.execute(
                """
                UPDATE project_state_nodes
                   SET project = ?, node_type = ?, title = ?, summary = ?, status = ?,
                       evidence_json = ?, metadata_json = ?, updated_at = ?
                 WHERE node_id = ?
                """,
                (
                    project_name,
                    resolved_type,
                    resolved_title,
                    _clean_text(summary or old.get("summary", ""), limit=600),
                    resolved_status or str(old.get("status", "open")),
                    _json_dumps(merged_evidence),
                    _json_dumps(merged_metadata),
                    now,
                    resolved_id,
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO project_state_nodes (
                    project, node_id, node_type, title, summary, status,
                    evidence_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_name,
                    resolved_id,
                    resolved_type,
                    resolved_title,
                    _clean_text(summary, limit=600),
                    resolved_status,
                    _json_dumps(evidence or {}),
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM project_state_nodes WHERE node_id = ?", (resolved_id,)).fetchone()
        return _row_to_node(row)

    def add_edge(
        self,
        project: str,
        source_node_id: str,
        target_node_id: str,
        edge_type: str,
        *,
        evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        edge_id: str | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        project_name = _clean_text(project or "Holo", limit=120)
        resolved_type = edge_type if edge_type in EDGE_TYPES else "supports"
        resolved_id = edge_id or _slug_edge_id(project_name, source_node_id, target_node_id, resolved_type)
        now = utc_now()
        existing = self.conn.execute(
            "SELECT * FROM project_state_edges WHERE edge_id = ?",
            (resolved_id,),
        ).fetchone()
        if existing:
            old = _row_to_edge(existing)
            merged_evidence = {**dict(old.get("evidence", {})), **dict(evidence or {})}
            merged_metadata = {**dict(old.get("metadata", {})), **dict(metadata or {})}
            self.conn.execute(
                """
                UPDATE project_state_edges
                   SET project = ?, source_node_id = ?, target_node_id = ?, edge_type = ?,
                       evidence_json = ?, metadata_json = ?, updated_at = ?
                 WHERE edge_id = ?
                """,
                (
                    project_name,
                    source_node_id,
                    target_node_id,
                    resolved_type,
                    _json_dumps(merged_evidence),
                    _json_dumps(merged_metadata),
                    now,
                    resolved_id,
                ),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO project_state_edges (
                    project, edge_id, source_node_id, target_node_id, edge_type,
                    evidence_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    project_name,
                    resolved_id,
                    source_node_id,
                    target_node_id,
                    resolved_type,
                    _json_dumps(evidence or {}),
                    _json_dumps(metadata or {}),
                    now,
                    now,
                ),
            )
        self.conn.commit()
        row = self.conn.execute("SELECT * FROM project_state_edges WHERE edge_id = ?", (resolved_id,)).fetchone()
        return _row_to_edge(row)

    def update_task_status(
        self,
        project: str,
        title_or_node_id: str,
        status: str,
        *,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        project_name = _clean_text(project or "Holo", limit=120)
        target = _clean_text(title_or_node_id, limit=260)
        row = self.conn.execute(
            """
            SELECT * FROM project_state_nodes
             WHERE project = ?
               AND node_type IN ('Task', 'Subtask', 'NextAction')
               AND (node_id = ? OR title = ?)
             ORDER BY updated_at DESC
             LIMIT 1
            """,
            (project_name, target, target),
        ).fetchone()
        if not row:
            raise KeyError(f"task not found: {title_or_node_id}")
        node = _row_to_node(row)
        return self.upsert_node(
            project_name,
            node["node_type"],
            node["title"],
            summary=node.get("summary", ""),
            status=status,
            evidence={**dict(node.get("evidence", {})), **dict(evidence or {})},
            metadata=dict(node.get("metadata", {})),
            node_id=node["node_id"],
        )

    def _nodes(self, project: str, *, limit: int = 200) -> list[dict[str, Any]]:
        self.ensure_schema()
        rows = self.conn.execute(
            """
            SELECT * FROM project_state_nodes
             WHERE project = ?
             ORDER BY updated_at DESC, id DESC
             LIMIT ?
            """,
            (_clean_text(project or "Holo", limit=120), int(limit)),
        ).fetchall()
        return [_row_to_node(row) for row in rows]

    def _edges(self, project: str, *, limit: int = 300) -> list[dict[str, Any]]:
        self.ensure_schema()
        rows = self.conn.execute(
            """
            SELECT * FROM project_state_edges
             WHERE project = ?
             ORDER BY updated_at DESC, id DESC
             LIMIT ?
            """,
            (_clean_text(project or "Holo", limit=120), int(limit)),
        ).fetchall()
        return [_row_to_edge(row) for row in rows]

    def get_project_state(self, project: str, *, limit: int = 200) -> dict[str, Any]:
        project_name = _clean_text(project or "Holo", limit=120)
        nodes = self._nodes(project_name, limit=limit)
        edges = self._edges(project_name, limit=limit * 2)
        projects = [node for node in nodes if node.get("node_type") == "Project"]
        active_project = projects[0] if projects else {"node_type": "Project", "title": project_name, "status": "implicit"}
        active_tasks = [
            node
            for node in nodes
            if node.get("node_type") in {"Task", "Subtask"} and str(node.get("status", "") or "").lower() not in CLOSED_STATUSES
        ][:10]
        open_questions = [
            node
            for node in nodes
            if node.get("node_type") == "OpenQuestion" and str(node.get("status", "") or "").lower() not in CLOSED_STATUSES
        ][:10]
        latest_decisions = [node for node in nodes if node.get("node_type") == "Decision"][:10]
        next_actions = [
            node
            for node in nodes
            if node.get("node_type") == "NextAction" and str(node.get("status", "") or "").lower() not in CLOSED_STATUSES
        ][:10]
        blocked_items = [
            node
            for node in nodes
            if str(node.get("status", "") or "").lower() == "blocked" or node.get("node_type") == "Risk"
        ][:10]
        by_status: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            by_status.setdefault(str(node.get("status", "") or "open").lower(), []).append(node)
        return {
            "schema": PROJECT_STATE_GRAPH_SCHEMA,
            "stage": "stage155-project-state-graph",
            "project": project_name,
            "generated_at": utc_now(),
            "active_project": active_project,
            "active_tasks": active_tasks,
            "open_questions": open_questions,
            "latest_decisions": latest_decisions,
            "next_actions": next_actions,
            "blocked_items": blocked_items,
            "nodes": nodes,
            "edges": edges,
            "nodes_by_status": by_status,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "open_loop_count": len(open_questions) + len(blocked_items) + len(active_tasks),
            "next_action_count": len(next_actions),
            "read_only": True,
        }

    def get_open_loops(self, project: str, *, limit: int = 50) -> dict[str, Any]:
        state = self.get_project_state(project, limit=max(limit, 50))
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for node in [*state.get("open_questions", []), *state.get("blocked_items", []), *state.get("active_tasks", [])]:
            node_id = str(node.get("node_id", "") or "")
            if node_id and node_id not in seen:
                seen.add(node_id)
                items.append(node)
        return {
            "schema": PROJECT_STATE_GRAPH_SCHEMA,
            "project": state.get("project", project),
            "mode": "open_loops",
            "items": items[:limit],
            "count": len(items[:limit]),
        }

    def get_next_actions(self, project: str, *, limit: int = 50) -> dict[str, Any]:
        state = self.get_project_state(project, limit=max(limit, 50))
        return {
            "schema": PROJECT_STATE_GRAPH_SCHEMA,
            "project": state.get("project", project),
            "mode": "next_actions",
            "items": list(state.get("next_actions", []))[:limit],
            "count": len(list(state.get("next_actions", []))[:limit]),
        }

    def apply_update_report(self, report: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(report, dict):
            return _empty_update_report("", status="skipped")
        project = str(report.get("project", "") or "Holo")
        applied_nodes: list[dict[str, Any]] = []
        applied_edges: list[dict[str, Any]] = []
        for node in list(report.get("nodes", []) or []):
            if not isinstance(node, dict):
                continue
            applied_nodes.append(
                self.upsert_node(
                    project,
                    str(node.get("node_type", "") or "Task"),
                    str(node.get("title", "") or ""),
                    summary=str(node.get("summary", "") or ""),
                    status=str(node.get("status", "") or "open"),
                    evidence=dict(node.get("evidence", {}) or {}),
                    metadata=dict(node.get("metadata", {}) or {}),
                    node_id=str(node.get("node_id", "") or "") or None,
                )
            )
        for edge in list(report.get("edges", []) or []):
            if not isinstance(edge, dict):
                continue
            source = str(edge.get("source_node_id", "") or "")
            target = str(edge.get("target_node_id", "") or "")
            if not source or not target:
                continue
            applied_edges.append(
                self.add_edge(
                    project,
                    source,
                    target,
                    str(edge.get("edge_type", "") or "supports"),
                    evidence=dict(edge.get("evidence", {}) or {}),
                    metadata=dict(edge.get("metadata", {}) or {}),
                    edge_id=str(edge.get("edge_id", "") or "") or None,
                )
            )
        state = self.get_project_state(project)
        return {
            "schema": PROJECT_STATE_GRAPH_SCHEMA,
            "stage": "stage155-project-state-graph",
            "project": project,
            "status": "applied" if applied_nodes or applied_edges else "no_updates",
            "applied_count": len(applied_nodes) + len(applied_edges),
            "applied_nodes": applied_nodes,
            "applied_edges": applied_edges,
            "project_state_graph": state,
        }


def _empty_update_report(project: str, *, status: str = "no_updates") -> dict[str, Any]:
    return {
        "schema": PROJECT_STATE_GRAPH_SCHEMA,
        "stage": "stage155-project-state-graph",
        "project": project or "Holo",
        "status": status,
        "nodes": [],
        "edges": [],
        "deterministic": True,
    }


def _split_candidate_sentences(text: str) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s+|[\n\r]+", text)
    candidates: list[str] = []
    for part in parts:
        cleaned = part.strip(" -\t")
        if cleaned:
            candidates.append(cleaned)
    return candidates or [text]


_PREFIX_PATTERNS: list[tuple[str, str, str]] = [
    ("Task", "active", r"(?:^|[.;。；!?！？]\s*)(?:Task|任务)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("Decision", "accepted", r"(?:^|[.;。；!?！？]\s*)(?:Decision|决定)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("OpenQuestion", "open", r"(?:^|[.;。；!?！？]\s*)(?:Open question|Question|开放问题|问题)\s*[:：]\s*([^.;。；!?！？]+[?？]?)"),
    ("Risk", "open", r"(?:^|[.;。；!?！？]\s*)(?:Risk|风险)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("NextAction", "open", r"(?:^|[.;。；!?！？]\s*)(?:Next action|下一步|下一步行动)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("Goal", "active", r"(?:^|[.;。；!?！？]\s*)(?:Goal|目标)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("Artifact", "available", r"(?:^|[.;。；!?！？]\s*)(?:Artifact|产物|文件)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("Assumption", "open", r"(?:^|[.;。；!?！？]\s*)(?:Assumption|假设)\s*[:：]\s*([^.;。；!?！？]+)"),
    ("Result", "completed", r"(?:^|[.;。；!?！？]\s*)(?:Result|结果)\s*[:：]\s*([^.;。；!?！？]+)"),
]


def detect_project_state_updates(
    *,
    project: str,
    user_text: str,
    reply_text: str = "",
    metadata: dict[str, Any] | None = None,
    source_ref: str = "",
) -> dict[str, Any]:
    """Extract explicit project-state statements from a turn.

    The extractor is conservative by design. It captures explicit labels such
    as "Task:" and "Decision:" first, with a small fallback for common project
    phrasing. This avoids treating ordinary chat logs as durable project state.
    """

    project_name = _clean_text(project or "Holo", limit=120)
    evidence = {
        "source_ref": source_ref,
        "source": "stage155_project_state_detector",
        "detected_from": "current_turn",
    }
    nodes: list[dict[str, Any]] = [
        {
            "node_id": _slug_node_id(project_name, "Project", project_name),
            "node_type": "Project",
            "title": project_name,
            "summary": project_name,
            "status": "active",
            "evidence": evidence,
            "metadata": dict(metadata or {}),
        }
    ]
    text = " ".join(part for part in [user_text, reply_text] if part)
    seen_titles = {(project_name, "Project", project_name.lower())}
    for node_type, status, pattern in _PREFIX_PATTERNS:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            title = _clean_text(match.group(1), limit=260).strip(" .。")
            if not title:
                continue
            key = (project_name, node_type, title.lower())
            if key in seen_titles:
                continue
            seen_titles.add(key)
            nodes.append(
                {
                    "node_id": _slug_node_id(project_name, node_type, title),
                    "node_type": node_type,
                    "title": title,
                    "summary": title,
                    "status": status,
                    "evidence": evidence,
                    "metadata": dict(metadata or {}),
                }
            )
    if len(nodes) == 1:
        for sentence in _split_candidate_sentences(user_text):
            lowered = sentence.lower()
            node_type = ""
            status = "open"
            if lowered.startswith(("we need to ", "need to ", "todo ")):
                node_type, status = "Task", "active"
            elif "需要" in sentence and len(sentence) <= 80:
                node_type, status = "Task", "active"
            elif lowered.startswith(("decided ", "we decided ")):
                node_type, status = "Decision", "accepted"
            if not node_type:
                continue
            title = _clean_text(sentence, limit=260).strip(" .。")
            nodes.append(
                {
                    "node_id": _slug_node_id(project_name, node_type, title),
                    "node_type": node_type,
                    "title": title,
                    "summary": title,
                    "status": status,
                    "evidence": evidence,
                    "metadata": dict(metadata or {}),
                }
            )
    edges: list[dict[str, Any]] = []
    project_id = nodes[0]["node_id"]
    for node in nodes[1:]:
        edges.append(
            {
                "edge_id": _slug_edge_id(project_name, project_id, node["node_id"], "supports"),
                "source_node_id": project_id,
                "target_node_id": node["node_id"],
                "edge_type": "supports",
                "evidence": evidence,
                "metadata": {"detected_relation": "project_contains_state"},
            }
        )
    return {
        "schema": PROJECT_STATE_GRAPH_SCHEMA,
        "stage": "stage155-project-state-graph",
        "project": project_name,
        "status": "detected" if len(nodes) > 1 else "no_updates",
        "nodes": nodes if len(nodes) > 1 else [],
        "edges": edges,
        "deterministic": True,
    }


def summarize_project_state_for_prompt(report: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(report or {})
    if payload.get("schema") != PROJECT_STATE_GRAPH_SCHEMA:
        return {}
    return {
        "active_project": payload.get("active_project", {}),
        "active_tasks": list(payload.get("active_tasks", []) or [])[:6],
        "open_questions": list(payload.get("open_questions", []) or [])[:6],
        "latest_decisions": list(payload.get("latest_decisions", []) or [])[:5],
        "next_actions": list(payload.get("next_actions", []) or [])[:6],
        "blocked_items": list(payload.get("blocked_items", []) or [])[:6],
        "node_count": int(payload.get("node_count", 0) or 0),
        "edge_count": int(payload.get("edge_count", 0) or 0),
    }


def render_project_state_cli(report: dict[str, Any], *, mode: str = "summary") -> str:
    payload = dict(report or {})
    project = str(payload.get("project", "") or "Holo")
    if mode == "open_loops":
        items = list(payload.get("items", []) or [])
        lines = [f"Project State: {project} open loops ({len(items)})"]
        for item in items:
            lines.append(f"- [{item.get('node_type', 'Item')}/{item.get('status', '')}] {item.get('title', '')}")
        return "\n".join(lines)
    if mode == "next_actions":
        items = list(payload.get("items", []) or [])
        lines = [f"Project State: {project} next actions ({len(items)})"]
        for item in items:
            lines.append(f"- {item.get('title', '')}")
        return "\n".join(lines)
    state = summarize_project_state_for_prompt(payload)
    lines = [
        f"Project State: {project}",
        f"nodes={payload.get('node_count', 0)} edges={payload.get('edge_count', 0)}",
    ]
    for label, key in [
        ("Active tasks", "active_tasks"),
        ("Open questions", "open_questions"),
        ("Latest decisions", "latest_decisions"),
        ("Next actions", "next_actions"),
        ("Blocked items", "blocked_items"),
    ]:
        items = list(state.get(key, []) or [])
        lines.append(f"{label}: {len(items)}")
        for item in items[:5]:
            lines.append(f"- {item.get('title', '')}")
    return "\n".join(lines)
