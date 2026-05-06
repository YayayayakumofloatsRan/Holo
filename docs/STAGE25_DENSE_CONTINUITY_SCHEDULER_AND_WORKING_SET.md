# Stage25 Dense Continuity Scheduler And Working Set

## Goal
- Turn Holo from a thread-resident subject into a denser bounded continuous subject by keeping a small set of hot threads warm between turns.
- Reuse only the existing stream family: `maintenance_stream`, `association_stream`, `social_stream`, and `deep_dream_cycle`.
- Improve interruption recovery and reentry without adding a second brain, a new loop family, or background heavy recall.

## What Changed
- Added persistent bounded Mind Graph state:
  - `dense_working_set` stores one compact continuity snapshot per channel.
  - `thread_pulse_trace` stores recent bounded pulse decisions per canonical thread.
- Added an inspectable continuity budget:
  - `max_hot_threads_per_cycle`
  - `per_thread_pulse_budget`
  - `cooldown_seconds_by_stream`
  - `skip_cold_without_pressure`
  - `max_dense_working_set_threads`
- Hooked dense continuity updates into the existing `record_stream_run(...)` path so daemon cadence and manual `stream_tick` share the same scheduler.
- Added ingress hydration from the dense working set before hybrid or deep recall.
- Added `mind_packet.stage25` with the current thread's dense-continuity slice.
- Added diagnostics and acceptance:
  - `show-continuity-budget`
  - `show-dense-working-set`
  - `trace-thread-pulse`
  - `accept-stage25`

## Dense Working Set Shape
- `top_hot_threads`
- `current_self_pose`
- `pending_interpersonal_pressure`
- `open_loops_likely_to_reenter`
- `budget`
- `last_stream_name`
- `updated_at`

Each hot-thread entry is bounded and inspectable:
- `thread_key`
- `chat_name`
- `thread_heat`
- `thread_warmth`
- `reentry_priority`
- `pending_open_loop_count`
- `pending_interpersonal_pressure`
- `reentry_hint`
- `last_pulse_at`
- `cooldown_until`
- `pulse_count`
- `sources`

## Runtime Behavior
- Stream-driven pulses only consider same-thread bounded state already present in the runtime:
  - Stage19 attention frontier
  - Stage20 temporal state
  - Stage24 active scene state
- Background pulses never trigger vector recall, hybrid recall, or archive reconstruction.
- Ingress can reuse dense continuity when fresher active state is missing or weak.
- Dense continuity can seed:
  - `continuity_summary`
  - `cache_warmth`
  - a minimal bounded scene frame
  - predictive continuity confidence
- Explicit memory/history/factual/search/visual turns still escalate through the normal recall path.

## Budget Defaults
- `max_hot_threads_per_cycle = 6`
- `per_thread_pulse_budget = 2`
- `cooldown_seconds_by_stream`:
  - `maintenance_stream = 600`
  - `association_stream = 900`
  - `social_stream = 1200`
  - `deep_dream_cycle = 3600`
- `skip_cold_without_pressure = true`
- `max_dense_working_set_threads = 8`

## Validation
- `pytest -q` green on `2026-04-11`
- `accept-stage22` green
- `accept-stage23` green
- `accept-stage24` green
- `accept-stage25` green

## Non-Negotiables Preserved
- Memory remains the self.
- Processors remain replaceable.
- Transport remains eyes and hands only.
- Action-market-first deliberation is unchanged.
- No second brain.
- No new unbounded always-on loop.
- No watcher-side decision logic.
- No background heavy recall.
