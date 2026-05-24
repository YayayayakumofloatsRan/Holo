# Stage138 System Optimization Tasks And Tool Calling Track

Date: 2026-05-24

## Purpose

Stage138 turns the current Holo prototype into a task-driven optimization program. The project already has a large set of components: memory, provider packet flow, processor lanes, tool adapters, CLI, WeChat transport, topology traces, and research documents. The next stage should stop treating each feature as an isolated stage. Each improvement must target one measurable system weakness and leave behind tests, docs, and operator-facing diagnostics.

The first optimization track is tool calling, because it directly affects hallucination, factual grounding, agent agency, and the user's ability to trust Holo's self-reports.

## Current Technical Baseline

| Area | Ordinary Provider Chat | Current Holo | Target Holo |
|---|---|---|---|
| Subject continuity | Provider session context only | WSL main brain, thread keys, memory stores, active thread state | Single subject state with every reply, tool result, visual observation, and memory writeback updating one I-state |
| Packet flow | One prompt, one answer | Stage124 fast packet, Stage132 progressive stream, optional deep packet | Reaction-kernel first response, explicit state delta, semantic continuation gate, tool/memory/vision reentry |
| Memory | Chat history or simple RAG | Working memory, archive, mind graph, vector memory, warehouse view | Source-traceable memory with short-term persistence, confidence, contradiction handling, and answer-level citation |
| Tool calling | Provider may expose function calling | Stage106 adapter, Stage113 local executor, Stage120 bounded tool selection, Stage129 DSML bridge | Tool-first agent loop where claims are blocked or repaired unless backed by an observation |
| Tool library | Usually small or ad hoc | 41 common tools; ordinary turns bounded to <=18 tools | Dynamic affordance set based on task, permission, recent failures, token budget, and cache value |
| Permission model | Provider or app decides | WSL executes tools; modifying tools require grants | Mutating actions require explicit operator approval, audit trail, tests, and post-action verification |
| Visibility | Mostly hidden | Stage131 CT, Stage135 topology, `/topology` latest trace | Continuous live topology with packet, tool, memory, visual, and state-delta playback |
| Evaluation | Manual conversation | Stage136 simulated dialogue; targeted pytest suites | Categorized benchmark suite with repetition, tool precision, recall accuracy, latency, and hallucination metrics |

## Verified Tool Calling Baseline

Fresh baseline command:

```powershell
python -m pytest -q tests/test_stage106_deepseek_tool_adapter.py tests/test_stage113_agent_tool_executor.py tests/test_stage115_deepseek_agent_tool_loop.py tests/test_stage116_multiround_agent_tools.py tests/test_stage117_complete_agent_tooling.py tests/test_stage118_tool_expansion.py tests/test_stage119_tool_library_expansion.py tests/test_stage120_tool_affordance_optimizer.py tests/test_stage123_internal_tool_flow.py --basetemp .holo_runtime\pytest-tmp-stage138-tool-baseline
```

Observed result:

```text
39 passed in 14.43s
```

Tool selection probe:

```powershell
python -m holo_host stage120-tool-affordance --query "inspect workspace, run pytest, check git diff, then explain tool evidence"
```

Observed result:

- library tools: `41`
- selected tools: `18`
- selected groups: `workspace`, `git`, `tests`
- selected examples: `workspace_inspect`, `git_status`, `git_diff`, `test_runner`, `file_read`, `symbol_search`

Stage123 internal tool-flow probe already states the intended contract:

- provider proposes tool calls;
- WSL Stage113 executes allowlisted tools;
- observations re-enter the next provider packet;
- visible speech must not fabricate tool results.

The remaining issue is enforcement. The contract exists, but visible answers can still contain ungrounded workspace, file, runtime, search, or test claims when no matching tool observation exists.

## Global Optimization Program

### P0: Trust And Grounding

1. Tool claim grounding gate.
   - Problem: Holo can claim it inspected the workspace without a matching observation.
   - Deliverable: visible reply guard that detects tool-dependent claims and requires a matching Stage113 observation.
   - Acceptance: a simulated reply that claims directory contents without `workspace_inspect` is repaired or marked ungrounded.

2. Memory answer grounding gate.
   - Problem: memory answers may sound confident while relying on weak or stale recall.
   - Deliverable: answer metadata with memory source class, confidence, selected ids, and missing-source fallback.
   - Acceptance: explicit memory questions produce traceable memory source fields or say the source is unavailable.

3. A-prime to A-double-prime novelty gate.
   - Problem: second bubbles may repeat or contradict the first bubble.
   - Deliverable: semantic-role and contradiction check before final bubble emission.
   - Acceptance: duplicated A' and A'' test cases collapse to one bubble or force A'' to add a new role.

4. Latency and cost budget gate.
   - Problem: deep calls and recall reconstruction can stack without clear utility.
   - Deliverable: per-turn packet budget report with stop reason, cache hint, token estimate, and elapsed time.
   - Acceptance: CLI JSON shows why each packet was sent or skipped.

### P1: Agent Capability

5. Tool observation ledger.
   - Problem: tool results live inside provider metadata but are not always first-class in reply state.
   - Deliverable: normalized per-turn `tool_observation_ledger` attached to reply JSON, memory metadata, and Stage135 topology.
   - Acceptance: `/topology` can show actual tool nodes and statuses from the last reply.

6. Tool need classifier.
   - Problem: tool exposure is bounded, but need detection still relies too much on prompt/provider behavior.
   - Deliverable: deterministic pre-provider classifier for read workspace, read memory, search web, run tests, inspect git, write file, and modify command.
   - Acceptance: categorized cases choose expected tool group before provider call.

7. Tool failure recovery.
   - Problem: rejected or failed tools may lead to weak final speech.
   - Deliverable: follow-up packet includes explicit failure reason and asks provider to answer with the limitation.
   - Acceptance: rejected modifying command produces a concise permission-required response.

8. Tool-use benchmark suite.
   - Problem: no continuous metric for tool precision.
   - Deliverable: replay set of categorized prompts with expected tool needs and forbidden claims.
   - Acceptance: report includes precision, recall, skipped count, ungrounded claim count, and latency.

### P2: Research Instrumentation

9. Continuous topology replay.
   - Problem: Stage135 topology is visible per latest reply, but not yet a moving trajectory.
   - Deliverable: replay artifact showing multi-turn state, packet, memory, and tool graph motion.
   - Acceptance: a Stage136-style conversation generates a graph sequence with one frame per reply.

10. Reaction-kernel parameter layer.
    - Problem: reaction tendencies are mostly prompt/rule driven.
    - Deliverable: local parameter object for style, risk, memory trust, tool preference, and continuation threshold.
    - Acceptance: feedback can update parameters without touching base model weights.

11. Visual perception bridge.
    - Problem: Holo has no reliable camera-derived world state.
    - Deliverable: sensor module that stores derived visual scene state and exposes read-only visual observations to the main brain.
    - Acceptance: visual input creates a state delta without raw camera frames entering provider prompts by default.

12. Publication benchmark.
    - Problem: project has a proposal but not enough experimental results.
    - Deliverable: baseline comparison: single-call, simple RAG, fixed two-bubble, multi-packet, full RK-CSM.
    - Acceptance: report includes metrics and ablations for memory, tool, continuation, and visualization components.

## Tool Calling Track: Detailed Task List

### Task 1: Tool Observation Ledger

Files:

- Modify: `holo_host/codex_runner.py`
- Modify: `holo_host/reply_api.py`
- Modify: `holo_host/stage135_i_state_topology.py`
- Test: `tests/test_stage115_deepseek_agent_tool_loop.py`
- Test: `tests/test_holo_host.py`
- Test: `tests/test_stage135_i_state_topology.py`

Implementation:

1. Add `tool_observation_ledger` to DeepSeek provider metadata.
2. Each ledger row should include `provider_call_id`, `tool`, `status`, `summary`, `data_keys`, and `grounding_tags`.
3. Propagate the ledger through `ReplyPlan.debug`.
4. Persist it in reply result metadata and archive metadata.
5. Add Stage135 topology nodes for actual observations, not only requested tools.

Acceptance:

- A mocked provider tool loop returns one `workspace_inspect` observation.
- Reply JSON includes `tool_observation_ledger`.
- Stage135 topology includes a matching `tool_observation` node.

### Task 2: Tool Claim Grounding Gate

Files:

- Create: `holo_host/tool_grounding.py`
- Modify: `holo_host/reply_api.py`
- Test: `tests/test_tool_grounding.py`
- Test: `tests/test_holo_host.py`

Implementation:

1. Implement a deterministic claim scanner for workspace, file, git, test, web lookup, runtime, and memory-warehouse claims.
2. Map claim families to required tools:
   - workspace/files: `workspace_inspect`, `file_read`, `file_list`, `file_search`, `repo_overview`
   - git: `git_inspect`, `git_status`, `git_diff`, `git_log`
   - tests: `test_runner`, `test_discover`, `python_module_check`
   - web/current facts: `external_lookup`
   - runtime/env: `runtime_health`, `config_inspect`, `env_read`, `dependency_check`
3. If the visible reply makes a claim without a matching observation, add `grounding_status=ungrounded_tool_claim`.
4. For CLI and Holo app replies, repair the text to say the inspection was not executed.
5. For WeChat, keep the repair concise and avoid exposing internal machinery.

Acceptance:

- Text claiming "I checked the directory and saw docs" without observations is repaired.
- Text summarizing a real `workspace_inspect` observation passes.
- Rejected tools produce a visible limitation, not a fabricated result.

### Task 3: Tool Need Classifier

Files:

- Create: `holo_host/tool_need.py`
- Modify: `holo_host/processors.py`
- Modify: `holo_host/stage120_tool_affordance_optimizer.py`
- Test: `tests/test_tool_need.py`
- Test: `tests/test_stage120_tool_affordance_optimizer.py`

Implementation:

1. Add deterministic classification before provider call:
   - `needs_workspace`
   - `needs_git`
   - `needs_tests`
   - `needs_memory`
   - `needs_external_lookup`
   - `needs_runtime`
   - `needs_mutation_permission`
2. Feed classifier output into Stage120 tool group selection.
3. Add classifier values to Stage132/Stage135 metadata.
4. Keep provider authority to propose exact calls, while host decides which tool families are exposed.

Acceptance:

- "read your own directory" exposes workspace tools.
- "run tests" exposes test tools and git status.
- "search latest paper" exposes external lookup.
- "write/modify/commit" exposes mutation tools only with grants or as rejected affordances.

### Task 4: Tool Failure Reentry

Files:

- Modify: `holo_host/codex_runner.py`
- Modify: `holo_host/processors.py`
- Test: `tests/test_stage116_multiround_agent_tools.py`
- Test: `tests/test_stage117_complete_agent_tooling.py`

Implementation:

1. When a tool is rejected, create a tool observation message with `status=rejected` and `reason`.
2. Add a provider follow-up instruction: answer based on the rejection; do not claim the tool succeeded.
3. Add result metadata: `tool_failure_reentry=true` when any rejected tool was returned to the provider.

Acceptance:

- A rejected `command_modify` call leads to a final answer that says permission is required.
- No raw provider tool markup leaks to visible speech.

### Task 5: Tool Benchmark Suite

Files:

- Create: `holo_host/tool_benchmark.py`
- Create: `tests/test_tool_benchmark.py`
- Create: `docs/STAGE139_TOOL_CALLING_BENCHMARK.md`

Implementation:

1. Define benchmark cases:
   - workspace read
   - memory recall
   - git inspect
   - test run
   - web lookup
   - rejected mutation
   - no-tool casual chat
2. For each case, record expected tool families and forbidden visible claims.
3. Run deterministic provider-mocked tests first.
4. Add optional live DeepSeek smoke mode with network/API key.

Acceptance:

- Deterministic benchmark produces precision, recall, ungrounded claim count, and mean simulated latency.
- Live mode is opt-in and never runs WeChat.

## System Optimization Order

1. Stage138: tool observation ledger and grounding gate.
2. Stage139: tool benchmark suite and live smoke summary.
3. Stage140: A' to A'' novelty and contradiction gate.
4. Stage141: memory answer grounding and source trace.
5. Stage142: continuous topology replay across multi-turn sessions.
6. Stage143: reaction-kernel parameter layer.
7. Stage144: visual perception bridge prototype.
8. Stage145: publication-grade ablation report.

## Success Criteria For The Tool Track

Holo reaches the next practical level when all of these are true:

1. It calls a read tool before making workspace, file, git, runtime, test, or current-fact claims.
2. It says clearly when a tool was unavailable, rejected, or not executed.
3. It does not leak provider tool markup into visible speech.
4. It records tool observations in reply JSON, memory archive metadata, and Stage135 topology.
5. It can run a benchmark that measures tool precision, tool recall, latency, and ungrounded claim rate.
6. It preserves the single-main-brain boundary: provider proposes, WSL Holo executes, transports only carry messages.
