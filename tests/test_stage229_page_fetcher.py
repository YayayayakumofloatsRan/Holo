from __future__ import annotations

from urllib.error import HTTPError
from io import BytesIO

from holo_agent.page_fetcher import PageFetchResult, PageFetcher, extract_page_text
from holo_agent.model import RuleFallbackModel
from holo_agent.tools import OpenPageTool, WebClient


def test_extract_page_text_removes_scripts_and_keeps_title() -> None:
    page = """
    <html><head><title>Example Doc</title><script>bad()</script></head>
    <body><nav>navigation</nav><main><h1>Official Docs</h1><p>Tool calling details.</p></main></body></html>
    """

    extracted = extract_page_text(page, url="https://example.com/docs", content_type="text/html")

    assert extracted.title == "Example Doc"
    assert "bad()" not in extracted.text
    assert "Official Docs" in extracted.text
    assert extracted.extraction_quality > 0.1


def test_page_fetcher_records_http_error_diagnostics() -> None:
    class Client:
        def open(self, request, timeout):
            raise HTTPError(request.full_url, 403, "Forbidden", {"content-type": "text/html"}, BytesIO(b"blocked"))

    fetcher = PageFetcher(opener=Client())

    result = fetcher.fetch("https://developers.openai.com/codex/cli", timeout=1)

    assert result.status == "error"
    assert result.status_code == 403
    assert result.error_type == "HTTPError"
    assert "Forbidden" in result.error


def test_open_page_observation_includes_fetch_and_extraction_report() -> None:
    class Client(WebClient):
        def fetch_page(self, url: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                final_url=url,
                status="ok",
                status_code=200,
                content_type="text/html",
                text="<html><title>Docs</title><main>Function Calling allows external tools.</main></html>",
                bytes_read=80,
                elapsed_ms=2,
            )

    obs = OpenPageTool(Client()).run(url="https://api-docs.deepseek.com/guides/function_calling")

    assert obs.status == "ok"
    assert obs.data["fetch"]["status_code"] == 200
    assert obs.data["extracted_page"]["title"] == "Docs"
    assert "Function Calling" in obs.data["text"]


def test_open_page_failure_includes_fetch_report() -> None:
    class Client(WebClient):
        def fetch_page(self, url: str) -> PageFetchResult:
            return PageFetchResult(
                url=url,
                final_url=url,
                status="error",
                status_code=403,
                content_type="text/html",
                error="HTTP Error 403: Forbidden",
                error_type="HTTPError",
                elapsed_ms=4,
            )

    obs = OpenPageTool(Client()).run(url="https://developers.openai.com/codex/cli")

    assert obs.status == "error"
    assert obs.summary == "HTTP Error 403: Forbidden"
    assert obs.data["fetch"]["status_code"] == 403
    assert obs.data["fetch"]["error_type"] == "HTTPError"


def test_explicit_url_request_routes_to_open_page() -> None:
    decision = RuleFallbackModel().decide(
        user_text="open https://docs.python.org/3/library/asyncio.html and summarize source",
        context={"observations": [], "search_goal": {}, "crawl_report": {"plan": {"queries": []}}},
        action_space=[],
    )

    assert decision.action == "open_page"
    assert decision.arguments["url"] == "https://docs.python.org/3/library/asyncio.html"


def test_explicit_url_open_success_finalizes_without_extra_search() -> None:
    decision = RuleFallbackModel().decide(
        user_text="open https://docs.python.org/3/library/asyncio.html and summarize source",
        context={
            "observations": [
                {
                    "tool": "open_page",
                    "status": "ok",
                    "summary": "asyncio docs",
                    "data": {"url": "https://docs.python.org/3/library/asyncio.html"},
                }
            ],
            "search_goal": {},
            "crawl_report": {"status": "weak", "plan": {"queries": [{"query": "asyncio docs"}]}},
        },
        action_space=[],
    )

    assert decision.action == "answer_direct"
    assert decision.can_answer is True
