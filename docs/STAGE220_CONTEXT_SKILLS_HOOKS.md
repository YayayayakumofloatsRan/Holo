# Stage220 Context, Skills, Hooks, And Local Memory

Stage220 adds Codex/Claude-Code-style project context infrastructure to Holo
Agent Kernel `2.1.0`.

The kernel still has its own semantic version. Stage220 is only the research
record for this iteration.

## Added Surfaces

### Instruction Layers

The kernel loads workspace instruction files:

```text
HOLO.md
AGENTS.md
CLAUDE.md
```

They are loaded into the public context event and made available to the model
context. This mirrors Codex/Claude Code project instruction files while keeping
the implementation simple.

### Skills

Skills live under:

```text
.holo/skills/<skill-name>/SKILL.md
```

Stage220 only loads and reports skills. Stage221 should add skill selection and
execution.

### Preferences And Memory

Local kernel memory lives in:

```text
.holo_kernel/memory.json
```

It currently stores preferences and notes. This is intentionally separate from
legacy Holo memory.

### Hooks

The new `HookManager` exposes lightweight events:

```text
goal
context
action_space
model_decide
tool_call
after_tool
observation
evaluate
stop
final
```

Hooks are host-side observability and automation points. They do not expose
hidden reasoning.

## CLI

```powershell
python -m holo_agent status
python -m holo_agent memory --set tone=concise
python -m holo_agent chat --trace
```

Inside chat:

```text
/status
/skills
/memory
/logs
```

## Stage221 Link

Stage221 continues from this context layer into model arbitration and search
quality:

```text
docs/STAGE221_MODEL_ARBITRATION_AND_SEARCH_QUALITY.md
```
