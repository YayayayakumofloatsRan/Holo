from __future__ import annotations

import hashlib
import urllib.parse
import xml.etree.ElementTree as ET

from kernel_v3.contracts import JsonObject
from kernel_v3.research import ACADEMIC_RESEARCH_PROFILE_ID
from kernel_v3.retrieval.contracts import QueryPlan, SearchGoal, SearchSource
from kernel_v3.retrieval.http_provider import HttpTransport, HttpTransportResponse


ARXIV_API_ENDPOINT = "https://export.arxiv.org/api/query"
ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivApiSearchProvider:
    provider_id = "arxiv_api_search"
    live_network = True
    default_enabled = True
    profile_aware = True
    supported_research_profiles = [ACADEMIC_RESEARCH_PROFILE_ID]

    def __init__(
        self,
        *,
        timeout_seconds: int = 20,
        max_bytes: int = 1_000_000,
        max_results: int = 25,
        transport: HttpTransport | None = None,
    ) -> None:
        self.timeout_seconds = max(1, int(timeout_seconds))
        self.max_bytes = max(1, int(max_bytes))
        self.max_results = max(1, min(int(max_results), 100))
        self.transport = transport or _urllib_transport
        self._last_search_diagnostics: JsonObject = {}
        self.capability_diagnostics = {
            "source": "arxiv_api_search",
            "endpoint_host": "export.arxiv.org",
            "allowed_host_count": 2,
            "allowed_hosts": ["export.arxiv.org", "arxiv.org"],
            "allow_all_hosts": False,
            "timeout_seconds": self.timeout_seconds,
            "max_bytes": self.max_bytes,
            "max_results": self.max_results,
        }

    def search(self, query: str, *, goal: SearchGoal, plan: QueryPlan) -> list[SearchSource]:
        if _research_profile_id(goal.metadata) != ACADEMIC_RESEARCH_PROFILE_ID:
            self._last_search_diagnostics = {
                "status": "empty",
                "reason": "non_academic_research_profile",
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        url = _query_url(query, max_results=min(self.max_results, max(1, int(goal.max_sources))))
        headers = {
            "User-Agent": "holo-kernel-v3/1.0 (academic retrieval; contact: local)",
            "Accept": "application/atom+xml, application/xml, text/xml",
        }
        try:
            response = self.transport(url, headers, self.timeout_seconds, self.max_bytes)
        except Exception as exc:  # pragma: no cover - urllib transport normalizes common errors.
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_transport_error",
                "error": type(exc).__name__,
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        if response.status_code < 200 or response.status_code >= 300:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_status_error",
                "status_code": response.status_code,
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        if len(response.body) > self.max_bytes:
            self._last_search_diagnostics = {
                "status": "failed",
                "reason": "http_body_too_large",
                "max_bytes": self.max_bytes,
                "query_hash": _hash(query),
                "plan_id": plan.plan_id,
            }
            return []
        sources = _sources_from_atom(
            response.body.decode("utf-8", errors="replace"),
            query=query,
            max_sources=goal.max_sources,
        )
        self._last_search_diagnostics = {
            "status": "ok" if sources else "empty",
            "source_count": len(sources),
            "status_code": response.status_code,
            "byte_count": len(response.body),
            "query_hash": _hash(query),
            "plan_id": plan.plan_id,
        }
        return sources

    def search_diagnostics(self) -> JsonObject:
        return dict(self._last_search_diagnostics)


def _sources_from_atom(body: str, *, query: str, max_sources: int) -> list[SearchSource]:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []
    sources: list[SearchSource] = []
    for entry in root.findall(f"{ATOM_NS}entry"):
        raw_id = _text(entry, "id")
        abs_url = _normalize_abs_url(raw_id)
        if not abs_url:
            continue
        title = _compact(_text(entry, "title"))
        summary = _compact(_text(entry, "summary"))
        published = _text(entry, "published")
        updated = _text(entry, "updated")
        authors = [_compact(author.findtext(f"{ATOM_NS}name") or "") for author in entry.findall(f"{ATOM_NS}author")]
        arxiv_id = abs_url.rstrip("/").rsplit("/", 1)[-1]
        source_id = f"{ArxivApiSearchProvider.provider_id}-{_hash(abs_url)[:12]}"
        sources.append(
            SearchSource(
                source_id=source_id,
                uri=abs_url,
                title=title or f"arXiv paper {arxiv_id}",
                snippet=_compact(
                    " ".join(
                        item
                        for item in [
                            f"arXiv:{arxiv_id}",
                            f"authors: {', '.join(authors[:6])}" if authors else "",
                            f"published: {published[:10]}" if published else "",
                            summary,
                        ]
                        if item
                    )
                )[:1000],
                provider=ArxivApiSearchProvider.provider_id,
                metadata={
                    "research_profile": ACADEMIC_RESEARCH_PROFILE_ID,
                    "source_family": "scholarly_preprint",
                    "authority_level": "primary",
                    "source_kind": "scholarly_preprint",
                    "arxiv_id": arxiv_id,
                    "authors": authors[:12],
                    "published": published,
                    "updated": updated,
                    "query_hash": _hash(query),
                },
            )
        )
        if len(sources) >= max(0, int(max_sources)):
            break
    return sources


def _query_url(query: str, *, max_results: int) -> str:
    params = {
        "search_query": _arxiv_search_expression(query),
        "start": "0",
        "max_results": str(max_results),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{ARXIV_API_ENDPOINT}?{urllib.parse.urlencode(params)}"


def _arxiv_search_expression(query: str) -> str:
    terms = _focus_terms(query)
    if not terms:
        return f"all:{query}"
    if len(terms) >= 2:
        return f'all:"{" ".join(terms[: min(3, len(terms))])}"'
    return " AND ".join(f"all:{term}" for term in terms[:5])


def _focus_terms(query: str) -> list[str]:
    raw = [
        item.strip().lower()
        for item in query.replace("-", " ").replace("_", " ").split()
        if item.strip()
    ]
    terms: list[str] = []
    seen: set[str] = set()
    for term in raw:
        cleaned = "".join(ch for ch in term if ch.isalnum())
        if len(cleaned) < 4 or cleaned in _ARXIV_QUERY_STOPWORDS or cleaned.isdigit():
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        terms.append(cleaned)
    return terms


def _text(entry: ET.Element, tag: str) -> str:
    return str(entry.findtext(f"{ATOM_NS}{tag}") or "").strip()


def _normalize_abs_url(raw: str) -> str:
    if not raw:
        return ""
    parsed = urllib.parse.urlparse(raw.strip())
    if not parsed.hostname or parsed.hostname.lower() not in {"arxiv.org", "www.arxiv.org"}:
        return ""
    path = parsed.path.rstrip("/")
    if not path.startswith("/abs/"):
        return ""
    return f"https://arxiv.org{path}"


def _compact(text: str) -> str:
    return " ".join(str(text or "").split())


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _research_profile_id(metadata: JsonObject) -> str | None:
    for key in ("research_profile_id", "research_profile"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = metadata.get("metadata")
    if isinstance(nested, dict):
        return _research_profile_id(nested)
    return None


_ARXIV_QUERY_STOPWORDS = {
    "academic",
    "advance",
    "advances",
    "article",
    "frontier",
    "frontiers",
    "journal",
    "latest",
    "literature",
    "paper",
    "papers",
    "preprint",
    "recent",
    "research",
    "review",
    "scholarly",
    "state",
    "survey",
}


def _urllib_transport(url: str, headers: dict[str, str], timeout_seconds: int, max_bytes: int) -> HttpTransportResponse:
    from kernel_v3.retrieval.http_provider import _urllib_transport as transport

    return transport(url, headers, timeout_seconds, max_bytes)
