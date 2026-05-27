# Stage174 Market Research Report Action

Stage174 connects the Stage173 report generator back into Holo's live agent tool loop.

## Purpose

Stage173 made market-research reports available as deterministic artifacts. Stage174 makes that capability usable by the agent kernel:

- the model can choose `market_research_report` from the structured action space;
- the WSL host executes or rejects the action;
- the host records `market_research_report_ledger`;
- Stage152 native DeepSeek tool calls can request the action;
- Stage160R FSM, Stage153 event stream, reply metadata, and Stage135 topology can inspect the action.

This moves market research closer to a real Claude Code-style workflow: model proposes, host executes, ledger proves, stop controller closes.

## Schemas

```text
holo.stage174.market_research_report_action.v1
holo.stage174.market_research_report_ledger.v1
```

Stage174 reuses:

```text
holo.stage173.market_research_report.v1
holo.stage169.market_research_pack.v1
```

## Host Action

```text
market_research_report
```

Inputs:

```text
query
filing_type
filing_text
source_url
web_observation_ledger
market_research_pack
market_research_pack_ledger
```

Behavior:

- if a Stage169 pack is supplied, generate a Stage173 report from it;
- if a Stage171 pack ledger is supplied, extract the nested Stage169 pack;
- if no pack exists, build the pack from authoritative filing inputs first;
- if the pack/report is insufficient, record bounded failure instead of claiming completion.

## Live Surfaces

Stage174 propagates through:

```text
DEEPSEEK_NATIVE_TOOL_REGISTRY
tool_action_space
stage152_deepseek_tool_loop
stage160r_agent_loop_fsm
stage153_agent_event_stream
ReplyPlan.debug / reply JSON / archive metadata
Stage135 topology
```

## Boundaries

Stage174 does not add:

- provider model calls outside processor fabric
- memory writes
- WeChat starts
- transport authority widening
- hidden reasoning exposure
- approval or sandbox policy changes
