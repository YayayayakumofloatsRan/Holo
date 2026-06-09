from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from kernel_v3.contracts import Contract, JsonObject


@dataclass(frozen=True, kw_only=True)
class FinanceFact(Contract):
    fact_id: str
    entity: str | None
    ticker: str | None
    period: str | None
    fiscal_year: int | None
    metric: str
    value: str
    unit: str | None
    scale: str | None
    source_ref: str
    evidence_ref: str | None
    citation_ref: str | None
    metadata: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class FormulaTrace(Contract):
    formula_id: str
    formula_name: str
    expression: str
    input_fact_ids: list[str]
    result_value: str
    unit: str | None
    diagnostics: JsonObject = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class NumericVerification(Contract):
    status: Literal["passed", "failed", "not_applicable"]
    issues: list[JsonObject]
    matched_values: list[JsonObject]
    formula_traces: list[JsonObject]
    missing_values: list[JsonObject] = field(default_factory=list)
    unit_mismatches: list[JsonObject] = field(default_factory=list)
    period_mismatches: list[JsonObject] = field(default_factory=list)
    diagnostics: JsonObject = field(default_factory=dict)
