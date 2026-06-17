from __future__ import annotations

from decimal import Decimal, InvalidOperation

from kernel_v3.contracts import CandidateAction, JsonObject, Observation, ToolManifest
from kernel_v3.finance.contracts import FinanceFact
from kernel_v3.tools import ToolRegistry


FINANCE_SLOT_BIND_TOOL_NAME = "finance.slot_bind"


def register_finance_slot_bind_tool(registry: ToolRegistry) -> ToolRegistry:
    registry.register(
        FINANCE_SLOT_BIND_TOOL_NAME,
        _execute_finance_slot_bind,
        manifest=ToolManifest(
            name=FINANCE_SLOT_BIND_TOOL_NAME,
            version="1",
            resource_kind="finance",
            operator_kind="slot_bind",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Validate model-selected finance slot bindings and formula requests against visible "
                "FinanceFact records, returning calculator-ready payloads without making semantic choices."
            ),
            input_schema={
                "facts": {"type": "list[FinanceFact]", "required": True},
                "slot_bindings": {"type": "list[object]", "required": False},
                "formula_requests": {"type": "list[object]", "required": False},
                "period_basis": {"type": "list[object]", "required": False},
                "line_item_basis": {"type": "list[object]", "required": False},
                "missing_slots": {"type": "list[str]", "required": False},
                "next_action": {"type": "object", "required": False},
                "reason_summary": {"type": "str", "required": False},
                "compiled_program": {"type": "object", "required": False},
                "ledger_ref": {"type": "str", "required": False},
            },
        ),
    )
    return registry


def _execute_finance_slot_bind(action: CandidateAction) -> Observation:
    try:
        facts = _finance_facts_from_payload(action.payload.get("facts"))
        content = finance_slot_bind_tool_result(action.payload, facts=facts)
        status = "ok" if content.get("status") in {"ready", "missing_slots"} else "failed"
    except Exception as exc:
        status = "failed"
        content = {
            "schema": "holo.kernel_v3.finance_slot_bind_tool_result.v1",
            "status": "failed",
            "error": "finance_slot_bind_failed",
            "reason": str(exc),
            "error_type": type(exc).__name__,
            "semantic_decision_owner": "model",
            "host_role": "schema_and_fact_id_validation_only",
        }
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="finance_slot_bind",
        status=status,
        source=f"tool:{FINANCE_SLOT_BIND_TOOL_NAME}",
        content=content,
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def finance_slot_bind_tool_result(payload: JsonObject, *, facts: list[FinanceFact]) -> JsonObject:
    fact_by_id = {fact.fact_id: fact for fact in facts if fact.fact_id}
    accepted_bindings, rejected_bindings, bindings = _validated_slot_bindings(
        payload.get("slot_bindings"),
        fact_by_id=fact_by_id,
    )
    accepted_payloads: list[JsonObject] = []
    rejected_formula_requests: list[JsonObject] = []
    for index, request in enumerate(_dict_items(payload.get("formula_requests"))[:12], start=1):
        calculator_payload, rejected = _calculator_payload_from_request(
            request,
            index=index,
            fact_by_id=fact_by_id,
            bindings=bindings,
            payload=payload,
        )
        if rejected:
            rejected_formula_requests.extend(rejected)
            continue
        if calculator_payload:
            accepted_payloads.append(calculator_payload)
    missing_slots = _string_list(payload.get("missing_slots"))
    decision = str(payload.get("decision") or "").strip()
    status = "ready" if accepted_bindings or accepted_payloads else "missing_slots" if missing_slots else "failed"
    return {
        "schema": "holo.kernel_v3.finance_slot_bind_tool_result.v1",
        "status": status,
        "decision": decision or status,
        "fact_count": len(facts),
        "accepted_slot_binding_count": len(accepted_bindings),
        "accepted_formula_plan_count": len(accepted_payloads),
        "slot_bindings": accepted_bindings,
        "period_basis": _dict_items(payload.get("period_basis"))[:64],
        "line_item_basis": _dict_items(payload.get("line_item_basis"))[:64],
        "formula_request_count": len(_dict_items(payload.get("formula_requests"))),
        "calculator_payloads": accepted_payloads,
        "missing_slots": missing_slots[:24],
        "next_action": payload.get("next_action") if isinstance(payload.get("next_action"), dict) else {},
        "reason_summary": str(payload.get("reason_summary") or "")[:500],
        "rejected_slot_bindings": rejected_bindings,
        "rejected_formula_requests": rejected_formula_requests,
        "compiled_program": payload.get("compiled_program") if isinstance(payload.get("compiled_program"), dict) else {},
        "ledger_ref": str(payload.get("ledger_ref") or ""),
        "semantic_decision_owner": "model",
        "host_role": "validate_fact_ids_and_prepare_calculator_payloads_only",
    }


def _finance_facts_from_payload(value: object) -> list[FinanceFact]:
    if not isinstance(value, list):
        raise ValueError("facts must be a list of FinanceFact dicts")
    facts: list[FinanceFact] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ValueError(f"invalid_fact_item:{index}")
        try:
            facts.append(FinanceFact.from_dict(item))
        except Exception as exc:
            raise ValueError(f"invalid_fact_item:{index}:{exc}") from exc
    return facts


def _validated_slot_bindings(
    value: object,
    *,
    fact_by_id: dict[str, FinanceFact],
) -> tuple[list[JsonObject], list[JsonObject], dict[str, FinanceFact]]:
    accepted: list[JsonObject] = []
    rejected: list[JsonObject] = []
    bindings: dict[str, FinanceFact] = {}
    for index, item in enumerate(_dict_items(value), start=1):
        fact_id = str(item.get("fact_id") or "").strip()
        fact = fact_by_id.get(fact_id)
        if fact is None:
            rejected.append({"index": index, "fact_id": fact_id, "reason": "unknown_fact_id"})
            continue
        binding = dict(item)
        binding["fact_id"] = fact.fact_id
        accepted.append(binding)
        for key in ("variable_name", "slot_name", "name"):
            variable_name = str(item.get(key) or "").strip()
            if variable_name:
                bindings[variable_name] = fact
    return accepted, rejected, bindings


def _calculator_payload_from_request(
    request: JsonObject,
    *,
    index: int,
    fact_by_id: dict[str, FinanceFact],
    bindings: dict[str, FinanceFact],
    payload: JsonObject,
) -> tuple[JsonObject | None, list[JsonObject]]:
    expression = str(request.get("expression") or "").strip()
    formula_name = str(request.get("formula_name") or request.get("name") or f"model_formula_{index}").strip()
    if not expression:
        return None, [{"index": index, "reason": "missing_expression"}]
    variables_raw = request.get("variables")
    variables_data = variables_raw if isinstance(variables_raw, dict) else {}
    variables: JsonObject = {}
    input_fact_ids: list[str] = []
    rejected: list[JsonObject] = []
    for variable_name, raw_value in variables_data.items():
        value, fact_id, error = _slot_bind_variable_value(raw_value, fact_by_id=fact_by_id, bindings=bindings)
        if error:
            rejected.append({"index": index, "variable": str(variable_name), "reason": error})
            continue
        variables[str(variable_name)] = value
        if fact_id:
            input_fact_ids.append(fact_id)
    if rejected:
        return None, rejected
    for fact_id in _string_list(request.get("input_fact_ids")):
        if fact_id in fact_by_id:
            input_fact_ids.append(fact_id)
    period_basis = _dict_items(payload.get("period_basis"))[:64]
    line_item_basis = _dict_items(payload.get("line_item_basis"))[:64]
    return {
        "expression": expression,
        "formula_name": formula_name or "model_bound_formula",
        "variables": variables,
        "unit": request.get("unit") if isinstance(request.get("unit"), str) else None,
        "input_fact_ids": _ordered_unique(input_fact_ids),
        "diagnostics": {
            "source": "finance_slot_bind_tool",
            "ledger_ref": str(payload.get("ledger_ref") or ""),
            "model_reason_summary": payload.get("reason_summary"),
            "model_period_basis": period_basis,
            "model_line_item_basis": line_item_basis,
        },
    }, []


def _slot_bind_variable_value(
    raw_value: object,
    *,
    fact_by_id: dict[str, FinanceFact],
    bindings: dict[str, FinanceFact],
) -> tuple[object, str | None, str | None]:
    fact_id = None
    literal = None
    if isinstance(raw_value, dict):
        fact_id = str(raw_value.get("fact_id") or "").strip() or None
        formula_ref = (
            str(
                raw_value.get("formula_ref")
                or raw_value.get("from_formula")
                or raw_value.get("trace_ref")
                or raw_value.get("formula_name")
                or ""
            ).strip()
            or None
        )
        if formula_ref:
            return {"__formula_ref__": formula_ref}, None, None
        literal = raw_value.get("value") if raw_value.get("value") is not None else raw_value.get("literal")
    elif isinstance(raw_value, str):
        text = raw_value.strip()
        if text in fact_by_id:
            fact_id = text
        elif text in bindings:
            fact = bindings[text]
            return fact.value, fact.fact_id, None
        else:
            literal = text
    else:
        literal = raw_value
    if fact_id:
        fact = fact_by_id.get(fact_id)
        if fact is None:
            return None, None, "unknown_fact_id"
        if _decimal_or_none(fact.value) is None:
            return None, None, "bound_fact_value_not_numeric"
        return fact.value, fact.fact_id, None
    if _decimal_or_none(literal) is None:
        text = str(literal or "").strip()
        if text:
            return {"__formula_ref__": text}, None, None
        return None, None, "literal_not_numeric"
    return literal, None, None


def _decimal_or_none(value: object) -> Decimal | None:
    try:
        if isinstance(value, bool) or value is None:
            return None
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _dict_items(value: object) -> list[JsonObject]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ordered_unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
