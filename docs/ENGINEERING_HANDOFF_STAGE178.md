# Engineering Handoff Stage178

## Summary

Stage178 adds a domain-independent evidence/action remediation controller. It generalizes Stage177's market-research remediation into a reusable agent-kernel pattern for literature research, mathematical derivation, GPU experiments, memory grounding, and tool-backed engineering claims.

The key idea is that an evidence gap should become an action plan with success criteria, not a vague failure label.

## Files Changed

```text
holo_host/evidence_action_remediation.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage178_evidence_action_remediation.py
docs/STAGE178_EVIDENCE_ACTION_REMEDIATION.md
docs/ENGINEERING_HANDOFF_STAGE178.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage178.evidence_action_remediation.v1
holo.stage178.evidence_action_remediation_bundle.v1
holo.stage178.evidence_action_remediation_action.v1
```

## CLI

```powershell
python -m holo_host run-evidence-action-remediation --output artifacts\stage178\stage178_evidence_action_remediation.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts without provider calls, network fetches, tool execution, memory writes, WeChat starts, or transport widening.

## Behaviors

```text
literature source gap -> primary_literature_search
math derivation gap -> derive_or_request_assumptions
GPU experiment failure -> inspect_experiment_artifacts + plan_experiment_retry
unsupported memory claim -> run_memory_recall
unexecuted tool claim -> execute_required_tool_or_repair_claim
conflicting evidence -> compare_conflicting_evidence
scope mismatch -> clarify_or_refetch_scope
```

Stage177 remediation results can be promoted into Stage178 generic evidence-action reports.

Stage135 topology exposes an `evidence_action_remediation` node and compact issue/action metrics.

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage178_evidence_action_remediation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage178-red
```

Result: `9 failed` because the Stage178 module, CLI command, and topology integration did not exist.

Targeted green:

```powershell
python -m pytest tests\test_stage178_evidence_action_remediation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage178-green1
```

Result: `9 passed`.

Targeted stack:

```powershell
python -m pytest tests\test_stage178_evidence_action_remediation.py tests\test_stage177_market_research_remediation.py tests\test_stage176_market_research_domain_benchmark.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage178-targeted
```

Result: `29 passed in 2.83s`.

Artifact smoke:

```powershell
python -m holo_host run-evidence-action-remediation --output artifacts\stage178\stage178_evidence_action_remediation.html --dry-run
```

Result: wrote `.html`, `.json`, and `.jsonl` artifacts under `artifacts\stage178`.

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage178-runtime
```

Result: `92 passed in 17.89s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `862 passed in 97.26s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: public hygiene passed; `git diff --check` exited 0 with CRLF normalization warnings only.

## Constraints Preserved

- no provider model path outside processor fabric
- no network fetches in tests
- no tool execution
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure

## Next Suggested Stage

Stage179 should wire Stage178 into the live model-first action loop as a post-evaluation repair controller, so failed observations from real CLI sessions can automatically produce the next candidate action instead of stopping at a report.
