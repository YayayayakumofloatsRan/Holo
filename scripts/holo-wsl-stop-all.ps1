$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\stop_holo_wechat.ps1')
& (Join-Path $PSScriptRoot 'holo-wsl-offline.ps1')
