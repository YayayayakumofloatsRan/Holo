# Stage218 Web Research Operator

Stage218 adds a second live registered operator: `web_research_operator_run`.

## Problem

Stage217 made operator dispatch reusable, but only `market_research_operator_run` was registered. Holo still lacked a domain-neutral web/literature research operator that could search, open pages, evaluate source evidence, expose the action trajectory, and feed a grounded final answer back into the agent loop.

## Implementation

- Added `holo_host/web_research_operator.py`.
- Added schema `holo.stage218.web_research_operator_run.v1`.
- Registered `web_research_operator_run` in `holo_host/operator_registry.py`.
- The operator reuses Stage186 live crawler search for query planning, web search, page opening, page evidence scoring, source authority checks, and stop reason selection.
- The operator reuses Stage212 action journal rendering so CLI users can inspect the crawl path.
- Stage152-to-Stage161 arbitration now maps `web_research_operator_run` to required observation `stage218_web_research_operator_run`.
- Stage160R FSM now treats `stage218_web_research_operator_run` as a first-class mandatory observation.
- Reply runtime dispatches any registered operator through `dispatch_operator_action(...)`, instead of special-casing the market operator.
- Stage153 event stream renders `[web_research_operator]` trajectory rows.
- Stage135 topology exposes a `web_research_operator` node and metrics.

## Runtime Contract

```text
model selects web_research_operator_run
host dispatches through operator registry
Stage186 crawler searches and opens pages
Stage212 records action journal
FSM observes stage218_web_research_operator_run
final answer is either source-grounded or reports the attempted failure
```

The operator does not expose raw hidden reasoning. It exposes auditable public process: query plan, crawl ledger, page observations, source URLs, stop reason, and final visible text.

## CLI Trace

Expected trace shape:

```text
[model_decide] selected=web_research_operator_run need=stage218_web_research_operator_run
[operator_dispatch] id=web_research_operator_run status=executed requires=stage218_web_research_operator_run stop=final_answer_ready
[web_research_operator] phase=plan status=planned sources=0 stop=
[web_research_operator] phase=crawl status=sufficient sources=1 stop=final_answer_ready
[web_research_operator] phase=evaluate status=sufficient sources=1 stop=final_answer_ready
[web_research_operator] phase=finalize status=ready sources=1 stop=final_answer_ready
```

## Boundaries

- No WeChat start or transport widening.
- No durable memory write.
- No hidden chain-of-thought or raw provider reasoning exposure.
- Network-disabled runs produce rejected web observations and a failure final.
- The operator is read-only and host-executed.

## Verification

Verification commands:

```powershell
python -m pytest tests\test_stage218_web_research_operator.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-green3
python -m pytest tests\test_stage218_web_research_operator.py tests\test_stage217_operator_registry_dispatch.py tests\test_stage216_model_first_market_operator_action.py tests\test_stage186_live_crawler_search.py tests\test_stage212_action_journal.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-targeted
python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage218-runtime
python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base
python scripts\check_public_release_hygiene.py
git diff --check
```

Results: `8 passed`, `29 passed`, `92 passed`, `1063 passed`, public hygiene passed, and `git diff --check` exited 0 with CRLF normalization warnings only.
