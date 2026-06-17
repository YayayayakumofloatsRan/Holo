from __future__ import annotations

import ast
import hashlib
from decimal import Decimal, InvalidOperation, localcontext

from kernel_v3.contracts import CandidateAction, JsonObject, Observation, ToolManifest
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace
from kernel_v3.finance.numeric_verifier import finance_numeric_repair_guidance, verify_finance_answer
from kernel_v3.retrieval.contracts import CitationItem, EvidenceItem
from kernel_v3.tools import ToolRegistry


CALCULATOR_TOOL_NAME = "calculator.compute"
FINANCE_VERIFY_NUMERIC_TOOL_NAME = "finance.verify_numeric"
DEFAULT_PRECISION = 28
MAX_EXPRESSION_CHARS = 1_000
MAX_VARIABLES = 128


class CalculatorError(ValueError):
    pass


def register_finance_tools(registry: ToolRegistry) -> ToolRegistry:
    registry.register(
        CALCULATOR_TOOL_NAME,
        _execute_calculator,
        manifest=ToolManifest(
            name=CALCULATOR_TOOL_NAME,
            version="1",
            resource_kind="calculator",
            operator_kind="compute",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description="calculator.compute",
            input_schema={
                "expression": {"type": "str", "required": True, "min_length": 1},
                "variables": {"type": "object", "required": False},
                "unit": {"type": "str", "required": False},
                "formula_name": {"type": "str", "required": False},
                "input_fact_ids": {"type": "list[str]", "required": False},
                "diagnostics": {"type": "object", "required": False},
                "precision": {"type": "int", "required": False, "min": 8, "max": 80},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "max_result_size_chars": 12000,
                "result_persistence_policy": "never",
                "idempotent": True,
            },
        ),
    )
    registry.register(
        FINANCE_VERIFY_NUMERIC_TOOL_NAME,
        _execute_finance_verify_numeric,
        manifest=ToolManifest(
            name=FINANCE_VERIFY_NUMERIC_TOOL_NAME,
            version="1",
            resource_kind="finance",
            operator_kind="verify_numeric",
            side_effect_class="read",
            permissions_required=[],
            enabled=True,
            description=(
                "Verify whether a finance answer's numeric claims are supported by provided "
                "FinanceFact records, FormulaTrace records, citations, and evidence."
            ),
            input_schema={
                "answer": {"type": "str", "required": True, "min_length": 1},
                "facts": {"type": "list[FinanceFact]", "required": False},
                "formula_traces": {"type": "list[FormulaTrace]", "required": False},
                "citations": {"type": "list[CitationItem]", "required": False},
                "evidence": {"type": "list[EvidenceItem]", "required": False},
                "question": {"type": "str", "required": False},
                "target_binding": {"type": "object", "required": False},
            },
            runtime={
                "concurrency_safe": True,
                "read_only": True,
                "always_load": True,
                "max_result_size_chars": 50000,
                "result_persistence_policy": "auto",
                "idempotent": True,
            },
        ),
    )
    return registry


def compute_formula(
    *,
    expression: str,
    variables: JsonObject | None = None,
    unit: str | None = None,
    formula_name: str | None = None,
    input_fact_ids: list[str] | None = None,
    diagnostics: JsonObject | None = None,
    precision: int = DEFAULT_PRECISION,
) -> FormulaTrace:
    expression = str(expression or "").strip()
    if not expression:
        raise CalculatorError("missing_expression")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalculatorError("expression_too_long")
    parsed_variables = _decimal_variables(variables or {})
    if len(parsed_variables) > MAX_VARIABLES:
        raise CalculatorError("too_many_variables")
    with localcontext() as context:
        context.prec = max(8, min(int(precision or DEFAULT_PRECISION), 80))
        tree = ast.parse(expression, mode="eval")
        result = _DecimalExpressionEvaluator(parsed_variables).visit(tree)
    formula_id = "formula-" + _short_hash(expression, _canonical_variables(parsed_variables), str(unit or ""))
    trace_diagnostics = {
        "variables": {key: _decimal_string(value) for key, value in sorted(parsed_variables.items())},
        "formatted_value": format_formula_value(result, unit=unit),
        "precision": max(8, min(int(precision or DEFAULT_PRECISION), 80)),
    }
    if isinstance(diagnostics, dict):
        trace_diagnostics.update(_json_safe_diagnostics(diagnostics))
    return FormulaTrace(
        formula_id=formula_id,
        formula_name=str(formula_name or "calculator.compute"),
        expression=expression,
        input_fact_ids=list(input_fact_ids or []),
        result_value=_decimal_string(result),
        unit=str(unit).strip() if isinstance(unit, str) and unit.strip() else None,
        diagnostics=trace_diagnostics,
    )


def format_formula_value(value: Decimal, *, unit: str | None) -> str:
    normalized_unit = str(unit or "").strip().lower()
    if normalized_unit in {"percent", "%"}:
        return f"{_decimal_string(value * Decimal(100))}%"
    if normalized_unit in {"bps", "basis_points", "basis points"}:
        return f"{_decimal_string(value)} bps"
    if normalized_unit:
        return f"{_decimal_string(value)} {unit}"
    return _decimal_string(value)


def _execute_calculator(action: CandidateAction) -> Observation:
    try:
        trace = compute_formula(
            expression=str(action.payload.get("expression") or ""),
            variables=action.payload.get("variables") if isinstance(action.payload.get("variables"), dict) else {},
            unit=str(action.payload.get("unit")) if isinstance(action.payload.get("unit"), str) else None,
            formula_name=str(action.payload.get("formula_name")) if isinstance(action.payload.get("formula_name"), str) else None,
            input_fact_ids=[str(item) for item in action.payload.get("input_fact_ids", [])]
            if isinstance(action.payload.get("input_fact_ids"), list)
            else [],
            diagnostics=action.payload.get("diagnostics") if isinstance(action.payload.get("diagnostics"), dict) else None,
            precision=int(action.payload.get("precision") or DEFAULT_PRECISION),
        )
    except Exception as exc:
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="calculator_result",
            status="failed",
            source=f"tool:{CALCULATOR_TOOL_NAME}",
            content={"error": "calculator_failed", "reason": str(exc), "error_type": type(exc).__name__},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="calculator_result",
        status="ok",
        source=f"tool:{CALCULATOR_TOOL_NAME}",
        content={
            "formula_trace": trace.to_dict(),
            "result_value": trace.result_value,
            "unit": trace.unit,
            "formatted_value": trace.diagnostics.get("formatted_value"),
        },
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


def _execute_finance_verify_numeric(action: CandidateAction) -> Observation:
    try:
        answer = str(action.payload.get("answer") or "").strip()
        if not answer:
            raise CalculatorError("missing_answer")
        verification = verify_finance_answer(
            answer=answer,
            facts=_contract_list(action.payload.get("facts"), FinanceFact, "facts"),
            formula_traces=_contract_list(action.payload.get("formula_traces"), FormulaTrace, "formula_traces"),
            citations=_contract_list(action.payload.get("citations"), CitationItem, "citations"),
            evidence=_contract_list(action.payload.get("evidence"), EvidenceItem, "evidence"),
            question=str(action.payload.get("question") or ""),
            target_binding=action.payload.get("target_binding") if isinstance(action.payload.get("target_binding"), dict) else None,
        )
    except Exception as exc:
        return Observation(
            observation_id=f"obs-{action.action_id}",
            run_id="",
            kind="finance_numeric_verification",
            status="failed",
            source=f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}",
            content={"error": "finance_numeric_verifier_failed", "reason": str(exc), "error_type": type(exc).__name__},
            observed_at_ms=0,
            action_id=action.action_id,
            tool_call_id=None,
        )
    guidance = finance_numeric_repair_guidance(verification)
    return Observation(
        observation_id=f"obs-{action.action_id}",
        run_id="",
        kind="finance_numeric_verification",
        status="ok",
        source=f"tool:{FINANCE_VERIFY_NUMERIC_TOOL_NAME}",
        content={
            "verification": verification.to_dict(),
            "verifier_status": verification.status,
            "issue_count": len(verification.issues),
            "matched_value_count": len(verification.matched_values),
            "missing_value_count": len(verification.missing_values),
            "repair_guidance": guidance,
            "repair_options": guidance.get("repair_options", []),
            "missing_value_examples": guidance.get("missing_value_examples", []),
            "unit_mismatch_examples": guidance.get("unit_mismatch_examples", []),
        },
        observed_at_ms=0,
        action_id=action.action_id,
        tool_call_id=None,
    )


class _DecimalExpressionEvaluator(ast.NodeVisitor):
    def __init__(self, variables: dict[str, Decimal]) -> None:
        self.variables = variables

    def visit_Expression(self, node: ast.Expression) -> Decimal:  # noqa: N802
        return self.visit(node.body)

    def visit_Constant(self, node: ast.Constant) -> Decimal:  # noqa: N802
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float, str)):
            raise CalculatorError("unsupported_constant")
        return _decimal_value(node.value)

    def visit_Name(self, node: ast.Name) -> Decimal:  # noqa: N802
        if node.id not in self.variables:
            raise CalculatorError(f"unknown_variable:{node.id}")
        return self.variables[node.id]

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Decimal:  # noqa: N802
        value = self.visit(node.operand)
        if isinstance(node.op, ast.UAdd):
            return value
        if isinstance(node.op, ast.USub):
            return -value
        raise CalculatorError("unsupported_unary_operator")

    def visit_BinOp(self, node: ast.BinOp) -> Decimal:  # noqa: N802
        left = self.visit(node.left)
        right = self.visit(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            if right == 0:
                raise CalculatorError("division_by_zero")
            return left / right
        if isinstance(node.op, ast.Pow):
            return _decimal_power(left, right)
        raise CalculatorError("unsupported_binary_operator")

    def visit_Call(self, node: ast.Call) -> Decimal:  # noqa: N802
        if not isinstance(node.func, ast.Name):
            raise CalculatorError("unsupported_call")
        name = node.func.id
        args = [self.visit(arg) for arg in node.args]
        if node.keywords:
            raise CalculatorError("unsupported_keyword_args")
        if name == "pow" and len(args) == 2:
            return _decimal_power(args[0], args[1])
        if name == "round" and len(args) in {1, 2}:
            digits = int(args[1]) if len(args) == 2 else 0
            quantum = Decimal(1).scaleb(-digits)
            return args[0].quantize(quantum)
        if name == "abs" and len(args) == 1:
            return abs(args[0])
        if name == "min" and args:
            return min(args)
        if name == "max" and args:
            return max(args)
        raise CalculatorError(f"unsupported_function:{name}")

    def generic_visit(self, node: ast.AST):  # noqa: D102
        raise CalculatorError(f"unsupported_expression:{type(node).__name__}")


def _decimal_variables(variables: JsonObject) -> dict[str, Decimal]:
    result: dict[str, Decimal] = {}
    for key, value in variables.items():
        if not isinstance(key, str) or not key:
            raise CalculatorError("invalid_variable_name")
        result[key] = _decimal_value(value)
    return result


def _decimal_value(value: object) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise CalculatorError("invalid_numeric_value")
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, AttributeError) as exc:
        raise CalculatorError("invalid_numeric_value") from exc


def _decimal_power(left: Decimal, right: Decimal) -> Decimal:
    try:
        return left.__pow__(right)
    except InvalidOperation:
        return Decimal(str(float(left) ** float(right)))


def _json_safe_diagnostics(value: object) -> JsonObject:
    if not isinstance(value, dict):
        return {}
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            continue
        result[key] = _json_safe_value(item)
    return result


def _json_safe_value(value: object):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Decimal):
        return _decimal_string(value)
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe_value(item) for key, item in value.items()}
    return str(value)


def _contract_list(value: object, cls, field_name: str):
    if value is None:
        return []
    if not isinstance(value, list):
        raise CalculatorError(f"invalid_{field_name}")
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise CalculatorError(f"invalid_{field_name}_item:{index}")
        try:
            result.append(cls.from_dict(item))
        except Exception as exc:
            raise CalculatorError(f"invalid_{field_name}_item:{index}:{exc}") from exc
    return result


def _decimal_string(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _canonical_variables(variables: dict[str, Decimal]) -> str:
    return "|".join(f"{key}={_decimal_string(value)}" for key, value in sorted(variables.items()))


def _short_hash(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]
