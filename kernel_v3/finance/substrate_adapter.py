from __future__ import annotations

import hashlib
import re

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace, NumericVerification
from kernel_v3.finance.formula_planner import FinanceFormulaPlan
from kernel_v3.substrate import (
    Claim,
    EvidencePolicy,
    SlotFill,
    SlotFrame,
    SlotSpec,
    TransformPlan,
    VerificationGateResult,
)


def finance_facts_to_claims(facts: list[FinanceFact]) -> list[Claim]:
    claims: list[Claim] = []
    for fact in facts:
        claims.append(
            Claim(
                claim_id=f"claim-{fact.fact_id}",
                domain="finance",
                entity=fact.entity or fact.ticker,
                attribute=fact.metric,
                value=fact.value,
                unit=fact.unit,
                time_period=fact.period or (str(fact.fiscal_year) if fact.fiscal_year is not None else None),
                source_ref=fact.source_ref,
                evidence_ref=fact.evidence_ref,
                citation_ref=fact.citation_ref,
                extraction_method=str(fact.metadata.get("source") or "finance_fact_ledger"),
                confidence=_confidence_from_fact(fact),
                metadata={
                    "finance_fact_id": fact.fact_id,
                    "ticker": fact.ticker,
                    "fiscal_year": fact.fiscal_year,
                    "scale": fact.scale,
                    "source_title": fact.metadata.get("source_title"),
                    "source_uri": fact.metadata.get("source_uri"),
                    "supported_metric": fact.metadata.get("supported_metric"),
                },
            )
        )
    return claims


def finance_evidence_policy_for_question(question: str, *, formula_name: str | None = None) -> EvidencePolicy:
    text = _normalized(question)
    required_terms: list[str] = []
    required_families = ["regulatory_filing", "structured_regulatory_data"]
    forbidden_families: list[str] = []
    authority = "primary"
    if _looks_like_reconciliation_task(text, formula_name=formula_name):
        required_terms.extend(["reconciliation", "non-gaap", "non gaap", "add-back", "add back", "addback"])
        forbidden_families.extend(["market_data_provider"])
    elif _looks_like_transaction_task(text, formula_name=formula_name):
        required_terms.extend(["transaction", "acquisition", "merger", "consideration", "8-k", "form 8-k"])
        required_families.append("company_ir")
    elif _looks_like_valuation_task(text, formula_name=formula_name):
        required_families.extend(["market_data_provider", "company_ir"])
    return EvidencePolicy(
        policy_id="evidence-policy-" + _short_hash(text, str(formula_name or "")),
        domain="finance",
        required_source_families=_ordered_unique(required_families),
        forbidden_source_families=_ordered_unique(forbidden_families),
        required_terms=_ordered_unique(required_terms),
        authority=authority,
        freshness="latest_available_when_market_data_required" if _looks_like_valuation_task(text, formula_name=formula_name) else None,
        diagnostics={"formula_name": formula_name, "source": "finance_substrate_adapter"},
    )


def finance_slot_frame(
    *,
    question: str,
    facts: list[FinanceFact],
    plan: FinanceFormulaPlan | None = None,
    formula_name: str | None = None,
    missing_slots: list[str] | None = None,
) -> SlotFrame:
    resolved_formula = str(formula_name or "")
    if not resolved_formula and plan is not None and plan.formula_name:
        resolved_formula = str(plan.formula_name or "")
    if not resolved_formula:
        resolved_formula = _infer_formula_name(question)
    task_type = _task_type_for_formula(resolved_formula, question)
    required = _slot_specs_for_formula(resolved_formula)
    claims = finance_facts_to_claims(facts)
    fills = _slot_fills(required, claims)
    if missing_slots is not None:
        missing = list(missing_slots)
    elif plan is not None and plan.missing_facts:
        missing = list(plan.missing_facts)
    else:
        missing = [spec.name for spec in required if spec.name not in {fill.slot_name for fill in fills}]
    return SlotFrame(
        frame_id="slot-frame-" + _short_hash(question, resolved_formula, ",".join(sorted(missing))),
        task_type=task_type,
        domain="finance",
        required_slots=required,
        optional_slots=_optional_slot_specs_for_formula(resolved_formula),
        filled_slots=fills,
        missing_slots=_ordered_unique([str(item) for item in missing if str(item)]),
        evidence_policy=finance_evidence_policy_for_question(question, formula_name=resolved_formula),
        diagnostics={
            "formula_name": resolved_formula or None,
            "claim_count": len(claims),
            "finance_fact_count": len(facts),
            "source": "finance_substrate_adapter",
        },
    )


def finance_formula_plan_to_transform_plan(plan: FinanceFormulaPlan, *, question: str = "") -> TransformPlan:
    status = "ready" if plan.status == "ready" else "missing_slots" if plan.status == "missing_facts" else "not_applicable"
    payload = dict(plan.payload) if isinstance(plan.payload, dict) else None
    return TransformPlan(
        plan_id="transform-plan-" + _short_hash(str(plan.formula_name or ""), ",".join(plan.input_fact_ids), str(payload or "")),
        domain="finance",
        operation="calculate",
        status=status,
        method=plan.formula_name,
        input_claim_ids=[f"claim-{fact_id}" for fact_id in plan.input_fact_ids],
        output_attribute=plan.formula_name,
        payload=payload,
        missing_slots=list(plan.missing_facts),
        diagnostics={**plan.diagnostics, "question_hash": _short_hash(question), "source": "finance_formula_planner"},
    )


def finance_verification_to_gate_result(
    verification: NumericVerification,
    *,
    policy: EvidencePolicy | None = None,
    formula_traces: list[FormulaTrace] | None = None,
) -> VerificationGateResult:
    traces = list(formula_traces or [])
    return VerificationGateResult(
        gate_id="verifier-gate-" + _short_hash(verification.status, str(len(verification.issues)), str(len(verification.matched_values))),
        domain="finance",
        status=verification.status,
        policy_id=policy.policy_id if policy is not None else None,
        issues=list(verification.issues),
        matched_claims=list(verification.matched_values),
        matched_transforms=[trace.to_dict() for trace in traces],
        missing_slots=_missing_slots_from_verification(verification),
        diagnostics={
            **verification.diagnostics,
            "source": "finance_numeric_verifier",
            "formula_trace_count": len(traces),
        },
    )


def _slot_specs_for_formula(formula_name: str) -> list[SlotSpec]:
    slots_by_formula: dict[str, list[str]] = {
        "cagr": ["beginning_value", "ending_value", "years"],
        "dio": ["inventory_begin", "inventory_end", "cogs", "fiscal_days"],
        "ev_revenue": ["equity_value_or_market_cap", "debt", "cash", "revenue"],
        "ev_ebitda": ["enterprise_value_or_market_cap", "debt", "cash", "ebitda_or_ebitda_components"],
        "bridge_subtotal": ["base_metric", "addback_components", "deduction_components", "adjusted_metric"],
        "margin": ["margin_numerator", "revenue_denominator"],
        "bps_difference": ["prior_rate_or_margin", "current_rate_or_margin"],
        "yoy_growth": ["prior_period_value", "current_period_value"],
    }
    names = slots_by_formula.get(str(formula_name or ""), [])
    return [
        SlotSpec(
            name=name,
            requirement="required",
            accepted_attributes=_accepted_attributes_for_slot(name),
            source_requirements=["finance_fact_ledger"],
        )
        for name in names
    ]


def _optional_slot_specs_for_formula(formula_name: str) -> list[SlotSpec]:
    if formula_name in {"ev_revenue", "ev_ebitda"}:
        return [SlotSpec(name="short_term_investments", requirement="optional", accepted_attributes=["short-term investments", "short term investments"])]
    return []


def _slot_fills(specs: list[SlotSpec], claims: list[Claim]) -> list[SlotFill]:
    fills: list[SlotFill] = []
    used_claim_ids: set[str] = set()
    for spec in specs:
        accepted = {item.lower() for item in spec.accepted_attributes}
        for claim in claims:
            if claim.claim_id in used_claim_ids:
                continue
            if str(claim.attribute or "").lower() not in accepted:
                continue
            fills.append(
                SlotFill(
                    slot_name=spec.name,
                    claim_id=claim.claim_id,
                    value=claim.value,
                    source_ref=claim.source_ref,
                    confidence=claim.confidence,
                    metadata={"attribute": claim.attribute},
                )
            )
            used_claim_ids.add(claim.claim_id)
            break
    return fills


def _accepted_attributes_for_slot(name: str) -> list[str]:
    mapping = {
        "beginning_value": ["revenue", "net sales", "net income", "ebitda"],
        "ending_value": ["revenue", "net sales", "net income", "ebitda"],
        "years": [],
        "inventory_begin": ["inventory", "inventories"],
        "inventory_end": ["inventory", "inventories"],
        "cogs": ["cogs", "cost of sales", "cost of revenue"],
        "fiscal_days": [],
        "equity_value_or_market_cap": ["equity value", "market cap", "market capitalization", "enterprise value", "transaction value"],
        "enterprise_value_or_market_cap": ["enterprise value", "market cap", "market capitalization", "transaction value"],
        "debt": ["debt", "long term debt", "short term debt"],
        "cash": ["cash and equivalents", "cash and cash equivalents"],
        "revenue": ["revenue", "net sales", "net revenues", "total revenues"],
        "ebitda_or_ebitda_components": ["adjusted ebitda", "ebitda", "net income", "interest expense", "tax", "depreciation and amortization"],
        "base_metric": ["net income", "operating income"],
        "addback_components": ["addback", "interest expense", "tax", "depreciation and amortization", "other expense"],
        "deduction_components": ["deduction", "other income", "general corporate expenses"],
        "adjusted_metric": ["adjusted ebitda"],
        "margin_numerator": ["net income", "operating income", "adjusted ebitda", "ebitda"],
        "revenue_denominator": ["revenue", "net sales", "net revenues", "total revenues"],
        "prior_rate_or_margin": ["margin", "rate", "yield"],
        "current_rate_or_margin": ["margin", "rate", "yield"],
        "prior_period_value": ["revenue", "net sales", "net income", "operating income", "ebitda"],
        "current_period_value": ["revenue", "net sales", "net income", "operating income", "ebitda"],
    }
    return mapping.get(name, [name])


def _task_type_for_formula(formula_name: str, question: str) -> str:
    if formula_name == "bridge_subtotal" or _looks_like_reconciliation_task(_normalized(question), formula_name=formula_name):
        return "reconcile"
    if formula_name in {"dio", "ev_revenue", "ev_ebitda", "cagr", "margin", "bps_difference", "yoy_growth"}:
        return "compare_compute" if _looks_like_compare(question) else "compute"
    return "lookup"


def _infer_formula_name(question: str) -> str:
    text = _normalized(question)
    compact = text.replace(" ", "")
    if "ev/ebitda" in compact:
        return "ev_ebitda"
    if "ev/revenue" in compact or "ev/rev" in compact:
        return "ev_revenue"
    if "dio" in text or "days inventory" in text:
        return "dio"
    if "cagr" in text:
        return "cagr"
    if "add-back" in text or "addback" in text or "bridge" in text or "reconciliation" in text:
        return "bridge_subtotal"
    if "basis point" in text or "bps" in text:
        return "bps_difference"
    if "margin" in text:
        return "margin"
    if "growth" in text or "yoy" in text:
        return "yoy_growth"
    return ""


def _looks_like_reconciliation_task(text: str, *, formula_name: str | None) -> bool:
    return str(formula_name or "") == "bridge_subtotal" or any(
        marker in text for marker in ("add-back", "add back", "addback", "reconciliation", "non-gaap", "non gaap", "bridge")
    )


def _looks_like_transaction_task(text: str, *, formula_name: str | None) -> bool:
    return str(formula_name or "") == "ev_revenue" and any(
        marker in text for marker in ("transaction", "acquisition", "merger", "deal", "consideration", "purchase price")
    )


def _looks_like_valuation_task(text: str, *, formula_name: str | None) -> bool:
    return str(formula_name or "") in {"ev_revenue", "ev_ebitda"} or any(
        marker in text for marker in ("ev/ebitda", "ev/revenue", "market cap", "enterprise value", "valuation")
    )


def _looks_like_compare(question: str) -> bool:
    text = _normalized(question)
    return any(marker in text for marker in ("compare", "versus", " vs ", " vs.", "对比", "比较"))


def _missing_slots_from_verification(verification: NumericVerification) -> list[str]:
    slots: list[str] = []
    for issue in verification.issues:
        code = str(issue.get("code") or "")
        if code == "missing_fact_ledger":
            slots.append("claim_ledger")
        elif code == "missing_formula_trace":
            slots.append("transform_trace")
        elif code == "unsupported_answer_number":
            slots.append("supported_numeric_claims")
        elif code.endswith("mismatch"):
            slots.append(code)
    return _ordered_unique(slots)


def _confidence_from_fact(fact: FinanceFact) -> float | None:
    if fact.citation_ref:
        return 0.9
    if fact.evidence_ref:
        return 0.75
    return None


def _normalized(value: str) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).lower()


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
