from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.extract import extract_spans, readable_document_text


def test_phase96_html_extraction_prefers_readable_body_over_raw_markup() -> None:
    document = FetchedDocument(
        document_id="doc-html",
        goal_id="goal-html",
        source_id="src-html",
        uri="https://docs.example.com/auth",
        title="DeepSeek API Docs",
        artifact_id="artifact-html",
        payload_hash="hash-html",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "text/html"},
    )
    body = _docusaurus_like_html()

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-html",
            query="DeepSeek API models authentication",
            max_spans_per_document=2,
        ),
        document=document,
        body=body,
    )

    assert mode == "html_readable_text"
    assert "do not use script text" not in text
    assert "<title" not in text
    assert spans
    assert spans[0].metadata["text_mode"] == "html_readable_text"
    assert "deepseek-chat" in spans[0].text
    assert "Authorization header" in spans[0].text
    assert "<script" not in spans[0].text


def test_phase96_retrieval_journals_readable_html_evidence_but_artifacts_keep_raw_body() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    source = SearchSource(
        source_id="src-docs",
        uri="https://docs.example.com/auth",
        title="DeepSeek API Docs",
        snippet="Models and authentication",
        provider="fake_search",
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"DeepSeek API models authentication": [source]}),
        fetch_provider=FakeFetchProvider({source.uri: {"status": "ok", "body": _docusaurus_like_html(), "mime_type": "text/html"}}),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-docs",
            query="DeepSeek API models authentication",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=2,
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-docs",
        run_id="run-docs",
    )

    assert report.status == "sufficient"
    evidence = journal.records(task_id="task-docs", kind="retrieval_evidence")[0].data
    extraction = journal.records(task_id="task-docs", kind="retrieval_extraction")[0].data
    artifact_payload = artifacts.read_blob(report.artifact_refs[0])
    assert isinstance(artifact_payload, str)
    assert "<script>do not use script text" in artifact_payload
    assert evidence["text"].find("deepseek-chat") >= 0
    assert "Authorization header" in evidence["text"]
    assert "<title" not in evidence["text"]
    assert extraction["diagnostics"]["text_modes"] == ["html_readable_text"]


def test_phase96_pdf_extraction_reads_text_literals_without_pdf_dependency() -> None:
    document = FetchedDocument(
        document_id="doc-pdf",
        goal_id="goal-pdf",
        source_id="src-pdf",
        uri="https://reports.example.com/aapl-annual-report.pdf",
        title="AAPL Annual Report PDF",
        artifact_id="artifact-pdf",
        payload_hash="hash-pdf",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "application/pdf"},
    )
    body = _text_pdf_like_body()

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-pdf",
            query="AAPL revenue operating margin services",
            max_spans_per_document=2,
        ),
        document=document,
        body=body,
    )

    assert mode == "pdf_text_literals"
    assert "AAPL 2024 annual report revenue" in text
    assert "operating margin improved" in text.lower()
    assert spans
    assert spans[0].metadata["text_mode"] == "pdf_text_literals"
    assert "services revenue" in spans[0].text


def test_phase96_retrieval_journals_pdf_text_evidence_but_artifacts_keep_raw_pdf() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    source = SearchSource(
        source_id="src-aapl-pdf",
        uri="https://reports.example.com/aapl-annual-report.pdf",
        title="AAPL Annual Report PDF",
        snippet="Annual report PDF",
        provider="fake_search",
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"AAPL revenue operating margin services": [source]}),
        fetch_provider=FakeFetchProvider(
            {source.uri: {"status": "ok", "body": _text_pdf_like_body(), "mime_type": "application/pdf"}}
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-pdf-doc",
            query="AAPL revenue operating margin services",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=2,
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-pdf",
        run_id="run-pdf",
    )

    assert report.status == "sufficient"
    evidence = journal.records(task_id="task-pdf", kind="retrieval_evidence")[0].data
    extraction = journal.records(task_id="task-pdf", kind="retrieval_extraction")[0].data
    artifact_payload = artifacts.read_blob(report.artifact_refs[0])
    assert isinstance(artifact_payload, str)
    assert artifact_payload.startswith("%PDF-1.4")
    assert evidence["text"].find("services revenue") >= 0
    assert "BT (" not in evidence["text"]
    assert extraction["diagnostics"]["text_modes"] == ["pdf_text_literals"]


def test_phase96_json_extraction_flattens_sec_companyfacts_for_evidence() -> None:
    document = FetchedDocument(
        document_id="doc-json",
        goal_id="goal-json",
        source_id="src-json",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        title="SEC companyfacts JSON",
        artifact_id="artifact-json",
        payload_hash="hash-json",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "application/json"},
    )
    body = _sec_companyfacts_json()

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-json",
            query="AAPL revenue 10-K companyfacts",
            max_spans_per_document=2,
        ),
        document=document,
        body=body,
    )

    assert mode == "json_readable_text"
    assert "entityName=Apple Inc." in text
    assert "Revenues.units.USD[0]:" in text
    assert "val=391035000000" in text
    assert "form=10-K" in text
    assert spans
    assert spans[0].metadata["text_mode"] == "json_readable_text"
    assert "companyfacts" in spans[0].text.lower() or "Revenues" in spans[0].text


def test_phase96_csv_extraction_flattens_finance_rows_for_evidence() -> None:
    document = FetchedDocument(
        document_id="doc-csv",
        goal_id="goal-csv",
        source_id="src-csv",
        uri="https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCSL",
        title="FRED CPI CSV",
        artifact_id="artifact-csv",
        payload_hash="hash-csv",
        preview="",
        size_bytes=0,
        metadata={"mime_type": "text/csv"},
    )
    body = "DATE,CPIAUCSL,source\n2024-09-01,315.301,FRED CPI inflation series\n"

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(
            goal_id="goal-csv",
            query="FRED CPI inflation 2024",
            max_spans_per_document=2,
        ),
        document=document,
        body=body,
    )

    assert mode == "csv_readable_text"
    assert "csv_header: DATE CPIAUCSL source" in text
    assert "csv_row_1: DATE=2024-09-01 CPIAUCSL=315.301 source=FRED CPI inflation series" in text
    assert spans
    assert spans[0].metadata["text_mode"] == "csv_readable_text"
    assert "FRED CPI inflation series" in spans[0].text


def test_phase96_retrieval_journals_structured_json_evidence_but_artifacts_keep_raw_json() -> None:
    journal = JournalStore.in_memory()
    artifacts = ArtifactStore.in_memory()
    source = SearchSource(
        source_id="src-companyfacts",
        uri="https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
        title="SEC companyfacts JSON",
        snippet="Official SEC XBRL companyfacts JSON.",
        provider="fake_search",
    )
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({"AAPL revenue 10-K companyfacts": [source]}),
        fetch_provider=FakeFetchProvider(
            {source.uri: {"status": "ok", "body": _sec_companyfacts_json(), "mime_type": "application/json"}}
        ),
    )

    report = operator.run(
        SearchGoal(
            goal_id="goal-json-doc",
            query="AAPL revenue 10-K companyfacts",
            max_sources=1,
            max_fetches=1,
            max_spans_per_document=2,
        ),
        journal=journal,
        artifact_store=artifacts,
        task_id="task-json",
        run_id="run-json",
    )

    assert report.status == "sufficient"
    evidence = journal.records(task_id="task-json", kind="retrieval_evidence")[0].data
    extraction = journal.records(task_id="task-json", kind="retrieval_extraction")[0].data
    artifact_payload = artifacts.read_blob(report.artifact_refs[0])
    assert isinstance(artifact_payload, str)
    assert '"entityName": "Apple Inc."' in artifact_payload
    assert evidence["text"].find("Revenues") >= 0
    assert extraction["diagnostics"]["text_modes"] == ["json_readable_text"]


def _docusaurus_like_html() -> str:
    return """
    <!doctype html>
    <html>
      <head>
        <title>DeepSeek API Docs</title>
        <script>do not use script text: authentication fake script value</script>
        <style>.hidden { display: none; }</style>
      </head>
      <body>
        <nav>DeepSeek API Docs Navigation Pricing Token Usage</nav>
        <main>
          <article>
            <h1>Models and Authentication</h1>
            <p>Models include deepseek-chat and deepseek-reasoner for API requests.</p>
            <p>Authentication uses the Authorization header with a Bearer token supplied by the host.</p>
          </article>
        </main>
      </body>
    </html>
    """


def _text_pdf_like_body() -> str:
    return (
        "%PDF-1.4\n"
        "1 0 obj << /Type /Page >> endobj\n"
        "stream\n"
        "BT (AAPL 2024 annual report revenue evidence from the official PDF) Tj\n"
        "[(Operating margin improved and services revenue grew year over year)] TJ\n"
        "ET\n"
        "endstream\n"
        "%%EOF"
    )


def _sec_companyfacts_json() -> str:
    return """
    {
      "cik": 320193,
      "entityName": "Apple Inc.",
      "facts": {
        "us-gaap": {
          "Revenues": {
            "label": "Revenue",
            "units": {
              "USD": [
                {
                  "fy": 2024,
                  "fp": "FY",
                  "form": "10-K",
                  "filed": "2024-11-01",
                  "frame": "CY2024",
                  "val": 391035000000
                }
              ]
            }
          }
        }
      }
    }
    """
