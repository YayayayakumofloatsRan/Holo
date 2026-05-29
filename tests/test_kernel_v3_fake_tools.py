from kernel_v3.contracts import CandidateAction
from kernel_v3.policy import PolicyGate
from kernel_v3.tools import ToolRegistry


def test_fake_workspace_tools_cover_phase0_5_simple_tools():
    registry = ToolRegistry.with_fake_workspace_tools(
        files={"README.md": "Holo is a host-owned agent harness."}
    )

    respond = registry.execute(
        CandidateAction(
            action_id="act-respond",
            kind="respond",
            name=None,
            description="respond",
            score=1.0,
            payload={"text": "hello"},
            reasons=[],
            side_effect_class="none",
        )
    )
    ask_user = registry.execute(
        CandidateAction(
            action_id="act-ask",
            kind="ask_user",
            name=None,
            description="ask",
            score=1.0,
            payload={"question": "which file?"},
            reasons=[],
            side_effect_class="none",
        )
    )
    search_action = CandidateAction(
        action_id="act-search",
        kind="tool",
        name="workspace.search",
        description="search",
        score=1.0,
        payload={"query": "host-owned"},
        reasons=[],
        side_effect_class="read",
    )
    read_action = CandidateAction(
        action_id="act-read",
        kind="tool",
        name="file.read",
        description="read",
        score=1.0,
        payload={"path": "README.md"},
        reasons=[],
        side_effect_class="read",
    )
    write_action = CandidateAction(
        action_id="act-write",
        kind="tool",
        name="blocked_external_write",
        description="write",
        score=1.0,
        payload={"target": "external"},
        reasons=[],
        side_effect_class="destructive",
    )
    gate = PolicyGate(permission="read_write")
    search = registry.execute_with_artifacts(
        search_action,
        policy_decision=gate.validate(run_id="run-1", action=search_action, manifest=registry.manifest_for_action(search_action)),
    ).observation
    read = registry.execute_with_artifacts(
        read_action,
        policy_decision=gate.validate(run_id="run-1", action=read_action, manifest=registry.manifest_for_action(read_action)),
    ).observation
    write = registry.execute_with_artifacts(
        write_action,
        policy_decision=gate.validate(run_id="run-1", action=write_action, manifest=registry.manifest_for_action(write_action)),
    ).observation

    assert respond.kind == "respond_result"
    assert ask_user.kind == "ask_user"
    assert search.content["matches"] == [{"path": "README.md", "text": "Holo is a host-owned agent harness."}]
    assert read.content == {"path": "README.md", "text": "Holo is a host-owned agent harness."}
    assert write.status == "blocked"


def test_respond_and_ask_user_normalize_common_model_payload_keys():
    registry = ToolRegistry.with_builtin_respond()

    answer = registry.execute(
        CandidateAction(
            action_id="act-answer",
            kind="respond",
            name=None,
            description="respond",
            score=1.0,
            payload={"answer": "model answer"},
            reasons=[],
            side_effect_class="none",
        )
    )
    summary = registry.execute(
        CandidateAction(
            action_id="act-summary",
            kind="respond",
            name=None,
            description="respond",
            score=1.0,
            payload={"summary": "brief reasoning summary"},
            reasons=[],
            side_effect_class="none",
        )
    )
    ask = registry.execute(
        CandidateAction(
            action_id="act-prompt",
            kind="ask_user",
            name=None,
            description="ask",
            score=1.0,
            payload={"prompt": "which market?"},
            reasons=[],
            side_effect_class="none",
        )
    )

    assert answer.content == {"text": "model answer"}
    assert summary.content == {"text": "brief reasoning summary"}
    assert ask.content == {"question": "which market?"}


def test_host_execution_context_is_not_visible_to_respond_or_ask_user():
    registry = ToolRegistry.with_builtin_respond()
    respond = CandidateAction(
        action_id="act-empty-respond",
        kind="respond",
        name=None,
        description="fallback answer",
        score=1.0,
        payload={},
        reasons=[],
        side_effect_class="none",
    )
    ask = CandidateAction(
        action_id="act-empty-ask",
        kind="ask_user",
        name=None,
        description="fallback question",
        score=1.0,
        payload={},
        reasons=[],
        side_effect_class="none",
    )

    respond_result = registry.execute_with_artifacts(
        respond,
        execution_context={"task_id": "task-secret", "run_id": "run-secret"},
    )
    ask_result = registry.execute_with_artifacts(
        ask,
        execution_context={"task_id": "task-secret", "run_id": "run-secret"},
    )

    assert respond_result.observation.content == {"text": "fallback answer"}
    assert ask_result.observation.content == {"question": "fallback question"}
