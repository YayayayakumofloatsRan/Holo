# Stage215 Market Research Operator Live Action

Stage215 connects the Stage214 market-research operator run to the live reply path used by `python -m holo_host chat --trace`.

## Problem

Stage214 could execute a full market-research trajectory as a standalone CLI artifact, but ordinary Holo CLI turns could still answer financial-research requests with a generic capability statement. That broke the agent loop contract: the system said it could research, while the live turn did not actually execute the crawler, source promotion, pack, report, finalization, and action journal.

## Implementation

Stage215 adds `holo.stage215.market_research_operator_action.v1` in `holo_host/market_research_operator_live_action.py`.

When a `holo_cli`, `engineering`, `research`, or `project` turn requests an actionable market/financial/fundamental/filing-grounded research task, the reply path now:

1. Runs Stage214's `run_market_research_operator_run`.
2. Copies the Stage214 operator run and key downstream ledgers into `capability_context`, sidecar/debug metadata, reply JSON, outbound metadata, and archive metadata.
3. Uses the operator's finalized visible report as the reply text when the run produces one.
4. Renders operator phases in Stage153 event stream as `[market_operator]` rows.

The dry-run path remains deterministic for tests. Live runs use the configured network gate and existing host search/open-page functions.

## Public Trace

The event stream exposes auditable process rows only:

```text
[market_operator] phase=action status=executed ...
[market_operator] phase=plan status=planned ...
[market_operator] phase=crawl status=sufficient ...
[market_operator] phase=promote_source status=promoted ...
[market_operator] phase=build_pack status=ready ...
[market_operator] phase=build_report status=evidence_ready ...
[market_operator] phase=assemble_report status=assembled ...
[market_operator] phase=finalize status=finalized ...
```

Raw hidden reasoning and provider internal messages remain private.

## Boundaries

- No WeChat start.
- No new provider call path outside the existing reply path.
- No memory reset or durable policy mutation.
- No hidden chain-of-thought exposure.
- Stage214 remains the single market-research operator implementation; Stage215 only attaches it to live turns.
