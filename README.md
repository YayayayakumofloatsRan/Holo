# Holo Agent Kernel

This is a new, standalone Holo agent kernel. It has its own product version and
is deliberately separate from the legacy `D:\Holo\holo` chat/persona runtime.
Stage documents remain research logs; the kernel itself is not stage-named.

Kernel version: `2.1.0`

Initial Stage219 goal:

- Linux/WSL-first engineering and research agent.
- Model-first action arbitration with host-side guardrails.
- Auditable event stream and JSONL logs.
- Continuous web search/open/evaluate loop.
- No WeChat/social/persona prompt in the core kernel.
- Architecture references are tracked in
  `docs/STAGE219_ARCHITECTURE_REFERENCES.md`.
- Stable kernel design principles are tracked in
  `docs/KERNEL_DESIGN_PRINCIPLES.md`.
- Context, skills, hooks, and local memory are tracked in
  `docs/STAGE220_CONTEXT_SKILLS_HOOKS.md`.
- Model arbitration and search quality fixes are tracked in
  `docs/STAGE221_MODEL_ARBITRATION_AND_SEARCH_QUALITY.md`.
- The LLM-controlled web loop correction is tracked in
  `docs/STAGE222_LLM_CONTROLLED_WEB_LOOP.md`.
- Engineering action primitives are tracked in
  `docs/STAGE223_ENGINEERING_ACTION_PRIMITIVES.md`.
- Engineering workflow policy and final claim grounding are tracked in
  `docs/STAGE224_ENGINEERING_WORKFLOW_POLICY.md`.
- Source authority evidence for research workflows is tracked in
  `docs/STAGE225_SOURCE_AUTHORITY_LAYER.md`.
- Web Research Kernel v2 contracts are tracked in
  `docs/STAGE226_WEB_RESEARCH_KERNEL_V2.md`.
- Web provider registry and health are tracked in
  `docs/STAGE227_WEB_PROVIDER_REGISTRY.md`.
- Source-policy provider candidates are tracked in
  `docs/STAGE228_SOURCE_POLICY_PROVIDER.md`.
- Page fetcher diagnostics and extraction are tracked in
  `docs/STAGE229_PAGE_FETCHER_EXTRACTION.md`.
- Action self-feedback reports are tracked in
  `docs/STAGE230_ACTION_SELF_FEEDBACK_LOOP.md`.

Run:

```powershell
cd D:\Holo\holo-agent-kernel
python -m holo_agent chat --trace
python -m holo_agent run "search official OpenAI Codex CLI docs and cite sources" --trace
python -m holo_agent status
python -m pytest -q
```

WSL run:

```powershell
wsl.exe -d HoloUbuntu -- bash -lc "cd /mnt/d/Holo/holo-agent-kernel && python3 -m holo_agent chat --trace"
```

Model selection:

- Default is `--model auto`.
- `auto` uses `deepseek-chat` when `DEEPSEEK_API_KEY` is configured.
- `auto` falls back to the explicit offline fallback when no provider key is
  configured.
- Use `--model fallback` to force offline fallback during tests.

Interactive commands:

- `/status` shows loaded local instructions and skills.
- `/web` shows web provider health without starting a live request.
- `/memory` shows local kernel preferences and notes.
- `/logs` shows recent JSONL event rows.
