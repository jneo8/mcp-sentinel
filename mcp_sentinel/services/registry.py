"""Tool registry abstractions for resolving Hosted MCP integrations."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set

import httpx
from agents.mcp import MCPServerStreamableHttp, MCPServerStreamableHttpParams
from agents.tool import MCPToolApprovalFunction
from loguru import logger

from ..models import HostedMCPServer
from .discovery import HostedMCPDiscoveryClient


@dataclass
class _GroupedTools:
    explicit: Set[str]
    wildcard: bool = False


def create_mcp_server(server_config: HostedMCPServer) -> MCPServerStreamableHttp:
    """Create an MCP server using the OpenAI Agents framework."""

    params = MCPServerStreamableHttpParams(
        url=server_config.server_url,
        timeout=30.0
    )

    # Add headers if configured
    if server_config.headers:
        params["headers"] = server_config.headers

    mcp_server = MCPServerStreamableHttp(
        params=params,
        name=server_config.name,
        cache_tools_list=True,
        client_session_timeout_seconds=30.0
    )

    logger.info(
        "Created MCP server",
        name=server_config.name,
        url=server_config.server_url
    )

    return mcp_server


class ToolRegistry:
    """Resolves tool identifiers declared on incident cards into agent tool objects."""

    def __init__(
        self,
        servers: Sequence[HostedMCPServer],
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
        discovery_client: HostedMCPDiscoveryClient | None = None,
    ) -> None:
        self._servers: Dict[str, HostedMCPServer] = {server.name: server for server in servers}
        self._approval_callback = approval_callback
        self._discovery = discovery_client or HostedMCPDiscoveryClient()
        self._discovered_cache: Dict[str, List[str]] = {}

    @classmethod
    def from_settings(
        cls,
        settings: "SentinelSettings",
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
        discovery_client: HostedMCPDiscoveryClient | None = None,
    ) -> "ToolRegistry":
        """Convenience constructor feeding hosted MCP servers from settings."""

        return cls(
            settings.mcp_servers,
            approval_callback=approval_callback,
            discovery_client=discovery_client,
        )

    def resolve(self, tool_identifiers: Sequence[str]) -> List[Tool]:
        """Return the list of tools applicable for the provided identifiers.

        Tool identifiers must use the ``server.tool`` format. Identifiers referencing unknown
        servers are ignored with a warning so that misconfigurations do not block other tools.
        """

        if not tool_identifiers:
            return []

        grouped: Dict[str, _GroupedTools] = defaultdict(lambda: _GroupedTools(set()))
        for identifier in tool_identifiers:
            identifier = identifier.strip()
            if not identifier:
                continue
            server, sep, tool_name = identifier.partition(".")
            if not server:
                logger.warning("Invalid tool identifier; missing server component", identifier=identifier)
                continue
            group = grouped[server]
            if not sep:
                group.wildcard = True
                continue
            if tool_name in {"", "*"}:
                group.wildcard = True
                continue
            group.explicit.add(tool_name)

        resolved: List[Tool] = []
        for server_name, grouped_tools in grouped.items():
            server_config = self._servers.get(server_name)
            if not server_config:
                logger.warning(
                    "Skipping tools for unknown MCP server",
                    server=server_name,
                    requested_tools=sorted(grouped_tools.explicit)
                    if grouped_tools.explicit
                    else None,
                    wildcard=grouped_tools.wildcard,
                )
                continue

            allowed_tools = self._derive_allowed_tools(server_config, grouped_tools)
            if allowed_tools is not None and not allowed_tools:
                logger.warning(
                    "No tools resolved for server",
                    server=server_name,
                )
                continue

            # Create MCP server for the OpenAI Agents framework
            mcp_server = create_mcp_server(server_config)

            # Return the MCP server instead of individual tools
            # Note: The Agent will need to be configured with mcp_servers instead of tools
            resolved.append(mcp_server)

        return resolved

    def _derive_allowed_tools(
        self, server: HostedMCPServer, grouped: _GroupedTools
    ) -> List[str] | None:
        explicit = grouped.explicit

        discovered = self._get_discovered_tools(server)
        discovered_set = set(discovered)

        if grouped.wildcard:
            if discovered:
                return discovered
            if server.default_allowed_tools:
                return list(dict.fromkeys(server.default_allowed_tools))
            # None signals to use server defaults
            logger.warning(
                "Wildcard request but no discovery data; falling back to unrestricted access",
                server=server.name,
            )
            return None

        if not explicit:
            if discovered:
                return discovered
            if server.default_allowed_tools:
                return list(dict.fromkeys(server.default_allowed_tools))
            return None

        if discovered:
            missing = sorted(explicit - discovered_set)
            if missing:
                logger.warning(
                    "Requested tools not advertised by server",
                    server=server.name,
                    requested=missing,
                )
            filtered = sorted(explicit & discovered_set)
            if filtered:
                return filtered
            logger.warning(
                "Using explicit tool list despite discovery miss",
                server=server.name,
                requested=sorted(explicit),
            )
            return sorted(explicit)

        return sorted(explicit)

    def _get_discovered_tools(self, server: HostedMCPServer) -> List[str]:
        if server.name in self._discovered_cache:
            return self._discovered_cache[server.name]

        try:
            discovered = self._discovery.discover(server)
        except Exception as exc:  # noqa: BLE001 - discovery should not break resolution
            logger.warning(
                "Hosted MCP discovery failed",
                server=server.name,
                error=str(exc),
            )
            discovered = []

        unique_discovered = list(dict.fromkeys(discovered))
        self._discovered_cache[server.name] = unique_discovered
        return unique_discovered


__all__ = ["ToolRegistry"]
