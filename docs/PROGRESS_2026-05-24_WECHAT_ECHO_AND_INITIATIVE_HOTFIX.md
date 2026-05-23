# Progress 2026-05-24: WeChat Echo And Initiative Hotfix

## Trigger

During live WeChat bringup, Holo rapidly sent old `initiative-wechat-*` messages and the operator observed that it could not reliably distinguish operator messages from its own sent bubbles.

## Root Cause

- Local autonomy config allowed proactive initiative sends.
- The Windows detached sender drained stale `send_queue` initiative tasks immediately after startup.
- Detached sender success did not update the shared watcher `state_file`, so `pyweixin_dialog` could later see Holo's own sent bubble as `direction=unknown` and treat it as a user turn.

## Runtime Mitigation

- Stopped the WeChat watcher/sender.
- Disabled proactive initiative in the local Windows and WSL `.holo_host.toml` runtime configs:
  - `allow_proactive_existing_threads = false`
  - `allow_initiative_whitelist_contacts = false`
  - `initiative_probe_enabled = false`
- Quarantined two stale `initiative-wechat-*.json` send-queue files under `.holo_runtime/wechat-helper/quarantine/`.
- Seeded the latest successful old initiative send into `state.live.json` so restart does not immediately echo it.

## Code Fix

`windows_helper/weixin_sender.pyw` now records successful detached sends into the same `StateStore` used by `pyweixin_dialog`, including sent timestamp, bubble text, and visible digests. This lets existing `outbound_echo` suppression handle detached sender output the same way it handles normal reply bubbles.

## Verification

- Red test first:
  - `python -m pytest -q tests\test_windows_helper.py::WindowsHelperTests::test_detached_sender_records_successful_outbound_for_echo_suppression --basetemp=.pytest_tmp_wechat_echo_red`
  - failed before the fix because `StateStore.last_outbound("TestUser")` had no `bubble_texts`.
- Focused green:
  - `python -m pytest -q tests\test_windows_helper.py --basetemp=.pytest_tmp_windows_helper_echo`
  - `47 passed`
- Full regression:
  - `python -m pytest -q --basetemp=.pytest_tmp_full_wechat_echo_fix`
  - `456 passed`
- Live check after restart:
  - WeChat transport `online`
  - detail `idle`
  - send queue count `0`
  - no new receipts after restart observation window

