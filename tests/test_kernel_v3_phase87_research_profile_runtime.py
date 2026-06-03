import json
import subprocess
import sys
from pathlib import Path

from kernel_v3.agent import AgentRuntime
from kernel_v3.chat import ChatRuntime
from kernel_v3.journal import JournalStore
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.research import FINANCE_FUNDAMENTALS_PROFILE_ID, TECHNICAL_DOCUMENTATION_PROFILE_ID
from kernel_v3.resident import ResidentQueue, ResidentRuntime


def test_phase87_agent_execution_metadata_applies_research_profile_to_retrieval() -> None:
    journal = JournalStore.in_memory()

    result = AgentRuntime(journal=journal).run(
        "AAPL 2024 revenue",
        mode="retrieval",
        execution_metadata={"retrieval": {"metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}}},
    )

    action = journal.records(task_id=result.task_id, kind="action")[0].data
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[-1].data
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert action["payload"]["max_queries"] == 128
    assert action["payload"]["max_sources"] == 5000
    assert action["payload"]["max_fetches"] == 2048
    context = journal.records(task_id=result.task_id, kind="context")[0].data
    capability = context["state"]["retrieval_capability_state"]
    assert capability["available"] is True
    assert capability["network_budget_available"] is False
    assert "fallback_search" in capability["search_provider_ids"]
    assert "sec_edgar_structured_search" in capability["search_provider_ids"]
    assert capability["profile_aware_search_available"] is True
    assert report["diagnostics"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert report["diagnostics"]["reason"] == "insufficient_evidence"
    assert report["diagnostics"]["provider_capabilities"][0]["provider_id"] == "fallback_search"
    assert journal.records(task_id=result.task_id, kind="retrieval_source_assessment")


def test_phase87_chat_runtime_carries_research_profile_into_agent_tasks() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _retrieval_intake()}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        execution_metadata={"retrieval": {"metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}}},
    )

    result = chat.receive("research AAPL revenue", thread_id="thread-research-profile")

    action = journal.records(task_id=result.task_id, kind="action")[0].data
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert journal.records(task_id=result.task_id, kind="retrieval_source_assessment")


def test_phase87_model_intake_technical_capability_selects_technical_profile() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _technical_docs_intake()}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
    )

    result = chat.receive("检索DeepSeek API鉴权和endpoint", thread_id="thread-technical-docs-profile")

    action = journal.records(task_id=result.task_id, kind="action")[0].data
    metadata = action["payload"]["metadata"]
    assert metadata["research_profile"] == TECHNICAL_DOCUMENTATION_PROFILE_ID
    assert metadata["research_task_kind"] == "api_documentation"
    assert metadata["source_authority_requirement"] == "primary"
    assert action["payload"]["max_queries"] == 32
    assert action["payload"]["max_sources"] == 500
    assert action["payload"]["max_fetches"] == 128
    report = journal.records(task_id=result.task_id, kind="retrieval_report")[-1].data
    assert report["diagnostics"]["research_profile"] == TECHNICAL_DOCUMENTATION_PROFILE_ID
    providers = report["diagnostics"]["provider_capabilities"][0]["diagnostics"]["providers"]
    assert any(item["provider_id"] == "research_source_directory_search" for item in providers)


def test_phase87_model_intake_technical_intent_kind_selects_technical_profile() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _technical_docs_intake_without_profile_capability()}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
    )

    result = chat.receive("检索DeepSeek API鉴权和endpoint", thread_id="thread-technical-docs-intent-kind")

    action = journal.records(task_id=result.task_id, kind="action")[0].data
    metadata = action["payload"]["metadata"]
    assert metadata["research_profile"] == TECHNICAL_DOCUMENTATION_PROFILE_ID
    assert metadata["research_task_kind"] == "technical_documentation"
    assert action["payload"]["max_queries"] == 32


def test_phase87_resident_runtime_carries_research_profile_into_agent_tasks(tmp_path: Path) -> None:
    queue = ResidentQueue(tmp_path / "resident.sqlite", clock_ms=_clock())
    journal = JournalStore.in_memory()
    fabric = fake_fabric({"semantic.intake": _retrieval_intake()}, journal=journal)
    chat = ChatRuntime(
        journal=journal,
        agent_runtime=AgentRuntime(journal=journal, processor_fabric=fabric),
        semantic_mode="model",
        execution_metadata={"retrieval": {"metadata": {"research_profile": FINANCE_FUNDAMENTALS_PROFILE_ID}}},
    )
    queue.enqueue(thread_id="resident-research-profile", text="research AAPL revenue", message_id="in-research-profile")

    result = ResidentRuntime(queue=queue, chat_runtime=chat, worker_id="worker-research-profile", journal=journal).run_once()

    outbox = queue.outbox_messages()[0]
    action = journal.records(task_id=outbox.task_id, kind="action")[0].data
    assert result.status == "processed"
    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert journal.records(task_id=outbox.task_id, kind="retrieval_source_assessment")


def test_phase87_cli_agent_exposes_research_profile_flag(tmp_path: Path) -> None:
    journal_path = tmp_path / "journal.jsonl"
    index_path = tmp_path / "journal.sqlite"

    payload = json.loads(
        _run_cli(
            "--journal",
            str(journal_path),
            "--index",
            str(index_path),
            "agent",
            "--offline",
            "AAPL 2024 revenue",
            "--research-profile",
            FINANCE_FUNDAMENTALS_PROFILE_ID,
            "--research-depth",
            "deep",
        ).stdout
    )
    journal = JournalStore(journal_path, index_path=index_path)
    action = journal.records(task_id=payload["task_id"], kind="action")[0].data
    report = journal.records(task_id=payload["task_id"], kind="retrieval_report")[-1].data

    assert action["payload"]["metadata"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert action["payload"]["metadata"]["research_depth"] == "deep"
    assert action["payload"]["max_queries"] == 128
    assert action["payload"]["max_fetches"] == 2048
    assert report["diagnostics"]["research_profile"] == FINANCE_FUNDAMENTALS_PROFILE_ID
    assert report["diagnostics"]["reason"] == "insufficient_evidence"
    assert report["diagnostics"]["provider_capabilities"][0]["provider_id"] == "fallback_search"


def _retrieval_intake() -> dict[str, object]:
    return {
        "primary_intent": "retrieval_research",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "retrieval_research",
                "text": "research AAPL revenue",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _technical_docs_intake() -> dict[str, object]:
    return {
        "primary_intent": "api_documentation",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "api_documentation",
                "text": "检索DeepSeek API鉴权和endpoint",
                "sequence_index": 1,
                "required_capabilities": ["technical.api_documentation"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _technical_docs_intake_without_profile_capability() -> dict[str, object]:
    return {
        "primary_intent": "technical_documentation_research",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "technical_documentation_research",
                "text": "检索DeepSeek API鉴权和endpoint",
                "sequence_index": 1,
                "required_capabilities": ["retrieval.run"],
                "risk": "read",
                "status": "ready",
                "metadata": {},
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _clock(start: int = 1_000):
    current = start

    def tick() -> int:
        nonlocal current
        current += 1
        return current

    return tick


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "kernel_v3.cli", *args],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
