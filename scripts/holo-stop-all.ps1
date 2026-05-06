$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

if (-not (Test-HoloForceWindows) -and (Test-HoloWslReady -WindowsRepoRoot $root)) {
  & (Join-Path $PSScriptRoot 'holo-wsl-stop-all.ps1')
  return
}
powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\stop_holo_wechat.ps1')
& (Join-Path $PSScriptRoot 'holo-offline.ps1')
