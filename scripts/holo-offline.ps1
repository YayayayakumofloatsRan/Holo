$ErrorActionPreference = 'Stop'

if ($env:HOLO_WSL_DISTRO) {
  & (Join-Path $PSScriptRoot 'holo-wsl-offline.ps1')
  return
}

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$runDir = Join-Path $root '.holo_runtime\run'

function Stop-Pidfile([string]$Name) {
  $pidFile = Join-Path $runDir "$Name.pid"
  if (-not (Test-Path $pidFile)) {
    Write-Output "$Name not running"
    return
  }
  $raw = (Get-Content -Path $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
  if (-not $raw) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Output "$Name stale pid file removed"
    return
  }
  try {
    $pidValue = [int]$raw
  } catch {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Output "$Name stale pid file removed"
    return
  }
  $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
  if ($null -eq $proc) {
    Remove-Item $pidFile -ErrorAction SilentlyContinue
    Write-Output "$Name stale pid file removed"
    return
  }
  Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 1
  $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
  if ($null -ne $proc) {
    Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
  }
  Remove-Item $pidFile -ErrorAction SilentlyContinue
  Write-Output "stopped $Name (pid $pidValue)"
}

function Stop-LegacyProcesses {
  $procs = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and (
      $_.CommandLine -like '*-m holo_host*serve-api*' -or
      $_.CommandLine -like '*-m holo_host*daemon*'
    )
  }
  foreach ($proc in $procs) {
    Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    Write-Output "stopped legacy holo_host process (pid $($proc.ProcessId))"
  }
}

Stop-Pidfile 'daemon'
Stop-Pidfile 'reply_api'
Stop-LegacyProcesses
