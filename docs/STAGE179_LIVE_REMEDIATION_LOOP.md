# Stage179 Live Remediation Loop

Stage179 connects Stage178 evidence/action remediation back into the live agent-loop FSM.

The control rule is:

```text
failed evidence gate -> remediation actions -> FSM next-action state -> event stream -> bounded final
```

Stage178 already classified evidence gaps into concrete actions. Stage179 makes those actions operationally visible to the live loop so Holo does not stop at a passive report.

## Schemas

```text
holo.stage179.live_remediation_loop.v1
holo.stage179.live_remediation_loop_simulation.v1
```

## Runtime Behavior

When a Stage178 report says `can_finalize=false`, Stage179:

- converts remediation actions into `next_action_candidates`
- selects the first bounded next action as `selected_next_action`
- writes `remediation_decide` and `remediation_plan` FSM steps
- sets a canonical stop reason such as `evidence_exhausted` or `tool_failure_report`
- replaces unsafe draft text with the Stage178 operator message
- exposes `[remediation]` events in the CLI event stream
- exposes a `live_remediation_loop` node in Stage135 topology

When Stage178 says `can_finalize=true`, Stage179 does not override the final answer.

## CLI Simulation

```powershell
python -m holo_host run-live-remediation-simulation --output artifacts\stage179\stage179_live_remediation_loop.html --dry-run
```

The command writes `.html`, `.json`, and `.jsonl` artifacts.

The simulation uses deterministic fixtures covering:

- literature source gaps
- mathematical derivation gaps
- GPU experiment failures
- unsupported memory claims
- unexecuted tool claims
- evidence conflicts
- scope mismatches

## Boundaries

Stage179 is a live-loop bridge, but it remains offline and diagnostic by default.

It does not:

- call provider models
- fetch network data
- execute tools
- write memory
- start WeChat
- widen transport authority
- expose hidden reasoning

## Why It Matters

This is the final connection needed for the current evidence-action arc. Holo can now turn failed retrieval, tool, memory, experiment, or derivation evidence into the next action visible inside the same agent loop. That is the practical core of the observe -> decide -> act-or-skip -> observe-result -> evaluate-stop -> final pattern.
