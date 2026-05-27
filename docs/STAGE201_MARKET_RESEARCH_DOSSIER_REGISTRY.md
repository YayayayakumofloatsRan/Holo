# Stage201 Market Research Dossier Registry

## Purpose

Stage200 can resume a dossier when the current turn already carries it. Stage201 makes market research continuity durable by storing the latest Stage199/Stage200 dossier state under `.holo_runtime` by thread or project key.

This is the next step toward long-running research workspaces: Holo can inspect the latest research dossier without reconstructing chat history.

## Schemas

- `holo.stage201.market_research_dossier_registry.v1`
- `holo.stage201.market_research_dossier_record.v1`
- `holo.stage201.market_research_dossier_lookup.v1`
- `holo.stage201.market_research_dossier_registry_bundle.v1`

## Storage

Records are JSONL runtime state:

```text
.holo_runtime/market_research_dossiers/*.jsonl
```

Each record includes:

- thread key
- project key
- dossier id/status
- question
- source and metric counts
- next-action count
- sanitized Stage199 dossier
- sanitized Stage200 resume report when available

The registry path is scope-key sanitized and forced under the configured runtime state directory.

## Runtime Behavior

When reply runtime builds a Stage199 dossier, Stage201 records it in the registry and exposes:

```text
stage201_market_research_dossier_registry
```

The registry report carries:

- latest lookup result
- new record metadata
- linked Stage200 resume metadata
- canonical stop reason

## CLI

Show the latest dossier for a thread:

```powershell
python -m holo_host market-research-dossier-state --state-dir .holo_runtime --thread-key holo_cli:default
```

Export a registry bundle:

```powershell
python -m holo_host market-research-dossier-state --state-dir .holo_runtime --thread-key holo_cli:default --output artifacts\stage201\stage201_registry.html --dry-run
```

The export writes HTML, JSON, and JSONL.

## Observability

Stage153 renders:

```text
[market_registry] status=resumed lookup=found action=web_search stop=final_answer_ready
```

Stage191 converts this into a public working-memory card.

Stage135 adds `market_research_dossier_registry` topology evidence and metrics:

- `market_research_dossier_registry_node_count`
- `market_research_dossier_registry_status`
- `market_research_dossier_registry_lookup_status`

## Boundaries

Stage201 does not:

- call provider models
- write memory
- start WeChat
- widen transport authority
- expose raw hidden reasoning
- create an unbounded loop

It writes only runtime registry state under `.holo_runtime`.
