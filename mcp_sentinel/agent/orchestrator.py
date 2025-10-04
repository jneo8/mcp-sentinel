"""Agent orchestrator backed by the openai-agents runtime."""

from __future__ import annotations

import json
from textwrap import shorten
from typing import Any, List, Protocol, Sequence

from agents import Agent, Runner
from agents.result import RunResult
from agents.run import RunConfig
from agents.tool import Tool
from loguru import logger

from ..interfaces import AgentOrchestrator
from ..models import IncidentCard, IncidentNotification, SentinelSettings
from ..prompts import PromptRenderer, PromptRepository
from ..mcp_integration import MCPServerRegistry
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


class OpenAIAgentOrchestrator(AgentOrchestrator):
    """Concrete orchestrator that delegates work to `openai-agents` Runner."""

    def __init__(
        self,
        settings: SentinelSettings,
        *,
        prompt_repository: PromptRepository | None = None,
        prompt_renderer: PromptRenderer | None = None,
        runner: RunnerProtocol | None = None,
        mcp_registry: MCPServerRegistry | None = None,
        sink_dispatcher: SinkDispatcher | None = None,
    ) -> None:
        self._settings = settings
        self._prompts = prompt_repository or PromptRepository()
        self._renderer = prompt_renderer or PromptRenderer()
        self._runner = runner or Runner
        self._mcp_registry = mcp_registry or MCPServerRegistry.from_settings(settings)
        self._sinks = sink_dispatcher or SinkDispatcher.from_settings(settings)

    async def run_incident(
        self, card: IncidentCard, notification: IncidentNotification
    ) -> None:
        logger.debug(
            "Starting incident response workflow",
            card_name=card.name,
            resource_name=notification.resource.name,
            resource_type=notification.resource.type,
            card_tools=card.tools,
        )

        instructions = self._render_instructions(card, notification)
        logger.debug(
            "Rendered agent instructions",
            card_name=card.name,
            instructions_length=len(instructions),
            instructions_preview=instructions[:200] + "..." if len(instructions) > 200 else instructions,
        )

        self._sinks.emit(card.sinks, incident_start_event(card, notification))

        logger.debug("Resolving MCP tools from card configuration", tools=card.tools)
        resolved_items = self._mcp_registry.resolve(card.tools)

        # Separate tools and MCP servers
        tools = []
        mcp_servers = []
        logger.debug(
            "Separating resolved items into tools and MCP servers",
            total_resolved_items=len(resolved_items),
        )

        for item in resolved_items:
            if hasattr(item, 'name') and hasattr(item, 'description'):  # Regular Tool
                logger.debug(
                    "Found regular tool in resolved items",
                    tool_name=getattr(item, 'name', 'unknown'),
                    tool_type=type(item).__name__,
                    has_description=hasattr(item, 'description')
                )
                tools.append(item)
            else:  # MCPServer
                logger.debug(
                    "Found MCP server in resolved items",
                    server_name=getattr(item, 'name', 'unknown'),
                    server_type=type(item).__name__,
                    server_url=getattr(getattr(item, 'params', None), 'url', 'unknown')
                )
                mcp_servers.append(item)

        logger.debug(
            "Tool/server separation completed",
            regular_tool_count=len(tools),
            mcp_server_count=len(mcp_servers),
            mcp_server_names=[getattr(server, 'name', 'unknown') for server in mcp_servers],
        )

        # Initialize MCP server connections
        logger.debug("Starting MCP server connections", server_count=len(mcp_servers))
        for mcp_server in mcp_servers:
            logger.debug(
                "Attempting to connect to MCP server",
                server_name=mcp_server.name,
                server_url=getattr(mcp_server.params, 'url', 'unknown'),
                server_timeout=getattr(mcp_server.params, 'timeout', 'unknown'),
                cache_enabled=getattr(mcp_server, 'cache_tools_list', 'unknown'),
            )
            try:
                await mcp_server.connect()
                logger.info(
                    "Connected to MCP server",
                    server_name=mcp_server.name,
                )
                logger.debug(
                    "MCP server connection established successfully",
                    server_name=mcp_server.name,
                    server_url=getattr(mcp_server.params, 'url', 'unknown'),
                    connection_status="connected",
                )
            except Exception as exc:
                logger.error(
                    "Failed to connect to MCP server",
                    server_name=mcp_server.name,
                    server_url=getattr(mcp_server.params, 'url', 'unknown'),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                raise

        agent_name = f"{card.name}-agent"
        agent_model = card.model or self._settings.openai.model

        logger.debug(
            "Creating OpenAI agent",
            agent_name=agent_name,
            model=agent_model,
            regular_tool_count=len(tools),
            mcp_server_count=len(mcp_servers),
            instructions_length=len(instructions),
        )

        agent = Agent(
            name=agent_name,
            instructions=instructions,
            tools=tools,
            mcp_servers=mcp_servers,
            model=agent_model,
        )

        logger.debug("Agent created successfully", agent_name=agent_name)

        initial_input = self._build_initial_input(notification)
        logger.debug(
            "Built initial input for agent",
            input_length=len(initial_input),
            input_preview=initial_input[:200] + "..." if len(initial_input) > 200 else initial_input,
        )

        run_config = RunConfig(
            workflow_name=f"incident::{card.name}",
            trace_metadata={
                "resource": notification.resource.name,
                "card": card.name,
            },
        )

        logger.debug(
            "Created run configuration",
            workflow_name=run_config.workflow_name,
            trace_metadata=run_config.trace_metadata,
        )

        logger.info(
            "Starting agent run",
            card=card.name,
            resource=notification.resource.name,
            model=agent.model,
            initial_input=initial_input,
            instructions_preview=instructions[:200],
            max_iterations=card.max_iterations,
        )

        logger.debug(
            "Executing agent run",
            max_turns=card.max_iterations,
            workflow_name=run_config.workflow_name,
        )

        try:
            result = await self._runner.run(
                agent,
                initial_input,
                max_turns=card.max_iterations,
                run_config=run_config,
            )
            logger.debug(
                "Agent run completed successfully",
                card=card.name,
                turn_count=getattr(result, 'turn_count', 'unknown'),
                status=getattr(result, 'status', 'unknown'),
                is_finished=getattr(result, 'is_finished', 'unknown'),
            )

            logger.debug("Emitting success event and logging results")
            self._emit_success_event(card, notification, result)
            self._log_result(card, notification, result)

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "Agent run failed with exception",
                card=card.name,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            self._emit_failure_event(card, notification, exc)
            logger.exception(
                "Agent run failed",
                card=card.name,
                resource=notification.resource.name,
                error=str(exc),
            )
            raise

        finally:
            # Clean up MCP server connections in finally block to ensure they're always cleaned up
            logger.debug(
                "Starting MCP server cleanup",
                server_count=len(mcp_servers),
                server_names=[mcp_server.name for mcp_server in mcp_servers]
            )
            await self._cleanup_mcp_servers(mcp_servers)

        logger.debug("Incident response workflow completed", card=card.name)

    async def _cleanup_mcp_servers(self, mcp_servers: List[Any]) -> None:
        """Clean up MCP server connections, handling async generators properly."""
        for mcp_server in mcp_servers:
            logger.debug(
                "Cleaning up MCP server connection",
                server_name=mcp_server.name,
                server_url=getattr(mcp_server.params, 'url', 'unknown'),
                cleanup_action="starting_cleanup"
            )
            try:
                # Try to close any HTTP client sessions first to avoid async generator issues
                if hasattr(mcp_server, '_client') and mcp_server._client:
                    if hasattr(mcp_server._client, 'aclose'):
                        logger.debug(
                            "Closing HTTP client session",
                            server_name=mcp_server.name,
                            cleanup_action="client_aclose"
                        )
                        await mcp_server._client.aclose()

                # Try to close any async generators in the HTTP streamable client
                if hasattr(mcp_server, '_http_client') and mcp_server._http_client:
                    if hasattr(mcp_server._http_client, 'aclose'):
                        logger.debug(
                            "Closing HTTP streamable client",
                            server_name=mcp_server.name,
                            cleanup_action="http_client_aclose"
                        )
                        await mcp_server._http_client.aclose()

                # Call the standard cleanup method
                await mcp_server.cleanup()
                logger.debug(
                    "Successfully cleaned up MCP server",
                    server_name=mcp_server.name,
                    cleanup_status="success"
                )
            except Exception as exc:
                logger.warning(
                    "Failed to cleanup MCP server",
                    server_name=mcp_server.name,
                    server_url=getattr(mcp_server.params, 'url', 'unknown'),
                    error=str(exc),
                    error_type=type(exc).__name__,
                    cleanup_status="failed"
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
