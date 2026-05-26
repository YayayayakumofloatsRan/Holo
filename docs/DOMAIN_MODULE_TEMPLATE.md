# Domain Module Template

Domain modules extend Holo Agent Kernel v1 with domain-specific instruction, memory, tool, benchmark, report, and risk contracts.

Stage158 only defines scaffolds. A domain module must not perform live work until a later stage adds explicit implementation, tests, grounding rules, and operator-facing documentation.

## Required Fields

```text
module_id
module_name
instruction_scope
memory_schema
tool_requirements
bench_categories
report_templates
risk_boundaries
```

## Scaffold Example

```python
{
    "module_id": "example_domain",
    "module_name": "Example Domain",
    "instruction_scope": "domain.example_domain",
    "memory_schema": {
        "objects": ["Problem", "Source", "Result"],
        "evidence": ["tool_observation", "source", "verification"],
    },
    "tool_requirements": ["repo_search", "web_lookup_optional"],
    "bench_categories": ["source_grounding", "continuity"],
    "report_templates": ["brief", "handoff"],
    "risk_boundaries": ["Do not claim verification without an evidence ledger."],
    "status": "scaffold_only",
    "implements_live_work": False,
}
```

## Implementation Rule

Future domain modules must preserve the Agent Kernel boundary:

- no hidden reasoning exposure
- no ungrounded tool, memory, web, or engineering claims
- no provider calls outside processor fabric
- no memory writes without explicit runtime authority
- no transport startup or transport-side decision layer
