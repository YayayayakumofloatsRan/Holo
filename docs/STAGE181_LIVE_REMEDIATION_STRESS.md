# Stage181 Live Remediation Stress

Stage181 adds adversarial stress coverage for the Stage178 -> Stage179 -> Stage180 remediation arc.

The control rule is:

```text
evidence gap -> next action -> host-safe execution -> observation ledger -> FSM re-entry -> adversarial stress score
```

Stage180 proved that a next action can execute. Stage181 verifies that the loop does not falsely finalize under harder cases.

## Schema

```text
holo.stage181.live_remediation_stress.v1
```

## Stress Cases

Stage181 covers:

```text
primary web search failure followed by fallback success
multi-action budget exhaustion with remaining remediation candidates
missing artifact path requiring clarification
network-disabled web action rejection
```

The important correction is that execution success for one action is not enough to close the loop when required actions remain.

## Runtime Effects

Stage181 hardens Stage180 behavior:

- `web_search` accepts fallback-provider success even if the primary provider failed first.
- reports include `attempted_count`, `skipped_count`, `remaining_action_candidates`, `next_action_required`, and `continuation_reason`.
- multi-action budget exhaustion returns `partial` with `canonical_stop_reason=budget_exhausted`.
- missing artifact paths return `needs_user_clarification`, not a generic boundary failure.
- FSM re-entry preserves only remaining action candidates after partial execution.
- rejected or failed executions enter the FSM as attempted execution, not as a stale planned remediation state.

## CLI

```powershell
python -m holo_host run-live-remediation-stress --output artifacts\stage181\stage181_live_remediation_stress.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Boundaries

Stage181 does not:

- call provider models
- require live network in tests
- execute write actions
- write memory
- start WeChat
- widen transport authority
- expose hidden reasoning

## Why It Matters

This stage prevents a common false-positive agent failure: one successful observation should not make the agent declare completion when the action budget skipped remaining required evidence. That matters for engineering, market research, literature review, and GPU experiment loops where incomplete evidence is worse than an honest stop.
