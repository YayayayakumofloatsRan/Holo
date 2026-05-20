$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

function Invoke-HoloWsl([string]$Distro, [string]$Repo, [string]$Command) {
  & wsl.exe -d $Distro --cd $Repo -- bash -lc $Command
  if ($LASTEXITCODE -ne 0) {
    throw "WSL command failed in distro '$Distro': $Command"
  }
}

$settings = Get-HoloWslSettings -WindowsRepoRoot $root

if (-not $env:OPENAI_COMPATIBLE_API_KEY -and $env:DEEPSEEK_API_KEY) {
  $env:OPENAI_COMPATIBLE_API_KEY = $env:DEEPSEEK_API_KEY
}
if (-not $env:OPENAI_COMPATIBLE_BASE_URL) {
  $env:OPENAI_COMPATIBLE_BASE_URL = 'https://api.deepseek.com'
}
$wslEnvNames = @(
  'DEEPSEEK_API_KEY',
  'DEEPSEEK_BASE_URL',
  'OPENAI_COMPATIBLE_API_KEY',
  'OPENAI_COMPATIBLE_BASE_URL',
  'HOLO_ENABLE_CODEX_FALLBACK'
)
$existingWslEnv = @(([string]$env:WSLENV).Split(':') | Where-Object { [string]$_ -ne '' })
foreach ($name in $wslEnvNames) {
  if ($existingWslEnv -notcontains $name) {
    $existingWslEnv += $name
  }
}
$env:WSLENV = ($existingWslEnv | Select-Object -Unique) -join ':'

& (Join-Path $PSScriptRoot 'holo-wsl-sync.ps1') -Distro $settings.Distro -DestinationRepo $settings.Repo
Write-Output "starting Holo kernel in WSL distro '$($settings.Distro)' at $($settings.Repo)"
Invoke-HoloWsl -Distro $settings.Distro -Repo $settings.Repo -Command "sed -i 's/\r$//' ./scripts/holo-online.sh ./scripts/holo-status.sh && bash ./scripts/holo-online.sh"
Start-Sleep -Seconds 2
Invoke-HoloWsl -Distro $settings.Distro -Repo $settings.Repo -Command "sed -i 's/\r$//' ./scripts/holo-status.sh && bash ./scripts/holo-status.sh"
