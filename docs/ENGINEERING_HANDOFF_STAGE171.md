# Engineering Handoff Stage171

## Summary

Stage171 turns `market_research_pack` from a Stage170 action-space affordance into a host-executed, ledgered action. A model-selected market-research action can now produce a Stage169 filing evidence pack, feed Stage170 answer gating, and appear in CLI/topology metadata.

## Files Changed

```text
holo_host/stage171_market_research_action.py
holo_host/stage152_deepseek_tool_loop.py
holo_host/agent_loop_fsm.py
holo_host/agent_event_stream.py
holo_host/model_tool_arbitration.py
holo_host/kernel_metadata_sanitizer.py
holo_host/stage170_market_research_gate.py
holo_host/stage135_i_state_topology.py
holo_host/reply_api.py
tests/test_stage171_market_research_action.py
docs/STAGE171_MARKET_RESEARCH_PACK_ACTION.md
docs/ENGINEERING_HANDOFF_STAGE171.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schemas

```text
holo.stage171.market_research_pack_action.v1
holo.stage171.market_research_pack_ledger.v1
```

## Runtime Propagation

Stage171 metadata is propagated through:

```text
stage152_deepseek_tool_loop
ReplyPlan.debug
reply JSON
outgoing metadata
archive/observe metadata
Stage153 event stream
Stage135 topology
```

Metadata keys:

```text
market_research_pack_ledger
stage171_market_research_pack_action_status
stage171_market_research_pack_evidence_count
stage169_market_research_pack
```

## Examples

Ready:

```text
market_research_pack status=ok pack=ready evidence>=5 source=sec.gov
```

Insufficient:

```text
market_research_pack status=insufficient failure=source_authority_insufficient
```

Rejected:

```text
market_research_pack status=rejected_network_disabled failure=network_disabled
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage171_market_research_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage171-red
```

Result: failed during collection because `holo_host.stage171_market_research_action` did not exist.

Targeted after implementation:

```powershell
python -m pytest tests\test_stage171_market_research_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage171-targeted2
```

Result: `8 passed in 0.28s`.

Market stack regression:

```powershell
python -m pytest tests\test_stage171_market_research_action.py tests\test_stage170_market_research_gate.py tests\test_stage169_market_research_pack.py tests\test_stage168_source_authority.py tests\test_stage161_model_tool_arbitration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage171-market-stack
```

Result: `55 passed in 1.93s`.

Runtime regression:

```powershell
python -m pytest tests\test_stage152_deepseek_tool_loop.py tests\test_stage153_interactive_cli.py tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage171-runtime
```

Result: `110 passed in 21.63s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `802 passed in 93.82s`.

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result: public hygiene passed; `git diff --check` exited 0 with CRLF normalization warnings only.

## Constraints Preserved

- no provider model path outside processor fabric
- no memory writes
- no WeChat start
- no transport authority widening
- no hidden reasoning exposure
- no approval or sandbox changes

## Next Suggested Stage

Stage172 should make filing retrieval/opening more complete: when only a SEC URL or search result is present, the host should fetch and extract filing text through the existing web/page evidence stack before invoking the Stage171 pack builder.
