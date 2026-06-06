import json

from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.retrieval import FakeFetchProvider, FakeSearchProvider, RetrievalOperator, SearchGoal, SearchSource
from kernel_v3.retrieval.contracts import FetchedDocument
from kernel_v3.retrieval.extract import extract_spans, readable_document_text


def test_phase116_arxiv_atom_metadata_becomes_paper_level_text() -> None:
    document = _document(
        uri="https://export.arxiv.org/api/query?search_query=all%3Ahyperbolic+dynamics",
        title="arXiv API results",
        mime_type="application/atom+xml",
        source_kind="scholarly_preprint",
    )
    body = """
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Recent advances in hyperbolic dynamics</title>
        <summary>This paper surveys frontier research and open problems in hyperbolic dynamics.</summary>
        <id>https://arxiv.org/abs/2601.00001</id>
        <published>2026-01-01T00:00:00Z</published>
        <author><name>Ada Researcher</name></author>
        <category term="math.DS" />
      </entry>
    </feed>
    """

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-arxiv", query="hyperbolic dynamics frontier open problems", max_spans_per_document=2),
        document=document,
        body=body,
    )

    assert mode == "arxiv_atom_readable_text"
    assert "scholarly_work source=arXiv" in text
    assert "Recent advances in hyperbolic dynamics" in text
    assert "<entry" not in text
    assert spans
    assert spans[0].metadata["text_mode"] == "arxiv_atom_readable_text"
    assert "open problems in hyperbolic dynamics" in spans[0].text


def test_phase116_openalex_metadata_ranks_relevant_record_not_neighbor_noise() -> None:
    document = _document(
        uri="https://api.openalex.org/works?search=hyperbolic+dynamics",
        title="OpenAlex works API results",
        mime_type="application/json",
        source_kind="scholarly_index_metadata",
    )
    body = json.dumps(
        {
            "results": [
                {
                    "display_name": "A frontier research review of sprint science",
                    "publication_year": 2026,
                    "abstract_inverted_index": {
                        "This": [0],
                        "paper": [1],
                        "surveys": [2],
                        "recent": [3],
                        "frontier": [4],
                        "research": [5],
                        "in": [6],
                        "sports": [7],
                    },
                    "authorships": [{"raw_author_name": "Irrelevant Author"}],
                    "id": "https://openalex.org/W0",
                },
                {
                    "display_name": "Frontier questions in hyperbolic dynamics",
                    "publication_year": 2025,
                    "abstract_inverted_index": {
                        "Recent": [0],
                        "work": [1],
                        "on": [2],
                        "hyperbolic": [3],
                        "dynamics": [4],
                        "studies": [5],
                        "frontier": [6],
                        "open": [7],
                        "problems": [8],
                    },
                    "authorships": [{"raw_author_name": "Dynamical Systems Group"}],
                    "ids": {"doi": "https://doi.org/10.1000/hypdyn"},
                    "cited_by_count": 42,
                    "primary_location": {"source": {"display_name": "Ergodic Theory Journal"}},
                    "concepts": [{"display_name": "Dynamical systems"}, {"display_name": "Mathematics"}],
                    "id": "https://openalex.org/W1",
                },
            ]
        }
    )

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-openalex", query="hyperbolic dynamics frontier open problems", max_spans_per_document=2),
        document=document,
        body=body,
    )

    assert mode == "openalex_readable_text"
    assert "scholarly_work source=OpenAlex" in text
    assert "Frontier questions in hyperbolic dynamics" in text
    assert spans
    joined = " ".join(span.text for span in spans)
    assert "Frontier questions in hyperbolic dynamics" in joined
    assert "sprint science" not in joined


def test_phase116_empty_scholarly_feed_does_not_create_header_only_evidence() -> None:
    document = _document(
        uri="https://export.arxiv.org/api/query?search_query=all%3Amissing",
        title="arXiv API empty results",
        mime_type="application/atom+xml",
        source_kind="scholarly_preprint",
    )
    body = '<feed xmlns="http://www.w3.org/2005/Atom"></feed>'

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-empty-arxiv", query="hyperbolic dynamics arxiv recent papers", max_spans_per_document=2),
        document=document,
        body=body,
    )

    assert mode == "arxiv_atom_readable_text"
    assert "record_count=0" in text
    assert spans == []


def test_phase116_crossref_metadata_strips_jats_markup_and_keeps_doi() -> None:
    document = _document(
        uri="https://api.crossref.org/works?query.bibliographic=hyperbolic+dynamics",
        title="Crossref works API results",
        mime_type="application/json",
        source_kind="scholarly_index_metadata",
    )
    body = json.dumps(
        {
            "message": {
                "items": [
                    {
                        "title": ["Hyperbolic dynamics and stable manifolds"],
                        "abstract": "<jats:p>This article surveys frontier research in hyperbolic dynamics.</jats:p>",
                        "DOI": "10.5555/hypdyn.2026",
                        "URL": "https://doi.org/10.5555/hypdyn.2026",
                        "container-title": ["Journal of Dynamical Systems"],
                        "issued": {"date-parts": [[2026, 4, 1]]},
                        "author": [{"given": "Noether", "family": "Example"}],
                    }
                ]
            }
        }
    )

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-crossref", query="hyperbolic dynamics DOI frontier research", max_spans_per_document=2),
        document=document,
        body=body,
    )

    assert mode == "crossref_readable_text"
    assert "doi=10.5555/hypdyn.2026" in text
    assert "<jats" not in text
    assert spans
    assert "Hyperbolic dynamics and stable manifolds" in spans[0].text


def test_phase116_semantic_scholar_metadata_preserves_abstract_and_pdf_url() -> None:
    document = _document(
        uri="https://api.semanticscholar.org/graph/v1/paper/search?query=hyperbolic+dynamics",
        title="Semantic Scholar paper search API results",
        mime_type="application/json",
        source_kind="scholarly_index_metadata",
    )
    body = json.dumps(
        {
            "data": [
                {
                    "paperId": "paper-1",
                    "title": "Open problems for hyperbolic dynamics",
                    "abstract": "A survey of recent papers, frontier research, and open problems in hyperbolic dynamics.",
                    "year": 2026,
                    "url": "https://www.semanticscholar.org/paper/paper-1",
                    "authors": [{"name": "Example Scholar"}],
                    "citationCount": 17,
                    "externalIds": {"DOI": "10.7777/semantic.hypdyn", "ArXiv": "2601.00001"},
                    "openAccessPdf": {"url": "https://arxiv.org/pdf/2601.00001"},
                }
            ]
        }
    )

    text, mode = readable_document_text(body, document=document)
    spans = extract_spans(
        goal=SearchGoal(goal_id="goal-semantic", query="hyperbolic dynamics recent papers open problems", max_spans_per_document=2),
        document=document,
        body=body,
    )

    assert mode == "semantic_scholar_readable_text"
    assert "Open problems for hyperbolic dynamics" in text
    assert "https://arxiv.org/pdf/2601.00001" in text
    assert spans
    assert "frontier research" in spans[0].text


def test_phase116_operator_preserves_source_metadata_for_scholarly_extraction() -> None:
    query = "hyperbolic dynamics frontier open problems"
    source = SearchSource(
        source_id="openalex-src",
        uri="https://api.openalex.org/works?search=hyperbolic+dynamics",
        title="OpenAlex works API results",
        snippet="Scholarly metadata for hyperbolic dynamics.",
        provider="fixture",
        metadata={
            "source_kind": "scholarly_index_metadata",
            "source_family": "scholarly_index",
            "authority_level": "secondary",
            "discovery_action": "query_openalex_api",
        },
    )
    body = json.dumps(
        {
            "results": [
                {
                    "display_name": "Frontier research in hyperbolic dynamics",
                    "publication_year": 2025,
                    "abstract_inverted_index": {
                        "Hyperbolic": [0],
                        "dynamics": [1],
                        "research": [2],
                        "identifies": [3],
                        "frontier": [4],
                        "open": [5],
                        "problems": [6],
                    },
                    "authorships": [{"raw_author_name": "Research Group"}],
                    "id": "https://openalex.org/W123",
                }
            ]
        }
    )
    journal = JournalStore.in_memory()
    operator = RetrievalOperator(
        search_provider=FakeSearchProvider({query: [source]}),
        fetch_provider=FakeFetchProvider({source.uri: {"status": "ok", "body": body, "mime_type": "application/json"}}),
    )

    report = operator.run(
        SearchGoal(goal_id="goal-operator-openalex", query=query, max_sources=1, max_fetches=1, max_spans_per_document=2),
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        task_id="task-operator-openalex",
        run_id="run-operator-openalex",
    )

    extraction = journal.records(task_id="task-operator-openalex", kind="retrieval_extraction")[0].data
    evidence = journal.records(task_id="task-operator-openalex", kind="retrieval_evidence")[0].data

    assert report.status == "sufficient"
    assert extraction["diagnostics"]["text_modes"] == ["openalex_readable_text"]
    assert extraction["document"]["metadata"]["source_metadata"]["source_kind"] == "scholarly_index_metadata"
    assert "Frontier research in hyperbolic dynamics" in evidence["text"]


def _document(*, uri: str, title: str, mime_type: str, source_kind: str) -> FetchedDocument:
    return FetchedDocument(
        document_id="doc-scholarly",
        goal_id="goal-scholarly",
        source_id="src-scholarly",
        uri=uri,
        title=title,
        artifact_id="artifact-scholarly",
        payload_hash="hash-scholarly",
        preview="",
        size_bytes=0,
        metadata={"mime_type": mime_type, "source_metadata": {"source_kind": source_kind}},
    )
