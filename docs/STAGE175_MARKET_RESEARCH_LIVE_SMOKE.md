# Stage175 Market Research Live Smoke

Stage175 adds a deterministic live-smoke harness for Holo's market-research agent path. It is not another offline report generator. It runs a provider-free simulation through the same kernel surfaces that a live turn should use:

1. a model-proposed native `market_research_report` tool call,
2. Stage152 host tool execution and ledgers,
3. Stage174 report action and Stage173 filing-grounded report,
4. Stage160R agent-loop FSM validation,
5. Stage153 event stream rendering,
6. Stage135 topology visibility,
7. a Codex/Claude-Code-style scorecard.

## Schema

```text
holo.stage175.market_research_live_smoke.v1
holo.stage175.market_research_live_smoke_result.v1
holo.stage175.codex_style_market_research_scorecard.v1
```

## CLI

```powershell
python -m holo_host run-market-research-live-smoke --output artifacts\stage175\stage175_market_research_live_smoke.html --dry-run
```

The command writes:

```text
.html
.json
.jsonl
```

`--dry-run` remains deterministic and requires no live provider or network access.

## Scorecard

The scorecard checks whether Holo's market-research path behaves like an auditable agent console:

```text
model_decide_visible
report_ledger_exists
report_ready
primary_citations_present
unsupported_claim_rate_low
stop_reason_known
trace_visibility
topology_visibility
privacy
persona_free
```

Ready evidence must come from primary filing-like sources such as SEC URLs. A weak third-party source fixture is intentionally included and must not be promoted as an evidence-ready research report.

## Boundaries

Stage175 preserves the existing kernel constraints:

```text
no provider model calls
no memory writes
no WeChat start
no transport authority widening
no live network requirement for tests
no hidden reasoning exposure
```

The harness is a reliability and observability gate for future market-research domain work.
