# Engineering Handoff Stage183

## Summary

Stage183 adds an agent capability gauntlet for Holo's base kernel. It evaluates Holo as an engineering/research tool rather than as isolated modules.

The gauntlet combines:

```text
engineering execution
market-research report generation
Stage182 remediation continuation
adversarial unsupported-claim detection
```

Each case must have auditable event traces, ledgers, stop reasons, privacy hygiene, and no persona leakage. For adversarial fixtures, detecting the failure is the pass condition.

## Files Changed

```text
holo_host/agent_capability_gauntlet.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage183_agent_capability_gauntlet.py
docs/STAGE183_AGENT_CAPABILITY_GAUNTLET.md
docs/ENGINEERING_HANDOFF_STAGE183.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage183.agent_capability_gauntlet.v1
holo.stage183.agent_capability_case.v1
holo.stage183.agent_capability_scorecard.v1
```

## CLI

```powershell
python -m holo_host run-agent-capability-gauntlet --output artifacts\stage183\stage183_agent_capability_gauntlet.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Runtime And Topology

Stage183 is a benchmark/reporting surface. It does not change live policy or execute new live authority.

Stage135 accepts `stage183_agent_capability_gauntlet` and exposes:

```text
agent_capability_gauntlet_node_count
agent_capability_gauntlet_case_count
agent_capability_gauntlet_passed_count
agent_capability_gauntlet_status
```

## Case Examples

Engineering success:

```text
workspace_search + file_read + apply_patch + test_run + git_diff ledgers
visible claim: searched, read, patched, tests passed, diff checked
expected: passed
```

Market research success:

```text
market_research_report ledger
Stage173 report status evidence_ready
citations present
expected: passed
```

Remediation continuation:

```text
Stage182 report present
[remediation_continue] rendered in event stream
known canonical stop reason
expected: passed
```

Adversarial unsupported claim:

```text
visible claim: read, patched, tests passed
engineering ledgers: none
expected: detected failure, not false success
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage183_agent_capability_gauntlet.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage183-red
```

Result: failed because `holo_host.agent_capability_gauntlet` did not exist.

Targeted:

```powershell
python -m pytest tests\test_stage183_agent_capability_gauntlet.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage183-targeted4
```

Result:

```text
8 passed in 1.46s
```

Targeted stack:

```powershell
python -m pytest tests\test_stage183_agent_capability_gauntlet.py tests\test_stage154_engineering_action_fabric.py tests\test_stage173_market_research_report.py tests\test_stage182_remediation_continuation.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage183-stack
```

Result:

```text
33 passed in 12.44s
```

Runtime regression:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage183-runtime
```

Result:

```text
92 passed in 43.02s
```

Artifact smoke:

```powershell
python -m holo_host run-agent-capability-gauntlet --output artifacts\stage183\stage183_agent_capability_gauntlet.html --dry-run
```

Result: `status=passed`, `case_count=4`, `pass_rate=1.0`, artifacts written to `artifacts\stage183\stage183_agent_capability_gauntlet.{html,json,jsonl}`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
904 passed in 253.38s
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: hygiene passed; `git diff --check` passed with CRLF normalization warnings only.

## Constraints Preserved

- no provider model calls;
- no memory writes;
- no WeChat start;
- no transport authority widening;
- no hidden reasoning exposure;
- no persona/social language in gauntlet surfaces;
- no live-network requirement in tests.

## Next Suggested Stage

Stage184 should add live-smoke mode for this gauntlet: execute a tiny real repo read/search/test path and a real local market-report fixture under timing budgets, while keeping provider/network optional.
