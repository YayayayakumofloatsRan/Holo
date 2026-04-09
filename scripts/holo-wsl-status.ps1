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
Write-Output "checking Holo kernel in WSL distro '$($settings.Distro)' at $($settings.Repo)"
Invoke-HoloWsl -Distro $settings.Distro -Repo $settings.Repo -Command "sed -i 's/\r$//' ./scripts/holo-status.sh && bash ./scripts/holo-status.sh"
