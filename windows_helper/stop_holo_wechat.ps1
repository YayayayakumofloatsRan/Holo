$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$killer = Join-Path $here 'kill_watchers.ps1'
$config = if ($env:HOLO_WECHAT_HELPER_CONFIG) { $env:HOLO_WECHAT_HELPER_CONFIG } else { Join-Path $here 'wechat_helper.live.json' }
if (Test-Path $killer) {
  powershell.exe -ExecutionPolicy Bypass -NoProfile -File $killer
}
if (Test-Path $config) {
  try {
    $cfg = Get-Content -Raw -Encoding UTF8 $config | ConvertFrom-Json
    if ($cfg.transport_state_file) {
      $payload = @{
        status = 'stopped'
        mode = 'live'
        transport = $cfg.watch_mode
        watch_mode = $cfg.watch_mode
        heartbeat_at = [int][double]::Parse((Get-Date -UFormat %s))
        detail = 'stop script invoked'
        error_type = ''
        heartbeat_only = $false
      }
      $payload | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 $cfg.transport_state_file
    }
  } catch {
  }
}
