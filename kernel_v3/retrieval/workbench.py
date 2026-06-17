from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import RETRIEVAL_WORKBENCH_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, ExtractedSpan, FetchedDocument, SearchGoal, SearchSource
from kernel_v3.retrieval.extract import readable_document_text_with_diagnostics
from kernel_v3.retrieval.url_utils import unwrap_url_candidates, url_equivalent_or_unwrapped


RETRIEVAL_WORKBENCH_TASK = "retrieval.workbench"

WORKBENCH_DECISIONS = {"sufficient", "continue", "fail_with_limitations"}
SOURCE_ROLES = {
    "primary_filing",
    "annual_report",
    "earnings_release",
    "transaction_disclosure",
    "market_data",
    "benchmark_context",
    "irrelevant",
    "other",
}
SLOT_STATUSES = {"filled", "partial", "missing", "assumption_required", "not_applicable"}

WORKBENCH_SOURCE_LIMIT = 10
WORKBENCH_DOCUMENT_LIMIT = 3
WORKBENCH_SPAN_LIMIT = 8
WORKBENCH_ACCEPTED_EVIDENCE_LIMIT = 6
WORKBENCH_REJECTED_EVIDENCE_LIMIT = 6
WORKBENCH_FETCH_SUMMARY_LIMIT = 6
WORKBENCH_CITATION_LIMIT = 8
WORKBENCH_TARGET_CANDIDATE_LIMIT = 8
WORKBENCH_RETRY_DOCUMENT_LIMIT = 4
WORKBENCH_RETRY_REJECTED_LIMIT = 8
WORKBENCH_TABLE_SNIPPET_LIMIT = 2

WORKBENCH_PROMPT_CONTRACT = """Return one JSON object matching retrieval.workbench.
The model owns semantic evidence judgment: decide whether the packet supports
the task, which evidence IDs are relevant, which slots are filled or missing,
and the next retrieval/source/document moves when more evidence is needed.
Allowed decisions: sufficient, continue, fail_with_limitations.
Do not invent evidence IDs, source IDs, citation IDs, facts, numeric values,
formulas, or URLs. Reference only IDs present in packet.
Use compiled_task_hint as the host-compiled work program: evidence_specs are
slots to fill; transform_specs are computations that wait for supported input
slots; tool_chain_plan is the assembly surface for retrieval, document targeting,
calculator preparation, or verified synthesis. The hint is not evidence.
Host rejection reasons are filters, not final semantic truth. If rejected_evidence
or target_document_candidates contain useful target-document excerpts, rescue
their existing evidence_id values and explain which slots they fill.
Finance workbench behavior: prefer primary filings, SEC structured data,
company IR, earnings releases, transaction disclosures, market-data providers,
government or central-bank sources according to the task. Preserve exact metric
phrases and statement context; do not substitute nearby line items unless the
limitation is explicit. If a numeric task has supported inputs, mark slots filled
so the planner can use calculator.compute; if inputs are missing, propose precise
next_queries, next_source_families, or next_document_targets.
The host validates provenance, authority, policy, budgets, and numeric support."""


@dataclass(frozen=True, kw_only=True)
class RetrievalWorkbenchResult:
    status: str
    decision: str
    reason_summary: str
    accepted_evidence_ids: list[str] = field(default_factory=list)
    rescued_evidence_ids: list[str] = field(default_factory=list)
    rejected_evidence_ids: list[str] = field(default_factory=list)
    source_roles: list[JsonObject] = field(default_factory=list)
    slot_assessments: list[JsonObject] = field(default_factory=list)
    covered_slots: list[str] = field(default_factory=list)
    missing_slots: list[str] = field(default_factory=list)
    assumptions_needed: list[str] = field(default_factory=list)
    next_queries: list[str] = field(default_factory=list)
    next_source_families: list[str] = field(default_factory=list)
    next_document_targets: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)

    def to_dict(self) -> JsonObject:
        return {
            "status": self.status,
            "decision": self.decision,
            "reason_summary": self.reason_summary,
            "accepted_evidence_ids": list(self.accepted_evidence_ids),
            "rescued_evidence_ids": list(self.rescued_evidence_ids),
            "rejected_evidence_ids": list(self.rejected_evidence_ids),
            "source_roles": [dict(item) for item in self.source_roles],
            "slot_assessments": [dict(item) for item in self.slot_assessments],
            "covered_slots": list(self.covered_slots),
            "missing_slots": list(self.missing_slots),
            "assumptions_needed": list(self.assumptions_needed),
            "next_queries": list(self.next_queries),
            "next_source_families": list(self.next_source_families),
            "next_document_targets": list(self.next_document_targets),
            "limitations": list(self.limitations),
            "diagnostics": dict(self.diagnostics),
        }


def run_retrieval_workbench(
    *,
    fabric: ProcessorFabric | None,
    goal: SearchGoal,
    sources: list[SearchSource],
    fetch_summaries: list[JsonObject],
    documents: list[tuple[FetchedDocument, str]],
    spans: list[ExtractedSpan],
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    rejected_evidence: list[JsonObject],
    task_id: str | None,
    run_id: str,
    step_id: str,
) -> RetrievalWorkbenchResult:
    packet = retrieval_workbench_packet(
        goal=goal,
        sources=sources,
        fetch_summaries=fetch_summaries,
        documents=documents,
        spans=spans,
        evidence=evidence,
        citations=citations,
        rejected_evidence=rejected_evidence,
    )
    if fabric is None:
        return RetrievalWorkbenchResult(
            status="disabled",
            decision="continue",
            reason_summary="retrieval workbench model processor is not configured",
            diagnostics={
                "reason": "processor_fabric_not_configured",
                "packet": _packet_diagnostics(packet),
            },
        )
    prompt = _workbench_prompt(packet)
    outcome = fabric.run_json(
        task_type=RETRIEVAL_WORKBENCH_TASK,
        run_id=run_id,
        context_id=f"ctx-{step_id}",
        prompt=prompt,
        schema=RETRIEVAL_WORKBENCH_SCHEMA,
        task_id=task_id,
        step_id=step_id,
        timeout_seconds=90,
        parameters={"temperature": 0.0},
    )
    if outcome.result.status != "ok" or not isinstance(outcome.parsed, dict):
        retry_packet = _workbench_retry_packet(packet)
        retry = fabric.run_json(
            task_type=RETRIEVAL_WORKBENCH_TASK,
            run_id=run_id,
            context_id=f"ctx-{step_id}-json-retry",
            prompt=_workbench_retry_prompt(retry_packet, error=outcome.result.error or "invalid_workbench_output"),
            schema=RETRIEVAL_WORKBENCH_SCHEMA,
            task_id=task_id,
            step_id=f"{step_id}-json-retry",
            timeout_seconds=90,
            parameters={"temperature": 0.0},
        )
        if retry.result.status == "ok" and isinstance(retry.parsed, dict):
            validated = validate_workbench_output(retry.parsed, packet=packet)
            return replace(
                validated,
                diagnostics={
                    **validated.diagnostics,
                    "json_retry": {
                        "attempted": True,
                        "first_error": outcome.result.error or "invalid_workbench_output",
                        "packet": _packet_diagnostics(retry_packet),
                    },
                },
            )
    if outcome.result.status != "ok" or not isinstance(outcome.parsed, dict):
        return RetrievalWorkbenchResult(
            status="failed",
            decision="continue",
            reason_summary=(
                "retrieval workbench LLM judge failed; host may continue acquisition, "
                "but deterministic filters are not the semantic evidence judge"
            ),
            diagnostics={
                "reason": outcome.result.error or "invalid_workbench_output",
                "semantic_decision_owner": "model",
                "host_role": "tool_execution_provenance_policy_and_budget_validation",
                "failure_code": "llm_retrieval_workbench_unavailable",
                "provider": outcome.provider,
                "model": outcome.model,
                "packet": _packet_diagnostics(packet),
            },
        )
    return validate_workbench_output(outcome.parsed, packet=packet)


def retrieval_workbench_packet(
    *,
    goal: SearchGoal,
    sources: list[SearchSource],
    fetch_summaries: list[JsonObject],
    documents: list[tuple[FetchedDocument, str]],
    spans: list[ExtractedSpan],
    evidence: list[EvidenceItem],
    citations: list[CitationItem],
    rejected_evidence: list[JsonObject],
) -> JsonObject:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    target_contract = _target_document_contract(metadata)
    compiled_hint = _compiled_task_hint(metadata.get("compiled_task_hint"))
    selection_terms = _packet_selection_terms(goal=goal, metadata=metadata, compiled_hint=compiled_hint)
    selected_sources = _select_sources(sources, target_contract=target_contract, terms=selection_terms, limit=WORKBENCH_SOURCE_LIMIT)
    selected_documents = _select_documents(documents, target_contract=target_contract, terms=selection_terms, limit=WORKBENCH_DOCUMENT_LIMIT)
    selected_spans = _select_spans(spans, target_contract=target_contract, terms=selection_terms, limit=WORKBENCH_SPAN_LIMIT)
    selected_evidence = _select_evidence(
        evidence,
        target_contract=target_contract,
        terms=selection_terms,
        limit=WORKBENCH_ACCEPTED_EVIDENCE_LIMIT,
    )
    selected_rejected = _select_rejected_evidence(
        rejected_evidence,
        target_contract=target_contract,
        terms=selection_terms,
        limit=WORKBENCH_REJECTED_EVIDENCE_LIMIT,
    )
    span_readers = _span_reader_diagnostics_by_document(spans)
    accepted = [_evidence_summary(item, target_contract=target_contract, terms=selection_terms) for item in selected_evidence]
    rejected = [_rejected_summary(item, target_contract=target_contract) for item in selected_rejected]
    return {
        "task_goal": _string_value(metadata.get("root_goal") or metadata.get("task_goal") or goal.query),
        "current_retrieval_goal": goal.query,
        "workflow_type": _string_value(metadata.get("workflow_type") or metadata.get("research_task_kind")),
        "required_slots": _string_list(metadata.get("required_slots")),
        "evidence_policy": _json_object(metadata.get("evidence_policy")),
        "required_transforms": _string_list(metadata.get("required_transforms")),
        "compiled_task_hint": compiled_hint,
        "target_document_contract": target_contract,
        "target_document_binding": _json_object(metadata.get("target_document_binding")),
        "required_statement": _string_value(metadata.get("required_statement")),
        "required_line_item": _string_value(metadata.get("required_line_item")),
        "source_summaries": [_source_summary(item) for item in selected_sources],
        "fetch_summaries": [_bounded_dict(item, text_limit=180) for item in fetch_summaries[-WORKBENCH_FETCH_SUMMARY_LIMIT:]],
        "document_summaries": [
            _document_summary(
                document,
                body,
                goal=goal,
                target_contract=target_contract,
                terms=selection_terms,
                span_reader_diagnostics=span_readers.get(document.document_id),
            )
            for document, body in selected_documents
        ],
        "extracted_spans": [
            _span_summary(item, target_contract=target_contract, terms=selection_terms)
            for item in selected_spans
        ],
        "accepted_evidence": accepted,
        "rejected_evidence": rejected,
        "target_document_candidates": _target_document_candidates(
            accepted=accepted,
            rejected=rejected,
            spans=selected_spans,
            target_contract=target_contract,
            terms=selection_terms,
        ),
        "current_slot_state": _json_object(metadata.get("slot_state")),
        "current_claim_state": _json_object(metadata.get("claim_state")),
        "current_citations": [_citation_summary(item) for item in citations[:WORKBENCH_CITATION_LIMIT]],
        "known_limitations": _string_list(metadata.get("known_limitations")),
        "selection_diagnostics": {
            "raw_source_count": len(sources),
            "selected_source_count": len(selected_sources),
            "raw_document_count": len(documents),
            "selected_document_count": len(selected_documents),
            "raw_span_count": len(spans),
            "selected_span_count": len(selected_spans),
            "raw_accepted_evidence_count": len(evidence),
            "selected_accepted_evidence_count": len(selected_evidence),
            "raw_rejected_evidence_count": len(rejected_evidence),
            "selected_rejected_evidence_count": len(selected_rejected),
            "selection_term_count": len(selection_terms),
        },
    }


def validate_workbench_output(parsed: JsonObject, *, packet: JsonObject) -> RetrievalWorkbenchResult:
    parsed = _normalize_workbench_aliases(parsed)
    evidence_ids = {
        str(item.get("evidence_id"))
        for item in [*packet.get("accepted_evidence", []), *packet.get("rejected_evidence", [])]
        if isinstance(item, dict) and item.get("evidence_id")
    }
    source_ids = {
        str(item.get("source_id"))
        for item in packet.get("source_summaries", [])
        if isinstance(item, dict) and item.get("source_id")
    }
    citation_ids = {
        str(item.get("citation_id"))
        for item in packet.get("current_citations", [])
        if isinstance(item, dict) and item.get("citation_id")
    }
    decision = str(parsed.get("decision") or "continue")
    if decision not in WORKBENCH_DECISIONS:
        decision = "continue"
    accepted = _valid_ids(parsed.get("accepted_evidence_ids"), evidence_ids)
    rescued = _valid_ids(parsed.get("rescued_evidence_ids"), evidence_ids)
    rejected = _valid_ids(parsed.get("rejected_evidence_ids"), evidence_ids)
    source_roles = _valid_source_roles(parsed.get("source_roles"), source_ids)
    slot_assessments = _valid_slot_assessments(parsed.get("slot_assessments"), evidence_ids)
    invalid = _invalid_reference_diagnostics(
        parsed=parsed,
        evidence_ids=evidence_ids,
        source_ids=source_ids,
        citation_ids=citation_ids,
    )
    return RetrievalWorkbenchResult(
        status="ok",
        decision=decision,
        reason_summary=_truncate(_string_value(parsed.get("reason_summary")), 600),
        accepted_evidence_ids=accepted,
        rescued_evidence_ids=rescued,
        rejected_evidence_ids=rejected,
        source_roles=source_roles,
        slot_assessments=slot_assessments,
        covered_slots=_bounded_strings(parsed.get("covered_slots"), limit=32),
        missing_slots=_bounded_strings(parsed.get("missing_slots"), limit=32),
        assumptions_needed=_bounded_strings(parsed.get("assumptions_needed"), limit=16),
        next_queries=_bounded_strings(parsed.get("next_queries"), limit=8, item_limit=220),
        next_source_families=_bounded_strings(parsed.get("next_source_families"), limit=12),
        next_document_targets=_bounded_strings(parsed.get("next_document_targets"), limit=8, item_limit=220),
        limitations=_bounded_strings(parsed.get("limitations"), limit=12, item_limit=220),
        diagnostics={
            "host_validation": {
                "valid": not invalid,
                "invalid_references": invalid,
                "known_evidence_count": len(evidence_ids),
                "known_source_count": len(source_ids),
                "known_citation_count": len(citation_ids),
            },
        },
    )


def _normalize_workbench_aliases(parsed: JsonObject) -> JsonObject:
    normalized = dict(parsed)
    if not normalized.get("decision"):
        sufficiency = _string_value(
            normalized.get("evidence_sufficiency")
            or normalized.get("sufficiency")
            or normalized.get("status")
        ).lower()
        if sufficiency in {"sufficient", "complete", "enough", "ready"}:
            normalized["decision"] = "sufficient"
        elif sufficiency in {"fail", "failed", "fail_with_limitations", "impossible"}:
            normalized["decision"] = "fail_with_limitations"
        else:
            normalized["decision"] = "continue"
    if not normalized.get("reason_summary"):
        normalized["reason_summary"] = _string_value(
            normalized.get("reason")
            or normalized.get("summary")
            or normalized.get("rationale")
            or normalized.get("diagnosis")
            or normalized.get("evidence_sufficiency")
        )
    if "covered_slots" not in normalized and isinstance(normalized.get("filled_slots"), list):
        normalized["covered_slots"] = normalized.get("filled_slots")
    if "missing_slots" not in normalized and isinstance(normalized.get("unfilled_slots"), list):
        normalized["missing_slots"] = normalized.get("unfilled_slots")
    if "assumptions_needed" not in normalized and isinstance(normalized.get("assumptions"), list):
        normalized["assumptions_needed"] = normalized.get("assumptions")
    if "limitations" not in normalized and isinstance(normalized.get("known_limitations"), list):
        normalized["limitations"] = normalized.get("known_limitations")
    normalized["next_queries"] = _normalize_query_items(normalized.get("next_queries"))
    normalized["next_document_targets"] = _normalize_target_items(normalized.get("next_document_targets"))
    normalized["next_source_families"] = _normalize_family_items(normalized.get("next_source_families"))
    for key in (
        "accepted_evidence_ids",
        "rescued_evidence_ids",
        "rejected_evidence_ids",
        "source_roles",
        "slot_assessments",
        "covered_slots",
        "missing_slots",
        "assumptions_needed",
        "next_queries",
        "next_source_families",
        "next_document_targets",
        "limitations",
    ):
        normalized.setdefault(key, [])
    normalized["source_roles"] = _normalize_source_role_aliases(normalized.get("source_roles"), parsed)
    normalized["slot_assessments"] = _normalize_slot_assessment_aliases(normalized.get("slot_assessments"), parsed)
    moves = _normalize_next_move_aliases(parsed)
    if moves["next_queries"]:
        normalized["next_queries"] = [*list(normalized.get("next_queries") or []), *moves["next_queries"]]
    if moves["next_source_families"]:
        normalized["next_source_families"] = [
            *list(normalized.get("next_source_families") or []),
            *moves["next_source_families"],
        ]
    if moves["next_document_targets"]:
        normalized["next_document_targets"] = [
            *list(normalized.get("next_document_targets") or []),
            *moves["next_document_targets"],
        ]
    return normalized


def _normalize_source_role_aliases(value: object, parsed: JsonObject) -> list[JsonObject]:
    if isinstance(value, list) and value:
        return [item for item in value if isinstance(item, dict)]
    aliases = parsed.get("key_source_roles") or parsed.get("source_role_map") or parsed.get("source_roles_by_id")
    result: list[JsonObject] = []
    if isinstance(aliases, dict):
        for source_id, role in aliases.items():
            result.append(
                {
                    "source_id": str(source_id),
                    "role": _source_role_alias(str(role)),
                    "confidence": 0.5,
                    "reason": f"model alias role: {role}",
                }
            )
    return result


def _normalize_slot_assessment_aliases(value: object, parsed: JsonObject) -> list[JsonObject]:
    result = [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    existing = {str(item.get("slot") or "") for item in result}
    for slot in _string_list(parsed.get("filled_slots")):
        if slot not in existing:
            result.append({"slot": slot, "status": "filled", "supporting_evidence_ids": [], "reason": "model filled_slots alias"})
            existing.add(slot)
    for slot in _string_list(parsed.get("missing_slots")) + _string_list(parsed.get("unfilled_slots")):
        if slot not in existing:
            result.append({"slot": slot, "status": "missing", "supporting_evidence_ids": [], "reason": "model missing_slots alias"})
            existing.add(slot)
    return result


def _normalize_query_items(value: object) -> list[str]:
    result: list[str] = []
    if not isinstance(value, list):
        return result
    for item in value[:16]:
        if isinstance(item, dict):
            for key in ("query", "search_query", "search", "q", "url", "uri", "document_url", "direct_url", "target"):
                text = _string_value(item.get(key))
                if text:
                    result.append(text)
                    break
            continue
        text = _string_value(item)
        if text:
            result.append(text)
    return result


def _normalize_target_items(value: object) -> list[str]:
    result: list[str] = []
    if not isinstance(value, list):
        return result
    for item in value[:16]:
        if isinstance(item, dict):
            for key in ("target", "url", "uri", "document_url", "direct_url", "document_target", "section"):
                text = _string_value(item.get(key))
                if text:
                    result.append(text)
                    break
            continue
        text = _string_value(item)
        if text:
            result.append(text)
    return result


def _normalize_family_items(value: object) -> list[str]:
    result: list[str] = []
    if not isinstance(value, list):
        return result
    for item in value[:16]:
        if isinstance(item, dict):
            text = _string_value(item.get("source_family") or item.get("source_type") or item.get("family") or item.get("tool"))
        else:
            text = _string_value(item)
        if text:
            result.append(text)
    return result


def _compiled_task_hint(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    task_spec = _json_object(value.get("task_spec"))
    evidence_specs = value.get("evidence_specs") if isinstance(value.get("evidence_specs"), list) else []
    transform_specs = value.get("transform_specs") if isinstance(value.get("transform_specs"), list) else []
    result: JsonObject = {
        "schema": _string_value(value.get("schema")) or "holo.kernel_v3.compiled_task_hint.v1",
        "domain": _string_value(value.get("domain")),
        "task_spec": {
            "task_type": _string_value(task_spec.get("task_type")),
            "target_entities": _bounded_strings(task_spec.get("target_entities"), limit=8, item_limit=80),
            "target_periods": _bounded_strings(task_spec.get("target_periods"), limit=8, item_limit=40),
            "success_criteria": _bounded_strings(task_spec.get("success_criteria"), limit=8, item_limit=140),
        },
        "evidence_specs": [
            _compiled_evidence_spec_summary(item)
            for item in evidence_specs[:16]
            if isinstance(item, dict)
        ],
        "transform_specs": [
            _compiled_transform_spec_summary(item)
            for item in transform_specs[:12]
            if isinstance(item, dict)
        ],
        "missing_slots": _bounded_strings(value.get("missing_slots"), limit=16, item_limit=80),
    }
    tool_chain_plan = _compiled_tool_chain_plan_summary(value.get("tool_chain_plan"))
    if tool_chain_plan:
        result["tool_chain_plan"] = tool_chain_plan
    diagnostics = _json_object(value.get("diagnostics"))
    if diagnostics:
        result["diagnostics"] = {
            key: diagnostics.get(key)
            for key in ("source", "evidence_spec_count", "transform_spec_count")
            if diagnostics.get(key) not in (None, "", [], {})
        }
    return result


def _compiled_tool_chain_plan_summary(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    return {
        "schema": _string_value(value.get("schema")),
        "decision_owner": _string_value(value.get("decision_owner")),
        "host_role": _string_value(value.get("host_role")),
        "task_type": _string_value(value.get("task_type")),
        "formula_status": _string_value(value.get("formula_status")),
        "formula_name": _string_value(value.get("formula_name")),
        "missing_slots": _bounded_strings(value.get("missing_slots"), limit=16, item_limit=80),
        "available_tools": [
            _bounded_dict(item, text_limit=160)
            for item in list(value.get("available_tools") or [])[:6]
            if isinstance(item, dict)
        ],
        "recommended_steps": [
            _bounded_dict(item, text_limit=320)
            for item in list(value.get("recommended_steps") or [])[:6]
            if isinstance(item, dict)
        ],
        "next_action_candidates": [
            _bounded_dict(item, text_limit=240)
            for item in list(value.get("next_action_candidates") or [])[:6]
            if isinstance(item, dict)
        ],
    }


def _compiled_evidence_spec_summary(item: JsonObject) -> JsonObject:
    return {
        "slot_name": _string_value(item.get("slot_name")),
        "accepted_attributes": _bounded_strings(item.get("accepted_attributes"), limit=8, item_limit=80),
        "source_role": _string_value(item.get("source_role")),
        "required_source_families": _bounded_strings(item.get("required_source_families"), limit=8, item_limit=60),
        "target_period": _string_value(item.get("target_period")),
        "statement": _string_value(item.get("statement")),
        "line_item": _string_value(item.get("line_item")),
        "required": bool(item.get("required")) if "required" in item else True,
    }


def _compiled_transform_spec_summary(item: JsonObject) -> JsonObject:
    return {
        "name": _string_value(item.get("name")),
        "required_slots": _bounded_strings(item.get("required_slots"), limit=12, item_limit=80),
        "expression": _truncate(_string_value(item.get("expression")), 160),
        "output_unit": _string_value(item.get("output_unit")),
        "output_attribute": _string_value(item.get("output_attribute")),
    }


def _normalize_next_move_aliases(parsed: JsonObject) -> JsonObject:
    result: JsonObject = {"next_queries": [], "next_source_families": [], "next_document_targets": []}
    raw_moves = parsed.get("next_acquisition_moves") or parsed.get("next_moves") or parsed.get("recommended_next_actions")
    if not isinstance(raw_moves, list):
        return result
    for move in raw_moves[:16]:
        if isinstance(move, str):
            text = move.strip()
            if text:
                result["next_queries"].append(text)
            continue
        if not isinstance(move, dict):
            continue
        for key in ("query", "search_query", "search", "q"):
            text = _string_value(move.get(key))
            if text:
                result["next_queries"].append(text)
        for key in ("target", "url", "uri", "document_url", "direct_url"):
            text = _string_value(move.get(key))
            if text:
                result["next_document_targets"].append(text)
                if text.startswith(("http://", "https://")):
                    result["next_queries"].append(text)
        family = _string_value(move.get("source_family") or move.get("source_type") or move.get("tool"))
        if family:
            result["next_source_families"].append(family)
    return result


def _packet_selection_terms(*, goal: SearchGoal, metadata: JsonObject, compiled_hint: JsonObject) -> list[str]:
    terms: list[str] = []
    terms.extend(_string_list(metadata.get("required_slots")))
    terms.extend(_string_list(metadata.get("required_transforms")))
    terms.extend(_string_list(metadata.get("known_limitations")))
    for key in ("required_statement", "required_line_item", "company", "issuer", "doc_type", "doc_period"):
        value = _string_value(metadata.get(key))
        terms.append(value)
        if key == "required_line_item":
            terms.extend(_workbench_line_item_aliases(value))
    binding = _json_object(metadata.get("target_document_binding"))
    binding_line_item = _string_value(binding.get("required_line_item"))
    if binding_line_item:
        terms.append(binding_line_item)
        terms.extend(_workbench_line_item_aliases(binding_line_item))
    terms.append(goal.query)
    task_spec = _json_object(compiled_hint.get("task_spec"))
    terms.extend(_string_list(task_spec.get("target_entities")))
    terms.extend(_string_list(task_spec.get("target_periods")))
    terms.extend(_string_list(task_spec.get("success_criteria")))
    evidence_specs = compiled_hint.get("evidence_specs") if isinstance(compiled_hint.get("evidence_specs"), list) else []
    for spec in evidence_specs:
        if not isinstance(spec, dict):
            continue
        for key in ("slot_name", "source_role", "target_period", "statement", "line_item"):
            value = _string_value(spec.get(key))
            terms.append(value)
            if key == "line_item":
                terms.extend(_workbench_line_item_aliases(value))
        terms.extend(_string_list(spec.get("accepted_attributes")))
        for attribute in _string_list(spec.get("accepted_attributes")):
            terms.extend(_workbench_line_item_aliases(attribute))
        terms.extend(_string_list(spec.get("required_source_families")))
    transform_specs = compiled_hint.get("transform_specs") if isinstance(compiled_hint.get("transform_specs"), list) else []
    for spec in transform_specs:
        if not isinstance(spec, dict):
            continue
        for key in ("name", "expression", "output_unit", "output_attribute"):
            terms.append(_string_value(spec.get(key)))
        terms.extend(_string_list(spec.get("required_slots")))
    policy = _json_object(metadata.get("evidence_policy"))
    terms.extend(_string_list(policy.get("required_terms")))
    terms.extend(_string_list(policy.get("required_source_families")))
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _normalize_selection_term(term)
        if not normalized or normalized in seen or _low_value_selection_term(normalized):
            continue
        seen.add(normalized)
        result.append(normalized)
    return result[:96]


def _select_sources(
    sources: list[SearchSource],
    *,
    target_contract: JsonObject,
    terms: list[str],
    limit: int,
) -> list[SearchSource]:
    return _top_ranked(sources, limit=limit, score=lambda item: _source_selection_score(item, target_contract=target_contract, terms=terms))


def _select_documents(
    documents: list[tuple[FetchedDocument, str]],
    *,
    target_contract: JsonObject,
    terms: list[str],
    limit: int,
) -> list[tuple[FetchedDocument, str]]:
    return _top_ranked(documents, limit=limit, score=lambda item: _document_selection_score(item, target_contract=target_contract, terms=terms))


def _select_spans(
    spans: list[ExtractedSpan],
    *,
    target_contract: JsonObject,
    terms: list[str],
    limit: int,
) -> list[ExtractedSpan]:
    return _top_ranked(spans, limit=limit, score=lambda item: _span_selection_score(item, target_contract=target_contract, terms=terms))


def _select_evidence(
    evidence: list[EvidenceItem],
    *,
    target_contract: JsonObject,
    terms: list[str],
    limit: int,
) -> list[EvidenceItem]:
    return _top_ranked(evidence, limit=limit, score=lambda item: _evidence_selection_score(item, target_contract=target_contract, terms=terms))


def _select_rejected_evidence(
    rejected: list[JsonObject],
    *,
    target_contract: JsonObject,
    terms: list[str],
    limit: int,
) -> list[JsonObject]:
    return _top_ranked(rejected, limit=limit, score=lambda item: _rejected_selection_score(item, target_contract=target_contract, terms=terms))


def _top_ranked(items: list, *, limit: int, score) -> list:
    if len(items) <= limit:
        return list(items)
    ranked = sorted(enumerate(items), key=lambda pair: (-float(score(pair[1])), pair[0]))
    selected_indices = sorted(index for index, _item in ranked[:limit])
    return [items[index] for index in selected_indices]


def _source_selection_score(source: SearchSource, *, target_contract: JsonObject, terms: list[str]) -> float:
    text = " ".join([source.uri, source.title, source.snippet])
    return _selection_score(text, terms=terms) + (120.0 if _target_document_uri_match(source.uri, target_contract) else 0.0)


def _document_selection_score(item: tuple[FetchedDocument, str], *, target_contract: JsonObject, terms: list[str]) -> float:
    document, body = item
    text = " ".join([document.uri, document.title, str(body or "")[:4_000]])
    return _selection_score(text, terms=terms) + (160.0 if _target_document_uri_match(document.uri, target_contract) else 0.0)


def _span_selection_score(span: ExtractedSpan, *, target_contract: JsonObject, terms: list[str]) -> float:
    uri = _string_value(span.metadata.get("source_uri") or span.metadata.get("uri"))
    text = " ".join([uri, span.text, " ".join(_string_list(span.metadata.get("matched_terms")))])
    return _selection_score(text, terms=terms) + float(span.score) + (180.0 if _target_document_uri_match(uri, target_contract) else 0.0)


def _evidence_selection_score(evidence: EvidenceItem, *, target_contract: JsonObject, terms: list[str]) -> float:
    text = " ".join([evidence.uri, evidence.title, evidence.text])
    return _selection_score(text, terms=terms) + float(evidence.score) + (180.0 if _target_document_uri_match(evidence.uri, target_contract) else 0.0)


def _rejected_selection_score(item: JsonObject, *, target_contract: JsonObject, terms: list[str]) -> float:
    uri = _string_value(item.get("uri"))
    text = " ".join([
        uri,
        _string_value(item.get("title")),
        _string_value(item.get("reason")),
        _string_value(item.get("preview")),
    ])
    return _selection_score(text, terms=terms) + (200.0 if _target_document_uri_match(uri, target_contract) else 0.0)


def _selection_score(text: str, *, terms: list[str]) -> float:
    normalized = str(text or "").casefold()
    score = 0.0
    for term in terms:
        if term and term in normalized:
            score += min(8.0, 1.0 + len(term) / 18.0)
    if _table_or_statement_hint(normalized):
        score += 4.0
    if re.search(r"\b-?\d[\d,]*(?:\.\d+)?%?\b", normalized):
        score += 1.5
    return score


def _focused_excerpt(
    text: str,
    *,
    terms: list[str],
    target_contract: JsonObject,
    metadata: JsonObject | None = None,
    limit: int,
) -> str:
    normalized_text = " ".join(str(text or "").split())
    if len(normalized_text) <= limit:
        return normalized_text
    markers = _focused_excerpt_markers(terms=terms, target_contract=target_contract, metadata=metadata or {})
    if not markers:
        return _truncate(normalized_text, limit)
    lowered = normalized_text.casefold()
    candidates: list[tuple[float, int, str]] = []
    for marker in markers:
        marker_norm = marker.casefold().strip()
        if not marker_norm:
            continue
        start = 0
        while True:
            index = lowered.find(marker_norm, start)
            if index < 0:
                break
            window = lowered[max(0, index - 260) : min(len(lowered), index + max(limit, 520))]
            numeric_count = len(re.findall(r"\(?\d[\d,]*(?:\.\d+)?\)?", window))
            score = float(len(marker_norm)) + min(20.0, numeric_count * 2.5)
            if _table_or_statement_hint(window):
                score += 8.0
            if "html_table_fact_" in window or "html_table_" in window:
                score += 6.0
            if "value=" in window or "column_" in window:
                score += 4.0
            candidates.append((score, index, marker_norm))
            start = index + max(1, len(marker_norm))
    if not candidates:
        return _truncate(normalized_text, limit)
    _score, index, _marker = sorted(candidates, key=lambda item: (-item[0], item[1]))[0]
    start = max(0, index - 260)
    end = min(len(normalized_text), start + limit)
    if end - start < limit and start > 0:
        start = max(0, end - limit)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(normalized_text) else ""
    return prefix + normalized_text[start:end] + suffix


def _focused_excerpt_markers(
    *,
    terms: list[str],
    target_contract: JsonObject,
    metadata: JsonObject,
) -> list[str]:
    markers: list[str] = []
    for value in terms:
        markers.append(_string_value(value))
        markers.extend(_workbench_line_item_aliases(_string_value(value)))
    binding = _json_object(target_contract.get("binding"))
    for key in ("target_line_item", "target_slot", "required_line_item"):
        value = _string_value(metadata.get(key) or binding.get(key))
        if value:
            markers.append(value)
            markers.extend(_workbench_line_item_aliases(value))
    return _ordered_unique(
        [
            marker
            for marker in markers
            if marker and len(marker) >= 3 and not _low_value_selection_term(_normalize_selection_term(marker))
        ]
    )


def _workbench_line_item_aliases(value: str) -> list[str]:
    normalized = _normalize_selection_term(value)
    if not normalized:
        return []
    compact = normalized.replace(" ", "")
    if normalized in {"capital expenditures", "capital expenditure", "capex"} or (
        "capital expenditure" in normalized or compact == "paymentstoacquirepropertyplantandequipment"
    ):
        return [
            "purchases of property, plant and equipment",
            "purchases of property plant and equipment",
            "payments to acquire property, plant and equipment",
            "payments to acquire property plant and equipment",
            "purchase of property and equipment",
            "purchases of pp&e",
            "purchase of pp&e",
            "capital expenditures",
            "capital expenditure",
            "capex",
            "pp&e",
        ]
    if normalized in {"property plant and equipment net", "net property plant and equipment", "ppe net", "pp&e net"}:
        return [
            "property, plant and equipment, net",
            "property plant and equipment net",
            "property, plant and equipment net",
            "property and equipment, net",
            "net property, plant and equipment",
            "net property plant and equipment",
            "net pp&e",
            "ppe net",
        ]
    if normalized in {"revenue", "revenues", "net sales", "net revenues"}:
        return ["net sales", "net revenues", "total revenues", "sales and other operating revenues", "revenues"]
    if normalized in {"operating cash flow", "cash flow from operations"}:
        return ["net cash provided by operating activities", "cash flow from operations", "operating activities"]
    if normalized in {"cost of sales", "cost of revenue", "cogs", "cost of goods sold"}:
        return ["cost of sales", "cost of revenue", "cost of goods sold", "cost of goods and services sold"]
    return []


def _normalize_selection_term(value: object) -> str:
    text = _string_value(value).casefold().replace("_", " ").strip()
    return re.sub(r"\s+", " ", text)


def _low_value_selection_term(term: str) -> bool:
    return term in {
        "source",
        "period",
        "entity",
        "finance",
        "primary",
        "required",
        "company",
        "filing",
        "sec filings",
        "company filing",
        "final answer must pass verifier gate",
    }


def _table_or_statement_hint(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "table",
            "statement of",
            "balance sheet",
            "cash flow",
            "income statement",
            "management's discussion",
            "results of operations",
            "reconciliation",
            "operating income margin",
        )
    )


def _source_role_alias(value: str) -> str:
    normalized = " ".join(value.lower().replace("-", "_").split())
    if normalized in SOURCE_ROLES:
        return normalized
    if "annual" in normalized or "10_k" in normalized or "10-k" in normalized:
        return "annual_report"
    if "filing" in normalized or "sec" in normalized or "primary" in normalized:
        return "primary_filing"
    if "transaction" in normalized or "8_k" in normalized or "8-k" in normalized:
        return "transaction_disclosure"
    if "market" in normalized:
        return "market_data"
    if "irrelevant" in normalized or "unrelated" in normalized:
        return "irrelevant"
    return "other"


def _workbench_prompt(packet: JsonObject) -> str:
    payload = {
        "contract": WORKBENCH_PROMPT_CONTRACT,
        "schema": {
            "decision": "sufficient|continue|fail_with_limitations",
            "reason_summary": "short semantic evidence judgment",
            "accepted_evidence_ids": "list of packet evidence ids",
            "rescued_evidence_ids": "list of rejected/target candidate evidence ids worth using",
            "rejected_evidence_ids": "list of packet evidence ids not relevant enough",
            "source_roles": "list of {source_id, role, confidence, reason}",
            "slot_assessments": "list of {slot, status, supporting_evidence_ids, reason}",
            "covered_slots": "list of filled slots",
            "missing_slots": "list of missing or partial slots",
            "assumptions_needed": "list of assumptions needed before final answer",
            "next_queries": "list of concrete search queries if decision=continue",
            "next_source_families": "list of source families to try next",
            "next_document_targets": "list of direct URLs/document targets to fetch next",
            "limitations": "list of evidence limits",
        },
        "packet": packet,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _workbench_retry_prompt(packet: JsonObject, *, error: str) -> str:
    payload = {
        "contract": (
            "Previous retrieval.workbench output was invalid JSON. Return one valid JSON object matching retrieval.workbench. "
            "Use semantic judgment over packet evidence. Do not invent IDs, sources, citations, values, formulas, or URLs. "
            "Use compiled_task_hint for slots and next moves, but never as evidence. "
            "Use target_document_candidates by existing evidence_id values when they are semantically useful."
        ),
        "previous_parser_error": error,
        "packet": packet,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _workbench_retry_packet(packet: JsonObject) -> JsonObject:
    return {
        "task_goal": packet.get("task_goal"),
        "current_retrieval_goal": packet.get("current_retrieval_goal"),
        "workflow_type": packet.get("workflow_type"),
        "required_slots": packet.get("required_slots"),
        "evidence_policy": packet.get("evidence_policy"),
        "required_transforms": packet.get("required_transforms"),
        "compiled_task_hint": packet.get("compiled_task_hint"),
        "target_document_contract": packet.get("target_document_contract"),
        "document_summaries": (packet.get("document_summaries") or [])[:WORKBENCH_RETRY_DOCUMENT_LIMIT],
        "target_document_candidates": packet.get("target_document_candidates"),
        "accepted_evidence": packet.get("accepted_evidence"),
        "rejected_evidence": (packet.get("rejected_evidence") or [])[:WORKBENCH_RETRY_REJECTED_LIMIT],
        "current_citations": packet.get("current_citations"),
        "known_limitations": packet.get("known_limitations"),
    }


def _packet_diagnostics(packet: JsonObject) -> JsonObject:
    hint = packet.get("compiled_task_hint") if isinstance(packet.get("compiled_task_hint"), dict) else {}
    return {
        "source_count": len(packet.get("source_summaries") or []),
        "fetch_count": len(packet.get("fetch_summaries") or []),
        "document_count": len(packet.get("document_summaries") or []),
        "span_count": len(packet.get("extracted_spans") or []),
        "accepted_evidence_count": len(packet.get("accepted_evidence") or []),
        "rejected_evidence_count": len(packet.get("rejected_evidence") or []),
        "target_document_candidate_count": len(packet.get("target_document_candidates") or []),
        "compiled_task_hint_present": bool(hint),
        "compiled_evidence_spec_count": len(hint.get("evidence_specs") or []) if isinstance(hint, dict) else 0,
        "compiled_transform_spec_count": len(hint.get("transform_specs") or []) if isinstance(hint, dict) else 0,
        "citation_count": len(packet.get("current_citations") or []),
    }


def _source_summary(source: SearchSource) -> JsonObject:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    return {
        "source_id": source.source_id,
        "uri": source.uri,
        "title": _truncate(source.title, 180),
        "snippet": _truncate(source.snippet, 180),
        "source_kind": metadata.get("source_kind"),
        "source_family": metadata.get("source_family"),
        "authority_level": metadata.get("authority_level"),
        "target_document_binding": _json_object(metadata.get("target_document_binding")),
    }


def _span_reader_diagnostics_by_document(spans: list[ExtractedSpan]) -> dict[str, JsonObject]:
    result: dict[str, JsonObject] = {}
    for span in spans:
        if span.document_id in result:
            continue
        metadata = span.metadata if isinstance(span.metadata, dict) else {}
        reader = metadata.get("document_reader")
        if isinstance(reader, dict) and reader:
            result[span.document_id] = _document_reader_summary(reader, text_mode=_string_value(metadata.get("text_mode")))
    return result


def _document_summary(
    document: FetchedDocument,
    body: str,
    *,
    goal: SearchGoal,
    target_contract: JsonObject | None = None,
    terms: list[str] | None = None,
    span_reader_diagnostics: JsonObject | None = None,
) -> JsonObject:
    metadata = document.metadata if isinstance(document.metadata, dict) else {}
    readable_text, text_mode, reader_diagnostics = _readable_document_summary_text(document=document, body=body, goal=goal)
    reader = _document_reader_summary(
        span_reader_diagnostics if isinstance(span_reader_diagnostics, dict) else {},
        reader_diagnostics if isinstance(reader_diagnostics, dict) else {},
        text_mode=text_mode,
    )
    summary = {
        "document_id": document.document_id,
        "source_id": document.source_id,
        "uri": document.uri,
        "title": _truncate(document.title, 180),
        "artifact_id": document.artifact_id,
        "chars": len(body or ""),
        "readable_chars": len(readable_text or ""),
        "preview": _truncate(" ".join(str(readable_text or body or "").split()), 180),
        "is_target_document": _target_document_uri_match(document.uri, target_contract or {}),
        "target_document_binding": _json_object(metadata.get("target_document_binding")),
    }
    if reader:
        summary["document_reader"] = reader
    snippets = _table_like_snippets(readable_text or body, terms=terms or [])
    if snippets:
        summary["table_like_snippets"] = snippets
    return summary


def _readable_document_summary_text(*, document: FetchedDocument, body: str, goal: SearchGoal) -> tuple[str, str, JsonObject]:
    try:
        return readable_document_text_with_diagnostics(body or "", document=document, goal=goal)
    except Exception as exc:  # pragma: no cover - parser failures depend on document/dependency details.
        return (
            _truncate(" ".join(str(body or "").split()), 12_000),
            "raw_body_fallback",
            {"extraction_failure_reason": f"{type(exc).__name__}: {exc}"},
        )


def _document_reader_summary(*diagnostics: JsonObject, text_mode: str = "") -> JsonObject:
    merged: JsonObject = {}
    for item in diagnostics:
        if not isinstance(item, dict):
            continue
        for key in (
            "parser_used",
            "pages_extracted",
            "chars_extracted",
            "table_like_blocks",
            "extraction_failure_reason",
            "fallback_failures",
        ):
            value = item.get(key)
            if value not in (None, "", [], {}):
                merged[key] = value
    if text_mode:
        merged["text_mode"] = text_mode
    return merged


def _table_like_snippets(text: str, *, terms: list[str], limit: int = WORKBENCH_TABLE_SNIPPET_LIMIT) -> list[JsonObject]:
    lines = _candidate_table_lines(text)
    if not lines:
        return []
    ranked: list[tuple[float, int, JsonObject]] = []
    normalized_terms = [term for term in terms if term and len(term) >= 3]
    for index, line in enumerate(lines):
        numeric_count = len(re.findall(r"\b-?\(?\d[\d,]*(?:\.\d+)?\)?%?\b", line))
        term_hits = _selection_score(line, terms=normalized_terms)
        statement_bonus = 3.0 if _table_or_statement_hint(line.casefold()) else 0.0
        if numeric_count < 2 and term_hits <= 0.0 and statement_bonus <= 0.0:
            continue
        if numeric_count == 0:
            continue
        start = max(0, index - 1)
        end = min(len(lines), index + 2)
        snippet = " ".join(lines[start:end])
        score = float(numeric_count) * 2.0 + term_hits + statement_bonus
        ranked.append(
            (
                score,
                index,
                {
                    "line_index": index,
                    "numeric_count": numeric_count,
                    "selection_score": round(score, 3),
                    "text": _truncate(snippet, 320),
                },
            )
        )
    selected = sorted(ranked, key=lambda item: (-item[0], item[1]))[:limit]
    return [item for _score, _index, item in selected]


def _candidate_table_lines(text: str) -> list[str]:
    raw = str(text or "")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines() if line.strip()]
    if len(lines) >= 2:
        return lines[:1_500]
    chunks = re.split(r"(?<=[.;:])\s+", re.sub(r"\s+", " ", raw).strip())
    return [chunk.strip() for chunk in chunks if chunk.strip()][:1_500]


def _span_summary(
    span: ExtractedSpan,
    *,
    target_contract: JsonObject | None = None,
    terms: list[str] | None = None,
) -> JsonObject:
    return {
        "span_id": span.span_id,
        "candidate_evidence_id": f"evidence-{span.span_id}",
        "source_id": span.source_id,
        "document_id": span.document_id,
        "score": span.score,
        "text": _focused_excerpt(
            span.text,
            terms=terms or [],
            target_contract=target_contract or {},
            metadata=span.metadata,
            limit=520,
        ),
        "matched_terms": _string_list(span.metadata.get("matched_terms")),
        "text_mode": span.metadata.get("text_mode"),
        "is_target_document": _target_document_uri_match(_string_value(span.metadata.get("source_uri") or span.metadata.get("uri")), target_contract or {}),
        "target_document_binding": _json_object(span.metadata.get("target_document_binding")),
        "target_statement": span.metadata.get("target_statement"),
        "target_line_item": span.metadata.get("target_line_item"),
    }


def _evidence_summary(
    evidence: EvidenceItem,
    *,
    target_contract: JsonObject | None = None,
    terms: list[str] | None = None,
) -> JsonObject:
    qualification = evidence.diagnostics.get("qualification") if isinstance(evidence.diagnostics, dict) else {}
    span_metadata = evidence.diagnostics.get("span_metadata") if isinstance(evidence.diagnostics, dict) else {}
    span_metadata = span_metadata if isinstance(span_metadata, dict) else {}
    return {
        "evidence_id": evidence.evidence_id,
        "source_id": evidence.source_id,
        "document_id": evidence.document_id,
        "span_id": evidence.span_id,
        "uri": evidence.uri,
        "title": _truncate(evidence.title, 180),
        "is_target_document": _target_document_uri_match(evidence.uri, target_contract or {}),
        "source_role_hint": _source_role_hint(evidence.uri, evidence.title, target_contract=target_contract or {}),
        "text": _focused_excerpt(
            evidence.text,
            terms=terms or [],
            target_contract=target_contract or {},
            metadata=span_metadata,
            limit=900 if _target_document_uri_match(evidence.uri, target_contract or {}) else 320,
        ),
        "qualification": _bounded_dict(qualification if isinstance(qualification, dict) else {}, text_limit=180),
        "span_metadata": _bounded_dict(span_metadata, text_limit=180),
    }


def _citation_summary(citation: CitationItem) -> JsonObject:
    return {
        "citation_id": citation.citation_id,
        "evidence_id": citation.evidence_id,
        "uri": citation.uri,
        "title": _truncate(citation.title, 120),
        "quote": _truncate(citation.quote, 160),
    }


def _rejected_summary(item: JsonObject, *, target_contract: JsonObject | None = None) -> JsonObject:
    uri = _string_value(item.get("uri"))
    title = _string_value(item.get("title"))
    reason = _string_value(item.get("reason"))
    is_target = _target_document_uri_match(uri, target_contract or {})
    return {
        "evidence_id": item.get("evidence_id"),
        "source_id": item.get("source_id"),
        "document_id": item.get("document_id"),
        "uri": uri,
        "title": _truncate(title, 180),
        "reason": reason,
        "is_target_document": is_target,
        "source_role_hint": _source_role_hint(uri, title, target_contract=target_contract or {}),
        "review_hint": _target_review_hint(reason=reason, is_target_document=is_target),
        "missing_profile_facets": _string_list(item.get("missing_profile_facets")),
        "missing_finance_facets": _string_list(item.get("missing_finance_facets")),
        "preview": _truncate(_string_value(item.get("preview")), 460 if is_target else 240),
    }


def _target_document_contract(metadata: JsonObject) -> JsonObject:
    binding = _json_object(metadata.get("target_document_binding"))
    urls: list[str] = []
    for key in ("source_url", "doc_link"):
        text = _string_value(metadata.get(key))
        if text:
            urls.append(text)
    for key in ("source_urls", "preferred_source_urls"):
        value = metadata.get(key)
        if isinstance(value, list):
            urls.extend(_string_list(value))
    doc_link = _string_value(binding.get("doc_link"))
    if doc_link:
        urls.append(doc_link)
    expanded_urls: list[str] = []
    for item in urls:
        expanded_urls.extend([item, *unwrap_url_candidates(item)])
    urls = _ordered_unique([item for item in expanded_urls if item])
    accessions = _ordered_unique([accession for accession in (_accession_number(url) for url in urls) if accession])
    return {
        "required_for_final_citation": bool(metadata.get("benchmark_doc_retrieval") is True or doc_link or urls),
        "binding": binding,
        "target_urls": urls[:16],
        "target_accessions": accessions[:8],
        "host_validation_rule": (
            "Final answer citation must trace to one of target_urls or a document with the same SEC accession; "
            "structured companyfacts may support facts but cannot replace target-document citation."
        ),
    }


def _target_document_candidates(
    *,
    accepted: list[JsonObject],
    rejected: list[JsonObject],
    spans: list[ExtractedSpan],
    target_contract: JsonObject,
    terms: list[str],
) -> list[JsonObject]:
    candidates: list[JsonObject] = []
    seen: set[str] = set()
    for item in [*accepted, *rejected]:
        if not item.get("is_target_document"):
            continue
        evidence_id = _string_value(item.get("evidence_id"))
        if evidence_id and evidence_id in seen:
            continue
        if evidence_id:
            seen.add(evidence_id)
        candidates.append(
            {
                "evidence_id": evidence_id,
                "source_id": item.get("source_id"),
                "document_id": item.get("document_id"),
                "uri": item.get("uri"),
                "title": item.get("title"),
                "reason": item.get("reason"),
                "source_role_hint": item.get("source_role_hint"),
                "rescuable": bool(evidence_id),
                "text": item.get("text") or item.get("preview"),
                "review_hint": item.get("review_hint") or "Use semantic judgment to decide if this target-document excerpt supports the task.",
            }
        )
    for span in spans[:128]:
        evidence_id = f"evidence-{span.span_id}"
        if evidence_id in seen:
            continue
        if not _target_document_uri_match(_string_value(span.metadata.get("source_uri") or span.metadata.get("uri")), target_contract):
            continue
        seen.add(evidence_id)
        candidates.append(
            {
                "evidence_id": evidence_id,
                "source_id": span.source_id,
                "document_id": span.document_id,
                "span_id": span.span_id,
                "uri": span.metadata.get("source_uri") or span.metadata.get("uri"),
                "title": span.metadata.get("source_title"),
                "source_role_hint": "target_document_span",
                "rescuable": True,
                "text": _focused_excerpt(
                    span.text,
                    terms=terms,
                    target_contract=target_contract,
                    metadata=span.metadata,
                    limit=900,
                ),
                "review_hint": "Extracted target-document span; if semantically useful, reference this evidence_id.",
            }
        )
    return candidates[:WORKBENCH_TARGET_CANDIDATE_LIMIT]


def _target_review_hint(*, reason: str, is_target_document: bool) -> str:
    if not is_target_document:
        return ""
    if reason:
        return (
            f"Host preliminary rejection was {reason}. Treat this as non-final; judge semantically whether the "
            "target filing excerpt fills a required slot or supports a source-grounded explanation."
        )
    return "Target filing excerpt. Judge semantically whether it supports the task."


def _source_role_hint(uri: str, title: str, *, target_contract: JsonObject) -> str:
    text = f"{uri} {title}".lower()
    if _target_document_uri_match(uri, target_contract):
        return "target_document"
    if "data.sec.gov/api/xbrl/companyfacts/" in text:
        return "structured_companyfacts"
    if "sec.gov/archives/edgar/data" in text:
        return "sec_filing"
    if "annual" in text or "10-k" in text or "10k" in text:
        return "annual_report"
    return ""


def _target_document_uri_match(uri: str, target_contract: JsonObject) -> bool:
    value = _string_value(uri)
    if not value:
        return False
    if "data.sec.gov/api/xbrl/companyfacts/" in value.lower() or "data.sec.gov/submissions/" in value.lower():
        return False
    for target in _string_list(target_contract.get("target_urls")):
        if url_equivalent_or_unwrapped(value, target) or _same_url_or_prefix(value, target) or _same_url_or_prefix(target, value):
            return True
    accession = _accession_number(value)
    return bool(accession and accession in set(_string_list(target_contract.get("target_accessions"))))


def _same_url_or_prefix(left: str, right: str) -> bool:
    left_norm = _string_value(left).rstrip("/")
    right_norm = _string_value(right).rstrip("/")
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm.startswith(f"{right_norm}/")))


def _accession_number(value: str) -> str:
    match = re.search(r"\b\d{10}-\d{2}-\d{6}\b|\b\d{18}\b", _string_value(value))
    return match.group(0).replace("-", "") if match else ""


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _valid_ids(value: object, allowed: set[str]) -> list[str]:
    return [item for item in _bounded_strings(value, limit=64) if item in allowed]


def _valid_source_roles(value: object, source_ids: set[str]) -> list[JsonObject]:
    result: list[JsonObject] = []
    if not isinstance(value, list):
        return result
    for item in value[:48]:
        if not isinstance(item, dict):
            continue
        source_id = _string_value(item.get("source_id"))
        if source_id not in source_ids:
            continue
        role = _string_value(item.get("role"))
        if role not in SOURCE_ROLES:
            role = "other"
        result.append(
            {
                "source_id": source_id,
                "role": role,
                "confidence": _confidence(item.get("confidence")),
                "reason": _truncate(_string_value(item.get("reason")), 300),
            }
        )
    return result


def _valid_slot_assessments(value: object, evidence_ids: set[str]) -> list[JsonObject]:
    result: list[JsonObject] = []
    if not isinstance(value, list):
        return result
    for item in value[:48]:
        if not isinstance(item, dict):
            continue
        slot = _string_value(item.get("slot"))
        if not slot:
            continue
        status = _string_value(item.get("status"))
        if status not in SLOT_STATUSES:
            status = "partial"
        result.append(
            {
                "slot": _truncate(slot, 120),
                "status": status,
                "supporting_evidence_ids": _valid_ids(item.get("supporting_evidence_ids"), evidence_ids),
                "reason": _truncate(_string_value(item.get("reason")), 300),
            }
        )
    return result


def _invalid_reference_diagnostics(
    *,
    parsed: JsonObject,
    evidence_ids: set[str],
    source_ids: set[str],
    citation_ids: set[str],
) -> JsonObject:
    invalid_evidence = sorted(
        {
            item
            for key in ("accepted_evidence_ids", "rescued_evidence_ids", "rejected_evidence_ids")
            for item in _bounded_strings(parsed.get(key), limit=128)
            if item not in evidence_ids
        }
    )
    invalid_sources = sorted(
        {
            _string_value(item.get("source_id"))
            for item in parsed.get("source_roles", [])
            if isinstance(item, dict) and _string_value(item.get("source_id")) and _string_value(item.get("source_id")) not in source_ids
        }
    ) if isinstance(parsed.get("source_roles"), list) else []
    invalid_citations = sorted(
        {
            item
            for item in _bounded_strings(parsed.get("citation_ids"), limit=128)
            if item not in citation_ids
        }
    )
    result: JsonObject = {}
    if invalid_evidence:
        result["evidence_ids"] = invalid_evidence[:16]
    if invalid_sources:
        result["source_ids"] = invalid_sources[:16]
    if invalid_citations:
        result["citation_ids"] = invalid_citations[:16]
    return result


def _bounded_strings(value: object, *, limit: int, item_limit: int = 120) -> list[str]:
    return [_truncate(item, item_limit) for item in _string_list(value)[:limit]]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _bounded_dict(value: object, *, text_limit: int) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key, item in value.items():
        if isinstance(item, str):
            result[str(key)] = _truncate(item, text_limit)
        elif isinstance(item, (int, float, bool)) or item is None:
            result[str(key)] = item
        elif isinstance(item, list):
            result[str(key)] = [_truncate(str(child), text_limit) for child in item[:12]]
        elif isinstance(item, dict):
            result[str(key)] = _bounded_dict(item, text_limit=text_limit)
    return result


def _string_value(value: object) -> str:
    return str(value or "").strip()


def _truncate(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 3)].rstrip()}..."


def _confidence(value: object) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, parsed))
