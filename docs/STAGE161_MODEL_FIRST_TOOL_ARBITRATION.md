# Stage161 Model-First Tool Arbitration

Date: 2026-05-27

## Purpose

Stage161 moves Holo away from keyword-first tool routing. The agent kernel now treats deterministic intent and Stage151 triage as weak hints, while the model sees a structured action space and proposes the next action. The host remains the authority for execution, rejection, ledger recording, stop reasons, and final-claim verification.

Core rule:

```text
LLM proposes.
Host executes.
Ledger proves.
Stop controller closes.
```

## Added Surfaces

```text
holo_host/tool_action_space.py
holo_host/model_tool_arbitration.py
holo_host/tool_decision_contract.py
holo_host/agent_loop_policy.py
```

Schemas:

```text
holo.stage161.tool_action_space.v1
holo.stage161.model_tool_arbitration.v1
holo.stage161.tool_decision_contract.v1
holo.stage161.agent_loop_policy.v1
```

## Action Space

The model-visible action space contains:

```text
answer_direct
ask_clarification
memory_recall
time_observe
web_search
open_page
find_in_page
workspace_search
file_read
apply_patch
test_run
git_status
git_diff
project_state_read
project_state_update
defer
```

Each action declares its input schema, observation schema, risk level, network/workspace requirements, read-only status, and examples. This is rendered into the provider prompt as a structured affordance list instead of being hidden behind host keyword logic.

## Model Arbitration

`build_tool_arbitration_prompt()` renders the exact user turn, structured context packet, goal state, prior observations, and action space. `decide_next_action_with_model()` parses the model's JSON decision into the public Stage161 schema. Deterministic hints can be included, but they are explicitly labeled weak and do not force routing.

DeepSeek native tool calls from Stage152 are normalized as model-proposed actions through `derive_arbitration_from_stage152()`. If DeepSeek returns no tool calls, the host treats that as `answer_direct` and still validates the final answer against ledgers.

## Host Guardrails

`validate_tool_decision()` checks:

- selected action exists in the action space;
- required arguments are present;
- network tools respect `network_enabled`;
- workspace actions require workspace availability.

`validate_answer_direct_against_ledgers()` blocks unsupported visible claims:

- current/web claims require web or time observation;
- memory claims require memory observation;
- read/patch/test/git claims require engineering action ledger evidence.

## Runtime Integration

`reply_api.py` no longer upgrades Stage151 keyword triage into eager web execution by default. It builds Stage161 action space and deterministic hints before generation, then derives or propagates the model arbitration after provider output. Stage160R's FSM now accepts `model_arbitration` and records a `model_decide` step when a Stage161 decision is present.

`processors.py` renders the Stage161 action space into the provider prompt and records `stage161_model_tool_arbitration` in `ReplyPlan.debug` when Stage152 tool-loop metadata is available.

Stage153 CLI event streams now show:

```text
[action_space] count=...
[model_decide] selected=...
```

Stage135 topology exposes a `model_tool_arbitration` node.

## Boundaries

Stage161 does not add a new provider call path in runtime. It does not write memory, start WeChat, widen transport authority, expose hidden reasoning, or reintroduce persona behavior in `holo_cli`. The model proposes actions; the host verifies everything before final delivery.

## CLI Expectation

For requests such as:

```text
回忆一下上次和你的对话是什么样的
联网搜索codex的官方文档
搜索一下apple
```

the console trace should show model arbitration and host execution/rejection evidence. If a tool fails, the final text must report the attempted failure instead of saying it will search later or guessing from persona-style context.
