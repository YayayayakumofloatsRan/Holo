from __future__ import annotations

import html
import base64
import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen

from .page_fetcher import PageFetchResult, PageFetcher, extract_page_text
from .schema import Observation
from .web_providers import SearchAttempt, SearchProviderRegistry, SourcePolicyProvider, filter_results_by_domain


def _safe_relative_path(root: Path, value: str) -> tuple[Path | None, str]:
    root_resolved = root.resolve()
    candidate = (root_resolved / str(value or "")).resolve()
    try:
        rel = candidate.relative_to(root_resolved)
    except ValueError:
        return None, "path outside workspace"
    return candidate, rel.as_posix()


def _run_command(argv: list[str], *, cwd: Path, timeout_seconds: int = 30) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        shell=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )


class Tool(Protocol):
    name: str

    def spec(self) -> dict[str, Any]:
        ...

    def run(self, **kwargs: Any) -> Observation:
        ...


class SourceEvaluator(Protocol):
    def evaluate_source(self, *, query: str, source: dict[str, Any], page_text: str, trajectory: list[dict[str, Any]]) -> dict[str, Any]:
        ...


def compact(text: str, limit: int = 500) -> str:
    current = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(current) <= limit:
        return current
    if limit <= 3:
        return "..."
    return current[: limit - 3].rstrip() + "..."


def strip_html(raw_html: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", raw_html)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    return compact(text, 8000)


QUERY_STOP_TERMS = {
    "search",
    "find",
    "look",
    "lookup",
    "research",
    "official",
    "sources",
    "source",
    "docs",
    "documentation",
    "cite",
    "and",
    "the",
    "a",
    "an",
    "检索",
    "搜索",
    "查找",
    "查一下",
    "联网",
    "官方",
    "官网",
    "文档",
    "来源",
    "给出来源",
}


def _semantic_query_text(query: str) -> str:
    text = str(query or "")
    text = re.sub(r"^(search|look up|find|research)\s+(for\s+)?", "", text.strip(), flags=re.I)
    for term in sorted(QUERY_STOP_TERMS, key=len, reverse=True):
        text = text.replace(term, " ")
    return compact(text, 180)


def normalize_result_url(url: str) -> str:
    clean_url = html.unescape(str(url or "").strip())
    if clean_url.startswith("//"):
        clean_url = "https:" + clean_url
    if "duckduckgo.com/" in clean_url and "uddg=" in clean_url:
        parsed = parse_qs(urlparse(clean_url).query).get("uddg", [""])[0]
        if parsed:
            clean_url = unquote(parsed)
    if "bing.com/ck/" in clean_url and "u=" in clean_url:
        parsed = parse_qs(urlparse(clean_url).query).get("u", [""])[0]
        if parsed.startswith("a1"):
            encoded = parsed[2:]
            try:
                decoded = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                decoded = ""
            if decoded.startswith(("http://", "https://")):
                clean_url = decoded
            elif decoded.startswith("/"):
                clean_url = "https://www.bing.com" + decoded
    return clean_url


def _is_search_navigation_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    if host.endswith("bing.com") and (
        path.startswith("/images/")
        or path.startswith("/videos/")
        or path.startswith("/maps")
        or path.startswith("/news/")
        or path.startswith("/shop/")
        or path.startswith("/travel/")
        or path.startswith("/search")
        or path.startswith("/ck/")
    ):
        return True
    if host.endswith("duckduckgo.com") and path.startswith("/html"):
        return True
    if host.endswith("google.com") and (path.startswith("/search") or path.startswith("/xhtml/search")):
        return True
    return False


def _score_support(query: str, text: str) -> float:
    terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", _semantic_query_text(query))]
    if not terms:
        return 0.0
    lowered = text.lower()
    hits = sum(1 for term in set(terms) if term in lowered)
    return round(hits / max(1, len(set(terms))), 4)


def _fallback_source_evaluation(query: str, source: dict[str, Any], page_text: str) -> dict[str, Any]:
    score = _score_support(query, page_text)
    return {
        "accepted": score >= 0.5,
        "confidence": score,
        "reason": "fallback lexical support score",
        "support_score": score,
        "evaluator": "fallback_lexical",
    }


@dataclass(slots=True)
class TimeTool:
    name: str = "time_observe"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Observe host clock.", "input_schema": {}}

    def run(self, **kwargs: Any) -> Observation:
        from .schema import utc_now

        now = utc_now()
        return Observation(tool=self.name, status="ok", summary=now, data={"utc": now})


@dataclass(slots=True)
class WebClient:
    timeout: int = 15
    user_agent: str = "HoloAgentKernel/2.1.0"
    providers: list[Any] | None = None
    provider_timeout_seconds: float = 8.0
    network_enabled: bool = True
    page_fetcher: PageFetcher | None = None
    _registry: SearchProviderRegistry | None = None

    def fetch_text(self, url: str) -> str:
        result = (self.page_fetcher or PageFetcher(user_agent=self.user_agent)).fetch(url, timeout=self.timeout)
        if result.status != "ok":
            raise RuntimeError(result.error or result.status)
        return result.text

    def fetch_page(self, url: str) -> PageFetchResult:
        if type(self).fetch_text is not WebClient.fetch_text:
            started = time.time()
            try:
                raw = self.fetch_text(url)
            except Exception as exc:  # noqa: BLE001
                return PageFetchResult(
                    url=url,
                    final_url=url,
                    status="error",
                    error=str(exc),
                    error_type=exc.__class__.__name__,
                    elapsed_ms=int((time.time() - started) * 1000),
                )
            return PageFetchResult(
                url=url,
                final_url=url,
                status="ok",
                status_code=200,
                content_type="text/html",
                text=raw,
                bytes_read=len(raw.encode("utf-8", errors="replace")),
                elapsed_ms=int((time.time() - started) * 1000),
            )
        return (self.page_fetcher or PageFetcher(user_agent=self.user_agent)).fetch(url, timeout=self.timeout)

    def _provider_registry(self) -> SearchProviderRegistry:
        if self._registry is None:
            providers = self.providers if self.providers is not None else [SourcePolicyProvider(), _LegacySearchProvider(self)]
            self._registry = SearchProviderRegistry(
                providers,
                provider_timeout_seconds=self.provider_timeout_seconds,
                network_enabled=self.network_enabled,
            )
        return self._registry

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> list[dict[str, str]]:
        attempt = self._provider_registry().search(
            query,
            max_results=max_results,
            allowed_domains=allowed_domains,
            blocked_domains=blocked_domains,
            region=region,
        )
        if attempt.status != "ok":
            raise RuntimeError(attempt.error or attempt.status)
        return [dict(item, provider=item.get("provider", attempt.provider)) for item in attempt.results]

    def health(self) -> dict[str, Any]:
        return self._provider_registry().health()

    def _legacy_search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        urls = [
            f"https://duckduckgo.com/html/?q={quote_plus(query)}",
            f"https://www.bing.com/search?q={quote_plus(query)}",
        ]
        errors: list[str] = []
        for url in urls:
            try:
                page = self.fetch_text(url)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{urlparse(url).netloc}: {exc}")
                continue
            results = self._parse_search_results(page, max_results=max_results)
            if results:
                return results
        raise RuntimeError("; ".join(errors) or "search returned no results")

    def _parse_search_results(self, page: str, *, max_results: int) -> list[dict[str, str]]:
        results: list[dict[str, str]] = []
        for href, title in re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, flags=re.I | re.S):
            clean_title = compact(strip_html(title), 120)
            clean_url = normalize_result_url(href)
            if not clean_url.startswith("http"):
                continue
            if not clean_title or "javascript:" in clean_url or _is_search_navigation_url(clean_url):
                continue
            if clean_url in {item["url"] for item in results}:
                continue
            results.append({"title": clean_title, "url": clean_url, "snippet": ""})
            if len(results) >= max_results:
                break
        return results


@dataclass(slots=True)
class _LegacySearchProvider:
    client: WebClient
    name: str = "legacy_html"

    def search(
        self,
        query: str,
        *,
        max_results: int = 5,
        allowed_domains: list[str] | None = None,
        blocked_domains: list[str] | None = None,
        region: str | None = None,
    ) -> SearchAttempt:
        started = time.time()
        results = self.client._legacy_search(query, max_results=max_results)
        results = [{**item, "provider": self.name} for item in filter_results_by_domain(results, allowed_domains=allowed_domains, blocked_domains=blocked_domains)]
        return SearchAttempt(provider=self.name, query=query, status="ok", results=results, elapsed_ms=int((time.time() - started) * 1000))


@dataclass(slots=True)
class WebSearchTool:
    client: WebClient
    name: str = "web_search"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Search the web.", "input_schema": {"query": "string", "max_results": "integer"}}

    def run(self, **kwargs: Any) -> Observation:
        query = str(kwargs.get("query", "") or "").strip()
        if not query:
            return Observation(tool=self.name, status="error", summary="missing query", data={"query": query})
        try:
            try:
                results = self.client.search(
                    query,
                    max_results=int(kwargs.get("max_results", 5) or 5),
                    allowed_domains=[str(item) for item in kwargs.get("allowed_domains", [])] if isinstance(kwargs.get("allowed_domains"), list) else None,
                    blocked_domains=[str(item) for item in kwargs.get("blocked_domains", [])] if isinstance(kwargs.get("blocked_domains"), list) else None,
                    region=str(kwargs.get("region", "") or "") or None,
                )
            except TypeError as exc:
                if "unexpected keyword" not in str(exc):
                    raise
                results = self.client.search(query, max_results=int(kwargs.get("max_results", 5) or 5))
        except Exception as exc:  # noqa: BLE001
            return Observation(
                tool=self.name,
                status="error",
                summary=str(exc),
                data={"query": query, "results": [], "provider_health": self.client.health()},
            )
        results = [{**item, "url": normalize_result_url(item.get("url", ""))} for item in results]
        return Observation(
            tool=self.name,
            status="ok",
            summary=f"{len(results)} search results",
            data={"query": query, "results": results, "provider_health": self.client.health()},
        )


@dataclass(slots=True)
class OpenPageTool:
    client: WebClient
    name: str = "open_page"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Fetch and extract text from a URL.", "input_schema": {"url": "string"}}

    def run(self, **kwargs: Any) -> Observation:
        url = str(kwargs.get("url", "") or "").strip()
        if not url.startswith(("http://", "https://")):
            return Observation(tool=self.name, status="error", summary="invalid url", data={"url": url})
        fetch = self.client.fetch_page(url) if hasattr(self.client, "fetch_page") else PageFetchResult(url=url, final_url=url, status="ok", text=self.client.fetch_text(url))
        if fetch.status != "ok":
            return Observation(tool=self.name, status="error", summary=fetch.error or fetch.status, data={"url": url, "fetch": fetch.to_dict()})
        extracted = extract_page_text(fetch.text, url=fetch.final_url or url, content_type=fetch.content_type)
        return Observation(
            tool=self.name,
            status="ok",
            summary=compact(extracted.text, 240),
            data={"url": fetch.final_url or url, "text": extracted.text, "fetch": fetch.to_dict(), "extracted_page": extracted.to_dict()},
        )


@dataclass(slots=True)
class WebResearchTool:
    search_tool: WebSearchTool
    open_tool: OpenPageTool
    source_evaluator: SourceEvaluator | None = None
    name: str = "web_research"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Bounded continuous search -> open page -> evaluate source evidence.",
            "input_schema": {"query": "string", "max_queries": "integer", "max_pages": "integer"},
        }

    def _query_variants(self, query: str, max_queries: int) -> list[str]:
        base = _semantic_query_text(query)
        variants = [base]
        if "official" not in base.lower() and "官方" not in base:
            variants.append(base + " official sources")
        if "docs" not in base.lower() and "文档" not in base:
            variants.append(base + " documentation")
        return [item for item in variants if item][: max(1, max_queries)]

    def run(self, **kwargs: Any) -> Observation:
        query = str(kwargs.get("query", "") or "").strip()
        max_queries = int(kwargs.get("max_queries", 3) or 3)
        max_pages = int(kwargs.get("max_pages", 4) or 4)
        trajectory: list[dict[str, Any]] = []
        sources: list[dict[str, Any]] = []
        errors: list[str] = []
        opened = 0
        for q in self._query_variants(query, max_queries):
            search_obs = self.search_tool.run(query=q, max_results=max_pages)
            trajectory.append({"phase": "search", "query": q, "status": search_obs.status, "summary": search_obs.summary})
            if search_obs.status != "ok":
                errors.append(search_obs.summary)
                continue
            for result in search_obs.data.get("results", [])[:max_pages]:
                if opened >= max_pages:
                    break
                opened += 1
                source_url = normalize_result_url(result.get("url", ""))
                page_obs = self.open_tool.run(url=source_url)
                page_text = page_obs.data.get("text", "") if page_obs.status == "ok" else ""
                trajectory.append(
                    {
                        "phase": "open",
                        "url": source_url,
                        "status": page_obs.status,
                    }
                )
                if page_obs.status != "ok":
                    continue
                if self.source_evaluator is None:
                    evaluation = _fallback_source_evaluation(query, result, page_text)
                else:
                    try:
                        evaluation = self.source_evaluator.evaluate_source(
                            query=query,
                            source={**result, "url": source_url},
                            page_text=page_text,
                            trajectory=list(trajectory),
                        )
                    except Exception as exc:  # noqa: BLE001
                        evaluation = {
                            "accepted": False,
                            "confidence": 0.0,
                            "reason": f"source evaluator failed: {exc}",
                            "evaluator": self.source_evaluator.__class__.__name__,
                        }
                confidence = max(0.0, min(1.0, float(evaluation.get("confidence", 0.0) or 0.0)))
                accepted = bool(evaluation.get("accepted", False))
                trajectory.append(
                    {
                        "phase": "evaluate",
                        "url": source_url,
                        "accepted": accepted,
                        "confidence": confidence,
                        "reason": compact(evaluation.get("reason", ""), 180),
                        "evaluator": evaluation.get("evaluator") or self.source_evaluator.__class__.__name__
                        if self.source_evaluator is not None
                        else "fallback_lexical",
                    }
                )
                if accepted:
                    sources.append(
                        {
                            "title": result.get("title", ""),
                            "url": source_url,
                            "snippet": compact(page_text, 300),
                            "confidence": confidence,
                            "evaluation_reason": compact(evaluation.get("reason", ""), 180),
                        }
                    )
            if sources:
                return Observation(
                    tool=self.name,
                    status="ok",
                    summary=f"found {len(sources)} supporting sources",
                    data={"query": query, "sources": sources, "trajectory": trajectory},
                )
        return Observation(
            tool=self.name,
            status="error",
            summary=compact("; ".join(errors) or "no supporting source found", 300),
            data={"query": query, "sources": sources, "trajectory": trajectory},
        )


@dataclass(slots=True)
class WorkspaceSearchTool:
    root: Path
    name: str = "workspace_search"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Search local workspace file names and text.", "input_schema": {"query": "string"}}

    def run(self, **kwargs: Any) -> Observation:
        query = str(kwargs.get("query", "") or "").strip()
        matches: list[dict[str, Any]] = []
        started = time.time()
        for path in self.root.rglob("*"):
            if time.time() - started > 5 or len(matches) >= 50:
                break
            if not path.is_file() or ".git" in path.parts:
                continue
            rel = path.relative_to(self.root).as_posix()
            if query.lower() in rel.lower():
                matches.append({"path": rel, "kind": "path"})
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if query.lower() in text.lower():
                matches.append({"path": rel, "kind": "content"})
        return Observation(tool=self.name, status="ok", summary=f"{len(matches)} matches", data={"query": query, "matches": matches})


@dataclass(slots=True)
class FileReadTool:
    root: Path
    name: str = "file_read"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Read a UTF-8 text file inside the workspace with optional 1-based line bounds.",
            "input_schema": {"path": "string", "start_line": "integer", "end_line": "integer"},
        }

    def run(self, **kwargs: Any) -> Observation:
        path, rel = _safe_relative_path(self.root, str(kwargs.get("path", "") or ""))
        if path is None:
            return Observation(tool=self.name, status="rejected", summary=rel, data={"path": kwargs.get("path", "")})
        if not path.is_file():
            return Observation(tool=self.name, status="error", summary="file not found", data={"path": rel})
        start = max(1, int(kwargs.get("start_line", 1) or 1))
        raw_end = kwargs.get("end_line", 0)
        end = int(raw_end or 0)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        end = len(lines) if end <= 0 else min(end, len(lines))
        selected = lines[start - 1 : end] if start <= end else []
        text = "\n".join(selected)
        return Observation(
            tool=self.name,
            status="ok",
            summary=f"read {rel}:{start}-{end}",
            data={"path": rel, "start_line": start, "end_line": end, "text": text},
        )


@dataclass(slots=True)
class GitStatusTool:
    root: Path
    name: str = "git_status"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Run git status --short in the workspace.", "input_schema": {}}

    def run(self, **kwargs: Any) -> Observation:
        argv = ["git", "status", "--short"]
        try:
            result = _run_command(argv, cwd=self.root, timeout_seconds=15)
        except Exception as exc:  # noqa: BLE001
            return Observation(tool=self.name, status="error", summary=str(exc), data={"command": argv})
        status = "ok" if result.returncode == 0 else "error"
        return Observation(
            tool=self.name,
            status=status,
            summary=compact(result.stdout or result.stderr or f"exit {result.returncode}", 500),
            data={"command": argv, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )


@dataclass(slots=True)
class GitDiffTool:
    root: Path
    name: str = "git_diff"

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": "Run git diff, optionally for one workspace-relative path.", "input_schema": {"path": "string"}}

    def run(self, **kwargs: Any) -> Observation:
        requested = str(kwargs.get("path", "") or "").strip()
        argv = ["git", "diff", "--"]
        rel = ""
        if requested:
            path, rel_or_error = _safe_relative_path(self.root, requested)
            if path is None:
                return Observation(tool=self.name, status="rejected", summary=rel_or_error, data={"path": requested})
            rel = rel_or_error
            argv.append(rel)
        try:
            result = _run_command(argv, cwd=self.root, timeout_seconds=20)
        except Exception as exc:  # noqa: BLE001
            return Observation(tool=self.name, status="error", summary=str(exc), data={"command": argv, "path": rel})
        status = "ok" if result.returncode == 0 else "error"
        return Observation(
            tool=self.name,
            status=status,
            summary=compact(result.stdout or result.stderr or f"exit {result.returncode}", 500),
            data={"command": argv, "path": rel, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )


def _parse_allowed_test_command(root: Path, command: str) -> tuple[list[str] | None, str]:
    if re.search(r"(\|\||&&|[;&|<>`])", command):
        return None, "command_not_allowlisted"
    if re.match(r"\s*[A-Za-z_][A-Za-z0-9_]*=", command):
        return None, "command_not_allowlisted"
    try:
        argv = shlex.split(command, posix=os.name != "nt")
    except ValueError:
        return None, "command_not_allowlisted"
    if not argv:
        return None, "command_not_allowlisted"
    lowered = [item.lower() for item in argv]
    forbidden = {"pip", "uv", "curl", "wget", "rm", "del", "erase", "rmdir", "npm", "pnpm", "yarn"}
    if any(Path(item).name.lower() in forbidden for item in lowered):
        return None, "command_not_allowlisted"
    allowed = False
    if lowered[0] == "pytest":
        allowed = True
    elif len(lowered) >= 3 and lowered[0] in {"python", "python3"} and lowered[1:3] == ["-m", "pytest"]:
        allowed = True
    elif lowered[:2] == ["python", "scripts/check_public_release_hygiene.py"]:
        allowed = True
    elif lowered == ["git", "status", "--short"]:
        allowed = True
    elif lowered[:3] == ["git", "diff", "--"] and len(lowered) <= 4:
        allowed = True
    if not allowed:
        return None, "command_not_allowlisted"
    for item in argv[1:]:
        if item.startswith("-") or item in {"--"}:
            continue
        if "/" in item or "\\" in item or item.endswith((".py", ".txt", ".md")):
            path, error = _safe_relative_path(root, item)
            if path is None:
                return None, error
    return argv, ""


@dataclass(slots=True)
class TestRunTool:
    __test__ = False

    root: Path
    name: str = "test_run"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Run an allowlisted test/status command inside the workspace without a shell.",
            "input_schema": {"command": "string", "timeout_seconds": "integer"},
        }

    def run(self, **kwargs: Any) -> Observation:
        command = str(kwargs.get("command", "") or "")
        argv, error = _parse_allowed_test_command(self.root, command)
        if argv is None:
            return Observation(tool=self.name, status="rejected", summary=error, data={"command": command, "shell": False})
        timeout_seconds = max(1, min(300, int(kwargs.get("timeout_seconds", 60) or 60)))
        try:
            result = _run_command(argv, cwd=self.root, timeout_seconds=timeout_seconds)
        except subprocess.TimeoutExpired:
            return Observation(tool=self.name, status="error", summary="timeout", data={"command": argv, "shell": False})
        status = "ok" if result.returncode == 0 else "error"
        return Observation(
            tool=self.name,
            status=status,
            summary=compact(result.stdout or result.stderr or f"exit {result.returncode}", 500),
            data={
                "command": argv,
                "shell": False,
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        )


@dataclass(slots=True)
class ApplyPatchTool:
    root: Path
    name: str = "apply_patch"

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": "Apply a simple Begin Patch update to files inside the workspace.",
            "input_schema": {"patch_text": "string"},
        }

    def run(self, **kwargs: Any) -> Observation:
        patch_text = str(kwargs.get("patch_text", "") or "")
        match = re.search(r"(?m)^\*\*\* Update File: (.+)$", patch_text)
        if not match:
            return Observation(tool=self.name, status="rejected", summary="unsupported patch format", data={})
        target, rel = _safe_relative_path(self.root, match.group(1).strip())
        if target is None:
            return Observation(tool=self.name, status="rejected", summary=rel, data={"path": match.group(1).strip()})
        if not target.is_file():
            return Observation(tool=self.name, status="error", summary="file not found", data={"path": rel})

        minus: list[str] = []
        plus: list[str] = []
        for line in patch_text.splitlines():
            if line.startswith("---") or line.startswith("+++"):
                continue
            if line.startswith("-") and not line.startswith("***"):
                minus.append(line[1:])
            elif line.startswith("+") and not line.startswith("***"):
                plus.append(line[1:])
        if not minus:
            return Observation(tool=self.name, status="rejected", summary="patch has no removable context", data={"path": rel})
        old = "\n".join(minus) + "\n"
        new = "\n".join(plus) + "\n"
        current = target.read_text(encoding="utf-8", errors="replace")
        if old not in current:
            return Observation(tool=self.name, status="error", summary="patch context not found", data={"path": rel})
        target.write_text(current.replace(old, new, 1), encoding="utf-8")
        return Observation(tool=self.name, status="ok", summary=f"patched {rel}", data={"files_changed": [rel]})


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def specs(self) -> list[dict[str, Any]]:
        return [tool.spec() for tool in self._tools.values()]

    def run(self, name: str, arguments: dict[str, Any]) -> Observation:
        tool = self._tools.get(name)
        if not tool:
            return Observation(tool=name, status="rejected", summary="unknown tool", data={"arguments": arguments})
        return tool.run(**dict(arguments or {}))

    def web_provider_health(self) -> dict[str, Any]:
        search_tool = self._tools.get("web_search")
        client = getattr(search_tool, "client", None)
        if client is not None and hasattr(client, "health"):
            return client.health()
        return {"schema": "holo.web_provider_health.v1", "last_status": "unavailable", "providers": [], "attempts": []}

    @classmethod
    def default(cls, *, root: Path | None = None, client: WebClient | None = None, source_evaluator: SourceEvaluator | None = None) -> "ToolRegistry":
        web_client = client or WebClient()
        search = WebSearchTool(web_client)
        open_page = OpenPageTool(web_client)
        return cls(
            [
                TimeTool(),
                search,
                open_page,
                FileReadTool(root or Path.cwd()),
                WorkspaceSearchTool(root or Path.cwd()),
                GitStatusTool(root or Path.cwd()),
                GitDiffTool(root or Path.cwd()),
                TestRunTool(root or Path.cwd()),
                ApplyPatchTool(root or Path.cwd()),
            ]
        )
