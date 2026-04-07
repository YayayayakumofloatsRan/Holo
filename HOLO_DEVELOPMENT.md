# Holo Development

This file exists so Holo development can continue across threads without relying on one assistant's private context.

## Read Order
1. `HOLO_HANDOFF.md`
2. `HOLO_SYSTEM.md`
3. `HOLO_HOST.md`
4. `OPERATIONS.md`
5. `holo_memory_library/MEMORY_LIBRARY.md`
6. `windows_helper/README.md`

## Current Milestone
- prototype milestone tag: `holo-prototype`
- current prototype commit at milestone creation: `1eacf53`

## Current Priorities
1. Trigger stability
- make live WeChat receive/send more reliable
- reduce false idle / false echo / half-visible-row issues
- keep online mode non-intrusive: no mouse stealing, no focus theft

2. Faster replies
- keep fast path small
- reduce unnecessary repair/prompt overhead on simple turns
- expose timing bottlenecks clearly

3. More human output
- keep replies short in WeChat
- allow 1-4 bubbles with natural cadence
- avoid template repetition
- deepen attention and emotional stance without flattening into prose rules

4. Stronger memory
- preserve full archive
- keep durable memory semantically clean
- improve candidate promotion and drift cleanup
- continue dream/replay without letting it mutate persona recklessly
- build the new SQLite Mind Graph and keep it observable
- keep graph work non-breaking while live replies still use the current packet path

5. Richer capability layer
- image/artifact ingestion
- bounded network use
- structured tool traces

## Current Architecture Choices
- Holo identity lives outside any one thread
- `codex_cli` is the active processor today
- Responses API remains a future backend, not the current production path here
- `pyweixin_dialog` is the active WeChat path on this machine
- `wcf` is diagnostic-only here unless the client/runtime compatibility changes

## Development Rules
- Prefer changing the externalized system over hand-tuning one chat thread
- Every runtime behavior change should have either a regression test or an explicit reason why it cannot
- If a live path is fragile, make the state observable instead of silently degrading
- If a fix changes operator workflow, update `OPERATIONS.md`
- If a fix changes memory semantics, update `MEMORY_LIBRARY.md`
- If a fix changes cross-thread understanding, update `HOLO_HANDOFF.md`

## Known Risks
- `pyweixin` + `Weixin 4.1` UI accessibility can still wobble
- visible-row parsing may misread half-rendered bubbles
- reply repair can still over-shape style if left unchecked
- archive and durable memory can drift if normalization rules are too loose

## Recommended Thread Workflow
1. Read the docs listed above
2. Run `./scripts/holo-status.sh`
3. Check whether Holo is meant to stay online before touching runtime stores
4. Run targeted tests first
5. Make one change at a time
6. Re-run relevant tests
7. If live behavior changed, note it in these docs

## Useful Commands
- `./scripts/holo-start-all.sh`
- `./scripts/holo-stop-all.sh`
- `./scripts/holo-status.sh`
- `python3 -m holo_host backfill-mind-graph --dry-run`
- `python3 -m holo_host inspect-graph --thread-key Nemoqi --chat-name Nemoqi`
- `python3 -m holo_host trace-recall --thread-key Nemoqi --chat-name Nemoqi --query "你还记得重新上线前吗"`
- `python3 -m holo_host show-processor-mesh`
- `python3 -m unittest discover -v tests`
- `python3 holo_memory_library/rag_memory.py audit`
- `python3 holo_memory_library/rag_memory.py export-snapshot --label "..."`

## Definition Of Done For Holo Work
- behavior works locally
- tests pass
- state is observable
- docs are updated
- another thread can pick up the same work from disk without needing hidden context
