# Kernel v3 Memory/RAG Research Notes

Date: 2026-06-07

This note records the external memory/RAG research pass and converts it into
kernel-v3 implementation guidance. It is not a replacement for the host-owned
loop. Models still propose; the host validates, executes, journals, verifies,
and controls memory promotion.

## Sources Reviewed

- MemGPT frames long-running LLM agents as an OS-style virtual context system:
  a limited main context plus external memory tiers, with function calls used
  to page information in and out during a task. This maps well to Holo's
  thread working set, durable memory store, and host-owned tool loop.
  Source: https://arxiv.org/abs/2310.08560
- Generative Agents uses observation, memory, planning, and reflection as
  separate architectural components. The important lesson is that memory is not
  only recall; it also feeds planning and reflection.
  Source: https://arxiv.org/abs/2304.03442
- A-MEM argues for agentic memory organized like a dynamic note network:
  structured notes, keywords/tags, links between related memories, and memory
  evolution when new facts arrive. This is stronger than fixed chunk RAG.
  Source: https://arxiv.org/abs/2502.12110
- Mem0 reports that persistent structured memory can outperform full-context
  and ordinary RAG baselines on long conversational recall while reducing
  latency and token cost. Its graph variant reinforces the need for relations,
  not only flat embeddings.
  Source: https://arxiv.org/abs/2504.19413
- Self-RAG and CRAG both point to corrective retrieval: the system should judge
  whether retrieval is needed, whether retrieved material is useful, and what
  corrective action to take when retrieval quality is poor.
  Sources: https://arxiv.org/abs/2310.11511 and
  https://arxiv.org/abs/2401.15884
- GraphRAG shows why a graph view matters for complex private or narrative data:
  extraction, graph construction, network analysis, and summarization can
  support global and local search rather than one-shot top-k chunks.
  Source: https://www.microsoft.com/en-us/research/project/graphrag/

## Practical Conclusion

Naive RAG is the wrong target for Holo. The kernel needs an agent memory system:

1. Event memory: the journal remains the authoritative sequence of turns,
   actions, tools, observations, citations, final answers, failures, and
   host_situation records.
2. Working memory: each thread/task needs a compact active set of current goal,
   open gaps, successful findings, failed attempts, user preferences, and next
   intent. This is page-in memory for the next planner/evaluator packet.
3. Durable memory: committed user/project/thread facts live in `MemoryStore`
   with scope, privacy class, TTL, provenance, approvals, tombstones, and audit.
4. Research graph memory: deep retrieval should preserve query -> provider ->
   discovery source -> fetched document -> evidence -> citation -> claim.
   Planners need the graph summary, not scattered journal records.
5. Tool memory: failed payloads, provider reliability, source-family success,
   and extraction failures should become strategy memory. It should tell the
   planner what to avoid and what to try next, without hard-coding domains.
6. Reflection memory: final answers and failed missions should produce pending
   memory proposals only when they are useful, scoped, non-secret, and backed by
   provenance. The model can propose; only host policy can commit.

## Existing Kernel v3 Fit

Kernel v3 already has the right core substrate:

- `JournalStore` for event memory and traceability.
- `ContextPackCompiler` for bounded snapshot assembly.
- `ThreadWorkingMemoryProvider` and `workmethod.memory` for thread-scoped
  working-set compilation.
- `MemoryStore`, `MemoryPipeline`, `MemoryRecallOperator`, privacy checks, and
  memory admin commands for durable memory.
- `RetrievalReport`, `ResearchGraph`, `DiscoveryExpansion`, source-quality
  diagnostics, and next-tool-action surfaces for research graph memory.
- `MissionSupervisor` and `WorkMethodSupervisor` for cross-loop coverage and
  strategy shifts.
- `host_situation` and `runtime_capabilities` packets so live models know the
  actual host state instead of hallucinating missing tools.

The main gap is integration quality. Memory exists, but it is still too passive.
The planner sees some thread context and can call `memory.recall`, but memory is
not yet a first-class loop operation for page-in, strategy repair, reflection,
and post-task consolidation.

## Target Architecture

### Memory Layers

| Layer | Store | Writer | Reader | Enters model as |
| --- | --- | --- | --- | --- |
| Event log | `JournalStore` | host runtime | trace/thread RAG | compact trace refs and deltas |
| Thread working set | journal-derived projection | host compiler | planner/evaluator | current goal, gaps, findings |
| Attention block | context compiler | host compiler | next processor call | recent high-value refs |
| Durable memory | `MemoryStore` | host-approved pipeline | `memory.recall` and context injection | scoped summaries/provenance |
| Research graph | retrieval report/artifacts | retrieval operator | planner/evaluator/synthesizer | graph summary and next actions |
| Tool memory | journal-derived stats/proposals | host supervisor | planner and retrieval strategy | avoid/retry/source-family hints |
| Reflection proposals | memory pipeline | host-approved pipeline | memory admin | pending proposals |

### Loop Integration

Every non-trivial task should allow this sequence:

```text
user turn
-> chat.route
-> semantic.intake
-> workmethod.frame
-> context compiler page-in:
   thread working set + durable memory + research graph + tool memory
-> planner proposes action
-> host validates and executes
-> observation enters journal
-> evaluator assesses
-> workloop termination policy
-> mission/workmethod gap assessment
-> if incomplete: directive + updated working set + next loop
-> if complete: final answer + optional memory proposal
```

The LLM remains the semantic decision core, but it must receive a compact,
honest host packet. The host never relies on fixed answer strings or hidden
precomputation.

## Implementation Roadmap

### Step 1: Prompt-Packet Hygiene

- Keep raw fetched bodies and large graphs out of processor prompts.
- Pass compact `host_situation`, `runtime_capabilities`, thread working set,
  retrieval graph summaries, and memory refs.
- Treat post-final mission/work-gap assessment as non-blocking when host rules
  already accept the final answer.

### Step 2: Active Memory Planner Surface

- Add explicit planner-visible memory actions:
  - `memory.recall` for committed facts;
  - `memory.inspect_scope` for "what do you remember";
  - host-only `memory.propose_from_result` after final answers;
  - host-only `memory.approve/reject/delete`.
- Ensure the planner can choose memory recall without requiring a user prompt
  when a follow-up turn depends on earlier context.

### Step 3: Thread Working Memory Page-In

- Generate a `ThreadWorkingSet` after every turn.
- Include:
  - latest user goal;
  - active task and pending question;
  - successful findings;
  - failed attempts and avoid-repeat signatures;
  - current user preferences;
  - open gaps and next intent;
  - relevant durable memory ids.
- Inject this before planner/evaluator, not only into chat summaries.

### Step 4: Research Graph as Retrieval Memory

- Make retrieval expose a compact graph packet:
  - nodes: query, source_family, discovery_page, document, evidence, claim;
  - edges: generated, fetched, extracted, supports, rejected_by;
  - diagnostics: failure layer, missing facets, next tool actions.
- The planner should see the graph summary and choose a materially different
  acquisition strategy when coverage is poor.

### Step 5: Tool Memory and Failure Learning

- Track provider/source-family outcomes:
  - query success/failure;
  - fetch empty/blocked;
  - extraction no spans;
  - weak source rejection;
  - citation mismatch;
  - domain/source family that solved the gap.
- Feed this back as tool memory, not as fixed templates.
- Promote only stable, useful lessons to durable memory after host review.

### Step 6: Reflection and Consolidation

- After final answer or failure:
  - summarize what was learned;
  - capture reusable source families or workflow lessons;
  - create pending memory proposals with provenance;
  - reject secret-like or low-confidence proposals;
  - never silently commit private data.

## Finance-Specific Application

Finance research should be one profile on top of the general system, not a
separate hard-coded loop. The finance profile can add:

- source families: SEC EDGAR, company investor relations, FRED, FiscalData,
  exchange filings, reputable market-data pages, policy/regulator sites;
- evidence facets: business model, revenue, profitability, balance sheet, cash
  flow, valuation, risks, management discussion, macro/policy context;
- structured extraction targets: companyfacts metrics, filing metadata,
  period/fiscal year, units, accession number, source URL;
- stricter citation and provenance requirements.

The general research graph and tool-memory machinery must still work for
mathematics, physics, law/policy, engineering, and other domains.

## Quality Gates

- No fixed-answer simulation assertions for live ability.
- Unit tests may use fake providers only to test contracts and host boundaries.
- Live benchmarks should report behavior metrics:
  - loop count;
  - duplicate query rate;
  - useful document count;
  - source-family diversity;
  - evidence/citation count;
  - final-answer length versus requested profile;
  - missing-facet disclosure quality;
  - whether final answer returned before post-final diagnostics.
- Private memory and live third-party model calls require explicit host policy
  and redaction boundaries.

## Immediate Engineering Decisions

This research pass supports three concrete kernel-v3 decisions:

1. Memory must enter the loop as an action surface and a compact page-in packet,
   not only as passive context.
2. Retrieval must preserve research graph summaries and next tool actions so
   later loops can change strategy instead of repeating queries.
3. Model calls must receive enough host/runtime truth to reason well, but large
   audit payloads must stay in journal/artifacts and be referenced by ids,
   hashes, previews, and diagnostics.

## 2026-06-07 Implementation Update: Task Reflection Memory

This pass adds the first host-owned learning hook after task completion/failure:

- `MemoryPipeline.propose_from_task_reflection()` accepts a compact task
  reflection packet: root goal, outcome, failure reason, attempted actions,
  attempted sources, missing evidence, next possible action, and host
  diagnostics.
- The resulting memory is a `workflow_convention` draft with provenance and a
  pending `MemoryProposal`. It is explicitly `review_nonblocking`, so it can be
  audited through memory admin without turning the chat thread into a pending
  question.
- `AgentRuntime._failure()` can call this hook for meaningful non-user-blocking
  failures. Clarification, user-input, cancellation-like, and empty direct-answer
  failures are not promoted.
- `ThreadWorkingMemoryProvider` now includes compact `memory_learning` records
  and an attention block for the latest learning signal. The planner/evaluator
  packet can therefore see reusable lessons from recent runs without reading raw
  logs or committed long-term memory bodies.
- Projection still journals manifests only: ids, hashes, previews, status,
  policy, and the `review_nonblocking` flag. Full memory bodies remain in
  `MemoryStore`, and committed durable memory still requires host/user approval.

This is not a fixed-response simulation shortcut. The host records task facts
and failure diagnostics; future LLM packets use those facts as context and still
decide their next action through the normal planner/evaluator loop.

## 2026-06-07 Implementation Update: Compact Research Notes

Research-result memory proposals now use a compact durable-memory shape instead
of storing the whole final report as candidate text:

- `MemoryPipeline.propose_from_research_result()` first checks the full final
  answer for secret-like content, then distills it into a bounded
  `research_note` draft.
- The note preserves root goal, summary, key findings, limitations,
  citation/evidence refs, answer profile, answer length, and provenance refs.
- The long final answer remains in the normal journal/final-answer trace. It is
  not copied wholesale into durable-memory body text.
- The proposal is reviewable and `review_nonblocking`; it can inform later
  planner context through thread RAG without interrupting the next user turn.

This makes durable memory a working substrate for future research continuity,
not a pile of long cached reports.
