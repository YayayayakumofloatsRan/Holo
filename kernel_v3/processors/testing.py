from __future__ import annotations

from kernel_v3.journal import JournalStore
from kernel_v3.processors.fabric import ProcessorFabric
from kernel_v3.processors.providers import FakeJsonProvider, FakeMalformedJsonProvider, FakeTimeoutProvider
from kernel_v3.processors.routing import ProcessorRouter


def fake_fabric(responses, *, journal: JournalStore | None = None) -> ProcessorFabric:
    return ProcessorFabric(
        providers={"fake_json": FakeJsonProvider(responses)},
        router=ProcessorRouter(default_provider="fake_json", default_model="fake-json"),
        journal=journal,
    )


def malformed_fabric(text: str = "not-json", *, journal: JournalStore | None = None) -> ProcessorFabric:
    return ProcessorFabric(
        providers={"fake_malformed_json": FakeMalformedJsonProvider(text)},
        router=ProcessorRouter(default_provider="fake_malformed_json", default_model="fake-malformed-json"),
        journal=journal,
    )


def timeout_fabric(*, journal: JournalStore | None = None) -> ProcessorFabric:
    return ProcessorFabric(
        providers={"fake_timeout": FakeTimeoutProvider()},
        router=ProcessorRouter(default_provider="fake_timeout", default_model="fake-timeout"),
        journal=journal,
    )
