# Holo Windows Bringup

Windows can still host the whole stack from `D:\Holo\holo`, but on this machine that path is now a fallback, not the preferred shape.
The intended deployment is back to:

- Windows for WeChat eyes and hands
- WSL for Codex, memory, and reply generation

That matches both the older Holo behavior and the current Codex Windows guidance. OpenAI's Windows setup docs say the best-performance path is WSL2 with the repo in the Linux filesystem:
- [Codex on Windows](https://developers.openai.com/codex/windows)

## What Changed

- `holo_host` can now pass extra `codex exec` flags from `.holo_host.toml`.
- On Windows, `CodexRunner` now tries to resolve the PowerShell `codex.ps1` wrapper before falling back to the raw `codex` binary.
- Codex hook helpers no longer hardcode `/home/ran_yakumo/holo` or `/tmp/holo_codex_hook_cache`.
- A Windows-native script set now exists under `scripts`:
  - `holo-online.ps1`
  - `holo-offline.ps1`
  - `holo-start-all.ps1`
  - `holo-stop-all.ps1`
  - `holo-restart-all.ps1`
  - `sync-codex-hooks.ps1`

## Current Local Settings

- Host config: `.holo_host.toml`
- WeChat helper config: `windows_helper/wechat_helper.live.json`
- Helper runtime files now live under `D:/Holo/holo/.holo_runtime/wechat-helper`
- Repo-local pyweixin checkout: `D:/Holo/holo/.vendor/pywechat-upstream`

Important runtime choice:

- `codex_extra_args = ["--dangerously-bypass-approvals-and-sandbox"]`

This is intentional for the unattended local Holo runtime. The previous `--full-auto` path was not stable enough in the current Windows environment.

## Reality Check

- The `pyweixin_dialog` transport is the right live lane on this machine and avoids the old foreground-stealing regression.
- Windows-native `codex exec` is functionally usable here, but measured direct runs now sit around `115s` even for trivial prompts because the CLI repeatedly retries a broken streaming path before falling back to HTTP.
- The old WSL-backed archive on this repo shows the same class of replies landing in roughly `7s` to `13s`.
- Because of that gap, Windows-native host mode should be treated as an emergency fallback, not the normal online path.

## Recommended Shape On This Machine

1. Rebuild or move the distro onto an internal drive such as `D:`.
2. Keep Holo's compute kernel in WSL.
3. Keep the Windows helper routed to the WSL reply API. On machines where WSL localhost forwarding is unavailable, the start script now rewrites the live helper runtime config to the current WSL IP automatically.
4. Use the PowerShell bridge scripts so your daily commands stay on the Windows side.

New bridge scripts:

- `scripts/holo-wsl-doctor.ps1`
- `scripts/holo-wsl-sync.ps1`
- `scripts/holo-wsl-online.ps1`
- `scripts/holo-wsl-offline.ps1`
- `scripts/holo-wsl-status.ps1`
- `scripts/holo-wsl-start-all.ps1`
- `scripts/holo-wsl-stop-all.ps1`
- `scripts/holo-wsl-restart-all.ps1`

If you set these env vars first:

- `HOLO_WSL_DISTRO`
- `HOLO_WSL_REPO`

then the existing Windows entrypoints will automatically route to WSL:

- `scripts/holo-online.ps1`
- `scripts/holo-offline.ps1`
- `scripts/holo-start-all.ps1`
- `scripts/holo-stop-all.ps1`
- `scripts/holo-restart-all.ps1`

When routed to WSL, `holo-online.ps1` now syncs the core code tree into `HOLO_WSL_REPO` before starting the Linux-side host.
The rsync step intentionally excludes environment-specific and runtime-only paths such as:

- `.holo_host.toml`
- `.codex/hooks.json`
- `.holo_runtime/`
- `.vendor/`
- `holo_memory_library/memories/*.jsonl`

After the code rsync, `scripts/holo-wsl-sync.ps1` now performs a JSONL memory merge from the Windows repo into the live WSL repo, then mirrors the merged result back to the Windows checkout, so archive / callback / thought / initiative history does not silently fork across the two copies.

The WSL reply API can now also actively pull older WeChat history on demand before a recall-heavy reply. On explicit memory prompts such as “记得 / 之前 / 更早 / 上线前”, `reply_api` calls the Windows helper wrapper `windows_helper/invoke_wechat_history.ps1`, ingests the export back through `/ingest-artifact`, then rebuilds the current mind packet. Progress is written to the Ubuntu-visible `reply_api.log`.

## Bringup Steps

### Preferred: WSL Kernel + Windows Helper

1. If the old distro was tied to a missing external disk, inspect it first:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-wsl-doctor.ps1`
2. Create a new distro on `D:` if needed:
   - `wsl.exe --install Ubuntu --name HoloUbuntu --location D:\WSL\HoloUbuntu`
3. Inside that new distro, place the repo in the Linux filesystem for best Codex performance.
4. On Windows, set:
   - `$env:HOLO_WSL_DISTRO='HoloUbuntu'`
   - `$env:HOLO_WSL_REPO='~/holo'`
5. Sync repo-local Codex hooks after a path move:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\sync-codex-hooks.ps1`
6. Start host plus WeChat watcher:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-start-all.ps1`
7. Stop everything:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-stop-all.ps1`

### Fallback: Windows-Native Host

1. Sync repo-local Codex hooks after a path move:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\sync-codex-hooks.ps1`
2. Start just the Holo host:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-online.ps1`
3. Start host plus WeChat watcher:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-start-all.ps1`
4. Stop everything:
   - `powershell -ExecutionPolicy Bypass -File .\scripts\holo-stop-all.ps1`

If you want to push code over without restarting the host, run:

- `powershell -ExecutionPolicy Bypass -File .\scripts\holo-wsl-sync.ps1`

## Notes

- `python` must exist on `PATH`.
- If `HOLO_WSL_DISTRO` is set, the Windows PowerShell launchers now route to the WSL scripts automatically.
- `wsl.exe --help` on this machine supports both `--install --location` and `--manage <Distro> --move <Location>`, so future distro placement does not need to live on the system drive.
- The currently registered broken distro on this machine points at `F:\WSL\Ubuntu`, which matches the external-SSD failure mode that broke the old runtime.
- `holo-online.ps1` still supports native Windows host mode with `pythonw` plus log redirection when WSL is unavailable.
- `holo-wsl-sync.ps1` treats the Windows repo as the source of truth for core code and the Linux repo as the runtime copy.
- The Windows helper start script now honors `HOLO_WECHAT_HELPER_CONFIG`, `HOLO_HELPER_PYTHON`, and `HOLO_HELPER_PYTHONW`.
- In WSL mode, `start_holo_wechat.ps1` now writes a runtime helper config under `.holo_runtime/wechat-helper/` and rewrites `agent_url` from `127.0.0.1` to the active WSL IP when needed.
- Manual active-memory probe from WSL:
  - `python3 -m holo_host --config /home/holo/holo/.holo_host.toml refresh-wechat-history --chat-name Nemoqi --query "你还记得重新上线前吗"`
- If this repo moves again, rerun `scripts\sync-codex-hooks.ps1`.
- The current machine is on `Weixin 4.1.8.29`, so `wcferry 39.x` is not the live path here; use `pyweixin_dialog`.
- The live helper timeout is still `180s` because the Windows-native fallback can exceed the old `90s` budget.
- If transport state says Weixin is not logged in after a `prime-pyweixin --restart-weixin`, click the Weixin login flow once and let the watcher retry.
