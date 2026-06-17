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
        formula_plan=formula_plan,
        question=question,
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


def _evidence_specs(
    *,
    frame,
    binding: JsonObject,
    target_period: str | None,
    formula_plan: FinanceFormulaPlan | None = None,
    question: str = "",
) -> list[EvidenceSpec]:
    specs: list[EvidenceSpec] = []
    policy = frame.evidence_policy
    source_families = list(policy.required_source_families) if policy is not None else []
    statement = _string(binding.get("required_statement"))
    line_item = _string(binding.get("required_line_item"))
    for slot in frame.required_slots:
        formula_line_item = _line_item_for_formula_slot(
            str(formula_plan.formula_name or "") if formula_plan is not None else "",
            slot.name,
            question,
        )
        formula_statement = _statement_for_formula_slot(
            str(formula_plan.formula_name or "") if formula_plan is not None else "",
            slot.name,
            question,
        )
        specs.append(
            EvidenceSpec(
                spec_id="evidence-spec-" + _short_hash(frame.frame_id, slot.name),
                slot_name=slot.name,
                domain="finance",
                accepted_attributes=list(slot.accepted_attributes),
                source_role=_source_role(binding=binding, source_families=source_families),
                required_source_families=source_families,
                target_period=target_period,
                statement=statement or formula_statement or _statement_for_slot(slot.name),
                line_item=line_item if _slot_matches_target_line(slot.name, line_item) else formula_line_item or _line_item_for_slot(slot.name),
                required=slot.requirement == "required",
                diagnostics={"source": "finance_task_compiler"},
            )
        )
    existing_slots = {spec.slot_name for spec in specs}
    if formula_plan is not None:
        for slot_name in list(formula_plan.missing_facts):
            if not slot_name or slot_name in existing_slots:
                continue
            formula_line_item = _line_item_for_formula_slot(
                str(formula_plan.formula_name or ""),
                slot_name,
                question,
            )
            formula_statement = _statement_for_formula_slot(
                str(formula_plan.formula_name or ""),
                slot_name,
                question,
            )
            specs.append(
                EvidenceSpec(
                    spec_id="evidence-spec-" + _short_hash(frame.frame_id, slot_name),
                    slot_name=slot_name,
                    domain="finance",
                    accepted_attributes=_accepted_attributes_for_evidence_slot(slot_name, formula_line_item),
                    source_role=_source_role(binding=binding, source_families=source_families),
                    required_source_families=source_families,
                    target_period=target_period,
                    statement=statement or formula_statement or _statement_for_slot(slot_name),
                    line_item=line_item if _slot_matches_target_line(slot_name, line_item) else formula_line_item or _line_item_for_slot(slot_name),
                    required=True,
                    diagnostics={"source": "finance_task_compiler", "from_formula_missing_fact": True},
                )
            )
            existing_slots.add(slot_name)
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
    if not specs:
        specs.extend(
            _direct_evidence_specs(
                question=question,
                binding=binding,
                target_period=target_period,
                source_families=source_families,
                statement=statement,
            )
        )
    return specs


def _direct_evidence_specs(
    *,
    question: str,
    binding: JsonObject,
    target_period: str | None,
    source_families: list[str],
    statement: str,
) -> list[EvidenceSpec]:
    blueprints = _direct_evidence_blueprints(question)
    specs: list[EvidenceSpec] = []
    for index, blueprint in enumerate(blueprints[:12]):
        slot_name = blueprint["slot_name"]
        line_item = blueprint.get("line_item") or _line_item_for_slot(slot_name)
        specs.append(
            EvidenceSpec(
                spec_id="evidence-spec-" + _short_hash("direct", question, index, slot_name),
                slot_name=slot_name,
                domain="finance",
                accepted_attributes=_ordered_unique([
                    *_string_list(blueprint.get("accepted_attributes")),
                    *_accepted_attributes_for_evidence_slot(slot_name, line_item),
                ]),
                source_role=_source_role(binding=binding, source_families=source_families),
                required_source_families=source_families,
                target_period=target_period,
                statement=statement or _string(blueprint.get("statement")) or _statement_for_slot(slot_name),
                line_item=line_item,
                required=True,
                diagnostics={"source": "finance_task_compiler", "from_direct_question_scaffold": True},
            )
        )
    return specs


def _direct_evidence_blueprints(question: str) -> list[JsonObject]:
    text = _normalized_question(question)
    blueprints: list[JsonObject] = []

    def add(slot_name: str, *, statement: str | None = None, line_item: str | None = None, attributes: list[str] | None = None) -> None:
        if any(item.get("slot_name") == slot_name and item.get("line_item") == line_item for item in blueprints):
            return
        blueprints.append(
            {
                "slot_name": slot_name,
                "statement": statement,
                "line_item": line_item,
                "accepted_attributes": list(attributes or []),
            }
        )

    if "quick ratio" in text:
        add("cash_and_equivalents", statement="balance_sheet", line_item="cash and cash equivalents")
        add("marketable_securities", statement="balance_sheet", line_item="marketable securities")
        add("accounts_receivable", statement="balance_sheet", line_item="accounts receivable")
        add("total_current_liabilities", statement="balance_sheet", line_item="total current liabilities")
    if "working capital" in text:
        add("total_current_assets", statement="balance_sheet", line_item="total current assets")
        add("total_current_liabilities", statement="balance_sheet", line_item="total current liabilities")
    if "capital expenditure" in text or "capex" in text:
        add("capital_expenditures", statement="cash_flow_statement", line_item="capital expenditures")
    if any(marker in text for marker in ("cash flow from operating activities", "cash from operations", "operating cash flow")):
        add("operating_cash_flow", statement="cash_flow_statement", line_item="operating cash flow")
    if "free cash flow" in text or "free cashflow" in text or "fcf" in text:
        add("operating_cash_flow", statement="cash_flow_statement", line_item="operating cash flow")
        add("capital_expenditures", statement="cash_flow_statement", line_item="capital expenditures")
    if "operations, investing, and financing" in text or "operating, investing, and financing" in text:
        add("cash_flow_activity_totals", statement="cash_flow_statement", line_item="net cash provided by operating investing financing activities")
        add("operating_cash_flow", statement="cash_flow_statement", line_item="net cash provided by operating activities")
        add("investing_cash_flow", statement="cash_flow_statement", line_item="net cash provided by investing activities")
        add("financing_cash_flow", statement="cash_flow_statement", line_item="net cash provided by financing activities")
    if "dividend" in text:
        add("dividends_paid", statement="cash_flow_statement", line_item="dividends paid")
    if "cash and cash equivalents" in text or "cash equivalents" in text:
        add("cash_and_equivalents", statement="balance_sheet", line_item="cash and cash equivalents")
        if any(marker in text for marker in ("drop", "dropped", "increase", "increased", "decrease", "decreased", "change", "changed", "between")):
            add("cash_and_equivalents_prior", statement="balance_sheet", line_item="cash and cash equivalents")
            add("cash_and_equivalents_current", statement="balance_sheet", line_item="cash and cash equivalents")
    if "debt" in text and ("increased" in text or "balance sheet" in text or "largest investment" in text):
        add("debt", statement="balance_sheet", line_item="debt")
    if "debt" in text and "balance sheet" in text and any(marker in text for marker in ("increased", "increase", "decreased", "decrease", "changed", "between")):
        add("prior_debt", statement="balance_sheet", line_item="debt")
        add("current_debt", statement="balance_sheet", line_item="debt")
    if "short term investments" in text or "short-term investments" in text:
        add("short_term_investments", statement="balance_sheet", line_item="short-term investments")
    if any(marker in text for marker in ("ppne", "pp and e", "net ppne", "net pp&e", "net property plant and equipment", "property, plant, and equipment")):
        add("property_plant_and_equipment_net", statement="balance_sheet", line_item="property plant and equipment net")
        if any(marker in text for marker in ("grow", "grew", "increase", "increased", "decrease", "decreased", "change", "changed", "between")):
            add("property_plant_and_equipment_net_prior", statement="balance_sheet", line_item="property plant and equipment net")
            add("property_plant_and_equipment_net_current", statement="balance_sheet", line_item="property plant and equipment net")
    if "total assets" in text:
        add("assets", statement="balance_sheet", line_item="total assets")
    if "asset turnover" in text and "fixed asset" not in text and "fixed-asset" not in text:
        add("revenue", statement="income_statement", line_item="revenue")
        add("assets_current", statement="balance_sheet", line_item="total assets")
        add("assets_prior", statement="balance_sheet", line_item="total assets")
    if "total current assets" in text:
        add("total_current_assets", statement="balance_sheet", line_item="total current assets")
    if "total current liabilities" in text:
        add("total_current_liabilities", statement="balance_sheet", line_item="total current liabilities")
    if "accounts payable" in text:
        add("accounts_payable", statement="balance_sheet", line_item="accounts payable")
    if "days payable" in text or "dpo" in text:
        add("accounts_payable_begin", statement="balance_sheet", line_item="accounts payable")
        add("accounts_payable_end", statement="balance_sheet", line_item="accounts payable")
        add("cogs", statement="income_statement", line_item="cost of goods sold")
        if "change in inventory" in text or "change in inventories" in text:
            add("inventory_begin", statement="balance_sheet", line_item="inventories")
            add("inventory_end", statement="balance_sheet", line_item="inventories")
    if "accounts receivable" in text or "net ar" in text:
        add("accounts_receivable", statement="balance_sheet", line_item="accounts receivable")
    if "inventor" in text:
        add("inventory", statement="balance_sheet", line_item="inventories")
    if "cogs" in text or "cost of revenue" in text or "cost of goods sold" in text:
        add("cogs_numerator", statement="income_statement", line_item="cost of goods sold")
    if "net income" in text or "net earnings" in text:
        add("net_income", statement="income_statement", line_item="net income")
    if "operating income" in text:
        add("operating_income", statement="income_statement", line_item="operating income")
    if "adjusted non gaap ebitda" in text or "adjusted ebitda" in text or "non gaap ebitda" in text:
        add("adjusted_ebitda", statement="non_gaap_reconciliation", line_item="adjusted ebitda")
    if "interest coverage" in text:
        add("adjusted_ebit", statement="non_gaap_reconciliation_or_income_statement", line_item="adjusted ebit")
        add("interest_expense", statement="income_statement_or_debt_note", line_item="interest expense")
    if "effective tax rate" in text:
        add("prior_effective_tax_rate", statement="income_tax_note", line_item="effective tax rate")
        add("current_effective_tax_rate", statement="income_tax_note", line_item="effective tax rate")
    if "unadjusted ebitda" in text or (
        "operating income" in text and ("depreciation and amortization" in text or "depreciation & amortization" in text or "d&a" in text)
    ):
        add("operating_income", statement="income_statement", line_item="operating income")
        add("depreciation_and_amortization", statement="cash_flow_statement", line_item="depreciation and amortization")
        if "less capex" in text or "less capital expenditure" in text or "less capital expenditures" in text:
            add("capital_expenditures", statement="cash_flow_statement", line_item="capital expenditures")
    if "revenue" in text or "sales" in text:
        add("revenue", statement="income_statement", line_item="revenue")
    if "restructuring" in text:
        add("restructuring_costs", statement="income_statement", line_item="restructuring costs")
    if "effective tax rate" in text:
        add("effective_tax_rate", statement="income_tax_note", line_item="effective tax rate")
    if "largest liability" in text:
        add("liabilities", statement="balance_sheet", line_item="liabilities")
    if "legal" in text or "litigation" in text:
        add("material_legal_proceedings", statement="legal_proceedings", line_item="material legal proceedings")
    if "debt securities" in text and "registered" in text:
        add("registered_debt_securities", statement="registered_securities", line_item="debt securities registered on national securities exchange")
    if _looks_like_category_metric_rank_question(text):
        add(
            "ranked_category_metric_table",
            statement=_category_rank_statement(question),
            line_item=_category_rank_line_item(question),
        )
    if "major acquisitions" in text or "companies acquired" in text or "acquired by" in text:
        add("acquisitions", statement="business_combinations", line_item="acquisitions")
    if "m and a" in text or "merger and acquisition" in text:
        add("acquisitions", statement="business_combinations", line_item="acquisitions")
    if "8k filing" in text or "8 k filing" in text or "8-k filing" in text:
        add("filing_event_summary", statement="form_8k", line_item="filing event")
    if "geographies" in text or "geographic region" in text or "primarily operates in" in text:
        add("operating_geographies", statement="business", line_item="geographic areas")
    if "products and services" in text or "product category" in text or "product categories" in text or "service category" in text or "service categories" in text:
        add("products_and_services", statement="business", line_item="products and services")
    if "primary customers" in text or "customer concentration" in text:
        add("customers", statement="business", line_item="customers")
    if "retain card members" in text or "card members" in text or "customer retention" in text:
        add("customer_retention", statement="md&a_or_business", line_item="customer retention")
    if "industry" in text:
        add("industry", statement="business", line_item="industry")
    if "cyclicality" in text or "cyclical" in text:
        add("business_cyclicality", statement="risk_factors_or_md&a", line_item="cyclicality")
    if "number of stores" in text or "stores between" in text:
        add("store_count", statement="business_or_properties", line_item="stores")
        if any(marker in text for marker in ("change", "changed", "increase", "decrease", "between")):
            add("store_count_prior", statement="business_or_properties", line_item="stores")
            add("store_count_current", statement="business_or_properties", line_item="stores")
    if "production rate" in text:
        add("production_rates", statement="md&a_or_business_outlook", line_item="production rates")
    if "ceo" in text or "board member" in text or "nominees" in text:
        add("governance_disclosure", statement="proxy_statement", line_item="directors and executive officers")
    if "shareholder vote" in text or "shareholder proposal" in text:
        add("shareholder_vote_results", statement="proxy_or_8k_voting_results", line_item="shareholder vote")
    if "high growth company" in text or "growth company" in text:
        add("revenue", statement="income_statement", line_item="revenue")
        add("net_income", statement="income_statement", line_item="net income")
    if "adjusted eps" in text or "guidance" in text:
        add("guidance", statement="earnings_release_or_md&a", line_item="guidance")
    if "discontinued operation" in text or "spin off" in text or "spinning off" in text or "separation" in text or "kenvue" in text:
        add("separation_or_discontinued_operation", statement="business_combinations_or_subsequent_events", line_item="separation or discontinued operation")
    if "gain" in text and ("separation" in text or "spin off" in text or "spinoff" in text):
        add("gain_on_separation", statement="business_combinations_or_subsequent_events", line_item="gain on separation")
    if "cash proceeds" in text or "proceeds" in text:
        add("cash_proceeds", statement="cash_flow_statement_or_transaction_note", line_item="cash proceeds")
    if "business segments" in text or "reporting segment" in text or "segment" in text or "ebitdar" in text or "region had" in text:
        add("segment_results", statement="segment_note", line_item="segment revenue income")
    if re.search(r"\bvar\b", text) or "value at risk" in text:
        add("market_risk_var", statement="market_risk_disclosures", line_item="value at risk")
    if "bankrupted" in text or "liquidated" in text or "liquidation" in text:
        add("assets", statement="balance_sheet", line_item="total assets")
        add("liabilities", statement="balance_sheet", line_item="total liabilities")
        add("shares_outstanding", statement="equity_or_cover_page", line_item="shares outstanding")
    if "revolving credit" in text or "credit agreement" in text:
        add("credit_facility", statement="debt_or_liquidity_note", line_item="revolving credit agreement")
    if "stock repurchases" in text or "share repurchases" in text:
        add("share_repurchases", statement="equity_note_or_cash_flow_statement", line_item="share repurchases")
        if "what percent" in text or "what percentage" in text:
            add("component_amount", statement="equity_note_or_cash_flow_statement", line_item="share repurchases")
            add("total_amount", statement="equity_note_or_cash_flow_statement", line_item="share repurchases")
    if "derivative instruments" in text or "notional value" in text:
        add("derivative_instruments", statement="derivatives_note_or_market_risk", line_item="derivative instruments notional value")
    if "retirees" in text or "pension" in text or "postretirement" in text:
        add("pension_postretirement_payments", statement="pension_and_postretirement_note", line_item="expected benefit payments")
    return blueprints


def _transform_specs(*, formula_plan: FinanceFormulaPlan, frame_missing_slots: list[str]) -> list[TransformSpec]:
    name = str(formula_plan.formula_name or "")
    if not name:
        return []
    if name == "disclosure_lookup":
        return []
    if name == "margin":
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        numerator_slot = _margin_numerator_slot(required_slots)
        denominator_slot = "revenue_denominator" if "revenue_denominator" in required_slots else "denominator"
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), str(payload.get("expression") or "")),
                domain="finance",
                name="margin",
                required_slots=required_slots,
                expression=_string(payload.get("expression")) or f"{numerator_slot} / {denominator_slot}",
                output_unit=_string(payload.get("unit")) or "percent",
                output_attribute="margin",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
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
    if name == "operating_cash_flow_ratio":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "ocf_current_liabilities"),
                domain="finance",
                name="operating_cash_flow_ratio",
                required_slots=["operating_cash_flow", "total_current_liabilities"],
                expression="operating_cash_flow / total_current_liabilities",
                output_unit="ratio",
                output_attribute="operating_cash_flow_ratio",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "dpo":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "average_ap_cogs"),
                domain="finance",
                name="dpo",
                required_slots=["accounts_payable_begin", "accounts_payable_end", "cogs", "fiscal_days"],
                expression="fiscal_days * ((accounts_payable_begin + accounts_payable_end) / 2) / cogs",
                output_unit="days",
                output_attribute="days_payable_outstanding",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "dpo_inventory_adjusted":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "average_ap_cogs_inventory_change"),
                domain="finance",
                name="dpo_inventory_adjusted",
                required_slots=[
                    "accounts_payable_begin",
                    "accounts_payable_end",
                    "cogs",
                    "inventory_begin",
                    "inventory_end",
                    "fiscal_days",
                ],
                expression=(
                    "fiscal_days * ((accounts_payable_begin + accounts_payable_end) / 2) / "
                    "(cogs + (inventory_end - inventory_begin))"
                ),
                output_unit="days",
                output_attribute="days_payable_outstanding",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "average_capex_to_revenue":
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        expression = _string(payload.get("expression")) or _string(formula_plan.diagnostics.get("expression"))
        if not expression:
            years = _years_from_period_slots(required_slots)
            terms = [f"(capital_expenditures_{year} / revenue_{year})" for year in years]
            expression = f"({' + '.join(terms)}) / {len(terms)}" if terms else "average(capital_expenditures / revenue)"
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), expression),
                domain="finance",
                name="average_capex_to_revenue",
                required_slots=required_slots,
                expression=expression,
                output_unit="percent",
                output_attribute="average_capex_to_revenue",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "average_cogs_to_revenue":
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        expression = _string(payload.get("expression")) or _string(formula_plan.diagnostics.get("expression"))
        if not expression:
            years = _years_from_period_slots(required_slots)
            terms = [f"(cogs_{year} / revenue_{year})" for year in years]
            expression = f"({' + '.join(terms)}) / {len(terms)}" if terms else "average(cogs / revenue)"
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), expression),
                domain="finance",
                name="average_cogs_to_revenue",
                required_slots=required_slots,
                expression=expression,
                output_unit="percent",
                output_attribute="average_cogs_to_revenue",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name in {"margin_profile_change", "margin_consistency_range"}:
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        expression = _string(payload.get("expression")) or _string(formula_plan.diagnostics.get("expression"))
        if not expression:
            expression = "max(period_margins) - min(period_margins)" if name == "margin_consistency_range" else "ending_margin - beginning_margin"
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), expression),
                domain="finance",
                name=name,
                required_slots=required_slots,
                expression=expression,
                output_unit="percent",
                output_attribute=name,
                diagnostics={
                    "source": "finance_task_compiler",
                    "formula_status": formula_plan.status,
                    "semantic_decision_policy": "LLM decides margin usefulness, improvement, stability, or drivers from evidence and explicit question criteria.",
                },
            )
        ]
    if name == "metric_lookup":
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        output_attribute = required_slots[0] if len(required_slots) == 1 else "metric_value"
        expression = _string(payload.get("expression")) or None
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), expression or ""),
                domain="finance",
                name="metric_lookup",
                required_slots=required_slots,
                expression=expression,
                output_unit=_string(payload.get("unit")) or "metric_value",
                output_attribute=output_attribute,
                diagnostics={
                    "source": "finance_task_compiler",
                    "formula_status": formula_plan.status,
                    "semantic_decision_policy": (
                        "LLM verifies statement, period, unit, sign convention, and explicit absence conditions from cited evidence."
                    ),
                },
            )
        ]
    if name == "category_metric_rank":
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots)
        rank_direction = _string(formula_plan.diagnostics.get("rank_direction")) or "max"
        expression = _string(payload.get("expression"))
        if not expression:
            expression = "min(category_metric_values)" if rank_direction == "min" else "max(category_metric_values)"
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), expression),
                domain="finance",
                name="category_metric_rank",
                required_slots=required_slots,
                expression=expression,
                output_unit=_string(payload.get("unit")) or "metric_value",
                output_attribute="category_metric_rank_value",
                diagnostics={
                    "source": "finance_task_compiler",
                    "formula_status": formula_plan.status,
                    "rank_direction": rank_direction,
                    "semantic_decision_policy": (
                        "LLM maps the computed extreme numeric value to the cited category row and explains the final answer."
                    ),
                },
            )
        ]
    if name == "effective_tax_rate_change":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "prior_current"),
                domain="finance",
                name="effective_tax_rate_change",
                required_slots=["prior_effective_tax_rate", "current_effective_tax_rate"],
                expression="(current_effective_tax_rate - prior_effective_tax_rate) * 100",
                output_unit="percentage_points",
                output_attribute="effective_tax_rate_change",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "interest_coverage_ratio":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "ebit_interest"),
                domain="finance",
                name="interest_coverage_ratio",
                required_slots=["adjusted_ebit_or_ebit", "interest_expense"],
                expression="adjusted_ebit_or_ebit / interest_expense",
                output_unit="x",
                output_attribute="interest_coverage_ratio",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "unadjusted_ebitda":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "operating_income_da"),
                domain="finance",
                name="unadjusted_ebitda",
                required_slots=["operating_income", "depreciation_and_amortization"],
                expression="operating_income + depreciation_and_amortization",
                output_unit="currency",
                output_attribute="unadjusted_ebitda",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "unadjusted_ebitda_less_capex":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "operating_income_da_capex"),
                domain="finance",
                name="unadjusted_ebitda_less_capex",
                required_slots=["operating_income", "depreciation_and_amortization", "capital_expenditures"],
                expression="operating_income + depreciation_and_amortization - capital_expenditures",
                output_unit="currency",
                output_attribute="unadjusted_ebitda_less_capex",
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    simple_transforms: dict[str, tuple[list[str], str, str, str]] = {
        "quick_ratio": (
            ["cash_and_equivalents", "marketable_securities", "accounts_receivable", "total_current_liabilities"],
            "(cash_and_equivalents + marketable_securities + accounts_receivable) / total_current_liabilities",
            "ratio",
            "quick_ratio",
        ),
        "working_capital_ratio": (
            ["total_current_assets", "total_current_liabilities"],
            "total_current_assets / total_current_liabilities",
            "ratio",
            "working_capital_ratio",
        ),
        "net_working_capital": (
            ["total_current_assets", "total_current_liabilities"],
            "total_current_assets - total_current_liabilities",
            "currency",
            "net_working_capital",
        ),
        "return_on_assets": (
            ["net_income", "assets_current", "assets_prior"],
            "net_income / ((assets_current + assets_prior) / 2)",
            "percent",
            "return_on_assets",
        ),
        "free_cash_flow": (
            ["operating_cash_flow", "capital_expenditures"],
            "operating_cash_flow - capital_expenditures",
            "currency",
            "free_cash_flow",
        ),
        "inventory_turnover": (
            ["cogs", "inventory_begin", "inventory_end"],
            "cogs / ((inventory_begin + inventory_end) / 2)",
            "x",
            "inventory_turnover",
        ),
        "dividend_payout_ratio": (
            ["dividends_paid", "net_income"],
            "dividends_paid / net_income",
            "ratio",
            "dividend_payout_ratio",
        ),
        "retention_ratio": (
            ["dividends_paid", "net_income"],
            "1 - dividends_paid / net_income",
            "ratio",
            "retention_ratio",
        ),
        "asset_turnover": (
            ["revenue", "assets_current", "assets_prior"],
            "revenue / ((assets_current + assets_prior) / 2)",
            "x",
            "asset_turnover",
        ),
        "liquidation_value_per_share": (
            ["assets", "liabilities", "shares_outstanding"],
            "(assets - liabilities) / shares_outstanding",
            "currency_per_share",
            "liquidation_value_per_share",
        ),
        "debt_change": (
            ["prior_debt", "current_debt"],
            "current_debt - prior_debt",
            "currency",
            "debt_change",
        ),
        "component_percent_of_total": (
            ["component_amount", "total_amount"],
            "component_amount / total_amount",
            "percent",
            "component_percent_of_total",
        ),
        "cash_and_equivalents_change": (
            ["cash_and_equivalents_prior", "cash_and_equivalents_current"],
            "cash_and_equivalents_current - cash_and_equivalents_prior",
            "currency",
            "cash_and_equivalents_change",
        ),
        "market_risk_var_change": (
            ["market_risk_var_prior", "market_risk_var_current"],
            "market_risk_var_current - market_risk_var_prior",
            "currency",
            "market_risk_var_change",
        ),
        "percent_of_sales_change": (
            ["prior_percent_of_sales", "current_percent_of_sales"],
            "current_percent_of_sales - prior_percent_of_sales",
            "percent",
            "percent_of_sales_change",
        ),
        "property_plant_and_equipment_change": (
            ["property_plant_and_equipment_net_prior", "property_plant_and_equipment_net_current"],
            "property_plant_and_equipment_net_current - property_plant_and_equipment_net_prior",
            "currency",
            "property_plant_and_equipment_change",
        ),
        "store_count_change": (
            ["store_count_prior", "store_count_current"],
            "store_count_current - store_count_prior",
            "count",
            "store_count_change",
        ),
        "cash_flow_activity_comparison": (
            ["operating_cash_flow", "investing_cash_flow", "financing_cash_flow"],
            "max(operating_cash_flow, investing_cash_flow, financing_cash_flow)",
            "currency",
            "cash_flow_activity_comparison",
        ),
    }
    if name in simple_transforms:
        default_slots, default_expression, default_unit, output_attribute = simple_transforms[name]
        payload = formula_plan.payload if isinstance(formula_plan.payload, dict) else {}
        variables = payload.get("variables") if isinstance(payload.get("variables"), dict) else {}
        required_slots = list(variables.keys()) if variables else list(formula_plan.missing_facts or frame_missing_slots or default_slots)
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, ",".join(required_slots), str(payload.get("expression") or default_expression)),
                domain="finance",
                name=name,
                required_slots=required_slots,
                expression=_string(payload.get("expression")) or default_expression,
                output_unit=_string(payload.get("unit")) or default_unit,
                output_attribute=output_attribute,
                diagnostics={"source": "finance_task_compiler", "formula_status": formula_plan.status},
            )
        ]
    if name == "yoy_growth":
        return [
            TransformSpec(
                spec_id="transform-spec-" + _short_hash(name, "prior_current"),
                domain="finance",
                name="yoy_growth",
                required_slots=["prior_period_value", "current_period_value"],
                expression="current_period_value / prior_period_value - 1",
                output_unit="percent",
                output_attribute="yoy_growth",
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


def _years_from_period_slots(slots: list[str]) -> list[int]:
    years: list[int] = []
    seen: set[int] = set()
    for slot in slots:
        match = re.search(r"_(?P<year>19\d{2}|20\d{2})$", slot)
        if not match:
            continue
        year = int(match.group("year"))
        if year in seen:
            continue
        seen.add(year)
        years.append(year)
    return sorted(years)


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


def _statement_for_formula_slot(formula_name: str, slot_name: str, question: str) -> str | None:
    if formula_name == "disclosure_lookup":
        spec = _disclosure_lookup_compiler_spec(question)
        if spec and spec.get("slot_name") == slot_name:
            return _string(spec.get("statement"))
        return _statement_for_slot(slot_name)
    if formula_name == "metric_lookup":
        return _statement_for_slot(slot_name)
    if formula_name == "category_metric_rank" and slot_name == "ranked_category_metric_table":
        return _category_rank_statement(question)
    if formula_name == "yoy_growth" and slot_name in {"prior_period_value", "current_period_value"}:
        line_item = _yoy_growth_line_item(question)
        if line_item in {"revenue", "net sales", "net revenues", "total revenues", "operating income", "net income", "ebitda"}:
            return "income_statement"
    if formula_name == "margin" and slot_name in {
        "margin_numerator",
        "cogs_numerator",
        "gross_profit_numerator",
        "operating_income_numerator",
        "net_income_numerator",
        "ebitda_numerator",
        "revenue_denominator",
    }:
        return "income_statement"
    return None


def _statement_for_slot(slot_name: str) -> str | None:
    if re.fullmatch(r"capital_expenditures_(?:19|20)\d{2}", slot_name):
        return "cash_flow_statement"
    if re.fullmatch(r"cogs_(?:19|20)\d{2}", slot_name):
        return "income_statement"
    if re.fullmatch(r"(?:gross_profit|operating_income)_(?:19|20)\d{2}", slot_name):
        return "income_statement"
    if re.fullmatch(r"revenue_(?:19|20)\d{2}", slot_name):
        return "income_statement"
    if slot_name in {"component_amount", "total_amount", "share_repurchases"}:
        return "equity_note_or_cash_flow_statement"
    if slot_name == "shares_outstanding":
        return "equity_or_cover_page"
    if slot_name in {
        "capital_expenditures",
        "operating_cash_flow",
        "investing_cash_flow",
        "financing_cash_flow",
        "dividends_paid",
        "cash_flow_activity_totals",
    }:
        return "cash_flow_statement"
    if slot_name == "depreciation_and_amortization":
        return "cash_flow_statement"
    if slot_name in {"prior_effective_tax_rate", "current_effective_tax_rate"}:
        return "income_tax_note"
    if slot_name in {
        "assets",
        "assets_current",
        "assets_prior",
        "liabilities",
        "property_plant_and_equipment_net",
        "property_plant_and_equipment_net_current",
        "property_plant_and_equipment_net_prior",
        "total_current_liabilities",
        "total_current_assets",
        "cash_and_equivalents",
        "cash_and_equivalents_prior",
        "cash_and_equivalents_current",
        "marketable_securities",
        "accounts_receivable",
        "accounts_payable",
        "accounts_payable_begin",
        "accounts_payable_end",
        "inventory",
        "inventory_begin",
        "inventory_end",
        "debt",
        "prior_debt",
        "current_debt",
        "cash",
    }:
        return "balance_sheet"
    if slot_name in {"store_count", "store_count_prior", "store_count_current"}:
        return "business_or_properties"
    if slot_name == "ranked_category_metric_table":
        return "md&a_or_note_table"
    if slot_name in {"gain_on_separation", "cash_proceeds"}:
        return "cash_flow_statement_or_transaction_note"
    if slot_name == "separation_payment":
        return "transaction_or_separation_note"
    if slot_name == "market_risk_var":
        return "market_risk_disclosures"
    if slot_name in {"market_risk_var_prior", "market_risk_var_current"}:
        return "market_risk_disclosures"
    if slot_name in {"prior_percent_of_sales", "current_percent_of_sales"}:
        return "md&a_or_income_statement"
    if slot_name == "organic_sales_change":
        return "md&a_or_segment_note"
    if slot_name == "credit_facility":
        return "debt_or_liquidity_note"
    if slot_name == "pension_postretirement_payments":
        return "pension_and_postretirement_note"
    disclosure_statements = {
        "registered_debt_securities": "registered_securities",
        "dividend_distribution_history": "dividend_disclosure",
        "filing_event_summary": "form_8k",
        "acquisitions": "business_combinations",
        "industry": "business",
        "products_and_services": "business",
        "product_revenue_concentration": "business_or_segment_note",
        "customers": "business",
        "operating_geographies": "business",
        "customer_retention": "md&a_or_business",
        "business_cyclicality": "risk_factors_or_md&a",
        "production_rates": "md&a_or_business_outlook",
        "material_legal_proceedings": "legal_proceedings",
        "dividends_disclosure": "dividend_disclosure_or_cash_flow_statement",
        "governance_disclosure": "proxy_statement",
        "shareholder_vote_results": "proxy_or_8k_voting_results",
        "guidance": "earnings_release_or_md&a",
        "guidance_change": "earnings_release_or_md&a",
        "separation_or_discontinued_operation": "business_combinations_or_subsequent_events",
        "nonrecurring_events": "md&a_or_income_statement_note",
        "revenue_driver_discussion": "md&a",
        "inventory_driver_discussion": "md&a_or_inventory_note",
        "expense_driver_discussion": "md&a_or_income_statement",
        "geographic_sales_growth": "md&a_or_segment_note",
        "expense_ratio_change": "md&a_or_income_statement",
        "growth_profile_evidence": "income_statement_or_md&a",
        "restructuring_liability": "restructuring_note",
    }
    if slot_name in disclosure_statements:
        return disclosure_statements[slot_name]
    if slot_name in {
        "revenue",
        "net_income",
        "operating_income",
        "cogs",
        "cogs_numerator",
        "gross_profit_numerator",
        "operating_income_numerator",
        "net_income_numerator",
        "ebitda_numerator",
        "revenue_denominator",
        "restructuring_costs",
        "ebitda_or_ebitda_components",
        "adjusted_ebit_or_ebit",
        "interest_expense",
    }:
        return "income_statement"
    return None


def _line_item_for_formula_slot(formula_name: str, slot_name: str, question: str) -> str | None:
    if formula_name == "disclosure_lookup":
        spec = _disclosure_lookup_compiler_spec(question)
        if spec and spec.get("slot_name") == slot_name:
            return _string(spec.get("line_item"))
        return _line_item_for_slot(slot_name)
    if formula_name == "metric_lookup":
        return _line_item_for_slot(slot_name)
    if formula_name == "category_metric_rank" and slot_name == "ranked_category_metric_table":
        return _category_rank_line_item(question)
    if formula_name == "percent_of_sales_change" and slot_name in {"prior_percent_of_sales", "current_percent_of_sales"}:
        return _percent_of_sales_line_item(question)
    if formula_name == "yoy_growth" and slot_name in {"prior_period_value", "current_period_value"}:
        return _yoy_growth_line_item(question)
    if formula_name == "margin":
        return _margin_line_item(slot_name, question)
    return None


def _line_item_for_slot(slot_name: str) -> str | None:
    if re.fullmatch(r"capital_expenditures_(?:19|20)\d{2}", slot_name):
        return "capital expenditures"
    if re.fullmatch(r"cogs_(?:19|20)\d{2}", slot_name):
        return "cost of goods sold"
    if re.fullmatch(r"gross_profit_(?:19|20)\d{2}", slot_name):
        return "gross profit"
    if re.fullmatch(r"operating_income_(?:19|20)\d{2}", slot_name):
        return "operating income"
    if re.fullmatch(r"revenue_(?:19|20)\d{2}", slot_name):
        return "revenue"
    mapping = {
        "capital_expenditures": "capital expenditures",
        "operating_cash_flow": "operating cash flow",
        "investing_cash_flow": "investing cash flow",
        "financing_cash_flow": "financing cash flow",
        "total_current_liabilities": "total current liabilities",
        "total_current_assets": "total current assets",
        "cash_and_equivalents": "cash and cash equivalents",
        "cash_and_equivalents_prior": "cash and cash equivalents",
        "cash_and_equivalents_current": "cash and cash equivalents",
        "marketable_securities": "marketable securities",
        "accounts_receivable": "accounts receivable",
        "accounts_payable": "accounts payable",
        "accounts_payable_begin": "accounts payable",
        "accounts_payable_end": "accounts payable",
        "inventory": "inventories",
        "inventory_begin": "inventories",
        "inventory_end": "inventories",
        "property_plant_and_equipment_net": "property plant and equipment net",
        "property_plant_and_equipment_net_current": "property plant and equipment net",
        "property_plant_and_equipment_net_prior": "property plant and equipment net",
        "assets": "assets",
        "assets_current": "total assets",
        "assets_prior": "total assets",
        "liabilities": "liabilities",
        "shares_outstanding": "shares outstanding",
        "prior_debt": "debt",
        "current_debt": "debt",
        "component_amount": "component amount",
        "total_amount": "total amount",
        "share_repurchases": "share repurchases",
        "revenue": "revenue",
        "operating_income": "operating income",
        "depreciation_and_amortization": "depreciation and amortization",
        "prior_effective_tax_rate": "effective tax rate",
        "current_effective_tax_rate": "effective tax rate",
        "adjusted_ebit_or_ebit": "adjusted ebit",
        "net_income": "net income",
        "interest_expense": "interest expense",
        "cogs": "cost of goods sold",
        "cogs_numerator": "cost of goods sold",
        "gross_profit_numerator": "gross profit",
        "operating_income_numerator": "operating income",
        "net_income_numerator": "net income",
        "ebitda_numerator": "ebitda",
        "revenue_denominator": "revenue",
        "dividends_paid": "dividends paid",
        "cash_flow_activity_totals": "net cash provided by operating investing financing activities",
        "restructuring_costs": "restructuring costs",
        "gain_on_separation": "gain on separation",
        "cash_proceeds": "cash proceeds",
        "separation_payment": "expected separation payment",
        "market_risk_var": "value at risk",
        "market_risk_var_prior": "value at risk",
        "market_risk_var_current": "value at risk",
        "prior_percent_of_sales": "metric as percent of sales",
        "current_percent_of_sales": "metric as percent of sales",
        "organic_sales_change": "organic sales change",
        "credit_facility": "revolving credit agreement",
        "pension_postretirement_payments": "expected benefit payments",
        "registered_debt_securities": "debt securities registered on national securities exchange",
        "dividend_distribution_history": "dividend distribution history",
        "filing_event_summary": "filing event",
        "acquisitions": "acquisitions",
        "industry": "industry",
        "products_and_services": "products and services",
        "product_revenue_concentration": "product category revenue concentration",
        "customers": "customers",
        "operating_geographies": "geographic areas",
        "customer_retention": "customer retention",
        "business_cyclicality": "cyclicality",
        "production_rates": "production rates",
        "material_legal_proceedings": "material legal proceedings",
        "dividends_disclosure": "dividends to common shareholders",
        "governance_disclosure": "directors and executive officers",
        "shareholder_vote_results": "shareholder vote",
        "guidance": "guidance",
        "guidance_change": "guidance change",
        "separation_or_discontinued_operation": "separation or discontinued operation",
        "nonrecurring_events": "nonrecurring events",
        "revenue_driver_discussion": "revenue drivers",
        "inventory_driver_discussion": "inventory balance drivers",
        "expense_driver_discussion": "expense drivers",
        "geographic_sales_growth": "geographic sales growth",
        "expense_ratio_change": "expense or earnings as percent of sales",
        "growth_profile_evidence": "growth profile evidence",
        "restructuring_liability": "restructuring liability",
        "store_count": "stores",
        "store_count_prior": "stores",
        "store_count_current": "stores",
        "ranked_category_metric_table": "ranked category metric table",
    }
    return mapping.get(slot_name)


def _category_rank_statement(question: str) -> str | None:
    text = _normalized_question(question)
    if "derivative instrument" in text or "notional value" in text:
        return "derivatives_note_or_market_risk"
    if "short term investments" in text or "short-term investments" in text or "type of debt" in text:
        return "investment_or_fair_value_note"
    if "liability" in text or "liabilities" in text:
        return "balance_sheet"
    if any(marker in text for marker in ("segment", "region", "ebitdar", "topline", "product category", "service category")):
        return "segment_note"
    return "md&a_or_note_table"


def _category_rank_line_item(question: str) -> str:
    text = _normalized_question(question)
    if "derivative instrument" in text or "notional value" in text:
        return "derivative instruments notional value"
    if "short term investments" in text or "short-term investments" in text or "type of debt" in text:
        return "short-term investments by debt security type"
    if "liability" in text or "liabilities" in text:
        return "liabilities"
    if "product category" in text or "service category" in text:
        return "product category revenue"
    if "ebitdar" in text:
        return "regional ebitdar contribution"
    if "net income" in text:
        return "segment net income"
    if ("geographic" in text or "region" in text) and ("revenue" in text or "sales" in text):
        return "geographic revenue"
    if "revenue" in text or "sales" in text or "topline" in text:
        return "segment revenue"
    return "ranked category metric table"


def _percent_of_sales_line_item(question: str) -> str:
    text = _normalized_question(question)
    denominator = "net sales" if "net sales" in text else "sales"
    if "net earnings" in text:
        return f"net earnings as percent of {denominator}"
    if "net income" in text:
        return f"net income as percent of {denominator}"
    if "wages expense" in text or "wage expense" in text:
        return f"wages expense as percent of {denominator}"
    if "sg&a" in text or "selling general" in text:
        return f"sg&a expense as percent of {denominator}"
    return f"metric as percent of {denominator}"


def _looks_like_category_metric_rank_question(text: str) -> bool:
    rank_markers = (
        "highest",
        "lowest",
        "largest",
        "smallest",
        "best",
        "worst",
        "most",
        "least",
        "dragged down",
        "biggest drop",
        "largest drop",
        "largest decline",
        "steepest decline",
        "proportionally increase",
        "proportionally increased",
        "performed the best",
    )
    if not any(marker in text for marker in rank_markers):
        return False
    if "registered to trade" in text or "registered on a national securities exchange" in text:
        return False
    category_markers = (
        "segment",
        "region",
        "geographic",
        "product category",
        "service category",
        "category",
        "among",
        "derivative instrument",
        "notional value",
        "short term investments",
        "short-term investments",
        "type of debt",
        "liability",
        "liabilities",
        "topline",
        "ebitdar",
    )
    return any(marker in text for marker in category_markers)


def _disclosure_lookup_compiler_spec(question: str) -> JsonObject | None:
    text = _normalized_question(question)
    if "debt securities" in text and ("registered to trade" in text or "national securities exchange" in text):
        return {"slot_name": "registered_debt_securities", "statement": "registered_securities", "line_item": "debt securities registered on national securities exchange"}
    if "stable trend of dividend" in text or "dividend distribution" in text:
        return {"slot_name": "dividend_distribution_history", "statement": "dividend_disclosure", "line_item": "dividend distribution history"}
    if "8k filing" in text or "8 k filing" in text or "8-k filing" in text or "key agenda" in text:
        return {"slot_name": "filing_event_summary", "statement": "form_8k", "line_item": "filing event"}
    if "major acquisitions" in text or "companies acquired" in text or "main companies acquired" in text:
        return {"slot_name": "acquisitions", "statement": "business_combinations", "line_item": "acquisitions"}
    if "what industry" in text or ("primarily operate in" in text and "geograph" not in text):
        return {"slot_name": "industry", "statement": "business", "line_item": "industry"}
    if "products and services" in text or "major products" in text or "product categories" in text or "service categories" in text:
        if "more than" in text and "revenue" in text:
            return {"slot_name": "product_revenue_concentration", "statement": "business_or_segment_note", "line_item": "product category revenue concentration"}
        return {"slot_name": "products_and_services", "statement": "business", "line_item": "products and services"}
    if "customer concentration" in text or "primary customers" in text:
        return {"slot_name": "customers", "statement": "business", "line_item": "customers"}
    if "geographies" in text or "geographic" in text or "primarily operates in" in text:
        return {"slot_name": "operating_geographies", "statement": "business", "line_item": "geographic areas"}
    if "retain card members" in text or "card members" in text or "customer retention" in text:
        return {"slot_name": "customer_retention", "statement": "md&a_or_business", "line_item": "customer retention"}
    if "cyclicality" in text or "cyclical" in text:
        return {"slot_name": "business_cyclicality", "statement": "risk_factors_or_md&a", "line_item": "cyclicality"}
    if "production rate" in text:
        return {"slot_name": "production_rates", "statement": "md&a_or_business_outlook", "line_item": "production rates"}
    if "legal battle" in text or "legal proceedings" in text or "litigation" in text:
        return {"slot_name": "material_legal_proceedings", "statement": "legal_proceedings", "line_item": "material legal proceedings"}
    if "paid dividends" in text or "dividends to common shareholders" in text:
        return {"slot_name": "dividends_disclosure", "statement": "dividend_disclosure_or_cash_flow_statement", "line_item": "dividends to common shareholders"}
    if "previous ceo experience" in text or "new ceo" in text or "board member" in text or "nominees" in text:
        if "votes against" in text:
            return {"slot_name": "shareholder_vote_results", "statement": "proxy_or_8k_voting_results", "line_item": "shareholder vote"}
        return {"slot_name": "governance_disclosure", "statement": "proxy_statement", "line_item": "directors and executive officers"}
    if "shareholder vote" in text or "shareholder proposal" in text or "agm" in text:
        return {"slot_name": "shareholder_vote_results", "statement": "proxy_or_8k_voting_results", "line_item": "shareholder vote"}
    if "guidance" in text or "adjusted eps expected" in text:
        return {"slot_name": "guidance_change" if "percentage points" in text else "guidance", "statement": "earnings_release_or_md&a", "line_item": "guidance change" if "percentage points" in text else "guidance"}
    if "discontinued operation" in text or "spinning off" in text or "spin off" in text or "spin-off" in text or "upjohn" in text:
        return {"slot_name": "separation_or_discontinued_operation", "statement": "business_combinations_or_subsequent_events", "line_item": "separation or discontinued operation"}
    if "standard business operations" in text or "substantially increased net income" in text:
        return {"slot_name": "nonrecurring_events", "statement": "md&a_or_income_statement_note", "line_item": "nonrecurring events"}
    if "what drove" in text or "why did" in text or "why " in text:
        if "inventory" in text or "inventories" in text:
            return {"slot_name": "inventory_driver_discussion", "statement": "md&a_or_inventory_note", "line_item": "inventory balance drivers"}
        if "sg&a" in text or "selling general" in text or "expense" in text or "wages" in text:
            return {"slot_name": "expense_driver_discussion", "statement": "md&a_or_income_statement", "line_item": "expense drivers"}
        return {"slot_name": "revenue_driver_discussion", "statement": "md&a", "line_item": "revenue drivers"}
    if "us sales growth" in text or "international sales growth" in text or "sales growth compare" in text:
        return {"slot_name": "geographic_sales_growth", "statement": "md&a_or_segment_note", "line_item": "geographic sales growth"}
    if "as a percent of sales" in text or "as a percent of net sales" in text:
        return {"slot_name": "expense_ratio_change", "statement": "md&a_or_income_statement", "line_item": "expense or earnings as percent of sales"}
    if "high growth company" in text:
        return {"slot_name": "growth_profile_evidence", "statement": "income_statement_or_md&a", "line_item": "growth profile evidence"}
    if "restructuring liability" in text:
        return {"slot_name": "restructuring_liability", "statement": "restructuring_note", "line_item": "restructuring liability"}
    return None


def _margin_line_item(slot_name: str, question: str) -> str | None:
    if slot_name == "margin_numerator":
        resolved = _margin_numerator_slot([], question=question)
        if resolved == "margin_numerator":
            return None
        return _margin_line_item(resolved, question)
    mapping = {
        "cogs_numerator": "cost of goods sold",
        "gross_profit_numerator": "gross profit",
        "operating_income_numerator": "operating income",
        "net_income_numerator": "net income",
        "ebitda_numerator": "ebitda",
        "revenue_denominator": "revenue",
    }
    return mapping.get(slot_name)


def _margin_numerator_slot(required_slots: list[str], *, question: str = "") -> str:
    for slot_name in required_slots:
        if slot_name.endswith("_numerator") or slot_name == "margin_numerator":
            return slot_name
    text = _normalized_question(question)
    if "cogs" in text or "cost of goods sold" in text or "cost of revenue" in text:
        return "cogs_numerator"
    if "gross margin" in text or "gross profit margin" in text:
        return "gross_profit_numerator"
    if "operating margin" in text or "operating income" in text:
        return "operating_income_numerator"
    if "net profit margin" in text or "net margin" in text or "net income" in text:
        return "net_income_numerator"
    if "ebitda" in text:
        return "ebitda_numerator"
    return "margin_numerator"


def _accepted_attributes_for_evidence_slot(slot_name: str, line_item: str | None = None) -> list[str]:
    if re.fullmatch(r"capital_expenditures_(?:19|20)\d{2}", slot_name):
        values = ["capital expenditures", "capex", "purchases of property plant and equipment"]
        if line_item:
            values.insert(0, line_item)
        return _ordered_unique(values)
    if re.fullmatch(r"cogs_(?:19|20)\d{2}", slot_name):
        values = ["cost of goods sold", "cost of revenue", "cost of sales", "cogs"]
        if line_item:
            values.insert(0, line_item)
        return _ordered_unique(values)
    if re.fullmatch(r"gross_profit_(?:19|20)\d{2}", slot_name):
        values = ["gross profit", "gross income"]
        if line_item:
            values.insert(0, line_item)
        return _ordered_unique(values)
    if re.fullmatch(r"operating_income_(?:19|20)\d{2}", slot_name):
        values = ["operating income", "income from operations", "operating profit"]
        if line_item:
            values.insert(0, line_item)
        return _ordered_unique(values)
    if re.fullmatch(r"revenue_(?:19|20)\d{2}", slot_name):
        values = ["revenue", "revenues", "net sales", "net revenues", "sales"]
        if line_item:
            values.insert(0, line_item)
        return _ordered_unique(values)
    mapping = {
        "capital_expenditures": ["capital expenditures", "capex", "purchases of property plant and equipment"],
        "operating_cash_flow": ["operating cash flow", "cash flow from operations", "net cash provided by operating activities"],
        "investing_cash_flow": [
            "investing cash flow",
            "cash flow from investing activities",
            "net cash provided by investing activities",
            "net cash used in investing activities",
        ],
        "financing_cash_flow": [
            "financing cash flow",
            "cash flow from financing activities",
            "net cash provided by financing activities",
            "net cash used in financing activities",
        ],
        "total_current_liabilities": ["total current liabilities", "current liabilities", "liabilities current"],
        "total_current_assets": ["total current assets", "current assets", "assets current"],
        "debt": ["debt", "short-term debt", "long-term debt", "borrowings"],
        "prior_debt": ["debt", "short-term debt", "long-term debt", "borrowings", "prior debt"],
        "current_debt": ["debt", "short-term debt", "long-term debt", "borrowings", "current debt"],
        "short_term_investments": ["short-term investments", "short term investments", "marketable securities"],
        "cash_and_equivalents": ["cash and cash equivalents", "cash equivalents", "cash"],
        "cash_and_equivalents_prior": ["cash and cash equivalents", "cash equivalents", "cash", "prior cash and cash equivalents"],
        "cash_and_equivalents_current": ["cash and cash equivalents", "cash equivalents", "cash", "current cash and cash equivalents"],
        "marketable_securities": ["marketable securities", "short-term investments"],
        "accounts_receivable": ["accounts receivable", "net accounts receivable", "receivables"],
        "accounts_payable": ["accounts payable", "payables"],
        "accounts_payable_begin": ["accounts payable", "trade accounts payable", "payables", "beginning accounts payable"],
        "accounts_payable_end": ["accounts payable", "trade accounts payable", "payables", "ending accounts payable"],
        "inventory": ["inventories", "inventory"],
        "inventory_begin": ["inventories", "inventory", "beginning inventory"],
        "inventory_end": ["inventories", "inventory", "ending inventory"],
        "property_plant_and_equipment_net": ["property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"],
        "assets": ["assets", "total assets"],
        "assets_current": ["assets", "total assets", "current period total assets"],
        "assets_prior": ["assets", "total assets", "prior period total assets"],
        "revenue": ["revenue", "revenues", "net sales", "net revenues", "sales"],
        "revenue_denominator": ["revenue", "revenues", "net sales", "net revenues", "sales"],
        "net_income": ["net income", "net earnings", "net income attributable to shareholders"],
        "operating_income": ["operating income", "income from operations"],
        "cogs": ["cost of goods sold", "cost of revenue", "cost of sales", "cogs"],
        "adjusted_ebitda": ["adjusted ebitda", "non-gaap ebitda", "non gaap ebitda"],
        "adjusted_ebit": ["adjusted ebit", "ebit"],
        "interest_expense": ["interest expense", "interest"],
        "cogs_numerator": ["cost of goods sold", "cost of revenue", "cost of sales", "cogs"],
        "gross_profit_numerator": ["gross profit"],
        "operating_income_numerator": ["operating income", "income from operations"],
        "net_income_numerator": ["net income", "net earnings", "net income attributable to shareholders"],
        "ebitda_numerator": ["ebitda", "adjusted ebitda", "depreciation and amortization"],
        "dividends_paid": ["dividends paid", "cash dividends paid", "dividends to shareholders"],
        "cash_flow_activity_totals": ["operating activities", "investing activities", "financing activities"],
        "restructuring_costs": ["restructuring costs", "restructuring expenses", "restructuring charges"],
        "effective_tax_rate": ["effective tax rate", "tax rate", "income tax rate"],
        "prior_effective_tax_rate": ["effective tax rate", "tax rate", "income tax rate", "prior effective tax rate"],
        "current_effective_tax_rate": ["effective tax rate", "tax rate", "income tax rate", "current effective tax rate"],
        "adjusted_ebit_or_ebit": ["adjusted ebit", "ebit", "operating income"],
        "depreciation_and_amortization": ["depreciation and amortization", "depreciation amortization", "d&a"],
        "liabilities": ["liabilities", "total liabilities"],
        "material_legal_proceedings": ["legal proceedings", "litigation", "material legal proceedings"],
        "registered_debt_securities": ["registered securities", "debt securities", "national securities exchange"],
        "acquisitions": ["acquisitions", "business combinations", "companies acquired"],
        "filing_event_summary": ["8-k", "8k", "filing event", "item"],
        "operating_geographies": ["geographies", "geographic areas", "regions"],
        "products_and_services": ["products", "services", "product categories", "service categories"],
        "customers": ["customers", "customer concentration", "primary customers"],
        "customer_retention": ["customer retention", "card member retention", "card members"],
        "industry": ["industry", "business"],
        "business_cyclicality": ["cyclicality", "cyclical", "business cycle"],
        "store_count": ["stores", "store count", "number of stores"],
        "store_count_prior": ["stores", "store count", "number of stores", "prior store count"],
        "store_count_current": ["stores", "store count", "number of stores", "current store count"],
        "production_rates": ["production rate", "production rates", "forecast production"],
        "governance_disclosure": ["directors", "executive officers", "board nominees", "ceo"],
        "shareholder_vote_results": ["shareholder vote", "shareholder proposal", "voting results"],
        "guidance": ["guidance", "outlook", "forecast"],
        "separation_or_discontinued_operation": ["separation", "spin-off", "discontinued operation", "subsequent events"],
        "gain_on_separation": ["gain on separation", "gain", "separation"],
        "cash_proceeds": ["cash proceeds", "proceeds"],
        "separation_payment": ["expected payment", "expect to pay", "spin-off payment", "separation payment", "upjohn"],
        "segment_results": ["segment revenue", "segment income", "reportable segments", "business segments"],
        "market_risk_var": ["value at risk", "var", "market risk"],
        "market_risk_var_prior": ["value at risk", "var", "market risk", "prior year"],
        "market_risk_var_current": ["value at risk", "var", "market risk", "current period"],
        "prior_percent_of_sales": ["as a percent of sales", "as a percent of net sales", "percent of sales", "prior period"],
        "current_percent_of_sales": ["as a percent of sales", "as a percent of net sales", "percent of sales", "current period"],
        "organic_sales_change": ["organic sales change", "real change in sales", "sales change excluding fx", "foreign exchange"],
        "derivative_instruments": ["derivative instruments", "notional value", "foreign currency derivatives", "interest rate derivatives"],
        "pension_postretirement_payments": ["expected benefit payments", "retirees", "pension", "postretirement"],
        "dividend_distribution_history": ["dividend distribution", "dividend history", "dividends declared", "dividends paid"],
        "dividends_disclosure": ["dividends", "common shareholders", "dividends to common shareholders"],
        "product_revenue_concentration": ["product categories", "service categories", "revenue concentration", "more than 20% of revenue"],
        "restructuring_liability": ["restructuring liability", "restructuring reserve", "restructuring accrual", "nature and purpose"],
        "nonrecurring_events": ["nonrecurring events", "special items", "standard business operations", "net income drivers"],
        "revenue_driver_discussion": ["revenue drivers", "sales drivers", "revenue change", "net sales change"],
        "inventory_driver_discussion": ["inventory drivers", "merchandise inventories", "inventory balance", "inventory increase"],
        "expense_driver_discussion": ["expense drivers", "sg&a", "selling general and administrative", "wages expense"],
        "geographic_sales_growth": ["us sales growth", "international sales growth", "geographic sales"],
        "expense_ratio_change": ["as a percent of sales", "as a percent of net sales", "expense ratio"],
        "growth_profile_evidence": ["growth profile", "revenue growth", "net income growth", "high growth company"],
        "guidance_change": ["guidance change", "full year guidance", "core constant currency eps growth", "percentage points"],
        "shares_outstanding": ["shares outstanding", "common shares outstanding"],
        "component_amount": ["component amount", "quarterly amount", "q4 amount", "share repurchases", "stock repurchases"],
        "total_amount": ["total amount", "annual amount", "share repurchases", "stock repurchases"],
        "credit_facility": ["revolving credit agreement", "credit facility", "borrowings"],
        "share_repurchases": ["share repurchases", "stock repurchases", "treasury stock"],
        "ranked_category_metric_table": [
            "category",
            "segment revenue",
            "segment net revenue",
            "segment net income",
            "regional ebitdar",
            "product category revenue",
            "short-term investments",
            "debt securities",
            "derivative instruments",
            "notional value",
            "liabilities",
        ],
    }
    values = list(mapping.get(slot_name, []))
    if line_item:
        values.insert(0, line_item)
    if not values:
        values.append(slot_name.replace("_", " "))
    return _ordered_unique(values)


def _yoy_growth_line_item(question: str) -> str | None:
    normalized = " ".join(str(question or "").lower().replace("-", " ").split())
    if "operating income" in normalized:
        return "operating income"
    if "net income" in normalized or "net earnings" in normalized:
        return "net income"
    if "ebitda" in normalized:
        return "ebitda"
    if "net sales" in normalized:
        return "net sales"
    if "net revenues" in normalized or "net revenue" in normalized:
        return "net revenues"
    if "total revenues" in normalized or "total revenue" in normalized:
        return "total revenues"
    if "revenue" in normalized or "revenues" in normalized:
        return "revenue"
    return None


def _slot_matches_target_line(slot_name: str, line_item: str) -> bool:
    if not line_item:
        return False
    return _slot_name_for_line_item(line_item) == slot_name


def _slot_name_for_line_item(line_item: str) -> str:
    normalized = " ".join(str(line_item or "").lower().replace("&", " and ").split())
    if normalized in {"property plant and equipment net", "net property plant and equipment", "net ppne", "ppne"}:
        return "property_plant_and_equipment_net"
    return normalized.replace(" ", "_").replace("-", "_")


def _normalized_question(question: str) -> str:
    return " ".join(str(question or "").lower().replace("&", " and ").replace("-", " ").split())


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
