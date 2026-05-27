# Stage171 Market Research Pack Action

Stage171 makes the Stage170 `market_research_pack` affordance executable by the host. The model can now select the market-research pack action, the host builds or rejects the pack, and the resulting ledger feeds Stage170 answer gating.

## Schemas

```text
holo.stage171.market_research_pack_action.v1
holo.stage171.market_research_pack_ledger.v1
```

## Runtime Flow

```text
model selects market_research_pack
host validates arguments and network boundary
host consumes existing web/filing evidence
host builds Stage169 market-research pack when filing text is available
host records market_research_pack_ledger
Stage170 reads the pack and gates final financial claims
Stage153/Stage135 expose the action as auditable metadata
```

Stage171 is read-only. It does not call a provider, write memory, start WeChat, widen transport authority, or make live network mandatory in tests.

## Ledger Behavior

Each execution records:

```text
action_id
action_type=market_research_pack
query
filing_type
status
pack_id
pack_status
failure_reasons
evidence_item_count
source_urls
observed_at
stage169_market_research_pack
```

`status=ok` means the Stage169 pack is ready. `status=insufficient` means a pack was built but source authority, checklist coverage, or metric consistency was insufficient. `status=rejected_network_disabled` records the host boundary when no local filing evidence is available and network is disabled.

## DeepSeek Tool Loop

Stage152 now exposes `market_research_pack` in the native tool registry. DeepSeek may propose this tool, but the host executes it and records the ledger. The raw model does not become the authority for market-research evidence.

## Topology

Stage135 now exposes `stage171_market_research_pack_action` with:

```text
market_research_pack_action_node_count
market_research_pack_action_status
market_research_pack_action_pack_status
market_research_pack_action_evidence_count
```

The action node feeds Stage170 when the market-research gate is present.

## Boundaries

- no provider model path outside processor fabric
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no approval/sandbox changes
