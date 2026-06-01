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
