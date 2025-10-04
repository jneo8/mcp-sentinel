"""MCP server registry for managing MCP server connections and tool resolution."""

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


@dataclass
class _GroupedTools:
    explicit: Set[str]
    wildcard: bool = False


def create_mcp_server(server_config: HostedMCPServer) -> MCPServerStreamableHttp:
    """Create an MCP server using the OpenAI Agents framework."""

    logger.debug(
        "Creating MCP server instance",
        name=server_config.name,
        url=server_config.server_url,
        default_tools=server_config.default_allowed_tools,
        headers_configured=bool(server_config.headers),
    )

    params = MCPServerStreamableHttpParams(
        url=server_config.server_url,
        timeout=30.0
    )

    # Add headers if configured
    if server_config.headers:
        logger.debug(
            "Adding HTTP headers to MCP server",
            name=server_config.name,
            header_count=len(server_config.headers),
        )
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
        url=server_config.server_url,
        timeout=30.0,
        cache_enabled=True,
    )

    return mcp_server


class MCPServerRegistry:
    """Manages MCP server connections and resolves tool identifiers into MCP server instances."""

    def __init__(
        self,
        servers: Sequence[HostedMCPServer],
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
    ) -> None:
        self._servers: Dict[str, HostedMCPServer] = {server.name: server for server in servers}

    @classmethod
    def from_settings(
        cls,
        settings: "SentinelSettings",
        *,
        approval_callback: MCPToolApprovalFunction | None = None,
    ) -> "MCPServerRegistry":
        """Convenience constructor feeding hosted MCP servers from settings."""

        logger.debug(
            "Creating MCPServerRegistry from settings",
            server_count=len(settings.mcp_servers),
            server_names=[server.name for server in settings.mcp_servers],
            approval_callback_configured=approval_callback is not None,
        )

        return cls(
            settings.mcp_servers,
            approval_callback=approval_callback,
        )

    def resolve(self, tool_identifiers: Sequence[str]) -> List[Tool]:
        """Return the list of MCP servers applicable for the provided tool identifiers.

        Tool identifiers must use the ``server.tool`` format. Identifiers referencing unknown
        servers are ignored with a warning so that misconfigurations do not block other tools.

        Includes warning logic previously in ToolResolver for better error handling.
        """

        logger.debug(
            "Starting tool identifier resolution",
            tool_identifiers=list(tool_identifiers),
            identifier_count=len(tool_identifiers),
        )

        if not tool_identifiers:
            logger.warning(
                "No tool identifiers provided to resolve",
                tools=list(tool_identifiers),
            )
            return []

        grouped: Dict[str, _GroupedTools] = defaultdict(lambda: _GroupedTools(set()))
        for identifier in tool_identifiers:
            identifier = identifier.strip()
            if not identifier:
                logger.debug("Skipping empty tool identifier")
                continue
            server, sep, tool_name = identifier.partition(".")
            logger.debug(
                "Parsing tool identifier",
                original_identifier=identifier,
                parsed_server=server,
                parsed_tool_name=tool_name,
                has_separator=bool(sep),
            )
            if not server:
                logger.warning("Invalid tool identifier; missing server component", identifier=identifier)
                continue
            group = grouped[server]
            if not sep:
                logger.debug(
                    "Tool identifier is wildcard (no separator)",
                    identifier=identifier,
                    server=server,
                    action="setting_wildcard_true"
                )
                group.wildcard = True
                continue
            if tool_name in {"", "*"}:
                logger.debug(
                    "Tool identifier is wildcard (explicit)",
                    identifier=identifier,
                    server=server,
                    tool_name=tool_name,
                    action="setting_wildcard_true"
                )
                group.wildcard = True
                continue
            logger.debug(
                "Adding explicit tool to server group",
                identifier=identifier,
                server=server,
                tool_name=tool_name,
                current_explicit_tools=sorted(group.explicit)
            )
            group.explicit.add(tool_name)

        logger.debug(
            "Grouped tool identifiers by server",
            grouped_servers=list(grouped.keys()),
            grouping_details={
                server: {
                    "explicit_tools": sorted(group.explicit),
                    "wildcard": group.wildcard
                }
                for server, group in grouped.items()
            }
        )

        resolved: List[Tool] = []
        for server_name, grouped_tools in grouped.items():
            logger.debug(
                "Processing server for tool resolution",
                server=server_name,
                explicit_tools=sorted(grouped_tools.explicit),
                wildcard=grouped_tools.wildcard,
            )

            server_config = self._servers.get(server_name)
            if not server_config:
                logger.warning(
                    "Skipping tools for unknown MCP server",
                    server=server_name,
                    requested_tools=sorted(grouped_tools.explicit)
                    if grouped_tools.explicit
                    else None,
                    wildcard=grouped_tools.wildcard,
                    available_servers=list(self._servers.keys()),
                )
                continue

            logger.debug(
                "Found server configuration",
                server=server_name,
                server_url=server_config.server_url,
                default_allowed_tools=server_config.default_allowed_tools,
            )

            allowed_tools = self._derive_allowed_tools(server_config, grouped_tools)
            logger.debug(
                "Derived allowed tools for server",
                server=server_name,
                allowed_tools=allowed_tools,
                tool_count=len(allowed_tools) if allowed_tools else 0,
            )

            if allowed_tools is not None and not allowed_tools:
                logger.warning(
                    "No tools resolved for server",
                    server=server_name,
                )
                continue

            # Create MCP server for the OpenAI Agents framework
            logger.debug("Creating MCP server instance for agent", server=server_name)
            mcp_server = create_mcp_server(server_config)
            logger.debug("Successfully created MCP server instance", server=server_name)

            # Return the MCP server instead of individual tools
            # Note: The Agent will need to be configured with mcp_servers instead of tools
            resolved.append(mcp_server)

        logger.debug(
            "Tool resolution completed",
            total_resolved_servers=len(resolved),
            resolved_server_names=[getattr(server, 'name', 'unknown') for server in resolved],
            original_tool_identifiers=list(tool_identifiers),
        )

        if not resolved:
            logger.warning(
                "No MCP servers resolved from tool identifiers",
                tools=list(tool_identifiers),
                available_servers=list(self._servers.keys()),
            )

        return resolved

    def _derive_allowed_tools(
        self, server: HostedMCPServer, grouped: _GroupedTools
    ) -> List[str] | None:
        explicit = grouped.explicit

        if grouped.wildcard:
            if server.default_allowed_tools:
                return list(dict.fromkeys(server.default_allowed_tools))
            # None signals to use server defaults
            return None

        if not explicit:
            if server.default_allowed_tools:
                return list(dict.fromkeys(server.default_allowed_tools))
            return None

        return sorted(explicit)



__all__ = ["MCPServerRegistry"]
