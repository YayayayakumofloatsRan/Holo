# Stage17 Engineering Handoff

## What Landed

- Internal `ActiveThreadState` persistence in `MindGraph`.
- Active-thread fast packet construction in `MemoryBridge` for ordinary short WeChat turns.
- Fast-lane prompt history minimization in `processors.py`.
- Blocking WeChat history refresh demotion for ordinary short turns.
- `accept-stage17` CLI/API gate and focused Stage17 regression tests.

## Rerun Commands

- `pytest -q tests/test_stage17_realtime_runtime.py`
- `pytest -q tests/test_stage14_replay.py tests/test_stage15_modularization.py tests/test_stage16_release.py`
- `python -m holo_host --config .holo_host.example.toml accept-stage14`
- `python -m holo_host --config .holo_host.example.toml accept-stage16`
- `python -m holo_host --config .holo_host.example.toml accept-stage17 --thread-key Nemoqi --chat-name Nemoqi --channel wechat`
- `pytest -q`

## Contracts To Preserve

- Watcher/transport still only append and execute; they must not run recall, policy selection, or a second decision layer.
- Fast lane must remain action-market-first. It can use ActiveThreadState to build the packet, but language generation still happens only after selected action.
- Ordinary fast-lane prompts should not include the default multi-line recent-history window.
- Low confidence alone must not trigger `deep_recall`.
- Blocking active WeChat history refresh is reserved for explicit memory/history requests or hard continuity failures.
- Canonical WeChat direct-message identity remains `wechat:<name>`.

## Next Focus

Observe online shadow latency and prompt history line counts before adding more capability. If a short-turn quality regression appears, prefer tuning active-state reducers and recall escalation rules before increasing model budget.
