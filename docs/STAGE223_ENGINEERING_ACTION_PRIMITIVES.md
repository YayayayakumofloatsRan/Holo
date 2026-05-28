# Stage223 Engineering Action Primitives

Stage223 adds the first Codex/Claude-Code-style engineering action surface to
Holo Agent Kernel `2.1.0`.

## Principle

The model decides the workflow. The host provides bounded primitive tools and
records observations.

This stage does not add a keyword playbook. It exposes engineering affordances
to the action space so the model can choose them:

- `workspace_search`
- `file_read`
- `git_status`
- `git_diff`
- `test_run`
- `apply_patch`

## Tool Boundaries

### `file_read`

Reads UTF-8 text inside the workspace with optional line ranges. Path escape is
rejected.

### `git_status`

Runs:

```text
git status --short
```

### `git_diff`

Runs:

```text
git diff --
git diff -- <workspace-relative-path>
```

Path escape is rejected.

### `test_run`

Runs allowlisted commands without a shell:

```text
python -m pytest ...
pytest ...
python scripts/check_public_release_hygiene.py
git status --short
git diff -- [path]
```

Shell chaining, redirects, pipes, package installs, network installers, and
delete commands are rejected.

### `apply_patch`

Applies a simple workspace-scoped `*** Begin Patch` update. This is deliberately
minimal and should be replaced by a richer patch engine later. It already
rejects path escape.

## Current Gap

The action surface is now available, but the model prompt still needs stronger
task framing for complex engineering jobs:

- inspect before patching
- run targeted tests after patching
- produce final answer only from observed ledgers
- use `git_diff` / `git_status` before handoff

That should be the next stage.
