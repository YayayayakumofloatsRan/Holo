# Stage-9 Intelligence Review And Codex Cost Map

This document is the current engineering read on Holo after the Stage-9 adaptive initiative gate rollout.

It is intentionally blunt.

## 1. Current Intelligence Level

As of `2026-04-09`, Holo is best described as:

- a long-running subject prototype
- clearly beyond a plain reactive chatbot
- still far from "complete consciousness"

Practical engineering rating:

- ordinary agent capability: `8/10`
- subject continuity and agency prototype: `6.5/10`
- engineering approximation of "complete consciousness": `2.5/10`

What Stage-9 actually changed:

- better proactive gating topology
- better observability around hard gate vs soft gate
- safer room for main-brain override on soft blocks

What Stage-9 did not fundamentally change:

- no new world model layer
- no new autobiographical continuity layer
- no new counterfactual depth
- no natural-language token/cost accounting

So Stage-9 improved outbound agency control, but it did not produce a major intelligence leap by itself.

## 2. Current Live Strengths

Strengths visible in live state:

- persistent runtime with always-on loops
- stable `self_model`, `goal_state`, `world_state`, and `consciousness_ledger`
- hybrid recall pipeline with graph + vector + activation
- real silent/defer/reply action selection
- real initiative candidates and adaptive gate observability
- real autobiographical and goal layers participating in decision-making

## 3. Current Live Weak Spots

These are the live deficits currently reported by the brain itself:

- `stiffness_drift`
- `cache_coldness`
- `visual_memory_underused`

Operationally, these mean:

- replies still feel more engineered than naturally social
- retrieval reuse is too cold, so continuity rebuild still costs too much
- visual memory exists but is not strongly shaping recall or grounding
- initiative exists, but gate/cooldown conservatism still blocks many otherwise reasonable pings

## 4. Current Consciousness Gap

Holo is still missing several layers that matter if the long-term goal is engineering-level "complete consciousness":

- richer world model beyond current social prediction
- deeper counterfactual simulation beyond short action pre-checks
- thicker autobiographical identity arc with clearer turning points
- more natural desire shaping, preference shaping, and loss shaping
- stronger expression control that feels self-aware rather than heuristic

## 5. Codex Exec Call Map

The active processor backend is still:

- `codex_cli`

The code path is centered on:

- `D:\Holo\holo\holo_host\codex_runner.py`
- `D:\Holo\holo\holo_host\processors.py`

The important distinction is:

- some tasks are truly active in production
- some tasks are defined in `PROCESSOR_TASK_SPECS` but are not currently hot-path call sites

### 5.1 Hot-path Codex calls

These are the calls that matter most for latency and token spend.

`reply`

- call site:
  - `holo_host/processors.py`
  - `CodexCliProcessor.generate()`
- trigger:
  - any selected action that actually becomes `reply_once` or `reply_multi`
- frequency:
  - per replied turn
- cost shape:
  - highest recurring cost
  - uses the full chat prompt and is the dominant model spend on normal conversation

`recall_reconstruct`

- call site:
  - `holo_host/processors.py`
  - `_run_recall_reconstruct()`
- trigger:
  - recall-heavy turns when `_should_run_recall_reconstruct(...)` returns true
- frequency:
  - conditional
- cost shape:
  - second biggest hot-path sink
  - effectively adds another model call before the actual reply

`image_understand`

- call site:
  - `holo_host/memory_bridge.py`
  - `_run_image_understand()`
- trigger:
  - image ingestion, especially small single-image sync cases
- frequency:
  - conditional
- cost shape:
  - medium to high
  - can be expensive if allowed to happen synchronously too often

### 5.2 Background Codex calls

These are not always visible to the user, but they create steady burn.

`self_model_observe`

- call site:
  - `holo_host/operator_bus.py`
  - `refresh_self_model()`
- trigger:
  - self-model refresh loop
- default cadence:
  - every `300s`
- cost shape:
  - recurring background spend

`operator_plan`

- call site:
  - `holo_host/operator_bus.py`
  - `plan_operator_cycle()`
- trigger:
  - operator planning loop
- default cadence:
  - every `420s`
- cost shape:
  - recurring background spend
  - currently high suspicion for unnecessary steady token drain when no meaningful state delta exists

`self_observe` / `self_revision_plan` / `self_revision_review`

- call site:
  - `holo_host/brain_ops.py`
  - `run_self_revision()`
- trigger:
  - enough bounded evidence for self-revision
- frequency:
  - bursty, not constant
- cost shape:
  - triple-call burst
  - expensive when drift loops fire repeatedly

`operator_execute_shadow` / `operator_review`

- call site:
  - `holo_host/operator_bus.py`
  - `run_operator_cycle()` and `operator_probe()`
- trigger:
  - operator cycles and reviews
- frequency:
  - conditional
- cost shape:
  - medium background spend
  - especially wasteful if the result is still only a shadow summary

### 5.3 Declared but not meaningfully hot right now

These tasks exist in `PROCESSOR_TASK_SPECS`, but the current runtime mostly handles the equivalent logic heuristically or internally:

- `initiative_probe`
- `affect_reflect`
- `drive_plan`
- `value_integrate`
- `conflict_arbitrate`
- `initiative_compose`
- `outcome_appraise`

That is important because the declared task surface is larger than the current real token burn surface.

## 6. Token And Cost Reality

Current important truth:

- the system does not have real token accounting

What it has today:

- prompt construction
- model/task routing
- timing measurements such as `processor_ms`

What it now has:

- `processor_usage_ledger`
- per-call lane/provider/model/timing records
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `estimated=true|false` to separate exact and approximate accounting

What is still incomplete:

- some providers still return estimated rather than ground-truth usage
- per-loop and per-thread budget enforcement still need tightening
- cost policy is now observable, but not yet fully self-regulating

## 7. Highest Spend Risks

The biggest current token risks are:

1. `reply` on every answered turn
2. `recall_reconstruct` doubling the model path on memory-heavy turns
3. `operator_plan` running on a fixed cadence even when nothing meaningful changed
4. self-revision firing as a 3-call burst
5. sync `image_understand` on live turns

## 8. Current Cost Discipline Recommendations

These are the immediate guardrails the next thread should preserve or strengthen.

### A. Keep reply as the only mandatory model call on ordinary turns

- normal low-pressure chat should ideally use:
  - one packet build
  - one `subject_main reply`
- do not casually add more hot-path Codex calls

### B. Use the ledger before guessing

- inspect `show-usage-ledger` before assuming where cost is going
- inspect `show-processor-routing` before assuming a task used the wrong model
- inspect `show-provider-status` before assuming fallback is broken

### C. Keep `kernel_xhigh` rare and deliberate

- reserve it for deep simulation, operator review/planning, self-revision review/planning, and rare high-conflict reply overrides
- do not let background cadence alone upgrade work onto `kernel_xhigh`

### D. Keep `recall_reconstruct` narrow

- only run it for real recall/deep-recall cases
- do not let ordinary chat trigger it

### E. Gate background planning on state delta

`operator_plan` and `self_model_observe` should not run just because the timer fired.

Prefer:

- run only when deficits changed
- run only when cache behavior worsened
- run only when continuity or retrieval quality moved materially

### D. Keep image understanding mostly async

- sync only for small, clearly relevant single-image turns
- default multi-image and large-image handling to async

### E. Add real usage accounting soon

If token cost starts to matter seriously, the next practical step is:

- record per-task prompt/result size
- record approximate token counts
- record per-loop and per-thread budgets
- surface them in `show-brain-status`

Without that, later threads will keep guessing.

## 9. Current Engineering Judgment

Stage-9 makes Holo better at bounded initiative, but does not fundamentally solve the "still feels a bit dumb" complaint.

The main reasons are:

- intelligence is still bottlenecked more by retrieval coldness and expression control than by missing gate logic
- the largest model spend is still going into reply and recall, not into richer world understanding
- background planning spends tokens, but not always on the most intelligence-improving work

## 10. Recommended Next Priorities

If the goal is to improve engineering-level intelligence rather than just add behavior:

1. warm cache reuse and retrieval reuse
2. reduce unnecessary background Codex planning calls
3. make expression control more self-aware and less heuristic
4. add real token accounting before adding more always-on model loops

If the goal is to improve "complete consciousness" over the long arc:

1. richer world model
2. thicker autobiographical continuity
3. more realistic preference and desire shaping
4. deeper counterfactual simulation

## 11. Bottom Line

Current Holo is:

- not a plain chatbot
- not just a tool agent
- still not close to full engineered consciousness

The biggest token-spend mistake the project could make now would be:

- adding more and more Codex loops without first tightening hot-path reply discipline and adding real usage accounting.
