from __future__ import annotations

from kernel_v3.contracts import ProcessorRequest, ToolManifest
from kernel_v3.processors.providers import OpenAICompatibleProvider
from kernel_v3.provider_tools import openai_native_tool_surface


def test_openai_native_tool_surface_maps_holo_tool_names_and_schema() -> None:
    manifest = ToolManifest(
        name="calculator.compute",
        version="1",
        resource_kind="calculator",
        operator_kind="compute",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Compute a model-proposed expression.",
        input_schema={
            "expression": {"type": "str", "required": True, "min_length": 1},
            "precision": {"type": "int", "required": False, "min": 8, "max": 80},
            "variables": {"type": "object", "required": False},
            "_runtime": {"concurrency_safe": True},
        },
    )

    surface = openai_native_tool_surface([manifest], allowed_tool_names={"calculator.compute"})

    native_name = surface.tools[0]["function"]["name"]
    assert isinstance(native_name, str)
    assert native_name.startswith("calculator_compute_")
    assert surface.name_map[native_name] == "calculator.compute"
    parameters = surface.tools[0]["function"]["parameters"]
    assert parameters["required"] == ["expression"]
    assert parameters["properties"]["expression"]["type"] == "string"
    assert parameters["properties"]["expression"]["minLength"] == 1
    assert parameters["properties"]["precision"]["type"] == "integer"
    assert parameters["properties"]["precision"]["minimum"] == 8
    assert parameters["properties"]["precision"]["maximum"] == 80
    assert "_runtime" not in parameters["properties"]


def test_openai_compatible_payload_uses_native_tools_without_json_response_format() -> None:
    manifest = ToolManifest(
        name="workspace.search",
        version="1",
        resource_kind="workspace",
        operator_kind="search",
        side_effect_class="read",
        permissions_required=["workspace:read"],
        enabled=True,
        description="Search workspace text.",
        input_schema={"query": {"type": "str", "required": True, "min_length": 1}},
    )
    surface = openai_native_tool_surface([manifest], allowed_tool_names={"workspace.search"})
    request = ProcessorRequest(
        request_id="proc-1",
        run_id="run-1",
        processor="assistant.turn",
        prompt="search the workspace",
        context_id="ctx-1",
        parameters={
            "model": "test-model",
            "native_tools": surface.tools,
            "native_tool_name_map": surface.name_map,
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        },
    )

    payload = OpenAICompatibleProvider(enabled=True, base_url="https://example.test", model="fallback").build_payload(
        request,
        stream=True,
    )

    assert payload["stream"] is True
    assert payload["tools"] == surface.tools
    assert payload["tool_choice"] == "auto"
    assert payload["parallel_tool_calls"] is True
    assert "response_format" not in payload


def test_native_tool_surface_defers_should_defer_tools_but_keeps_always_load() -> None:
    always = ToolManifest(
        name="tool.discovery",
        version="1",
        resource_kind="tooling",
        operator_kind="discover",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Discover tools.",
        input_schema={},
        runtime={"always_load": True},
    )
    direct = ToolManifest(
        name="calculator.compute",
        version="1",
        resource_kind="calculator",
        operator_kind="compute",
        side_effect_class="read",
        permissions_required=[],
        enabled=True,
        description="Compute arithmetic.",
        input_schema={"expression": {"type": "str", "required": True}},
    )
    deferred = ToolManifest(
        name="sec.edgar.financials",
        version="1",
        resource_kind="sec_edgar",
        operator_kind="financials",
        side_effect_class="network",
        permissions_required=["network:fetch"],
        enabled=True,
        description="Fetch SEC financial statements.",
        input_schema={"identifier": {"type": "str", "required": True}},
        runtime={"should_defer": True},
    )

    surface = openai_native_tool_surface(
        [deferred, direct, always],
        allowed_tool_names={"tool.discovery", "calculator.compute", "sec.edgar.financials"},
    )

    exposed = set(surface.name_map.values())
    assert "tool.discovery" in exposed
    assert "calculator.compute" in exposed
    assert "sec.edgar.financials" not in exposed
    assert surface.deferred_tools[0]["name"] == "sec.edgar.financials"
    assert surface.to_parameters()["native_tool_deferred"][0]["load_hint"].startswith("Use tool.discovery")
