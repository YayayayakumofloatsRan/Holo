from kernel_v3.finance.calculator import (
    CALCULATOR_TOOL_NAME,
    FINANCE_VERIFY_NUMERIC_TOOL_NAME,
    compute_formula,
    register_finance_tools as register_finance_calculator_tools,
)
from kernel_v3.finance.contracts import FinanceFact, FormulaTrace, NumericVerification
from kernel_v3.finance.fact_ledger import build_finance_fact_ledger
from kernel_v3.finance.formula_planner import FinanceFormulaPlan, plan_finance_formula
from kernel_v3.finance.numeric_verifier import finance_numeric_repair_guidance, verify_finance_answer
from kernel_v3.finance.open_components import (
    DOCUMENT_DOCLING_CONVERT_TOOL_NAME,
    FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES,
    FINANCE_OPEN_COMPONENT_TOOL_NAMES,
    FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME,
    MARKET_OPENBB_FETCH_TOOL_NAME,
    SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME,
    SEC_EDGAR_FINANCIALS_TOOL_NAME,
    register_finance_open_component_tools,
)
from kernel_v3.finance.substrate_adapter import (
    finance_evidence_policy_for_question,
    finance_facts_to_claims,
    finance_formula_plan_to_transform_plan,
    finance_slot_frame,
    finance_verification_to_gate_result,
)
from kernel_v3.finance.task_compiler import compile_finance_task_program, compile_finance_task_program_model_first
from kernel_v3.finance.target_binding import (
    attach_target_binding_to_facts,
    filter_facts_for_target_binding,
    primary_source_numeric_binding_resolution,
    target_document_binding_from_metadata,
)
from kernel_v3.tools import ToolRegistry


def register_finance_tools(registry: ToolRegistry) -> ToolRegistry:
    register_finance_calculator_tools(registry)
    register_finance_open_component_tools(registry)
    return registry

__all__ = [
    "FinanceFact",
    "FinanceFormulaPlan",
    "FormulaTrace",
    "NumericVerification",
    "CALCULATOR_TOOL_NAME",
    "DOCUMENT_DOCLING_CONVERT_TOOL_NAME",
    "FINANCE_VERIFY_NUMERIC_TOOL_NAME",
    "FINANCE_OPEN_COMPONENT_NETWORK_TOOL_NAMES",
    "FINANCE_OPEN_COMPONENT_TOOL_NAMES",
    "FINANCE_TOOLCHAIN_DESCRIBE_TOOL_NAME",
    "MARKET_OPENBB_FETCH_TOOL_NAME",
    "SEC_EDGAR_COMPANY_FILINGS_TOOL_NAME",
    "SEC_EDGAR_FINANCIALS_TOOL_NAME",
    "build_finance_fact_ledger",
    "compute_formula",
    "compile_finance_task_program",
    "compile_finance_task_program_model_first",
    "finance_evidence_policy_for_question",
    "finance_facts_to_claims",
    "finance_formula_plan_to_transform_plan",
    "finance_slot_frame",
    "finance_verification_to_gate_result",
    "finance_numeric_repair_guidance",
    "attach_target_binding_to_facts",
    "filter_facts_for_target_binding",
    "primary_source_numeric_binding_resolution",
    "plan_finance_formula",
    "register_finance_calculator_tools",
    "register_finance_open_component_tools",
    "register_finance_tools",
    "target_document_binding_from_metadata",
    "verify_finance_answer",
]
