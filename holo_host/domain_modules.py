from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOMAIN_MODULE_SCHEMA = "holo.stage158.domain_module.v1"

DOMAIN_MODULE_REQUIRED_FIELDS = (
    "module_id",
    "module_name",
    "instruction_scope",
    "memory_schema",
    "tool_requirements",
    "bench_categories",
    "report_templates",
    "risk_boundaries",
)


@dataclass(frozen=True, slots=True)
class DomainModuleScaffold:
    module_id: str
    module_name: str
    instruction_scope: str
    memory_schema: dict[str, Any]
    tool_requirements: list[str] = field(default_factory=list)
    bench_categories: list[str] = field(default_factory=list)
    report_templates: list[str] = field(default_factory=list)
    risk_boundaries: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DOMAIN_MODULE_SCHEMA,
            "module_id": self.module_id,
            "module_name": self.module_name,
            "instruction_scope": self.instruction_scope,
            "memory_schema": dict(self.memory_schema),
            "tool_requirements": list(self.tool_requirements),
            "bench_categories": list(self.bench_categories),
            "report_templates": list(self.report_templates),
            "risk_boundaries": list(self.risk_boundaries),
            "status": "scaffold_only",
            "implements_live_work": False,
            "runtime_entrypoint": None,
        }


_SCAFFOLDS = (
    DomainModuleScaffold(
        module_id="math_research",
        module_name="Math Research",
        instruction_scope="domain.math_research",
        memory_schema={
            "objects": ["Problem", "Definition", "Lemma", "ProofAttempt", "Counterexample", "Result"],
            "evidence": ["derivation", "source", "verification"],
        },
        tool_requirements=["symbolic_scratchpad", "proof_checker_optional", "literature_lookup"],
        bench_categories=["reasoning_consistency", "proof_gap_detection", "notation_continuity"],
        report_templates=["problem_brief", "proof_log", "result_note"],
        risk_boundaries=[
            "Do not claim theorem proof without a checked derivation ledger.",
            "Keep conjecture, sketch, and proof states separate.",
        ],
    ),
    DomainModuleScaffold(
        module_id="physics_research",
        module_name="Physics Research",
        instruction_scope="domain.physics_research",
        memory_schema={
            "objects": ["System", "Variable", "Assumption", "Equation", "Simulation", "Observation"],
            "evidence": ["measurement", "derivation", "simulation_run", "source"],
        },
        tool_requirements=["unit_checker", "simulation_runner_optional", "paper_lookup"],
        bench_categories=["unit_integrity", "assumption_tracking", "model_fit_explanation"],
        report_templates=["model_card", "simulation_report", "assumption_table"],
        risk_boundaries=[
            "Do not present unverified simulation output as measured reality.",
            "Expose assumptions and units before conclusions.",
        ],
    ),
    DomainModuleScaffold(
        module_id="market_research",
        module_name="Market Research",
        instruction_scope="domain.market_research",
        memory_schema={
            "objects": ["Company", "Market", "Source", "Metric", "Claim", "Risk", "Scenario"],
            "evidence": ["filing", "transcript", "dataset", "web_source"],
        },
        tool_requirements=["web_lookup", "filing_reader", "spreadsheet_export_optional"],
        bench_categories=["source_grounding", "metric_consistency", "recency_discipline"],
        report_templates=["company_note", "market_map", "risk_register"],
        risk_boundaries=[
            "Do not provide investment advice.",
            "Separate current source evidence from model inference.",
        ],
    ),
    DomainModuleScaffold(
        module_id="projecth_ops",
        module_name="ProjectH Ops",
        instruction_scope="domain.projecth_ops",
        memory_schema={
            "objects": ["Campaign", "RemoteRun", "Artifact", "Blocker", "Decision", "NextAction"],
            "evidence": ["manifest", "log", "config", "benchmark_result"],
        },
        tool_requirements=["repo_search", "remote_manifest_reader", "artifact_diff"],
        bench_categories=["control_plane_safety", "artifact_evidence", "blocker_tracking"],
        report_templates=["run_handoff", "blocker_report", "acceptance_summary"],
        risk_boundaries=[
            "Prefer local dry-run planning before billed remote runs.",
            "Do not relabel authority failures as model-quality failures.",
        ],
    ),
)


def get_domain_module_registry() -> dict[str, dict[str, Any]]:
    """Return domain-module scaffolds without activating live domain work."""

    return {module.module_id: module.to_dict() for module in _SCAFFOLDS}


def get_domain_module(module_id: str) -> dict[str, Any] | None:
    return get_domain_module_registry().get(str(module_id or "").strip())
