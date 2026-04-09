# Engineering Handoff Stage 14

## What Changed
- Stage14 adds an offline replay harness that evaluates calibration and policy quality from deterministic fixtures.
- Replay uses isolated temporary graph/runtime state so default runs do not mutate live memory.
- Stage14 adds `replay-calibration-fixture`, `replay-policy-regret`, and `accept-stage14`.
- Replay artifacts are written as reviewable `summary.json` and `summary.md` files under `artifacts/replays/stage14/` unless an explicit artifact directory is supplied.

## What To Verify
- Repeated replay runs on the same fixture set produce the same aggregate metrics.
- Synthetic, archive-derived, and calibration-history fixtures all normalize into the same replay shape.
- Canonical WeChat direct-message identity stays prefixed as `wechat:<name>`.
- Policy regret, initiative false-block rate, and expression overflow rates are visible from CLI output and artifacts.
- Live graph/runtime state does not change when replay runs against the default isolated harness.

## What Not To Change
- Do not add a second evaluator path that bypasses existing action simulation or outcome reducers.
- Do not let replay mutate live runtime state by default.
- Do not add a new daemon loop to maintain offline evaluation state.
- Do not weaken operator safety boundaries or transport contracts.

## Recommended Follow-Up
- Expand curated replay corpora only when they expose a new failure mode that existing fixtures miss.
- Keep fixture metadata explicit and human-readable; do not hide policy labels in opaque score blobs.
- Use `docs/releases/` for curated summaries, not raw replay scratch output.
