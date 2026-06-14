from __future__ import annotations

import re

from kernel_v3.research.contracts import ResearchProfile
from kernel_v3.research.profile_policy import (
    QUERY_FACET_ALIASES,
    QUERY_FACET_TRIGGERS,
    assess_profile_evidence_coverage,
    assess_query_facet_coverage,
    evidence_source_kind,
    profile_evidence_facets,
    profile_is_discovery_goal,
    qualify_profile_evidence_candidate,
    query_facets,
    resolve_goal_research_profile,
)
from kernel_v3.research.profiles import (
    FINANCE_DISCOVERY_SOURCE_KINDS,
    FINANCE_FUNDAMENTAL_FACET_ALIASES,
    FINANCE_FUNDAMENTAL_FACET_TRIGGERS,
    FINANCE_FUNDAMENTAL_TASK_KINDS,
    FINANCE_FUNDAMENTALS_PROFILE_ID,
    FINANCE_NUMERIC_FACT_FACETS,
)
from kernel_v3.research.identity import resolve_issuer_identity
from kernel_v3.research.issuer_registry import builtin_issuers_for_text
from kernel_v3.research.source_policy import (
    assess_evidence_source,
    source_authority_summary,
    source_quality_summary,
)
from kernel_v3.retrieval.contracts import (
    CitationItem,
    EvidenceEvaluationDecision,
    EvidenceItem,
    SearchGoal,
)
from kernel_v3.retrieval.targeting import assess_target_entity_coverage, target_entity_diagnostics


TEMPLATE_PLACEHOLDER_RE = re.compile(r"\{\{[^{}]{1,120}\}\}|\$\{[^{}]{1,120}\}|<%[^%]{1,120}%>")


def qualify_evidence_candidate(
    *,
    goal: SearchGoal,
    evidence: EvidenceItem,
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    result = dict(
        qualify_profile_evidence_candidate(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
    )
    target_diagnostics = target_entity_diagnostics(goal.query, [evidence.title, evidence.uri, evidence.text])
    if bool(target_diagnostics.get("target_entity_required")):
        result["target_entity"] = target_diagnostics
        result["required_target_phrases"] = target_diagnostics.get("required_target_phrases", [])
        result["matched_target_phrases"] = target_diagnostics.get("matched_target_phrases", [])
        result["missing_target_phrases"] = target_diagnostics.get("missing_target_phrases", [])
        finance_requested_issuer_match = _is_finance_profile(
            goal=goal,
            research_profile=research_profile,
        ) and _finance_evidence_matches_requested_issuer(goal=goal, evidence=evidence)
        if finance_requested_issuer_match:
            result["target_entity"] = {
                **target_diagnostics,
                "target_entity_satisfied": True,
                "finance_requested_issuer_match": True,
            }
            result["matched_target_phrases"] = target_diagnostics.get("matched_target_phrases", [])
            result["missing_target_phrases"] = []
        elif not bool(target_diagnostics.get("target_entity_satisfied")):
            result["accepted"] = False
            result["reason"] = "target_entity_mismatch"
    if _is_finance_profile(goal=goal, research_profile=research_profile):
        _add_finance_compatibility_fields(result)
        if (
            not bool(result.get("accepted", True))
            and result.get("reason") == "missing_finance_fact_in_span"
            and _finance_source_grounded_target_document_candidate(goal=goal, evidence=evidence)
        ):
            result["accepted"] = True
            result["reason"] = "source_grounded_target_document_candidate"
            result["covered_profile_facets"] = _ordered_unique([
                *_string_list(result.get("covered_profile_facets")),
                "official_financial_statement",
                "source_grounded_text",
            ])
            result["covered_finance_facets"] = _ordered_unique([
                *_string_list(result.get("covered_finance_facets")),
                "official_financial_statement",
                "source_grounded_text",
            ])
            result["missing_profile_facets"] = [
                item for item in _string_list(result.get("missing_profile_facets")) if item != "numeric_profile_fact"
            ]
            result["missing_finance_facets"] = [
                item for item in _string_list(result.get("missing_finance_facets")) if item != "numeric_financial_fact"
            ]
            result["profile_numeric_fact_required"] = False
            result["finance_numeric_fact_required"] = False
        entity_mismatch = _finance_companyfacts_entity_mismatch(goal=goal, evidence=evidence)
        if entity_mismatch:
            result["accepted"] = False
            result["reason"] = "finance_companyfacts_entity_mismatch"
            result["target_entity"] = entity_mismatch
        if bool(result.get("accepted", True)):
            qualifier_diagnostics = _finance_specialized_query_coverage(goal=goal, evidence=[evidence])
            result["finance_specialized_query_coverage"] = qualifier_diagnostics
            if (
                qualifier_diagnostics["required"]
                and not qualifier_diagnostics["satisfied"]
                and not _finance_complementary_fact_source(goal=goal, evidence=evidence)
                and not _finance_target_bound_structured_fact_source(goal=goal, evidence=evidence)
            ):
                result["accepted"] = False
                result["reason"] = "finance_specialized_query_terms_missing"
    if bool(result.get("accepted", True)):
        weak_source = _weak_source_for_required_profile(goal=goal, evidence=evidence, research_profile=research_profile)
        if weak_source:
            result["accepted"] = False
            result["reason"] = "weak_source_authority_for_research_profile"
            result["source_authority"] = weak_source
    if bool(result.get("accepted", True)) and _is_academic_profile(goal=goal, research_profile=research_profile):
        topic_diagnostics = _query_topic_coverage(
            goal.query,
            [f"{evidence.title} {evidence.uri} {evidence.text}"],
        )
        result["query_topic_coverage"] = topic_diagnostics
        if topic_diagnostics["topic_terms"] and not topic_diagnostics["satisfied"]:
            result["accepted"] = False
            result["reason"] = "query_topic_terms_missing"
    placeholder_diagnostics = _template_placeholder_diagnostics(evidence.text)
    if bool(placeholder_diagnostics.get("template_placeholder_evidence")):
        result["accepted"] = False
        result["reason"] = "template_placeholder_evidence"
        result["template_placeholder"] = placeholder_diagnostics
    return result


class EvidenceEvaluator:
    def evaluate(
        self,
        *,
        goal: SearchGoal,
        evidence: list[EvidenceItem],
        citations: list[CitationItem],
        research_profile: ResearchProfile | None = None,
    ) -> EvidenceEvaluationDecision:
        diagnostics = {
            "query": goal.query,
            "max_fetches": goal.max_fetches,
            "max_spans_per_document": goal.max_spans_per_document,
        }
        sufficient = bool(evidence and citations)
        reason = "evidence_with_citations" if sufficient else "insufficient_evidence"

        facet_diagnostics = assess_query_facet_coverage(goal=goal, evidence=evidence)
        diagnostics.update(facet_diagnostics)
        if sufficient and facet_diagnostics["missing_query_facets"]:
            sufficient = False
            reason = "query_facets_missing"

        target_diagnostics = assess_target_entity_coverage(
            goal.query,
            [f"{item.title} {item.uri} {item.text}" for item in evidence],
        )
        diagnostics.update(target_diagnostics)
        if (
            sufficient
            and target_diagnostics["target_entity_required"]
            and target_diagnostics["missing_target_phrases"]
        ):
            sufficient = False
            reason = "target_entity_mismatch"

        profile_diagnostics = assess_profile_evidence_coverage(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
        diagnostics.update(profile_diagnostics)
        period_diagnostics: dict[str, object] | None = None
        if _is_finance_profile(goal=goal, research_profile=research_profile):
            diagnostics.update(_finance_coverage_compatibility(profile_diagnostics))
            issuer_coverage = _finance_requested_issuer_coverage(goal=goal, evidence=evidence)
            diagnostics["finance_requested_issuer_coverage"] = issuer_coverage
            period_diagnostics = _finance_target_period_diagnostics(goal=goal, evidence=evidence)
            diagnostics["finance_target_period"] = period_diagnostics
            specialized_query_diagnostics = _finance_specialized_query_coverage(goal=goal, evidence=evidence)
            diagnostics["finance_specialized_query_coverage"] = specialized_query_diagnostics
            if sufficient and issuer_coverage["required"] and not issuer_coverage["satisfied"]:
                sufficient = False
                reason = "finance_requested_issuer_missing"
            if (
                sufficient
                and specialized_query_diagnostics["required"]
                and not specialized_query_diagnostics["satisfied"]
            ):
                sufficient = False
                reason = "finance_specialized_query_terms_missing"
        if sufficient and profile_diagnostics["profile_evidence_required"] and profile_diagnostics["missing_profile_facets"]:
            sufficient = False
            reason = (
                "finance_fundamental_facets_missing"
                if _is_finance_profile(goal=goal, research_profile=research_profile)
                else "profile_evidence_facets_missing"
            )
        if period_diagnostics is not None and period_diagnostics["required"] and not period_diagnostics["satisfied"]:
            sufficient = False
            reason = "finance_target_period_missing"

        resolved_profile = resolve_goal_research_profile(goal, research_profile)
        if resolved_profile is not None:
            if resolved_profile.profile_id == "academic_research":
                topic_diagnostics = _query_topic_coverage(goal.query, [item.text for item in evidence])
                diagnostics["query_topic_coverage"] = topic_diagnostics
                if sufficient and topic_diagnostics["topic_terms"] and not topic_diagnostics["satisfied"]:
                    sufficient = False
                    reason = "query_topic_terms_missing"
            assessments = [assess_evidence_source(item, profile=resolved_profile) for item in evidence]
            authority_summary = source_authority_summary(assessments)
            diagnostics["research_profile"] = resolved_profile.profile_id
            diagnostics["source_authority"] = authority_summary
            authority_requirement = _source_authority_requirement(goal)
            diagnostics["source_authority_requirement"] = authority_requirement
            diagnostics["source_quality"] = source_quality_summary(
                assessments,
                authority_requirement=authority_requirement,
            )
            if not evidence:
                sufficient = False
                reason = "insufficient_evidence"
            elif resolved_profile.citations_required and not citations:
                sufficient = False
                reason = "citations_required_by_research_profile"
            elif not _authority_satisfies(assessments, authority_requirement):
                sufficient = False
                reason = (
                    "no_primary_source_for_research_profile"
                    if authority_requirement == "primary"
                    else "no_required_authority_source_for_research_profile"
                )

        return EvidenceEvaluationDecision(
            decision_id=f"eval-{goal.goal_id}",
            goal_id=goal.goal_id,
            status="sufficient" if sufficient else "insufficient_evidence",
            sufficient=sufficient,
            reason=reason,
            evidence_count=len(evidence),
            citation_count=len(citations),
            diagnostics=diagnostics,
        )


def assess_finance_fundamental_coverage(
    *,
    goal: SearchGoal,
    evidence: list[EvidenceItem],
    research_profile: ResearchProfile | None = None,
) -> dict[str, object]:
    return _finance_coverage_compatibility(
        assess_profile_evidence_coverage(
            goal=goal,
            evidence=evidence,
            research_profile=research_profile,
        )
    )


def finance_fundamental_facets(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> list[str]:
    if not _is_finance_fundamental_goal(goal=goal, research_profile=research_profile):
        return []
    return profile_evidence_facets(goal=goal, research_profile=research_profile)


def is_discovery_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    return profile_is_discovery_goal(goal=goal, research_profile=research_profile)


def _finance_coverage_compatibility(profile_diagnostics: dict[str, object]) -> dict[str, object]:
    missing = _finance_missing_names(_string_list(profile_diagnostics.get("missing_profile_facets")))
    return {
        "finance_fundamental_required": bool(profile_diagnostics.get("profile_evidence_required")),
        "finance_fundamental_facets": _string_list(profile_diagnostics.get("profile_evidence_facets")),
        "covered_finance_facets": _string_list(profile_diagnostics.get("covered_profile_facets")),
        "missing_finance_facets": missing,
        "finance_numeric_fact_required": bool(profile_diagnostics.get("profile_numeric_fact_required")),
        "finance_numeric_fact_present": bool(profile_diagnostics.get("profile_numeric_fact_present")),
        "finance_facet_coverage": profile_diagnostics.get("profile_facet_coverage", 1.0),
        "finance_facet_matches": profile_diagnostics.get("profile_facet_matches", {}),
    }


def _add_finance_compatibility_fields(result: dict[str, object]) -> None:
    if result.get("reason") == "discovery_metadata_not_final_evidence":
        result["reason"] = "finance_discovery_metadata_not_final_evidence"
    elif result.get("reason") == "qualified_profile_evidence":
        result["reason"] = "qualified_finance_evidence"
    elif result.get("reason") == "missing_profile_fact_in_span":
        result["reason"] = "missing_finance_fact_in_span"
    elif result.get("reason") == "no_required_profile_facets":
        result["reason"] = "not_finance_fundamental_goal"
    result["covered_finance_facets"] = _string_list(result.get("covered_profile_facets"))
    result["missing_finance_facets"] = _finance_missing_names(_string_list(result.get("missing_profile_facets")))
    result["finance_numeric_fact_required"] = bool(result.get("profile_numeric_fact_required"))
    result["finance_numeric_fact_present"] = bool(result.get("profile_numeric_fact_present"))


def _finance_missing_names(values: list[str]) -> list[str]:
    return ["numeric_financial_fact" if value == "numeric_profile_fact" else value for value in values]


def _finance_companyfacts_entity_mismatch(*, goal: SearchGoal, evidence: EvidenceItem) -> dict[str, object] | None:
    text = str(evidence.text or "")
    if "SEC companyfacts" not in text and "entityName=" not in text:
        return None
    entity = _companyfacts_entity_name(text)
    if not entity:
        return None
    requested = _requested_issuer_entries(goal)
    if requested:
        if _companyfacts_entity_matches_any_issuer(entity, _companyfacts_cik(text), requested):
            return None
        return {
            "target_entity_required": True,
            "target_entity_satisfied": False,
            "expected_companies": [str(item.get("company") or item.get("ticker") or "") for item in requested],
            "expected_ciks": [str(item.get("sec_cik") or "") for item in requested if item.get("sec_cik")],
            "observed_companyfacts_entity": entity,
            "observed_companyfacts_cik": _companyfacts_cik(text),
            "reason": "companyfacts_entity_not_requested_issuer",
        }
    identity = resolve_issuer_identity(goal.query, goal.metadata)
    target = identity.company or _metadata_company(goal.metadata)
    if not target:
        return None
    entity_key = _entity_key(entity)
    target_key = _entity_key(target)
    if not entity_key or not target_key:
        return None
    entity_tokens = set(entity_key.split())
    target_tokens = set(target_key.split())
    if target_tokens and target_tokens.issubset(entity_tokens) and not _has_unrequested_subsidiary_terms(
        entity_tokens,
        target_tokens=target_tokens,
    ):
        return None
    if entity_tokens and entity_tokens.issubset(target_tokens):
        return None
    if target_key in entity_key and not _has_unrequested_subsidiary_terms(entity_tokens, target_tokens=target_tokens):
        return None
    return {
        "target_entity_required": True,
        "target_entity_satisfied": False,
        "expected_company": target,
        "observed_companyfacts_entity": entity,
        "identity_sources": list(identity.sources),
        "reason": "companyfacts_entity_not_target_company",
    }


def _companyfacts_entity_name(text: str) -> str | None:
    match = re.search(r"\bentityName=([^=\n\r]{1,160}?)(?:\s+cik=|\s+source=|\s+fy=|\s+taxonomy=|\s+concept=|$)", text)
    if not match:
        return None
    return " ".join(match.group(1).replace(",", " ").split())


def _companyfacts_cik(text: str) -> str | None:
    match = re.search(r"\bcik=0*([0-9]{1,10})\b", str(text or ""), flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).zfill(10)


def _finance_evidence_matches_requested_issuer(*, goal: SearchGoal, evidence: EvidenceItem) -> bool:
    requested = _requested_issuer_entries(goal)
    if not requested:
        return False
    text = " ".join(str(value or "") for value in (evidence.title, evidence.uri, evidence.text))
    entity = _companyfacts_entity_name(text)
    cik = _companyfacts_cik(text)
    if entity and _companyfacts_entity_matches_any_issuer(entity, cik, requested):
        return True
    normalized = _entity_key(text)
    for issuer in requested:
        if _issuer_matches_text(issuer, normalized):
            return True
    return False


def _requested_issuer_entries(goal: SearchGoal) -> list[dict[str, object]]:
    text = _goal_target_text(goal)
    metadata = goal.metadata or {}
    registered = builtin_issuers_for_text(text)
    explicit = _issuer_payload_from_metadata(metadata)
    if explicit:
        registered.insert(0, explicit)
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for issuer in registered:
        key = str(issuer.get("sec_cik") or issuer.get("ticker") or issuer.get("company") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(dict(issuer))
    return result


def _goal_target_text(goal: SearchGoal) -> str:
    parts = [str(goal.query or "")]
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    for key in ("root_goal", "task_goal", "original_goal", "user_goal", "goal"):
        value = metadata.get(key)
        if isinstance(value, str):
            parts.append(value)
    research_mission = metadata.get("research_mission")
    if isinstance(research_mission, dict):
        for key in ("root_goal", "goal", "task_goal"):
            value = research_mission.get(key)
            if isinstance(value, str):
                parts.append(value)
    answer_profile = metadata.get("answer_profile")
    if isinstance(answer_profile, dict):
        for key in ("root_goal", "task_goal"):
            value = answer_profile.get(key)
            if isinstance(value, str):
                parts.append(value)
    return " ".join(item for item in parts if item.strip())


def _issuer_payload_from_metadata(metadata: dict[str, object]) -> dict[str, object]:
    company = _metadata_company(metadata)
    ticker = _metadata_string(metadata, "ticker", "sec_ticker")
    cik = _metadata_string(metadata, "sec_cik", "cik", "company_cik")
    if not any((company, ticker, cik)):
        return {}
    payload: dict[str, object] = {}
    if company:
        payload["company"] = company
    if ticker:
        payload["ticker"] = ticker.upper()
    normalized_cik = _normalize_cik(cik)
    if normalized_cik:
        payload["sec_cik"] = normalized_cik
    return payload


def _metadata_string(metadata: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _metadata_string(nested, *keys)
    return None


def _companyfacts_entity_matches_any_issuer(
    entity: str,
    cik: str | None,
    requested: list[dict[str, object]],
) -> bool:
    normalized_cik = _normalize_cik(cik)
    entity_key = _entity_key(entity)
    for issuer in requested:
        issuer_cik = _normalize_cik(issuer.get("sec_cik"))
        if normalized_cik and issuer_cik and normalized_cik == issuer_cik:
            return True
        if _companyfacts_entity_matches_issuer(entity_key, issuer):
            return True
    return False


def _companyfacts_entity_matches_issuer(entity_key: str, issuer: dict[str, object]) -> bool:
    entity_tokens = set(entity_key.split())
    for candidate in _issuer_name_candidates(issuer):
        candidate_key = _entity_key(candidate)
        if not candidate_key:
            continue
        candidate_tokens = set(candidate_key.split())
        if candidate_tokens and candidate_tokens.issubset(entity_tokens):
            if _has_unrequested_subsidiary_terms(entity_tokens, target_tokens=candidate_tokens):
                continue
            return True
        if entity_tokens and entity_tokens.issubset(candidate_tokens):
            return True
        if candidate_key in entity_key and not _has_unrequested_subsidiary_terms(
            entity_tokens,
            target_tokens=candidate_tokens,
        ):
            return True
    return False


def _issuer_matches_text(issuer: dict[str, object], normalized_text: str) -> bool:
    for candidate in _issuer_name_candidates(issuer, include_ticker=True):
        candidate_key = _entity_key(candidate)
        if not candidate_key:
            continue
        candidate_tokens = set(candidate_key.split())
        text_tokens = set(normalized_text.split())
        if candidate_key in normalized_text:
            return True
        if candidate_tokens and candidate_tokens.issubset(text_tokens):
            return True
    return False


def _issuer_name_candidates(issuer: dict[str, object], *, include_ticker: bool = False) -> list[str]:
    candidates: list[str] = []
    keys = ("company", "matched_alias", "ticker") if include_ticker else ("company", "matched_alias")
    for key in keys:
        value = issuer.get(key)
        if isinstance(value, str):
            candidates.append(value)
    aliases = issuer.get("aliases")
    if isinstance(aliases, list):
        candidates.extend(value for value in aliases if isinstance(value, str))
    return candidates


def _finance_requested_issuer_coverage(*, goal: SearchGoal, evidence: list[EvidenceItem]) -> dict[str, object]:
    requested = _requested_issuer_entries(goal)
    if len(requested) < 2:
        return {
            "required": False,
            "satisfied": True,
            "requested": [
                _issuer_label(issuer)
                for issuer in requested
            ],
            "covered": [],
            "missing": [],
        }
    covered: list[str] = []
    refs: dict[str, list[str]] = {}
    for issuer in requested:
        label = _issuer_label(issuer)
        matching_refs = [
            item.evidence_id
            for item in evidence
            if _finance_evidence_matches_issuer(evidence=item, issuer=issuer)
        ]
        if matching_refs:
            covered.append(label)
            refs[label] = matching_refs[:8]
    covered_set = set(covered)
    requested_labels = [_issuer_label(issuer) for issuer in requested]
    missing = [label for label in requested_labels if label not in covered_set]
    return {
        "required": True,
        "satisfied": not missing,
        "requested": requested_labels,
        "covered": covered,
        "missing": missing,
        "evidence_refs": refs,
    }


def _finance_evidence_matches_issuer(*, evidence: EvidenceItem, issuer: dict[str, object]) -> bool:
    text = " ".join(str(value or "") for value in (evidence.title, evidence.uri, evidence.text))
    entity = _companyfacts_entity_name(text)
    cik = _companyfacts_cik(text)
    if entity and _companyfacts_entity_matches_any_issuer(entity, cik, [issuer]):
        return True
    return _issuer_matches_text(issuer, _entity_key(text))


def _issuer_label(issuer: dict[str, object]) -> str:
    return str(issuer.get("ticker") or issuer.get("company") or issuer.get("sec_cik") or "issuer")


def _normalize_cik(value: object) -> str | None:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return None
    return digits[-10:].zfill(10)


def _metadata_company(metadata: dict[str, object]) -> str | None:
    for key in ("company", "company_name", "issuer", "issuer_name"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _metadata_company(nested)
    return None


def _entity_key(value: str) -> str:
    tokens = []
    for raw in re.findall(r"[a-z0-9]+", str(value or "").lower()):
        if raw in _ENTITY_SUFFIX_TOKENS:
            continue
        tokens.append(raw)
    return " ".join(tokens)


def _has_unrequested_subsidiary_terms(entity_tokens: set[str], *, target_tokens: set[str]) -> bool:
    return bool((entity_tokens - target_tokens) & _SUBSIDIARY_ENTITY_TOKENS)


def _finance_target_period_diagnostics(*, goal: SearchGoal, evidence: list[EvidenceItem]) -> dict[str, object]:
    years = _requested_finance_period_years(goal.query)
    if not years:
        return {
            "required": False,
            "satisfied": True,
            "requested_years": [],
            "covered_years": [],
            "missing_years": [],
        }
    covered: list[str] = []
    evidence_refs: dict[str, list[str]] = {}
    for year in years:
        refs = [
            item.evidence_id
            for item in evidence
            if _evidence_covers_finance_period(item.text, year)
        ]
        if refs:
            covered.append(year)
            evidence_refs[year] = refs[:8]
    covered_set = set(covered)
    missing = [year for year in years if year not in covered_set]
    return {
        "required": True,
        "satisfied": not missing,
        "requested_years": years,
        "covered_years": covered,
        "missing_years": missing,
        "evidence_refs": evidence_refs,
    }


def _finance_specialized_query_coverage(*, goal: SearchGoal, evidence: list[EvidenceItem]) -> dict[str, object]:
    terms = _finance_specialized_query_terms(goal)
    if not terms:
        return {
            "required": False,
            "satisfied": True,
            "terms": [],
            "matched_terms": [],
            "missing_terms": [],
            "required_match_count": 0,
        }
    corpus = "\n".join(f"{item.title} {item.uri} {item.text}" for item in evidence).lower()
    matched = [term for term in terms if term in corpus or _finance_specialized_term_matches(term, corpus)]
    required_count = 1 if len(terms) == 1 else min(2, len(terms))
    transaction_required_terms = _finance_transaction_required_terms(goal)
    transaction_matched = [
        term for term in transaction_required_terms if term in corpus or _finance_specialized_term_matches(term, corpus)
    ]
    addback_required_terms = _finance_addback_trend_required_terms(goal)
    addback_matched = [term for term in addback_required_terms if term in corpus]
    missing = [term for term in terms if term not in set(matched)]
    satisfied = len(matched) >= required_count
    if transaction_required_terms and not transaction_matched:
        satisfied = False
    if addback_required_terms and not addback_matched:
        satisfied = False
    return {
        "required": True,
        "satisfied": satisfied,
        "terms": terms,
        "matched_terms": matched,
        "missing_terms": missing,
        "required_match_count": required_count,
        "transaction_required_terms": transaction_required_terms,
        "transaction_matched_terms": transaction_matched,
        "addback_required_terms": addback_required_terms,
        "addback_matched_terms": addback_matched,
    }


def _finance_specialized_term_matches(term: str, corpus: str) -> bool:
    normalized = str(term or "").strip().lower()
    if not normalized:
        return False
    synonym_groups = {
        "transaction": ("transaction", "acquisition", "acquire", "acquires", "acquired", "merger"),
        "acquisition": ("acquisition", "acquire", "acquires", "acquired", "transaction", "merger"),
        "deal": ("deal", "transaction", "acquisition", "merger"),
        "deal disclosure": ("deal disclosure", "press release", "form 8-k", "8-k", "transaction", "acquisition"),
        "deal disclosures": ("deal disclosures", "press release", "form 8-k", "8-k", "transaction", "acquisition"),
        "transaction value": ("transaction value", "enterprise value", "equity value"),
        "ev": ("enterprise value", "transaction value", "equity value"),
    }
    return any(marker in corpus for marker in synonym_groups.get(normalized, ()))


def _finance_specialized_query_terms(goal: SearchGoal) -> list[str]:
    query = _finance_specialized_query_text(goal)
    if not _finance_query_has_specialized_scope(query):
        return []
    stopwords = set(_FINANCE_SPECIALIZED_QUERY_STOPWORDS)
    identity = resolve_issuer_identity(goal.query, goal.metadata)
    for value in (identity.company, identity.ticker, identity.issuer):
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower()):
            stopwords.add(token)
    for year in _requested_finance_period_years(goal.query):
        stopwords.add(year)
    terms: list[str] = []
    seen: set[str] = set()
    for phrase in _SPECIALIZED_QUERY_PHRASES:
        if phrase in query and phrase not in seen:
            seen.add(phrase)
            terms.append(phrase)
    for token in re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", query):
        if token.isdigit() or token in stopwords:
            continue
        if len(token) < 4 and not re.search(r"[\u4e00-\u9fff]", token):
            continue
        if token in seen:
            continue
        seen.add(token)
        terms.append(token)
    return terms[:8]


def _finance_transaction_required_terms(goal: SearchGoal) -> list[str]:
    query = _finance_specialized_query_text(goal)
    if not any(marker in query for marker in ("transaction", "acquisition", "deal disclosure", "merger agreement", "8-k", "ev / revenue", "ev revenue")):
        return []
    return ["transaction", "acquisition", "acquire", "acquired", "deal", "merger", "8-k", "form 8-k", "consideration"]


def _finance_complementary_fact_source(*, goal: SearchGoal, evidence: EvidenceItem) -> bool:
    if not _finance_transaction_required_terms(goal):
        return False
    source_kind = evidence_source_kind(evidence)
    if source_kind not in {"sec_companyfacts_json", "sec_companyconcept_json"}:
        return False
    text = str(evidence.text or "").lower()
    if "sec_xbrl_companyfacts" not in text and "companyfacts" not in text:
        return False
    return any(
        marker in text
        for marker in (
            "metric=revenue",
            "metric=net sales",
            "metric=net income",
            "metric=cash",
            "metric=cash and cash equivalents",
            "metric=debt",
            "metric=assets",
            "metric=shares outstanding",
            "concept=revenue",
            "concept=revenues",
            "concept=entitycommonstocksharesoutstanding",
            "entity common stock, shares outstanding",
            "revenues",
            "net sales",
        )
    )


def _finance_target_bound_structured_fact_source(*, goal: SearchGoal, evidence: EvidenceItem) -> bool:
    source_kind = evidence_source_kind(evidence)
    uri = str(evidence.uri or "").lower()
    if (
        source_kind not in {"sec_companyfacts_json", "sec_companyconcept_json"}
        and "data.sec.gov/api/xbrl/companyfacts/" not in uri
        and "data.sec.gov/api/xbrl/companyconcept/" not in uri
    ):
        return False
    text = str(evidence.text or "").lower()
    if "sec companyfacts official financial statement" not in text:
        return False
    if not re.search(r"\b(?:value|val)=-?\d+(?:,\d{3})*(?:\.\d+)?\b", text):
        return False
    diagnostics = evidence.diagnostics if isinstance(evidence.diagnostics, dict) else {}
    span_metadata = diagnostics.get("span_metadata")
    if isinstance(span_metadata, dict):
        target_period = str(span_metadata.get("target_period") or "").strip()
        target_line_item = str(span_metadata.get("target_line_item") or "").strip()
        if target_period and target_line_item:
            return True
    target_binding = diagnostics.get("target_document_binding")
    if not isinstance(target_binding, dict):
        metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
        target_binding = metadata.get("target_document_binding")
    if not isinstance(target_binding, dict):
        return False
    doc_period = str(target_binding.get("doc_period") or "").strip()
    return bool(doc_period and _evidence_covers_finance_period(evidence.text, doc_period))


def _finance_source_grounded_target_document_candidate(*, goal: SearchGoal, evidence: EvidenceItem) -> bool:
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    if not _source_grounded_research_goal(metadata):
        return False
    uri = str(evidence.uri or "").strip()
    if not uri:
        return False
    target_urls = _source_grounded_target_document_urls(metadata)
    if not target_urls:
        return False
    if not _uri_matches_any_target_document(uri, target_urls):
        return False
    text = f"{evidence.title} {evidence.text}".lower()
    return any(
        marker in text
        for marker in (
            "10-k",
            "annual report",
            "operating",
            "margin",
            "income",
            "sales",
            "cost of sales",
            "s&a",
            "sg&a",
            "md&a",
            "management's discussion",
            "results of operations",
        )
    )


def _source_grounded_research_goal(metadata: dict[str, object]) -> bool:
    if metadata.get("benchmark_doc_retrieval") is True:
        return True
    return str(metadata.get("workflow_type") or metadata.get("research_task_kind") or "").strip().lower() in {
        "source_grounded_research",
        "filing_document_qa",
    }


def _source_grounded_target_document_urls(metadata: dict[str, object]) -> list[str]:
    raw: list[object] = []
    for key in ("source_url", "doc_link"):
        value = metadata.get(key)
        if isinstance(value, str):
            raw.append(value)
    for key in ("source_urls", "preferred_source_urls"):
        value = metadata.get(key)
        if isinstance(value, list):
            raw.extend(value)
    binding = metadata.get("target_document_binding")
    if isinstance(binding, dict):
        value = binding.get("doc_link")
        if isinstance(value, str):
            raw.append(value)
    urls: list[str] = []
    seen: set[str] = set()
    for item in raw:
        url = str(item or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _uri_matches_any_target_document(uri: str, target_urls: list[str]) -> bool:
    for target_url in target_urls:
        if _same_url_or_prefix(uri, target_url) or _same_url_or_prefix(target_url, uri):
            return True
        accession = _accession_number(uri)
        target_accession = _accession_number(target_url)
        if accession and target_accession and accession == target_accession:
            return True
    return False


def _same_url_or_prefix(left: str, right: str) -> bool:
    left_norm = str(left or "").strip().rstrip("/")
    right_norm = str(right or "").strip().rstrip("/")
    return bool(left_norm and right_norm and (left_norm == right_norm or left_norm.startswith(f"{right_norm}/")))


def _accession_number(value: str) -> str:
    match = re.search(r"\b\d{10}-\d{2}-\d{6}\b|\b\d{18}\b", str(value or ""))
    return match.group(0).replace("-", "") if match else ""


def _finance_addback_trend_required_terms(goal: SearchGoal) -> list[str]:
    query = _finance_specialized_query_text(goal)
    if not (
        any(marker in query for marker in ("add-back", "addback", "add back", "add-backs", "add backs"))
        and any(marker in query for marker in ("trend", "bridge", "reconciliation", "non-gaap", "non gaap", "adjusted ebitda"))
    ):
        return []
    return [
        "add-back",
        "add back",
        "addback",
        "add-backs",
        "add backs",
        "reconciliation",
        "non-gaap",
        "non gaap",
        "adjusted ebitda reconciliation",
    ]


def _finance_specialized_query_text(goal: SearchGoal) -> str:
    root_goal = ""
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    for key in ("root_goal", "user_goal", "original_goal"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            root_goal = f"{root_goal} {value.strip()}"
    mission = metadata.get("research_mission")
    if isinstance(mission, dict) and isinstance(mission.get("root_goal"), str):
        root_goal = f"{root_goal} {mission['root_goal']}"
    return f"{goal.query or ''} {root_goal}".lower()


def _finance_query_has_specialized_scope(query: str) -> bool:
    return any(marker in query for marker in _SPECIALIZED_QUERY_SCOPE_MARKERS)


def _requested_finance_period_years(query: str) -> list[str]:
    text = str(query or "").lower()
    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    if not years:
        return []
    if any(
        marker in text
        for marker in (
            "fiscal",
            "fy",
            "financial year",
            "year-end",
            "year end",
            "annual",
            "10-k",
            "10k",
            "财年",
            "年度",
            "年报",
        )
    ):
        return _ordered_unique(years)
    if _is_finance_metric_query(text):
        return _ordered_unique(years)
    return []


def _evidence_covers_finance_period(text: str, year: str) -> bool:
    normalized = str(text or "").lower()
    escaped = re.escape(year)
    structured_patterns = (
        rf"\bfy\s*=?\s*{escaped}\b",
        rf"\bend\s*=\s*{escaped}-\d{{2}}-\d{{2}}\b",
        rf"\breportdate\s*=\s*{escaped}-\d{{2}}-\d{{2}}\b",
        rf"\breport\s+date\s*=\s*{escaped}-\d{{2}}-\d{{2}}\b",
        rf"\bframe\s*=\s*cy{escaped}(?!q)\b",
    )
    if any(re.search(pattern, normalized) for pattern in structured_patterns):
        return True
    if any(marker in normalized for marker in ("fy=", "end=", "reportdate=", "report date=", "frame=", "filed=")):
        return False
    period_patterns = (
        rf"\bfiscal\s+year\s+{escaped}\b",
        rf"\bfinancial\s+year\s+{escaped}\b",
        rf"\b{escaped}\s+fiscal\s+year\b",
        rf"\b{escaped}\s+(?:form\s+)?10-k\b",
        rf"\b{escaped}\s+annual\s+report\b",
        rf"\bannual\s+report\s+{escaped}\b",
        rf"\bfor\s+(?:the\s+)?(?:year|fiscal\s+year)\s+(?:ended\s+)?{escaped}\b",
        rf"\b(?:revenue|revenues|net income|eps|earnings|assets|cash flow)[^.\n]{{0,120}}\b{escaped}\b",
        rf"\b{escaped}\b[^.\n]{{0,120}}\b(?:revenue|revenues|net income|eps|earnings|assets|cash flow)\b",
    )
    return any(re.search(pattern, normalized) for pattern in period_patterns)


def _is_finance_metric_query(text: str) -> bool:
    return any(
        marker in text
        for marker in (
            "revenue",
            "revenues",
            "net income",
            "eps",
            "earnings",
            "assets",
            "liabilities",
            "cash flow",
            "market cap",
            "pe ratio",
            "total revenues",
            "收入",
            "营收",
            "净利润",
            "每股收益",
            "资产",
            "现金流",
        )
    )


def _is_finance_fundamental_goal(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    if not _is_finance_profile(goal=goal, research_profile=research_profile):
        return False
    metadata = goal.metadata if isinstance(goal.metadata, dict) else {}
    task_kind = str(metadata.get("research_task_kind") or metadata.get("task_kind") or "").strip().lower()
    if task_kind in set(FINANCE_FUNDAMENTAL_TASK_KINDS):
        return True
    if task_kind in {"market_data", "market_news", "macro_data", "competitive_landscape"}:
        return False
    return bool(profile_evidence_facets(goal=goal, research_profile=research_profile))


def _is_sec_discovery_query(query: str) -> bool:
    goal = SearchGoal(
        goal_id="compat-sec-discovery",
        query=query,
        metadata={"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID},
    )
    return profile_is_discovery_goal(goal=goal)


def _is_finance_profile(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    resolved = resolve_goal_research_profile(goal, research_profile)
    return resolved is not None and resolved.profile_id == FINANCE_FUNDAMENTALS_PROFILE_ID


def _is_academic_profile(*, goal: SearchGoal, research_profile: ResearchProfile | None = None) -> bool:
    resolved = resolve_goal_research_profile(goal, research_profile)
    return resolved is not None and resolved.profile_id == "academic_research"


def _evidence_source_kind(evidence: EvidenceItem) -> str:
    return evidence_source_kind(evidence)


def _source_authority_requirement(goal: SearchGoal) -> str:
    value = goal.metadata.get("source_authority_requirement")
    if not isinstance(value, str):
        value = goal.metadata.get("authority_requirement")
    normalized = str(value or "primary").strip().lower()
    if normalized in {"secondary_or_better", "secondary_allowed", "secondary"}:
        return "secondary_or_better"
    if normalized in {"any", "any_citable"}:
        return "any_citable"
    return "primary"


def _weak_source_for_required_profile(
    *,
    goal: SearchGoal,
    evidence: EvidenceItem,
    research_profile: ResearchProfile | None,
) -> dict[str, object] | None:
    profile = resolve_goal_research_profile(goal, research_profile)
    if profile is None:
        return None
    assessment = evidence.diagnostics.get("source_assessment")
    if not isinstance(assessment, dict):
        return None
    authority_level = str(assessment.get("authority_level") or "")
    if authority_level != "weak":
        return None
    return {
        "profile_id": profile.profile_id,
        "authority_level": authority_level,
        "source_family": str(assessment.get("source_family") or ""),
        "authority_score": assessment.get("authority_score"),
        "required_authority": _source_authority_requirement(goal),
    }


def _template_placeholder_diagnostics(text: str) -> dict[str, object]:
    matches = [match.group(0) for match in TEMPLATE_PLACEHOLDER_RE.finditer(text)]
    if not matches:
        return {"template_placeholder_evidence": False, "placeholder_count": 0}
    unique = []
    seen = set()
    for match in matches:
        key = match.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(match[:80])
    normalized = " ".join(text.split())
    density = len(matches) / max(1, len(normalized.split()))
    template_like = len(matches) >= 2 or density >= 0.08
    return {
        "template_placeholder_evidence": template_like,
        "placeholder_count": len(matches),
        "placeholder_density": round(density, 4),
        "sample_placeholders": unique[:6],
    }


def _query_topic_coverage(query: str, evidence_texts: list[str]) -> dict[str, object]:
    terms = _query_topic_terms(query)
    corpus = "\n".join(evidence_texts).lower()
    matched = [term for term in terms if term in corpus]
    required_count = len(terms) if len(terms) <= 1 else max(2, min(len(terms), (len(terms) + 1) // 2))
    return {
        "topic_terms": terms,
        "matched_topic_terms": matched,
        "missing_topic_terms": [term for term in terms if term not in set(matched)],
        "required_match_count": required_count,
        "satisfied": len(matched) >= required_count,
    }


def _query_topic_terms(query: str) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"[A-Za-z0-9]+|[\u4e00-\u9fff]{2,}", query.lower()):
        term = match.group(0)
        if term.isdigit() or len(term) < 2:
            continue
        if term in _QUERY_TOPIC_STOPWORDS:
            continue
        if len(term) < 4 and not re.search(r"[\u4e00-\u9fff]", term):
            continue
        if term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms[:8]


def _authority_satisfies(assessments: object, requirement: str) -> bool:
    items = list(assessments) if isinstance(assessments, list) else []
    if requirement == "any_citable":
        return bool(items)
    if requirement == "secondary_or_better":
        return any(item.usable_as_primary or item.authority_level == "secondary" for item in items)
    return any(item.usable_as_primary for item in items)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in (str(raw).strip() for raw in value if isinstance(raw, str)) if item]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


_QUERY_TOPIC_STOPWORDS = {
    "about",
    "academic",
    "advance",
    "advances",
    "analysis",
    "article",
    "complete",
    "comprehensive",
    "deep",
    "detailed",
    "frontier",
    "frontiers",
    "information",
    "investigate",
    "journal",
    "latest",
    "literature",
    "open",
    "paper",
    "papers",
    "preprint",
    "problem",
    "problems",
    "recent",
    "report",
    "research",
    "review",
    "scholarly",
    "search",
    "state",
    "study",
    "survey",
    "前沿",
    "最新",
    "查询",
    "检索",
    "搜索",
    "调查",
    "研究",
    "论文",
    "报告",
    "文献",
    "综述",
}

_ENTITY_SUFFIX_TOKENS = {
    "and",
    "co",
    "company",
    "corp",
    "corporation",
    "de",
    "inc",
    "incorporated",
    "limited",
    "llc",
    "ltd",
    "plc",
    "the",
}

_SUBSIDIARY_ENTITY_TOKENS = {
    "bank",
    "capital",
    "credit",
    "finance",
    "financing",
    "fund",
    "funding",
    "holdings",
    "insurance",
    "lease",
    "leasing",
    "mortgage",
    "receivables",
    "securities",
    "statutory",
    "trust",
}

_SPECIALIZED_QUERY_SCOPE_MARKERS = {
    "add-back",
    "addback",
    "adjusted ebitda",
    "artificial intelligence",
    "bridge",
    "business unit",
    "capital expenditure",
    "cloud",
    "deal disclosure",
    "deal disclosures",
    "family of apps",
    "infrastructure",
    "investment",
    "merger agreement",
    "multiple",
    "non gaap",
    "non-gaap",
    "operating segment",
    "reportable segment",
    "reconciliation",
    "segment",
    "segment reporting",
    "transaction",
    "transaction multiple",
    "transaction value",
    "分部",
    "板块",
    "业务线",
    "云",
    "人工智能",
    "基础设施",
}

_SPECIALIZED_QUERY_PHRASES = (
    "adjusted ebitda",
    "artificial intelligence",
    "business unit",
    "capital expenditure",
    "deal disclosure",
    "deal disclosures",
    "family of apps",
    "merger agreement",
    "non gaap",
    "non-gaap",
    "operating segment",
    "reportable segment",
    "reconciliation",
    "segment reporting",
    "transaction",
    "transaction multiple",
    "transaction value",
)

_FINANCE_SPECIALIZED_QUERY_STOPWORDS = {
    "and",
    "annual",
    "apps",
    "company",
    "corp",
    "corporation",
    "customer",
    "debt",
    "equity",
    "fiscal",
    "from",
    "income",
    "investment",
    "inc",
    "incorporated",
    "net",
    "public",
    "ratio",
    "revenue",
    "revenues",
    "sales",
    "segment",
    "stated",
    "total",
    "what",
    "with",
    "year",
    "year-end",
}
