# Kernel v3 Progress: System Time and Resident Scheduling

Date: 2026-06-06

## Purpose

This pass closes the basic resident/runtime gaps exposed by live interaction:
time questions must route to the host time tool, resident background work needs
priority, and reminder-like user input needs to become local schedules without
letting the model write directly into resident state.

The boundary remains host-owned. The model may emit semantic packets such as
`time_query` with `required_capabilities=["system.time"]`; the host normalizes
that packet, validates the recipe, executes `system.time`, and journals the
observation. Resident reminders are compiled by the host queue/scheduler layer,
not by a model tool call.

## Changes

- Normalized time/date/clock intent aliases including `time_query`,
  `current_time`, `date_query`, and `system_clock` to canonical
  `system_time`.
- Made `system.time` capability force `system_answer` at semantic/task-graph
  routing time, so a live model cannot accidentally leave a time request in a
  `semantic_answer` recipe with no allowed tool.
- Preserved the safety boundary from the previous pass: generic
  self-description, environment, or capability-check packets still lose a
  spurious `system.time` capability and do not call the time tool.
- Added first-class `priority` to resident inbox messages and schedules.
  Resident claim and due-schedule selection now order by `priority DESC` before
  creation time/id, and schema migration adds the column to existing SQLite
  resident stores.
- Added `--priority` to `holo-v3 resident enqueue` and `holo-v3 resident
  schedule-add`; schedule ticks propagate priority into generated inbox
  messages.
- Added `kernel_v3.resident.reminder.compile_reminder()` for bounded relative
  reminder input such as "十分钟后提醒我喝水" and "in 10 minutes remind me to
  stretch".
- Connected reminder compilation inside `ResidentRuntime`: claimed reminder
  messages create deterministic local schedules, append ready outbox
  confirmations, journal `resident_reminder_compiled`, and complete the original
  inbox message.
- Added human resident status rendering through `holo-v3 resident --output
  human status`. JSON remains the default.
- Added gated live smoke for system time, ten-minute reminder compilation,
  background queue priority, cancellation, and recurring schedules.

## Verification

```bash
.venv/bin/pytest -q tests/test_kernel_v3_phase119_resident_time_priority.py \
  tests/test_kernel_v3_phase94_capability_space_and_long_loop.py::test_phase94_agent_executes_system_time_as_non_workspace_capability \
  tests/test_kernel_v3_phase112_strategy_supervision.py::test_phase112_spurious_system_answer_without_system_tool_downgrades_to_semantic_answer
```

Result: `8 passed`.

```bash
.venv/bin/pytest -q tests/test_kernel_v3_phase73_resident_runtime.py \
  tests/test_kernel_v3_phase76_resident_scheduler.py \
  tests/test_kernel_v3_phase77_resident_doctor.py
```

Result: `82 passed`.

```bash
.venv/bin/pytest -q tests/test_kernel_v3_phase94_capability_space_and_long_loop.py \
  tests/test_kernel_v3_phase112_strategy_supervision.py \
  tests/test_kernel_v3_phase119_resident_time_priority.py
```

Result: `40 passed`.

```bash
.venv/bin/pytest -q tests/test_kernel_v3_*.py
```

Result: `727 passed`.

Live smoke:

```bash
HOLO_V3_LIVE_MODEL=1 .venv/bin/pytest -q tests/live/test_kernel_v3_phase119_resident_live_smoke.py
```

Result: `1 passed`.

Full repository `pytest -q` was also attempted. Kernel v3 tests passed, but
legacy/non-kernel tests failed for environmental or user-edited reasons:
socket creation is denied by the sandbox for reply API tests, `/mnt/c` is
read-only for Windows helper tests, old stage engineering drills assume a bare
`python` command exists, one old artifact file is absent, and the user-updated
root `AGENTS.md` no longer matches an older depersonalized-agent assertion.
Those failures were not caused by this kernel-v3 change set.

## Notes

- Resident reminder compilation is intentionally narrow: it handles relative
  reminders and creates local schedules. Absolute calendar parsing and external
  calendar connectors remain future work.
- Priority is bounded to `[-1000, 1000]` at the store/compiler boundary.
- `holo-v3 resident --output human status` is an operator view, not a new state
  source. The SQLite queue/scheduler and journal remain authoritative.
