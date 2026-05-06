$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

& (Join-Path $PSScriptRoot 'holo-wsl-online.ps1')
powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\start_holo_wechat.ps1')

Write-Output ''
Write-Output 'Holo WSL kernel + WeChat watcher started'
