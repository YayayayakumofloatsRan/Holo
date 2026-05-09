from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AdapterSpec:
    name: str
    channel: str
    transport_is_interface: bool = True
    transport_decision_authority: bool = False
    uses_live_transport: bool = False
    canonicalizes_wechat_identity: bool = False

    def to_contract(self) -> dict[str, object]:
        return {
            "adapter": self.name,
            "channel": self.channel,
            "transport_is_interface": self.transport_is_interface,
            "transport_decision_authority": self.transport_decision_authority,
            "uses_live_transport": self.uses_live_transport,
            "canonicalizes_wechat_identity": self.canonicalizes_wechat_identity,
        }


class AdapterRegistry:
    def __init__(self) -> None:
        self._specs: dict[tuple[str, str], AdapterSpec] = {}
        self.register(AdapterSpec(name="cli", channel="cli"))
        self.register(AdapterSpec(name="wechat", channel="wechat", canonicalizes_wechat_identity=True))
        self.register(AdapterSpec(name="http", channel="http"))

    def register(self, spec: AdapterSpec) -> None:
        self._specs[(spec.name, spec.channel)] = spec

    def resolve(self, *, adapter: str, channel: str) -> AdapterSpec:
        normalized_adapter = str(adapter or channel or "cli").strip().lower() or "cli"
        normalized_channel = str(channel or normalized_adapter).strip().lower() or normalized_adapter
        return self._specs.get(
            (normalized_adapter, normalized_channel),
            AdapterSpec(name=normalized_adapter, channel=normalized_channel),
        )


adapter_registry = AdapterRegistry()
