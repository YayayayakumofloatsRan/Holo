# Engineering Handoff Stage196

## Summary

Stage196 adds market-research source promotion. It turns authoritative financial-filing web/page observations into a reusable source state for pack and report generation. This directly extends the Stage195 continuation loop by making source quality visible and actionable.

## Files Changed

- Added `holo_host/market_research_source_promotion.py`
- Added `tests/test_stage196_market_research_source_promotion.py`
- Added `docs/STAGE196_MARKET_RESEARCH_SOURCE_PROMOTION.md`
- Added `docs/ENGINEERING_HANDOFF_STAGE196.md`
- Updated `holo_host/market_research_continuation_loop.py`
- Updated `holo_host/agent_event_stream.py`
- Updated `holo_host/public_thought_stream.py`
- Updated `holo_host/reply_api.py`
- Updated `holo_host/stage135_i_state_topology.py`
- Updated `HOLO_HANDOFF.md`
- Updated `docs/ROADMAP_REGISTRY.md`

## New Schema

- `holo.stage196.market_research_source_promotion.v1`

## Runtime Propagation

Stage196 runs inside Stage195 after execution rounds and records the latest source-promotion report under:

```text
stage196_market_research_source_promotion
```

It is propagated into:

- `ReplyPlan.debug`
- reply JSON / outgoing metadata
- archive metadata
- Stage153 event stream as `[source_promote]`
- Stage191 public thought stream
- Stage135 topology metrics under `market_research_source_promotion_*`

## Examples

- SEC page evidence:
  - status: `promoted`
  - authority: `sufficient`
  - source family: `financial_filing`
  - `can_build_market_research_pack=true`

- Third-party filing summary:
  - status: `weak`
  - authority: `insufficient`
  - `can_build_market_research_pack=false`

- No rows and network enabled:
  - Stage196 delegates to Stage186 live crawler with a bounded query budget.
  - It promotes the result if source authority is sufficient.

- Network disabled:
  - status: `blocked`
  - canonical stop: `boundary_or_permission`
  - no fetch is attempted.

## Constraints Preserved

- No provider model calls were added.
- No memory writes were added.
- No WeChat start was added.
- No transport authority was widened.
- Raw hidden reasoning and provider `reasoning_content` remain excluded from public surfaces.

## Test Commands And Results

```powershell
python -m pytest tests\test_stage196_market_research_source_promotion.py tests\test_stage195_market_research_continuation_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage196-targeted
# 12 passed

python -m pytest tests\test_stage196_market_research_source_promotion.py tests\test_stage195_market_research_continuation_loop.py tests\test_stage194_market_research_plan_execution.py tests\test_stage186_live_crawler_search.py tests\test_stage189_crawler_source_authority_stop.py tests\test_stage168_source_authority.py tests\test_stage163_page_evidence_verifier.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage196-neighbor
# 47 passed

python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage196-runtime
# 92 passed

python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
# 968 passed
```

Public hygiene and `git diff --check` were also run before the Stage196 commit.

## Next Suggested Stage

Stage197 should improve market-research report execution with source-promotion-aware report assembly, including source ordering, citation quality, and explicit "insufficient current filing evidence" reports when promotion fails.
