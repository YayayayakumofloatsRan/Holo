# Stage231 Context Kernel And Dynamic Final Contract

Kernel version remains `2.1.0`.

## Purpose

Stage231 fixes a foundational agent-console failure: Holo could choose
`answer_direct` for a normal capability question, then answer:

```text
I do not have a tool observation for this request yet.
```

That was a kernel-level issue. The runtime lacked a clean distinction between:

- capability explanation
- plan or intent
- attempted failure report
- completed action/result claim
- ordinary direct answer

The old verifier treated capability language such as "I can read files and run
tests" as if Holo had claimed that it already read files and ran tests.

## Context Kernel

Stage231 adds `holo_agent.context_kernel`.

It builds a structured context pack:

```text
stable_prefix
instruction_chain
operator_metadata
selected_operator_brief
action_space
working_state
observation_ledger_window
self_feedback_reports
final_constraints
exact_user_message
```

Important properties:

- The stable prefix does not include dynamic observations.
- Exact current user text is preserved near the end.
- Tool results remain observations, not chat history.
- Skills/operators are progressively disclosed: metadata is always visible;
  the selected operator brief can load the full body.
- Executable compact state preserves last action, last observation, unresolved
  evidence gaps, recommended next action, and stop reason.
- Low-priority old observations are truncated before the exact user request.

This aligns Holo with the Codex-style idea that context is a rendered work
state, not raw conversation history or a memory dump.

## Dynamic Final Contract

Stage231 adds `holo_agent.final_answer_contract`.

The contract is not a hard reply-type gate. It performs claim-obligation
analysis:

```text
visible final text
+ current user request
+ action space/context
+ observation ledger
-> claim obligations
-> missing required ledgers, if any
```

Examples:

- "I can read files and run tests" is a capability statement. It creates no
  completion ledger obligation.
- "I read README.md, patched it, and tests passed" creates `file_read`,
  `apply_patch`, and `test_run` obligations.
- "open_page was attempted but failed: HTTP Error 403" is a failure report and
  is valid when a failed `open_page` observation exists.

The answer type remains metadata for inspection. The actual validation uses
claim obligations and observation ledgers.

## Runtime Integration

The agent now inserts:

```text
context.context_pack
context.rendered_context
metadata.context_pack
metadata.final_answer_contract
```

The event stream shows:

```text
[final_contract] capability_statement
```

or another auditable contract class.

## Live Verification

WSL command:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run '？？？你现在可以做什么？' --trace --model fallback"
```

Observed result:

```text
[model_decide] selected=answer_direct
[final_contract] capability_statement
[stop] final_answer_ready
```

Final answer now lists concrete capabilities instead of the previous tool
observation error.

## Test Verification

Targeted:

```powershell
python -m pytest tests\test_stage231_context_kernel.py tests\test_stage231_final_answer_contract.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage231-targeted2
```

Result:

```text
10 passed
```

Neighbor + full:

```powershell
python -m pytest tests\test_stage224_engineering_workflow_policy.py tests\test_stage230_self_feedback_loop.py tests\test_stage231_context_kernel.py tests\test_stage231_final_answer_contract.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage231-neighbor2
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
18 passed
85 passed
```
