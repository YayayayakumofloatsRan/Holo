# Engineering Handoff Stage44

## Status

Stage44 reduces live reply latency by keeping non-explicit recall pressure off the blocking Windows/history/reconstruction path.

This is a pipeline optimization, not a capability downgrade:

- WSL remains the authoritative kernel.
- Windows remains transport and history/artifact helper only.
- The watcher does not gain decision authority.
- Explicit memory/history/origin recall still uses the full recall path.

## Modified Surfaces

- `holo_host/reply_api.py`
  - `_should_refresh_wechat_history()` no longer treats `stage17:high_risk_continuity_ambiguity` as sufficient for blocking Windows history refresh.
  - Blocking history refresh remains available for explicit memory/search, explicit memory recall reasons, and origin recall.
  - Non-explicit demotions are recorded as `nonblocking_recall_without_explicit_request`.
- `holo_host/processors.py`
  - Non-explicit emotional `recall + history_refresh` turns skip synchronous `recall_reconstruct`.
- `tests/test_holo_host.py`
  - Covers nonblocking high-risk continuity, explicit-memory preservation, and reconstruction demotion.
- `docs/BIOMIMETIC_DIALOGUE_BOUNDARY_TEST_2026-05-11.md`
  - Records the latency evidence and live probes.

## Verified On 2026-05-11

- `pytest -q tests/test_holo_host.py tests/test_processor_fabric.py -k "deepseek_provider or recall_reconstruct or reconstruction or windows_history_refresh or high_risk_continuity"` passed with `9` tests.
- `python -m holo_host show-internal-runtime-readiness` passed after API restart.
- Live casual probe:
  - `elapsed_ms=4098`
  - `selected_action=reply_once`
  - `route=recall`
  - `processor_ms=3142`
  - `recall_reconstruct_ms=0`
- Live explicit-memory probe:
  - `elapsed_ms=10162`
  - `selected_action=history_refresh`
  - `route=deep_recall`
  - `processor_ms=2677`
  - `recall_reconstruct_ms=5971`

## Follow-Up

- Continue lowering the system floor by reducing prompt size and host-side post-reply persistence overhead.
- Do not move reply policy into Windows helper code.
- Do not disable explicit recall reconstruction to make benchmark numbers look better.
- If adding background recall warming later, keep it bounded and observable through the existing daemon/job surfaces.
