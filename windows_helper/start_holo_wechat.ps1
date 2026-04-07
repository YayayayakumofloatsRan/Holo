$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Split-Path -Parent $here
$watcher = Join-Path $here 'pyweixin_watcher.pyw'
$sender = Join-Path $here 'weixin_sender.pyw'
$helper = Join-Path $here 'wechat_helper.py'
$config = if ($env:HOLO_WECHAT_HELPER_CONFIG) { $env:HOLO_WECHAT_HELPER_CONFIG } else { Join-Path $here 'wechat_helper.live.json' }
$python = if ($env:HOLO_HELPER_PYTHON) {
  $env:HOLO_HELPER_PYTHON
} else {
  (Get-Command python -ErrorAction Stop).Source
}
$pythonw = if ($env:HOLO_HELPER_PYTHONW) {
  $env:HOLO_HELPER_PYTHONW
} elseif (Get-Command pythonw -ErrorAction SilentlyContinue) {
  (Get-Command pythonw).Source
} else {
  $python
}
$killer = Join-Path $here 'kill_watchers.ps1'

if (Test-Path $killer) {
  powershell.exe -ExecutionPolicy Bypass -NoProfile -File $killer | Out-Null
}
if (-not (Test-Path $config)) {
  Write-Output "live helper config not found: $config"
  exit 1
}

$mode = 'auto'
try {
  $cfgJson = Get-Content -Raw -Encoding UTF8 $config | ConvertFrom-Json
  if ($cfgJson.watch_mode) {
    $mode = [string]$cfgJson.watch_mode
  }
} catch {
  Write-Output "failed to parse live config"
  exit 1
}

if ($mode -eq 'wcf') {
  $wcfInfoRaw = & $python $helper --config $config wcf-info 2>$null
  if ($LASTEXITCODE -ne 0) {
    Write-Output "failed to probe WCF compatibility"
    exit 1
  }

  try {
    $wcfInfo = $wcfInfoRaw | ConvertFrom-Json
  } catch {
    Write-Output "failed to parse WCF compatibility output"
    exit 1
  }

  if ($wcfInfo.compatibility -eq 'incompatible') {
    Write-Output ("refusing to start live watcher: " + $wcfInfo.reason)
    exit 1
  }
}

Start-Process -WindowStyle Hidden -WorkingDirectory $repo -FilePath $pythonw -ArgumentList @($sender, '--config', $config)
Start-Process -WindowStyle Hidden -WorkingDirectory $repo -FilePath $pythonw -ArgumentList @($watcher, '--config', $config)
Start-Sleep -Seconds 1
Write-Output "started holo live watcher"
