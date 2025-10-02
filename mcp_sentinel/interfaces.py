"""Shared protocol/interface definitions for MCP Sentinel."""

from __future__ import annotations

from typing import Protocol

from .models import IncidentCard, IncidentNotification


class AgentOrchestrator(Protocol):
    """Orchestrates incident handling with the agent runtime."""

    async def run_incident(
        self, card: IncidentCard, notification: IncidentNotification
    ) -> None:
        """Execute an incident workflow for the given card and notification."""
