from __future__ import annotations

import json
from dataclasses import dataclass, field

from kernel_v3.contracts import JsonObject
from kernel_v3.processors.contracts import RETRIEVAL_WORKBENCH_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem, ExtractedSpan, FetchedDocument, SearchGoal, SearchSource


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
        return RetrievalWorkbenchResult(
            status="failed",
            decision="continue",
            reason_summary="retrieval workbench processor failed; host continues with deterministic verifier state",
            diagnostics={
                "reason": outcome.result.error or "invalid_workbench_output",
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
    return {
        "task_goal": _string_value(metadata.get("root_goal") or metadata.get("task_goal") or goal.query),
        "current_retrieval_goal": goal.query,
        "workflow_type": _string_value(metadata.get("workflow_type") or metadata.get("research_task_kind")),
        "required_slots": _string_list(metadata.get("required_slots")),
        "evidence_policy": _json_object(metadata.get("evidence_policy")),
        "required_transforms": _string_list(metadata.get("required_transforms")),
        "source_summaries": [_source_summary(item) for item in sources[:48]],
        "fetch_summaries": [_bounded_dict(item, text_limit=280) for item in fetch_summaries[-48:]],
        "document_summaries": [_document_summary(document, body) for document, body in documents[-32:]],
        "extracted_spans": [_span_summary(item) for item in spans[:96]],
        "accepted_evidence": [_evidence_summary(item) for item in evidence[:64]],
        "rejected_evidence": [_rejected_summary(item) for item in rejected_evidence[:96]],
        "current_slot_state": _json_object(metadata.get("slot_state")),
        "current_claim_state": _json_object(metadata.get("claim_state")),
        "current_citations": [_citation_summary(item) for item in citations[:64]],
        "known_limitations": _string_list(metadata.get("known_limitations")),
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
    return (
        "You are Holo Kernel v3 retrieval.workbench. Judge evidence relevance and next acquisition moves semantically. "
        "Do not invent evidence, source IDs, citation IDs, facts, numeric values, formulas, or URLs. "
        "You may only reference IDs present in the packet. Host will validate provenance, authority, policy, and numeric support. "
        "Return exactly one JSON object with the requested schema. Decide whether evidence is sufficient for the task, "
        "which slots are filled or missing, which source roles matter, and what the next queries/source families/document targets should be.\n\n"
        f"Packet:\n{json.dumps(packet, ensure_ascii=False, sort_keys=True)}"
    )


def _packet_diagnostics(packet: JsonObject) -> JsonObject:
    return {
        "source_count": len(packet.get("source_summaries") or []),
        "fetch_count": len(packet.get("fetch_summaries") or []),
        "document_count": len(packet.get("document_summaries") or []),
        "span_count": len(packet.get("extracted_spans") or []),
        "accepted_evidence_count": len(packet.get("accepted_evidence") or []),
        "rejected_evidence_count": len(packet.get("rejected_evidence") or []),
        "citation_count": len(packet.get("current_citations") or []),
    }


def _source_summary(source: SearchSource) -> JsonObject:
    metadata = source.metadata if isinstance(source.metadata, dict) else {}
    return {
        "source_id": source.source_id,
        "uri": source.uri,
        "title": _truncate(source.title, 180),
        "snippet": _truncate(source.snippet, 360),
        "source_kind": metadata.get("source_kind"),
        "source_family": metadata.get("source_family"),
        "authority_level": metadata.get("authority_level"),
    }


def _document_summary(document: FetchedDocument, body: str) -> JsonObject:
    return {
        "document_id": document.document_id,
        "source_id": document.source_id,
        "uri": document.uri,
        "title": _truncate(document.title, 180),
        "artifact_id": document.artifact_id,
        "chars": len(body or ""),
        "preview": _truncate(" ".join(str(body or "").split()), 360),
    }


def _span_summary(span: ExtractedSpan) -> JsonObject:
    return {
        "span_id": span.span_id,
        "source_id": span.source_id,
        "document_id": span.document_id,
        "score": span.score,
        "text": _truncate(span.text, 700),
        "matched_terms": _string_list(span.metadata.get("matched_terms")),
        "text_mode": span.metadata.get("text_mode"),
    }


def _evidence_summary(evidence: EvidenceItem) -> JsonObject:
    qualification = evidence.diagnostics.get("qualification") if isinstance(evidence.diagnostics, dict) else {}
    return {
        "evidence_id": evidence.evidence_id,
        "source_id": evidence.source_id,
        "document_id": evidence.document_id,
        "span_id": evidence.span_id,
        "uri": evidence.uri,
        "title": _truncate(evidence.title, 180),
        "text": _truncate(evidence.text, 800),
        "qualification": _bounded_dict(qualification if isinstance(qualification, dict) else {}, text_limit=180),
    }


def _citation_summary(citation: CitationItem) -> JsonObject:
    return {
        "citation_id": citation.citation_id,
        "evidence_id": citation.evidence_id,
        "uri": citation.uri,
        "title": _truncate(citation.title, 180),
        "quote": _truncate(citation.quote, 360),
    }


def _rejected_summary(item: JsonObject) -> JsonObject:
    return {
        "evidence_id": item.get("evidence_id"),
        "source_id": item.get("source_id"),
        "document_id": item.get("document_id"),
        "uri": item.get("uri"),
        "title": _truncate(_string_value(item.get("title")), 180),
        "reason": item.get("reason"),
        "missing_profile_facets": _string_list(item.get("missing_profile_facets")),
        "missing_finance_facets": _string_list(item.get("missing_finance_facets")),
        "preview": _truncate(_string_value(item.get("preview")), 600),
    }


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
