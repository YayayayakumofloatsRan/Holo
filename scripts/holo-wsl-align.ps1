param(
  [string]$Distro = '',
  [string]$DestinationRepo = '',
  [switch]$Force,
  [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
. (Join-Path $PSScriptRoot 'holo-wsl-common.ps1')

function ConvertTo-BashSingleQuoted([string]$Value) {
  return "'" + ([string]$Value).Replace("'", "'`"`"`'") + "'"
}

$settings = Get-HoloWslSettings -Distro $Distro -Repo $DestinationRepo -WindowsRepoRoot $root
$sourceRepo = [string]$settings.SourceRepo
$sourceBranch = (git -C $root branch --show-current).Trim()
if (-not $sourceBranch) {
  throw 'The Windows repo must be on a named branch before aligning WSL.'
}
$sourceHead = (git -C $root rev-parse HEAD).Trim()
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$quotedRepo = ConvertTo-BashSingleQuoted $settings.Repo
$quotedSourceRepo = ConvertTo-BashSingleQuoted $sourceRepo
$quotedBranch = ConvertTo-BashSingleQuoted $sourceBranch
$quotedHead = ConvertTo-BashSingleQuoted $sourceHead
$quotedStamp = ConvertTo-BashSingleQuoted $stamp
$forceFlag = if ($Force) { '1' } else { '0' }
$dryRunFlag = if ($DryRun) { '1' } else { '0' }

$command = @"
set -euo pipefail
repo=$quotedRepo
source_repo=$quotedSourceRepo
source_branch=$quotedBranch
source_head=$quotedHead
stamp=$quotedStamp
force=$forceFlag
dry_run=$dryRunFlag

private_paths=(
  ".holo_runtime"
  ".holo_host.toml"
  ".subject.local.md"
  ".codex"
  "holo_memory_library/subject_seed.md"
  "holo_memory_library/voice_profile.md"
  "windows_helper/wechat_helper.live.json"
)

parent=`$(dirname "`$repo")
base=`$(basename "`$repo")
replacement="`$parent/.`$base.align-`$stamp"
old_repo="`$parent/`$base.pre-align-`$stamp"

echo "source_repo=`$source_repo"
echo "source_branch=`$source_branch"
echo "source_head=`$source_head"
echo "target_repo=`$repo"

if [ "`$dry_run" = "1" ]; then
  echo "dry_run=true"
  exit 0
fi

running=`$(pgrep -af 'python3 -m holo_[h]ost|pyweixin_[w]atcher.pyw|wechat_[h]elper.py.*watch' || true)
if [ -n "`$running" ] && [ "`$force" != "1" ]; then
  echo "Holo runtime processes appear to be running:" >&2
  echo "`$running" >&2
  echo "Stop Holo first or rerun with -Force after verifying it is safe." >&2
  exit 3
fi

if [ -e "`$replacement" ] || [ -e "`$old_repo" ]; then
  echo "Refusing to overwrite an existing alignment path." >&2
  echo "replacement=`$replacement" >&2
  echo "old_repo=`$old_repo" >&2
  exit 4
fi

git clone --no-hardlinks --branch "`$source_branch" "`$source_repo" "`$replacement"
cd "`$replacement"
actual_head=`$(git rev-parse HEAD)
if [ "`$actual_head" != "`$source_head" ]; then
  git fetch "`$source_repo" "`$source_head"
  git checkout --detach "`$source_head"
fi

if [ -d "`$repo" ]; then
  for path in "`${private_paths[@]}"; do
    if [ -e "`$repo/`$path" ]; then
      if [ -d "`$repo/`$path" ]; then
        mkdir -p "`$replacement/`$path"
        rsync -a "`$repo/`$path/" "`$replacement/`$path/"
      else
        mkdir -p "`$(dirname "`$replacement/`$path")"
        rsync -a "`$repo/`$path" "`$replacement/`$path"
      fi
      echo "preserved_private_path=`$path"
    fi
  done
  memory_dir="`$repo/holo_memory_library/memories"
  replacement_memory_dir="`$replacement/holo_memory_library/memories"
  if [ -d "`$memory_dir" ]; then
    mkdir -p "`$replacement_memory_dir"
    shopt -s nullglob
    for memory_file in "`$memory_dir"/*.jsonl; do
      rsync -a "`$memory_file" "`$replacement_memory_dir/"
      echo "preserved_private_path=holo_memory_library/memories/`$(basename "`$memory_file")"
    done
  fi
  mv "`$repo" "`$old_repo"
  echo "previous_repo_backup=`$old_repo"
fi

mv "`$replacement" "`$repo"
cd "`$repo"
new_head=`$(git rev-parse HEAD)
if [ "`$new_head" != "`$source_head" ]; then
  echo "Aligned repo head mismatch: `$new_head != `$source_head" >&2
  exit 5
fi
echo "aligned_head=`$new_head"
git status --short
"@

Write-Output "aligning WSL repo '$($settings.Repo)' in distro '$($settings.Distro)'"
$tempScript = New-TemporaryFile
try {
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($tempScript.FullName, $command, $utf8NoBom)
  $wslScript = Convert-WindowsPathToWsl $tempScript.FullName
  & wsl.exe -d $settings.Distro -- bash $wslScript
  if ($LASTEXITCODE -ne 0) {
    throw "WSL alignment failed for distro '$($settings.Distro)'"
  }
} finally {
  Remove-Item -LiteralPath $tempScript.FullName -Force -ErrorAction SilentlyContinue
}
Write-Output 'WSL repo alignment complete'
