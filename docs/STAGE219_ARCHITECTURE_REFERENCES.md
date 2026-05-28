# Stage219 Architecture References

Stage219 is not a patch of the legacy Holo chat runtime. It starts a new
engineering-agent kernel and borrows architecture patterns from mature agent
tools.

## Codex / Codex CLI Patterns

References:

- OpenAI Codex developer entry: <https://developers.openai.com/codex/>
- Codex use cases: <https://developers.openai.com/codex/explore>
- OpenAI Codex repository: <https://github.com/openai/codex>
- Codex `AGENTS.md` guidance in repository docs:
  <https://github.com/openai/codex/blob/main/docs/agents_md.md>

Design implications for Holo:

- Project instructions are first-class and file-scoped.
- The terminal is an agent console, not a chat box.
- Actions must leave an auditable trace.
- Tool execution and sandbox/permission boundaries are host concerns.
- Repeated workflows should become skills instead of prompt bulk.
- MCP-style tool adapters should be a stable interface, not ad hoc prompt text.

Stage219 status:

- Implements an auditable CLI and event log.
- Implements a tool registry with structured specs.
- Keeps host tool execution separate from model decision.

Stage220 targets:

- Add instruction hierarchy files similar to `AGENTS.md`.
- Add skills as small folders with `SKILL.md` plus optional scripts/resources.
- Add a stable MCP-compatible adapter layer.

## Claude Code Patterns

References:

- Claude Code overview: <https://docs.anthropic.com/en/docs/claude-code/overview>
- Claude Code memory: <https://docs.anthropic.com/en/docs/claude-code/memory>
- Claude Code subagents: <https://docs.anthropic.com/en/docs/claude-code/sub-agents>
- Claude Code hooks: <https://docs.anthropic.com/en/docs/claude-code/hooks>

Design implications for Holo:

- Memory should be layered by authority and scope.
- Project memory should be loaded from the working directory hierarchy.
- Subagents should have separate context windows and tool allowlists.
- Hooks are useful for observability, validation, and workflow automation.
- `/memory`, `/trace`, `/tools`, `/logs`, and `/status` should be native CLI
  inspection commands.

Stage219 status:

- Creates a public event log and trace renderer.
- Avoids hidden reasoning in public surfaces.

Stage220 targets:

- Add `HOLO.md` / `.holo/` scoped instructions.
- Add `/logs`, `/tools`, `/context`, and `/memory` CLI commands.
- Add hook points: before_tool, after_tool, before_final, after_final.

## Hermes Agent Patterns

References:

- NousResearch Hermes Agent repository:
  <https://github.com/NousResearch/hermes-agent>

The Hermes ecosystem emphasizes persistent memory, tool use, multi-platform
gateways, and skill/self-improvement loops. For Holo, the useful part is not
the chat-platform surface; it is the closed loop:

```text
tool trace -> failure analysis -> skill/policy candidate -> benchmark -> promotion
```

Design implications for Holo:

- Tool histories should be reusable training/evaluation data.
- Skills should be promoted only after benchmark evidence.
- Multi-platform adapters must be outside the core kernel.
- Self-improvement must be reversible and inspectable.

Stage219 status:

- Starts durable JSONL event traces.

Stage221+ targets:

- Add a skill journal.
- Add benchmark-driven skill promotion.
- Add memory/preferences/skills storage that the agent can inspect.

## Core Holo Kernel Requirements Derived From References

The new kernel must satisfy these invariants before domain modules:

1. Model proposes; host executes; ledger proves; stop controller closes.
2. CLI shows public events, not hidden chain-of-thought.
3. Web research is search -> open -> evaluate -> continue/stop.
4. Every final current/web claim must cite an observation.
5. Project instructions, preferences, and skills are loaded as structured
   context, not mixed into persona text.
6. WeChat and roleplay are adapters, not the kernel.
7. Long-running research leaves resumable logs and error reports.

