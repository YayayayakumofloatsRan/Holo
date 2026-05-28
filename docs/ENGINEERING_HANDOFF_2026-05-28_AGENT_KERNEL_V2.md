# Engineering Handoff: Holo Agent Kernel v2

Date: 2026-05-28

Repository: `D:\Holo\holo-agent-kernel`

WSL path: `/mnt/d/Holo/holo-agent-kernel`

Branch: `agent-kernel-v2`

Remote: `git@github.com:YayayayakumofloatsRan/Holo.git`

Kernel version: `2.1.0`

Current head before this handoff document: `53be63a fix: add Stage233 provider timeout continuity`

## Stop State

Feature development was stopped per operator request. This document records the
current implementation state, verification evidence, known failures, and the
recommended next technical cut. It does not add new runtime behavior.

The current kernel is a useful foundation, but it is not yet a mature
Codex/Claude-Code-grade agent. The most important unfinished work is still the
real agent loop:

```text
model proposes -> host executes -> observation ledger -> model evaluates
-> host guardrails -> continue or stop
```

The code has several pieces of this loop, but the loop is not yet strong enough
for broad autonomous web research, finance research, engineering work, or long
running project execution.

## Current Runtime Entry Points

PowerShell from Windows:

```powershell
cd D:\Holo\holo-agent-kernel
python -m holo_agent chat --trace
python -m holo_agent run "search official DeepSeek API key usage docs and cite sources" --trace
python -m holo_agent status
python -m pytest -q
```

WSL:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent chat --trace"
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run '上网查一下deepseek api key的用法' --trace --model fallback --max-steps 6"
```

Model selection:

```text
--model auto      Uses DeepSeek when DEEPSEEK_API_KEY is configured, otherwise fallback.
--model fallback  Forces offline deterministic fallback for tests.
```

Interactive commands currently documented in `README.md`:

```text
/status
/web
/memory
/logs
```

## Commit Timeline

Recent commits on `agent-kernel-v2`:

```text
53be63a fix: add Stage233 provider timeout continuity
bd36596 feat: add Stage232 model-evaluated self feedback
807b5f3 feat: add Stage231 context kernel contract
6db80bb feat: add Stage230 action self feedback loop
ebfa8e2 feat: add Stage229 page fetcher diagnostics
ae16e3f fix: recognize DeepSeek docs as official sources
7a6ce16 feat: add Stage228 source policy provider
bf14a35 feat: add Stage227 web provider registry
e4f56db feat: add Holo agent kernel web research v2
```

Stage documents are research and engineering logs. The product kernel is not
stage-named; the kernel version is `2.1.0`.

## Implemented Architecture Pieces

Main package files:

```text
holo_agent/agent.py
holo_agent/cli.py
holo_agent/context_kernel.py
holo_agent/event_log.py
holo_agent/final_answer_contract.py
holo_agent/hooks.py
holo_agent/memory.py
holo_agent/model.py
holo_agent/page_fetcher.py
holo_agent/prompt_policy.py
holo_agent/schema.py
holo_agent/self_feedback.py
holo_agent/source_authority.py
holo_agent/tools.py
holo_agent/web_providers.py
holo_agent/web_research_kernel.py
holo_agent/workflow_policy.py
holo_agent/workspace.py
```

### Agent Shell

`holo_agent/cli.py` provides `chat`, `run`, and status-like commands. The trace
is intended to show public, auditable events rather than hidden chain of
thought:

```text
[goal]
[context]
[action_space]
[workflow_policy]
[model_decide]
[tool_call]
[observation]
[model_evaluate]
[self_feedback]
[final_contract]
[evaluate]
[stop]
[final]
```

This is the correct direction, but the event stream should eventually be driven
from a single loop controller rather than partly from helper functions and
fallback paths.

### Web Research Kernel

`holo_agent/web_research_kernel.py` defines a cleaner web research contract:

```text
SearchGoal
SearchPlan
SearchAttempt
SearchResult
SourceCandidate
FetchResult
ExtractedPage
EvidenceItem
Citation
CrawlReport
```

This is better than a single `web_search()` function, but it is still an early
kernel. It needs a real multi-provider search layer, stronger extraction, and a
source graph before it can support serious market, literature, or technical
research.

### Provider Registry And Health

`holo_agent/web_providers.py` added bounded provider attempts and provider
health metadata. This made web failures diagnosable instead of turning every
failure into a vague "network is broken" statement.

Current limitation: the generic provider path still depends on fragile public
HTML search behavior. This is not enough for robust research.

### Source Policy Provider

`holo_agent/web_providers.py` and `holo_agent/source_authority.py` can route
some official-docs goals to known official candidates. This helped DeepSeek API
docs and some official source cases.

Important boundary: source policy must not become the tool decision brain. The
model should still decide that search is needed. Source policy should only help
provider/source selection after the action is selected.

### Page Fetcher And Extraction

`holo_agent/page_fetcher.py` separates page fetch and extraction diagnostics.
`open_page` observations expose fetch/extraction details.

Known live result:

```text
DeepSeek API docs: fetch/open worked.
OpenAI Codex CLI developers page: WSL fetch path hit HTTP 403.
```

The OpenAI 403 should be treated as a site-specific fetch/access issue, not as
proof that WSL network is globally down.

### Self-Feedback

`holo_agent/self_feedback.py` records self-feedback after tool observations.
Stage232 added a model-evaluation hook through `DeepSeekJsonModel`:

```text
evaluate_action_feedback(...)
```

Fallback mode still uses host-only evaluation. The target architecture is for
the model to judge sufficiency and next action, while the host validates bounds,
ledgers, and final claims.

### Context Kernel And Final Contract

`holo_agent/context_kernel.py` and `holo_agent/final_answer_contract.py` started
the move away from hard reply gates. Capability statements such as "what can
you do" no longer require a tool observation.

This fixed the most obvious failure:

```text
User: 你能做什么？
Bad old final: I do not have a tool observation for this request yet.
Fixed direction: capability statement is allowed without ledger.
```

The context kernel is not yet a mature cache/compaction engine.

### Chat Goal Continuity

Stage233 added `ChatSession` continuity for retry/follow-up turns. After a web
search failure, turns such as `再试一次`, `？？？`, and `我说去查一下` can inherit the
failed goal instead of becoming unrelated capability statements.

This is basic continuity only. It is not a general long-running task memory or
project-state system.

## Verification Evidence

Latest recorded Stage233 verification:

```powershell
python -m pytest tests\test_stage228_source_policy_provider.py::test_source_policy_provider_returns_deepseek_api_key_docs_candidate tests\test_stage233_chat_goal_continuity.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage233-green1
```

Result:

```text
4 passed
```

Neighbor:

```powershell
python -m pytest tests\test_stage228_source_policy_provider.py tests\test_stage233_chat_goal_continuity.py tests\test_stage227_web_provider_layer.py tests\test_stage232_model_self_feedback.py -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\stage233-neighbor
```

Result:

```text
24 passed
```

Full:

```powershell
python -m pytest -q --basetemp D:\Holo\holo-agent-kernel\.pytest_tmp\base
```

Result:

```text
93 passed
```

Live WSL smoke from Stage233:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent run '上网查一下deepseek api key的用法' --trace --model fallback --max-steps 6"
```

Observed trace shape:

```text
[model_decide] selected=web_search
[observation] web_search status=ok
[model_decide] selected=open_page
[observation] open_page status=ok
[stop] final_answer_ready
```

Final source:

```text
https://api-docs.deepseek.com/
```

## Known Failures And Gaps

These should not be hidden.

1. Generic search is not strong enough.

   DeepSeek docs can work because source policy gives an official candidate.
   Generic web search still depends on weak provider/fallback behavior. This is
   the main reason the CLI repeatedly looked like it had "no network".

2. The crawler is not yet a robust research operator.

   It needs:

   ```text
   provider abstraction with real APIs
   query planning
   candidate ranking
   fetch policy
   extraction quality scoring
   claim-level evidence
   source graph
   citation builder
   retry/stop controller
   ```

3. The model is not yet the authority for all semantic loop decisions.

   The target is model-first. The current code still has fallback behavior and
   source-policy shortcuts. Fallback is acceptable for tests, but it is not the
   desired intelligence path.

4. Self-feedback is present but not yet decisive enough.

   Feedback is recorded. The next cut should make feedback drive continue/stop
   and next action selection in the loop controller.

5. Context management is only partially rebuilt.

   The context kernel exists, but does not yet provide a production-grade:

   ```text
   stable prefix
   dynamic suffix
   compact executable state
   observation window
   selected operator brief
   cache-aware layout
   ```

6. Chat goal continuity is shallow.

   Retry/follow-up inheritance exists for recent failed goals. It is not yet a
   persistent project/task memory.

7. The new kernel is not a full replacement for the legacy Holo runtime yet.

   The old system has many stage-era modules and WeChat integrations. The new
   kernel is cleaner but much smaller. Replacement should be deliberate, not a
   blind remote overwrite.

8. CLI text and encoding still need careful live validation.

   A previous live run showed a stray leading punctuation before the banner and
   possible Chinese input display issues. This should be tested in WSL and
   Windows terminals before calling the interface stable.

9. No finance/market research domain module is ready.

   Financial research depends on robust web/crawler/source infrastructure.
   Building a market module before the crawler is fixed will reproduce the same
   failures at a higher layer.

## What Was Actually Improved

The current work did improve several concrete failure modes:

```text
Capability questions no longer require nonexistent tool observations.
DeepSeek API docs search no longer falls through to timeout-prone generic search.
Retry/follow-up after a failed search can inherit the previous failed goal.
Tool failures are reported as attempted failures rather than future intent.
Fetch/extraction diagnostics are now visible in observations.
Self-feedback events are visible in the trace.
```

These are foundation fixes, not final agent maturity.

## Recommended Next Cut

Do not keep patching random symptoms. The next useful cut should be a focused
crawler/operator rebuild.

### P0: Web Provider Layer

Add real provider backends behind a single contract:

```text
Brave Search API
Tavily
SerpAPI or Bing API
DuckDuckGo HTML fallback
site-specific providers for official docs, SEC, arXiv, PubMed, GitHub
```

Each provider result should record:

```text
provider
query
status
results
source_urls
latency_ms
error
rate_limit
```

### P1: Crawler FSM

Make the crawler a real bounded loop:

```text
plan_queries
search
rank_sources
fetch_pages
extract_pages
extract_evidence
evaluate_sufficiency
continue_or_stop
```

Every phase should have a ledger row and a CLI event.

### P2: Model-Evaluated Sufficiency

The model should evaluate:

```text
is the evidence sufficient?
what is missing?
is another query likely to help?
what exact next action should run?
can final answer cite this evidence?
```

The host should validate:

```text
network policy
source bounds
tool safety
ledger existence
final claim grounding
budget
```

### P3: Context Kernel Upgrade

Build a real context pack:

```text
stable kernel contract
instruction chain
action/operator metadata
selected operator brief
working state
recent observation window
compact executable state
exact current user message
```

Do not feed raw history as the primary state.

### P4: Persistent Action Journal

Persist:

```text
turn id
goal
selected action
observations
self-feedback
stop reason
citations
unresolved gaps
next action
```

This is required before serious long-running tasks.

### P5: Domain Modules Only After Search Is Solid

Do not start finance, math, physics, or ProjectH modules until the crawler and
agent loop can pass golden live transcripts.

## Golden Transcript Targets

Use these as live acceptance checks, not only unit tests:

```text
User: 你能做什么？
Expected: concise capability statement, no fake tool claim.

User: 上网查一下deepseek api key的用法
Expected: web_search -> open_page -> cited official DeepSeek docs, or explicit attempted failure.

User: 再试一次
Expected: inherits previous failed/unfinished search goal.

User: 搜索 OpenAI Codex CLI 官方文档
Expected: search/open attempts, official source preference, clear report if developers.openai.com blocks fetch.

User: 搜索一下 apple
Expected: web search or clarification; no playful fruit/persona output.

User: 做一个 Apple 最近 10-K 的基本面初步研究
Expected: SEC/company IR source requirement, not generic blog summaries.
```

## Remote And Replacement Guidance

This repository is technically a continuation of the Holo stage lineage, but it
is also a new kernel. If it is later used to replace the old remote/default
branch, do it explicitly:

```text
1. Preserve old branch/tag before replacement.
2. Push this kernel branch.
3. Document the branch mapping.
4. Do not mix legacy Holo chat/persona runtime into the kernel prompt.
5. Keep WeChat as an adapter, not the core agent loop.
```

Suggested branch strategy:

```text
legacy/public-sanitized      old Holo runtime snapshot
agent-kernel-v2              current new kernel work
public-sanitized             only move after explicit operator approval
```

## Do Not Overclaim

Do not claim:

```text
Holo can already do mature autonomous web research.
Holo can already match Codex.
Holo has solved finance research.
Holo has reliable generic network search.
Holo has a complete long-running project memory.
```

It is accurate to claim:

```text
The new kernel has a cleaner model/host/tool/ledger architecture.
The first web research contracts and ledgers exist.
DeepSeek API-doc lookup was fixed for the tested official-source case.
The test suite passed at 93 tests after Stage233.
The next blocker is crawler/provider/operator maturity.
```

## Handoff Conclusion

The useful work is the architectural reset, not the current agent quality. The
next maintainer should avoid adding more superficial stages and instead harden
the kernel around:

```text
model-first decision
host-owned tools
structured observations
model-evaluated sufficiency
canonical stop reasons
auditable public trace
```

No more feature development was performed after this handoff document.
