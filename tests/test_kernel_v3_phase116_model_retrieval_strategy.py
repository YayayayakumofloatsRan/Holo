from kernel_v3.contracts import CandidateAction
from kernel_v3.retrieval.contracts import SearchGoal
from kernel_v3.retrieval.operator import _goal_from_payload
from kernel_v3.retrieval.query_campaign import build_query_campaign
from kernel_v3.retrieval.strategy import supervise_retrieval_payload


def test_phase116_model_owned_strategy_drives_generic_research_campaign():
    strategy = {
        "strategy_id": "model-physics-frontier",
        "task_understanding": "Find frontier research sources, not definitions.",
        "domain_hypotheses": ["physics", "dynamical systems"],
        "source_family_plan": [
            {"family": "scholarly_preprint", "reason": "recent work appears early"},
            {"family": "scholarly_publisher", "reason": "journal papers support claims"},
        ],
        "query_plan": [
            {
                "query": "Hamiltonian chaos plasma physics recent papers open problems",
                "purpose": "frontier paper search",
                "source_family": "scholarly_index",
            },
            {
                "query": "site:arxiv.org Hamiltonian chaos plasma physics recent",
                "purpose": "preprint search",
                "source_family": "scholarly_preprint",
            },
            {
                "query": "Hamiltonian chaos plasma physics survey state of the art",
                "purpose": "survey framing",
                "source_family": "scholarly_publisher",
            },
        ],
    }

    campaign = build_query_campaign(
        SearchGoal(
            goal_id="goal-model-strategy",
            query="Hamiltonian chaos in plasma physics frontier research",
            max_queries=6,
            max_sources=120,
            max_fetches=80,
            metadata={"retrieval_strategy": strategy, "query_campaign": "auto"},
        )
    )

    assert campaign.queries[:3] == [item["query"] for item in strategy["query_plan"]]
    assert campaign.diagnostics["model_strategy_present"] is True
    assert campaign.diagnostics["model_strategy_query_count"] == 3
    assert campaign.diagnostics["host_axis_expansion_enabled"] is False
    selected_sources = [item["source"] for item in campaign.diagnostics["selected"]]
    assert selected_sources[:3] == ["model_strategy_query_plan"] * 3
    assert "generic_research_axis" not in selected_sources


def test_phase116_strategy_supervision_preserves_model_retrieval_strategy_on_replan():
    payload = {
        "query": "hyperbolic dynamics frontier research",
        "metadata": {
            "retrieval_strategy": {
                "query_plan": [
                    {"query": "hyperbolic dynamics recent survey open problems"},
                    {"query": "site:arxiv.org hyperbolic dynamics recent papers"},
                ],
                "source_family_plan": [{"family": "scholarly_preprint"}],
            }
        },
    }

    decision = supervise_retrieval_payload(
        payload,
        replan_hints={
            "needs_replan": True,
            "attempted_queries": ["hyperbolic dynamics frontier research"],
            "suggested_query_hints": ["hyperbolic dynamics dictionary definition"],
        },
        root_goal="hyperbolic dynamics frontier research",
    )

    assert decision.payload["query"] == "hyperbolic dynamics frontier research"
    assert "queries" not in decision.payload
    assert decision.payload["metadata"]["retrieval_strategy"] == payload["metadata"]["retrieval_strategy"]
    assert decision.diagnostics["model_strategy_present"] is True
    assert decision.diagnostics["model_strategy_query_count"] == 2
    assert decision.diagnostics["rewritten"] is False


def test_phase116_goal_default_query_count_uses_model_strategy_query_plan():
    action = CandidateAction(
        action_id="act-model-strategy",
        kind="tool",
        name="retrieval.run",
        description="run model strategy",
        score=0.9,
        reasons=["model planned multiple source families"],
        payload={
            "query": "general research target",
            "retrieval_strategy": {
                "query_plan": [
                    {"query": "general research target official record"},
                    {"query": "general research target scholarly discussion"},
                    {"query": "general research target recent analysis"},
                    {"query": "general research target source documentation"},
                ],
            },
        },
        side_effect_class="network",
    )

    goal = _goal_from_payload(action)

    assert goal.max_queries == 4
    assert goal.metadata["retrieval_strategy"]["query_plan"][0]["query"] == "general research target official record"
