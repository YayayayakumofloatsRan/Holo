# Stage183 Agent Capability Gauntlet

Stage183 adds a Codex-style capability gauntlet for Holo's engineering agent kernel.

The goal is not another narrow unit test. The gauntlet evaluates whether Holo's current base can behave like a useful engineering/research agent:

```text
observe -> decide -> act -> ledger -> evaluate -> stop/final
```

It combines engineering execution, market research report generation, remediation continuation, and adversarial unsupported-claim detection into one inspectable scorecard.

## Schemas

```text
holo.stage183.agent_capability_gauntlet.v1
holo.stage183.agent_capability_case.v1
holo.stage183.agent_capability_scorecard.v1
```

## What It Tests

The default gauntlet covers:

```text
engineering_execution
market_research_report
remediation_continuation
adversarial_unsupported_claim
```

Each case checks:

- visible claim grounding against action ledgers;
- event-stream completeness;
- stop reason quality;
- hidden-reasoning absence;
- persona/social-language absence;
- engineering read/search/patch/test/diff evidence;
- filing-grounded market-research report readiness;
- Stage182 remediation continuation visibility.

Adversarial cases pass only when Holo detects the failure. A false confident success is a failed case.

## CLI

```powershell
python -m holo_host run-agent-capability-gauntlet --output artifacts\stage183\stage183_agent_capability_gauntlet.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Metrics

Each case records:

```text
evidence_integrity_score
action_trace_score
engineering_grounding_score
market_research_score
remediation_closure_score
search_grounding_score
stop_reason_score
privacy_score
persona_free_score
overall_score
failure_flags
```

The bundle summary reports case count, pass rate, overall score, and failure-flag counts.

## Topology

Stage135 exposes:

```text
stage183_agent_capability_gauntlet
agent_capability_gauntlet_node_count
agent_capability_gauntlet_case_count
agent_capability_gauntlet_passed_count
agent_capability_gauntlet_status
```

This makes practical agent readiness visible in the same topology surface as tool, memory, market-research, and remediation state.

## Boundaries

Stage183 does not add provider calls, memory writes, WeChat startup, transport widening, or hidden reasoning exposure. It uses deterministic local fixtures and existing host ledgers.

## Acceptance

Stage183 is accepted when:

- the default gauntlet covers the core categories;
- grounded engineering and market-research cases pass;
- Stage182 remediation continuation is required and visible;
- unsupported engineering overclaims are detected;
- CLI artifacts are written;
- Stage135 topology exposes the gauntlet node;
- targeted, runtime, and full regression tests pass.
