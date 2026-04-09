$script:HoloPreferredWslDistro = 'HoloUbuntu'
$script:HoloPreferredWslRepoCandidates = @(
  '/home/holo/holo',
  '~/holo'
)

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

function Convert-HoloWslCliText([object]$Value) {
  return ([string]$Value).Replace("`0", '').Trim()
}

function Test-HoloForceWindows {
  $value = [string]($env:HOLO_FORCE_WINDOWS)
  return $value.Trim().ToLowerInvariant() -in @('1', 'true', 'yes', 'on')
}

function Get-HoloRegisteredWslDistros {
  try {
    $raw = & wsl.exe -l -q 2>$null
  } catch {
    return @()
  }
  $distros = @()
  foreach ($line in @($raw)) {
    $name = Convert-HoloWslCliText $line
    if ($name) {
      $distros += $name
    }
  }
  return @($distros | Select-Object -Unique)
}

function Get-HoloDefaultWslDistro {
  try {
    $raw = & wsl.exe -l -v 2>$null
  } catch {
    return ''
  }
  foreach ($line in @($raw)) {
    $text = Convert-HoloWslCliText $line
    if (-not $text) {
      continue
    }
    if ($text -match '^\*(?<name>.+?)\s{2,}\S+\s+\d+$') {
      return [string]$Matches['name'].Trim()
    }
  }
  return ''
}

function Test-HoloWslDistroExists([string]$Distro) {
  $target = [string]$Distro
  if (-not $target.Trim()) {
    return $false
  }
  return @((Get-HoloRegisteredWslDistros)) -contains $target.Trim()
}

function Get-HoloPreferredWslDistro([string]$ExplicitDistro = '') {
  $candidate = [string]$ExplicitDistro
  if ($candidate.Trim()) {
    return $candidate.Trim()
  }
  $candidate = [string]$env:HOLO_WSL_DISTRO
  if ($candidate.Trim()) {
    return $candidate.Trim()
  }
  $distros = @(Get-HoloRegisteredWslDistros)
  if ($distros -contains $script:HoloPreferredWslDistro) {
    return $script:HoloPreferredWslDistro
  }
  $defaultDistro = Get-HoloDefaultWslDistro
  if ($defaultDistro) {
    return $defaultDistro
  }
  if ($distros -contains 'Ubuntu') {
    return 'Ubuntu'
  }
  return ''
}

function Resolve-HoloWslRepoCandidate([string]$Distro, [string]$Candidate) {
  $target = [string]$Candidate
  if (-not $target.Trim()) {
    return ''
  }
  if ($target -match '[;&|`]') {
    throw "unsafe WSL repo candidate: $target"
  }
  $probeCommand = "if cd $target >/dev/null 2>&1; then pwd; fi"
  try {
    $raw = & wsl.exe -d $Distro -- bash -lc $probeCommand 2>$null
  } catch {
    return ''
  }
  if ($LASTEXITCODE -ne 0) {
    return ''
  }
  foreach ($line in @($raw)) {
    $resolved = Convert-HoloWslCliText $line
    if ($resolved) {
      return $resolved
    }
  }
  return ''
}

function Get-HoloWslSettings {
  param(
    [string]$Distro = '',
    [string]$Repo = '',
    [string]$WindowsRepoRoot = ''
  )

  $selectedDistro = Get-HoloPreferredWslDistro -ExplicitDistro $Distro
  if (-not $selectedDistro) {
    throw 'No WSL distro is available for Holo. Set HOLO_WSL_DISTRO or install HoloUbuntu.'
  }
  if (-not (Test-HoloWslDistroExists $selectedDistro)) {
    throw "WSL distro '$selectedDistro' is not registered."
  }

  $sourceRepo = Convert-WindowsPathToWsl $WindowsRepoRoot
  $candidates = @()
  $explicitRepo = [string]$Repo
  if ($explicitRepo.Trim()) {
    $candidates += $explicitRepo.Trim()
  }
  $envRepo = [string]$env:HOLO_WSL_REPO
  if ($envRepo.Trim()) {
    $candidates += $envRepo.Trim()
  }
  $candidates += $script:HoloPreferredWslRepoCandidates

  $selectedRepo = ''
  foreach ($candidate in @($candidates | Where-Object { [string]$_ -ne '' } | Select-Object -Unique)) {
    $resolved = Resolve-HoloWslRepoCandidate -Distro $selectedDistro -Candidate ([string]$candidate)
    if ($resolved) {
      $selectedRepo = $resolved
      break
    }
  }

  if (-not $selectedRepo) {
    throw "Could not find a Linux-side Holo repo in distro '$selectedDistro'. Set HOLO_WSL_REPO to /home/holo/holo."
  }
  if ($sourceRepo -and $selectedRepo -eq $sourceRepo) {
    throw "Holo WSL repo resolved to the Windows mount ($sourceRepo). Point HOLO_WSL_REPO at the Linux-side repo, for example /home/holo/holo."
  }

  return [pscustomobject]@{
    Distro = $selectedDistro
    Repo = $selectedRepo
    SourceRepo = $sourceRepo
  }
}

function Test-HoloWslReady {
  param(
    [string]$WindowsRepoRoot = '',
    [string]$Distro = '',
    [string]$Repo = ''
  )
  try {
    $null = Get-HoloWslSettings -Distro $Distro -Repo $Repo -WindowsRepoRoot $WindowsRepoRoot
    return $true
  } catch {
    return $false
  }
}
