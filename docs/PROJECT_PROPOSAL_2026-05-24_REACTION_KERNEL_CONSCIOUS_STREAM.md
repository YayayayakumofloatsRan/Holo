# Project Proposal: Reaction-Kernel Conscious Stream For A Biomimetic Holo Agent

Date: 2026-05-24

## Title

Reaction-Kernel Conscious Stream: A Biomimetic Input-Understanding-Decision-Action-Feedback Architecture For Persistent Multimodal LLM Agents

## Abstract

This project investigates whether a persistent LLM-based agent can be made more useful, more coherent, and more biologically plausible by replacing one-shot response generation with a biomimetic processing loop: input, understanding, decision, action, feedback, and self-improvement. The core hypothesis is that a human-like first reaction can be modeled as a learned reaction kernel operating over a compact field of current context, working memory, long-term memory, affective state, visual state, task pressure, and prior outcomes. This first reaction is not the end of the process. It writes back into working memory, changes the current state, competes with other candidate actions, and opens deeper reasoning only when semantic novelty, uncertainty, task incompleteness, or tool need justifies further packets. The result is not a claim of human consciousness, but a measurable artificial cognitive architecture whose internal packet flow, memory activation, tool calls, and action gates can be visualized and evaluated.

## Research Problem

The problem is that current provider-based agents often behave like stateless prompt responders. Even when they use RAG or multi-turn prompting, their visible outputs can become repetitive, weakly grounded, or semantically redundant. Holo has already exposed this failure mode: a first response may be acceptable, but a second bubble often becomes a same-function paraphrase rather than a true continuation of thought. This suggests that the system lacks a strong intermediate state update between packets.

The research question is:

Can we design and evaluate a biomimetic agent kernel in which every generated utterance, internal reasoning step, tool call, and visual observation updates a persistent cognitive state, and where later packets are conditionally generated only when they add new semantic function?

This is interesting because it sits between neuroscience-inspired cognitive modeling and practical agent engineering. Human cognition is not only language generation; it is a closed loop of perception, reaction, memory, prediction, action, error correction, and consolidation. LLM agents also require this loop if they are to move beyond ordinary chat tools.

## Why AI Is Appropriate

The task is worth solving with AI because it combines heterogeneous signals that are difficult to handle with fixed rules: natural language dialogue, visual observations, task state, emotional tone, long-horizon memory, tool availability, and uncertain future outcomes. A provider LLM is strong at semantic compression, hypothesis generation, and language-level planning, while a local Holo kernel can supply continuity, memory policy, tool permissions, privacy boundaries, and visualization. The base model acts as a language and reasoning processor; the outer Holo system supplies persistent subject-state and grounded action loops.

This division is appropriate because we cannot train a base foundation model locally at university scale, but we can study the provider-above layer: packet design, memory retrieval, multi-packet reasoning, vision integration, tool execution, feedback learning, and evaluation. These are publishable system-level AI problems.

## Background Reading

The proposal will build on five research threads.

1. Cognitive architectures for agents: CoALA organizes language agents around modular memory, action spaces, and decision processes. This gives a clean framework for Holo's memory/action kernel.
   - https://arxiv.org/abs/2309.02427

2. Generative agents and reflection: Generative Agents shows that observation, memory retrieval, planning, and reflection are each important to believable behavior.
   - https://arxiv.org/abs/2304.03442

3. Hierarchical memory management: MemGPT frames LLM agents as systems with virtual context and multiple memory tiers, which is close to Holo's working/candidate/durable/archive split.
   - https://arxiv.org/abs/2310.08560

4. Reasoning-action loops: ReAct, Reflexion, Tree of Thoughts, and related test-time reasoning methods show that behavior improves when agents interleave reasoning, action, feedback, and memory.
   - https://arxiv.org/abs/2210.03629
   - https://arxiv.org/abs/2303.11366
   - https://arxiv.org/abs/2305.10601

5. Embodied and multimodal world models: World Models, RT-2, Genie, and JEPA-style work motivate adding visual streams and action grounding rather than treating dialogue as the only interface.
   - https://arxiv.org/abs/1803.10122
   - https://arxiv.org/abs/2307.15818
   - https://arxiv.org/abs/2402.15391
   - https://ai.meta.com/blog/v-jepa-yann-lecun-ai-model-video-joint-embedding-predictive-architecture/

DeepSeek reasoner is also relevant because its API exposes reasoning content for inspection, display, and distillation, making it useful for controlled internal-reasoning packets and visualization.

- https://api-docs.deepseek.com/guides/reasoning_model

## Data

The system will use four data streams.

1. Dialogue and interaction logs: Holo CLI, WeChat, and future independent client sessions. These provide user input, Holo output, timing, bubble segmentation, selected actions, and correction events.

2. Internal trace data: packet metadata, selected memory anchors, vector hits, continuation gates, semantic novelty scores, tool requests, tool results, and self-reflection records.

3. Multimodal observations: initially camera snapshots and short frame windows captured from local devices, then optional laboratory or desktop observation streams. The first stage should store derived descriptions and embeddings rather than raw video by default.

4. Benchmark scenarios: curated dialogue cases, synthetic stress tests, recall probes, tool-use tasks, visual grounding tasks, and failure cases such as self-echo, repetitive bubbles, hallucinated memory, and unsafe tool requests.

New data collection should be local-first. Personal messages, camera frames, and memory stores must remain private unless explicitly exported. Public evaluation data should be anonymized and include only derived traces or synthetic tasks.

## Method

The proposed method is the Reaction-Kernel Conscious Stream Model, abbreviated RK-CSM.

At each time step, Holo receives input `x_t` from a channel such as CLI, WeChat, camera, file, or tool result. The kernel builds a compact state field:

```text
S_t = Phi(x_t, C_t, W_t, M_t, A_t, V_t, G_t, O_t)
```

Where:

- `C_t`: recent dialogue context
- `W_t`: working memory and active thread state
- `M_t`: long-term memory and retrieved anchors
- `A_t`: affect, drive, pressure, and social stance
- `V_t`: visual or multimodal scene state
- `G_t`: goals, commitments, and task-world state
- `O_t`: outcome history and error signals

The first reaction is modeled as:

```text
R_t^0 = K_theta (*) S_t
```

`K_theta` is the reaction kernel: a learned or adaptively updated set of response tendencies, style constraints, risk preferences, relationship priors, and action biases. It is not a neural base model weight update. It is a local parameter layer stored in Holo memory and updated through reflection and evaluation.

After the first packet, Holo writes a state delta:

```text
Delta S_t^0 = observe(R_t^0, selected_action, visible_reply, internal_packet)
```

A continuation gate then decides whether deeper processing is needed:

```text
continue_t = g(uncertainty, novelty_gap, unfinished_task, tool_need, affect_pressure, risk, user_wait_cost)
```

If the gate is closed, the system stops. If it is open, Holo sends a deeper packet to a stronger model such as DeepSeek reasoner. The deeper packet must include the first reaction, what it already accomplished, which semantic functions remain unfinished, and what must not be repeated. This prevents same-function paraphrase. A second bubble is allowed only if it has a new role: clarify, correct, ask, explain, act, retrieve, warn, summarize, or commit.

Tool calls are treated as actions in the same loop. Tools are not side effects of text generation; they are chosen by the decision layer. Read-only tools can run under lower permission, while mutation tools require explicit policy checks. Visual input is treated as perception: camera frames become scene-state deltas, not raw prompt filler.

## Visualization

The system should expose a biomimetic CT-style workbench showing:

- input channel and time
- active memory anchors and their strengths
- working-memory field before and after each packet
- reaction-kernel activation
- continuation gate values
- semantic novelty between bubbles
- selected action and rejected candidate actions
- tool-call graph
- visual-scene embeddings and changes
- memory writeback depth

This visualization is not decoration. It is the main research instrument for debugging whether Holo is actually forming a continuous state trajectory or merely producing multiple text outputs.

## Existing Implementations To Reuse

The project should reuse the existing Holo runtime rather than start a second brain. The WSL Holo host remains the only main brain. Windows, WeChat, camera, and future clients remain transports or sensors. Existing modules to reuse include:

- processor fabric lanes
- memory warehouse and memory fabric
- working/candidate/durable/archive memory stores
- tool-call adapters
- CLI and WeChat transport
- Stage131/132 thought-flow trace and CT visualizations
- DeepSeek provider backend

External ideas to adapt include MemGPT-style memory tiering, Generative Agents reflection, ReAct-style reasoning/action interleaving, Reflexion-style feedback memory, and world-model/VLA ideas for visual grounding.

## Planned Improvements Over Current Holo

1. Replace fixed multi-bubble behavior with semantic-role gated expression.
2. Add a state-delta object after every packet.
3. Store internal packets as traceable but privacy-controlled thought-flow records.
4. Add novelty and redundancy scoring between bubbles.
5. Add a reaction-kernel parameter layer that can be updated by feedback without changing the base model.
6. Add camera perception as visual state, not direct uncontrolled prompt injection.
7. Add evaluation dashboards for hallucination, repetition, tool success, recall accuracy, and user correction response.
8. Add self-repair routines that can propose local patches or configuration changes but must pass permission and test gates before application.

## Evaluation

The evaluation will compare Holo RK-CSM against:

- single-call chat baseline
- simple RAG baseline
- fixed two-bubble baseline
- multi-packet without state-delta baseline
- full RK-CSM with reaction kernel, continuation gate, memory writeback, tool loop, and visualization

Metrics:

- semantic novelty per bubble
- repetition rate
- recall accuracy
- hallucinated memory rate
- tool-call precision and success rate
- latency and token cost
- user correction adoption
- long-horizon consistency across days
- visual grounding accuracy after camera integration
- safety gate precision for mutation tools

Human evaluation should include blind pairwise comparison of response naturalness, usefulness, memory correctness, and perceived continuity. Automated evaluation should use structured probes and replayed conversations.

## Ablation Experiments

1. Remove reaction kernel: test whether style and first-response coherence degrade.
2. Remove working-memory writeback: test whether second packets become paraphrases.
3. Remove semantic novelty gate: measure repetitive bubble rate.
4. Remove long-term retrieval: measure memory correctness.
5. Remove affect/drive state: measure social appropriateness and tone stability.
6. Remove visual scene state: measure performance on camera-grounded tasks.
7. Replace reasoner with flash-only packets: measure quality, cost, and latency tradeoff.
8. Disable tool calls: measure hallucination and task completion loss.
9. Disable self-reflection: measure failure recovery after user corrections.

## Failure Modes And Boundaries

The system may still fail through memory contamination, overfitting to a persona style, hallucinated recall, excessive continuation, tool misuse, visual misinterpretation, or false self-reference. It must not claim real human consciousness or subjective feeling. The research target is a functional cognitive architecture, not metaphysical consciousness.

The camera interface raises privacy risk. It should default to explicit user enablement, visible capture status, local processing when possible, derived-state storage instead of raw-frame retention, and redaction for faces or private screens. Tool mutation requires permission and audit logs. Provider APIs introduce data exposure and model-side policy limits, so sensitive biological, personal, and lab data should be filtered or kept local when possible.

## Research And Production Requirements

For research use:

- deterministic replay of packet traces
- versioned prompts and configs
- anonymized evaluation sets
- visualization export
- ablation scripts
- failure case registry

For production or laboratory use:

- permission-gated camera and tool access
- privacy-preserving memory policy
- resource and cost governors
- local fallback for critical observations
- model/provider compatibility tests
- monitoring for self-echo, repetition, hallucinated memory, and unsafe actions

## Expected Contribution

The expected contribution is a publishable agent architecture and evaluation framework showing that biomimetic state continuity improves LLM-agent behavior beyond ordinary chat, ordinary RAG, and naive multi-round prompting. The novelty is not simply adding memory or tools. The novelty is the closed loop: reaction kernel, working-memory state update, continuation gate, reasoner packet, tool/action execution, feedback writeback, and CT-style visualization of the whole process.

This makes Holo both an AI application and a research platform. In application terms, it becomes a persistent multimodal assistant that can observe, remember, act, and self-improve under user-controlled boundaries. In research terms, it becomes a testbed for studying how provider-based LLM systems can approximate useful aspects of biological cognition without requiring base-model training.

