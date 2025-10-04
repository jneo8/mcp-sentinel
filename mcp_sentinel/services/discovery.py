"""Utilities for discovering hosted MCP server capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, List

import httpx
from loguru import logger

from ..models import HostedMCPServer


DEFAULT_DISCOVERY_PATH = "/.well-known/mcp/tools"


def _merge_unique(preferred: Iterable[str], fallback: Iterable[str]) -> List[str]:
    merged: List[str] = []
    seen: set[str] = set()
    for name in list(preferred) + list(fallback):
        if not name or name in seen:
            continue
        merged.append(name)
        seen.add(name)
    return merged


def _extract_names(payload: object) -> List[str]:
    if isinstance(payload, dict):
        tools = payload.get("tools")
        if isinstance(tools, list):
            return _extract_names(tools)
        return []

    names: List[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                name = item.get("name") if isinstance(item, dict) else None
                if isinstance(name, str):
                    names.append(name)
    return names


def _build_discovery_url(server: HostedMCPServer) -> str | None:
    if not server.server_url:
        return None
    if server.discovery_url:
        return server.discovery_url

    base = server.server_url.rstrip("/")
    return f"{base}{DEFAULT_DISCOVERY_PATH}"


@dataclass
class HostedMCPDiscoveryClient:
    """Fetches tool metadata from hosted MCP servers."""

    http_client_factory: Callable[[], httpx.Client] | None = None

    def discover(self, server: HostedMCPServer) -> List[str]:
        configured = server.default_allowed_tools or []
        logger.info(
            "Using configured tools directly, skipping discovery",
            server=server.name,
            tools=configured,
        )
        return list(dict.fromkeys(configured))


__all__ = ["HostedMCPDiscoveryClient"]
