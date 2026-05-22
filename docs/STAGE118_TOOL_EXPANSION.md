# Stage118 Tool Expansion

## Purpose

Stage118 increases Holo's provider-callable local tool surface from four tools
to eight tools. The goal is to let the model form a Codex-like work loop:

1. recall relevant memory;
2. inspect local files;
3. edit bounded workspace text;
4. inspect git state;
5. run tests;
6. record a short progress note;
7. return a final answer grounded in tool observations.

## Tool Set

Default ordinary Holo chat exposes:

- `memory_recall`
- `external_lookup`
- `workspace_inspect`
- `local_command`
- `workspace_edit`
- `git_inspect`
- `test_runner`
- `progress_note`

## Added Tools

### `workspace_edit`

Bounded UTF-8 text writes inside the workspace:

- `write_file`
- `append_text`
- `replace_text`

It rejects paths outside the workspace and protected paths such as `.git`,
`.holo_runtime`, and `__pycache__`.

### `git_inspect`

Structured read-only git inspection:

- `status_short`
- `diff_check`
- `diff_stat`
- `log_latest`

### `test_runner`

Structured pytest execution through argv, without shell strings. The tool
accepts bounded path patterns, optional `-k` keyword selection, and a timeout.

### `progress_note`

Appends a short local note under `docs/agent_progress_notes`. This is for
operator-visible progress preservation, not hidden memory mutation.

## Safety Boundary

The expanded surface is intentionally not unrestricted shell access. Local
execution authority stays in Holo:

- no shell command strings;
- workspace writes stay inside the configured repo root;
- protected runtime and git paths are rejected;
- test and git tools are structured operations;
- external network use remains controlled by runtime network settings.

## Verification

Primary regression:

```powershell
python -m pytest -q tests\test_stage118_tool_expansion.py --basetemp .holo_runtime\pytest-stage118-green2
```

Expected result:

- provider payload exposes all eight tools;
- `workspace_edit` can write and replace workspace text;
- `progress_note` appends a note;
- `git_inspect` reports local git state;
- `test_runner` runs a bounded pytest target;
- provider can complete `workspace_edit -> test_runner -> git_inspect -> final`;
- ordinary chat metadata exposes all eight tools.

Live DeepSeek smoke:

- forced first tool: `workspace_edit`
- write target: temporary repo `notes/live_stage118.txt`
- observed final `finish_reason=stop`
- observed `agent_tool_loop.round_count=1`
- observed `executed_count=1`
- observed written text: `live stage118 tool ok`
