import json
import sys
from pathlib import Path

from kernel_v3.context import ContextCompiler
from kernel_v3.contracts import CandidateAction, PolicyDecision
from kernel_v3.journal import JournalStore
from kernel_v3.loop import LoopControllerV3
from kernel_v3.policy import PolicyGate
from kernel_v3.testing.fakes import FakeEvaluator, FakePlanner
from kernel_v3.tools import ToolRegistry


def test_tool_registry_exposes_stable_manifests_for_resources_and_operators():
    root = Path("kernel_v3/.test-phase2-manifests")
    _reset_dir(root)
    try:
        registry = ToolRegistry.with_permissioned_workspace(root=root)

        manifests = {manifest.name: manifest for manifest in registry.manifests()}

        assert manifests["workspace.search"].resource_kind == "workspace"
        assert manifests["workspace.search"].operator_kind == "search"
        assert manifests["workspace.search"].side_effect_class == "read"
        assert manifests["workspace.search"].permissions_required == ["workspace:read"]
        assert manifests["workspace.write"].permissions_required == ["workspace:write"]
        assert manifests["shell.exec"].side_effect_class == "shell"
        assert manifests["network.fetch"].side_effect_class == "network"
        assert manifests["network.fetch"].enabled is False
    finally:
        _remove_dir(root)


def test_real_workspace_read_only_tools_work_under_workspace_root():
    root = Path("kernel_v3/.test-phase2-read")
    _reset_dir(root)
    try:
        raw_text = "Holo is a host-owned kernel. " + "workspace-raw-sentinel-" * 40
        (root / "README.md").write_text(raw_text, encoding="utf-8")
        registry = ToolRegistry.with_permissioned_workspace(root=root)
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

        search = registry.execute_with_artifacts(
            search_action,
            policy_decision=_allowed_decision(search_action),
        )
        read = registry.execute_with_artifacts(
            read_action,
            policy_decision=_allowed_decision(read_action),
        )

        assert search.observation.status == "ok"
        assert search.observation.content["matches"][0]["path"] == "README.md"
        assert "text" not in search.observation.content["matches"][0]
        assert search.observation.content["matches"][0]["text_preview"].startswith("Holo is a host-owned kernel.")
        assert read.observation.content["path"] == "README.md"
        assert "text" not in read.observation.content
        assert read.observation.content["text_preview"].startswith("Holo is a host-owned kernel.")
        encoded = json.dumps([search.observation.to_dict(), read.observation.to_dict()], ensure_ascii=False)
        assert raw_text not in encoded
        assert search.artifact_refs[0].payload_hash
        assert read.artifact_refs[0].artifact_id.startswith("artifact-workspace-")
    finally:
        _remove_dir(root)


def test_workspace_write_requires_explicit_permission_and_journals_artifact_refs():
    root = Path("kernel_v3/.test-phase2-write")
    _reset_dir(root)
    try:
        action = CandidateAction(
            action_id="act-write",
            kind="tool",
            name="workspace.write",
            description="write file",
            score=1.0,
            payload={"path": "notes.txt", "text": "durable"},
            reasons=[],
            side_effect_class="write",
        )

        blocked_registry = ToolRegistry.with_permissioned_workspace(root=root)
        blocked_loop = LoopControllerV3(
            journal=JournalStore.in_memory(),
            context_compiler=ContextCompiler(),
            planner=FakePlanner([action]),
            policy_gate=PolicyGate(permission="read_write"),
            tool_registry=blocked_registry,
            evaluator=FakeEvaluator.stop_on_block(),
        )
        blocked = blocked_loop.run("write notes")

        assert blocked.status == "blocked"
        assert not (root / "notes.txt").exists()
        assert blocked_registry.executed_actions == []

        allowed_registry = ToolRegistry.with_permissioned_workspace(root=root)
        allowed_journal = JournalStore.in_memory()
        allowed_loop = LoopControllerV3(
            journal=allowed_journal,
            context_compiler=ContextCompiler(),
            planner=FakePlanner([action]),
            policy_gate=PolicyGate(permission="read_write", allowed_permissions={"workspace:write"}),
            tool_registry=allowed_registry,
            evaluator=FakeEvaluator.final_answer("written"),
        )
        allowed = allowed_loop.run("write notes")

        observation = allowed_journal.records(task_id=allowed.task_id, kind="observation")[0]
        assert allowed.status == "completed"
        assert (root / "notes.txt").read_text(encoding="utf-8") == "durable"
        assert observation.artifact_refs
        assert observation.data["content"]["path"] == "notes.txt"
    finally:
        _remove_dir(root)


def test_loop_passes_policy_decision_before_tool_side_effect_executes():
    root = Path("kernel_v3/.test-phase2-loop-policy")
    _reset_dir(root)
    try:
        action = CandidateAction(
            action_id="act-write-through-loop",
            kind="tool",
            name="workspace.write",
            description="write through loop",
            score=1.0,
            payload={"path": "loop.txt", "text": "policy-gated"},
            reasons=[],
            side_effect_class="write",
        )
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        journal = JournalStore.in_memory()
        loop = LoopControllerV3(
            journal=journal,
            context_compiler=ContextCompiler(),
            planner=FakePlanner([action]),
            policy_gate=PolicyGate(permission="read_write", allowed_permissions={"workspace:write"}),
            tool_registry=registry,
            evaluator=FakeEvaluator.final_answer("written"),
        )

        result = loop.run("write through loop")

        policy_record = journal.records(task_id=result.task_id, kind="policy_decision")[0]
        observation_record = journal.records(task_id=result.task_id, kind="observation")[0]
        assert (root / "loop.txt").read_text(encoding="utf-8") == "policy-gated"
        assert policy_record.data["allowed"] is True
        assert policy_record.data["constraints"]["tool_name"] == "workspace.write"
        assert policy_record.data["constraints"]["side_effect_class"] == "write"
        assert observation_record.action_ref == policy_record.action_ref
        assert observation_record.artifact_refs
    finally:
        _remove_dir(root)


def test_registry_refuses_tool_execution_without_policy_decision():
    root = Path("kernel_v3/.test-phase2-policy-required")
    _reset_dir(root)
    try:
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        read_result = registry.execute_with_artifacts(
            CandidateAction(
                action_id="act-read-no-policy",
                kind="tool",
                name="file.read",
                description="read without policy",
                score=1.0,
                payload={"path": "README.md"},
                reasons=[],
                side_effect_class="read",
            )
        )
        write_result = registry.execute_with_artifacts(
            CandidateAction(
                action_id="act-write-no-policy",
                kind="tool",
                name="workspace.write",
                description="write without policy",
                score=1.0,
                payload={"path": "notes.txt", "text": "blocked"},
                reasons=[],
                side_effect_class="write",
            )
        )

        assert read_result.observation.status == "blocked"
        assert read_result.observation.content["reason"] == "policy_decision_required"
        assert write_result.observation.status == "blocked"
        assert write_result.observation.content["reason"] == "policy_decision_required"
        assert not (root / "notes.txt").exists()
    finally:
        _remove_dir(root)


def test_registry_refuses_policy_decision_for_different_action():
    root = Path("kernel_v3/.test-phase2-policy-bound")
    _reset_dir(root)
    try:
        (root / "README.md").write_text("policy binding", encoding="utf-8")
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        action = CandidateAction(
            action_id="act-read-bound",
            kind="tool",
            name="file.read",
            description="read with mismatched policy",
            score=1.0,
            payload={"path": "README.md"},
            reasons=[],
            side_effect_class="read",
        )
        other = CandidateAction(
            action_id="act-other",
            kind="tool",
            name="file.read",
            description="other",
            score=1.0,
            payload={"path": "README.md"},
            reasons=[],
            side_effect_class="read",
        )

        result = registry.execute_with_artifacts(action, policy_decision=_allowed_decision(other))

        assert result.observation.kind == "policy_block"
        assert result.observation.status == "blocked"
        assert result.observation.content["reason"] == "policy_decision_action_mismatch"
        assert result.observation.content["policy_action_id"] == "act-other"
        assert registry.executed_actions == []
    finally:
        _remove_dir(root)


def test_registry_refuses_policy_decision_bound_to_different_tool_or_run():
    root = Path("kernel_v3/.test-phase2-policy-tool-bound")
    _reset_dir(root)
    try:
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        action = CandidateAction(
            action_id="act-bound",
            kind="tool",
            name="workspace.write",
            description="write with mismatched policy",
            score=1.0,
            payload={"path": "notes.txt", "text": "should-not-write"},
            reasons=[],
            side_effect_class="write",
        )

        wrong_tool = registry.execute_with_artifacts(
            action,
            policy_decision=PolicyDecision(
                decision_id="policy-wrong-tool",
                run_id="run-1",
                action_id=action.action_id,
                allowed=True,
                reason="allowed",
                constraints={
                    "tool_name": "file.read",
                    "side_effect_class": "read",
                },
            ),
        )
        wrong_run = registry.execute_with_artifacts(
            action,
            policy_decision=_allowed_decision(action),
            execution_context={"run_id": "run-2"},
        )

        assert wrong_tool.observation.status == "blocked"
        assert wrong_tool.observation.content["reason"] == "policy_decision_tool_mismatch"
        assert wrong_run.observation.status == "blocked"
        assert wrong_run.observation.content["reason"] == "policy_decision_run_mismatch"
        assert registry.executed_actions == []
        assert not (root / "notes.txt").exists()
    finally:
        _remove_dir(root)


def test_shell_execution_is_restricted_auditable_and_permissioned():
    root = Path("kernel_v3/.test-phase2-shell")
    _reset_dir(root)
    try:
        action = CandidateAction(
            action_id="act-shell",
            kind="tool",
            name="shell.exec",
            description="run safe shell command",
            score=1.0,
            payload={"argv": [sys.executable, "-c", "print('ok')"]},
            reasons=[],
            side_effect_class="shell",
        )
        registry = ToolRegistry.with_permissioned_workspace(
            root=root,
            shell_allowed_executables={Path(sys.executable).name},
        )
        journal = JournalStore.in_memory()
        loop = LoopControllerV3(
            journal=journal,
            context_compiler=ContextCompiler(),
            planner=FakePlanner([action]),
            policy_gate=PolicyGate(permission="read_write", allowed_permissions={"shell:exec"}),
            tool_registry=registry,
            evaluator=FakeEvaluator.final_answer("shell ok"),
        )

        result = loop.run("run command")

        observation = journal.records(task_id=result.task_id, kind="observation")[0]
        assert result.status == "completed"
        assert observation.data["content"]["exit_code"] == 0
        assert observation.data["content"]["stdout"].strip() == "ok"
        assert observation.data["content"]["argv"][0] == sys.executable
        assert observation.artifact_refs

        disallowed = registry.execute_with_artifacts(
            CandidateAction(
                action_id="act-shell-denied",
                kind="tool",
                name="shell.exec",
                description="run disallowed shell command",
                score=1.0,
                payload={"argv": ["definitely-not-allowed"]},
                reasons=[],
                side_effect_class="shell",
            )
        )
        assert disallowed.observation.status == "blocked"
    finally:
        _remove_dir(root)


def test_network_tool_is_manifested_as_disabled_contract_and_cannot_execute():
    root = Path("kernel_v3/.test-phase2-network")
    _reset_dir(root)
    try:
        registry = ToolRegistry.with_permissioned_workspace(root=root)
        action = CandidateAction(
            action_id="act-network",
            kind="tool",
            name="network.fetch",
            description="fetch later",
            score=1.0,
            payload={"url": "https://example.invalid/"},
            reasons=[],
            side_effect_class="network",
        )

        result = registry.execute_with_artifacts(
            action,
            policy_decision=PolicyDecision(
                decision_id="policy-network",
                run_id="run-1",
                action_id=action.action_id,
                allowed=True,
                reason="allowed_contract_only",
                constraints={
                    "permission": "network:fetch",
                    "tool_name": "network.fetch",
                    "side_effect_class": "network",
                },
            ),
        )

        assert registry.manifest_for_action(action).enabled is False
        assert result.observation.kind == "policy_block"
        assert result.observation.status == "blocked"
        assert result.observation.content["reason"] == "tool_disabled"
        assert registry.executed_actions == []
        assert result.artifact_refs
    finally:
        _remove_dir(root)


def _reset_dir(path: Path) -> None:
    _remove_dir(path)
    path.mkdir(parents=True)


def _allowed_decision(action: CandidateAction) -> PolicyDecision:
    return PolicyDecision(
        decision_id=f"policy-{action.action_id}",
        run_id="run-1",
        action_id=action.action_id,
        allowed=True,
        reason="allowed",
        constraints={
            "permission": "test",
            "tool_name": action.name,
            "side_effect_class": action.side_effect_class,
        },
    )


def _remove_dir(path: Path) -> None:
    if not path.exists():
        return
    for child in sorted(path.rglob("*"), reverse=True):
        if child.is_file():
            child.unlink()
        elif child.is_dir():
            child.rmdir()
    path.rmdir()
