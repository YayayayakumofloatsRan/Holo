$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

if (-not (Test-HoloForceWindows) -and (Test-HoloWslReady -WindowsRepoRoot $root)) {
  & (Join-Path $PSScriptRoot 'holo-wsl-online.ps1')
  return
}
$runtimeDir = Join-Path $root '.holo_runtime'
$runDir = Join-Path $runtimeDir 'run'
$logDir = Join-Path $runtimeDir 'logs'
$configPath = if ($env:HOLO_HOST_CONFIG) { $env:HOLO_HOST_CONFIG } else { Join-Path $root '.holo_host.toml' }
$python = if ($env:HOLO_HOST_PYTHON) {
  $env:HOLO_HOST_PYTHON
} else {
  (Get-Command python -ErrorAction Stop).Source
}
$pythonBackground = if ($env:HOLO_HOST_PYTHONW) {
  $env:HOLO_HOST_PYTHONW
} elseif (Get-Command pythonw -ErrorAction SilentlyContinue) {
  (Get-Command pythonw).Source
} else {
  $python
}
function Ensure-DefaultConfig {
  if (Test-Path $configPath) {
    return
  }
  $example = Join-Path $root '.holo_host.example.toml'
  if (Test-Path $example) {
    Copy-Item $example $configPath
    return
  }
  @'
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "codex_cli"
poll_interval_seconds = 30
max_jobs_per_cycle = 4
codex_binary = "codex"
codex_extra_args = ["--dangerously-bypass-approvals-and-sandbox"]
codex_model = "gpt-5.4"
codex_reasoning_effort = "low"
fast_model = "gpt-5.4-mini"
fast_reasoning_effort = "low"
responses_model = "gpt-5.4"
responses_fast_model = "gpt-5.4-mini"
network_enabled = true
image_enabled = true
codex_timeout_seconds = 900
resume_sessions = true
dry_run = false
api_bind_host = "127.0.0.1"
api_port = 8004

[mail]
transport = "maildir"
poll_limit = 10
maildir_inbox = ".holo_runtime/mail/inbox"
maildir_processed = ".holo_runtime/mail/processed"
maildir_outbox = ".holo_runtime/mail/outbox"

[memory]
prompt_top_k = 4
auto_observe = true
promote_batch_size = 8
promote_interval_seconds = 300
thought_interval_seconds = 900
reflection_interval_seconds = 1800
dream_interval_seconds = 1800
initiative_interval_seconds = 1800
dream_sample_size = 6
thought_sample_size = 4
reflection_window_hours = 12.0
history_messages = 8

[autonomy]
auto_send_mode = "full_auto"
allow_proactive_existing_threads = true
allow_initiative_whitelist_contacts = true
proactive_after_hours = 72
initiative_cooldown_hours = 48
wechat_helper_config_path = "windows_helper/wechat_helper.live.json"
max_auto_replies_per_contact_per_hour = 120
'@ | Set-Content -Path $configPath -Encoding UTF8
}

function Get-RunningProcessId([string]$PidFile) {
  if (-not (Test-Path $PidFile)) {
    return $null
  }
  $raw = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
  if (-not $raw) {
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    return $null
  }
  try {
    $pidValue = [int]$raw
  } catch {
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    return $null
  }
  $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
  if ($null -eq $proc) {
    Remove-Item $PidFile -ErrorAction SilentlyContinue
    return $null
  }
  return $pidValue
}

function Start-Detached([string]$Name, [string[]]$CommandArgs) {
  $pidFile = Join-Path $runDir "$Name.pid"
  $stdoutLog = Join-Path $logDir "$Name.stdout.log"
  $stderrLog = Join-Path $logDir "$Name.stderr.log"
  $argumentList = @($CommandArgs | Where-Object { $null -ne $_ -and [string]$_ -ne '' } | ForEach-Object { [string]$_ })
  $existing = Get-RunningProcessId $pidFile
  if ($null -ne $existing) {
    Write-Output "$Name already running (pid $existing)"
    return
  }
  if ($argumentList.Count -eq 0) {
    throw "no arguments were provided for $Name"
  }

  Remove-Item $stdoutLog -ErrorAction SilentlyContinue
  Remove-Item $stderrLog -ErrorAction SilentlyContinue

  $proc = Start-Process `
    -FilePath $pythonBackground `
    -ArgumentList $argumentList `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

  Set-Content -Path $pidFile -Value $proc.Id -Encoding ASCII
  Start-Sleep -Seconds 1
  if ($proc.HasExited) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    throw "$Name failed to start"
  }
  Write-Output "started $Name (pid $($proc.Id))"
}

New-Item -ItemType Directory -Force -Path $runDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
Ensure-DefaultConfig

Start-Detached -Name 'reply_api' -CommandArgs @('-m', 'holo_host', '--config', $configPath, 'serve-api')
Start-Detached -Name 'daemon' -CommandArgs @('-m', 'holo_host', '--config', $configPath, 'daemon')

Write-Output ''
Write-Output 'Holo runtime is online'
Write-Output "config: $configPath"
Write-Output "logs:   $logDir"
