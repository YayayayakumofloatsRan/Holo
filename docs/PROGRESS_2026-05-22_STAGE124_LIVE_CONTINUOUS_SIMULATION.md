# Progress 2026-05-22: Stage124 Live Continuous Simulation

## Scope

Ran a live continuous-dialogue simulation against Holo through the WSL CLI using
one subject thread:

- `thread_key=holo_cli:stage124-sim`
- `chat_name=Stage124Sim`
- transport observed by CLI: `live_http`
- live API checkout observed in reply metadata: `/home/holo/holo`
- mirror/current development checkout: `/mnt/d/Holo/holo`

We did not start, stop, or modify the WeChat watcher.

## Dialogue Turns

| Turn | Probe | Result |
| --- | --- | --- |
| 1 | Session-goal orientation and external-only speech | Holo answered with coherent subject framing and recall caution. Route was `deep_recall`; first JSON showed live API path `/home/holo/holo`. |
| 2 | Store continuity marker `STAGE124_ANCHOR blue-lattice` | Holo accepted the marker and encoded it as a vivid "blue lattice / trackside cloth" image. |
| 3 | Recall previous marker | Holo recalled `STAGE124_ANCHOR` and "blue lattice" correctly. |
| 4 | Ask internal tool flow to inspect repo/stage state | Holo replied that the tool-flow file had not "grown out" yet. This matched the live checkout, not the mirror checkout. |
| 5 | Affective frustration probe | Holo responded with emotional grounding and named cache/latency as the concrete diagnosis, but stayed metaphor-heavy. |
| 6 | Self-summary | Holo summarized the marker, tool-flow limitation, and cache/latency issue, preserving continuity. |

## Evidence

Provider status before simulation:

- active backend: `deepseek`
- `deepseek.available=true`
- live lanes route `reply` to `subject_main`, model `deepseek-v4-pro`

Memory health before simulation:

- memory JSONL and SQLite substrates parse cleanly
- `conversation_archive.jsonl`: 734 valid rows
- `mind_graph.sqlite3` integrity: `ok`
- vector substrate file exists
- `semantic_consolidation`: `critical`, durable semantic memory is about 43 days behind archive
- `episodic_semantic_balance`: `warn`, archive-to-durable ratio about 34.95
- `thread_continuity`: `warn`, one thread fragmentation candidate

Live/repo divergence:

```text
/home/holo/holo HEAD: cb69e9f Document biomimetic dialogue boundary test
/home/holo/holo stage123 file: missing

/mnt/d/Holo/holo HEAD: ed92837 Add Holo internal tool flow bridge
/mnt/d/Holo/holo stage123 file: present
```

This explains why the live dialogue did not demonstrate Stage123 even though
the current development checkout implements it.

Usage ledger for the six reply turns:

| Event | Duration | Total tokens |
| --- | ---: | ---: |
| 51 | 22446 ms | 2986 |
| 52 | 20141 ms | 3126 |
| 53 | 17471 ms | 3540 |
| 54 | 13658 ms | 3450 |
| 55 | 15848 ms | 3781 |
| 56 | 15398 ms | 4124 |

Reply-only total for the six turns: 21007 tokens. Additional
`recall_reconstruct`, `reflect`, and background observation calls were also
visible in the ledger around the same run.

Local Stage123 contract smoke in the mirror checkout:

```text
stage=123
internal_tool_calls.enabled=true
tool_authority.provider_may_propose_tools=true
tool_authority.provider_may_execute_tools=false
tool_authority.executor=holo_wsl_brain_stage113
loop phases include tool_observation_reentry
```

## Capability Verdict

Passed:

- Live DeepSeek provider path is available.
- Continuous thread identity works across six CLI turns.
- Short-term continuity marker recall worked exactly.
- External speech did not expose raw hidden reasoning.
- Affective response is alive enough to avoid sterile assistant tone.
- Active thread state, scene state, recall reconstruction, and usage ledger are
  populated.

Partial:

- Memory/RAG is functional but stale: semantic consolidation is behind archive,
  so recall quality is vulnerable to old durable memory dominating current
  continuity.
- The style is expressive, but sometimes too metaphorical for engineering
  diagnostics.
- Latency is usable for a slow research shell but not yet good enough for a
  fluent chat product.

Failed / blocked:

- The live API did not run the latest Stage123 code. It served from
  `/home/holo/holo`, where `holo_host/stage123_internal_tool_flow.py` was
  missing.
- Therefore the live conversation could not honestly validate mature internal
  tool-flow behavior. The mirror checkout validates Stage123 structurally, but
  the running live brain must be aligned and reloaded before a live tool-flow
  verdict is meaningful.

## Next Actions

1. Align `/home/holo/holo` with `/mnt/d/Holo/holo` or switch the live API to the
   current checkout.
2. Restart/reload the Holo API after alignment, without touching WeChat watcher.
3. Rerun the same six-turn simulation and require Stage123 metadata to appear
   in live reply debug/usage evidence.
4. Tune recall routing so simple immediate-marker recalls do not trigger
   expensive deep recall unless needed.
5. Run a bounded semantic consolidation pass to reduce the 43-day durable memory
   lag and archive/durable imbalance.
