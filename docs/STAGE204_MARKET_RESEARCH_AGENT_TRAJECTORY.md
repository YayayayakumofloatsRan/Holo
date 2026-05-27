# Stage204 Market Research Agent Trajectory

Date: 2026-05-28

## Purpose

Stage203 made the persisted dossier resume action visible in the CLI. Stage204 makes it useful as a longer agent trajectory.

When `market_research_dossier_resume` is invoked with a larger action budget, Holo can now resume the latest persisted dossier, execute the first recorded next action, then continue through the existing Stage195 bounded market-research loop. A single model-selected host action can therefore produce an inspectable sequence such as:

```text
web_search -> market_research_pack -> market_research_report
```

## Schema

- `holo.stage204.market_research_agent_trajectory.v1`
- `holo.stage204.market_research_trajectory_row.v1`

## Runtime Behavior

`run_market_research_dossier_agent_trajectory()` performs:

1. Stage201 registry lookup.
2. Stage200 dossier resume for the first next action.
3. Optional Stage195 continuation for remaining action budget.
4. A unified trajectory row list with action, status, observation count, source count, and stop reason.

Stage202 now uses Stage204 under the hood. Stage152 native DeepSeek tool execution returns the Stage204 trajectory and Stage195 continuation loop when `market_research_dossier_resume` is called with `max_actions > 1`.

## CLI Trace

Stage153 renders trajectory rows as:

```text
[market_trajectory] step=1 action=web_search phase=resume_action status=resumed obs=1 sources=1 stop=final_answer_ready
[market_trajectory] step=2 action=market_research_pack phase=continuation_round status=executed obs=1 sources=0 stop=final_answer_ready
[market_trajectory] step=3 action=market_research_report phase=continuation_round status=executed obs=1 sources=0 stop=final_answer_ready
```

This is a public action/observation trace. It does not expose hidden chain-of-thought or raw provider reasoning.

## Topology

Stage135 adds `market_research_agent_trajectory` topology evidence and metrics:

- `market_research_agent_trajectory_node_count`
- `market_research_agent_trajectory_status`
- `market_research_agent_trajectory_step_count`

## Boundaries

Stage204 does not add a provider call path, memory writes, WeChat startup, transport widening, or hidden reasoning exposure. It reuses the existing Stage201, Stage200, Stage195, Stage194, web, pack, and report ledgers.
