# Public Release Hygiene

This repository is publishable only when the public tree contains runtime code, architecture docs, examples, and tests, but not one deployment's private subject memory or personality files.

## Current Version State
- Active branch at the time this hygiene pass was created: `codex/stage27-blackbox-soak`.
- Remote: `origin` points to `https://github.com/YayayayakumofloatsRan/Holo.git`.
- Local branch was ahead of `origin/codex/stage27-blackbox-soak` by two Stage28 commits before this pass.
- Stage28 runtime verification had passed before this pass; this pass is release-surface hygiene and does not start Holo.

## Public Versus Private
- Public templates: `.subject.example.md`, `holo_memory_library/subject_seed.example.md`, `holo_memory_library/voice_profile.example.md`.
- Private local files: `.subject.local.md`, `holo_memory_library/subject_seed.md`, `holo_memory_library/voice_profile.md`.
- Private live stores: `holo_memory_library/memories/*.jsonl`.
- Private runtime state: `.holo_runtime/`, SQLite databases, transport receipts, snapshots, canary artifacts, and live helper config.

## Required Before Push
1. Run `git status --short --branch` and confirm the intended branch.
2. Run `git ls-files` or `python scripts/check_public_release_hygiene.py` and confirm no private profile, memory, runtime, artifact, or live transport file is tracked.
3. Run the relevant tests for the changed surface.
4. Confirm Holo remains stopped if the task is publish hygiene only.

## Rationale
The public project should be reusable as a configurable subject-runtime kernel. Local memory and local personality are deployment data, not universal source code. Public defaults must therefore be generic and template-based, while real deployments restore their private profile and memory only on trusted machines or private stores.
