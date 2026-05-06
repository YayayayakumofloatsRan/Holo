param(
  [string]$Distro = '',
  [string]$DestinationRepo = '',
  [switch]$SkipDelete,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

$settings = Get-HoloWslSettings -Distro $Distro -Repo $DestinationRepo -WindowsRepoRoot $root
$sourceRepo = [string]$settings.SourceRepo

$deleteFlag = if ($SkipDelete) { '' } else { '--delete' }
$dryRunFlag = if ($DryRun) { '--dry-run -v' } else { '' }
$excludeFlags = @(
  "--exclude='.git/'",
  "--exclude='.holo_runtime/'",
  "--exclude='.tmp-tests/'",
  "--exclude='.tmp-smoke/'",
  "--exclude='.pytest_cache/'",
  "--exclude='__pycache__/'",
  "--exclude='.vendor/'",
  "--exclude='.holo_host.toml'",
  "--exclude='.codex/hooks.json'",
  "--exclude='holo_memory_library/memories/*.jsonl'",
  "--exclude='codex-smoke-output.txt'",
  "--exclude='injector.log'"
) -join ' '

$command = @(
  "mkdir -p `"$($settings.Repo)`"",
  "rsync -a $deleteFlag $dryRunFlag $excludeFlags `"$sourceRepo/`" `"$($settings.Repo)/`""
) -join '; '

Write-Output "syncing core code to WSL distro '$($settings.Distro)'"
Write-Output "source: $root"
Write-Output "target: $($settings.Repo)"
& wsl.exe -d $settings.Distro -- bash -lc $command
if ($LASTEXITCODE -ne 0) {
  throw "core sync failed for distro '$($settings.Distro)'"
}
Write-Output 'core sync complete'

$memoryMergeCommand = @(
  "cd `"$($settings.Repo)`"",
  "python3 ./scripts/merge_memory_jsonl.py --source-dir `"$sourceRepo/holo_memory_library/memories`" $(if ($DryRun) { '--dry-run' } else { '' })"
) -join ' && '

Write-Output "merging memory streams into WSL distro '$($settings.Distro)'"
& wsl.exe -d $settings.Distro -- bash -lc $memoryMergeCommand
if ($LASTEXITCODE -ne 0) {
  throw "memory merge failed for distro '$($settings.Distro)'"
}
Write-Output 'memory merge complete'

$memoryMirrorFlag = if ($DryRun) { '--dry-run -v' } else { '' }
$memoryMirrorCommand = @(
  "mkdir -p `"$sourceRepo/holo_memory_library/memories`"",
  "rsync -a $memoryMirrorFlag `"$($settings.Repo)/holo_memory_library/memories/working_store.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/memory_store.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/candidate_store.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/conversation_archive.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/emotion_trace.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/callback_candidates.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/thought_stream.jsonl`" `"$($settings.Repo)/holo_memory_library/memories/initiative_candidates.jsonl`" `"$sourceRepo/holo_memory_library/memories/`""
) -join '; '

Write-Output "mirroring merged memory back to Windows repo at $root"
& wsl.exe -d $settings.Distro -- bash -lc $memoryMirrorCommand
if ($LASTEXITCODE -ne 0) {
  throw "memory mirror failed for distro '$($settings.Distro)'"
}
Write-Output 'memory mirror complete'
