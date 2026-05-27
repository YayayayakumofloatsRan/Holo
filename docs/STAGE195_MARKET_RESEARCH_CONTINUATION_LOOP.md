# Stage195 Market Research Continuation Loop

Stage195 adds a bounded market-research continuation loop over the Stage192/193/194 stack.

Stage192 evaluates whether a filing-grounded report is ready. Stage193 selects the next concrete action. Stage194 executes one host-supported action. Stage195 repeats that sequence with a strict round budget until the report is ready, a host boundary blocks progress, a tool fails, or the budget is exhausted.

## Schemas

- `holo.stage195.market_research_continuation_loop.v1`
- `holo.stage195.market_research_continuation_round.v1`

## Loop

The loop is:

```text
feedback -> plan -> execute -> observe -> feedback -> stop_or_continue
```

Each round records:

- Stage192 feedback
- Stage193-compatible action plan
- Stage194 execution result
- selected action
- executed/rejected/failed counters
- post-action feedback
- canonical stop reason

Stage195 can also convert newly observed authoritative filing web evidence into a `market_research_pack` action, allowing a bounded path such as:

```text
web_search -> market_research_pack -> market_research_report
```

## Runtime Surfaces

Stage195 is propagated into:

- `ReplyPlan.debug`
- reply JSON / outgoing metadata
- archive/observe metadata
- Stage153 event stream as `[market_continue]`
- Stage191 public thought stream as a self-feedback card
- Stage135 topology as `market_research_continuation_loop`

## Boundaries

Stage195 does not:

- call provider models
- write memory
- start WeChat
- widen transport authority
- expose raw hidden reasoning or provider `reasoning_content`
- run unbounded loops

Web and page actions still go through the existing host functions and respect `runtime.network_enabled`.

## Stop Reasons

Stage195 reports:

- `final_answer_ready` when the report is ready
- `boundary_or_permission` when network or host policy blocks execution
- `tool_failure_report` when a host tool fails
- `budget_exhausted` when the round budget is spent before readiness

## Acceptance

Stage195 is accepted when it can:

- run `market_research_report` after a ready pack and stop at readiness
- avoid web fetches when network is disabled
- stop after failed web search rather than looping indefinitely
- run a bounded `web_search -> market_research_pack -> market_research_report` sequence with mocked host tools
- expose continuation state in CLI/event/topology metadata without leaking hidden reasoning
