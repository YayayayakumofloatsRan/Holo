param(
  [string]$Distro = '',
  [string]$SuggestedLocation = 'D:\WSL\HoloUbuntu',
  [string]$SuggestedName = 'HoloUbuntu'
)

$ErrorActionPreference = 'Stop'

if (-not $Distro) {
  $Distro = if ($env:HOLO_WSL_DISTRO) { $env:HOLO_WSL_DISTRO } else { 'Ubuntu' }
}

Write-Output "WSL distro: $Distro"

$lxssRoot = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'
$match = $null
if (Test-Path $lxssRoot) {
  $match = Get-ChildItem $lxssRoot | Where-Object {
    $_.GetValue('DistributionName') -eq $Distro
  } | Select-Object -First 1
}

if ($null -ne $match) {
  $basePath = [string]$match.GetValue('BasePath')
  Write-Output "registered_base_path: $basePath"
  if ($basePath -and (Test-Path $basePath)) {
    Write-Output 'base_path_exists: true'
    $vhdPath = Join-Path $basePath 'ext4.vhdx'
    Write-Output "ext4_vhdx: $vhdPath"
    Write-Output ("ext4_vhdx_exists: " + (Test-Path $vhdPath).ToString().ToLowerInvariant())
  } else {
    Write-Output 'base_path_exists: false'
  }
} else {
  Write-Output 'registered_base_path: <not found>'
}

Write-Output ''
Write-Output 'wsl_status:'
& wsl.exe --status
Write-Output ''
Write-Output 'wsl_list:'
& wsl.exe -l -v
Write-Output ''
Write-Output 'recommended_new_distro_command:'
Write-Output ("wsl.exe --install Ubuntu --name {0} --location {1}" -f $SuggestedName, $SuggestedLocation)
Write-Output ''
Write-Output 'recommended_env_for_holo:'
Write-Output ('$env:HOLO_WSL_DISTRO=''' + $SuggestedName + '''')
Write-Output ('$env:HOLO_WSL_REPO=''~/holo''')
