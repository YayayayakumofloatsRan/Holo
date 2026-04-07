$ErrorActionPreference = 'Stop'

if ($env:HOLO_WSL_DISTRO) {
  & (Join-Path $PSScriptRoot 'holo-wsl-start-all.ps1')
  return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configPath = if ($env:HOLO_HOST_CONFIG) { $env:HOLO_HOST_CONFIG } else { Join-Path $root '.holo_host.toml' }

& (Join-Path $PSScriptRoot 'holo-online.ps1')

$bindHost = '127.0.0.1'
$port = 8004
if (Test-Path $configPath) {
  $raw = Get-Content -Path $configPath -Raw -Encoding UTF8
  if ($raw -match '(?m)^\s*api_bind_host\s*=\s*"([^"]+)"') {
    $bindHost = $Matches[1]
  }
  if ($raw -match '(?m)^\s*api_port\s*=\s*(\d+)') {
    $port = [int]$Matches[1]
  }
}

$url = "http://$bindHost`:$port/health"
$lastError = $null
for ($i = 0; $i -lt 20; $i++) {
  try {
    Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2 | Out-Null
    $lastError = $null
    break
  } catch {
    $lastError = $_
    Start-Sleep -Milliseconds 500
  }
}
if ($null -ne $lastError) {
  throw "reply api did not become healthy in time: $lastError"
}

powershell.exe -ExecutionPolicy Bypass -NoProfile -File (Join-Path $root 'windows_helper\start_holo_wechat.ps1')

Write-Output ''
Write-Output 'Holo host + WeChat watcher started'
