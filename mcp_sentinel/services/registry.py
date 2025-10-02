"""Tool registry abstractions for resolving Hosted MCP integrations."""

from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Sequence

from agents.tool import HostedMCPTool, MCPToolApprovalFunction, Tool
from loguru import logger

from ..models import HostedMCPServer


class ToolRegistry:
    """Resolves tool identifiers declared on incident cards into agent tool objects."""

    def __init__(
        self,
        servers: Sequence[HostedMCPServer],
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
    ) -> None:
        self._servers: Dict[str, HostedMCPServer] = {server.name: server for server in servers}
        self._approval_callback = approval_callback

    @classmethod
    def from_settings(
        cls,
        settings: "SentinelSettings",
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
    ) -> "ToolRegistry":
        """Convenience constructor feeding hosted MCP servers from settings."""

        return cls(settings.mcp_servers, approval_callback=approval_callback)

    def resolve(self, tool_identifiers: Sequence[str]) -> List[Tool]:
        """Return the list of tools applicable for the provided identifiers.

        Tool identifiers must use the ``server.tool`` format. Identifiers referencing unknown
        servers are ignored with a warning so that misconfigurations do not block other tools.
        """

        if not tool_identifiers:
            return []

        grouped: Dict[str, set[str]] = defaultdict(set)
        for identifier in tool_identifiers:
            server, sep, tool_name = identifier.partition(".")
            if not sep or not tool_name:
                logger.warning("Invalid tool identifier format", identifier=identifier)
                continue
            grouped[server].add(tool_name)

        resolved: List[Tool] = []
        for server_name, tool_names in grouped.items():
            server_config = self._servers.get(server_name)
            if not server_config:
                logger.warning(
                    "Skipping tools for unknown MCP server",
                    server=server_name,
                    requested_tools=sorted(tool_names),
                )
                continue

            tool_config = server_config.to_mcp_config(allowed_tools=sorted(tool_names))
            hosted_tool = HostedMCPTool(
                tool_config=tool_config, on_approval_request=self._approval_callback
            )
            resolved.append(hosted_tool)

        return resolved


__all__ = ["ToolRegistry"]
