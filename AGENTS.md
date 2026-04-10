# Holo Working Rules

## Canonical Identity Invariants

- WeChat ordinary direct-message threads are canonicalized as `wechat:<name>`.
- Do not split ordinary direct-message identity between `wechat:<name>` and bare aliases.
- Keep chatrooms like `*@chatroom` and `wxid_*` identities untouched.
- Store, mind graph, archive backfill, outcome appraisal, and acceptance gates must agree on the same thread key.

## Runtime Safety Boundaries

- Runtime memory is part of self; do not bolt on a second brain layer.
- Processors remain replaceable; model calls must stay inside the unified processor fabric.
- Windows transport is eyes/hands only; it must not become a second decision layer.
- Runtime/operator flows must not hot-edit the live repo. Code patch flows stay shadow-write only.
- Preserve action-market-first deliberation. Language generation is downstream of action selection.

## Test Commands

- Full suite: `pytest -q`
- Targeted calibration: `pytest -q tests/test_stage11_calibration.py tests/test_stage12_acceptance.py`
- Stage14 replay: `pytest -q tests/test_stage14_replay.py`
- Targeted host/runtime: `pytest -q tests/test_holo_host.py tests/test_rag_memory.py tests/test_windows_helper.py`
- Acceptance probes:
  - `python -m holo_host --config .holo_host.example.toml accept-stage10`
  - `python -m holo_host --config .holo_host.example.toml accept-stage12`
  - `python -m holo_host --config .holo_host.example.toml accept-stage13`
  - `python -m holo_host --config .holo_host.example.toml accept-stage14`
  - `python -m holo_host --config .holo_host.example.toml accept-stage16`
  - `python -m holo_host --config .holo_host.example.toml replay-calibration-fixture --fixture-path tests/fixtures/stage14`
  - `python -m holo_host --config .holo_host.example.toml replay-policy-regret --fixture-path tests/fixtures/stage14`

## Stage Doc Update Rules

- When a stage lands, add `docs/STAGEXX_*.md` and `docs/ENGINEERING_HANDOFF_STAGEXX.md`.
- Update `HOLO_HANDOFF.md` in the same change so current stage, completed work, and next focus are not stale.
- Acceptance surfaces and docs must move together; do not add a stage gate without updating handoff docs.
- Replay artifact conventions belong in the stage doc and handoff doc; do not rely on thread-local memory for rerun instructions.

## Preferred Workflow

- Read handoff docs and the affected wheel contracts first.
- Fix the smallest structural break that restores invariants; do not widen feature surface casually.
- Prefer regression tests before or alongside behavior changes.
- Keep changes narrowly scoped, reviewable, and processor-fabric-safe.

## Module Layout

- `holo_host/mind_graph.py`, `holo_host/memory_bridge.py`, and `holo_host/reply_api.py` are the stable façade entrypoints.
- Reducer logic belongs under `holo_host/mind_graph_parts/`.
- Policy and counterfactual logic belongs under `holo_host/policy_runtime/`.
- Reply diagnostics, acceptance helpers, artifact helpers, and route helpers belong under `holo_host/reply_service_parts/`.

## Stage16 Release Hardening

- Helper artifact paths must be converted by explicit direction: Holo-host-facing paths use `/mnt/<drive>/...`, Windows-helper-facing paths use `X:\...`.
- Localhost-to-WSL fallback depends on endpoint topology, not the host OS running tests.
- Stage12 acceptance must stay deterministic in local/offline mode and may use only acceptance-scoped stub evidence.
- Stage14 replay metrics must expose raw values and deterministic display rounding.
- Persona/default and autobiographical update text must remain UTF-8 clean; do not reintroduce mojibake into policy defaults.
# Holo Repo Agent Notes

## Canonical invariants
- Keep direct-message WeChat identity canonical and stable across reply, memory, and appraisal paths.
- Do not split ordinary WeChat threads into competing aliases during runtime changes.
- Preserve `memory-is-self`, `processor-replaceable`, and `transport-eyes-hands` as the runtime contract.
- Keep action-market-first deliberation and bounded operator repair intact.

## Safety rules
- Do not let runtime code hot-edit the live repository.
- Do not weaken operator safety boundaries or add an always-on control loop.
- Keep shadow-write-only behavior for code patch flows.

## Workflow
- Read the current handoff and architecture docs before making subject-runtime changes.
- Prefer the smallest patch that restores stability, calibration, or observability.
- Update stage docs whenever runtime behavior, identity semantics, or acceptance gates change.
- Add or update regression tests alongside behavior changes.

## Test commands
- `pytest -q`
- `python -m holo_host show-processor-routing`
- `python -m holo_host show-provider-status`
- `python -m holo_host accept-processor-fabric`
- `python -m holo_host accept-stage12`
