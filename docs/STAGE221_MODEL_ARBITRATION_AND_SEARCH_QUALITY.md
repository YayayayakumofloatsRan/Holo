# Stage221 Model Arbitration And Search Quality

Stage221 records runtime improvements for Holo Agent Kernel `2.1.0`.
The kernel name and package remain stage-free; Stage221 is only the research
and engineering progress record.

## Changes

- Kernel product version is `2.1.0`.
- CLI/runtime surfaces report `Holo Agent Kernel 2.1.0`, not a stage label.
- The agent loop now feeds prior observations and prior decisions back into
  the next model decision.
- Source relevance is now represented as a `SourceEvaluator` model contract:
  `search -> open -> evaluate_source -> accept/continue`.
- CLI model selection now defaults to `auto`: use `deepseek-chat` when
  `DEEPSEEK_API_KEY` exists, otherwise use the explicit offline fallback.
- A failed `web_research` attempt is reported as `tool_failure_report` instead
  of repeating the identical failing call.
- Search result parsing now filters Bing navigation/category pages such as
  Images, Videos, Maps, News, and Shopping.
- Bing `/ck/` redirect URLs are decoded when possible before source filtering.
- Query cleaning keeps valid UTF-8 Chinese terms and removes low-value English
  glue words such as `and`.
- Lexical support is only the explicit fallback evaluator when no model source
  evaluator is attached. It is not the primary intelligence path.

## Verified Smoke

Command:

```powershell
python -m holo_agent run "search official OpenAI Codex CLI docs and cite sources" --trace
```

Observed result:

```text
[model_decide] selected=web_research
[observation] web_research status=ok
[stop] final_answer_ready
```

The smoke returned primary or directly relevant sources including:

- `https://developers.openai.com/codex/cli`
- `https://github.com/openai/codex`

## Next Work

The next stage should keep the kernel name stable and improve the model-first
loop rather than adding stage-named runtime surfaces:

- Make DeepSeek JSON arbitration the default when `DEEPSEEK_API_KEY` exists.
- Add explicit source-authority scoring for official docs, filings, papers,
  and financial data.
- Add a research report assembler that cites only accepted source evidence.
- Add richer workspace tools after the web loop is stable.
