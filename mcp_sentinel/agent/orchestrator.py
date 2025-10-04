"""Agent orchestrator backed by the openai-agents runtime."""

from __future__ import annotations

import json
from textwrap import shorten
from typing import Any, Protocol, Sequence

from agents import Agent, Runner
from agents.result import RunResult
from agents.run import RunConfig
from agents.tool import Tool
from loguru import logger

from ..interfaces import AgentOrchestrator
from ..models import IncidentCard, IncidentNotification, SentinelSettings
from ..prompts import PromptRenderer, PromptRepository
from ..services import ToolRegistry
from ..sinks import (
    SinkDispatcher,
    incident_completion_event,
    incident_start_event,
)


class RunnerProtocol(Protocol):
    """Protocol abstraction for agents.Runner to enable dependency injection in tests."""

    async def run(
        self,
        starting_agent: Agent[Any],
        input: str,
        *,
        context: Any | None = None,
        max_turns: int = 10,
        hooks: Any | None = None,
        run_config: RunConfig | None = None,
        previous_response_id: str | None = None,
        conversation_id: str | None = None,
        session: Any | None = None,
    ) -> RunResult:
        ...


class ToolResolver:
    """Best-effort resolver converting incident card tool identifiers to agent tools."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self._registry = registry

    def resolve(self, tool_identifiers: Sequence[str]) -> list[Tool]:
        if not tool_identifiers:
            return []
        if not self._registry:
            logger.warning(
                "Tool registry not configured; ignoring tool identifiers",
                tools=list(tool_identifiers),
            )
            return []
        resolved = self._registry.resolve(tool_identifiers)
        if not resolved:
            logger.warning(
                "No tools resolved for incident card",
                tools=list(tool_identifiers),
            )
        return resolved


class OpenAIAgentOrchestrator(AgentOrchestrator):
    """Concrete orchestrator that delegates work to `openai-agents` Runner."""

    def __init__(
        self,
        settings: SentinelSettings,
        *,
        prompt_repository: PromptRepository | None = None,
        prompt_renderer: PromptRenderer | None = None,
        runner: RunnerProtocol | None = None,
        tool_resolver: ToolResolver | None = None,
        tool_registry: ToolRegistry | None = None,
        sink_dispatcher: SinkDispatcher | None = None,
    ) -> None:
        self._settings = settings
        self._prompts = prompt_repository or PromptRepository()
        self._renderer = prompt_renderer or PromptRenderer()
        self._runner = runner or Runner
        registry = tool_registry or ToolRegistry.from_settings(settings)
        self._tool_resolver = tool_resolver or ToolResolver(registry)
        self._sinks = sink_dispatcher or SinkDispatcher.from_settings(settings)

    async def run_incident(
        self, card: IncidentCard, notification: IncidentNotification
    ) -> None:
        instructions = self._render_instructions(card, notification)
        self._sinks.emit(card.sinks, incident_start_event(card, notification))
        resolved_items = self._tool_resolver.resolve(card.tools)

        # Separate tools and MCP servers
        tools = []
        mcp_servers = []
        for item in resolved_items:
            if hasattr(item, 'name') and hasattr(item, 'description'):  # Regular Tool
                tools.append(item)
            else:  # MCPServer
                mcp_servers.append(item)

        # Initialize MCP server connections
        for mcp_server in mcp_servers:
            try:
                await mcp_server.connect()
                logger.info(
                    "Connected to MCP server",
                    server_name=mcp_server.name,
                )
            except Exception as exc:
                logger.error(
                    "Failed to connect to MCP server",
                    server_name=mcp_server.name,
                    error=str(exc),
                )
                raise

        agent = Agent(
            name=f"{card.name}-agent",
            instructions=instructions,
            tools=tools,
            mcp_servers=mcp_servers,
            model=card.model or self._settings.openai.model,
        )

        initial_input = self._build_initial_input(notification)
        run_config = RunConfig(
            workflow_name=f"incident::{card.name}",
            trace_metadata={
                "resource": notification.resource.name,
                "card": card.name,
            },
        )

        logger.info(
            "Starting agent run",
            card=card.name,
            resource=notification.resource.name,
            model=agent.model,
            initial_input=initial_input,
            instructions_preview=instructions[:200],
        )

        try:
            result = await self._runner.run(
                agent,
                initial_input,
                max_turns=card.max_iterations,
                run_config=run_config,
            )
        except Exception as exc:  # noqa: BLE001
            self._emit_failure_event(card, notification, exc)
            logger.exception(
                "Agent run failed",
                card=card.name,
                resource=notification.resource.name,
                error=str(exc),
            )
            raise

        self._emit_success_event(card, notification, result)
        self._log_result(card, notification, result)

        # Clean up MCP server connections
        for mcp_server in mcp_servers:
            try:
                await mcp_server.cleanup()
                logger.debug("Cleaned up MCP server", server_name=mcp_server.name)
            except Exception as exc:
                logger.warning(
                    "Failed to cleanup MCP server",
                    server_name=mcp_server.name,
                    error=str(exc),
                )

    def _render_instructions(
        self, card: IncidentCard, notification: IncidentNotification
    ) -> str:
        template = self._prompts.load(card.prompt_template)
        return self._renderer.render(template, notification)

    def _build_initial_input(self, notification: IncidentNotification) -> str:
        resource = notification.resource
        lines = [
            f"Incident resource {resource.name} ({resource.type})",
            f"State: {resource.state or 'unknown'} | Value: {resource.value or ''}",
        ]
        if resource.labels:
            lines.append(
                "Labels: "
                + ", ".join(sorted(f"{key}={value}" for key, value in resource.labels.items()))
            )
        if resource.annotations:
            lines.append(
                "Annotations: "
                + ", ".join(
                    sorted(f"{key}={value}" for key, value in resource.annotations.items())
                )
            )
        if notification.raw_payload:
            payload_preview = shorten(json.dumps(notification.raw_payload, default=str), width=480)
            lines.append(f"Raw payload: {payload_preview}")
        return "\n".join(lines)

    def _log_result(
        self,
        card: IncidentCard,
        notification: IncidentNotification,
        result: RunResult,
    ) -> None:
        final_output = getattr(result, "final_output", None)
        turn_count = getattr(result, "turn_count", None)
        is_finished = getattr(result, "is_finished", None)
        status = getattr(result, "status", None)
        preview = shorten(str(final_output), width=240) if final_output is not None else "<none>"

        # Always log the complete final result for visibility
        logger.info(
            f"Agent run completed - Final Output:\n{final_output or '<NO OUTPUT PRODUCED>'}",
        )

        logger.info(
            "Agent run metadata",
            card=card.name,
            resource=notification.resource.name,
            turn_count=turn_count,
            is_finished=is_finished,
            status=status,
            result_type=type(result).__name__,
        )

    def _emit_success_event(
        self,
        card: IncidentCard,
        notification: IncidentNotification,
        result: RunResult,
    ) -> None:
        payload = {
            "final_output": getattr(result, "final_output", None),
            "turn_count": getattr(result, "turn_count", None),
        }
        event = incident_completion_event(
            card,
            notification,
            outcome="success",
            result_payload=payload,
        )
        self._sinks.emit(card.sinks, event)

    def _emit_failure_event(
        self,
        card: IncidentCard,
        notification: IncidentNotification,
        error: Exception,
    ) -> None:
        payload = {"error": str(error)}
        event = incident_completion_event(
            card,
            notification,
            outcome="failure",
            result_payload=payload,
        )
        self._sinks.emit(card.sinks, event)
