param(
  [string]$LocalUrl = 'http://127.0.0.1:8004'
)

$ErrorActionPreference = 'Stop'

if (-not $env:HOLO_API_BEARER_TOKEN) {
  throw 'Set HOLO_API_BEARER_TOKEN before opening a remote tunnel.'
}

$cloudflared = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cloudflared) {
  throw 'cloudflared is not installed or not on PATH.'
}

& (Join-Path $PSScriptRoot 'holo-wsl-start-all.ps1')

Write-Output ''
Write-Output "Opening Cloudflare Quick Tunnel to $LocalUrl"
Write-Output 'Use the printed https://*.trycloudflare.com URL in the mobile Holo connection settings.'
Write-Output 'Set the same HOLO_API_BEARER_TOKEN value as the mobile bearer token.'
Write-Output ''

& $cloudflared.Source tunnel --url $LocalUrl
