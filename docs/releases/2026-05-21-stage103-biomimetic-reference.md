# Prerelease Note

## Slice

Stage103 biomimetic semantic-affective reference publish.

## User Impact

The current visualization can now be opened from a stable reference package instead of only from transient `artifacts/` output. The package includes a standalone workbench, sanitized payload, checksums, reproduction commands, and a short research reference note.

## Migration

No runtime migration. Run:

```powershell
python -m holo_host publish-biomimetic-reference
```

## Observability

- reference directory: `references/biomimetic_agent_stage103/`
- manifest: `references/biomimetic_agent_stage103/manifest.json`
- workbench: `references/biomimetic_agent_stage103/stage100_biomimetic_system_workbench.html`
- payload: `references/biomimetic_agent_stage103/stage100_biomimetic_system_payload.json`

## Replay Eval

- replay command:

```powershell
python -m holo_host simulate-biomimetic-telemetry --topics-per-category 4 --turns-per-topic 24 --seed 103 --batch-id stage103-categorized-topic-sweep-final
python -m holo_host visualize-biomimetic-system
python -m holo_host publish-biomimetic-reference
```

- artifact directory: `references/biomimetic_agent_stage103/`
- trajectory_source: `biomimetic_simulation`
- frames: `2304`
- categories: `6`
- topics: `24`
- topology_nodes: `211`
- topology_edges: `329`
- continuity_max_delta: `0.0691`
- continuity_mean_delta: `0.0116`
- large_jumps: `0`

## Rollback

Remove the reference directory and the publish CLI registration. The command is offline and does not alter memory stores, live transport, or provider configuration.
