from __future__ import annotations

from dataclasses import dataclass

from kernel_v3.contracts import Contract, JsonObject


EXECUTION_PROFILE_IDS = (
    "local-retrieval-fast",
    "finance-fact-fast",
    "finance-modeling",
    "web-research",
    "long-mission",
)


@dataclass(frozen=True, kw_only=True)
class ExecutionProfile(Contract):
    profile_id: str
    use_chat_router: bool
    use_semantic_intake_model: bool
    use_workmethod: bool
    use_mission_supervisor: bool
    planner_mode: str
    evaluator_mode: str
    synthesizer_mode: str
    max_processor_calls: int | None
    max_total_model_tokens: int | None
    max_prompt_chars_per_call: int | None
    max_agent_steps: int
    max_agent_tool_calls: int
    max_retrieval_runs: int
    retrieval_mode: str
    max_queries: int
    max_sources: int
    max_fetches: int
    max_spans_per_document: int
    require_citations: bool
    require_numeric_verifier: bool
    allow_partial_answer: bool
    context_profile: str
    research_depth: str
    notes: tuple[str, ...] = ()


def execution_profile(profile_id: str | None) -> ExecutionProfile:
    normalized = _normalize_profile_id(profile_id)
    try:
        return _PROFILES[normalized]
    except KeyError as exc:
        supported = ", ".join(EXECUTION_PROFILE_IDS)
        raise ValueError(f"unsupported execution profile: {profile_id}. Supported: {supported}") from exc


def execution_profile_runtime_metadata(profile: ExecutionProfile) -> JsonObject:
    return {
        "execution_profile": profile.to_dict(),
        "agent_loop": {
            "max_steps": profile.max_agent_steps,
            "max_tool_calls": profile.max_agent_tool_calls,
        },
        "retrieval": {
            "max_queries": profile.max_queries,
            "max_sources": profile.max_sources,
            "max_fetches": profile.max_fetches,
            "max_spans_per_document": profile.max_spans_per_document,
            "metadata": {
                "execution_profile": profile.profile_id,
                "retrieval_mode": profile.retrieval_mode,
                "research_depth": profile.research_depth,
            },
        },
        "processor_budget": {
            "max_calls_per_task": profile.max_processor_calls,
            "max_total_tokens_per_task": profile.max_total_model_tokens,
            "max_prompt_chars_per_call": profile.max_prompt_chars_per_call,
        },
    }


def profile_processor_mode(profile: ExecutionProfile, name: str, requested: str, *, online: bool) -> str:
    if name == "planner":
        return profile.planner_mode
    if name == "evaluator":
        return profile.evaluator_mode
    if name == "synthesizer":
        return profile.synthesizer_mode
    if name == "semantic_intake":
        return "model" if profile.use_semantic_intake_model else "fake"
    if name == "turn_router":
        return "model" if profile.use_chat_router else "fake"
    return "model" if online and requested == "fake" else requested


def profile_mission_enabled(profile: ExecutionProfile, requested: str = "auto") -> bool:
    normalized = str(requested or "auto").strip().lower().replace("_", "-")
    if normalized in {"on", "true", "yes", "1"}:
        return True
    if normalized in {"off", "false", "no", "0"}:
        return False
    return profile.use_mission_supervisor


def _normalize_profile_id(profile_id: str | None) -> str:
    normalized = str(profile_id or "long-mission").strip().lower().replace("_", "-")
    if normalized == "local":
        return "local-retrieval-fast"
    if normalized == "finance-fast":
        return "finance-fact-fast"
    if normalized == "long":
        return "long-mission"
    return normalized


_PROFILES: dict[str, ExecutionProfile] = {
    "local-retrieval-fast": ExecutionProfile(
        profile_id="local-retrieval-fast",
        use_chat_router=False,
        use_semantic_intake_model=False,
        use_workmethod=False,
        use_mission_supervisor=False,
        planner_mode="model",
        evaluator_mode="fake",
        synthesizer_mode="model",
        max_processor_calls=3,
        max_total_model_tokens=40_000,
        max_prompt_chars_per_call=30_000,
        max_agent_steps=3,
        max_agent_tool_calls=2,
        max_retrieval_runs=1,
        retrieval_mode="local_only",
        max_queries=1,
        max_sources=8,
        max_fetches=2,
        max_spans_per_document=2,
        require_citations=True,
        require_numeric_verifier=False,
        allow_partial_answer=True,
        context_profile="compact",
        research_depth="light",
        notes=("Short path for local evidence lookup and compact synthesis.",),
    ),
    "finance-fact-fast": ExecutionProfile(
        profile_id="finance-fact-fast",
        use_chat_router=False,
        use_semantic_intake_model=False,
        use_workmethod=False,
        use_mission_supervisor=False,
        planner_mode="model",
        evaluator_mode="fake",
        synthesizer_mode="model",
        max_processor_calls=4,
        max_total_model_tokens=60_000,
        max_prompt_chars_per_call=40_000,
        max_agent_steps=4,
        max_agent_tool_calls=3,
        max_retrieval_runs=2,
        retrieval_mode="structured_first",
        max_queries=4,
        max_sources=24,
        max_fetches=8,
        max_spans_per_document=8,
        require_citations=True,
        require_numeric_verifier=True,
        allow_partial_answer=True,
        context_profile="compact",
        research_depth="light",
        notes=("Fast lane for public finance benchmark fact extraction and numeric answers.",),
    ),
    "finance-modeling": ExecutionProfile(
        profile_id="finance-modeling",
        use_chat_router=False,
        use_semantic_intake_model=True,
        use_workmethod=False,
        use_mission_supervisor=False,
        planner_mode="model",
        evaluator_mode="model",
        synthesizer_mode="model",
        max_processor_calls=8,
        max_total_model_tokens=160_000,
        max_prompt_chars_per_call=60_000,
        max_agent_steps=8,
        max_agent_tool_calls=6,
        max_retrieval_runs=4,
        retrieval_mode="mixed",
        max_queries=16,
        max_sources=80,
        max_fetches=24,
        max_spans_per_document=16,
        require_citations=True,
        require_numeric_verifier=True,
        allow_partial_answer=True,
        context_profile="provider",
        research_depth="balanced",
        notes=("Medium lane for multi-metric finance analysis and calculations.",),
    ),
    "web-research": ExecutionProfile(
        profile_id="web-research",
        use_chat_router=True,
        use_semantic_intake_model=True,
        use_workmethod=True,
        use_mission_supervisor=False,
        planner_mode="model",
        evaluator_mode="model",
        synthesizer_mode="model",
        max_processor_calls=12,
        max_total_model_tokens=240_000,
        max_prompt_chars_per_call=80_000,
        max_agent_steps=10,
        max_agent_tool_calls=8,
        max_retrieval_runs=5,
        retrieval_mode="web",
        max_queries=24,
        max_sources=120,
        max_fetches=40,
        max_spans_per_document=20,
        require_citations=True,
        require_numeric_verifier=False,
        allow_partial_answer=True,
        context_profile="provider",
        research_depth="balanced",
        notes=("Research lane for open-web tasks that need several source families.",),
    ),
    "long-mission": ExecutionProfile(
        profile_id="long-mission",
        use_chat_router=True,
        use_semantic_intake_model=True,
        use_workmethod=True,
        use_mission_supervisor=True,
        planner_mode="model",
        evaluator_mode="model",
        synthesizer_mode="model",
        max_processor_calls=None,
        max_total_model_tokens=None,
        max_prompt_chars_per_call=None,
        max_agent_steps=2048,
        max_agent_tool_calls=1024,
        max_retrieval_runs=64,
        retrieval_mode="mixed",
        max_queries=128,
        max_sources=5_000,
        max_fetches=2_048,
        max_spans_per_document=64,
        require_citations=True,
        require_numeric_verifier=False,
        allow_partial_answer=True,
        context_profile="provider",
        research_depth="deep",
        notes=("Full resident-style mission loop for complex, long-running tasks.",),
    ),
}
