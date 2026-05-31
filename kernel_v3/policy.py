from __future__ import annotations

from kernel_v3.contracts import CandidateAction, PolicyDecision, ToolManifest


class PolicyGate:
    def __init__(
        self,
        *,
        permission: str = "read_write",
        allowed_permissions: set[str] | None = None,
    ) -> None:
        self.permission = permission
        self.allowed_permissions = set(allowed_permissions or set())

    def validate(
        self,
        *,
        run_id: str,
        action: CandidateAction,
        manifest: ToolManifest | None = None,
    ) -> PolicyDecision:
        side_effect_class = manifest.side_effect_class if manifest is not None else action.side_effect_class
        required = set(manifest.permissions_required if manifest is not None else [])
        tool_name = manifest.name if manifest is not None else action.name
        missing_permissions = sorted(required - self._base_permissions(side_effect_class) - self.allowed_permissions)
        blocked_destructive = self.permission == "read_only" and side_effect_class in {
            "destructive",
            "write",
            "shell",
            "network",
        }
        disabled = manifest is not None and not manifest.enabled
        allowed = not blocked_destructive and not missing_permissions and not disabled
        if blocked_destructive:
            reason = "blocked_side_effect_in_read_only_mode"
        elif missing_permissions:
            reason = "missing_permissions:" + ",".join(missing_permissions)
        elif disabled:
            reason = "tool_disabled"
        else:
            reason = "allowed"
        return PolicyDecision(
            decision_id=f"policy-{run_id}-{action.action_id}",
            run_id=run_id,
            action_id=action.action_id,
            allowed=allowed,
            reason=reason,
            constraints={
                "permission": self.permission,
                "tool_name": tool_name,
                "side_effect_class": side_effect_class,
                "required_permissions": sorted(required),
                "allowed_permissions": sorted(self.allowed_permissions),
                "manifest_enabled": None if manifest is None else manifest.enabled,
            },
        )

    def _base_permissions(self, side_effect_class: str) -> set[str]:
        if self.permission == "read_only":
            return {"workspace:read"} if side_effect_class == "read" else set()
        if self.permission == "read_write":
            return {"workspace:read"}
        return set()
