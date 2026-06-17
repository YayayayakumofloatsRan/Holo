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
                "facts": {
                    "type": "list[FinanceFact]",
                    "required": False,
                    "description": "FinanceFact rows or minimal fact objects with at least metric and value.",
                },
                "formula_traces": {
                    "type": "list[FormulaTrace]",
                    "required": False,
                    "description": "FormulaTrace rows or minimal trace objects with a result_value.",
                },
                "citations": {
                    "type": "list[CitationItem]",
                    "required": False,
                    "description": "CitationItem rows or minimal citation objects with citation_id/evidence_id/quote.",
                },
                "evidence": {
                    "type": "list[EvidenceItem]",
                    "required": False,
                    "description": "EvidenceItem rows or minimal evidence objects with evidence_id/text or quote.",
                },
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
            result.append(_contract_from_tool_payload(item, cls, field_name=field_name, index=index))
        except Exception as exc:
            raise CalculatorError(f"invalid_{field_name}_item:{index}:{exc}") from exc
    return result


def _contract_from_tool_payload(item: JsonObject, cls, *, field_name: str, index: int):
    try:
        return cls.from_dict(item)
    except Exception:
        if cls is FinanceFact:
            return _finance_fact_from_tool_payload(item, index=index)
        if cls is FormulaTrace:
            return _formula_trace_from_tool_payload(item, index=index)
        if cls is CitationItem:
            return _citation_item_from_tool_payload(item, index=index)
        if cls is EvidenceItem:
            return _evidence_item_from_tool_payload(item, index=index)
        raise


def _finance_fact_from_tool_payload(item: JsonObject, *, index: int) -> FinanceFact:
    metric = _first_text(item, "metric", "line_item", "name", "label", "concept")
    value = _first_text(item, "value", "amount", "result_value", "numeric_value")
    if not metric:
        raise CalculatorError("FinanceFact missing fields: metric")
    if not value:
        raise CalculatorError("FinanceFact missing fields: value")
    metadata = _metadata_from_tool_payload(item)
    return FinanceFact(
        fact_id=_first_text(item, "fact_id", "id") or f"tool-fact-{_payload_hash(item, index=index)}",
        entity=_first_text(item, "entity", "company", "issuer") or None,
        ticker=_first_text(item, "ticker", "symbol") or None,
        period=_first_text(item, "period", "fiscal_period", "target_period") or None,
        fiscal_year=_optional_int(item.get("fiscal_year", item.get("year"))),
        metric=metric,
        value=value,
        unit=_first_text(item, "unit", "units", "currency") or None,
        scale=_first_text(item, "scale", "display_unit") or None,
        source_ref=(
            _first_text(item, "source_ref", "source_uri", "uri", "source_id", "citation_ref", "evidence_ref")
            or "tool_payload"
        ),
        evidence_ref=_first_text(item, "evidence_ref", "evidence_id") or None,
        citation_ref=_first_text(item, "citation_ref", "citation_id") or None,
        metadata=metadata,
    )


def _formula_trace_from_tool_payload(item: JsonObject, *, index: int) -> FormulaTrace:
    result_value = _first_text(item, "result_value", "value", "formatted_value")
    if not result_value:
        raise CalculatorError("FormulaTrace missing fields: result_value")
    input_fact_ids = item.get("input_fact_ids")
    if not isinstance(input_fact_ids, list):
        input_fact_ids = []
    return FormulaTrace(
        formula_id=_first_text(item, "formula_id", "id") or f"tool-formula-{_payload_hash(item, index=index)}",
        formula_name=_first_text(item, "formula_name", "name") or "tool_formula_trace",
        expression=_first_text(item, "expression", "formula") or "",
        input_fact_ids=[str(raw) for raw in input_fact_ids if str(raw or "").strip()],
        result_value=result_value,
        unit=_first_text(item, "unit") or None,
        diagnostics=_metadata_from_tool_payload(item),
    )


def _citation_item_from_tool_payload(item: JsonObject, *, index: int) -> CitationItem:
    quote = _first_text(item, "quote", "quote_preview", "text", "text_preview", "content") or ""
    span_start = _optional_int(item.get("span_start"))
    span_end = _optional_int(item.get("span_end"))
    return CitationItem(
        citation_id=_first_text(item, "citation_id", "citation_ref", "id") or f"tool-cite-{_payload_hash(item, index=index)}",
        goal_id=_first_text(item, "goal_id") or "",
        evidence_id=_first_text(item, "evidence_id", "evidence_ref") or "",
        artifact_id=_first_text(item, "artifact_id", "artifact_ref") or "",
        uri=_first_text(item, "uri", "source_uri") or "",
        title=_first_text(item, "title", "source_title") or "",
        quote=quote,
        span_start=span_start if span_start is not None else 0,
        span_end=span_end if span_end is not None else len(quote),
        metadata=_metadata_from_tool_payload(item),
    )


def _evidence_item_from_tool_payload(item: JsonObject, *, index: int) -> EvidenceItem:
    text = _first_text(item, "text", "text_preview", "quote", "quote_preview", "content") or ""
    score = item.get("score")
    try:
        parsed_score = float(score) if score is not None else 1.0
    except (TypeError, ValueError):
        parsed_score = 1.0
    return EvidenceItem(
        evidence_id=_first_text(item, "evidence_id", "evidence_ref", "id") or f"tool-ev-{_payload_hash(item, index=index)}",
        goal_id=_first_text(item, "goal_id") or "",
        span_id=_first_text(item, "span_id") or f"tool-span-{index}",
        document_id=_first_text(item, "document_id", "doc_id") or "",
        source_id=_first_text(item, "source_id") or "",
        artifact_id=_first_text(item, "artifact_id", "artifact_ref") or "",
        uri=_first_text(item, "uri", "source_uri") or "",
        title=_first_text(item, "title", "source_title") or "",
        text=text,
        score=parsed_score,
        payload_hash=_first_text(item, "payload_hash", "hash") or _payload_hash(item, index=index),
        diagnostics=_metadata_from_tool_payload(item),
    )


def _first_text(item: JsonObject, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _metadata_from_tool_payload(item: JsonObject) -> JsonObject:
    metadata = item.get("metadata")
    result: JsonObject = dict(metadata) if isinstance(metadata, dict) else {}
    for key in (
        "source_title",
        "source_uri",
        "concept",
        "label",
        "statement",
        "line_item",
        "relevance",
        "raw_metric",
        "display_unit",
    ):
        if key in item and key not in result:
            result[key] = item[key]
    result.setdefault("tool_payload_normalized", True)
    return _json_safe_diagnostics(result)


def _payload_hash(item: JsonObject, *, index: int) -> str:
    try:
        text = str(sorted((str(key), str(value)) for key, value in item.items()))
    except Exception:
        text = str(item)
    return hashlib.sha256(f"{index}:{text}".encode("utf-8")).hexdigest()[:12]


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
