# Kernel v3 Frontier Multi-Agent Research Compute Memo

Date: 2026-06-16

Status: research direction memo. This is not a benchmark score report and not an
implementation claim.

## Core Thesis

Kernel v3's current finance work is valuable agent engineering, but it is not yet
the frontier of multi-agent intelligence research.

FinanceBench, FAB, HD/LOW DIO, 3M capital intensity, and similar tasks test
whether an agent can retrieve public filings, bind line items, compute formulas,
preserve citations, and pass host-owned verification. These are high-pressure
reliability tasks. They are important because they force Holo to build durable
evidence ledgers, tool traces, numeric verification, and synthesis gates.

However, they are still mostly document-world tasks:

- the answer usually exists in public filings or can be computed from them;
- failure is often source acquisition, line-item binding, period mismatch, or
  unsupported synthesis;
- a single strong agent with enough context can often solve one item after
  enough retrieval and repair;
- consuming hundreds of thousands of tokens per item is expensive, but it is
  still closer to a "home computer" workload than a true research-compute
  workload.

The next research frontier is different. It is not just longer context or more
retrieval. It is verifier-guided search over huge spaces where the answer is not
already sitting in a filing.

The supercomputer-level problem class is:

> Use many LLM agents as proposal engines inside a host-owned search,
> verification, memory, and selection loop to discover new proofs, algorithms,
> programs, strategies, or scientific hypotheses.

In this regime, more agents can increase intelligence only if the host can
evaluate, preserve, recombine, and route their work. Without a verifier and
durable failure memory, one thousand agents mostly create one thousand plausible
but ungrounded branches.

## What Makes A Problem "Supercomputer-Level"

A problem is materially harder than current finance benchmark work when it has
most of these properties:

1. Huge search space.
   The task is not to find a known answer, but to search an exponential or
   combinatorial space of proofs, programs, constructions, policies, or
   experiments.

2. Sparse success signal.
   Most local attempts fail. The system must exploit partial progress and
   negative results instead of treating each failure as an isolated bad answer.

3. Strong verifier.
   A proof checker, test suite, evaluator, simulator, or scoring environment can
   reject bad candidates and preserve valid progress. This is the difference
   between research compute and unbounded brainstorming.

4. New knowledge potential.
   The result is not just an answer. It may be a proof, a faster program, a new
   construction, a better heuristic, or a validated experimental result.

5. Parallel branching with memory.
   Many agents can explore different branches, but only if the host maintains
   shared state: branch lineage, failed lemmas, evaluator scores, novelty,
   reusable sub-results, and search priorities.

6. Long horizon.
   The task may require hours or days of search, not one prompt turn. Progress
   must survive context compaction, process restarts, and model failures.

## Frontier Task Families To Watch

### 1. Research-Level Mathematics

FrontierMath is a clear example of the target difficulty class. It contains
original, exceptionally challenging mathematical problems crafted and vetted by
expert mathematicians, spanning modern mathematical areas such as number theory,
real analysis, algebraic geometry, and category theory. The paper reports that
typical problems can take relevant researchers hours, upper-end problems can take
days, and state-of-the-art models solved under 2 percent at release.

Why it matters for Holo:

- a one-shot answer is usually useless;
- multiple agents can search different proof paths;
- symbolic systems, calculators, and theorem provers can verify subclaims;
- durable memory can store failed approaches and discovered lemmas;
- the main object is not a response but a verified proof or construction.

Reference:

- FrontierMath: A Benchmark for Evaluating Advanced Mathematical Reasoning in
  AI, https://arxiv.org/abs/2411.04872

### 2. Lean4 Formal Proof Search

Lean4 is a natural verifier for multi-agent search. A model can propose a proof
step, lemma, tactic, or formalization. The host can run Lean and get a hard pass
or failure. This makes it much more suitable for scaling test-time compute than
open-ended prose.

DeepMind's AlphaProof and AlphaGeometry work shows the shape of this path:
formal proof systems plus search can reach high-level olympiad mathematics. The
important lesson is not only the score. The important lesson is the architecture:
proposal, search, formal verification, and repeated refinement.

Why it matters for Holo:

- ClaimLedger becomes theorem/lemma ledger;
- SlotFrame becomes proof state / missing lemma state;
- TransformPlan becomes proof strategy;
- FormulaTrace becomes proof trace;
- VerifierGate becomes the Lean kernel;
- Retrieval Workbench becomes lemma/source/library search;
- multi-agent branching can be measured by verified proof progress.

Reference:

- AI solves IMO problems at silver-medal level, Google DeepMind,
  https://deepmind.google/discover/blog/ai-solves-imo-problems-at-silver-medal-level/

### 3. ARC-AGI And Abstract Skill Acquisition

ARC-AGI-style tasks are important because they reduce reliance on language,
memorized facts, and external knowledge. The agent must infer hidden rules from
few examples or from interaction. ARC-AGI-3 is especially relevant because it is
interactive: agents must explore, infer goals, build an internal environment
model, and plan action sequences.

This is a different kind of difficulty from FinanceBench. There is no SEC filing
to retrieve. The system must learn the task structure efficiently.

Why it matters for Holo:

- tests adaptive intelligence rather than document retrieval;
- useful for studying whether multi-agent hypothesis search improves rule
  induction;
- Host can maintain competing hypotheses, counterexamples, and programmatic
  transformations;
- success should be measured by sample efficiency, not just final answer.

References:

- ARC-AGI benchmark overview, https://arcprize.org/arc-agi
- ARC-AGI-3: A New Challenge for Frontier Agentic Intelligence,
  https://arxiv.org/abs/2603.24621

### 4. Algorithm Discovery And Program Evolution

FunSearch and AlphaEvolve-like systems are closest to the "LLM as search
proposal engine" model. The LLM writes candidate programs. The host executes an
evaluator. High-scoring candidates are retained, mutated, recombined, and tested
again.

This is the most direct path from agent harness to research compute:

- candidate generation is cheap and parallel;
- scoring is automatic;
- valid improvements can be stored;
- the final artifact is an inspectable program or heuristic;
- many agents can contribute by exploring different islands of the search space.

Why it matters for Holo:

- Holo already has tool execution, journaling, and verification boundaries;
- AlgorithmLedger can store candidate programs, scores, lineage, and evaluator
  diagnostics;
- memory becomes an evolutionary archive rather than a chat history;
- the host can spend compute on candidates with measurable promise.

References:

- FunSearch: making new discoveries in mathematical sciences using Large
  Language Models, Google DeepMind,
  https://deepmind.google/discover/blog/funsearch-making-new-discoveries-in-mathematical-sciences-using-large-language-models/
- Mathematical discoveries from program search with large language models,
  Nature, https://www.nature.com/articles/s41586-023-06924-6
- AlphaEvolve: A coding agent for scientific and algorithmic discovery,
  https://arxiv.org/abs/2506.13131

### 5. AI Research Engineering

RE-Bench is relevant because it evaluates frontier agents on open-ended ML
research engineering environments and compares them with human experts. The
important point is that agents can generate and test solutions quickly, but
longer horizons still expose planning, experiment design, and cumulative
learning gaps.

Why it matters for Holo:

- long-horizon task state matters more than one answer;
- the system must design experiments, run code, interpret results, and revise;
- failure memory and result analysis become central;
- multi-agent parallelism can split experiment design, implementation, analysis,
  and critique.

Reference:

- RE-Bench: Evaluating frontier AI R&D capabilities of language model agents
  against human experts, https://arxiv.org/abs/2411.15114

### 6. Computational Discovery Benchmarks

HorizonMath-like benchmarks target problems where solutions may be unknown but
verification is computationally cheap. This is a particularly important class:
it avoids data contamination and allows automatic scoring while still aiming at
novel discovery.

Why it matters for Holo:

- the benchmark rewards actual discovery rather than benchmark memorization;
- successful outputs may become publishable mathematical or algorithmic
  contributions;
- host-side verification and archive management are mandatory;
- multi-agent search can be evaluated by best-known score improvement over time.

Reference:

- HorizonMath: Measuring AI Progress Toward Mathematical Discovery with
  Automatic Verification, https://arxiv.org/abs/2603.15617

## Multi-Agent Scaling Hypotheses

The research question is not "can we run many agents?" That is easy. The real
question is:

> Under what host architecture does adding agents increase effective
> intelligence rather than only increasing cost and noise?

Working hypotheses:

1. Independent sampling has diminishing returns.
   Running the same prompt many times can help when a verifier exists, but it
   wastes compute once branches become correlated.

2. Diversity beats role theater.
   It is less important to name agents "critic", "planner", or "researcher" than
   to ensure they explore genuinely different proof strategies, program
   mutations, datasets, abstractions, or counterexamples.

3. Verifier quality sets the ceiling.
   If the verifier is weak, more agents amplify false positives. If the verifier
   is strong, more agents can become useful search workers.

4. Shared failure memory is a force multiplier.
   A failed proof branch, failing program, or invalid hypothesis should not be
   thrown away. It should become searchable negative evidence.

5. Credit assignment is central.
   The system must know which agent output improved the search frontier. Without
   credit assignment, selection becomes random or popularity-based.

6. LLM-owned semantic judgment still matters.
   The host can verify and route, but task decomposition, analogy, hypothesis
   formation, and explanation should stay model-owned. Kernel v3 should not
   collapse into a table-driven or threshold-driven workflow.

## Proposed Holo Research-Compute Architecture

The next architecture target can be called:

> Holo Research Compute Engine

It should extend Kernel v3 from single-agent finance research into
verifier-guided multi-agent search.

Core components:

1. ProblemSpec
   A formal problem contract: objective, domain, allowed tools, verifier, scoring
   function, budget, and termination criteria.

2. SearchLedger
   Durable branch ledger containing hypotheses, candidate programs, proof states,
   failed attempts, score traces, and lineage.

3. CandidateStore
   Artifact store for generated Lean files, Python programs, kernels, experiment
   configs, datasets, plots, and evaluator outputs.

4. VerifierGate
   Domain-specific hard evaluators: Lean, unit tests, property tests, simulators,
   benchmark scorers, theorem checkers, type checkers, or formal constraints.

5. BranchScheduler
   Host-owned scheduler that allocates budget to promising or novel branches,
   avoids repeated failures, and balances exploitation with exploration.

6. Multi-Agent Fabric
   A pool of LLM workers with different prompts, models, temperatures, or
   context slices. The fabric should support independent branching, critique,
   recombination, and specialist sub-search.

7. SynthesisAndCompression
   Periodic model-owned summaries that convert many failed and successful
   branches into reusable strategy memory without polluting hard verifier state.

8. ResearchMemory
   Long-term memory for discovered lemmas, useful code patterns, failed
   strategies, evaluator quirks, and domain heuristics. Memory must be structured
   and reversible, not a vague chat transcript.

## Candidate Packs

### Pack A: Lean4 Proof Pack

Goal:

- solve formal proof tasks with Lean4;
- start with small public benchmarks or local theorem sets;
- scale to miniF2F / ProofNet-style tasks, then harder math.

Minimum loop:

1. compile theorem statement;
2. propose proof branch;
3. run Lean;
4. record error;
5. ask agents for repair, lemma discovery, or alternative proof;
6. preserve verified proof.

Key metric:

- verified theorem pass rate and time-to-first-valid proof.

### Pack B: Algorithm Discovery Pack

Goal:

- replicate a small FunSearch-style loop locally;
- generate candidate Python functions for optimization problems;
- score them with deterministic evaluators;
- evolve a candidate archive.

Initial tasks:

- online bin packing heuristics;
- small scheduling heuristics;
- graph independent set heuristics;
- portfolio optimizer variants under synthetic constraints;
- CPU/GPU kernel micro-optimizations if test infrastructure exists.

Key metric:

- best score versus compute, novelty, and reproducibility.

### Pack C: ARC-Style Abstraction Pack

Goal:

- study few-shot rule induction and interactive environment exploration;
- compare single-agent, independent multi-sample, and coordinated multi-agent
  hypothesis search.

Minimum loop:

1. parse examples;
2. generate candidate transformation programs;
3. test candidates;
4. record counterexamples;
5. branch into new hypotheses;
6. output the simplest verified transformation.

Key metric:

- sample efficiency and verified task solve rate.

### Pack D: Research Engineering Pack

Goal:

- run RE-Bench-inspired local research-engineering tasks;
- require code changes, experiments, metrics, and result interpretation;
- measure whether multi-agent experiment design improves over one strong agent.

Minimum loop:

1. create experiment plan;
2. implement candidate;
3. run evaluator;
4. analyze logs;
5. schedule next branch;
6. archive reproducible results.

Key metric:

- score improvement over time and useful experiment throughput.

## Why Finance Still Matters

Finance should not be discarded. It is the right reliability training ground
because it forces:

- citation discipline;
- line-item grounding;
- numeric verification;
- period and unit control;
- source authority checks;
- user-facing explanation.

But finance benchmark QA should be understood as the foundation, not the summit.
It teaches Holo how to avoid unsupported claims. The frontier research-compute
track teaches Holo how to discover, search, and verify new structure.

The bridge is direct:

- ClaimLedger -> SearchLedger;
- SlotFrame -> proof/program/environment state;
- TransformPlan -> proof or algorithm strategy;
- FormulaTrace -> verifier/evaluator trace;
- Retrieval Workbench -> branch workbench;
- SynthesisGate -> research conclusion gate;
- durable memory -> reusable discovery archive.

## Measurement Discipline

Every multi-agent research-compute run should report:

- total agents / branches;
- total model tokens and wall-clock time;
- verifier calls;
- valid candidate count;
- best score over time;
- time-to-first-valid solution;
- branch novelty rate;
- repeated-failure rate;
- memory reuse rate;
- cost per verified improvement;
- human or single-agent baseline comparison.

Do not report raw agent count as progress. Report verified progress per compute.

## Near-Term Holo Roadmap

1. Preserve the finance track as the reliability baseline.
   Continue FinanceBench/FAB live work, but do not confuse those results with
   frontier research-compute claims.

2. Add a small verifier-native pack.
   The safest first step is Lean4 or deterministic algorithm-evaluator tasks,
   because the host can hard-check outputs.

3. Build SearchLedger and CandidateStore.
   Do not start with a "multi-agent chatroom". Start with durable branch state
   and hard evaluator records.

4. Add branch scheduling.
   The first scheduler can be simple: prioritize verified partial progress,
   novelty, and high-score candidates; deprioritize repeated failure signatures.

5. Compare against single-agent baselines.
   The research question is whether coordination improves scaling, not whether
   many agents can spend more tokens.

6. Only then scale agent count.
   A thousand agents before verifier, ledger, and scheduler discipline would
   produce cost, not intelligence.

## Presentation Summary

The finance agent work proves that Kernel v3 can run an evidence-grounded,
tool-using, verifier-gated agent loop. But the next research frontier is not
larger FinanceBench runs. It is verifier-guided multi-agent research compute.

The target is a system where many LLM agents propose proof steps, programs,
hypotheses, or experiments; the host verifies them; durable memory preserves
successes and failures; and a scheduler allocates future compute to the most
promising branches.

In short:

> FinanceBench is the reliability training ground. FrontierMath, Lean proof
> search, ARC-AGI, FunSearch-style algorithm discovery, HorizonMath, and RE-Bench
> are the real "supercomputer-level" research targets.

The question for Kernel v3.1 is therefore:

> Can Holo turn more test-time compute and more agents into verified progress,
> rather than just more text?
