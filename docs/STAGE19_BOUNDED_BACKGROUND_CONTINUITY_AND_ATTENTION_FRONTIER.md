# Stage19 Bounded Background Continuity And Attention Frontier

## Goal

Stage19 makes continuity survive short idle gaps by keeping a bounded attention frontier warm with existing runtime machinery.

The frontier answers a narrow question: which current threads or unfinished lines deserve light continuity awareness if a turn arrives soon?

## Boundary

- No second brain layer.
- No new unbounded always-on loop.
- No new proactive send rights.
- No transport-side policy, recall, or reply selection.
- No raw full-history cache in the frontier.
- Preserve action-market-first deliberation.
- Reuse existing daemon loops and stream machinery where possible.

## Runtime Shape

Stage19 should reuse existing loops:

- `attention_tick`
- `continuity_audit`
- `association_stream`
- `social_stream`
- `deep_dream_cycle` only when already enabled by mode and idle rules

The new object is an attention frontier, not a second runtime. It is bounded, inspectable, and expires entries.

The frontier should be refreshed by existing loop ticks and by normal turn ingestion. It should not run its own infinite scan.

## Data Contract

The frontier can be implemented as a Mind Graph table or as a bounded state object under runtime state, but it must be surfaced consistently through diagnostics.

Minimum `attention_frontier` entry fields:

```json
{
  "channel": "wechat",
  "thread_key": "wechat:Nemoqi",
  "chat_name": "Nemoqi",
  "attention_score": 0.0,
  "frontier_reason": "",
  "open_line": "",
  "suggested_preheat": [],
  "last_event_at": "",
  "expires_at": "",
  "source_loop": "attention_tick",
  "evidence_refs": []
}
```

Bounded defaults:

- max frontier entries: `8`
- max open lines per thread: `1`
- max suggested preheat refs per thread: `3`
- expired entries are ignored before packet assembly

`mind_packet.stage19` should include:

```json
{
  "frontier_visible": false,
  "frontier_used_for_thread": false,
  "frontier_reason": "",
  "frontier_score": 0.0,
  "frontier_expired": false,
  "frontier_entry_count": 0
}
```

## Action Market Contract

The frontier may influence:

- recall ordering
- active-state warmth
- continuity pull
- whether a same-thread short turn starts with `active_thread` or graph recall

The frontier may not:

- send messages
- create initiative jobs
- bypass cooldowns or whitelist policy
- select actions without the action market
- refresh WeChat history by itself

## Acceptance Checklist

Closure command:

```bash
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
```

The acceptance gate should verify:

- Stage18 remains green.
- Existing loop names are reused; no Stage19-only always-on loop is required.
- A bounded frontier entry is produced from a continuity-relevant thread.
- Frontier entries include evidence refs and expiry.
- Expired frontier entries are ignored.
- A same-thread packet can see a valid frontier entry.
- A different thread cannot receive the same frontier entry.
- Initiative sending behavior is unchanged.
- Stream status or a dedicated diagnostic exposes frontier count and latest update.

Recommended regression commands:

```bash
pytest -q tests/test_stage19_attention_frontier.py
pytest -q tests/test_stage18_dual_speed_reflex.py tests/test_stage17_realtime_runtime.py
python -m holo_host --config .holo_host.example.toml accept-stage19 --thread-key Nemoqi --chat-name Nemoqi --channel wechat
pytest -q
```

## Regression Risks

- A new background loop duplicates daemon responsibility.
- Frontier refresh scans unbounded history.
- Frontier entries leak across thread aliases.
- Social stream influence accidentally schedules initiative.
- Frontier state becomes another memory layer instead of an index over existing memory.
- Idle stream ticks increase latency on ordinary live turns.

## Rollback

Stage19 should degrade by returning an empty frontier. Stage18 predictive continuity and Stage17 active-thread fast lane must still work when frontier state is missing.
