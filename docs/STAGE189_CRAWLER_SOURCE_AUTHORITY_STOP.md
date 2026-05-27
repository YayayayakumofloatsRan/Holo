# Stage189 Crawler Source Authority Stop

Stage189 makes crawler stop decisions respect source authority.

Stage186/187 made Holo search and open pages. Stage188 cleaned page text. Stage189 addresses the next research-quality failure: a page can contain the right words but still be the wrong kind of source. For financial and market research, a third-party blog that repeats "10-K annual report" must not satisfy a task that requires SEC filings, company IR, or first-party disclosure.

## Change

`run_live_crawler_search()` now evaluates source authority for each web observation using Stage168. Evaluation rows include:

```text
authority_status
authority_required_family
```

When a query implies a required source family, such as financial filings, the crawler only stops as `sufficient` when both are true:

```text
page evidence is supported
source authority is sufficient
```

If page evidence is supported but authority is insufficient, the crawler records:

```text
stop_reason=authority_insufficient
```

and continues to the next query or source.

## CLI Trace

Stage153 now renders authority status in crawler evaluation lines:

```text
[crawl:evaluate] status=supported score=... stop=... authority=sufficient
```

This is public audit metadata, not hidden reasoning.

## Boundary

Stage189 does not add provider calls, memory writes, WeChat startup, transport changes, unbounded crawler loops, or hidden reasoning exposure.
