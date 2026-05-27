# Stage193 Market Research Action Planner

Stage193 turns the Stage192 market-research feedback loop into concrete next actions. Stage192 answers whether a filing-grounded report is ready. Stage193 answers what Holo should attempt next: search for authoritative filings, retrieve filing text, rebuild a market-research pack, generate a report, finalize, or stop because evidence/action budget is exhausted.

## Schemas

- `holo.stage193.market_research_action_plan.v1`
- `holo.stage193.market_research_action_candidate.v1`

## Runtime Role

Stage193 is planning-only. It does not execute web fetches, call providers, write memory, start WeChat, or widen transport authority. It consumes existing report evidence:

- `stage192_market_research_feedback_loop`
- `stage169_market_research_pack`
- `stage173_market_research_report`
- `market_research_pack_ledger`
- `market_research_report_ledger`

The planner records:

- `status`: `planned`, `no_action_needed`, `blocked`, or `exhausted`
- `next_action`: `web_search`, `filing_text_retrieval`, `market_research_pack`, `market_research_report`, `finalize_report`, or `report_insufficient_evidence`
- `action_candidates[]`: concrete action type, query/URL/arguments, required source family, expected observation, and block reason
- `stop_reason`: why planning can stop at this layer

## Policy

If Stage192 reports insufficient financial-filing source authority, Stage193 plans authoritative searches first, prioritizing SEC filings and then company investor-relations annual reports.

If the filing pack is sufficient but the report is missing or incomplete, Stage193 plans `market_research_report`.

If no action budget remains, Stage193 reports `exhausted`.

If a web-dependent action is needed while network is disabled, Stage193 reports `blocked` with `network_disabled`.

## Observability

Stage153 event stream renders Stage193 as:

```text
[market_plan] status=planned next=web_search candidates=2 first=web_search stop=action_plan_ready query=site:sec.gov Apple AAPL 2024 Form 10-K SEC filing
```

Stage191 public thought stream maps the same event to an `action_plan` card. Stage135 topology exposes a `market_research_action_plan` node and metrics for status, next action, and candidate count.

## Boundaries

- No hidden chain-of-thought is exposed.
- No provider call is added.
- No memory write is added.
- No tool execution is performed by this stage.
- No WeChat or transport authority is started or widened.
