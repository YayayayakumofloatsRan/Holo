# Stage178 Evidence Action Remediation

Stage178 generalizes the Stage177 remediation pattern into a domain-independent evidence/action controller.

The core behavior is:

```text
observe evidence gap -> classify issue -> select next action -> define success criteria -> block unsafe finalization
```

This is part of Holo's agent cognition layer. It is meant to support market research, literature review, mathematical research, physics work, engineering tasks, and autonomous GPU experiments through the same control pattern.

## Schemas

```text
holo.stage178.evidence_action_remediation.v1
holo.stage178.evidence_action_remediation_bundle.v1
holo.stage178.evidence_action_remediation_action.v1
```

## Supported Issue Types

```text
source_missing
derivation_gap / math_gap
experiment_failed
memory_unsupported
tool_unexecuted
metric_conflict / evidence_conflict
period_mismatch / scope_mismatch
unknown
```

## Example Actions

```text
literature_research + source_missing
  -> primary_literature_search
  -> web_search

math_research + derivation_gap
  -> derive_or_request_assumptions
  -> answer_direct with explicit bounded reasoning

gpu_experiment + experiment_failed
  -> inspect_experiment_artifacts
  -> plan_experiment_retry

agent_memory + memory_unsupported
  -> run_memory_recall

engineering + tool_unexecuted
  -> execute_required_tool_or_repair_claim
```

## CLI

```powershell
python -m holo_host run-evidence-action-remediation --output artifacts\stage178\stage178_evidence_action_remediation.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Boundaries

Stage178 is deterministic and offline by default.

It does not:

- call provider models
- fetch network data
- execute tools
- write memory
- start WeChat
- widen transport authority
- expose hidden reasoning

## Why It Matters

The market-research stack is one test domain. Stage178 extracts the reusable control rule that makes Holo agentic: when evidence is insufficient, Holo should identify the missing observation, choose the next action, and refuse premature finalization. This same loop is what Holo needs for literature review, proof work, experimental science, and engineering execution.
