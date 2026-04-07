$ErrorActionPreference = 'Stop'

& (Join-Path $PSScriptRoot 'holo-wsl-stop-all.ps1')
Start-Sleep -Seconds 1
& (Join-Path $PSScriptRoot 'holo-wsl-start-all.ps1')
