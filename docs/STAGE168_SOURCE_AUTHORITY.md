# Stage168 Source Authority

Stage168 adds a reusable source-authority registry and evaluator for Holo's search evidence chain. It answers a stricter question than citation formatting:

```text
Is this the right kind of source for the research task?
```

This matters for the long-term market-research target. A cited blog post is not enough for a filing question; SEC filings, company investor-relations pages, official API docs, source repositories, package registries, and news sources have different authority roles.

## Schemas

```text
holo.stage168.source_authority.v1
holo.stage168.source_authority_report.v1
holo.stage168.source_authority_audit.v1
```

## Source Families

Stage168 currently classifies:

- `financial_filing`: SEC EDGAR filing pages and filing-like regulatory sources
- `company_ir`: company investor-relations and disclosure pages
- `official_docs`: first-party product/developer documentation
- `api_docs`: first-party API documentation
- `code_repository`: source repositories such as GitHub
- `package_registry`: package registry pages such as npm or PyPI
- `news`: recognized journalistic or market-news sources
- `unclassified`: low-authority or unknown third-party pages

Each classification includes:

```text
source_family
authority_tier: primary | official | secondary | low | blocked
source_role
is_first_party
risk_flags
confidence
```

## Runtime Integration

`stage151_tool_decision_loop.execute_tool_decision()` now attaches `source_authority` to successful `web_search` observation rows after page evidence and source synthesis have been built.

This keeps the runtime evidence path:

```text
web_search -> search_evidence -> page_evidence -> source_synthesis -> source_authority
```

## CLI

```powershell
python -m holo_host run-source-authority-audit --output artifacts\stage168\stage168_source_authority.html --dry-run
```

The audit writes HTML, JSON, and JSONL artifacts.

## Boundary

Stage168 is deterministic host-side evidence control. It does not add provider model calls, memory writes, WeChat starts, transport widening, hidden reasoning exposure, or a new tool authority path.
