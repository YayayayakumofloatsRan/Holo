# Holo Plans

## Current Reality
- Baseline date: `2026-04-11`.
- The live runtime milestone remains `stage22-bounded-blackbox-online-canary`.
- This bootstrap task is doc-only. No runtime, CLI, schema, or test behavior changes belong in this change.
- Stage23 starts with Stage22 contract paydown before any Stage24-27 long-horizon capability work.
- Observed baseline on `2026-04-11`:
  - `.agent/` did not exist before this change.
  - `python -m holo_host --config .holo_host.example.toml accept-stage22 --thread-key Nemoqi --chat-name Nemoqi --channel wechat` passed.
  - `pytest -q tests/test_stage22_online_canary.py tests/test_stage15_modularization.py tests/test_holo_host.py` reported `16` failures, all in `tests/test_holo_host.py`.
- The durable planning pair for the next arc is `.agent/PLANS.md` plus `.agent/STAGE23_27_PROGRAM.md`.

## Non-Negotiable Contracts
- Memory is the self.
- Processors remain replaceable; model calls stay inside the processor fabric.
- Transport remains eyes and hands only.
- Action-market-first deliberation remains the decision path.
- Do not add a second brain layer.
- Do not add a new unbounded always-on loop.
- Do not let runtime or operator flows hot-edit the live repo.
- Ordinary WeChat direct-message identity remains canonicalized as `wechat:<name>`.

## Active Program Index
- `Stage23-27 bootstrap program`: `.agent/STAGE23_27_PROGRAM.md`
- `Current live runtime handoff`: `HOLO_HANDOFF.md`
- `Architecture reference`: `docs/HOLO_ARCHITECTURE_MAP.md`
- `Roadmap registry`: `docs/ROADMAP_REGISTRY.md`
- `Active implementation priority`: Stage23 contract repair and surface separation
- `Current live runtime boundary`: Stage22 stays implemented and live; Stage23-27 is planned work only

## Blocker Inventory
- `Stage22 shell/core coupling`: `open`; `holo_host/reply_api.py` currently mixes host shell endpoints, `/reply`, `/ingest-artifact`, Stage22 diagnostics, canary gate logic, live-artifact replay conversion, rollback control, acceptance, and HTTP dispatch in one facade. Evidence: `holo_host/reply_api.py:679-700`, `1089-1408`, `4352-4532`, `4899-5078`, `5959-6382`, and `7486-7490`.
- `Artifact-ingest compatibility drift`: `open`; the service now passes `channel`, `thread_key`, `chat_name`, `world_cue_type`, and `due_at` into `memory.ingest_artifact`, while the test double still exposes the older signature. Evidence: `holo_host/reply_api.py:679-700`, `tests/test_holo_host.py:1220-1235`, and the observed baseline failure `FakeMemory.ingest_artifact() got an unexpected keyword argument 'channel'`.
- `Replay rounding drift`: `open`; Stage14 replay preserves both rounded `aggregate_metrics` and raw `raw_aggregate_metrics`, but replay-gated logic still compares rounded regret values. Evidence: `holo_host/stage14_replay.py:36-38`, `451-486`, `546-547`, `holo_host/mind_graph_parts/policy_sedimentation.py:512-513`, and `holo_host/reply_api.py:4306-4307`.
- `Acceptance/runtime mismatches`: `open`; `accept-stage22` passes while baseline host tests still assert pre-shadow reply and defer behavior. Evidence: `holo_host/config.py:201-207`, `holo_host/reply_api.py:6057-6064`, the passing `accept-stage22` run on `2026-04-11`, and the `pytest -q tests/test_stage22_online_canary.py tests/test_stage15_modularization.py tests/test_holo_host.py` baseline with `16` failures in `tests/test_holo_host.py`.

## Execution Ledger
| Stage | Status | Goal | Dependencies | Validation | Stop rule | Rollback rule |
| --- | --- | --- | --- | --- | --- | --- |
| `Stage23` | `planned - first` | Pay down the four recorded Stage22 blockers before new long-horizon runtime work. | Stage22 runtime, current docs, blocker inventory. | `accept-stage22`; `tests/test_stage22_online_canary.py`; `tests/test_stage15_modularization.py`; `tests/test_holo_host.py` green or explicit accepted debt. | Do not advance if shadow-mode behavior still cannot be represented cleanly in baseline host tests. | Freeze at Stage22 runtime plus doc-only plan updates; do not widen canary or add new subject state. |
| `Stage24` | `planned` | Introduce bounded, inspectable subject programs. | Stage23 contract repair. | Planned `accept-stage24`; planned Stage24 regression tests; Stage23 surfaces remain green. | Do not advance if the design starts behaving like a second brain or requires a new always-on loop. | Ignore or empty the program surface without changing Stage23 behavior. |
| `Stage25` | `planned` | Couple artifacts, tool outcomes, deferred replies, and world cues into the same bounded program surface. | Stage24 program surface. | Planned `accept-stage25`; planned Stage25 regression tests; Stage24 surfaces remain green. | Do not advance if ingest surfaces fork into incompatible schemas again. | Disable progress reducers while preserving Stage24 read surfaces. |
| `Stage26` | `planned` | Extend replay discipline and promotion gates to long-horizon behavior. | Stage25 progress coupling and Stage14 replay baseline discipline. | Planned `accept-stage26`; planned Stage26 replay tests; `tests/test_stage14_replay.py`; Stage25 surfaces remain green. | Do not advance if replay cannot explain approval or rejection decisions. | Disable promotion of long-horizon overlays and keep replay observational only. |
| `Stage27` | `planned` | Canary program-aware long-horizon behavior online in host-side shadow-first mode. | Stage26 replay and promotion discipline. | Planned `accept-stage27`; planned Stage27 canary tests; Stage26 surfaces remain green; live-artifact replay still works. | Do not advance if online canary requires watcher logic, hidden state mutation, or hard-gate bypasses. | Set canary back to `shadow` or `disabled` and ignore program-aware live behavior while preserving observability. |
