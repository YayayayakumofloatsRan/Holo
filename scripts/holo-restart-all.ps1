$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

if (-not (Test-HoloForceWindows) -and (Test-HoloWslReady -WindowsRepoRoot $root)) {
  & (Join-Path $PSScriptRoot 'holo-wsl-restart-all.ps1')
  return
}

& (Join-Path $PSScriptRoot 'holo-stop-all.ps1')
Start-Sleep -Seconds 1
& (Join-Path $PSScriptRoot 'holo-start-all.ps1')
