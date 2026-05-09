# Holo

Holo is an experimental subject-runtime host for building a bounded, inspectable conversational agent around durable local state, replaceable processors, and transport shells that only act as eyes and hands.

The repository is published as a generic runtime kernel. It does not include a live deployment's private subject profile, chat history, long-term memory, runtime databases, transport receipts, or canary artifacts.

## Core Architecture

- `holo_host/`: host runtime, reply API, daemon, queue store, Mind Graph bridge, action selection, replay, diagnostics, and acceptance gates.
- `holo_memory_library/`: local memory lifecycle tooling and public templates for private subject profiles.
- `windows_helper/`: Windows-side transport shell for local WeChat automation; it must not make subject decisions.
- `docs/`: architecture maps, stage notes, handoffs, and release hygiene rules.
- `tests/`: regression coverage for host behavior, memory fabric, replay, canary safety, and transport helpers.

## Runtime Contracts

- Memory is self-state, but private deployment memory stays outside the public repository.
- Processors are replaceable compute; model calls should go through the processor fabric.
- Transports are eyes and hands only; they do not choose actions.
- Action-market selection happens before language generation.
- No second brain layer, no unbounded always-on loop, and no live repo hot-editing from runtime state.

## Public Versus Private Files

Tracked public templates:
- `.subject.example.md`
- `holo_memory_library/subject_seed.example.md`
- `holo_memory_library/voice_profile.example.md`

Local/private deployment files:
- `.subject.local.md`
- `holo_memory_library/subject_seed.md`
- `holo_memory_library/voice_profile.md`
- `.holo_runtime/`
- `holo_memory_library/memories/*.jsonl`
- `artifacts/`
- `windows_helper/wechat_helper.live.json`

Before publishing, run:

```powershell
python scripts\check_public_release_hygiene.py
pytest -q tests\test_public_release_hygiene.py
```

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
Copy-Item .holo_host.example.toml .holo_host.toml
Copy-Item .subject.example.md .subject.local.md
Copy-Item holo_memory_library\subject_seed.example.md holo_memory_library\subject_seed.md
Copy-Item holo_memory_library\voice_profile.example.md holo_memory_library\voice_profile.md
pytest -q
```

Then adjust `.holo_host.toml` and the local private profile files for the target deployment.

## Safety Notes

- Do not publish private profiles, memory JSONL, runtime databases, helper receipts, snapshots, or artifact exports.
- Do not enable live canary or transport automation without reading the watcher contract and current handoff.
- Keep public examples generic. Use placeholder thread keys such as `wechat:TestUser` in tests and docs.

## Offline Bionic Kernel Probe

The current offline agent surface is the bionic subject kernel plus subject-loop diagnostics:

```powershell
python -m holo_host agent-run --query "continue" --thread-key cli:TestUser --chat-name TestUser --channel cli --offline
python -m holo_host show-bionic-metrics
python -m holo_host show-subject-loop-metrics
python -m holo_host accept-stage31 --thread-key cli:TestUser --chat-name TestUser --channel cli
```

These commands do not start WeChat, do not send transport messages, and do not write private self-memory.
