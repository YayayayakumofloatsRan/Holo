param(
  [Parameter(Mandatory = $true)][string]$ConfigPath,
  [Parameter(Mandatory = $true)][string]$ChatName,
  [int]$Limit = 40,
  [int]$PageTurns = 8,
  [switch]$NoVisible,
  [switch]$NoCaptures,
  [switch]$Force
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$helperScript = Join-Path $root 'windows_helper\wechat_helper.py'

if (-not (Test-Path $helperScript)) {
  throw "wechat_helper.py not found at $helperScript"
}

$python = $null
$pythonArgs = @()
if ($env:HOLO_HELPER_PYTHON) {
  $python = $env:HOLO_HELPER_PYTHON
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  $python = (Get-Command py).Source
  $pythonArgs = @('-3')
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  $python = (Get-Command python).Source
} else {
  throw 'No Windows Python interpreter found for wechat history ingest'
}

$helperArgs = @(
  $helperScript,
  '--config', $ConfigPath,
  'ingest-pyweixin-history',
  '--chat-name', $ChatName,
  '--limit', ([Math]::Max(1, $Limit)).ToString(),
  '--page-turns', ([Math]::Max(0, $PageTurns)).ToString()
)
if ($NoVisible) {
  $helperArgs += '--no-visible'
}
if ($NoCaptures) {
  $helperArgs += '--no-captures'
}
if ($Force) {
  $helperArgs += '--force'
}

& $python @pythonArgs @helperArgs
if ($LASTEXITCODE -ne 0) {
  throw "ingest-pyweixin-history failed with exit code $LASTEXITCODE"
}
