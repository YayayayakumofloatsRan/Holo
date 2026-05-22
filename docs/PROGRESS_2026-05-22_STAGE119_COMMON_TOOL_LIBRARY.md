# Progress: Stage119 Common Tool Library

Date: 2026-05-22

## Goal

Expand Holo's provider-facing tool library from the Stage118 8-tool surface to
dozens of common tools, including command-line affordances, while requiring
explicit host permission for modifying tools.

## Completed

- Added 33 Stage119 tool schemas on top of the Stage118 core, for 41 total
  provider-callable tools.
- Added default Stage119 tool exposure for Holo replies through
  `_agent_tool_requests`.
- Added read-only wrappers for files, directories, JSON/TOML, Markdown outlines,
  git inspection, test discovery, Python syntax checks, docs/artifacts, env
  status, dependency manifests, time, path resolution, and workspace snapshots.
- Added permission gates for:
  - `workspace_edit`
  - `progress_note`
  - `file_write`
  - `file_replace`
  - `file_append`
  - `note_append`
  - `git_stage`
  - `git_commit`
  - `command_modify`
- Passed provider metadata grants into local tool execution with
  `tool_permission_grants` and `approved_tool_permissions`.
- Added one-shot interactive CLI grants through `/grant <tool> [argv prefix]`.
- Kept shell execution disabled; command tools remain argv-only.
- Did not touch live WeChat or watcher transport.

## Verification

```text
python -m pytest -q tests/test_stage119_tool_library_expansion.py --basetemp=.pytest_tmp_stage119
5 passed in 0.99s
```

```text
python -m pytest -q tests/test_stage118_tool_expansion.py --basetemp=.pytest_tmp_stage118
5 passed in 20.57s
```

```text
python -m pytest -q --basetemp=.pytest_tmp_full_stage119
397 passed in 146.36s (0:02:26)
```

## Next

Stage120 should evaluate tool-choice behavior in live or simulated provider
dialogues: whether the model chooses the right read tool first, when it requests
permissioned tools, and whether tool observations reduce hallucination in
multi-turn tasks.
