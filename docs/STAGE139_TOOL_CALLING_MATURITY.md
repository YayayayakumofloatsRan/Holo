# Stage139 Tool Calling Maturity

Date: 2026-05-24

## Purpose

Stage139 turns the Stage138 tool-calling plan into an enforceable runtime layer. The target is not merely to expose more tools to a provider. The target is a mature Holo agent loop in which the provider may propose actions, WSL Holo validates and executes them, tool observations re-enter the next provider packet, and visible speech is checked against the actual observation ledger.

This follows the DeepSeek function-calling contract: external tools enhance model capability, but the model itself does not execute the functions. Holo therefore keeps execution authority inside the WSL main brain. DeepSeek's reasoner documentation also states that `deepseek-reasoner` does not support Function Calling, so tool execution remains attached to chat/flash style provider packets while reasoner use should stay on non-tool deliberation paths.

## What Landed

### Tool Observation Ledger

`holo_host/tool_grounding.py` now normalizes Stage113 execution reports into a stable `tool_observation_ledger`. Each row records:

- `provider_call_id`
- `tool`
- `status`
- `summary`
- `data_keys`
- `grounding_tags`

`DeepSeekProvider` attaches this ledger both inside `metadata["agent_tool_loop"]` and at top level as `metadata["tool_observation_ledger"]`. Rejected or skipped tools now set `tool_failure_reentry=true`, so follow-up packets can answer from the failure rather than pretending a tool succeeded.

### Tool Claim Grounding

Visible replies are now checked for tool-dependent claims. If Holo says it checked a workspace, file, git state, runtime, tests, web/current fact, command, or memory source without a matching observation family, `HoloReplyService` marks the reply as `ungrounded_tool_claim` and repairs the visible text to say the inspection was not executed.

This directly addresses the earlier failure mode where Holo claimed to have inspected its WSL directory without an executed tool call.

### Tool Need Classifier

`holo_host/tool_need.py` adds a deterministic pre-provider classifier for:

- workspace
- memory
- docs
- git
- tests
- external lookup
- runtime
- artifacts
- time
- mutation permission

`Stage120` now consumes this classifier when constructing the bounded tool working set. This keeps ordinary turns below the tool budget while preserving task-relevant tools such as `file_read`, `test_runner`, `git_diff`, or `external_lookup`.

Permissioned mutation tools still require grants. The optimizer prioritizes non-library explicit requests, granted tools, baseline tools, and topic tools before trimming.

### Stage135 Topology Integration

Stage135 topology now renders actual observation nodes from `tool_observation_ledger`, not only abstract requested tool nodes. A real `workspace_inspect` observation appears as a `tool_observation_*` node with an edge back into `state_delta`.

This is important for the biomimetic visualization path: the graph now shows whether tool evidence actually re-entered Holo's I-state before the visible answer.

### Tool Benchmark CLI

`holo_host/tool_benchmark.py` defines a deterministic benchmark for:

- workspace read
- memory recall
- external latest lookup
- git diff
- pytest run
- runtime health
- mutation requiring permission
- no-tool casual chat

Run it with:

```bash
python3 -m holo_host stage139-tool-benchmark
```

The report includes tool precision, tool recall, and ungrounded claim count. Current deterministic probe result was:

```text
case_count=8
tool_precision=1.0
tool_recall=1.0
ungrounded_claim_count=1
```

The one ungrounded case is intentional: it verifies that a workspace claim without a tool observation is detected.

## Operator Contract

Holo's tool authority is now:

1. Provider proposes tool calls.
2. WSL Holo validates allowed tools and permissions.
3. WSL Holo executes the tool or records rejection.
4. Tool observations are sent back to the provider as bounded `role=tool` messages.
5. The final visible reply is checked against the observation ledger.
6. Stage135 topology exposes the packet, tool, memory, and state-delta path.

This preserves the single-main-brain rule. Transports do not execute or decide. Provider output is not trusted as action completion. Tool observations become state evidence.

## Verification

Targeted regression:

```powershell
python -m pytest tests/test_tool_benchmark.py tests/test_tool_grounding.py tests/test_tool_need.py tests/test_stage120_tool_affordance_optimizer.py -q
```

Result:

```text
13 passed in 0.97s
```

Tool-chain regression:

```powershell
python -m pytest tests/test_stage106_deepseek_tool_adapter.py tests/test_stage113_agent_tool_executor.py tests/test_stage114_agent_tool_cycle.py tests/test_stage115_deepseek_agent_tool_loop.py tests/test_stage116_multiround_agent_tools.py tests/test_stage117_complete_agent_tooling.py tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py tests/test_stage123_internal_tool_flow.py -q
```

Result:

```text
42 passed in 9.22s
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
479 passed in 86.76s
```

## Remaining Work

Stage139 matures the core tool loop, but several higher-level problems remain:

- memory answers still need source-level grounding similar to tool grounding;
- A' and A'' still need semantic novelty and contradiction checks;
- topology is per-turn, not yet a multi-turn moving replay;
- live DeepSeek smoke tests should remain opt-in and should never start WeChat;
- reasoner integration should be separated from function-calling paths because `deepseek-reasoner` does not support tool calling.
