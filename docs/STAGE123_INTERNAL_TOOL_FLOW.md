# Stage123 Internal Tool Flow

Stage123 makes Holo's internal flow tool-aware. Stage122 separated internal
intent, local processing, and external speech; Stage123 adds the missing bridge:
when the internal flow needs evidence, memory, workspace state, lookup, or
verification, it may call tools before committing external speech.

This does not move execution authority into the provider. The provider can only
propose `tool_calls`. Holo validates and executes them locally through Stage113
inside the WSL brain, then re-enters the next provider packet with bounded tool
observations.

## Control Model

The loop is:

1. `internal_intent` decides whether the turn needs grounding
2. Stage123 exposes the relevant tool affordance to the provider packet
3. provider proposes `tool_calls`
4. Stage113 validates allowlist, arguments, and permission grants
5. Holo executes locally in WSL
6. bounded `tool_observation` re-enters the provider loop
7. `external_speech` is committed only after observations arrive or no tool is
   needed

The important distinction is:

- internal flow may decide that a tool should be called
- provider may propose tool calls
- only Holo's WSL Stage113 executor may execute tools
- Windows transport may not execute tools or become a second decision layer

## Runtime Data

`holo_host/stage123_internal_tool_flow.py` builds
`stage123_internal_tool_flow`:

- `internal_tool_calls`
  - whether tool calling is enabled
  - whether tools should be called before external speech
  - proposed tool names in the current bounded working set
- `tool_authority`
  - `provider_may_propose_tools=true`
  - `provider_may_execute_tools=false`
  - executor is `holo_wsl_brain_stage113`
- `loop_contract`
  - internal intent
  - provider tool call
  - Stage113 local execution
  - tool observation re-entry
  - external speech
- `external_expression_gate`
  - external speech requires an observation or a no-tool-needed state
  - tool results must not be fabricated

## Provider Prompt Contract

`CodexCliProcessor.generate()` appends a stable prompt block:

```text
Stage123 Internal Tool Flow:
- If internal_intent needs memory, evidence, lookup, workspace state, or verification, use exposed tool_calls before external_speech.
- Provider may propose tool_calls only; Holo Stage113 executes tools locally inside the WSL brain.
- Tool observations re-enter the next provider packet before external_speech is committed.
- Never fabricate tool results; if a tool is unavailable or rejected, explain the limitation in external_speech.
```

This block is stable and cacheable. The detailed per-turn flow remains local
metadata.

## Operator Surface

Inspect the internal tool-flow frame:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage123-internal-tool-flow --query '内部流需要调用记忆和仓库检查工具' --uncertainty 0.8 --tool memory_recall --tool workspace_inspect"
```

This command is read-only and does not spend provider tokens.

## Verification

```powershell
python -m pytest -q tests\test_stage123_internal_tool_flow.py --basetemp=.pytest_tmp_stage123
```
