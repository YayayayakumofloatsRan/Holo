$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Convert-WindowsPathToWsl([string]$Path) {
  if (-not $Path) {
    return ''
  }
  if ($Path -match '^[A-Za-z]:\\') {
    $full = [System.IO.Path]::GetFullPath($Path)
    $drive = $full.Substring(0, 1).ToLowerInvariant()
    $tail = $full.Substring(2).TrimStart('\').Replace('\', '/')
    if (-not $tail) {
      return "/mnt/$drive"
    }
    return "/mnt/$drive/$tail"
  }
  return $Path.Replace('\', '/')
}

function Get-HoloWslSettings {
  $distro = if ($env:HOLO_WSL_DISTRO) { $env:HOLO_WSL_DISTRO } else { 'Ubuntu' }
  $repo = if ($env:HOLO_WSL_REPO) { $env:HOLO_WSL_REPO } else { Convert-WindowsPathToWsl $root }
  return [pscustomobject]@{
    Distro = $distro
    Repo = $repo
  }
}

function Invoke-HoloWsl([string]$Distro, [string]$Repo, [string]$Command) {
  & wsl.exe -d $Distro --cd $Repo -- bash -lc $Command
  if ($LASTEXITCODE -ne 0) {
    throw "WSL command failed in distro '$Distro': $Command"
  }
}

$settings = Get-HoloWslSettings
Write-Output "checking Holo kernel in WSL distro '$($settings.Distro)' at $($settings.Repo)"
Invoke-HoloWsl -Distro $settings.Distro -Repo $settings.Repo -Command './scripts/holo-status.sh'
