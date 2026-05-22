# Stage119 Common Tool Library

Date: 2026-05-22

Stage119 expands the provider-facing Holo agent tool surface from the Stage118
8-tool core to 41 common tools. The provider may propose tool calls, but Holo
still validates and executes every tool locally through the WSL/local brain.

## Tool Surface

Core continuity tools:

- `memory_recall`
- `external_lookup`
- `workspace_inspect`
- `local_command`
- `workspace_edit`
- `git_inspect`
- `test_runner`
- `progress_note`

Read-only common tools:

- `file_read`
- `file_list`
- `file_search`
- `file_stat`
- `directory_tree`
- `json_read`
- `toml_read`
- `markdown_outline`
- `symbol_search`
- `repo_overview`
- `git_status`
- `git_diff`
- `git_log`
- `test_discover`
- `python_module_check`
- `config_inspect`
- `runtime_health`
- `memory_warehouse_search`
- `doc_lookup`
- `artifact_list`
- `env_read`
- `dependency_check`
- `time_now`
- `path_resolve`
- `workspace_snapshot`
- `command_run`

Permissioned modifying tools:

- `workspace_edit`
- `progress_note`
- `file_write`
- `file_replace`
- `file_append`
- `note_append`
- `git_stage`
- `git_commit`
- `command_modify`

## Permission Model

Modifying tools do not run from provider intent alone. The host must pass an
explicit permission grant into the local executor:

```json
{
  "tool_permission_grants": [
    {"tool": "file_write"},
    {"tool": "command_modify", "argv_prefix": ["git", "add"]}
  ]
}
```

If no grant matches the tool and optional command prefix, the executor returns a
normal tool observation with `status=rejected` and `reason=host_permission_required`.
This keeps the provider loop continuous while preventing unapproved file or git
mutation.

Interactive CLI grants are one-shot:

```text
/grant file_write
/grant command_modify git add
```

The queued grant is attached only to the next user turn and is then cleared.

`command_run` remains read-only and allowlisted. `command_modify` is a separate
permissioned surface and currently supports bounded git mutation commands:

- `git add <workspace paths>`
- `git commit -m <message>`
- `git restore --staged <workspace paths>`

Shell strings are still rejected; commands are argv-only.

## Architecture Notes

- Tool schemas live in `holo_host/stage106_deepseek_tool_adapter.py`.
- Tool execution lives in `holo_host/stage113_agent_tool_executor.py`.
- Default tool exposure is injected by `holo_host/processors.py`.
- Provider tool-loop authorization is passed through `holo_host/codex_runner.py`.
- Stage119 does not touch or start WeChat/watchers; `runtime_health` explicitly
  reports local runtime paths only.

## Verification

- `python -m pytest -q tests/test_stage119_tool_library_expansion.py --basetemp=.pytest_tmp_stage119`
- `python -m pytest -q tests/test_stage118_tool_expansion.py --basetemp=.pytest_tmp_stage118`
- `python -m pytest -q --basetemp=.pytest_tmp_full_stage119`
