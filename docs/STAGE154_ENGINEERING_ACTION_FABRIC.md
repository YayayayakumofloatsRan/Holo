# Stage154 Engineering Action Fabric

Date: 2026-05-27

## Purpose

Stage154 adds a workspace-scoped engineering action fabric for Holo. The goal is practical engineering usefulness: Holo can now represent repo search, file reads, patch application, guarded test commands, git status, and git diff as host-side actions with auditable ledgers.

This stage does not add an approval UI. Approval is treated as out of scope for this milestone, and destructive commands remain rejected by default.

## Schemas

```text
holo.stage154.engineering_action.v1
holo.stage154.engineering_verification_ledger.v1
```

## Host Tools

Implemented host tools:

```text
workspace_search(query, glob)
file_read(path, start_line, end_line)
apply_patch(patch_text)
test_run(command)
git_status()
git_diff(path?)
```

All tools are workspace-scoped. File paths are resolved under the supplied repo root and rejected if they escape the workspace.

`test_run` rejects dangerous commands without an approval UI, including destructive git resets, recursive deletion, shell-piped downloads, common package installs, and obvious credential-file reads.

## Ledger

Every action records:

```text
action_id
action_type
input
status
stdout_summary
stderr_summary
files_read
files_changed
commands_run
tests_run
duration_ms
observed_at
```

The ledger is normalized by `holo_host.engineering_action_fabric.normalize_engineering_action_ledger`.

## Grounding

Stage154 adds deterministic grounding for engineering claims:

- "I read / checked / inspected..." requires a successful `file_read` ledger.
- "I patched / edited / modified..." requires a successful `apply_patch` ledger with changed files.
- "tests passed" requires a successful `test_run` ledger.
- "checked the diff / git status / diff clean" requires a `git_status` or `git_diff` ledger.
- workspace search claims require a successful `workspace_search` ledger.

Unsupported claims are marked `unverified_engineering_claim` and repaired before visible delivery/archive.

## Runtime Propagation

Stage154 propagates:

```text
engineering_action_ledger
engineering_action_count
engineering_claim_grounding
engineering_claim_grounding_status
engineering_claim_unverified_count
```

into reply debug, outgoing metadata, archive/observe metadata, reply JSON, Stage150 evidence views, Stage153 event streams, and Stage135 topology.

## CLI

The interactive CLI can display engineering action events:

```text
[eng:search]
[eng:read]
[eng:patch]
[eng:test]
[eng:diff]
[eng:handoff]
```

It also exposes local engineering commands:

```text
/eng search <query> [glob]
/eng read <path> [start] [end]
/eng patch <patch-file>
/eng test <command>
/eng status
/eng diff [path]
```

These commands operate inside the current repo workspace and record Stage154 ledger rows. They do not start WeChat or widen transport authority.

## Boundaries

Stage154 does not:

- start WeChat
- widen transport authority
- add a provider call path
- add durable memory writes
- implement approval or sandbox UI
- allow destructive commands by default
- treat provider claims as proof of engineering actions

Actual host action ledgers are the source of truth.
