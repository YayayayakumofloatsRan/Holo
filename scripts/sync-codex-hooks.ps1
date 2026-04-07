$ErrorActionPreference = 'Stop'

$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$hooksDir = Join-Path $root '.codex'
$hooksPath = Join-Path $hooksDir 'hooks.json'
$python = if ($env:HOLO_HOOK_PYTHON) {
  $env:HOLO_HOOK_PYTHON
} else {
  (Get-Command python -ErrorAction Stop).Source
}

function Quote-Path([string]$Value) {
  if ($Value.Contains(' ')) {
    return '"' + $Value.Replace('"', '\"') + '"'
  }
  return $Value
}

$submit = (Join-Path $root 'holo_memory_library\codex_hooks\user_prompt_submit.py').Replace('\', '/')
$stop = (Join-Path $root 'holo_memory_library\codex_hooks\stop_revise.py').Replace('\', '/')
$pythonCmd = Quote-Path (($python).Replace('\', '/'))

$payload = @{
  hooks = @{
    UserPromptSubmit = @(
      @{
        matcher = '*'
        hooks = @(
          @{
            type = 'command'
            command = "$pythonCmd $submit"
          }
        )
      }
    )
    Stop = @(
      @{
        matcher = '*'
        hooks = @(
          @{
            type = 'command'
            command = "$pythonCmd $stop"
          }
        )
      }
    )
  }
}

New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null
$json = $payload | ConvertTo-Json -Depth 8
$tmpPath = "$hooksPath.tmp"
[System.IO.File]::WriteAllText($tmpPath, $json, [System.Text.Encoding]::UTF8)
Move-Item -Path $tmpPath -Destination $hooksPath -Force
Write-Output "updated $hooksPath"
