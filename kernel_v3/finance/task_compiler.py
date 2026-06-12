from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace

from kernel_v3.contracts import JsonObject
from kernel_v3.finance.contracts import FinanceFact
from kernel_v3.finance.formula_planner import FinanceFormulaPlan, plan_finance_formula
from kernel_v3.finance.substrate_adapter import finance_formula_plan_to_transform_plan, finance_slot_frame
from kernel_v3.processors.contracts import TASK_COMPILE_SCHEMA
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.substrate import CompiledTaskProgram, EvidencePolicy, EvidenceSpec, SlotFill, SlotFrame, SlotSpec, TaskSpec, TransformSpec


TASK_COMPILE_TASK_TYPE = "task.compile"


def compile_finance_task_program_model_first(
    *,
    question: str,
    facts: list[FinanceFact],
    target_binding: JsonObject | None = None,
    plan: FinanceFormulaPlan | None = None,
    processor_fabric: ProcessorFabric | None = None,
    task_id: str | None = None,
    run_id: str = "task-compile-preflight",
    step_id: str | None = None,
    context_id: str | None = None,
    processor_budget: JsonObject | None = None,
) -> CompiledTaskProgram:
    """Compile a finance task with the LLM as the semantic owner.

    The deterministic compiler remains the host fallback and boundary. When a
    processor is available, the model receives the current question, target
    document binding, compact fact ledger, and host fallback program, then
    proposes TaskSpec/EvidenceSpec/TransformSpec. The host validates that output
    into contracts and never lets the model create evidence, citations, facts,
    or final numeric values.
    """

    fallback = compile_finance_task_program(
        question=question,
        facts=facts,
        target_binding=target_binding,
        plan=plan,
    )
    if processor_fabric is None:
        return fallback
    parameters: JsonObject = {
        "temperature": 0.0,
        "generation_mode": "auto",
        "latency_target": "quality",
    }
    if processor_budget:
        parameters["processor_budget"] = processor_budget
    outcome = processor_fabric.run_json(
        task_type=TASK_COMPILE_TASK_TYPE,
        run_id=run_id,
        context_id=context_id or "ctx-task-compile-" + _short_hash(question),
        prompt=_model_task_compile_prompt(
            question=question,
            facts=facts,
            target_binding=target_binding,
            fallback=fallback,
        ),
        schema=TASK_COMPILE_SCHEMA,
        task_id=task_id,
        step_id=step_id,
        timeout_seconds=120,
        parameters=parameters,
    )
    if outcome.result.status != "ok" or not isinstance(outcome.parsed, dict):
        return _fallback_program_with_model_diagnostic(
            fallback,
            reason=outcome.result.error or "task_compile_processor_failed",
            provider=outcome.provider,
            model=outcome.model,
        )
    try:
        return _compiled_program_from_model_output(
            outcome.parsed,
            question=question,
            fallback=fallback,
        )
    except Exception as exc:
        return _fallback_program_with_model_diagnostic(
            fallback,
            reason="task_compile_output_rejected",
            provider=outcome.provider,
            model=outcome.model,
            details={"error": type(exc).__name__, "message": str(exc)[:240]},
        )


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
    tool_chain_plan = _tool_chain_plan(
        frame=frame,
        formula_plan=formula_plan,
        evidence_specs=evidence_specs,
        transform_specs=transform_specs,
    )
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
            "tool_chain_plan": tool_chain_plan,
        },
    )


def _model_task_compile_prompt(
    *,
    question: str,
    facts: list[FinanceFact],
    target_binding: JsonObject | None,
    fallback: CompiledTaskProgram,
) -> str:
    packet = {
        "schema": "holo.kernel_v3.task_compile_input.v1",
        "objective": question,
        "domain": "finance",
        "instruction": (
            "You are task.compile for Holo Kernel v3. Produce the work program a capable analyst would use: "
            "TaskSpec, EvidenceSpec, TransformSpec, and SlotFrame. Decide semantically; do not follow fixed query templates. "
            "The host fallback is a scaffold, not a constraint. Correct it when the question implies better slots, source roles, "
            "line items, periods, transforms, or tool-chain moves. Do not invent facts, evidence ids, citations, source ids, "
            "numeric values, formulas with unsupported inputs, or final answers. Host will validate and execute tools."
        ),
        "target_binding": target_binding or {},
        "fact_ledger": [_fact_summary(fact) for fact in facts[:96]],
        "host_fallback_program": _compact_program_for_model(fallback),
        "output_contract": {
            "task_spec": {
                "task_type": "semantic work type such as filing_qa, compute, compare_compute, reconciliation, transaction_multiple, valuation_multiple, disclosure_analysis, modeling_lite",
                "objective": "the task objective",
                "target_entities": ["company/ticker/entities if known"],
                "target_periods": ["periods if known"],
                "success_criteria": ["what must be true before synthesis"],
            },
            "evidence_specs": [
                {
                    "slot_name": "required information slot",
                    "accepted_attributes": ["metric aliases or line-item names"],
                    "source_role": "primary_filing | annual_report | earnings_release | transaction_disclosure | market_data | benchmark_context | other",
                    "required_source_families": ["source families if constrained"],
                    "target_period": "period or null",
                    "statement": "financial statement/table/section if applicable",
                    "line_item": "line item if applicable",
                    "required": True,
                }
            ],
            "transform_specs": [
                {
                    "name": "transform name",
                    "required_slots": ["slot names needed before calculator/synthesis"],
                    "expression": "calculator expression if deterministic and supported, else null",
                    "output_unit": "unit or null",
                    "output_attribute": "output attribute name",
                }
            ],
            "slot_frame": {
                "task_type": "same work type",
                "required_slots": [{"name": "slot", "accepted_attributes": ["aliases"], "source_requirements": ["source role/family"]}],
                "missing_slots": ["slots not supported by current fact_ledger"],
            },
            "tool_chain_plan": {
                "decision_owner": "model",
                "recommended_steps": ["plain JSON objects describing the next tool-chain moves"],
            },
        },
    }
    return (
        "Return exactly one JSON object matching task.compile. "
        "Prefer the model's semantic judgment over the host fallback when they differ, but keep every required slot executable and auditable.\n\n"
        f"Packet:\n{json.dumps(packet, ensure_ascii=False, sort_keys=True)}"
    )


def _compiled_program_from_model_output(
    parsed: JsonObject,
    *,
    question: str,
    fallback: CompiledTaskProgram,
) -> CompiledTaskProgram:
    task_spec = _model_task_spec(parsed.get("task_spec"), question=question, fallback=fallback.task_spec)
    evidence_specs = _model_evidence_specs(parsed.get("evidence_specs"), fallback=fallback.evidence_specs, task_type=task_spec.task_type)
    transform_specs = _model_transform_specs(parsed.get("transform_specs"), fallback=fallback.transform_specs)
    slot_frame = _model_slot_frame(
        parsed.get("slot_frame"),
        parsed=parsed,
        fallback=fallback.slot_frame,
        task_spec=task_spec,
        evidence_specs=evidence_specs,
    )
    diagnostics = {
        **dict(fallback.diagnostics),
        "source": "task_compile_model",
        "fallback_program_id": fallback.program_id,
        "model_reason_summary": _string(parsed.get("reason_summary"))[:480],
        "model_diagnostics": _json_object(parsed.get("diagnostics")),
        "tool_chain_plan": _model_tool_chain_plan(parsed.get("tool_chain_plan"), fallback=fallback),
    }
    return CompiledTaskProgram(
        program_id="task-program-model-" + _short_hash(task_spec.spec_id, ",".join(spec.slot_name for spec in evidence_specs)),
        domain=task_spec.domain or "finance",
        task_spec=task_spec,
        evidence_specs=evidence_specs,
        transform_specs=transform_specs,
        slot_frame=slot_frame,
        transform_plan=fallback.transform_plan,
        diagnostics=diagnostics,
    )


def _fallback_program_with_model_diagnostic(
    fallback: CompiledTaskProgram,
    *,
    reason: str,
    provider: str | None = None,
    model: str | None = None,
    details: JsonObject | None = None,
) -> CompiledTaskProgram:
    return replace(
        fallback,
        diagnostics={
            **dict(fallback.diagnostics),
            "task_compile_model": {
                "status": "fallback",
                "reason": reason,
                "provider": provider,
                "model": model,
                **(details or {}),
            },
        },
    )


def _model_task_spec(value: object, *, question: str, fallback: TaskSpec) -> TaskSpec:
    data = _json_object(value)
    task_type = _string(data.get("task_type")) or fallback.task_type
    return TaskSpec(
        spec_id=_string(data.get("spec_id")) or "task-spec-model-" + _short_hash(question, task_type),
        domain=_string(data.get("domain")) or fallback.domain or "finance",
        task_type=task_type,
        objective=_string(data.get("objective")) or question or fallback.objective,
        target_entities=_string_list(data.get("target_entities")) or list(fallback.target_entities),
        target_periods=_string_list(data.get("target_periods")) or list(fallback.target_periods),
        success_criteria=_string_list(data.get("success_criteria")) or list(fallback.success_criteria),
        diagnostics={
            **dict(fallback.diagnostics),
            "source": "task_compile_model",
            **_json_object(data.get("diagnostics")),
        },
    )


def _model_evidence_specs(value: object, *, fallback: list[EvidenceSpec], task_type: str) -> list[EvidenceSpec]:
    specs: list[EvidenceSpec] = []
    for index, item in enumerate(_json_list(value)[:32]):
        slot_name = _string(item.get("slot_name") or item.get("name"))
        if not slot_name:
            continue
        specs.append(
            EvidenceSpec(
                spec_id=_string(item.get("spec_id")) or "evidence-spec-model-" + _short_hash(slot_name, index),
                slot_name=slot_name,
                domain=_string(item.get("domain")) or "finance",
                accepted_attributes=_string_list(item.get("accepted_attributes") or item.get("aliases")),
                source_role=_string(item.get("source_role")) or None,
                required_source_families=_string_list(item.get("required_source_families")),
                target_period=_string(item.get("target_period")) or None,
                statement=_string(item.get("statement")) or None,
                line_item=_string(item.get("line_item")) or None,
                required=bool(item.get("required", True)),
                diagnostics={
                    "source": "task_compile_model",
                    "task_type": task_type,
                    **_json_object(item.get("diagnostics")),
                },
            )
        )
    return specs or list(fallback)


def _model_transform_specs(value: object, *, fallback: list[TransformSpec]) -> list[TransformSpec]:
    specs: list[TransformSpec] = []
    for index, item in enumerate(_json_list(value)[:24]):
        name = _string(item.get("name"))
        if not name:
            continue
        specs.append(
            TransformSpec(
                spec_id=_string(item.get("spec_id")) or "transform-spec-model-" + _short_hash(name, index),
                domain=_string(item.get("domain")) or "finance",
                name=name,
                required_slots=_string_list(item.get("required_slots")),
                expression=_string(item.get("expression")) or None,
                output_unit=_string(item.get("output_unit")) or None,
                output_attribute=_string(item.get("output_attribute")) or name,
                diagnostics={
                    "source": "task_compile_model",
                    **_json_object(item.get("diagnostics")),
                },
            )
        )
    return specs or list(fallback)


def _model_slot_frame(
    value: object,
    *,
    parsed: JsonObject,
    fallback: SlotFrame | None,
    task_spec: TaskSpec,
    evidence_specs: list[EvidenceSpec],
) -> SlotFrame:
    data = _json_object(value)
    required_slots = _model_slot_specs(data.get("required_slots"))
    if not required_slots:
        required_slots = [
            SlotSpec(
                name=spec.slot_name,
                requirement="required" if spec.required else "optional",
                accepted_attributes=list(spec.accepted_attributes),
                source_requirements=_ordered_unique([*list(spec.required_source_families), _string(spec.source_role)]),
                metadata={"source": "task_compile_model", "evidence_spec_id": spec.spec_id},
            )
            for spec in evidence_specs
        ]
    optional_slots = _model_slot_specs(data.get("optional_slots"))
    filled_slots = _model_slot_fills(data.get("filled_slots"))
    missing_slots = _string_list(data.get("missing_slots")) or _string_list(parsed.get("missing_slots"))
    if not missing_slots and fallback is not None:
        missing_slots = list(fallback.missing_slots)
    return SlotFrame(
        frame_id=_string(data.get("frame_id")) or "slot-frame-model-" + _short_hash(task_spec.spec_id),
        task_type=_string(data.get("task_type")) or task_spec.task_type,
        domain=_string(data.get("domain")) or task_spec.domain or "finance",
        required_slots=required_slots,
        optional_slots=optional_slots,
        filled_slots=filled_slots,
        missing_slots=missing_slots,
        evidence_policy=_model_evidence_policy(data.get("evidence_policy"), fallback=fallback.evidence_policy if fallback else None),
        diagnostics={
            "source": "task_compile_model",
            **_json_object(data.get("diagnostics")),
        },
    )


def _model_slot_specs(value: object) -> list[SlotSpec]:
    specs: list[SlotSpec] = []
    for item in _json_list_or_strings(value)[:32]:
        if isinstance(item, str):
            name = _string(item)
            if name:
                specs.append(SlotSpec(name=name))
            continue
        name = _string(item.get("name") or item.get("slot_name"))
        if not name:
            continue
        requirement = _string(item.get("requirement")) or "required"
        if requirement not in {"required", "optional"}:
            requirement = "required"
        specs.append(
            SlotSpec(
                name=name,
                requirement=requirement,
                description=_string(item.get("description")) or None,
                accepted_attributes=_string_list(item.get("accepted_attributes") or item.get("aliases")),
                source_requirements=_string_list(item.get("source_requirements")),
                metadata=_json_object(item.get("metadata")),
            )
        )
    return specs


def _model_slot_fills(value: object) -> list[SlotFill]:
    fills: list[SlotFill] = []
    for item in _json_list(value)[:64]:
        slot_name = _string(item.get("slot_name") or item.get("name"))
        if not slot_name:
            continue
        fills.append(
            SlotFill(
                slot_name=slot_name,
                claim_id=_string(item.get("claim_id")) or None,
                value=_string(item.get("value")) or None,
                source_ref=_string(item.get("source_ref")) or None,
                confidence=_float_or_none(item.get("confidence")),
                metadata=_json_object(item.get("metadata")),
            )
        )
    return fills


def _model_evidence_policy(value: object, *, fallback: EvidencePolicy | None) -> EvidencePolicy | None:
    data = _json_object(value)
    if not data:
        return fallback
    return EvidencePolicy(
        policy_id=_string(data.get("policy_id")) or "evidence-policy-model-" + _short_hash(data),
        domain=_string(data.get("domain")) or "finance",
        required_source_families=_string_list(data.get("required_source_families")),
        forbidden_source_families=_string_list(data.get("forbidden_source_families")),
        required_terms=_string_list(data.get("required_terms")),
        authority=_string(data.get("authority")) or None,
        freshness=_string(data.get("freshness")) or None,
        diagnostics={"source": "task_compile_model", **_json_object(data.get("diagnostics"))},
    )


def _model_tool_chain_plan(value: object, *, fallback: CompiledTaskProgram) -> JsonObject:
    data = _json_object(value)
    if not data:
        return _json_object(fallback.diagnostics.get("tool_chain_plan"))
    data.setdefault("schema", "holo.kernel_v3.tool_chain_plan.v1")
    data.setdefault("decision_owner", "model")
    data.setdefault("host_role", "verify_provenance_policy_budget_and_numeric_support")
    return data


def _compact_program_for_model(program: CompiledTaskProgram) -> JsonObject:
    return {
        "program_id": program.program_id,
        "domain": program.domain,
        "task_spec": program.task_spec.to_dict(),
        "evidence_specs": [spec.to_dict() for spec in program.evidence_specs[:16]],
        "transform_specs": [spec.to_dict() for spec in program.transform_specs[:12]],
        "slot_frame": program.slot_frame.to_dict() if program.slot_frame is not None else None,
        "diagnostics": {
            key: value
            for key, value in dict(program.diagnostics).items()
            if key in {"source", "evidence_spec_count", "transform_spec_count", "missing_slots", "tool_chain_plan"}
        },
    }


def _fact_summary(fact: FinanceFact) -> JsonObject:
    return {
        "fact_id": fact.fact_id,
        "entity": fact.entity,
        "ticker": fact.ticker,
        "period": fact.period,
        "fiscal_year": fact.fiscal_year,
        "metric": fact.metric,
        "value": fact.value,
        "unit": fact.unit,
        "scale": fact.scale,
        "source_ref": fact.source_ref,
        "evidence_ref": fact.evidence_ref,
        "citation_ref": fact.citation_ref,
        "metadata": {
            key: value
            for key, value in dict(fact.metadata).items()
            if key in {"form", "filed", "accession", "concept", "statement", "line_item"}
        },
    }


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


def _tool_chain_plan(
    *,
    frame,
    formula_plan: FinanceFormulaPlan,
    evidence_specs: list[EvidenceSpec],
    transform_specs: list[TransformSpec],
) -> JsonObject:
    """Expose a model-readable assembly surface for the next workflow move.

    The compiler does not answer the task and does not decide final relevance.
    It makes the intermediate program explicit so the LLM planner/workbench can
    choose how to assemble retrieval, calculator, verifier, and synthesis steps
    while the host keeps provenance and numeric gates.
    """

    missing_slots = _ordered_unique([
        *list(frame.missing_slots),
        *list(formula_plan.missing_facts),
    ])
    recommended_steps: list[JsonObject] = []
    next_action_candidates: list[JsonObject] = []
    if missing_slots or evidence_specs:
        recommended_steps.append(
            {
                "step": "acquire_or_read_evidence",
                "tool": "retrieval.run | workspace.search | file.read | shell.exec",
                "decision_owner": "model",
                "when": "required slots are missing, source evidence has not been accepted, or local/cached documents need parsing",
                "missing_slots": missing_slots[:16],
                "evidence_specs": [_tool_chain_evidence_spec(spec) for spec in evidence_specs[:12]],
            }
        )
        next_action_candidates.append(
            {
                "tool": "retrieval.run",
                "reason": "fill_missing_evidence_slots",
                "missing_slots": missing_slots[:16],
                "target_source_roles": _ordered_unique([
                    str(spec.source_role or "")
                    for spec in evidence_specs
                    if spec.source_role
                ])[:8],
            }
        )
    if formula_plan.status == "ready" and isinstance(formula_plan.payload, dict):
        recommended_steps.append(
            {
                "step": "compute_supported_transform",
                "tool": "calculator.compute",
                "decision_owner": "model",
                "when": "all formula inputs are supported by claim ledger facts and no equivalent formula trace exists",
                "formula_name": formula_plan.formula_name,
                "input_fact_ids": list(formula_plan.input_fact_ids)[:32],
                "transform_specs": [_tool_chain_transform_spec(spec) for spec in transform_specs[:8]],
            }
        )
        next_action_candidates.append(
            {
                "tool": "calculator.compute",
                "reason": "supported_transform_ready",
                "formula_name": formula_plan.formula_name,
                "payload_available": True,
            }
        )
    elif formula_plan.status == "missing_facts" and transform_specs:
        recommended_steps.append(
            {
                "step": "do_not_compute_yet",
                "tool": "calculator.compute",
                "decision_owner": "model",
                "when": "formula exists but required input slots are not supported yet",
                "missing_slots": missing_slots[:16],
                "transform_specs": [_tool_chain_transform_spec(spec) for spec in transform_specs[:8]],
            }
        )
    recommended_steps.append(
        {
            "step": "verify_then_synthesize",
            "tool": "host.verifier_gate",
            "decision_owner": "host",
            "when": "candidate answer material claims are backed by claim ledger, transform traces, or labeled assumptions",
            "guards": [
                "do not invent source ids, evidence ids, citations, facts, values, or formulas",
                "material numeric claims must pass numeric support and synthesis gates",
                "unsupported required slots must become explicit limitations, not fabricated answers",
            ],
        }
    )
    return {
        "schema": "holo.kernel_v3.tool_chain_plan.v1",
        "decision_owner": "model",
        "host_role": "verify_provenance_policy_budget_and_numeric_support",
        "task_type": frame.task_type,
        "formula_status": formula_plan.status,
        "formula_name": formula_plan.formula_name,
        "missing_slots": missing_slots[:16],
        "available_tools": [
            {
                "name": "retrieval.run",
                "use_for": "source acquisition, document reading, evidence slot filling",
            },
            {
                "name": "workspace.list",
                "use_for": "discover local benchmark files, cached documents, reports, or trace directories when the recipe exposes workspace tools",
            },
            {
                "name": "workspace.search",
                "use_for": "locate local filings, JSONL rows, cached traces, scripts, or reports by keyword/path",
            },
            {
                "name": "file.read",
                "use_for": "inspect known local files, cached benchmark artifacts, scripts, traces, and extracted document text",
            },
            {
                "name": "shell.exec",
                "use_for": "run host-permitted local analysis scripts or CLI tools for document/table parsing, JSONL inspection, scoring, and evidence transformation",
                "host_boundary": "requires shell:exec permission and executable allowlist",
            },
            {
                "name": "calculator.compute",
                "use_for": "deterministic transforms after input facts are supported",
            },
            {
                "name": "host.verifier_gate",
                "use_for": "mandatory provenance, citation, assumption, and numeric support validation",
            },
        ],
        "recommended_steps": recommended_steps,
        "next_action_candidates": next_action_candidates,
    }


def _tool_chain_evidence_spec(spec: EvidenceSpec) -> JsonObject:
    return {
        "slot_name": spec.slot_name,
        "accepted_attributes": list(spec.accepted_attributes)[:6],
        "source_role": spec.source_role,
        "target_period": spec.target_period,
        "statement": spec.statement,
        "line_item": spec.line_item,
        "required": spec.required,
    }


def _tool_chain_transform_spec(spec: TransformSpec) -> JsonObject:
    return {
        "name": spec.name,
        "required_slots": list(spec.required_slots)[:12],
        "expression": spec.expression,
        "output_unit": spec.output_unit,
        "output_attribute": spec.output_attribute,
    }


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


def _json_object(value: object) -> JsonObject:
    return dict(value) if isinstance(value, dict) else {}


def _json_list(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _json_list_or_strings(value: object) -> list[JsonObject | str]:
    if not isinstance(value, list):
        return []
    result: list[JsonObject | str] = []
    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))
        elif isinstance(item, str):
            result.append(item)
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return _ordered_unique([str(item or "").strip() for item in value if str(item or "").strip()])


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _short_hash(*parts: object) -> str:
    raw = "\n".join(str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _string(value: object) -> str:
    return str(value or "").strip()
