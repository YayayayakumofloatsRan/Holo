# Stage182 Remediation Continuation

Stage182 closes the Stage178 -> Stage179 -> Stage180 remediation loop by allowing bounded multi-round continuation over remaining evidence/action candidates.

The core flow is:

```text
evidence gap -> remediation action plan -> host execution -> observation ledger -> sufficiency score -> continue or stop
```

Stage180 executed one bounded remediation batch and then returned control to the FSM. Stage182 keeps the remaining action candidates visible and can run additional rounds within an explicit budget. This makes the action plan part of the live agent loop instead of a one-shot diagnostic.

## Schemas

```text
holo.stage182.remediation_continuation.v1
holo.stage182.remediation_continuation_bundle.v1
holo.stage182.remediation_sufficiency.v1
```

## Runtime Behavior

`run_live_remediation_continuation()` consumes a Stage179 live remediation loop and calls the Stage180 executor repeatedly:

- one or more actions per round, default one;
- bounded `max_rounds`;
- accumulated web, memory, and engineering ledgers;
- explicit remaining action candidates;
- canonical stop reasons:
  - `final_answer_ready`
  - `budget_exhausted`
  - `needs_user_clarification`
  - `boundary_or_permission`
  - `tool_failure_report`
  - `evidence_exhausted`

The reply API now uses Stage182 when a Stage179 remediation loop blocks finalization. The aggregate Stage180 execution report is still preserved for compatibility, while `stage182_remediation_continuation` records the multi-round controller state.

## Sufficiency Scoring

Stage182 scores whether executed remediation evidence is enough to finalize:

- web evidence must include usable source URLs, search evidence, and source-authority support;
- weak web evidence remains insufficient even if a tool technically executed;
- memory evidence requires grounded or weak memory observation rows;
- engineering evidence requires ok engineering action ledgers.

The score is diagnostic and bounded. It does not add provider calls or mutate memory.

## CLI

```powershell
python -m holo_host run-remediation-continuation --output artifacts\stage182\stage182_remediation_continuation.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

## Event Stream And Topology

The Stage153 event stream can render:

```text
[remediation_continue] status=<status> rounds=<n> executed=<n> stop=<reason>
```

Stage135 exposes a `stage182_remediation_continuation` topology node and compact metrics for node count, round count, execution count, and status.

## Boundaries

Stage182 preserves the existing authority boundaries:

- no provider model calls;
- no memory writes;
- no WeChat start;
- no transport authority widening;
- no hidden reasoning exposure;
- no write-action execution beyond the already-guarded Stage180 host surfaces;
- live network is not required for tests.

## Acceptance

Stage182 is accepted when multi-action plans can continue over multiple bounded rounds, remaining actions stay visible, sufficiency is scored, CLI artifacts are written, Stage135 shows the continuation node, and targeted remediation tests pass.
