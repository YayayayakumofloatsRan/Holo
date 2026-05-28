# Stage224 Engineering Workflow Policy

Stage224 adds an engineering workflow policy layer to Holo Agent Kernel
`2.1.0`.

## Purpose

Stage223 exposed primitive engineering tools. Stage224 tells the model how to
use them as a complete engineering loop and verifies that final engineering
claims are backed by observations.

## Workflow Policy

For engineering change tasks, the context now includes:

```text
workspace_search -> file_read -> apply_patch -> test_run -> git_diff -> git_status -> answer_direct
```

This is guidance for model arbitration, not a keyword playbook. The model still
chooses the next action. The host provides the workflow policy, executes tools,
records observations, and verifies final claims.

## Final Claim Verification

The host now checks final engineering claims against observation ledgers:

- read/open/inspect claims require `file_read` or `open_page`
- patch/modify/fix claims require `apply_patch`
- tests-passed claims require successful `test_run`
- diff/status/worktree claims require `git_diff` or `git_status`

If a final answer makes an unsupported engineering claim, the answer is repaired
to an explicit unverified-claim report and the turn stops as
`evidence_exhausted`.

## Current Gap

The policy is still local and heuristic at the final-claim layer. The next step
should add a model-based final evaluator:

```text
observations + candidate final -> model_evaluate_final -> host verify -> deliver
```

The deterministic verifier should remain as a hard safety backstop, not the
primary semantic judge.
