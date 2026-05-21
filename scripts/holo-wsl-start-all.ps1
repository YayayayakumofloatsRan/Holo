param(
  [switch]$WithWeChat
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$wechatFlag = ''
if ($env:HOLO_START_WECHAT) {
  $wechatFlag = $env:HOLO_START_WECHAT.Trim().ToLowerInvariant()
}
$startWeChat = $WithWeChat -or (@('1', 'true', 'yes', 'on') -contains $wechatFlag)

& (Join-Path $PSScriptRoot 'holo-wsl-online.ps1')

if ($startWeChat) {
  powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\start_holo_wechat.ps1')
  Write-Output ''
  Write-Output 'Holo WSL kernel + WeChat watcher started'
} else {
  Write-Output ''
  Write-Output 'Holo WSL kernel started'
  Write-Output 'WeChat watcher not started (set HOLO_START_WECHAT=1 or pass -WithWeChat to enable transport)'
}
