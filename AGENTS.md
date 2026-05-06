# Holo Working Rules

## Canonical Identity Invariants

- WeChat ordinary direct-message threads are canonicalized as `wechat:<name>`.
- Do not split ordinary direct-message identity between `wechat:<name>` and bare aliases.
- Keep chatrooms like `*@chatroom` and `wxid_*` identities untouched.
- Store, mind graph, archive backfill, outcome appraisal, and acceptance gates must agree on the same thread key.

## Runtime Safety Boundaries

- Runtime memory is part of self; do not bolt on a second brain layer.
- Processors remain replaceable; model calls must stay inside the unified processor fabric.
- Windows transport is eyes and hands only; it must not become a second decision layer.
- Preserve action-market-first deliberation. Language generation stays downstream of action selection.
- Keep bounded operator repair intact.
- Runtime and operator flows must not hot-edit the live repo. Code patch flows stay shadow-write only.
- Do not weaken operator safety boundaries or add an always-on control loop.

## Preferred Workflow

- Read `HOLO_HANDOFF.md`, `docs/HOLO_ARCHITECTURE_MAP.md`, and the affected wheel contracts first.
- For Stage23+ planning or implementation, keep `.agent/PLANS.md`, `.agent/STAGE23_27_PROGRAM.md`, and runtime docs aligned until a newer durable program file supersedes them.
- Fix the smallest structural break that restores invariants, stability, calibration, or observability; do not widen feature surface casually.
- Prefer regression tests before or alongside behavior changes.
- Keep changes narrowly scoped, reviewable, and processor-fabric-safe.

## Stage Doc Update Rules

- When a stage lands, add `docs/STAGEXX_*.md` and `docs/ENGINEERING_HANDOFF_STAGEXX.md`.
- Update `HOLO_HANDOFF.md` in the same change so current stage, completed work, and next focus are not stale.
- For the Stage23-27 arc, update `.agent/PLANS.md`, `.agent/STAGE23_27_PROGRAM.md`, and `docs/ROADMAP_REGISTRY.md` in the same change whenever sequencing, blockers, stop rules, or rollback rules move.
- Acceptance surfaces and docs must move together; do not add a stage gate without updating handoff docs.
- Replay artifact conventions belong in the stage doc and handoff doc; do not rely on thread-local memory for rerun instructions.

## Module Layout

- `holo_host/mind_graph.py`, `holo_host/memory_bridge.py`, and `holo_host/reply_api.py` are the stable facade entrypoints.
- Reducer logic belongs under `holo_host/mind_graph_parts/`.
- Policy and counterfactual logic belongs under `holo_host/policy_runtime/`.
- Reply diagnostics, acceptance helpers, artifact helpers, and route helpers belong under `holo_host/reply_service_parts/`.

## Test Commands

- `pytest -q`
- `pytest -q tests/test_stage11_calibration.py tests/test_stage12_acceptance.py`
- `pytest -q tests/test_stage14_replay.py`
- `pytest -q tests/test_stage15_modularization.py`
- `pytest -q tests/test_holo_host.py tests/test_rag_memory.py tests/test_windows_helper.py`
- `python -m holo_host show-processor-routing`
- `python -m holo_host show-provider-status`
- `python -m holo_host accept-processor-fabric`
- `python -m holo_host --config .holo_host.example.toml accept-stage10`
- `python -m holo_host --config .holo_host.example.toml accept-stage12`
- `python -m holo_host --config .holo_host.example.toml accept-stage13`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`
- `python -m holo_host --config .holo_host.example.toml accept-stage16`
- `python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python -m holo_host --config .holo_host.example.toml accept-stage27 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python -m holo_host --config .holo_host.example.toml accept-stage28 --thread-key TestUser --chat-name TestUser --channel wechat`
- `python -m holo_host --config .holo_host.example.toml replay-calibration-fixture --fixture-path tests/fixtures/stage14`
- `python -m holo_host --config .holo_host.example.toml replay-policy-regret --fixture-path tests/fixtures/stage14`

## Release And Replay Hardening

- Helper artifact paths must be converted by explicit direction: Holo-host-facing paths use `/mnt/<drive>/...`, Windows-helper-facing paths use `X:\...`.
- Localhost-to-WSL fallback depends on endpoint topology, not the host OS running tests.
- Stage12 acceptance must stay deterministic in local or offline mode and may use only acceptance-scoped stub evidence.
- Stage14 replay metrics must expose raw values and deterministic display rounding.
- Persona, defaults, and autobiographical update text must remain UTF-8 clean; do not reintroduce mojibake into policy defaults.

## Stage17 Realtime Runtime

- Ordinary short WeChat turns should prefer `ActiveThreadState` and the `active-thread-fast` memory route.
- Fast-lane prompts must not default to a multi-line verbatim recent-history block; use continuity summary and last outbound action first.
- Low confidence alone must not trigger `deep_recall`; explicit memory need, unresolved references, factual recall need, high-risk ambiguity, or cold active state are the escalation reasons.
- Active WeChat history refresh must not block ordinary short turns; keep it explicit and on-demand unless the turn is a hard continuity or history request.

## Stage28 Multimodal Kernel

- Stage28 situational fields are derived packet surfaces, not self-memory stores.
- Visual/image work must stay inside visual memory and processor-fabric seams; do not add raw provider calls in the runtime hot path.
- Situational grounding may nudge action-market scores but must not bypass action-market-first deliberation, explicit recall escalation, transport safety, or canary gates.
