from kernel_v3.contracts import CandidateAction
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
    search = registry.execute(
        CandidateAction(
            action_id="act-search",
            kind="tool",
            name="workspace.search",
            description="search",
            score=1.0,
            payload={"query": "host-owned"},
            reasons=[],
            side_effect_class="read",
        )
    )
    read = registry.execute(
        CandidateAction(
            action_id="act-read",
            kind="tool",
            name="file.read",
            description="read",
            score=1.0,
            payload={"path": "README.md"},
            reasons=[],
            side_effect_class="read",
        )
    )
    write = registry.execute(
        CandidateAction(
            action_id="act-write",
            kind="tool",
            name="blocked_external_write",
            description="write",
            score=1.0,
            payload={"target": "external"},
            reasons=[],
            side_effect_class="destructive",
        )
    )

    assert respond.kind == "respond_result"
    assert ask_user.kind == "ask_user"
    assert search.content["matches"] == [{"path": "README.md", "text": "Holo is a host-owned agent harness."}]
    assert read.content == {"path": "README.md", "text": "Holo is a host-owned agent harness."}
    assert write.status == "blocked"
