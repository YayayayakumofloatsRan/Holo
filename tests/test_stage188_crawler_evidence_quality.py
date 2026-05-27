from __future__ import annotations

from holo_host.live_crawler_search import run_live_crawler_search
from holo_host.stage163_page_evidence_verifier import extract_page_evidence_text


CSS_HEAVY_DOC_HTML = """
<html>
  <head>
    <title>CLI - Codex | OpenAI Developers</title>
  </head>
  <body>
    @layer theme, base, components, utilities;
    .page-copy-action:where(.astro-y3m22efp){display:inline-flex;min-height:26px;align-items:center;var(--surface-primary)}
    .page-copy-action__icon:where(.astro-y3m22efp){display:block}
    <main>
      <h1>Codex CLI</h1>
      <p>Codex CLI is OpenAI's coding agent that runs locally from your terminal.</p>
      <p>It can read, change, and run code on your machine in the selected directory.</p>
    </main>
  </body>
</html>
"""


def _search(_query: str) -> dict:
    return {
        "query": "OpenAI Codex CLI",
        "status": "ok",
        "provider": "mock_search",
        "results": [
            {
                "title": "CLI - Codex | OpenAI Developers",
                "url": "https://developers.openai.com/codex/cli",
                "snippet": "Codex CLI is OpenAI's coding agent that runs locally from your terminal.",
            }
        ],
    }


def _open_page(url: str) -> dict:
    return {
        "url": url,
        "status": "ok",
        "provider": "mock_page",
        "html": CSS_HEAVY_DOC_HTML,
    }


def test_stage188_page_extractor_removes_css_noise_outside_style_tags() -> None:
    extracted = extract_page_evidence_text(CSS_HEAVY_DOC_HTML, url="https://developers.openai.com/codex/cli")

    assert "Codex CLI is OpenAI's coding agent" in extracted["text"]
    assert "It can read, change, and run code" in extracted["text"]
    assert "@layer" not in extracted["text"]
    assert "display:inline-flex" not in extracted["text"]
    assert "var(--surface-primary)" not in extracted["text"]
    assert "astro-y3m22efp" not in extracted["text"]


def test_stage188_crawler_supporting_snippet_prefers_clean_page_content() -> None:
    report = run_live_crawler_search(
        user_text="search OpenAI Codex CLI official documentation",
        web_search_fn=_search,
        open_page_fn=_open_page,
        network_enabled=True,
    )

    page = report["page_observation_ledger"][0]
    score = page["page_evidence_score"]

    assert report["status"] == "sufficient"
    assert "Codex CLI is OpenAI's coding agent" in page["text"]
    assert "display:inline-flex" not in page["text"]
    assert "Codex CLI is OpenAI's coding agent" in score["supporting_snippet"]
    assert "page-copy-action" not in score["supporting_snippet"]
