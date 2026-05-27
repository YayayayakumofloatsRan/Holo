# Stage192 Market Research Feedback Loop

Stage192 extends Holo's public self-feedback controller from crawler evidence to market-research report readiness.

## Purpose

Holo can already collect filing evidence, build a market-research pack, generate a bounded analyst-style report, and ground financial claims. The missing control layer was a direct answer to:

- Is the report ready to deliver?
- If not, what evidence is missing?
- Should the next action be more filing/source search, report regeneration, or an explicit insufficient-evidence final?

Stage192 adds that answer as structured runtime metadata and CLI-visible feedback.

## Schema

- `holo.stage192.market_research_feedback_loop.v1`
- `holo.stage192.market_research_feedback_step.v1`

Each feedback step records:

- report status
- pack status
- source authority status
- section, metric, citation, and unsupported-claim counts
- combined sufficiency score
- unresolved items
- next action
- stop decision
- stop reason

## Agent Loop Role

Stage192 follows the same operating pattern used by Codex/Claude-style agents: propose or execute an action, record observations, evaluate whether evidence is sufficient, then either continue or stop. Public references that informed this direction include OpenAI's Codex developer surfaces and Anthropic's computer-use agent-loop documentation, where tool calls are executed by the host and results are fed back to the model or controller.

Stage192 is host-side and deterministic. It does not call a provider, write memory, execute tools, start WeChat, or widen transport authority.

## Runtime Integration

- `reply_api` builds `stage192_market_research_feedback_loop` whenever market-research pack/report evidence is present.
- Stage153 event stream renders it as `[feedback] market_research_report ...`.
- Stage191 public thought stream consumes that feedback as `self_feedback` cards.
- Stage135 topology includes a compact `market_research_feedback` node.

## Stop Behavior

- `report_ready`: report can be finalized.
- `source_authority_insufficient`: continue by rebuilding the market-research pack, usually requiring a primary filing or first-party disclosure.
- `report_insufficient`: continue by regenerating the report from existing improved evidence.
- `evidence_exhausted`: stop and report insufficient evidence when no action budget remains.

## Verification

- Targeted: `python -m pytest tests\test_stage192_market_research_feedback_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage192-green2`
- Neighbor: `python -m pytest tests\test_stage192_market_research_feedback_loop.py tests\test_stage173_market_research_report.py tests\test_stage174_market_research_report_action.py tests\test_stage191_public_thought_stream.py tests\test_stage190_self_feedback_loop.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage192-neighbor`
- Runtime: `python -m pytest tests\test_holo_host.py tests\test_stage135_i_state_topology.py -q --basetemp D:\Holo\holo\.pytest_tmp\stage192-runtime`
- Full: `python -m pytest -q --basetemp D:\Holo\holo\.pytest_tmp\base`
