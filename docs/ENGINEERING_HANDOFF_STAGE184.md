# Engineering Handoff Stage184

## Summary

Stage184 adds a real-use agent drill for Holo's engineering/search/market-research kernel. It is stricter than Stage183 because the default engineering case executes real host actions in a temporary repository:

```text
workspace_search -> file_read -> apply_patch -> test_run -> git_status -> git_diff
```

The search case drives Stage151 decision, web observation ledger construction, grounding, and live trace rendering with deterministic mocked providers. The market case drives the Stage174 market-research report action. A claim-only baseline proves unsupported claims are detected instead of accepted as success.

## Files Changed

```text
holo_host/agent_real_use_drill.py
holo_host/cli.py
holo_host/stage135_i_state_topology.py
tests/test_stage184_real_use_agent_drill.py
docs/STAGE184_REAL_USE_AGENT_DRILL.md
docs/ENGINEERING_HANDOFF_STAGE184.md
HOLO_HANDOFF.md
docs/ROADMAP_REGISTRY.md
```

## New Schemas

```text
holo.stage184.real_use_agent_drill.v1
holo.stage184.real_use_case.v1
holo.stage184.real_use_scorecard.v1
```

## Runtime Propagation

Stage184 is a benchmark/drill surface. It does not alter the live reply policy by itself.

CLI:

```powershell
python -m holo_host run-agent-real-use-drill --output artifacts\stage184\stage184_real_use_agent_drill.html --dry-run
```

Artifacts:

```text
artifacts/stage184/stage184_real_use_agent_drill.html
artifacts/stage184/stage184_real_use_agent_drill.json
artifacts/stage184/stage184_real_use_agent_drill.jsonl
```

Stage135 topology accepts `stage184_real_use_drill` and exposes `real_use_drill_*` metrics.

## Cases

### engineering-real-use

Creates a temporary repo, seeds a failing add function, searches for the marker, reads the file, applies a patch, runs pytest, and checks git status/diff. Visible engineering claims must be grounded by ledgers.

### search-real-use

Runs Stage151 web-search decision/execution/grounding with deterministic mocked search/open-page providers. The result must contain `web_observation_ledger`, source URLs, time observation, and trace lines.

### search-network-disabled-boundary

Runs the same decision path with network disabled. The drill passes only if a rejected web observation is recorded and final text avoids pretending that current web evidence exists.

### market-research-real-use

Builds a Stage169 pack from deterministic filing evidence and runs Stage174 report action. The report must be `evidence_ready`, include citations, and produce a report ledger.

### claim-only-baseline

Deliberately overclaims read/patch/test/search/report success without ledgers. The case passes only when unsupported claim failures are detected.

## Verification

Targeted red:

```powershell
python -m pytest tests\test_stage184_real_use_agent_drill.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage184-red
```

Result:

```text
1 error: ModuleNotFoundError: No module named 'holo_host.agent_real_use_drill'
```

Targeted green:

```powershell
python -m pytest tests\test_stage184_real_use_agent_drill.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage184-green2
```

Result:

```text
8 passed in 27.98s
```

Stack:

```powershell
python -m pytest tests\test_stage184_real_use_agent_drill.py tests\test_stage183_agent_capability_gauntlet.py tests\test_stage154_engineering_action_fabric.py tests\test_stage151_tool_decision_loop.py tests\test_stage173_market_research_report.py tests\test_stage174_market_research_report_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage184-stack
```

Result:

```text
53 passed in 43.79s
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage184-runtime
```

Result:

```text
92 passed in 22.94s
```

Artifact smoke:

```powershell
python -m holo_host run-agent-real-use-drill --output artifacts\stage184\stage184_real_use_agent_drill.html --dry-run
```

Result:

```text
status=passed
case_count=5
full_loop_score=1.0
claim_only_baseline_score=0.12
score_delta_vs_claim_only=0.88
```

Final release verification:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
912 passed in 285.38s (0:04:45)
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: public hygiene passed; `git diff --check` passed with CRLF normalization warnings only.
## Constraints Preserved

```text
provider calls: none added
memory writes: none added
WeChat start: none
transport authority widened: no
hidden reasoning exposure: no
live network required for tests: no
engineering writes confined to temp repo: yes
```

## Next Suggested Stage

Stage185 should focus on live crawler/search maturity: real network optional drills, source freshness, page extraction quality, retry/fallback reporting, and market-research source pack quality under actual web conditions.
