# Stage188 Crawler Evidence Quality

Stage188 hardens the opened-page evidence layer used by live crawler search.

The Stage187 live smoke showed that Holo could search, open the OpenAI Codex CLI documentation page, and stop with sufficient evidence, but the extracted page text still included CSS utility noise such as `@layer`, `.astro-*`, and `display:inline-flex`. That is not acceptable for market research, document review, or source-grounded report writing.

## Change

Stage188 improves `holo_host/stage163_page_evidence_verifier.py` so page evidence extraction removes common CSS noise that appears outside normal `<style>` tags in modern documentation pages.

The cleanup removes:

```text
CSS at-rules
CSS selector blocks
CSS property fragments
CSS custom-property var(...) fragments
Astro-style selector noise
```

The fix is intentionally in Stage163, not Stage186, because Stage163 is the shared opened-page evidence verifier. This means normal Stage151 web grounding, Stage186 crawler search, and live chat crawler integration all receive cleaner evidence.

## Boundary

Stage188 does not add provider calls, memory writes, WeChat startup, transport changes, or hidden reasoning exposure. It only improves deterministic page evidence cleanup and tests that crawler snippets prefer readable content.
