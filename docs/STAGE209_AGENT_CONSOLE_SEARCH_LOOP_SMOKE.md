# Stage209 Agent Console Search Loop Smoke

Stage209 verifies that the live Holo reply path can continue a web search after weak evidence and show that continuation in the CLI console trace.

The smoke fixture runs through `HoloReplyService`, Stage151 model-first tool decision metadata, Stage186 bounded crawler search, Stage190 self-feedback, Stage153 event stream, and Stage207 console rendering. It uses a deterministic broker that first returns a weak third-party Codex overview, then returns the official OpenAI Codex CLI documentation when the crawler escalates to official/docs queries.

Public visibility is explicit and bounded:

- user text and final answer remain normal visible text
- system/action rows show `[model_decide]`, `[crawl:query]`, `[crawl:search]`, `[crawl:open]`, `[crawl:evaluate]`, and `[crawl:stop]`
- raw provider reasoning, chain-of-thought text, and internal messages remain private
- the public trace shows auditable decisions, observations, source selection, and stop reasons

The Stage209 smoke fails if:

- the crawler stops after the weak source
- weak third-party evidence is promoted into final sources
- official source evidence is missing from the final answer
- the console reports `answer_direct` while crawler/web observations actually ran
- the stop reason is unknown
- private reasoning leaks into artifacts

CLI:

```powershell
python -m holo_host run-agent-console-search-loop-smoke --output artifacts\stage209\stage209_agent_console_search_loop_smoke.html --dry-run
```

Artifacts:

- `.html` console report
- `.json` bundle
- `.jsonl` per-fixture rows

Stage209 is still a smoke/evaluation layer. It does not add provider calls, memory writes, transport authority, watcher behavior, or hidden reasoning exposure.
