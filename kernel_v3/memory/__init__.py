from kernel_v3.memory.contracts import (
    MemoryItem,
    MemoryInspection,
    MemoryPrivacyError,
    MemoryProposal,
    MemoryRecallResult,
    MemoryTombstone,
    ProvenanceRef,
    ShadowCandidate,
)
from kernel_v3.memory.pipeline import MemoryPipeline, MemoryPipelineResult
from kernel_v3.memory.privacy import MemoryPrivacyDecision, contains_secret_like_content, validate_memory_item
from kernel_v3.memory.store import MemoryStore, stable_candidate_id, stable_memory_id, stable_proposal_id

MEMORY_RECALL_TOOL_NAME = "memory.recall"

__all__ = [
    "MemoryItem",
    "MemoryInspection",
    "MemoryPipeline",
    "MemoryPipelineResult",
    "MemoryPrivacyDecision",
    "MemoryPrivacyError",
    "MemoryProposal",
    "MemoryRecallResult",
    "MemoryRecallOperator",
    "MemoryStore",
    "MemoryTombstone",
    "MEMORY_RECALL_TOOL_NAME",
    "ProvenanceRef",
    "ShadowCandidate",
    "contains_secret_like_content",
    "stable_candidate_id",
    "stable_memory_id",
    "stable_proposal_id",
    "register_memory_tools",
    "validate_memory_item",
]


def __getattr__(name: str):
    if name in {"MemoryRecallOperator", "register_memory_tools"}:
        from kernel_v3.memory.operator import MemoryRecallOperator, register_memory_tools

        values = {
            "MemoryRecallOperator": MemoryRecallOperator,
            "register_memory_tools": register_memory_tools,
        }
        return values[name]
    raise AttributeError(name)
