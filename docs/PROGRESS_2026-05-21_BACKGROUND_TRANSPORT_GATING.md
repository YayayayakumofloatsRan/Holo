# Progress - Background Transport Gating - 2026-05-21

## Context

The operator reported that live Holo was too frequently taking desktop focus
through the WeChat transport path. This is a transport ergonomics problem, not a
subject-runtime problem: the WSL kernel can run independently, while the
Windows-side pyweixin watcher/sender may need foreground UI access.

## Action

- Stopped the running Holo stack through the official stop path.
- Verified:
  - WSL `reply_api`: stopped.
  - WSL daemon: stopped.
  - WeChat transport state: stopped.
  - No `weixin_sender.pyw`, `pyweixin_watcher.pyw`, or live `holo_host`
    process remained apart from the inspection command itself.
- Changed startup defaults so normal start/restart commands do not launch the
  WeChat watcher.
- Added explicit opt-in transport controls:
  - PowerShell: pass `-WithWeChat`.
  - Environment: set `HOLO_START_WECHAT=1`.

## Changed Entry Points

- `scripts/holo-start-all.ps1`
- `scripts/holo-wsl-start-all.ps1`
- `scripts/holo-restart-all.ps1`
- `scripts/holo-wsl-restart-all.ps1`
- `scripts/holo-start-all.sh`

## Verification

- `python -m pytest tests\test_startup_scripts.py -q`: 2 passed.
- PowerShell AST parse succeeded for:
  - `scripts/holo-start-all.ps1`
  - `scripts/holo-wsl-start-all.ps1`
  - `scripts/holo-restart-all.ps1`
  - `scripts/holo-wsl-restart-all.ps1`
- `scripts/holo-wsl-status.ps1` after shutdown reported `reply_api: stopped`,
  `daemon: stopped`, and `transport: stopped`.

## Operator Rule

For ordinary desktop work, keep the WeChat watcher off. Start the Holo brain
only when needed, and attach WeChat transport only during deliberate live
testing windows.
