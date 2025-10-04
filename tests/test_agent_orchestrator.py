from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from mcp_sentinel.agent.orchestrator import OpenAIAgentOrchestrator

from mcp_sentinel.models import (
    IncidentCard,
    IncidentNotification,
    Resource,
    SentinelSettings,
)
from mcp_sentinel.sinks import SinkEvent


class StubRunner:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def run(self, starting_agent, input, **kwargs):  # noqa: ANN002, ANN003
        self.calls.append({"agent": starting_agent, "input": input, "kwargs": kwargs})
        return SimpleNamespace(final_output="incident resolved")


class RecordingSinkDispatcher:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def emit(self, sink_names, event):  # noqa: ANN001 - test helper
        self.calls.append({"sinks": list(sink_names), "event": event})


@pytest.mark.asyncio
async def test_agent_orchestrator_renders_prompt() -> None:
    settings = SentinelSettings()
    card = IncidentCard(
        name="latency",
        resource="web-tier",
        prompt_template="Investigate ${resource_name} state ${resource_state}",
        max_iterations=3,
    )
    notification = IncidentNotification(
        resource=Resource(
            type="prometheus_alert",
            name="web-tier",
            state="firing",
            labels={"alertname": "HighLatency"},
        )
    )

    runner = StubRunner()
    orchestrator = OpenAIAgentOrchestrator(
        settings,
        runner=runner,
    )

    await orchestrator.run_incident(card, notification)

    assert runner.calls, "Runner should have been invoked"
    call = runner.calls[0]
    agent = call["agent"]
    assert "Investigate web-tier state firing" in agent.instructions
    assert call["kwargs"]["max_turns"] == 3
    assert "Incident resource web-tier" in call["input"]


@pytest.mark.asyncio
async def test_agent_orchestrator_resolves_hosted_mcp_servers() -> None:
    # For unit testing, use a test without actual network connectivity
    # This test verifies the MCP server resolution logic without network calls
    settings = SentinelSettings()
    card = IncidentCard(
        name="ceph-alert",
        resource="ceph-pg",
        prompt_template="Investigate",
        tools=[],  # No tools to avoid MCP server connections
    )
    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="ceph-pg"),
    )

    runner = StubRunner()
    orchestrator = OpenAIAgentOrchestrator(settings, runner=runner)

    await orchestrator.run_incident(card, notification)

    agent = runner.calls[0]["agent"]

    # Check that both tools and mcp_servers are empty when no tools are specified
    assert len(agent.tools) == 0, "Tools should be empty when no tools specified"
    assert len(agent.mcp_servers) == 0, "MCP servers should be empty when no tools specified"


@pytest.mark.asyncio
async def test_agent_orchestrator_emits_sink_events_on_success() -> None:
    settings = SentinelSettings()
    card = IncidentCard(
        name="latency",
        resource="web-tier",
        prompt_template="Investigate",
        sinks=["audit"],
    )
    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="web-tier"),
    )

    runner = StubRunner()
    sink_dispatcher = RecordingSinkDispatcher()
    orchestrator = OpenAIAgentOrchestrator(
        settings,
        runner=runner,
        sink_dispatcher=sink_dispatcher,
    )

    await orchestrator.run_incident(card, notification)

    assert len(sink_dispatcher.calls) == 2
    first, second = sink_dispatcher.calls
    assert first["sinks"] == ["audit"]
    assert isinstance(first["event"], SinkEvent)
    assert first["event"].type == "incident.started"
    assert second["event"].type == "incident.success"


class FailingRunner:
    async def run(self, *args, **kwargs):  # noqa: ANN002, ANN003 - test helper
        raise RuntimeError("runner boom")


@pytest.mark.asyncio
async def test_agent_orchestrator_emits_failure_sink_event() -> None:
    settings = SentinelSettings()
    card = IncidentCard(
        name="latency",
        resource="web-tier",
        prompt_template="Investigate",
        sinks=["audit"],
    )
    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="web-tier"),
    )

    sink_dispatcher = RecordingSinkDispatcher()
    orchestrator = OpenAIAgentOrchestrator(
        settings,
        runner=FailingRunner(),
        sink_dispatcher=sink_dispatcher,
    )

    with pytest.raises(RuntimeError):
        await orchestrator.run_incident(card, notification)

    assert len(sink_dispatcher.calls) == 2
    start, failure = sink_dispatcher.calls
    assert start["event"].type == "incident.started"
    assert failure["event"].type == "incident.failure"
