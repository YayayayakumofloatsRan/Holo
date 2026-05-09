from __future__ import annotations

from dataclasses import dataclass
from typing import Any


STAGE34_NAME = "stage34-debt-registry-and-visual-readiness"


@dataclass(frozen=True)
class DebtItem:
    debt_id: str
    title: str
    status: str
    category: str
    evidence: str
    resolution: str
    validation: str
    next_gate: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "debt_id": self.debt_id,
            "title": self.title,
            "status": self.status,
            "category": self.category,
            "evidence": self.evidence,
            "resolution": self.resolution,
            "validation": self.validation,
            "next_gate": self.next_gate,
        }


def current_debt_items() -> list[DebtItem]:
    return [
        DebtItem(
            debt_id="reply-api-facade-size",
            title="reply_api.py remains a large compatibility facade",
            status="bounded_structural_debt",
            category="structure",
            evidence="HOLO_HANDOFF.md Current Weak Spots and .agent/PLANS.md still name reply_api.py as the largest facade.",
            resolution="Do not opportunistically split it further; require dedicated replay-backed compatibility cuts.",
            validation="Full pytest plus the latest stage acceptance gate before and after each facade split.",
            next_gate="future-facade-slimming-plan",
        ),
        DebtItem(
            debt_id="live-wechat-hardening",
            title="WeChat watcher and pyweixin_dialog need live hardening",
            status="external_precondition",
            category="live_transport",
            evidence="Live watcher verification is intentionally disabled while Holo remains shut down.",
            resolution="Keep offline gates green; restart and live-soak only after explicit operator approval.",
            validation="Official watcher status, transport_state.live.json, ledgers, and a controlled live probe.",
            next_gate="operator-approved-live-soak",
        ),
        DebtItem(
            debt_id="visual-provider-readiness",
            title="Image understanding must not be overclaimed by text-only providers",
            status="bounded_by_stage34",
            category="provider_contract",
            evidence="Stage33 provider contracts mark DeepSeek/OpenAI-compatible text APIs as image_support=false.",
            resolution="Expose a Stage34 visual-readiness gate that proves text APIs reject image requests and image routing is visible.",
            validation="accept-stage34 and tests/test_stage34_debt_closure.py.",
            next_gate="configured-real-image-provider-soak",
        ),
        DebtItem(
            debt_id="latency-cache-soak",
            title="Latency, cache reuse, and provider fallback need real soak data",
            status="external_precondition",
            category="operations",
            evidence="Stage35 validates internal DeepSeek readiness; it still cannot prove multi-hour provider latency or cache quality.",
            resolution="Treat remaining latency/cache evidence as operational soak debt after internal readiness is green.",
            validation="show-internal-runtime-readiness, show-usage-ledger, show-provider-status, blackbox soak, and provider telemetry after restart approval.",
            next_gate="operator-approved-provider-soak",
        ),
        DebtItem(
            debt_id="internal-runtime-readiness",
            title="Internal DeepSeek runtime startup was not machine-checkable",
            status="resolved",
            category="operations",
            evidence="Stage35 adds show-internal-runtime-readiness and accept-stage35 for DeepSeek lanes, env-key presence, config secret hygiene, and no-WeChat quiescence.",
            resolution="Internal startup is now gated before treating Holo as runnable from the CLI/API surface.",
            validation="tests/test_stage35_internal_runtime_readiness.py and accept-stage35.",
            next_gate="accept-stage35",
        ),
        DebtItem(
            debt_id="autonomous-inquiry-quality",
            title="Autonomous inquiry shape is still engineered and must remain action-market-first",
            status="planned",
            category="bionic_behavior",
            evidence="Stage32 removed the fixed fallback opener but did not add new autonomy or widen initiative rights.",
            resolution="Future work must improve inquiry composition through the bionic kernel without adding a second brain.",
            validation="Dedicated behavior fixtures plus action-market-first and no-unbounded-loop checks.",
            next_gate="stage36-or-explicit-replan",
        ),
        DebtItem(
            debt_id="provider-contract-drift",
            title="OpenAI-compatible and DeepSeek API contracts could drift silently",
            status="resolved",
            category="provider_contract",
            evidence="Stage33 pins OpenAI-compatible/DeepSeek to chat.completions and keeps Responses on responses.create.",
            resolution="Provider contracts and accept-stage33 are now first-class diagnostics.",
            validation="tests/test_stage33_provider_contracts.py and accept-stage33.",
            next_gate="accept-stage33",
        ),
        DebtItem(
            debt_id="template-pressure",
            title="Deterministic fallback used a repeated fixed opener",
            status="resolved",
            category="expression",
            evidence="Stage32 added bounded response shaping and context_shaping_score metrics.",
            resolution="Fixed fallback phrase is replaced by compact context-shaped fallback generation.",
            validation="tests/test_stage32_response_shaping.py and accept-stage32.",
            next_gate="accept-stage32",
        ),
        DebtItem(
            debt_id="replay-fixture-breadth",
            title="Replay fixture breadth remains intentionally narrow",
            status="bounded_structural_debt",
            category="verification",
            evidence="ROADMAP_REGISTRY.md keeps replay breadth growth tied to real blind spots.",
            resolution="Do not add synthetic fixture sprawl; add fixtures only when a concrete regression shape appears.",
            validation="tests/test_stage14_replay.py and future targeted replay fixtures.",
            next_gate="regression-driven-fixture-addition",
        ),
    ]


def current_debt_registry() -> dict[str, Any]:
    items = [item.to_dict() for item in current_debt_items()]
    unclassified = [item for item in items if item.get("status") in {"", "unclassified"}]
    counts: dict[str, int] = {}
    for item in items:
        status = str(item.get("status", "") or "unclassified")
        counts[status] = counts.get(status, 0) + 1
    return {
        "ok": not unclassified,
        "stage": STAGE34_NAME,
        "items": items,
        "summary": {
            "count": len(items),
            "by_status": counts,
            "closed_or_bounded": all(str(item.get("status", "")) != "unclassified" for item in items),
        },
        "unclassified": unclassified,
        "hard_boundaries": {
            "no_live_transport_started": True,
            "no_self_memory_mutation": True,
            "no_new_unbounded_loop": True,
            "action_market_first_preserved": True,
        },
    }
