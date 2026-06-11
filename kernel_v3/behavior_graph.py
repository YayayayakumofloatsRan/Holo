from __future__ import annotations

import json
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from kernel_v3.context.redaction import Redactor
from kernel_v3.contracts import Contract, JsonObject, LedgerRecord
from kernel_v3.journal import JournalStore


MAX_GRAPH_NODES = 800
MAX_GRAPH_EDGES = 1600
_REDACTOR = Redactor()


@dataclass(frozen=True, kw_only=True)
class BehaviorGraphNode(Contract):
    node_id: str
    node_type: str
    label: str
    record_id: str | None = None
    run_id: str | None = None
    step_id: str | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class BehaviorGraphEdge(Contract):
    source: str
    target: str
    edge_type: str
    label: str | None = None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class BehaviorGraph(Contract):
    schema: str
    task_id: str
    nodes: list[JsonObject]
    edges: list[JsonObject]
    diagnostics: JsonObject


class BehaviorGraphBuilder:
    def __init__(self, journal: JournalStore) -> None:
        self.journal = journal

    def build_task_graph(self, task_id: str, *, max_nodes: int = MAX_GRAPH_NODES) -> BehaviorGraph:
        records = self.journal.records(task_id=task_id)
        builder = _GraphAccumulator(task_id=task_id, max_nodes=max_nodes)
        builder.add_node(
            BehaviorGraphNode(
                node_id=f"task:{task_id}",
                node_type="task",
                label=f"Task {task_id}",
                metadata={"record_count": len(records)},
            )
        )
        previous: str | None = None
        request_nodes: dict[str, str] = {}
        action_nodes: dict[str, str] = {}
        observation_nodes: dict[str, str] = {}
        retrieval_plan_nodes: dict[str, str] = {}
        search_nodes_by_goal: dict[str, list[str]] = {}
        source_nodes: dict[str, str] = {}
        fetch_nodes_by_source: dict[str, str] = {}
        document_nodes: dict[str, str] = {}
        evidence_nodes: dict[str, str] = {}

        for record in records:
            node = _node_for_record(record)
            if node is None:
                continue
            if not builder.add_node(node):
                builder.truncated_records += 1
                continue
            builder.add_edge("task:" + task_id, node.node_id, "contains")
            if previous is not None:
                builder.add_edge(previous, node.node_id, "next")
            previous = node.node_id

            data = record.data
            if record.kind == "processor_request":
                request_id = _text(data.get("request_id"))
                if request_id:
                    request_nodes[request_id] = node.node_id
            elif record.kind == "processor_result":
                request_id = _text(data.get("request_id"))
                if request_id and request_id in request_nodes:
                    builder.add_edge(request_nodes[request_id], node.node_id, "processor_result", _status_label(data))
            elif record.kind == "action":
                action_id = _text(data.get("action_id"))
                if action_id:
                    action_nodes[action_id] = node.node_id
            elif record.kind == "observation":
                observation_id = _text(data.get("observation_id"))
                if observation_id:
                    observation_nodes[observation_id] = node.node_id
                action_id = _text(data.get("action_id"))
                if action_id and action_id in action_nodes:
                    builder.add_edge(action_nodes[action_id], node.node_id, "observed", _status_label(data))
            elif record.kind == "feedback":
                observation_id = _text(data.get("observation_id"))
                if observation_id and observation_id in observation_nodes:
                    builder.add_edge(observation_nodes[observation_id], node.node_id, "evaluated")

            if record.kind == "retrieval_query_plan":
                plan_id = _text(data.get("plan_id"))
                if plan_id:
                    retrieval_plan_nodes[plan_id] = node.node_id
            elif record.kind == "retrieval_search_attempt":
                goal_id = _text(data.get("goal_id"))
                if goal_id:
                    search_nodes_by_goal.setdefault(goal_id, []).append(node.node_id)
                    for plan_node_id in retrieval_plan_nodes.values():
                        builder.add_edge(plan_node_id, node.node_id, "searches")
                for source in _list_of_dicts(data.get("sources"))[:64]:
                    source_node = _source_node(source)
                    if builder.add_node(source_node):
                        source_id = _text(source.get("source_id")) or source_node.node_id.removeprefix("source:")
                        source_nodes[source_id] = source_node.node_id
                        builder.add_edge(node.node_id, source_node.node_id, "found_source", _score_label(source))
            elif record.kind == "retrieval_fetch_attempt":
                source_id = _text(data.get("source_id"))
                if source_id and source_id in source_nodes:
                    builder.add_edge(source_nodes[source_id], node.node_id, "fetched", _status_label(data))
                    fetch_nodes_by_source[source_id] = node.node_id
                artifact_id = _text(data.get("artifact_id"))
                if artifact_id:
                    artifact_node = BehaviorGraphNode(
                        node_id=f"artifact:{artifact_id}",
                        node_type="artifact",
                        label=_preview(f"Artifact {artifact_id}", 80),
                        metadata={"artifact_id": artifact_id, "payload_hash": _text(data.get("payload_hash"))},
                    )
                    if builder.add_node(artifact_node):
                        builder.add_edge(node.node_id, artifact_node.node_id, "stores_raw_body")
            elif record.kind == "retrieval_extraction":
                document = data.get("document") if isinstance(data.get("document"), dict) else {}
                document_id = _text(document.get("document_id")) or _text(data.get("document_id"))
                if document_id:
                    document_node = BehaviorGraphNode(
                        node_id=f"document:{document_id}",
                        node_type="document",
                        label=_preview(_text(document.get("title")) or document_id, 120),
                        record_id=record.record_id,
                        run_id=record.run_id,
                        step_id=record.step_id,
                        metadata={
                            "document_id": document_id,
                            "artifact_id": _text(document.get("artifact_id")),
                            "span_count": len(_list_of_dicts(data.get("spans"))),
                        },
                    )
                    if builder.add_node(document_node):
                        document_nodes[document_id] = document_node.node_id
                        artifact_id = _text(document.get("artifact_id"))
                        if artifact_id:
                            builder.add_edge(f"artifact:{artifact_id}", document_node.node_id, "extracted_document")
                        builder.add_edge(document_node.node_id, node.node_id, "extracted_spans")
            elif record.kind == "retrieval_evidence":
                evidence_id = _text(data.get("evidence_id"))
                if evidence_id:
                    evidence_nodes[evidence_id] = node.node_id
                source_id = _text(data.get("source_id"))
                if source_id and source_id in fetch_nodes_by_source:
                    builder.add_edge(fetch_nodes_by_source[source_id], node.node_id, "supports_evidence", _score_label(data))
                artifact_id = _text(data.get("artifact_id"))
                if artifact_id:
                    builder.add_edge(f"artifact:{artifact_id}", node.node_id, "supports_evidence")
            elif record.kind == "retrieval_citation":
                evidence_id = _text(data.get("evidence_id"))
                if evidence_id and evidence_id in evidence_nodes:
                    builder.add_edge(evidence_nodes[evidence_id], node.node_id, "cited_by")
            elif record.kind in {"agent_final_answer", "semantic_task_plan_final_answer"}:
                for ref in _string_list(data.get("citation_refs")):
                    citation_node_id = _find_node_by_record_data(builder.nodes, "citation_id", ref)
                    if citation_node_id:
                        builder.add_edge(citation_node_id, node.node_id, "used_in_answer")
            elif record.kind == "agent_failure_report":
                for action_name in _string_list(data.get("attempted_actions")):
                    for action_id, action_node_id in action_nodes.items():
                        if action_name in action_node_id or action_name in action_id:
                            builder.add_edge(action_node_id, node.node_id, "attempted_before_failure")

        return builder.to_graph()


def load_benchmark_result_records(path: Path | str) -> list[JsonObject]:
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    stripped = text.strip()
    if not stripped:
        return []
    if source.suffix.lower() in {".jsonl", ".ndjson"}:
        return [_json_object(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(stripped)
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("results", "items", "records", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
        if "item_id" in payload or "question" in payload:
            return [payload]
    raise ValueError(f"unsupported benchmark result graph input: {source}")


def build_benchmark_result_graph(
    results: list[JsonObject],
    *,
    benchmark_id: str = "finance",
    max_items: int = 200,
) -> BehaviorGraph:
    benchmark_node_id = f"benchmark:{_safe_node_id(benchmark_id)}"
    builder = _GraphAccumulator(task_id=benchmark_node_id, max_nodes=max(MAX_GRAPH_NODES, max_items * 6 + 32))
    summary = _benchmark_result_summary(results)
    builder.add_node(
        BehaviorGraphNode(
            node_id=benchmark_node_id,
            node_type="benchmark",
            label=f"Benchmark {benchmark_id}",
            metadata={**summary, "item_count": len(results), "shown_item_count": min(len(results), max_items)},
        )
    )

    status_nodes: dict[str, str] = {}
    category_nodes: dict[str, str] = {}
    reason_nodes: dict[str, str] = {}
    failure_nodes: dict[str, str] = {}
    metric_nodes = _benchmark_metric_nodes(summary)
    for node in metric_nodes:
        if builder.add_node(node):
            builder.add_edge(benchmark_node_id, node.node_id, "has_metric")

    for index, result in enumerate(results[: max(0, max_items)], start=1):
        item_id = _text(result.get("item_id")) or f"item-{index}"
        status = _text(result.get("status")) or _scorecard_text(result, "status") or "unknown"
        scorecard = _dict(result.get("scorecard"))
        trace_metrics = _dict(result.get("trace_metrics"))
        metadata = _dict(result.get("metadata"))
        item_node_id = f"bench_item:{_safe_node_id(item_id)}"
        item_node = BehaviorGraphNode(
            node_id=item_node_id,
            node_type="benchmark_item",
            label=_preview(f"{item_id}: {status}", 140),
            metadata=_safe_metadata(
                {
                    "item_id": item_id,
                    "status": status,
                    "question_preview": _preview(_text(result.get("question")), 220),
                    "task_id": _text(result.get("task_id")),
                    "thread_id": _text(result.get("thread_id")),
                    "category": _text(metadata.get("category")),
                    "source": _text(metadata.get("source")),
                    "score_reason": _text(scorecard.get("reason")),
                    "answer_present": scorecard.get("answer_present"),
                    "citation_present": scorecard.get("citation_present"),
                    "numeric_passed": _nested(scorecard, "numeric", "passed"),
                    "total_tokens": _number(trace_metrics.get("total_tokens")),
                    "retrieval_runs": _number(trace_metrics.get("retrieval_run_count")),
                    "fetches": _number(trace_metrics.get("fetch_attempt_count")),
                    "downloaded_bytes": _number(trace_metrics.get("downloaded_bytes")),
                    "query_repetition_rate": _number(trace_metrics.get("query_repetition_rate")),
                    "processor_errors": _number(trace_metrics.get("processor_error_count")),
                    "calculator_calls": _number(trace_metrics.get("calculator_call_count")),
                    "formula_traces": _number(trace_metrics.get("formula_trace_count")),
                    "finance_facts": _number(trace_metrics.get("finance_fact_count")),
                    "numeric_verifier_status": _text(trace_metrics.get("numeric_verifier_status")),
                    "answer_numeric_support_rate": _number(trace_metrics.get("answer_numeric_support_rate")),
                    "finance_numeric_failure_reason": _text(trace_metrics.get("finance_numeric_failure_reason")),
                    "final_answer_chars": _number(trace_metrics.get("final_answer_chars")),
                    "latest_failure_mode": _text(trace_metrics.get("latest_failure_mode")),
                }
            ),
        )
        if not builder.add_node(item_node):
            builder.truncated_records += 1
            continue
        builder.add_edge(benchmark_node_id, item_node_id, "contains_item", status)

        status_node_id = status_nodes.get(status)
        if status_node_id is None:
            status_node_id = f"bench_status:{_safe_node_id(status)}"
            status_nodes[status] = status_node_id
            if builder.add_node(
                BehaviorGraphNode(
                    node_id=status_node_id,
                    node_type="benchmark_status",
                    label=f"Status: {status}",
                    metadata={"status": status, "count": summary["status_counts"].get(status, 0)},
                )
            ):
                builder.add_edge(benchmark_node_id, status_node_id, "has_status")
        builder.add_edge(item_node_id, status_node_id, "has_status")

        category = _text(metadata.get("category"))
        if category:
            category_node_id = category_nodes.get(category)
            if category_node_id is None:
                category_node_id = f"bench_category:{_safe_node_id(category)}"
                category_nodes[category] = category_node_id
                if builder.add_node(
                    BehaviorGraphNode(
                        node_id=category_node_id,
                        node_type="benchmark_category",
                        label=_preview(f"Category: {category}", 120),
                        metadata={"category": category},
                    )
                ):
                    builder.add_edge(benchmark_node_id, category_node_id, "has_category")
            builder.add_edge(item_node_id, category_node_id, "in_category")

        reason = _text(scorecard.get("reason"))
        if reason:
            reason_node_id = reason_nodes.get(reason)
            if reason_node_id is None:
                reason_node_id = f"bench_reason:{_safe_node_id(reason)}"
                reason_nodes[reason] = reason_node_id
                if builder.add_node(
                    BehaviorGraphNode(
                        node_id=reason_node_id,
                        node_type="benchmark_reason",
                        label=_preview(f"Reason: {reason}", 120),
                        metadata={"reason": reason},
                    )
                ):
                    builder.add_edge(benchmark_node_id, reason_node_id, "has_reason")
            builder.add_edge(item_node_id, reason_node_id, "scored_as")

        failure_mode = _text(trace_metrics.get("latest_failure_mode"))
        if failure_mode:
            failure_node_id = failure_nodes.get(failure_mode)
            if failure_node_id is None:
                failure_node_id = f"bench_failure:{_safe_node_id(failure_mode)}"
                failure_nodes[failure_mode] = failure_node_id
                if builder.add_node(
                    BehaviorGraphNode(
                        node_id=failure_node_id,
                        node_type="benchmark_failure_mode",
                        label=_preview(f"Failure: {failure_mode}", 120),
                        metadata={"failure_mode": failure_mode},
                    )
                ):
                    builder.add_edge(benchmark_node_id, failure_node_id, "has_failure_mode")
            builder.add_edge(item_node_id, failure_node_id, "failed_at")

    graph = builder.to_graph()
    diagnostics = dict(graph.diagnostics)
    diagnostics.update(summary)
    if len(results) > max_items:
        diagnostics["truncated_items"] = len(results) - max_items
    return BehaviorGraph(
        schema="holo.kernel_v3.benchmark_behavior_graph.v1",
        task_id=benchmark_node_id,
        nodes=graph.nodes,
        edges=graph.edges,
        diagnostics=diagnostics,
    )


def build_benchmark_result_graph_from_path(
    path: Path | str,
    *,
    benchmark_id: str = "finance",
    max_items: int = 200,
) -> BehaviorGraph:
    return build_benchmark_result_graph(load_benchmark_result_records(path), benchmark_id=benchmark_id, max_items=max_items)


def render_behavior_graph_dot(graph: BehaviorGraph) -> str:
    lines = ["digraph HoloBehaviorGraph {", '  rankdir="LR";', '  node [shape=box, style="rounded"];']
    for node in graph.nodes:
        node_id = _dot_id(str(node.get("node_id")))
        label = _dot_label(str(node.get("label") or node.get("node_id")))
        node_type = str(node.get("node_type") or "node")
        lines.append(f'  "{node_id}" [label="{label}", color="{_dot_color(node_type)}"];')
    for edge in graph.edges:
        label = _dot_label(str(edge.get("label") or edge.get("edge_type") or ""))
        lines.append(
            f'  "{_dot_id(str(edge.get("source")))}" -> "{_dot_id(str(edge.get("target")))}" '
            f'[label="{label}"];'
        )
    lines.append("}")
    return "\n".join(lines)


class _GraphAccumulator:
    def __init__(self, *, task_id: str, max_nodes: int) -> None:
        self.task_id = task_id
        self.max_nodes = max(8, int(max_nodes or MAX_GRAPH_NODES))
        self.nodes: dict[str, JsonObject] = {}
        self.edges: list[JsonObject] = []
        self.truncated_records = 0

    def add_node(self, node: BehaviorGraphNode) -> bool:
        if node.node_id in self.nodes:
            return True
        if len(self.nodes) >= self.max_nodes:
            return False
        self.nodes[node.node_id] = node.to_dict()
        return True

    def add_edge(self, source: str, target: str, edge_type: str, label: str | None = None) -> bool:
        if source not in self.nodes or target not in self.nodes:
            return False
        if len(self.edges) >= MAX_GRAPH_EDGES:
            return False
        edge = BehaviorGraphEdge(source=source, target=target, edge_type=edge_type, label=label)
        payload = edge.to_dict()
        if payload not in self.edges:
            self.edges.append(payload)
        return True

    def to_graph(self) -> BehaviorGraph:
        node_types: dict[str, int] = {}
        edge_types: dict[str, int] = {}
        for node in self.nodes.values():
            key = str(node.get("node_type") or "unknown")
            node_types[key] = node_types.get(key, 0) + 1
        for edge in self.edges:
            key = str(edge.get("edge_type") or "unknown")
            edge_types[key] = edge_types.get(key, 0) + 1
        return BehaviorGraph(
            schema="holo.kernel_v3.behavior_graph.v1",
            task_id=self.task_id,
            nodes=list(self.nodes.values()),
            edges=list(self.edges),
            diagnostics={
                "node_count": len(self.nodes),
                "edge_count": len(self.edges),
                "node_types": node_types,
                "edge_types": edge_types,
                "truncated_records": self.truncated_records,
                "max_nodes": self.max_nodes,
            },
        )


def _node_for_record(record: LedgerRecord) -> BehaviorGraphNode | None:
    data = record.data
    kind = record.kind
    if kind == "processor_request":
        task_type = _processor_task_type(data)
        return _record_node(record, "processor_request", f"Model request: {task_type}", {"task_type": task_type})
    if kind == "processor_result":
        task_type = _processor_task_type(data)
        return _record_node(
            record,
            "processor_result",
            f"Model result: {task_type} {_text(data.get('status'))}",
            {"task_type": task_type, "status": _text(data.get("status")), "error": _preview(_text(data.get("error")), 160)},
        )
    if kind == "semantic_intake":
        return _record_node(record, "semantic", "Semantic intake", {"intent": _text(data.get("primary_intent"))})
    if kind == "semantic_task_graph":
        return _record_node(record, "task_graph", "Semantic task graph", {"status": _text(data.get("status"))})
    if kind == "semantic_task_plan":
        return _record_node(record, "task_plan", "Semantic task plan", {"status": _text(data.get("status"))})
    if kind == "mission_assessment":
        return _record_node(record, "mission_assessment", "Mission assessment", {"decision": _text(data.get("decision"))})
    if kind == "mission_directive":
        return _record_node(record, "mission_directive", "Mission directive", {"strategy": _text(data.get("strategy"))})
    if kind == "workmethod_frame":
        return _record_node(record, "workmethod", "Work method frame", {"status": _text(data.get("status"))})
    if kind == "work_gap_assessment":
        return _record_node(record, "work_gap", "Work gap", {"status": _text(data.get("status"))})
    if kind == "strategy_shift":
        return _record_node(record, "strategy_shift", "Strategy shift", {"strategy": _text(data.get("strategy"))})
    if kind == "action":
        name = _text(data.get("name")) or _text(data.get("kind"))
        return _record_node(
            record,
            "action",
            f"Action: {name}",
            {"action_id": _text(data.get("action_id")), "name": name, "side_effect_class": _text(data.get("side_effect_class"))},
        )
    if kind == "policy_decision":
        return _record_node(record, "policy", f"Policy: {_text(data.get('allowed'))}", {"reason": _preview(_text(data.get("reason")), 160)})
    if kind == "observation":
        return _record_node(
            record,
            "observation",
            f"Observation: {_text(data.get('source'))} {_text(data.get('status'))}",
            {
                "observation_id": _text(data.get("observation_id")),
                "action_id": _text(data.get("action_id")),
                "status": _text(data.get("status")),
                "source": _text(data.get("source")),
            },
        )
    if kind == "feedback":
        return _record_node(
            record,
            "feedback",
            f"Feedback: {_text(data.get('status'))}",
            {"status": _text(data.get("status")), "stop_reason": _text(data.get("stop_reason"))},
        )
    if kind == "retrieval_query_plan":
        return _record_node(
            record,
            "query_plan",
            f"Query plan: {len(_list_of_dicts(data.get('queries')))} queries",
            {"plan_id": _text(data.get("plan_id")), "goal_id": _text(data.get("goal_id"))},
        )
    if kind == "retrieval_search_attempt":
        return _record_node(
            record,
            "search",
            f"Search: {_preview(_text(data.get('query')), 120)}",
            {
                "attempt_id": _text(data.get("attempt_id")),
                "goal_id": _text(data.get("goal_id")),
                "query": _preview(_text(data.get("query")), 240),
                "status": _text(data.get("status")),
            },
        )
    if kind == "retrieval_rank_sources":
        return _record_node(record, "rank", "Rank sources", {"source_count": len(_list_of_dicts(data.get("ranked_sources")))})
    if kind == "retrieval_fetch_attempt":
        return _record_node(
            record,
            "fetch",
            f"Fetch: {_text(data.get('status'))}",
            {
                "fetch_id": _text(data.get("fetch_id")),
                "source_id": _text(data.get("source_id")),
                "uri": _preview(_text(data.get("uri")), 240),
                "status": _text(data.get("status")),
                "artifact_id": _text(data.get("artifact_id")),
                "size_bytes": _int(data.get("size_bytes")),
            },
        )
    if kind == "retrieval_extraction":
        return _record_node(record, "extraction", "Extract spans", {"span_count": len(_list_of_dicts(data.get("spans")))})
    if kind == "retrieval_evidence":
        return _record_node(
            record,
            "evidence",
            f"Evidence: {_preview(_text(data.get('text')), 100)}",
            {
                "evidence_id": _text(data.get("evidence_id")),
                "source_id": _text(data.get("source_id")),
                "artifact_id": _text(data.get("artifact_id")),
                "score": _number(data.get("score")),
            },
        )
    if kind == "retrieval_citation":
        return _record_node(
            record,
            "citation",
            f"Citation: {_text(data.get('citation_id'))}",
            {
                "citation_id": _text(data.get("citation_id")),
                "evidence_id": _text(data.get("evidence_id")),
                "artifact_id": _text(data.get("artifact_id")),
                "quote_preview": _preview(_text(data.get("quote")), 160),
            },
        )
    if kind == "retrieval_evaluation_decision":
        return _record_node(
            record,
            "retrieval_evaluation",
            f"Retrieval evaluation: {_text(data.get('sufficient'))}",
            {"reason": _preview(_text(data.get("reason")), 160)},
        )
    if kind == "retrieval_report":
        return _record_node(record, "retrieval_report", f"Retrieval report: {_text(data.get('status'))}", {"status": _text(data.get("status"))})
    if kind == "agent_final_answer":
        return _record_node(
            record,
            "final_answer",
            "Final answer",
            {"confidence": _number(data.get("confidence")), "citation_refs": _string_list(data.get("citation_refs"))[:64]},
        )
    if kind == "agent_failure_report":
        return _record_node(
            record,
            "failure_report",
            "Failure report",
            {"reason": _preview(_text(data.get("reason")), 160), "next_possible_action": _text(data.get("next_possible_action"))},
        )
    if kind.startswith("memory_"):
        return _record_node(record, "memory", kind, {"memory_id": _text(data.get("memory_id")), "proposal_id": _text(data.get("proposal_id"))})
    return None


def _record_node(record: LedgerRecord, node_type: str, label: str, metadata: JsonObject | None = None) -> BehaviorGraphNode:
    return BehaviorGraphNode(
        node_id=f"record:{record.record_id}",
        node_type=node_type,
        label=_preview(_redact(label), 160),
        record_id=record.record_id,
        run_id=record.run_id,
        step_id=record.step_id,
        metadata=_safe_metadata(
            {
                "kind": record.kind,
                "payload_hash": record.payload_hash,
                "artifact_refs": list(record.artifact_refs),
                **dict(metadata or {}),
            }
        ),
    )


def _source_node(source: JsonObject) -> BehaviorGraphNode:
    source_id = _text(source.get("source_id")) or _text(source.get("id")) or _short_hash(source)
    title = _text(source.get("title")) or _text(source.get("name")) or source_id
    return BehaviorGraphNode(
        node_id=f"source:{source_id}",
        node_type="source",
        label=_preview(_redact(title), 140),
        metadata=_safe_metadata(
            {
                "source_id": source_id,
                "uri": _preview(_text(source.get("uri") or source.get("url")), 240),
                "authority": _text(source.get("authority")),
                "score": _number(source.get("score")),
            }
        ),
    )


def _benchmark_result_summary(results: list[JsonObject]) -> JsonObject:
    status_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    failure_mode_counts: dict[str, int] = {}
    finance_numeric_failure_reason_counts: dict[str, int] = {}
    workflow_type_counts: dict[str, int] = {}
    values: dict[str, list[float]] = {
        "total_tokens": [],
        "retrieval_run_count": [],
        "fetch_attempt_count": [],
        "downloaded_bytes": [],
        "query_repetition_rate": [],
        "final_answer_chars": [],
        "calculator_call_count": [],
        "formula_trace_count": [],
        "finance_fact_count": [],
        "claim_count": [],
        "transform_plan_count": [],
        "missing_slot_count": [],
        "answer_numeric_support_rate": [],
    }
    passed_tokens: list[float] = []
    answer_present = 0
    citation_present = 0
    numeric_scored = 0
    numeric_passed = 0
    calculator_used = 0
    formula_trace_present = 0
    claim_ledger_present = 0
    slot_frame_present = 0
    transform_plan_present = 0
    verifier_scored = 0
    verifier_passed = 0
    gate_scored = 0
    gate_passed = 0
    synthesis_gate_scored = 0
    synthesis_gate_passed = 0
    synthesis_gate_repairable = 0
    synthesis_gate_repaired = 0
    unsupported_numeric_count = 0
    missing_slot_recovery_scored = 0
    missing_slot_recovered = 0
    scored = 0
    passed = 0
    for result in results:
        status = _text(result.get("status")) or _scorecard_text(result, "status") or "unknown"
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "passed":
            passed += 1
            trace_metrics = _dict(result.get("trace_metrics"))
            total_tokens = _number(trace_metrics.get("total_tokens"))
            if isinstance(total_tokens, (int, float)):
                passed_tokens.append(float(total_tokens))
        scorecard = _dict(result.get("scorecard"))
        if scorecard.get("scored") is True:
            scored += 1
        if scorecard.get("answer_present") is True:
            answer_present += 1
        if scorecard.get("citation_present") is True:
            citation_present += 1
        reason = _text(scorecard.get("reason"))
        if reason:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
        numeric = _dict(scorecard.get("numeric"))
        if numeric.get("scored") is True:
            numeric_scored += 1
            if numeric.get("passed") is True:
                numeric_passed += 1
        trace_metrics = _dict(result.get("trace_metrics"))
        metadata = _dict(result.get("metadata"))
        workflow_type = _text(metadata.get("workflow_type") or metadata.get("category") or "unclassified")
        workflow_type_counts[workflow_type] = workflow_type_counts.get(workflow_type, 0) + 1
        calculator_calls = _number(trace_metrics.get("calculator_call_count"))
        formula_traces = _number(trace_metrics.get("formula_trace_count"))
        if isinstance(calculator_calls, (int, float)) and calculator_calls > 0:
            calculator_used += 1
        if isinstance(formula_traces, (int, float)) and formula_traces > 0:
            formula_trace_present += 1
        if trace_metrics.get("claim_ledger_present") is True:
            claim_ledger_present += 1
        if trace_metrics.get("slot_frame_present") is True:
            slot_frame_present += 1
        transform_plan_count = _number(trace_metrics.get("transform_plan_count"))
        if isinstance(transform_plan_count, (int, float)) and transform_plan_count > 0:
            transform_plan_present += 1
        verifier_status = _text(trace_metrics.get("numeric_verifier_status"))
        if verifier_status in {"passed", "failed"}:
            verifier_scored += 1
            if verifier_status == "passed":
                verifier_passed += 1
        gate_status = _text(trace_metrics.get("verifier_gate_status"))
        if gate_status in {"passed", "failed"}:
            gate_scored += 1
            if gate_status == "passed":
                gate_passed += 1
        synthesis_gate_status = _text(trace_metrics.get("synthesis_gate_status"))
        if synthesis_gate_status in {"passed", "failed"}:
            synthesis_gate_scored += 1
            if synthesis_gate_status == "passed":
                synthesis_gate_passed += 1
        synthesis_gate_attempt_count = _number(trace_metrics.get("synthesis_gate_attempt_count"))
        if (
            isinstance(synthesis_gate_attempt_count, (int, float))
            and synthesis_gate_attempt_count > 1
        ) or trace_metrics.get("synthesis_gate_repaired") is True:
            synthesis_gate_repairable += 1
            if trace_metrics.get("synthesis_gate_repaired") is True:
                synthesis_gate_repaired += 1
        missing_slot_transform_count = _number(trace_metrics.get("missing_slot_transform_plan_count"))
        if isinstance(missing_slot_transform_count, (int, float)) and missing_slot_transform_count > 0:
            missing_slot_recovery_scored += 1
            missing_slot_count = _number(trace_metrics.get("missing_slot_count"))
            if isinstance(missing_slot_count, (int, float)) and missing_slot_count == 0:
                missing_slot_recovered += 1
        failure_mode = _text(trace_metrics.get("latest_failure_mode"))
        if failure_mode:
            failure_mode_counts[failure_mode] = failure_mode_counts.get(failure_mode, 0) + 1
        finance_failure_reason = _text(trace_metrics.get("finance_numeric_failure_reason"))
        if finance_failure_reason:
            finance_numeric_failure_reason_counts[finance_failure_reason] = (
                finance_numeric_failure_reason_counts.get(finance_failure_reason, 0) + 1
            )
            failure_mode_counts[f"finance_numeric:{finance_failure_reason}"] = failure_mode_counts.get(
                f"finance_numeric:{finance_failure_reason}",
                0,
            ) + 1
            if finance_failure_reason == "unsupported_answer_number":
                unsupported_numeric_count += 1
        for key in values:
            value = trace_metrics.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                values[key].append(float(value))
    item_count = len(results)
    repeated_item_count, repeatability_score = _benchmark_repeatability_summary(results)
    return {
        "status_counts": status_counts,
        "reason_counts": reason_counts,
        "failure_mode_counts": failure_mode_counts,
        "finance_numeric_failure_reason_counts": finance_numeric_failure_reason_counts,
        "workflow_type_counts": workflow_type_counts,
        "item_count": item_count,
        "scored_count": scored,
        "passed_count": passed,
        "pass_rate": _rate(passed, scored),
        "answer_present_rate": _rate(answer_present, item_count),
        "citation_present_rate": _rate(citation_present, item_count),
        "citation_preservation_rate": _rate(citation_present, item_count),
        "numeric_accuracy": _rate(numeric_passed, numeric_scored) if numeric_scored else None,
        "average_total_tokens": _average(values["total_tokens"]),
        "average_retrieval_runs": _average(values["retrieval_run_count"]),
        "average_fetches": _average(values["fetch_attempt_count"]),
        "average_downloaded_bytes": _average(values["downloaded_bytes"]),
        "average_query_repetition_rate": _average(values["query_repetition_rate"]),
        "average_final_answer_chars": _average(values["final_answer_chars"]),
        "calculator_used_rate": _rate(calculator_used, item_count),
        "formula_trace_present_rate": _rate(formula_trace_present, item_count),
        "claim_ledger_present_rate": _rate(claim_ledger_present, item_count),
        "slot_frame_present_rate": _rate(slot_frame_present, item_count),
        "transform_plan_present_rate": _rate(transform_plan_present, item_count),
        "numeric_verifier_pass_rate": _rate(verifier_passed, verifier_scored) if verifier_scored else None,
        "verifier_gate_pass_rate": _rate(gate_passed, gate_scored) if gate_scored else None,
        "synthesis_gate_pass_rate": _rate(synthesis_gate_passed, synthesis_gate_scored) if synthesis_gate_scored else None,
        "synthesis_gate_repair_rate": _rate(synthesis_gate_repaired, synthesis_gate_repairable) if synthesis_gate_repairable else None,
        "unsupported_numeric_claim_rate": _rate(unsupported_numeric_count, item_count),
        "missing_slot_recovery_rate": _rate(missing_slot_recovered, missing_slot_recovery_scored) if missing_slot_recovery_scored else None,
        "repeated_item_count": repeated_item_count,
        "repeatability_score": repeatability_score,
        "average_calculator_calls": _average(values["calculator_call_count"]),
        "average_formula_traces": _average(values["formula_trace_count"]),
        "average_finance_facts": _average(values["finance_fact_count"]),
        "average_claims": _average(values["claim_count"]),
        "average_transform_plans": _average(values["transform_plan_count"]),
        "average_missing_slots": _average(values["missing_slot_count"]),
        "average_total_tokens_per_passed_item": _average(passed_tokens) if passed_tokens else None,
        "average_answer_numeric_support_rate": _average(values["answer_numeric_support_rate"])
        if values["answer_numeric_support_rate"]
        else None,
    }


def _benchmark_metric_nodes(summary: JsonObject) -> list[BehaviorGraphNode]:
    specs = [
        ("pass_rate", "Pass rate"),
        ("citation_present_rate", "Citation rate"),
        ("average_total_tokens", "Avg tokens"),
        ("average_retrieval_runs", "Avg retrieval runs"),
        ("average_fetches", "Avg fetches"),
        ("average_query_repetition_rate", "Avg query repetition"),
        ("calculator_used_rate", "Calculator used"),
        ("numeric_verifier_pass_rate", "Verifier pass"),
        ("verifier_gate_pass_rate", "Verifier gate"),
        ("synthesis_gate_pass_rate", "Synthesis gate"),
        ("average_formula_traces", "Avg formula traces"),
        ("claim_ledger_present_rate", "Claim ledger"),
        ("slot_frame_present_rate", "Slot frame"),
        ("transform_plan_present_rate", "Transform plan"),
        ("average_finance_facts", "Avg finance facts"),
        ("average_claims", "Avg claims"),
        ("average_answer_numeric_support_rate", "Avg numeric support"),
        ("unsupported_numeric_claim_rate", "Unsupported numeric"),
        ("repeatability_score", "Repeatability"),
        ("average_final_answer_chars", "Avg answer chars"),
    ]
    nodes: list[BehaviorGraphNode] = []
    for key, label in specs:
        value = summary.get(key)
        if value is None:
            continue
        nodes.append(
            BehaviorGraphNode(
                node_id=f"bench_metric:{key}",
                node_type="benchmark_metric",
                label=f"{label}: {value}",
                metadata={"metric": key, "value": value},
            )
        )
    return nodes


def _benchmark_repeatability_summary(results: list[JsonObject]) -> tuple[int, float | None]:
    grouped: dict[str, list[JsonObject]] = {}
    for index, result in enumerate(results, start=1):
        item_id = _text(result.get("item_id")) or f"item-{index}"
        grouped.setdefault(item_id, []).append(result)
    repeated = {item_id: rows for item_id, rows in grouped.items() if len(rows) > 1}
    if not repeated:
        return 0, None
    scores: list[float] = []
    for rows in repeated.values():
        statuses = {_text(row.get("status")) or _scorecard_text(row, "status") or "unknown" for row in rows}
        citation_presence = {bool(_dict(row.get("scorecard")).get("citation_present")) for row in rows}
        verifier_statuses = {_text(_dict(row.get("trace_metrics")).get("numeric_verifier_status")) for row in rows}
        verifier_gate_statuses = {_text(_dict(row.get("trace_metrics")).get("verifier_gate_status")) for row in rows}
        synthesis_gate_statuses = {_text(_dict(row.get("trace_metrics")).get("synthesis_gate_status")) for row in rows}
        formula_presence = {
            bool((_number(_dict(row.get("trace_metrics")).get("formula_trace_count")) or 0) > 0)
            for row in rows
        }
        claim_counts = {_number(_dict(row.get("trace_metrics")).get("claim_count")) for row in rows}
        missing_slot_counts = {_number(_dict(row.get("trace_metrics")).get("missing_slot_count")) for row in rows}
        components = [
            len(statuses) == 1,
            len(citation_presence) == 1,
            len(verifier_statuses) == 1,
            len(verifier_gate_statuses) == 1,
            len(synthesis_gate_statuses) == 1,
            len(formula_presence) == 1,
            len(claim_counts) == 1,
            len(missing_slot_counts) == 1,
        ]
        scores.append(_rate(sum(1 for item in components if item), len(components)))
    return len(repeated), _average(scores)


def _processor_task_type(data: JsonObject) -> str:
    parameters = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    output = data.get("output") if isinstance(data.get("output"), dict) else {}
    for container in (data, parameters, output):
        value = container.get("task_type") if isinstance(container, dict) else None
        if isinstance(value, str) and value:
            return value
    processor = data.get("processor")
    return str(processor) if isinstance(processor, str) and processor else "unknown"


def _safe_metadata(data: JsonObject) -> JsonObject:
    safe: JsonObject = {}
    for key, value in data.items():
        if value in (None, "", []):
            continue
        if isinstance(value, str):
            safe[key] = _preview(_redact(value), 300)
        elif isinstance(value, (int, float, bool)):
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = [_preview(_redact(str(item)), 160) for item in value[:64]]
        elif isinstance(value, dict):
            safe[key] = {str(k): _preview(_redact(str(v)), 160) for k, v in list(value.items())[:64]}
        else:
            safe[key] = _preview(_redact(str(value)), 160)
    return safe


def _json_object(text: str) -> JsonObject:
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("expected JSON object per benchmark result row")
    return payload


def _dict(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _nested(data: JsonObject, *path: str) -> object:
    current: object = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _scorecard_text(result: JsonObject, key: str) -> str:
    scorecard = _dict(result.get("scorecard"))
    return _text(scorecard.get(key))


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def _safe_node_id(text: str) -> str:
    safe = []
    for char in str(text):
        if char.isalnum() or char in {"-", "_", "."}:
            safe.append(char)
        else:
            safe.append("-")
    joined = "".join(safe).strip("-")
    if not joined:
        return _short_hash(text)
    if len(joined) > 80:
        return joined[:60] + "-" + _short_hash(text)
    return joined


def _find_node_by_record_data(nodes: dict[str, JsonObject], key: str, value: str) -> str | None:
    for node_id, node in nodes.items():
        metadata = node.get("metadata")
        if isinstance(metadata, dict) and metadata.get(key) == value:
            return node_id
    return None


def _list_of_dicts(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if isinstance(value, str) and value:
        return [value]
    return []


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _redact(value.strip())
    if isinstance(value, (int, float, bool)):
        return str(value)
    return _redact(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _redact(text: str) -> str:
    redacted, _ = _REDACTOR.redact(text)
    return str(redacted)


def _preview(text: str, limit: int) -> str:
    safe = _redact(str(text or "")).replace("\n", " ").strip()
    if len(safe) <= limit:
        return safe
    return safe[: max(0, limit - 1)].rstrip() + "…"


def _number(value: object) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    return None


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _status_label(data: JsonObject) -> str | None:
    status = _text(data.get("status"))
    return status or None


def _score_label(data: JsonObject) -> str | None:
    score = data.get("score")
    if isinstance(score, (int, float)) and not isinstance(score, bool):
        return f"score={score:.3g}"
    return None


def _short_hash(value: object) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _dot_id(text: str) -> str:
    return text.replace('"', "'")


def _dot_label(text: str) -> str:
    return _preview(text, 120).replace("\\", "\\\\").replace('"', "'")


def _dot_color(node_type: str) -> str:
    colors = {
        "task": "#666666",
        "processor_request": "#888888",
        "processor_result": "#999999",
        "action": "#c47f2c",
        "policy": "#4f8f5f",
        "observation": "#6d6d6d",
        "search": "#d08a2d",
        "source": "#b8843a",
        "fetch": "#b05c42",
        "artifact": "#777777",
        "document": "#777777",
        "evidence": "#3f8f5f",
        "citation": "#d28a31",
        "final_answer": "#3f8f5f",
        "failure_report": "#b84a4a",
        "benchmark": "#666666",
        "benchmark_item": "#777777",
        "benchmark_status": "#4f8f5f",
        "benchmark_metric": "#d28a31",
        "benchmark_category": "#888888",
        "benchmark_reason": "#b8843a",
        "benchmark_failure_mode": "#b84a4a",
    }
    return colors.get(node_type, "#777777")
