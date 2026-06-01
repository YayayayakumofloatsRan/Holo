from __future__ import annotations

from kernel_v3.contracts import JsonObject


CONTEXT_BUDGET_PROFILES: dict[str, JsonObject] = {
    "compact": {
        "token_budget": 4096,
        "section_budget": 1024,
        "workspace_evidence_chars": 12000,
        "workspace_citation_chars": 2048,
        "synthesis_evidence_preview_chars": 4096,
        "synthesis_citation_preview_chars": 2048,
    },
    "large": {
        "token_budget": 65536,
        "section_budget": 16384,
        "workspace_evidence_chars": 120000,
        "workspace_citation_chars": 16384,
        "synthesis_evidence_preview_chars": 65536,
        "synthesis_citation_preview_chars": 16384,
    },
    "huge": {
        "token_budget": 262144,
        "section_budget": 65536,
        "workspace_evidence_chars": 250000,
        "workspace_citation_chars": 32768,
        "synthesis_evidence_preview_chars": 131072,
        "synthesis_citation_preview_chars": 32768,
    },
    "provider": {
        "token_budget": 1000000,
        "section_budget": 200000,
        "workspace_evidence_chars": 750000,
        "workspace_citation_chars": 65536,
        "synthesis_evidence_preview_chars": 500000,
        "synthesis_citation_preview_chars": 65536,
    },
}


def context_budget_profile(profile: object = None) -> JsonObject:
    if not isinstance(profile, str) or not profile:
        return dict(CONTEXT_BUDGET_PROFILES["compact"])
    return dict(CONTEXT_BUDGET_PROFILES.get(profile, CONTEXT_BUDGET_PROFILES["compact"]))


def merge_context_budget(
    profile: object = None,
    *,
    token_budget: object = None,
    section_budget: object = None,
    workspace_evidence_chars: object = None,
    synthesis_evidence_preview_chars: object = None,
) -> JsonObject:
    budget = context_budget_profile(profile)
    _set_positive_int(budget, "token_budget", token_budget)
    _set_positive_int(budget, "section_budget", section_budget)
    _set_positive_int(budget, "workspace_evidence_chars", workspace_evidence_chars)
    _set_positive_int(budget, "synthesis_evidence_preview_chars", synthesis_evidence_preview_chars)
    if "workspace_citation_chars" not in budget:
        budget["workspace_citation_chars"] = min(int(budget["workspace_evidence_chars"]), 65536)
    if "synthesis_citation_preview_chars" not in budget:
        budget["synthesis_citation_preview_chars"] = min(int(budget["synthesis_evidence_preview_chars"]), 65536)
    return budget


def _set_positive_int(target: JsonObject, key: str, value: object) -> None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return
    if parsed > 0:
        target[key] = parsed
