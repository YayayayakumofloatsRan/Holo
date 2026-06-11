from __future__ import annotations

import hashlib
import re

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact
from kernel_v3.finance.formula_planner import FinanceFormulaPlan, plan_finance_formula
from kernel_v3.finance.substrate_adapter import finance_formula_plan_to_transform_plan, finance_slot_frame
from kernel_v3.substrate import CompiledTaskProgram, EvidenceSpec, TaskSpec, TransformSpec


def compile_finance_task_program(
    *,
    question: str,
    facts: list[FinanceFact],
    target_binding: JsonObject | None = None,
    plan: FinanceFormulaPlan | None = None,
) -> CompiledTaskProgram:
    """Compile a finance question into an auditable evidence/computation program.

    This is not an answer table. It projects the current question, target
    document binding, fact ledger, and formula intent into generic task/evidence
    and transform specs so later retrieval/verifier/synthesis steps can operate
    on explicit slots instead of a raw prompt.
    """

    binding = dict(target_binding) if isinstance(target_binding, dict) else {}
    formula_plan = plan or plan_finance_formula(question=question, facts=facts, existing_traces=[])
    frame = finance_slot_frame(
        question=question,
        facts=facts,
        plan=formula_plan,
        formula_name=formula_plan.formula_name,
        missing_slots=formula_plan.missing_facts if formula_plan.status == "missing_facts" else None,
    )
    transform_plan = finance_formula_plan_to_transform_plan(formula_plan, question=question)
    task_spec = TaskSpec(
        spec_id="task-spec-" + _short_hash(question, frame.task_type, str(formula_plan.formula_name or "")),
        domain="finance",
        task_type=frame.task_type,
        objective=question,
        target_entities=_target_entities(question=question, binding=binding),
        target_periods=_target_periods(question=question, binding=binding),
        success_criteria=_success_criteria(frame.task_type, formula_plan.formula_name, binding=binding),
        diagnostics={
            "source": "finance_task_compiler",
            "formula_name": formula_plan.formula_name,
            "formula_status": formula_plan.status,
            "fact_count": len(facts),
        },
    )
    evidence_specs = _evidence_specs(
        frame=frame,
        binding=binding,
        target_period=task_spec.target_periods[0] if task_spec.target_periods else None,
    )
    transform_specs = _transform_specs(formula_plan=formula_plan, frame_missing_slots=frame.missing_slots)
    return CompiledTaskProgram(
        program_id="task-program-" + _short_hash(task_spec.spec_id, ",".join(spec.slot_name for spec in evidence_specs)),
        domain="finance",
        task_spec=task_spec,
        evidence_specs=evidence_specs,
        transform_specs=transform_specs,
        slot_frame=frame,
        transform_plan=transform_plan,
        diagnostics={
            "source": "finance_task_compiler",
            "evidence_spec_count": len(evidence_specs),
            "transform_spec_count": len(transform_specs),
            "missing_slots": list(frame.missing_slots),
        },
    )


def _evidence_specs(*, frame, binding: JsonObject, target_period: str | None) -> list[EvidenceSpec]:
    specs: list[EvidenceSpec] = []
    policy = frame.evidence_policy
    source_families = list(policy.required_source_families) if policy is not None else []
    statement = _string(binding.get("required_statement"))
    line_item = _string(binding.get("required_line_item"))
    for slot in frame.required_slots:
        specs.append(
            EvidenceSpec(
                spec_id="evidence-spec-" + _short_hash(frame.frame_id, slot.name),
                slot_name=slot.name,
                domain="finance",
                accepted_attributes=list(slot.accepted_attributes),
                source_role=_source_role(binding=binding, source_families=source_families),
                required_source_families=source_families,
                target_period=target_period,
                statement=statement or _statement_for_slot(slot.name),
                line_item=line_item if _slot_matches_target_line(slot.name, line_item) else _line_item_for_slot(slot.name),
                required=slot.requirement == "required",
                diagnostics={"source": "finance_task_compiler"},
            )
        )
    if not specs and line_item:
        specs.append(
            EvidenceSpec(
                spec_id="evidence-spec-" + _short_hash("target-binding", line_item, target_period or ""),
                slot_name=_slot_name_for_line_item(line_item),
                domain="finance",
                accepted_attributes=[line_item],
                source_role=_source_role(binding=binding, source_families=source_families),
                required_source_families=source_families,
                target_period=target_period,
                statement=statement,
                line_item=line_item,
                required=True,
                diagnostics={"source": "finance_task_compiler", "from_target_document_binding": True},
            )
        )
    return specs


def _transform_specs(*, formula_plan: FinanceFormulaPlan, frame_missing_slots: list[str]) -> list[TransformSpec]:
    name = str(formula_plan.formula_name or "")
    if not name:
        return []
    if name == "capital_intensity":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "capex_revenue"),
                domain="finance",
                name="capital_intensity_capex_revenue",
                required_slots=["capital_expenditures", "revenue"],
                expression="capital_expenditures / revenue",
                output_unit="percent",
                output_attribute="capex_to_revenue",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            ),
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "capex_ocf"),
                domain="finance",
                name="capital_intensity_capex_operating_cash_flow",
                required_slots=["capital_expenditures", "operating_cash_flow"],
                expression="capital_expenditures / operating_cash_flow",
                output_unit="percent",
                output_attribute="capex_to_operating_cash_flow",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            ),
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "ppe_assets"),
                domain="finance",
                name="capital_intensity_ppe_assets",
                required_slots=["property_plant_and_equipment_net", "assets"],
                expression="property_plant_and_equipment_net / assets",
                output_unit="percent",
                output_attribute="ppe_to_assets",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            ),
        ]
    payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
    return [
        TransformSpec(
            spec_id="transform-spec-" + _short_hash(name, ",".join(formula_plan.missing_facts), str(payload.get("expression") or "")),
            domain="finance",
            name=name,
            required_slots=list(formula_plan.missing_facts or frame_missing_slots),
            expression=_string(payload.get("expression")) or None,
            output_unit=_string(payload.get("unit")) or None,
            output_attribute=name,
            diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
        )
    ]


def _target_entities(*, question: str, binding: JsonObject) -> list[str]:
    entities = []
    company = _string(binding.get("company") or binding.get("issuer"))
    if company:
        entities.append(company)
    for match in re.finditer(r"\b(?:NYSE|NASDAQ|Nasdaq|NYSEARCA)\s*:\s*([A-Z][A-Z0-9.]{0,5})\b", question):
        entities.append(match.group(1))
    return _ordered_unique(entities)


def _target_periods(*, question: str, binding: JsonObject) -> list[str]:
    periods = []
    period = _string(binding.get("doc_period") or binding.get("report_date"))
    if period:
        periods.append(period)
    for match in re.finditer(r"\b(?:FY|fiscal\s+year\s*)?((?:19|20)\d{2})\b", question, flags=re.IGNORECASE):
        periods.append(match.group(1))
    return _ordered_unique(periods)


def _success_criteria(task_type: str, formula_name: str | None, *, binding: JsonObject) -> list[str]:
    criteria = ["material claims must be backed by claim ledger or transform trace", "final answer must pass verifier gate"]
    if binding.get("primary_source_required"):
        criteria.append("evidence must satisfy target primary source binding")
    if formula_name:
        criteria.append("required transform must be planned before synthesis")
    if task_type in {"compute", "compare_compute", "model"}:
        criteria.append("numeric outputs must come from calculator traces or labeled assumptions")
    return criteria


def _source_role(*, binding: JsonObject, source_families: list[str]) -> str | None:
    if binding.get("doc_type"):
        return "primary_filing"
    if "market_data_provider" in source_families:
        return "market_data"
    if source_families:
        return source_families[0]
    return None


def _statement_for_slot(slot_name: str) -> str | None:
    if slot_name in {"capital_expenditures", "operating_cash_flow"}:
        return "cash_flow_statement"
    if slot_name in {"assets", "property_plant_and_equipment_net", "debt", "cash"}:
        return "balance_sheet"
    if slot_name in {"revenue", "net_income", "ebitda_or_ebitda_components"}:
        return "income_statement"
    return None


def _line_item_for_slot(slot_name: str) -> str | None:
    mapping = {
        "capital_expenditures": "capital expenditures",
        "operating_cash_flow": "operating cash flow",
        "property_plant_and_equipment_net": "property plant and equipment net",
        "assets": "assets",
        "revenue": "revenue",
    }
    return mapping.get(slot_name)


def _slot_matches_target_line(slot_name: str, line_item: str) -> bool:
    if not line_item:
        return False
    return _slot_name_for_line_item(line_item) == slot_name


def _slot_name_for_line_item(line_item: str) -> str:
    normalized = " ".join(str(line_item or "").lower().replace("&", " and ").split())
    if normalized in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        return "property_plant_and_equipment_net"
    return normalized.replace(" ", "_").replace("-", "_")


def _ordered_unique(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _short_hash(*parts: object) -> str:
    raw = "\n".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _string(value: object) -> str:
    return str(value or "").strip()
