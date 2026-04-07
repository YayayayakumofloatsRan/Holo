$ErrorActionPreference = 'Stop'

if ($env:HOLO_WSL_DISTRO) {
  & (Join-Path $PSScriptRoot 'holo-wsl-restart-all.ps1')
  return
}

& (Join-Path $PSScriptRoot 'holo-stop-all.ps1')
Start-Sleep -Seconds 1
& (Join-Path $PSScriptRoot 'holo-start-all.ps1')
