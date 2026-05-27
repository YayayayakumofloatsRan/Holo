# Engineering Handoff Stage197

## Summary

Stage197 adds the market-research report assembly boundary. Holo now checks whether a Stage173 market-research report actually cites the authoritative source promoted by Stage196 before marking the report as final-ready.

## Files Changed

- `holo_host/market_research_report_assembly.py`
- `holo_host/reply_api.py`
- `holo_host/agent_event_stream.py`
- `holo_host/public_thought_stream.py`
- `holo_host/stage135_i_state_topology.py`
- `tests/test_stage197_market_research_report_assembly.py`
- `docs/STAGE197_MARKET_RESEARCH_REPORT_ASSEMBLY.md`
- `docs/ENGINEERING_HANDOFF_STAGE197.md`
- `HOLO_HANDOFF.md`
- `docs/ROADMAP_REGISTRY.md`

## New Schema

- `holo.stage197.market_research_report_assembly.v1`

## Runtime Propagation

`stage197_market_research_report_assembly` is built after Stage195/196 and Stage173 report metadata are available. It is attached to sidecar/debug metadata, capability context, outgoing reply metadata, archive metadata, Stage153 event streams, Stage191 public thought streams, and Stage135 topology.

## Examples

Aligned report:

```text
status=assembled
final_report_ready=true
citation_quality_status=sufficient
canonical_stop_reason=final_answer_ready
```

Promoted source missing from citations:

```text
status=citation_mismatch
final_report_ready=false
citation_quality_status=missing_promoted_source
missing_requirements=promoted_source_missing_from_report_citations
```

Weak source:

```text
status=insufficient_evidence
final_report_ready=false
investment_recommendation=not_provided
canonical_stop_reason=evidence_exhausted
```

## Verification

Targeted:

```powershell
python -m pytest tests\test_stage197_market_research_report_assembly.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage197-green1
```

Result:

```text
5 passed
```

Neighbor market stack:

```powershell
python -m pytest tests\test_stage197_market_research_report_assembly.py tests\test_stage196_market_research_source_promotion.py tests\test_stage195_market_research_continuation_loop.py tests\test_stage174_market_research_report_action.py tests\test_stage173_market_research_report.py tests\test_stage176_market_research_domain_benchmark.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage197-neighbor
```

Result:

```text
43 passed
```

Runtime:

```powershell
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage197-runtime
```

Result:

```text
92 passed
```

Full regression:

```powershell
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
```

Result:

```text
973 passed
```

Public hygiene:

```powershell
python scripts\check_public_release_hygiene.py
git diff --check
```

Result:

```text
Public release hygiene passed.
git diff --check passed with CRLF normalization warnings only.
```

## Constraints Preserved

- No provider calls
- No network fetches
- No tool execution
- No memory writes
- No WeChat start
- No transport authority widening
- No raw hidden reasoning exposure

## Next Suggested Stage

Stage198 should make Stage197 final-ready state drive live report finalization: `assembled` reports can produce a bounded final answer, while `citation_mismatch` and `insufficient_evidence` should trigger user-visible evidence failure repair or another bounded evidence action.
