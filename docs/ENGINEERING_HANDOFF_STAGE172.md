# Engineering Handoff Stage172

## Summary

Stage172 adds host-side filing text retrieval for the market-research pipeline. Stage171 can now build a Stage169 pack from existing Stage163 page evidence or by opening an authoritative SEC/IR URL through the existing host web path, instead of requiring manual `filing_text` input.

## Files Changed

```text
holo_host/stage172_filing_text_retrieval.py
holo_host/stage171_market_research_action.py
holo_host/stage152_deepseek_tool_loop.py
holo_host/agent_event_stream.py
holo_host/kernel_metadata_sanitizer.py
holo_host/reply_api.py
holo_host/stage135_i_state_topology.py
tests/test_stage172_filing_text_retrieval.py
docs/STAGE172_FILING_TEXT_RETRIEVAL.md
docs/ENGINEERING_HANDOFF_STAGE172.md
docs/ROADMAP_REGISTRY.md
HOLO_HANDOFF.md
```

## New Schema

```text
holo.stage172.filing_text_retrieval.v1
```

## Runtime Propagation

Stage172 metadata is propagated through:

```text
stage152_deepseek_tool_loop
market_research_pack_ledger
ReplyPlan.debug
reply JSON
outgoing metadata
archive/observe metadata
Stage153 event stream
Stage135 topology
```

Metadata keys:

```text
filing_text_retrieval
stage172_filing_text_retrieval_status
stage172_filing_text_retrieval_source
```

## Examples

Page evidence:

```text
filing_text_retrieval status=ok retrieval_source=page_evidence
```

Open page:

```text
filing_text_retrieval status=ok retrieval_source=open_page
```

Network disabled:

```text
filing_text_retrieval status=rejected_network_disabled failure=network_disabled
```

## Verification

Initial TDD red:

```powershell
python -m pytest tests\test_stage172_filing_text_retrieval.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage172-red
```

Result: failed during collection because `holo_host.stage172_filing_text_retrieval` did not exist.

Targeted after implementation:

```powershell
python -m pytest tests\test_stage172_filing_text_retrieval.py tests\test_stage171_market_research_action.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage172-targeted2
```

Result: `15 passed in 0.61s`.

Market stack regression:

```powershell
python -m pytest tests\test_stage172_filing_text_retrieval.py tests\test_stage171_market_research_action.py tests\test_stage170_market_research_gate.py tests\test_stage169_market_research_pack.py tests\test_stage168_source_authority.py tests\test_stage161_model_tool_arbitration.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage172-market-stack
```

Result: `62 passed in 2.04s`.

Runtime regression:

```powershell
python -m pytest tests\test_stage152_deepseek_tool_loop.py tests\test_stage153_interactive_cli.py tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage172-runtime
```

Result: `110 passed in 23.98s`.

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result: `809 passed in 95.61s`.

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

Stage173 should add a market-research report generator that consumes Stage169-172 evidence and produces a structured analyst report with explicit unsupported-claim accounting, source citations, and benchmark fixtures against weak web-only baselines.
