from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from holo_host.config import load_config
from holo_host.models import ProcessorTaskResult
from holo_host.store import QueueStore


def _write_fake_mcp_server(root: Path, *, extra_tool: bool = False) -> Path:
    server_path = root / "fake_mcp_server.py"
    extra = ', {"name": "danger.delete", "description": "blocked", "inputSchema": {"type": "object"}}' if extra_tool else ""
    server_path.write_text(
        textwrap.dedent(
            rf'''
            import json
            import sys

            for line in sys.stdin:
                message = json.loads(line)
                method = message.get("method")
                if method == "initialize":
                    print(json.dumps({{
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {{
                            "protocolVersion": "2025-11-25",
                            "capabilities": {{"tools": {{"listChanged": False}}, "resources": {{"listChanged": False}}}},
                            "serverInfo": {{"name": "fake-upstream", "version": "test"}}
                        }}
                    }}), flush=True)
                elif method == "notifications/initialized":
                    continue
                elif method == "tools/list":
                    print(json.dumps({{
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {{
                            "tools": [
                                {{"name": "echo", "description": "echo input", "inputSchema": {{"type": "object"}}}}
                                {extra}
                            ]
                        }}
                    }}), flush=True)
                elif method == "tools/call":
                    params = message.get("params", {{}})
                    args = params.get("arguments", {{}})
                    print(json.dumps({{
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {{
                            "content": [{{"type": "text", "text": args.get("value", "")}}],
                            "isError": False
                        }}
                    }}), flush=True)
                elif method == "resources/read":
                    print(json.dumps({{
                        "jsonrpc": "2.0",
                        "id": message["id"],
                        "result": {{
                            "contents": [{{"uri": message.get("params", {{}}).get("uri", ""), "mimeType": "text/plain", "text": "resource-ok"}}]
                        }}
                    }}), flush=True)
            '''
        ).strip(),
        encoding="utf-8",
    )
    return server_path


class Stage53McpUpstreamClientTests(unittest.TestCase):
    def test_stdio_client_initializes_lists_tools_and_calls_without_shell(self) -> None:
        from holo_host.mcp_upstream import McpStdioUpstreamClient

        with tempfile.TemporaryDirectory() as tmpdir:
            server_path = _write_fake_mcp_server(Path(tmpdir))
            client = McpStdioUpstreamClient([sys.executable, str(server_path)], timeout_seconds=5)
            tools = client.list_tools()
            result = client.call_tool("echo", {"value": "upstream-ok"})

        self.assertEqual(tools["tools"][0]["name"], "echo")
        self.assertEqual(result["content"][0]["text"], "upstream-ok")
        self.assertFalse(result["isError"])
        self.assertEqual(client.command[0], sys.executable)
        self.assertFalse(client.uses_shell)


class Stage53McpUpstreamHubTests(unittest.TestCase):
    def test_registry_loads_enabled_mcp_servers_from_holo_config(self) -> None:
        from holo_host.mcp_upstream import load_mcp_server_registry

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server_path = _write_fake_mcp_server(root)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[mcp_servers.echo]
enabled = true
command = [{json.dumps(sys.executable)}, {json.dumps(str(server_path))}]
allowed_tools = ["echo"]
timeout_seconds = 5
max_response_bytes = 500000

[mcp_servers.disabled]
enabled = false
command = [{json.dumps(sys.executable)}, {json.dumps(str(server_path))}]
""".strip(),
                encoding="utf-8",
            )

            registry = load_mcp_server_registry(config_path=str(config_path), repo_root=root)

        self.assertEqual(set(registry.servers), {"echo", "disabled"})
        self.assertTrue(registry.servers["echo"].enabled)
        self.assertFalse(registry.servers["disabled"].enabled)
        self.assertEqual(registry.servers["echo"].allowed_tools, ("echo",))
        self.assertEqual(registry.enabled_server_names(), ["echo"])

    def test_registry_allows_disabled_placeholder_servers_without_command(self) -> None:
        from holo_host.mcp_upstream import load_mcp_server_registry

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                """
[mcp_servers.browser]
enabled = false
allowed_tools = ["page_snapshot"]
""".strip(),
                encoding="utf-8",
            )

            registry = load_mcp_server_registry(config_path=str(config_path), repo_root=root)

        self.assertFalse(registry.servers["browser"].enabled)
        self.assertEqual(registry.servers["browser"].command, ())
        self.assertEqual(registry.enabled_server_names(), [])

    def test_hub_discovers_namespaced_allowed_tools_and_filters_denied_tools(self) -> None:
        from holo_host.mcp_upstream import McpUpstreamHub, McpUpstreamRegistry, McpUpstreamServerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            server_path = _write_fake_mcp_server(Path(tmpdir), extra_tool=True)
            registry = McpUpstreamRegistry(
                servers={
                    "toolbox": McpUpstreamServerConfig(
                        name="toolbox",
                        command=(sys.executable, str(server_path)),
                        allowed_tools=("echo",),
                        timeout_seconds=5,
                    )
                }
            )
            hub = McpUpstreamHub(registry)
            tools = hub.list_tools()

        self.assertEqual([tool["qualified_name"] for tool in tools["tools"]], ["toolbox.echo"])
        self.assertEqual(tools["tools"][0]["server"], "toolbox")
        self.assertEqual(tools["tools"][0]["name"], "echo")
        self.assertTrue(tools["boundary"]["upstream_results_are_observations"])
        self.assertFalse(tools["boundary"]["upstream_server_decision_authority"])

    def test_hub_calls_tool_as_observation_without_transport_or_memory_authority(self) -> None:
        from holo_host.mcp_upstream import McpUpstreamHub, McpUpstreamRegistry, McpUpstreamServerConfig, STAGE53_NAME

        with tempfile.TemporaryDirectory() as tmpdir:
            server_path = _write_fake_mcp_server(Path(tmpdir))
            registry = McpUpstreamRegistry(
                servers={
                    "toolbox": McpUpstreamServerConfig(
                        name="toolbox",
                        command=(sys.executable, str(server_path)),
                        allowed_tools=("echo",),
                        timeout_seconds=5,
                    )
                }
            )
            hub = McpUpstreamHub(registry)
            envelope = hub.call_tool("toolbox.echo", {"value": "hello-tool"})

        self.assertEqual(envelope["stage"], STAGE53_NAME)
        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["server"], "toolbox")
        self.assertEqual(envelope["tool"], "echo")
        self.assertEqual(envelope["result"]["content"][0]["text"], "hello-tool")
        self.assertTrue(envelope["boundary"]["wsl_kernel_authority"])
        self.assertTrue(envelope["boundary"]["upstream_results_are_observations"])
        self.assertFalse(envelope["boundary"]["transport_decision_authority"])
        self.assertFalse(envelope["boundary"]["self_memory_write_allowed"])
        self.assertFalse(envelope["boundary"]["shell_execution_via_mcp"])

    def test_hub_rejects_unknown_or_not_allowed_tools_before_process_launch(self) -> None:
        from holo_host.mcp_upstream import (
            McpToolNotAllowedError,
            McpUpstreamHub,
            McpUpstreamRegistry,
            McpUpstreamServerConfig,
        )

        registry = McpUpstreamRegistry(
            servers={
                "toolbox": McpUpstreamServerConfig(
                    name="toolbox",
                    command=(sys.executable, "-c", "raise SystemExit('should not launch')"),
                    allowed_tools=("echo",),
                    timeout_seconds=5,
                )
            }
        )
        hub = McpUpstreamHub(registry)

        with self.assertRaises(McpToolNotAllowedError):
            hub.call_tool("toolbox.danger.delete", {})
        with self.assertRaises(McpToolNotAllowedError):
            hub.call_tool("missing.echo", {})

    def test_hub_reads_resources_as_bounded_observations(self) -> None:
        from holo_host.mcp_upstream import McpUpstreamHub, McpUpstreamRegistry, McpUpstreamServerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            server_path = _write_fake_mcp_server(Path(tmpdir))
            registry = McpUpstreamRegistry(
                servers={
                    "docs": McpUpstreamServerConfig(
                        name="docs",
                        command=(sys.executable, str(server_path)),
                        timeout_seconds=5,
                    )
                }
            )
            hub = McpUpstreamHub(registry)
            envelope = hub.read_resource("docs", "doc://sample")

        self.assertTrue(envelope["ok"])
        self.assertEqual(envelope["server"], "docs")
        self.assertEqual(envelope["uri"], "doc://sample")
        self.assertEqual(envelope["result"]["contents"][0]["text"], "resource-ok")
        self.assertTrue(envelope["boundary"]["upstream_results_are_observations"])

    def test_cli_surfaces_status_list_and_call_for_upstream_tools(self) -> None:
        from holo_host.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            server_path = _write_fake_mcp_server(root)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[mcp_servers.toolbox]
enabled = true
command = [{json.dumps(sys.executable)}, {json.dumps(str(server_path))}]
allowed_tools = ["echo"]
timeout_seconds = 5
""".strip(),
                encoding="utf-8",
            )

            status_stdout = StringIO()
            with redirect_stdout(status_stdout):
                status_code = main(["--config", str(config_path), "show-mcp-upstream-status"])

            list_stdout = StringIO()
            with redirect_stdout(list_stdout):
                list_code = main(["--config", str(config_path), "list-mcp-upstream-tools"])

            call_stdout = StringIO()
            with redirect_stdout(call_stdout):
                call_code = main(
                    [
                        "--config",
                        str(config_path),
                        "call-mcp-tool",
                        "--tool",
                        "toolbox.echo",
                        "--arguments-json",
                        '{"value":"cli-ok"}',
                    ]
                )

        status_payload = json.loads(status_stdout.getvalue())
        list_payload = json.loads(list_stdout.getvalue())
        call_payload = json.loads(call_stdout.getvalue())
        self.assertEqual(status_code, 0)
        self.assertEqual(list_code, 0)
        self.assertEqual(call_code, 0)
        self.assertEqual(status_payload["servers"]["toolbox"]["enabled"], True)
        self.assertEqual(list_payload["tools"][0]["qualified_name"], "toolbox.echo")
        self.assertEqual(call_payload["result"]["content"][0]["text"], "cli-ok")
        self.assertTrue(call_payload["boundary"]["upstream_results_are_observations"])

    def test_engineering_agent_can_call_allowlisted_upstream_mcp_tool(self) -> None:
        from holo_host.engineering_agent import EngineeringAgentHarness

        class _McpPlanningRunner:
            def run_task(self, request):
                return ProcessorTaskResult(
                    task_type=request.task_type,
                    text=json.dumps(
                        {
                            "summary": "call upstream MCP tool",
                            "actions": [
                                {
                                    "tool": "mcp_call_tool",
                                    "mutation_class": "external_observation",
                                    "qualified_name": "toolbox.echo",
                                    "arguments": {"value": "agent-tool-ok"},
                                }
                            ],
                            "done": True,
                            "verification": "MCP observation captured",
                        },
                        ensure_ascii=False,
                    ),
                    returncode=0,
                    output_schema="json",
                    metadata={"provider": "deepseek", "model": "deepseek-v4-pro", "lane": "kernel_xhigh"},
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / ".holo_runtime").mkdir(parents=True)
            server_path = _write_fake_mcp_server(root)
            config_path = root / ".holo_host.toml"
            config_path.write_text(
                f"""
[runtime]
state_dir = ".holo_runtime"
db_path = ".holo_runtime/holo_host.sqlite3"
log_dir = ".holo_runtime/logs"
processor_backend = "deepseek"
api_port = 65511

[provider_backends.kernel_xhigh]
primary_provider = "deepseek"
backup_provider = "codex_cli"
model = "deepseek-v4-pro"
reasoning_effort = "xhigh"
max_output_tokens = 512

[mcp_servers.toolbox]
enabled = true
command = [{json.dumps(sys.executable)}, {json.dumps(str(server_path))}]
allowed_tools = ["echo"]
timeout_seconds = 5
""".strip(),
                encoding="utf-8",
            )
            config = load_config(config_path=str(config_path), repo_root=root)
            store = QueueStore(config.runtime.db_path)
            store.initialize()
            try:
                harness = EngineeringAgentHarness(config=config, store=store, runner=_McpPlanningRunner())
                result = harness.run(goal="use upstream MCP tool", thread_key="cli:stage53-mcp", max_steps=1)
            finally:
                store.close()

        action = result["steps"][0]["tool_loop"]["actions"][0]
        self.assertTrue(result["ok"], result)
        self.assertEqual(action["tool"], "mcp_call_tool")
        self.assertTrue(action["gate"]["allowed"])
        self.assertEqual(action["mutation_class"], "external_observation")
        self.assertEqual(action["observation"]["result"]["content"][0]["text"], "agent-tool-ok")
        self.assertTrue(action["observation"]["boundary"]["upstream_results_are_observations"])
        self.assertEqual(result["metrics"]["mcp_tool_count"], 1)
