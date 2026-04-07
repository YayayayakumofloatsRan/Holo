$ErrorActionPreference = 'Stop'

if ($env:HOLO_WSL_DISTRO) {
  & (Join-Path $PSScriptRoot 'holo-wsl-stop-all.ps1')
  return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\stop_holo_wechat.ps1')
& (Join-Path $PSScriptRoot 'holo-offline.ps1')
