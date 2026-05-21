# Stage104 Context Learning and Semantic Attractors

Stage104 turns the memory complaint into an executable mechanism: provider calls are stateless, so Holo must learn locally by compressing recent activity into stable semantic attractors and placing those attractors into the next context packet.

## First Principles

- The provider does not preserve Holo's subjective continuity between calls. Each call receives a packet.
- Short-term working memory can be strong, but it decays unless the system selects what should become long-term memory.
- Long-term memory should not be raw chat replay. It should be compressed, semantic, prompt-eligible, and traceable to evidence.
- A biomimetic approximation should expose repeated semantic-affective attractors, because those are the structures that make broad recall less like recent-log echoing.

## Research Anchors

- MemGPT: virtual context management across memory tiers.
- Generative Agents: observation, reflection, planning, and dynamic memory retrieval.
- Reflexion: verbal reinforcement through reflected episodic memory rather than provider weight updates.
- A-MEM: agentic, graph-like memory organization inspired by linked notes and adaptive memory operations.

Stage104 maps these into Holo as:

- `archive/working/thought` rows as recent experience.
- `context_attractor` candidates as compressed semantic memories.
- `stage104_context_packet()` as the local context-learning packet.
- `inject_stage104_context()` as the provider-facing insertion point.

## Runtime Contract

Command:

```powershell
python -m holo_host stage104-context-learning --dry-run --query "回忆任何事情？"
```

WSL-only write:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo && python3 -m holo_host stage104-context-learning --repo-root /home/holo/holo --apply --confirm APPLY_STAGE104_CONTEXT_LEARNING_FROM_WSL --query '回忆任何事情？'"
```

Apply only writes `context_attractor` candidates. It is not a reset path and it does not touch transport/watchers.

## Provider Packet Effect

Before Stage104, broad recall could be dominated by a recent echo such as "you just asked this recall test".

After Stage104, the first recalled lines become:

- `Stage104 attractor: Holo is in the Stage100+ biomimetic-agent research arc...`
- `Stage104 attractor: Provider calls are stateless inference...`
- `Stage104 attractor: The biomimetic hypothesis is that repeated semantic-affective themes form high-dimensional attractors...`
- `Stage104 attractor: The operator's acceptance bar is experiential improvement...`

This is the first practical step from visualization-only topology toward a packet-level memory substrate.

## Live Evidence

Run on 2026-05-22 from WSL against `/home/holo/holo`:

- Warehouse start: `2026-04-02T00:00:00Z`
- Before Stage104 live apply: durable memory staleness was `44` days.
- Stage104 dry run found 5 attractors: `project_stage`, `memory_consolidation`, `provider_context_learning`, `biomimetic_topology`, `experience_deficit`.
- WSL apply wrote 5 `context_attractor` candidates.
- A subsequent mind-packet inspection promoted these attractors into durable rows `memory-0023` through `memory-0027` and reported durable staleness `0` days.

## Known Constraint

The `/home/holo/holo` checkout is heavily dirty and not safe to overwrite wholesale. The Stage104 code is implemented in `D:\Holo\holo`; the live memory data has been updated from WSL using that code. Aligning the live checkout should be a separate controlled operation.
