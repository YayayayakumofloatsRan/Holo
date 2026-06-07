from kernel_v3.agent import AgentRuntime
from kernel_v3.agent.answer_profile import infer_answer_profile
from kernel_v3.agent.contracts import AgentRuntimeResult, SemanticIntake
from kernel_v3.agent.runtime import task_recipe
from kernel_v3.chat.runtime import _pending_memory_proposals
from kernel_v3.context import ArtifactStore
from kernel_v3.journal import JournalStore
from kernel_v3.memory import MemoryStore
from kernel_v3.mission import MissionSupervisor
from kernel_v3.processors.testing import fake_fabric
from kernel_v3.retrieval import DirectUrlSearchProvider, FakeFetchProvider, RetrievalOperator


SEC_URL = "https://www.sec.gov/Archives/edgar/data/320193/aapl-20240928.htm"


def test_phase109_detailed_research_short_synthesis_is_not_finalized() -> None:
    journal = JournalStore.in_memory()
    fabric = fake_fabric(
        {
            "semantic.intake": _finance_detail_intake("去调查一下 AAPL 的基本面信息，写详细报告"),
            "synthesizer.answer": {
                "answer": "AAPL 有营收和利润信息，但这里先给简短摘要。",
                "citation_refs": ["cite-evidence-span-doc-goal-plan-1-1-1-1"],
                "confidence": 0.84,
                "limitations": [],
                "used_evidence": ["evidence-span-doc-goal-plan-1-1-1-1"],
            },
        },
        journal=journal,
    )
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=_operator(),
    )

    result = runtime.run(
        "去调查一下 AAPL 的基本面信息，写详细报告",
        mode="auto",
        semantic_mode="model",
        synthesizer_mode="model",
    )

    assert result.status == "failed"
    assert result.failure_report is not None
    assert result.failure_report["reason"] == "final_answer_quality_insufficient"
    assert any(item.startswith("answer_min_chars:") for item in result.failure_report["missing_evidence"])
    quality = journal.records(task_id=result.task_id, kind="final_answer_quality_check")[-1].data
    assert quality["passed"] is False
    assert quality["answer_profile"]["format"] == "detailed_report"


def test_phase109_answer_profile_preserves_explicit_detailed_report_shape() -> None:
    profile = infer_answer_profile(
        "请检索双曲动力学的前沿研究，按摘要、关键文献、开放问题、局限写一份详细中文报告",
        response_language="zh",
    )

    assert profile.format == "detailed_report"
    assert profile.detail_level == "detailed"
    assert profile.metadata["quality_gate"] == "strict"
    assert profile.min_answer_chars >= 1200
    assert "证据质量与局限" in profile.target_sections or "风险与局限" in profile.target_sections


def test_phase109_answer_profile_preserves_explicit_brief_shape() -> None:
    profile = infer_answer_profile("简短说明什么是双曲动力学", response_language="zh")

    assert profile.format == "brief_answer"
    assert profile.detail_level == "brief"
    assert profile.min_answer_chars <= 100


def test_phase109_detailed_research_final_creates_memory_proposal() -> None:
    journal = JournalStore.in_memory()
    memory = MemoryStore.in_memory()
    answer = _long_finance_answer()
    fabric = fake_fabric(
        {
            "semantic.intake": _finance_detail_intake("去调查一下 AAPL 的基本面信息，写详细报告"),
            "synthesizer.answer": {
                "answer": answer,
                "citation_refs": ["cite-evidence-span-doc-goal-plan-1-1-1-1"],
                "confidence": 0.86,
                "limitations": ["部分估值指标只来自当前提供证据，仍需继续跟踪。"],
                "used_evidence": ["evidence-span-doc-goal-plan-1-1-1-1"],
            },
        },
        journal=journal,
    )
    runtime = AgentRuntime(
        journal=journal,
        artifact_store=ArtifactStore.in_memory(),
        processor_fabric=fabric,
        retrieval_operator=_operator(),
        memory_store=memory,
    )

    result = runtime.run(
        "去调查一下 AAPL 的基本面信息，写详细报告",
        mode="auto",
        semantic_mode="model",
        synthesizer_mode="model",
    )

    assert result.status == "completed"
    quality = journal.records(task_id=result.task_id, kind="final_answer_quality_check")[-1].data
    assert quality["passed"] is True
    proposals = memory.proposals()
    assert len(proposals) == 1
    assert proposals[0].approval_status == "pending"
    assert proposals[0].metadata["source_kind"] == "research_final_answer"
    assert journal.records(task_id=result.task_id, kind="memory_proposal")


def test_phase109_failure_reflection_creates_nonblocking_memory_proposal() -> None:
    journal = JournalStore.in_memory()
    memory = MemoryStore.in_memory()
    runtime = AgentRuntime(journal=journal, memory_store=memory)
    recipe = task_recipe(
        "retrieval_answer",
        metadata={
            "thread_id": "thread-1",
            "execution_metadata": {
                "semantic_goal": {
                    "root_goal": "调查 Apple 和 Oracle 的基本面并做对比",
                }
            },
        },
    )

    failure = runtime._failure(
        "task-1",
        "run-1",
        "retrieval_source_quality_insufficient",
        missing_evidence=["Oracle fundamentals", "market valuation"],
        next_action="switch_to_authoritative_finance_sources",
        recipe=recipe,
    )

    assert failure.reason == "retrieval_source_quality_insufficient"
    proposals = memory.proposals()
    assert len(proposals) == 1
    assert proposals[0].metadata["source_kind"] == "task_reflection"
    assert proposals[0].metadata["review_nonblocking"] is True
    assert memory.list_items() == []
    proposal_record = journal.records(task_id="task-1", kind="memory_proposal")[-1]
    assert proposal_record.data["review_nonblocking"] is True
    assert _pending_memory_proposals(journal, task_id="task-1") == []


def test_phase109_mission_supervisor_rejects_short_detailed_final_answer() -> None:
    journal = JournalStore.in_memory()
    goal = "调查 AAPL 基本面，写详细报告"
    profile = infer_answer_profile(goal, semantic_intake=_semantic_intake_contract(goal), response_language="zh")
    supervisor = MissionSupervisor(journal=journal, max_iterations=3)
    mission = supervisor.start(
        root_goal=goal,
        thread_id="t",
        metadata={"answer_profile": profile.to_dict()},
    )
    result = AgentRuntimeResult(
        status="completed",
        task_id="task-x",
        run_id="run-1",
        mode="retrieval_answer",
        recipe_id="recipe-retrieval-answer",
        final_answer={
            "answer": "AAPL 有营收。",
            "citation_refs": ["cite-1"],
            "used_evidence": ["ev-1"],
            "limitations": [],
            "confidence": 0.8,
            "task_id": "task-x",
            "run_id": "run-1",
            "trace_refs": [],
        },
        failure_report=None,
        trace_refs=[],
    )

    _updated, assessment = supervisor.assess(mission, result, index=1)

    assert assessment.decision == "continue"
    assert any(item.startswith("answer_min_chars:") for item in assessment.missing_requirements)
    assert assessment.next_directive is not None


def _finance_detail_intake(goal: str):
    return {
        "primary_intent": "finance_fundamentals_research",
        "suggested_mode": "retrieval_answer",
        "compound": False,
        "requires_clarification": False,
        "intents": [
            {
                "kind": "finance_fundamentals_research",
                "text": goal,
                "sequence_index": 1,
                "required_capabilities": ["finance.fundamentals_research"],
                "risk": "read",
                "status": "ready",
                "metadata": {
                    "answer_profile_hint": {
                        "format": "detailed_report",
                        "detail_level": "detailed",
                        "quality_gate": "strict",
                    },
                    "capability_args": {
                        "retrieval.run": {
                            "goal_id": "goal-plan-1-1",
                            "query": "AAPL 2024 10-K revenue net income cash flow market cap",
                            "source_url": SEC_URL,
                            "metadata": {
                                "research_profile": "finance_fundamentals",
                                "research_task_kind": "fundamentals",
                                "source_authority_requirement": "primary",
                            },
                        }
                    },
                },
            }
        ],
        "blocked_capabilities": [],
        "warnings": [],
        "response_hint": None,
        "clarification_question": None,
    }


def _semantic_intake_contract(goal: str) -> SemanticIntake:
    return SemanticIntake(intake_id="intake-test", goal=goal, **_finance_detail_intake(goal))


def _operator() -> RetrievalOperator:
    return RetrievalOperator(
        search_provider=DirectUrlSearchProvider(),
        fetch_provider=FakeFetchProvider(
            {
                SEC_URL: (
                    "Apple 2024 Form 10-K official annual report. "
                    "Revenue net sales were $391.0 billion. Net income was $93.7 billion. "
                    "Operating cash flow was $118.3 billion. Total assets and liabilities are reported "
                    "in the balance sheet. Market valuation and PE ratio require current market data. "
                    "The filing describes business segments, risks, services growth, iPhone concentration, "
                    "and capital return policy."
                )
            }
        ),
    )


def _long_finance_answer() -> str:
    section = """
**结论摘要**
AAPL 的基本面调研需要把公司与业务、财务表现、资产负债与现金流、估值与市场数据、增长驱动与风险分开看。当前证据支持的事实包括官方年报中的收入、净利润和经营现金流；对实时股价、市值、市盈率等估值指标仍需要继续接入市场数据源。

**公司与业务**
Apple 是以硬件、软件、服务和生态系统协同为核心的消费科技公司。业务质量的核心在于 iPhone、Mac、iPad、可穿戴设备和服务收入的组合，以及用户基础带来的持续服务变现能力。

**财务表现**
证据显示，公司年报披露了 revenue / net sales、net income 和相关 earnings 指标。营收和利润是判断规模、盈利能力和周期韧性的核心事实。这里引用的数字必须以官方 filing 为准，不能用营销页替代财务报表。

**资产负债与现金流**
现金流是 Apple 基本面分析的关键。证据支持经营现金流信息，资产、负债和股东权益需要从资产负债表继续拆解。现金流、回购、股息和资本开支共同影响股东回报与财务弹性。

**估值与市场数据**
估值需要股价、市值、市盈率、股息率和增长预期。当前证据不充分支持实时 PE ratio 或 market cap 的完整判断，因此这里只能说明估值分析框架，并把缺口列为后续检索目标。

**增长驱动与风险**
增长驱动包括服务业务、生态粘性、新产品周期和全球市场渗透。风险包括硬件周期、供应链、监管、汇率、竞争、估值过高和单一产品线集中度。风险判断必须和证据分开，不应包装成确定事实。

**证据质量与局限**
本报告只使用提供的 evidence 和 citation。局限是实时市场数据、估值倍数、分部明细和最新季度变化仍需继续补充。下一步应优先检索 companyfacts、investor relations earnings release 和可靠市场数据源。
"""
    return "\n".join([section.strip()] * 2)
