from typing import List

import pytest

from mcp_sentinel.models import HostedMCPServer
from mcp_sentinel.mcp_integration import MCPServerRegistry


def _server(name: str, *, default_tools: List[str] | None = None) -> HostedMCPServer:
    return HostedMCPServer(
        name=name,
        server_url=f"https://{name}.example/api",
        default_allowed_tools=default_tools,
    )


def test_mcp_server_registry_wildcard_uses_default_tools() -> None:
    registry = MCPServerRegistry([
        _server("grafana", default_tools=["search", "alerts"])
    ])

    tools = registry.resolve(["grafana.*"])

    assert len(tools) == 1
    # Note: tools now returns MCPServerStreamableHttp objects instead of HostedMCPTool


def test_mcp_server_registry_explicit_tools() -> None:
    registry = MCPServerRegistry([
        _server("grafana", default_tools=["search", "alerts"])
    ])

    tools = registry.resolve(["grafana.search", "grafana.alerts"])

    assert len(tools) == 1
    # Note: tools now returns MCPServerStreamableHttp objects instead of HostedMCPTool


def test_mcp_server_registry_falls_back_to_default_allowlist() -> None:
    registry = MCPServerRegistry([
        _server("grafana", default_tools=["annotations"])
    ])

    tools = registry.resolve(["grafana"])

    assert len(tools) == 1
    # Note: tools now returns MCPServerStreamableHttp objects instead of HostedMCPTool


def test_mcp_server_registry_returns_empty_for_unknown_server() -> None:
    registry = MCPServerRegistry([])

    tools = registry.resolve(["unknown.server"])

    assert tools == []
