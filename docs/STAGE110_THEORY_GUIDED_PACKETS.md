# Stage110 Theory-Guided Packets

Stage110 turns theory into packet-control guidance.

Stage105 can already plan finite provider packets. Stage109 defines axioms and
metrics. Stage110 connects them:

```text
theory axiom -> packet rule -> budget / send decision / wait state
```

## Control Rules

`A1_finite_context`

- Every packet needs a bounded budget.
- Stage110 records the recommended total budget and per-role budget.

`A2_local_continuity`

- Broad recall or multiple semantic attractors should preserve a multi-packet
  stream.
- Recommended effect: keep `context_seed -> deliberation_delta -> reply_commit`
  and expand the total packet budget.

`A3_compressive_recurrence`

- Provider returns must be compressed before the next packet.
- Recommended effect: require `distill_delta` before `reply_commit`.

`A4_grounded_perturbation`

- Current-fact or high-uncertainty lookup should run a local tool before reply
  commitment.
- Recommended effect: `next_action=execute_tool_locally`,
  `provider_may_execute_tools=false`, and observation must re-enter the next
  packet.

`A5_expression_decoupling`

- External expression must wait for a provider return or tool observation.
- Recommended effect: `may_emit_before_provider_return=false`.

## CLI

```powershell
python -m holo_host stage110-theory-guided-packets --query "recall anything from memory"
```

Example output for a broad recall query:

- `recommended_packet_count=3`
- `recommended_packet_budget_tokens=3000`
- applied axioms:
  - `A1_finite_context`
  - `A5_expression_decoupling`
  - `A2_local_continuity`
  - `A3_compressive_recurrence`

## Role in the Pipeline

Stage110 does not call the provider. It is the policy layer that a live executor
should consult before sending:

1. Stage105 proposes a packet stream.
2. Stage109 supplies theoretical constraints and measurement hooks.
3. Stage110 returns executable packet guidance.
4. A live executor sends, observes, compresses, and records metrics.

This is the bridge from biomimetic theory to practical provider dispatch.

## Research Bridge

Stage110 uses research ideas as engineering constraints rather than claims of
human consciousness:

- Working memory maps to bounded packet budgets and a limited active buffer.
- Global workspace theory maps to a reply-commit packet that broadcasts only
  selected content outward.
- Complementary learning systems map to fast episodic capture followed by slow
  consolidation into reusable memory summaries.
- Predictive-processing and free-energy ideas map to uncertainty-triggered tool
  calls and measurement of prediction error through observations.
- Generative-agent work maps to observation, planning, reflection, and dynamic
  retrieval as separate packet roles.
- ReAct-style agents map to interleaving provider reasoning, local action, and
  tool observation before final expression.

Primary references used for this mapping:

- Baddeley, `The episodic buffer: a new component of working memory?`,
  https://pubmed.ncbi.nlm.nih.gov/11058819/
- Dehaene and Changeux, `Experimental and theoretical approaches to conscious
  processing`, https://pubmed.ncbi.nlm.nih.gov/21521609/
- McClelland, McNaughton, and O'Reilly, `Why there are complementary learning
  systems in the hippocampus and neocortex`,
  https://web.stanford.edu/~jlmcc/papers/McCMcNaughtonOReilly95.pdf
- Friston, `The free-energy principle: a unified brain theory?`,
  https://www.nature.com/articles/nrn2787
- Park et al., `Generative Agents: Interactive Simulacra of Human Behavior`,
  https://arxiv.org/abs/2304.03442
- Yao et al., `ReAct: Synergizing Reasoning and Acting in Language Models`,
  https://arxiv.org/abs/2210.03629
- `MemGPT: Towards LLMs as Operating Systems`,
  https://arxiv.org/abs/2310.08560
- `Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging
  Frontiers`, https://arxiv.org/abs/2603.07670
