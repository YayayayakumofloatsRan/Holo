from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from kernel_v3.contracts import JsonObject
from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profile_policy import (
    evidence_compaction_policy,
    profile_evidence_facets,
)
from kernel_v3.retrieval.contracts import EvidenceItem, ExtractedSpan, SearchGoal
from kernel_v3.retrieval.finance_metrics import finance_metric_intent_score


@dataclass(frozen=True, kw_only=True)
class EvidenceCandidate:
    evidence: EvidenceItem
    span: ExtractedSpan


def compact_evidence_candidates(
    candidates: list[EvidenceCandidate],
    *,
    goal: SearchGoal,
    research_profile: ResearchProfile | None,
    limit: int,
) -> tuple[list[EvidenceCandidate], list[JsonObject], JsonObject]:
    if not candidates or limit <= 0:
        return [], [], {"strategy": "none", "candidate_count": len(candidates), "selected_count": 0}
    policy = evidence_compaction_policy(research_profile)
    has_profile_compaction = bool(policy)
    effective_limit = _positive_int(policy.get("max_items"), default=limit)
    effective_limit = max(1, min(limit, effective_limit))
    per_source_limit = _positive_int(policy.get("per_source_limit"), default=effective_limit)
    required_facets = profile_evidence_facets(goal=goal, research_profile=research_profile)
    unique_candidates = _dedupe_candidates(candidates, goal=goal, required_facets=required_facets)
    ordered = sorted(
        unique_candidates,
        key=lambda candidate: _candidate_sort_key(candidate, goal=goal, required_facets=required_facets),
    )

    selected: list[EvidenceCandidate] = []
    selected_ids: set[str] = set()
    source_counts: dict[str, int] = {}
    selected_target_documents: list[str] = []
    target_document_urls = _target_document_urls(goal)
    if target_document_urls:
        candidate = _best_candidate_for_target_document(
            ordered,
            goal=goal,
            target_urls=target_document_urls,
            selected_ids=selected_ids,
            source_counts=source_counts,
            per_source_limit=per_source_limit,
        )
        if candidate is not None:
            _select_candidate(candidate, selected, selected_ids, source_counts)
            selected_target_documents.append(str(candidate.evidence.uri or ""))
    target_entities = _target_entity_markers(goal)
    if target_entities:
        for target in target_entities:
            candidate = _best_candidate_for_target(
                ordered,
                target=target,
                selected_ids=selected_ids,
                source_counts=source_counts,
                per_source_limit=per_source_limit,
            )
            if candidate is not None:
                _select_candidate(candidate, selected, selected_ids, source_counts)
            if len(selected) >= effective_limit:
                break
    selected_target_line_items: list[str] = []
    if len(selected) < effective_limit:
        for line_item in _target_line_item_markers(ordered):
            if len(selected) >= effective_limit:
                break
            candidate = _best_candidate_for_target_line_item(
                ordered,
                line_item=line_item,
                selected_ids=selected_ids,
                source_counts=source_counts,
                per_source_limit=per_source_limit,
            )
            if candidate is not None:
                _select_candidate(candidate, selected, selected_ids, source_counts)
                selected_target_line_items.append(line_item)
            if len(selected) >= effective_limit:
                break
    if bool(policy.get("prefer_facet_coverage", True)) and required_facets and len(selected) < effective_limit:
        for facet in required_facets:
            if len(selected) >= effective_limit:
                break
            candidate = _best_candidate_for_facet(
                ordered,
                facet=facet,
                selected_ids=selected_ids,
                source_counts=source_counts,
                per_source_limit=per_source_limit,
            )
            if candidate is not None:
                _select_candidate(candidate, selected, selected_ids, source_counts)
            if len(selected) >= effective_limit:
                break

    for candidate in ordered:
        if len(selected) >= effective_limit:
            break
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        _select_candidate(candidate, selected, selected_ids, source_counts)

    rejected = [
        _compaction_rejection(
            candidate,
            reason="evidence_compacted_out" if has_profile_compaction else "evidence_item_limit_reached",
        )
        for candidate in unique_candidates
        if candidate.evidence.evidence_id not in selected_ids
    ]
    diagnostics = {
        "strategy": str(policy.get("strategy_id") or "evidence_item_limit"),
        "candidate_count": len(candidates),
        "deduped_candidate_count": len(unique_candidates),
        "selected_count": len(selected),
        "compacted_out_count": len(rejected),
        "limit": effective_limit,
        "per_source_limit": per_source_limit,
        "required_facets": required_facets,
        "selected_facets": _selected_facets(selected),
        "selected_target_line_items": selected_target_line_items,
        "selected_target_documents": selected_target_documents,
    }
    return selected, rejected, diagnostics


def _dedupe_candidates(
    candidates: list[EvidenceCandidate],
    *,
    goal: SearchGoal,
    required_facets: list[str],
) -> list[EvidenceCandidate]:
    best_by_hash: dict[str, EvidenceCandidate] = {}
    for candidate in candidates:
        key = _text_hash(candidate.evidence.text)
        existing = best_by_hash.get(key)
        if existing is None or _candidate_sort_key(
            candidate,
            goal=goal,
            required_facets=required_facets,
        ) < _candidate_sort_key(existing, goal=goal, required_facets=required_facets):
            best_by_hash[key] = candidate
    return list(best_by_hash.values())


def _best_candidate_for_facet(
    candidates: list[EvidenceCandidate],
    *,
    facet: str,
    selected_ids: set[str],
    source_counts: dict[str, int],
    per_source_limit: int,
) -> EvidenceCandidate | None:
    for candidate in candidates:
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        if facet in _candidate_facets(candidate):
            return candidate
    return None


def _best_candidate_for_target(
    candidates: list[EvidenceCandidate],
    *,
    target: str,
    selected_ids: set[str],
    source_counts: dict[str, int],
    per_source_limit: int,
) -> EvidenceCandidate | None:
    for candidate in candidates:
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        if _candidate_matches_target(candidate, target):
            return candidate
    return None


def _best_candidate_for_target_document(
    candidates: list[EvidenceCandidate],
    *,
    goal: SearchGoal,
    target_urls: list[str],
    selected_ids: set[str],
    source_counts: dict[str, int],
    per_source_limit: int,
) -> EvidenceCandidate | None:
    matches: list[EvidenceCandidate] = []
    for candidate in candidates:
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        if _candidate_matches_target_document(candidate, target_urls):
            matches.append(candidate)
    if not matches:
        return None
    return min(matches, key=lambda candidate: _target_document_sort_key(candidate, goal=goal))


def _best_candidate_for_target_line_item(
    candidates: list[EvidenceCandidate],
    *,
    line_item: str,
    selected_ids: set[str],
    source_counts: dict[str, int],
    per_source_limit: int,
) -> EvidenceCandidate | None:
    matches: list[EvidenceCandidate] = []
    for candidate in candidates:
        if candidate.evidence.evidence_id in selected_ids:
            continue
        if source_counts.get(candidate.evidence.source_id, 0) >= per_source_limit:
            continue
        if _candidate_target_line_item(candidate) == line_item and _candidate_target_period(candidate):
            matches.append(candidate)
    if not matches:
        return None
    return min(matches, key=_target_line_item_sort_key)


def _select_candidate(
    candidate: EvidenceCandidate,
    selected: list[EvidenceCandidate],
    selected_ids: set[str],
    source_counts: dict[str, int],
) -> None:
    selected.append(candidate)
    selected_ids.add(candidate.evidence.evidence_id)
    source_counts[candidate.evidence.source_id] = source_counts.get(candidate.evidence.source_id, 0) + 1


def _candidate_sort_key(
    candidate: EvidenceCandidate,
    *,
    goal: SearchGoal,
    required_facets: list[str],
) -> tuple[float, float, float, float, float, float, float, float, int, str]:
    evidence = candidate.evidence
    qualification = evidence.diagnostics.get("qualification")
    facets = _candidate_facets(candidate)
    authority = _authority_score(evidence)
    numeric_bonus = 0.2 if isinstance(qualification, dict) and qualification.get("profile_numeric_fact_present") else 0.0
    required_specific = _specific_required_facets(required_facets)
    specific_overlap = len(set(facets).intersection(required_specific))
    metric_intent_score = finance_metric_intent_score(evidence.text, query=goal.query)
    metric_density = _metric_density(evidence.text)
    structured_summary_bonus = 1.0 if _looks_like_structured_finance_summary(evidence.text) else 0.0
    market_valuation_bonus = _market_valuation_bonus(candidate, goal=goal)
    return (
        -market_valuation_bonus,
        -authority,
        -float(specific_overlap),
        -float(metric_intent_score),
        -structured_summary_bonus,
        -float(metric_density),
        -(float(evidence.score) + numeric_bonus),
        -float(len(facets)),
        len(evidence.text),
        evidence.evidence_id,
    )


def _target_line_item_sort_key(candidate: EvidenceCandidate) -> tuple[int, int, int, int, int, float, str]:
    # Target-bound structured spans are generated in EvidenceSpec priority order.
    # Preserve that order instead of letting broad finance facet scoring drop a
    # required slot before formula planning gets a chance to bind it.
    start_offset = candidate.span.start_offset
    if start_offset < 0:
        start_offset = 1_000_000_000
    text = candidate.evidence.text.lower()
    line_item = _candidate_target_line_item(candidate)
    alias_match = _candidate_line_item_alias_match(text, line_item)
    table_fact = "html_table_fact_" in text or ("html_table_" in text and "column_" in text)
    numeric_count = len(re.findall(r"\(?\d[\d,]*(?:\.\d+)?\)?", text))
    statement_match = _candidate_statement_match(text, candidate)
    return (
        0 if alias_match and numeric_count else 1,
        0 if table_fact else 1,
        0 if statement_match else 1,
        -min(numeric_count, 20),
        start_offset,
        -float(candidate.evidence.score),
        candidate.evidence.evidence_id,
    )


def _target_document_sort_key(candidate: EvidenceCandidate, *, goal: SearchGoal) -> tuple[int, int, float, float, float, int, str]:
    text = f"{candidate.evidence.title} {candidate.evidence.text}".lower()
    line_item_strength = _candidate_line_item_strength(candidate)
    explanation_hits = sum(
        1
        for marker in (
            "operating income margin",
            "operating margin",
            "cost of sales",
            "gross margin",
            "sg&a",
            "primarily due",
            "drove",
            "driven by",
            "results of operations",
            "management's discussion",
        )
        if marker in text
    )
    start_offset = candidate.span.start_offset
    if start_offset < 0:
        start_offset = 1_000_000_000
    return (
        -line_item_strength,
        -explanation_hits,
        -finance_metric_intent_score(candidate.evidence.text, query=goal.query),
        -float(candidate.evidence.score),
        -_authority_score(candidate.evidence),
        start_offset,
        candidate.evidence.evidence_id,
    )


def _candidate_line_item_strength(candidate: EvidenceCandidate) -> int:
    line_item = _candidate_target_line_item(candidate)
    if not line_item:
        return 0
    text = candidate.evidence.text.lower()
    score = 0
    if _candidate_line_item_alias_match(text, line_item):
        score += 4
    if _candidate_statement_match(text, candidate):
        score += 2
    if "html_table_fact_" in text or ("html_table_" in text and "column_" in text):
        score += 2
    if re.search(r"\(?\d[\d,]*(?:\.\d+)?\)?", text):
        score += 1
    return score


def _candidate_line_item_alias_match(text: str, line_item: str) -> bool:
    normalized = str(line_item or "").strip().lower()
    if not normalized:
        return False
    aliases = _line_item_aliases(normalized)
    return any(alias and alias in text for alias in aliases)


def _candidate_statement_match(text: str, candidate: EvidenceCandidate) -> bool:
    metadata = _candidate_span_metadata(candidate)
    statement = str(metadata.get("target_statement") or "").strip().lower()
    if statement == "cash_flow_statement":
        return any(
            marker in text
            for marker in (
                "statement of cash flows",
                "statements of cash flows",
                "cash flows from investing activities",
                "cash flows from operating activities",
                "cash flows",
            )
        )
    if statement == "income_statement":
        return any(marker in text for marker in ("statement of income", "statement of operations", "income statement"))
    if statement == "balance_sheet":
        return "balance sheet" in text or "total assets" in text
    return False


def _line_item_aliases(line_item: str) -> list[str]:
    normalized = " ".join(str(line_item or "").lower().replace("_", " ").replace("&", " and ").split())
    if not normalized:
        return []
    if normalized in {"capital expenditures", "capital expenditure", "capex"} or "capital expenditure" in normalized:
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
        return ["revenue", "revenues", "net sales", "net revenues", "sales and other operating revenues"]
    if normalized in {"operating cash flow", "cash flow from operations"}:
        return ["net cash provided by operating activities", "cash flow from operations", "operating activities"]
    if normalized in {"cost of sales", "cost of revenue", "cogs", "cost of goods sold"}:
        return ["cost of sales", "cost of revenue", "cost of goods sold", "cost of goods and services sold"]
    return [normalized]


def _target_document_urls(goal: SearchGoal) -> list[str]:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    binding = metadata.get("target_document_binding")
    if not isinstance(binding, dict) and metadata.get("benchmark_doc_retrieval") is not True:
        return []
    raw: list[object] = []
    if isinstance(binding, dict):
        raw.append(binding.get("doc_link"))
    for key in ("source_url", "doc_link"):
        raw.append(metadata.get(key))
    for key in ("preferred_source_urls", "source_urls"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw.extend(value)
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw:
        url = str(item or "").strip()
        if not url or url in seen or _structured_data_url(url):
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _candidate_matches_target_document(candidate: EvidenceCandidate, target_urls: list[str]) -> bool:
    uri = str(candidate.evidence.uri or "").strip()
    if not uri:
        return False
    if _structured_data_url(uri):
        return False
    for target_url in target_urls:
        if _same_url_or_prefix(uri, target_url) or _same_url_or_prefix(target_url, uri):
            return True
        accession = _accession_number(uri)
        target_accession = _accession_number(target_url)
        if accession and target_accession and accession == target_accession:
            return True
    return False


def _structured_data_url(url: str) -> bool:
    lowered = str(url or "").lower()
    return "data.sec.gov/api/xbrl/companyfacts/" in lowered or "data.sec.gov/submissions/" in lowered


def _same_url_or_prefix(left: str, right: str) -> bool:
    left_norm = str(left or "").strip().rstrip("/")
    right_norm = str(right or "").strip().rstrip("/")
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm.startswith(f"{right_norm}/")))


def _accession_number(value: str) -> str:
    match = re.search(r"\b\d{10}-\d{2}-\d{6}\b|\b\d{18}\b", str(value or ""))
    return match.group(0).replace("-", "") if match else ""


def _market_valuation_bonus(candidate: EvidenceCandidate, *, goal: SearchGoal) -> float:
    goal_text = f"{goal.query} {_metadata_text(goal.metadata)}".lower()
    compact_goal = "".join(ch for ch in goal_text if ch.isalnum())
    if not any(
        marker in goal_text or marker in compact_goal
        for marker in (
            "ev/ebitda",
            "evebitda",
            "ev/revenue",
            "evrevenue",
            "enterprise value",
            "market cap",
            "market capitalization",
            "valuation multiple",
            "trading multiple",
        )
    ):
        return 0.0
    assessment = candidate.evidence.diagnostics.get("source_assessment")
    assessment = assessment if isinstance(assessment, dict) else {}
    family = str(assessment.get("source_family") or "").strip().lower()
    if family != "market_data_provider":
        return 0.0
    text = str(candidate.evidence.text or "").lower()
    if any(marker in text for marker in ("metric=market cap", "metric=enterprise value", "market cap", "enterprise value")):
        return 2.0
    return 0.5


def _metadata_text(value: object) -> str:
    if isinstance(value, dict):
        return " ".join(_metadata_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_metadata_text(item) for item in value)
    return str(value or "")


def _target_entity_markers(goal: SearchGoal) -> list[str]:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    raw_items: list[object] = []
    for key in ("target_tickers", "tickers"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
        elif isinstance(value, str):
            raw_items.extend(value.replace(";", ",").split(","))
    for key in ("ticker", "sec_ticker"):
        value = metadata.get(key)
        if isinstance(value, str):
            raw_items.append(value)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        marker = str(item or "").strip()
        if not marker:
            continue
        normalized = marker.upper()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(marker)
    return result


def _candidate_matches_target(candidate: EvidenceCandidate, target: str) -> bool:
    target_norm = str(target or "").strip().lower()
    if not target_norm:
        return False
    compact_target = "".join(ch for ch in target_norm if ch.isalnum())
    haystack = " ".join(
        str(value or "")
        for value in (
            candidate.evidence.title,
            candidate.evidence.uri,
            candidate.evidence.text,
        )
    ).lower()
    compact_haystack = "".join(ch for ch in haystack if ch.isalnum())
    return (
        f"ticker={target_norm}" in haystack
        or f"/{target_norm}/" in haystack
        or f"stocks/{target_norm}" in haystack
        or f"quote/{target_norm}" in haystack
        or compact_target in compact_haystack
    )


def _target_line_item_markers(candidates: list[EvidenceCandidate]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for candidate in sorted(candidates, key=_target_line_item_marker_sort_key):
        line_item = _candidate_target_line_item(candidate)
        if not line_item or line_item in seen:
            continue
        if not _candidate_target_period(candidate):
            continue
        seen.add(line_item)
        result.append(line_item)
    return result


def _target_line_item_marker_sort_key(candidate: EvidenceCandidate) -> tuple[int, int, str]:
    start_offset = candidate.span.start_offset
    if start_offset < 0:
        start_offset = 1_000_000_000
    return (start_offset, len(candidate.evidence.text), candidate.evidence.evidence_id)


def _candidate_target_line_item(candidate: EvidenceCandidate) -> str:
    metadata = _candidate_span_metadata(candidate)
    return str(metadata.get("target_line_item") or "").strip().lower()


def _candidate_target_period(candidate: EvidenceCandidate) -> str:
    metadata = _candidate_span_metadata(candidate)
    return str(metadata.get("target_period") or "").strip()


def _candidate_span_metadata(candidate: EvidenceCandidate) -> JsonObject:
    if isinstance(candidate.span.metadata, dict) and candidate.span.metadata:
        return candidate.span.metadata
    span_metadata = candidate.evidence.diagnostics.get("span_metadata")
    return span_metadata if isinstance(span_metadata, dict) else {}


def _candidate_facets(candidate: EvidenceCandidate) -> list[str]:
    qualification = candidate.evidence.diagnostics.get("qualification")
    if not isinstance(qualification, dict):
        return []
    raw = qualification.get("covered_profile_facets")
    if not isinstance(raw, list):
        raw = qualification.get("covered_finance_facets")
    return [item for item in (str(value).strip() for value in raw or [] if isinstance(value, str)) if item]


def _authority_score(evidence: EvidenceItem) -> float:
    assessment = evidence.diagnostics.get("source_assessment")
    if not isinstance(assessment, dict):
        return 0.0
    value = assessment.get("authority_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _specific_required_facets(required_facets: list[str]) -> set[str]:
    broad = {"official_financial_statement", "financial_metric", "scholarly_work", "bibliographic_metadata"}
    return {facet for facet in required_facets if facet not in broad}


def _metric_density(text: str) -> int:
    normalized = text.lower()
    return normalized.count("metric=") + normalized.count("concept=")


def _looks_like_structured_finance_summary(text: str) -> bool:
    normalized = text.lower()
    return "sec companyfacts annual financial summary" in normalized or (
        "period=annual" in normalized and "metric=" in normalized and "value=" in normalized
    )


def _selected_facets(selected: list[EvidenceCandidate]) -> list[str]:
    facets: list[str] = []
    seen: set[str] = set()
    for candidate in selected:
        for facet in _candidate_facets(candidate):
            if facet in seen:
                continue
            seen.add(facet)
            facets.append(facet)
    return facets


def _compaction_rejection(candidate: EvidenceCandidate, *, reason: str) -> JsonObject:
    return {
        "evidence_id": candidate.evidence.evidence_id,
        "source_id": candidate.evidence.source_id,
        "document_id": candidate.evidence.document_id,
        "uri": candidate.evidence.uri,
        "title": candidate.evidence.title,
        "reason": reason,
        "covered_profile_facets": _candidate_facets(candidate),
        "target_line_item": _candidate_target_line_item(candidate),
        "target_period": _candidate_target_period(candidate),
        "preview": candidate.evidence.text[:160],
    }


def _positive_int(value: object, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _text_hash(text: str) -> str:
    return hashlib.sha256(" ".join(text.lower().split()).encode("utf-8")).hexdigest()
