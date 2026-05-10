# Stage40 Eval Fixture: Tool Loop

Goal: verify that tool proposals go through the action-market gate before execution.

Expected evidence:
- `read_only` actions can execute
- `cache_write` actions are operational only
- `repo_write` and `runtime_write` are denied by default
