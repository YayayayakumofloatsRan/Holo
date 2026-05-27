# Stage184 Real-Use Agent Drill

Stage184 moves beyond fixture-only scoring. It runs bounded, local real-use drills that force Holo to prove agent behavior through actual host observations:

```text
observe -> decide -> act -> ledger -> verify -> final
```

The current priority is the updated Holo objective: become a Claude Code/Codex-level engineering and research agent base with strong search/crawler evidence, tool use, reasoning discipline, market-research workflows, and self-checking.

## Schemas

```text
holo.stage184.real_use_agent_drill.v1
holo.stage184.real_use_case.v1
holo.stage184.real_use_scorecard.v1
```

## What Stage184 Exercises

Stage184 executes five default drills:

```text
engineering-real-use
search-real-use
search-network-disabled-boundary
market-research-real-use
claim-only-baseline
```

The engineering drill creates a temporary repository, searches for a seeded bug, reads the target file, applies a patch, runs pytest, and inspects git diff. The result must be backed by Stage154 engineering ledgers.

The search drill drives the Stage151 decision/execution/grounding chain with mocked deterministic web search and page-open providers. It records web observation ledgers, source URLs, time observation, live trace, and grounding status. Network-disabled mode must record `rejected_network_disabled` and visibly avoid fake current-web claims.

The market-research drill uses the Stage169/173/174 evidence-pack and report-action path. A report passes only with an evidence-ready report, citations, and market research report ledgers.

The claim-only baseline deliberately says it read, patched, tested, searched, and produced a report without ledgers. It is accepted only if the system detects the unsupported claims.

## CLI

```powershell
python -m holo_host run-agent-real-use-drill --output artifacts\stage184\stage184_real_use_agent_drill.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Metrics

Stage184 records:

```text
case_count
passed_case_count
pass_rate
full_loop_score
claim_only_baseline_score
score_delta_vs_claim_only
baseline_failure_flags
failure_flag_counts
private_reasoning_free
```

## Topology

Stage135 exposes:

```text
stage184_real_use_drill
real_use_drill_node_count
real_use_drill_case_count
real_use_drill_passed_count
real_use_drill_full_loop_score
real_use_drill_claim_only_baseline_score
real_use_drill_status
```

## Boundaries

Stage184 does not add provider calls, memory writes, WeChat startup, transport widening, or hidden reasoning exposure. It confines engineering write actions to a temporary repository. Live-network dependence remains out of tests; deterministic mocked web providers are used so failures are attributable to Holo's tool loop and grounding logic, not external search-engine availability.

## Next Pressure

Stage184 identifies the next necessary hardening target: a live crawler/search drill that can run against real web pages when network is enabled, while keeping deterministic offline fixtures for regression.
