"""Kernel v4 single-agent harness.

Kernel v4 is a clean Python rewrite of the mature single-agent query loop
shape: model emits tool_use blocks, host executes tools, tool_results are
fed back into the next model turn. Domain logic lives in prompts and tools,
not in local semantic gates.
"""

from kernel_v4.contracts import (
    AssistantMessage,
    LoopResult,
    ModelEvent,
    ToolCall,
    ToolMessage,
)
from kernel_v4.finance_runner import FinanceQuestionSpec, build_finance_registry, run_finance_question
from kernel_v4.loop import SingleAgentLoop
from kernel_v4.monitoring import WorkflowConsoleMonitor
from kernel_v4.providers import DeepSeekChatProvider, OpenAICompatibleChatProvider
from kernel_v4.runtime import AbortController, ContextEdit, WorkflowObserver
from kernel_v4.tooling import ToolRegistry

__all__ = [
    "AbortController",
    "AssistantMessage",
    "ContextEdit",
    "LoopResult",
    "ModelEvent",
    "SingleAgentLoop",
    "DeepSeekChatProvider",
    "FinanceQuestionSpec",
    "OpenAICompatibleChatProvider",
    "ToolCall",
    "ToolMessage",
    "ToolRegistry",
    "WorkflowObserver",
    "WorkflowConsoleMonitor",
    "build_finance_registry",
    "run_finance_question",
]
