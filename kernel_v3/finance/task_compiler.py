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
TASK_COMPILE_FACT_LIMIT = 24
TASK_COMPILE_PROMPT_CONTRACT = (
    "You are task.compile for Holo Kernel v3. Return only one JSON object. "
    "The model owns semantic task decomposition; the host only validates schema, executes tools, journals provenance, and verifies arithmetic. "
    "Compile the objective into task_spec, evidence_specs, transform_specs, slot_frame, and tool_chain_plan. "
    "Use the host fallback only as a scaffold: keep useful executable slots/transforms, correct wrong semantics, and remove unrelated slots. "
    "Evidence specs describe information to acquire; they are not evidence and must not invent source ids, citation ids, fact ids, URLs, values, or final answers. "
    "Transform specs are only for deterministic calculations whose inputs can be filled from evidence or stated assumptions. "
    "For numeric finance work, include calculator.compute in tool_chain_plan after supported inputs exist; do not ask synthesis to do mental arithmetic. "
    "For capital-intensity or capital-intensive-business analysis, consider executable ratios such as capex/revenue, capex/operating cash flow, PP&E/assets, and return on assets when the objective asks for an overall assessment. "
    "If you include return on assets, include net_income and assets slots and a calculator-visible net_income / assets transform. "
    "Keep required slots minimal and executable: include fields needed by the objective and transform expressions, and do not add financial statement lines that are not requested and not transform inputs. "
    "If current facts already support a slot, list it as filled; if not, list it in missing_slots with a precise retrieval/tool next step. "
    "Return compact JSON: evidence_specs<=12, transform_specs<=8, required_slots<=16, reason_summary<=240 chars, no markdown."
)
TASK_COMPILE_OUTPUT_SCHEMA: JsonObject = {
    "task_spec": {
        "task_type": "filing_metric_lookup|compute|compare_compute|reconciliation|transaction_multiple|valuation_multiple|disclosure_analysis|modeling_lite|other",
        "objective": "root task",
        "target_entities": ["issuers/targets/tickers"],
        "target_periods": ["periods"],
        "success_criteria": ["auditable completion criteria"],
    },
    "evidence_specs": [
        {
            "slot_name": "input/info slot",
            "accepted_attributes": ["metric aliases"],
            "source_role": "primary_filing|annual_report|earnings_release|transaction_disclosure|market_data|benchmark_context|other",
            "required_source_families": ["source families"],
            "target_period": "period|null",
            "statement": "statement/table/section|null",
            "line_item": "line item|null",
            "required": True,
        }
    ],
    "transform_specs": [
        {
            "name": "transform name",
            "required_slots": ["slot names"],
            "expression": "calculator expression|null",
            "output_unit": "unit|null",
            "output_attribute": "output attribute",
        }
    ],
    "slot_frame": {
        "task_type": "same as task_spec",
        "required_slots": [{"name": "slot", "accepted_attributes": ["aliases"], "source_requirements": ["source role/family"]}],
        "filled_slots": [{"slot_name": "slot", "fact_id": "fact id if present", "confidence": 0.0}],
        "missing_slots": ["unfilled required slots"],
    },
    "tool_chain_plan": {
        "decision_owner": "model",
        "recommended_steps": [{"tool": "retrieval.run|calculator.compute|workspace.search|file.read|script.exec|respond", "reason": "why now"}],
    },
    "reason_summary": "short semantic rationale",
}


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
    llm_judgment_required: bool = False,
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
        if llm_judgment_required:
            return _model_unavailable_program(
                question=question,
                fallback=fallback,
                reason="task_compile_processor_fabric_not_configured",
            )
        return fallback
    parameters: JsonObject = {
        "temperature": 0.0,
        "generation_mode": "auto",
        "latency_target": "quality",
    }
    if processor_budget:
        parameters["processor_budget"] = processor_budget
    parameters["max_tokens"] = max(
        int(parameters.get("max_tokens") or 0),
        _task_compile_max_tokens(facts=facts, fallback=fallback),
    )
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
        retry_outcome = processor_fabric.run_json(
            task_type=TASK_COMPILE_TASK_TYPE,
            run_id=run_id,
            context_id=(context_id or "ctx-task-compile-" + _short_hash(question)) + "-retry",
            prompt=_model_task_compile_retry_prompt(
                question=question,
                facts=facts,
                target_binding=target_binding,
                fallback=fallback,
                previous_error=outcome.result.error or "task_compile_processor_failed",
                previous_raw_output=outcome.raw_text,
            ),
            schema=TASK_COMPILE_SCHEMA,
            task_id=task_id,
            step_id=f"{step_id or 'task-compile'}-retry",
            timeout_seconds=120,
            parameters=parameters,
        )
        if retry_outcome.result.status == "ok" and isinstance(retry_outcome.parsed, dict):
            outcome = retry_outcome
    if outcome.result.status != "ok" or not isinstance(outcome.parsed, dict):
        if llm_judgment_required:
            return _model_unavailable_program(
                question=question,
                fallback=fallback,
                reason=outcome.result.error or "task_compile_processor_failed",
                provider=outcome.provider,
                model=outcome.model,
            )
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
        if llm_judgment_required:
            return _model_unavailable_program(
                question=question,
                fallback=fallback,
                reason="task_compile_output_rejected",
                provider=outcome.provider,
                model=outcome.model,
                details={"error": type(exc).__name__, "message": str(exc)[:240]},
            )
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
    payload = {
        "contract": TASK_COMPILE_PROMPT_CONTRACT,
        "output_schema": TASK_COMPILE_OUTPUT_SCHEMA,
        "task_packet": _task_compile_dynamic_packet(
            question=question,
            facts=facts,
            target_binding=target_binding,
            fallback=fallback,
        ),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _task_compile_max_tokens(*, facts: list[FinanceFact], fallback: CompiledTaskProgram) -> int:
    evidence_count = len(fallback.evidence_specs)
    transform_count = len(fallback.transform_specs)
    slot_count = len(fallback.slot_frame.required_slots) if fallback.slot_frame is not None else 0
    if len(facts) >= TASK_COMPILE_FACT_LIMIT or evidence_count + transform_count + slot_count > 24:
        return 8192
    if len(facts) >= 10 or evidence_count + transform_count + slot_count > 12:
        return 6144
    return 4096


def _model_task_compile_retry_prompt(
    *,
    question: str,
    facts: list[FinanceFact],
    target_binding: JsonObject | None,
    fallback: CompiledTaskProgram,
    previous_error: str,
    previous_raw_output: str | None,
) -> str:
    payload = {
        "contract": (
            TASK_COMPILE_PROMPT_CONTRACT
            + " Previous output was rejected by host JSON/schema validation. Recompile from the task packet; do not repair by adding prose."
        ),
        "output_schema": TASK_COMPILE_OUTPUT_SCHEMA,
        "previous_failure": {
            "error": str(previous_error or "")[:240],
            "raw_output_preview": _text_preview(previous_raw_output or "", 900),
            "structured_feedback": _task_compile_repair_feedback(previous_error),
        },
        "task_packet": _task_compile_dynamic_packet(
            question=question,
            facts=facts,
            target_binding=target_binding,
            fallback=fallback,
        ),
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _task_compile_repair_feedback(error: str) -> JsonObject:
    code = str(error or "unknown").strip() or "unknown"
    feedback: JsonObject = {
        "schema": "holo.kernel_v3.task_compile_repair_feedback.v1",
        "error_code": _text_preview(code, 240),
        "required_fields": list(TASK_COMPILE_SCHEMA.required.keys()),
        "optional_fields": list(TASK_COMPILE_SCHEMA.optional.keys()),
        "host_role": "schema_parse_validation_only",
        "model_role": "recompile_task_semantics_from_task_packet",
    }
    checklist = [
        "Return exactly one JSON object with no markdown or prose outside JSON.",
        "Include task_spec, evidence_specs, and transform_specs.",
        "Keep evidence_specs as an array, even when empty.",
        "Keep transform_specs as an array, even when empty.",
        "Do not invent facts, citation ids, evidence ids, source ids, values, or final answers.",
        "Use host_fallback_program only as a scaffold; correct its semantics when the objective requires it.",
    ]
    if code.startswith("missing_required_field:"):
        field = code.split(":", 1)[1].strip()
        feedback["category"] = "missing_required_field"
        feedback["field"] = field
        checklist.insert(1, f"Add required field `{field}` with the schema type shown in output_schema.")
    elif code.startswith("invalid_field_type:"):
        parts = code.split(":")
        field = parts[1].strip() if len(parts) > 1 else ""
        expected = parts[2].strip() if len(parts) > 2 else ""
        feedback["category"] = "invalid_field_type"
        if field:
            feedback["field"] = field
        if expected:
            feedback["expected_type"] = expected
        if field and expected:
            checklist.insert(1, f"Rewrite `{field}` as type `{expected}`.")
    elif "json_root_not_object" in code:
        feedback["category"] = "json_root_not_object"
        checklist.insert(1, "The root must be a JSON object, not an array, string, or scalar.")
    elif "JSONDecodeError" in code or "json_invalid" in code or "Expecting" in code:
        feedback["category"] = "malformed_json"
        checklist.insert(1, "Fix JSON syntax: close arrays/objects, quote keys and strings, and remove trailing prose.")
    else:
        feedback["category"] = "schema_or_parse_error"
    feedback["repair_checklist"] = checklist
    return feedback


def _task_compile_dynamic_packet(
    *,
    question: str,
    facts: list[FinanceFact],
    target_binding: JsonObject | None,
    fallback: CompiledTaskProgram,
) -> JsonObject:
    return {
        "schema": "holo.kernel_v3.task_compile_input.v1",
        "domain": "finance",
        "fact_ledger_count": len(facts),
        "fact_ledger": _compact_fact_summaries(facts),
        "objective": question,
        "target_binding": _compact_target_binding(target_binding),
        "host_fallback_program": _compact_program_for_model(fallback),
        "host_fallback_risks": _host_fallback_risks(fallback),
    }


def _host_fallback_risks(fallback: CompiledTaskProgram) -> list[JsonObject]:
    risks: list[JsonObject] = []
    formula_name = str(fallback.task_spec.diagnostics.get("formula_name") or "")
    if formula_name == "yoy_growth":
        risks.append(
            {
                "risk": "fallback_yoy_growth_may_be_over_eager",
                "decision_owner": "model",
                "instruction": (
                    "Keep yoy_growth only when the task asks for a numeric year-over-year or growth-rate calculation. "
                    "If the task asks which source, segment, factor, or disclosure explains growth, compile source-grounded "
                    "evidence slots instead of prior/current numeric formula slots."
                ),
            }
        )
    if formula_name == "capital_intensity":
        risks.append(
            {
                "risk": "capital_intensity_needs_complete_ratio_lens",
                "decision_owner": "model",
                "instruction": (
                    "For an overall capital-intensive-business assessment, decide whether to keep the fallback's executable "
                    "capex/revenue, capex/operating cash flow, PP&E/assets, and ROA transforms. If you omit ROA/net_income, "
                    "explain why the objective does not require profitability/asset-return context."
                ),
            }
        )
    return risks


def _compiled_program_from_model_output(
    parsed: JsonObject,
    *,
    question: str,
    fallback: CompiledTaskProgram,
) -> CompiledTaskProgram:
    task_spec = _model_task_spec(parsed.get("task_spec"), question=question, fallback=fallback.task_spec)
    preserve_formula_contract = _model_scaffold_formula_contract_required(task_spec=task_spec, fallback=fallback)
    task_spec = _preserve_fallback_task_contract(
        task_spec,
        fallback=fallback,
        preserve_formula_contract=preserve_formula_contract,
    )
    evidence_specs = _model_evidence_specs(parsed.get("evidence_specs"), fallback=fallback.evidence_specs, task_type=task_spec.task_type)
    evidence_specs = _preserve_fallback_evidence_contract(
        evidence_specs,
        fallback=fallback,
        preserve_formula_contract=preserve_formula_contract,
    )
    transform_specs = _model_transform_specs(parsed.get("transform_specs"), fallback=fallback.transform_specs)
    transform_specs = _preserve_fallback_transform_contract(
        transform_specs,
        fallback=fallback,
        preserve_formula_contract=preserve_formula_contract,
    )
    slot_frame = _model_slot_frame(
        parsed.get("slot_frame"),
        parsed=parsed,
        fallback=fallback.slot_frame,
        task_spec=task_spec,
        evidence_specs=evidence_specs,
    )
    slot_frame = _preserve_fallback_slot_contract(
        slot_frame,
        fallback=fallback,
        preserve_formula_contract=preserve_formula_contract,
    )
    diagnostics = {
        **dict(fallback.diagnostics),
        "source": "task_compile_model",
        "semantic_decision_owner": "model",
        "host_fallback_role": "scaffold_only_no_semantic_override",
        "fallback_program_id": fallback.program_id,
        "model_reason_summary": _string(parsed.get("reason_summary"))[:480],
        "model_diagnostics": _json_object(parsed.get("diagnostics")),
        "tool_chain_plan": _model_tool_chain_plan(
            parsed.get("tool_chain_plan"),
            fallback=fallback,
            preserve_formula_contract=preserve_formula_contract,
        ),
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


def _model_scaffold_formula_contract_required(*, task_spec: TaskSpec, fallback: CompiledTaskProgram) -> bool:
    fallback_formula = _string(fallback.task_spec.diagnostics.get("formula_name"))
    if fallback_formula != "capital_intensity":
        return False
    if task_spec.task_type not in {"compute", "compare_compute", "modeling_lite"}:
        return False
    model_formula = _string(task_spec.diagnostics.get("formula_name"))
    return model_formula in {"", fallback_formula}


def _fallback_formula_contract_required(fallback: CompiledTaskProgram) -> bool:
    formula_name = _string(fallback.task_spec.diagnostics.get("formula_name"))
    if not formula_name or formula_name == "yoy_growth":
        return False
    return bool(fallback.transform_specs)


def _preserve_fallback_task_contract(
    task_spec: TaskSpec,
    *,
    fallback: CompiledTaskProgram,
    preserve_formula_contract: bool,
) -> TaskSpec:
    if not preserve_formula_contract:
        return task_spec
    if fallback.task_spec.task_type not in {"compute", "compare_compute", "model", "reconcile"}:
        return task_spec
    if task_spec.task_type in {"compute", "compare_compute", "model", "reconcile"}:
        return task_spec
    return replace(
        task_spec,
        task_type=fallback.task_spec.task_type,
        success_criteria=_ordered_unique([*list(task_spec.success_criteria), *list(fallback.task_spec.success_criteria)]),
        diagnostics={
            **dict(task_spec.diagnostics),
            "fallback_formula_contract_preserved": True,
            "fallback_task_type": fallback.task_spec.task_type,
        },
    )


def _preserve_fallback_evidence_contract(
    evidence_specs: list[EvidenceSpec],
    *,
    fallback: CompiledTaskProgram,
    preserve_formula_contract: bool,
) -> list[EvidenceSpec]:
    if not preserve_formula_contract:
        return evidence_specs
    seen = {spec.slot_name for spec in evidence_specs}
    merged = list(evidence_specs)
    for spec in fallback.evidence_specs:
        if spec.slot_name in seen:
            continue
        merged.append(spec)
        seen.add(spec.slot_name)
    return merged


def _preserve_fallback_transform_contract(
    transform_specs: list[TransformSpec],
    *,
    fallback: CompiledTaskProgram,
    preserve_formula_contract: bool,
) -> list[TransformSpec]:
    if not preserve_formula_contract:
        return transform_specs
    seen = {spec.name for spec in transform_specs}
    merged = list(transform_specs)
    for spec in fallback.transform_specs:
        if spec.name in seen:
            continue
        merged.append(spec)
        seen.add(spec.name)
    return merged


def _preserve_fallback_slot_contract(
    slot_frame: SlotFrame,
    *,
    fallback: CompiledTaskProgram,
    preserve_formula_contract: bool,
) -> SlotFrame:
    if not preserve_formula_contract or fallback.slot_frame is None:
        return slot_frame
    required = list(slot_frame.required_slots)
    seen = {slot.name for slot in required}
    for slot in fallback.slot_frame.required_slots:
        if slot.name in seen:
            continue
        required.append(slot)
        seen.add(slot.name)
    task_type = slot_frame.task_type
    if task_type not in {"compute", "compare_compute", "model", "reconcile"}:
        task_type = fallback.slot_frame.task_type
    return replace(
        slot_frame,
        task_type=task_type,
        required_slots=required,
        missing_slots=_ordered_unique([*list(slot_frame.missing_slots), *list(fallback.slot_frame.missing_slots)]),
        diagnostics={
            **dict(slot_frame.diagnostics),
            "fallback_formula_contract_preserved": True,
        },
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


def _model_unavailable_program(
    *,
    question: str,
    fallback: CompiledTaskProgram,
    reason: str,
    provider: str | None = None,
    model: str | None = None,
    details: JsonObject | None = None,
) -> CompiledTaskProgram:
    task_spec = TaskSpec(
        spec_id="task-spec-llm-unavailable-" + _short_hash(question, reason),
        domain="finance",
        task_type="model_judgment_unavailable",
        objective=question or fallback.task_spec.objective,
        target_entities=list(fallback.task_spec.target_entities),
        target_periods=list(fallback.task_spec.target_periods),
        success_criteria=[
            "Run task.compile with a model before deciding evidence slots or transforms.",
            "Do not let deterministic fallback become the semantic task compiler.",
        ],
        diagnostics={
            "source": "task_compile_model_unavailable",
            "semantic_decision_owner": "model",
            "host_fallback_role": "blocked_no_semantic_override",
            "reason": reason,
            "provider": provider,
            "model": model,
            **({"details": details} if details else {}),
        },
    )
    policy = EvidencePolicy(
        policy_id="policy-llm-task-compile-required-" + _short_hash(question, reason),
        domain="finance",
        required_source_families=[],
        forbidden_source_families=[],
        required_terms=[],
        authority=None,
        diagnostics={
            "source": "task_compile_model_unavailable",
            "semantic_decision_owner": "model",
            "host_role": "schema_state_only",
        },
    )
    slot_frame = SlotFrame(
        frame_id="slot-frame-llm-unavailable-" + _short_hash(question, reason),
        task_type="model_judgment_unavailable",
        domain="finance",
        required_slots=[
            SlotSpec(
                name="llm_task_compile_judgment",
                requirement="required",
                description="A model-owned task.compile packet is required before semantic slot, source, or transform decisions.",
                accepted_attributes=["task_spec", "evidence_specs", "transform_specs", "slot_frame"],
                source_requirements=["model:task.compile"],
                metadata={"semantic_decision_owner": "model"},
            )
        ],
        missing_slots=["llm_task_compile_judgment"],
        evidence_policy=policy,
        diagnostics={
            "source": "task_compile_model_unavailable",
            "reason": reason,
            "semantic_decision_owner": "model",
            "host_fallback_role": "blocked_no_semantic_override",
        },
    )
    return CompiledTaskProgram(
        program_id="task-program-llm-unavailable-" + _short_hash(task_spec.spec_id, reason),
        domain="finance",
        task_spec=task_spec,
        evidence_specs=[],
        transform_specs=[],
        slot_frame=slot_frame,
        transform_plan=None,
        diagnostics={
            "source": "task_compile_model_unavailable",
            "status": "llm_judgment_unavailable",
            "semantic_decision_owner": "model",
            "host_fallback_role": "blocked_no_semantic_override",
            "fallback_program_id": fallback.program_id,
            "reason": reason,
            "provider": provider,
            "model": model,
            "tool_chain_plan": {
                "schema": "holo.kernel_v3.tool_chain_plan.v1",
                "decision_owner": "model",
                "host_role": "tool_interface_only_until_model_judgment_returns",
                "task_type": "model_judgment_unavailable",
                "missing_slots": ["llm_task_compile_judgment"],
                "recommended_steps": [
                    {
                        "tool": "model:task.compile",
                        "purpose": "obtain model-owned task, evidence, slot, and transform judgment",
                    }
                ],
                "next_action_candidates": [
                    {
                        "action": "retry_task_compile_or_change_model_provider",
                        "reason": reason,
                    }
                ],
            },
            **({"details": details} if details else {}),
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
    raw_items = _json_list(value)
    for index, item in enumerate(raw_items[:24]):
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
    if specs:
        return specs
    if isinstance(value, list):
        return []
    return list(fallback)


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


def _model_tool_chain_plan(
    value: object,
    *,
    fallback: CompiledTaskProgram,
    preserve_formula_contract: bool = False,
) -> JsonObject:
    data = _json_object(value)
    if not data:
        data = _json_object(fallback.diagnostics.get("tool_chain_plan"))
    else:
        data.setdefault("schema", "holo.kernel_v3.tool_chain_plan.v1")
        data.setdefault("decision_owner", "model")
        data.setdefault("host_role", "verify_provenance_policy_budget_and_numeric_support")
    if preserve_formula_contract:
        fallback_plan = _json_object(fallback.diagnostics.get("tool_chain_plan"))
        formula_name = _string(fallback.task_spec.diagnostics.get("formula_name"))
        if formula_name:
            data["formula_name"] = formula_name
        if fallback_plan.get("formula_status") is not None:
            data["formula_status"] = fallback_plan.get("formula_status")
        data["missing_slots"] = _ordered_unique([
            *_string_list(data.get("missing_slots")),
            *_string_list(fallback_plan.get("missing_slots")),
        ])
        if not data.get("recommended_steps") and fallback_plan.get("recommended_steps"):
            data["recommended_steps"] = fallback_plan.get("recommended_steps")
        if not data.get("next_action_candidates") and fallback_plan.get("next_action_candidates"):
            data["next_action_candidates"] = fallback_plan.get("next_action_candidates")
    return data


def _compact_program_for_model(program: CompiledTaskProgram) -> JsonObject:
    tool_chain = _json_object(program.diagnostics.get("tool_chain_plan"))
    task_diagnostics = dict(program.task_spec.diagnostics)
    return {
        "program_id": program.program_id,
        "domain": program.domain,
        "task_spec": {
            "task_type": program.task_spec.task_type,
            "objective": program.task_spec.objective,
            "target_entities": list(program.task_spec.target_entities)[:8],
            "target_periods": list(program.task_spec.target_periods)[:8],
            "success_criteria": list(program.task_spec.success_criteria)[:6],
            "diagnostics": {
                key: task_diagnostics.get(key)
                for key in ("source", "formula_name", "formula_status", "fact_count")
                if task_diagnostics.get(key) is not None
            },
        },
        "evidence_specs": [_compact_evidence_spec_for_model(spec) for spec in program.evidence_specs[:12]],
        "transform_specs": [_compact_transform_spec_for_model(spec) for spec in program.transform_specs[:8]],
        "slot_frame": _compact_slot_frame_for_model(program.slot_frame),
        "tool_chain_plan": _compact_tool_chain_for_model(tool_chain),
        "diagnostics": {
            key: value
            for key, value in dict(program.diagnostics).items()
            if key in {"source", "evidence_spec_count", "transform_spec_count", "missing_slots"}
        },
    }


def _compact_evidence_spec_for_model(spec: EvidenceSpec) -> JsonObject:
    return {
        "slot_name": spec.slot_name,
        "accepted_attributes": list(spec.accepted_attributes)[:6],
        "source_role": spec.source_role,
        "required_source_families": list(spec.required_source_families)[:6],
        "target_period": spec.target_period,
        "statement": spec.statement,
        "line_item": spec.line_item,
        "required": spec.required,
    }


def _compact_transform_spec_for_model(spec: TransformSpec) -> JsonObject:
    return {
        "name": spec.name,
        "required_slots": list(spec.required_slots)[:10],
        "expression": spec.expression,
        "output_unit": spec.output_unit,
        "output_attribute": spec.output_attribute,
    }


def _compact_slot_frame_for_model(frame: SlotFrame | None) -> JsonObject | None:
    if frame is None:
        return None
    return {
        "task_type": frame.task_type,
        "required_slots": [
            {
                "name": slot.name,
                "accepted_attributes": list(slot.accepted_attributes)[:6],
                "source_requirements": list(slot.source_requirements)[:4],
            }
            for slot in frame.required_slots[:16]
        ],
        "filled_slots": [
            {
                "slot_name": fill.slot_name,
                "claim_id": fill.claim_id,
                "source_ref": fill.source_ref,
                "confidence": fill.confidence,
            }
            for fill in frame.filled_slots[:16]
        ],
        "missing_slots": list(frame.missing_slots)[:16],
    }


def _compact_tool_chain_for_model(plan: JsonObject) -> JsonObject:
    if not plan:
        return {}
    return {
        "decision_owner": plan.get("decision_owner") or "model",
        "task_type": plan.get("task_type"),
        "formula_status": plan.get("formula_status"),
        "formula_name": plan.get("formula_name"),
        "missing_slots": _string_list(plan.get("missing_slots"))[:16],
        "available_tools": [
            item
            for item in (
                {"name": "retrieval.run", "use_for": "evidence/source acquisition"},
                {"name": "calculator.compute", "use_for": "deterministic arithmetic after inputs are supported"},
                {"name": "workspace.search", "use_for": "local/cached document discovery"},
                {"name": "file.read", "use_for": "known local artifact inspection"},
                {"name": "script.exec", "use_for": "audited parser/calculation helper when exposed"},
            )
        ],
        "recommended_steps": [
            _compact_tool_step(item)
            for item in _json_list(plan.get("recommended_steps"))[:5]
        ],
        "next_action_candidates": [
            _compact_tool_step(item)
            for item in _json_list(plan.get("next_action_candidates"))[:5]
        ],
    }


def _compact_tool_step(item: JsonObject) -> JsonObject:
    return {
        key: value
        for key, value in {
            "step": item.get("step"),
            "tool": item.get("tool"),
            "reason": item.get("reason"),
            "when": _text_preview(_string(item.get("when")), 180),
            "missing_slots": _string_list(item.get("missing_slots"))[:10],
            "formula_name": item.get("formula_name"),
            "payload_available": item.get("payload_available"),
            "transform_specs": item.get("transform_specs") if isinstance(item.get("transform_specs"), list) else None,
        }.items()
        if not _empty_model_value(value)
    }


def _compact_target_binding(value: JsonObject | None) -> JsonObject:
    data = dict(value) if isinstance(value, dict) else {}
    keep = (
        "company",
        "issuer",
        "ticker",
        "cik",
        "doc_period",
        "report_date",
        "doc_type",
        "accession",
        "primary_source_required",
        "required_statement",
        "required_line_item",
    )
    return {str(key): data.get(key) for key in keep if not _empty_model_value(data.get(key))}


def _compact_fact_summaries(facts: list[FinanceFact]) -> list[JsonObject]:
    summaries: list[JsonObject] = []
    seen: set[str] = set()
    for fact in facts:
        key = fact.fact_id or "|".join([
            str(fact.entity or ""),
            str(fact.ticker or ""),
            str(fact.period or fact.fiscal_year or ""),
            str(fact.metric or ""),
            str(fact.value or ""),
        ])
        if key in seen:
            continue
        seen.add(key)
        summaries.append(_fact_summary(fact))
        if len(summaries) >= TASK_COMPILE_FACT_LIMIT:
            break
    return summaries


def _fact_summary(fact: FinanceFact) -> JsonObject:
    metadata = dict(fact.metadata)
    return {
        "fact_id": _compact_fact_text(fact.fact_id, 96),
        "entity": _compact_fact_text(fact.entity, 96),
        "ticker": _compact_fact_text(fact.ticker, 24),
        "period": _compact_fact_text(fact.period, 64),
        "fiscal_year": fact.fiscal_year,
        "metric": _compact_fact_text(fact.metric, 120),
        "value": _compact_fact_text(fact.value, 80),
        "unit": _compact_fact_text(fact.unit, 40),
        "scale": _compact_fact_text(fact.scale, 40),
        "source_ref": _compact_fact_text(fact.source_ref, 120),
        "evidence_ref": _compact_fact_text(fact.evidence_ref, 120),
        "citation_ref": _compact_fact_text(fact.citation_ref, 80),
        "metadata": {
            key: _compact_fact_text(value, 120)
            for key, value in metadata.items()
            if key in {
                "form",
                "fp",
                "duration_days",
                "filed",
                "start",
                "end",
                "frame",
                "accn",
                "accession",
                "concept",
                "label",
                "statement",
                "line_item",
                "source_family",
                "target_document_binding_accepted",
                "target_document_binding_score",
            }
        },
    }


def _text_preview(text: str, limit: int = 240) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)] + "..."


def _compact_fact_text(value: object, limit: int) -> str | int | float | bool | None:
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return _text_preview(str(value), limit)


def _empty_model_value(value: object) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, dict)) and not value:
        return True
    return False


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
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "roa"),
                domain="finance",
                name="capital_intensity_return_on_assets",
                required_slots=["net_income", "assets"],
                expression="net_income / assets",
                output_unit="percent",
                output_attribute="return_on_assets",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            ),
        ]
    if name == "fixed_asset_turnover":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "revenue_average_ppe"),
                domain="finance",
                name="fixed_asset_turnover",
                required_slots=[
                    "revenue",
                    "property_plant_and_equipment_net_current",
                    "property_plant_and_equipment_net_prior",
                ],
                expression="revenue / ((property_plant_and_equipment_net_current + property_plant_and_equipment_net_prior) / 2)",
                output_unit="x",
                output_attribute="fixed_asset_turnover",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
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
                "tool": "retrieval.run | workspace.search | file.read | workspace.write | script.exec | shell.exec",
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
                "name": "workspace.write",
                "use_for": "write temporary parsers, normalized extraction artifacts, or intermediate JSON files when the recipe exposes workspace write",
                "host_boundary": "requires workspace:write permission and workspace-relative paths",
            },
            {
                "name": "script.exec",
                "use_for": "run a host-written temporary Python parser or local analysis program and emit JSON facts/tables/slot fills",
                "host_boundary": "requires shell:exec and workspace:write; outputs are audited before grounding",
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
    if slot_name in {
        "assets",
        "property_plant_and_equipment_net",
        "property_plant_and_equipment_net_current",
        "property_plant_and_equipment_net_prior",
        "debt",
        "cash",
    }:
        return "balance_sheet"
    if slot_name in {"revenue", "net_income", "ebitda_or_ebitda_components"}:
        return "income_statement"
    return None


def _line_item_for_slot(slot_name: str) -> str | None:
    mapping = {
        "capital_expenditures": "capital expenditures",
        "operating_cash_flow": "operating cash flow",
        "property_plant_and_equipment_net": "property plant and equipment net",
        "property_plant_and_equipment_net_current": "property plant and equipment net",
        "property_plant_and_equipment_net_prior": "property plant and equipment net",
        "assets": "assets",
        "revenue": "revenue",
        "net_income": "net income",
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
