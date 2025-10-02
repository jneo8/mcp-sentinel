from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

import pytest

from mcp_sentinel.agent.orchestrator import OpenAIAgentOrchestrator
from agents.tool import HostedMCPTool

from mcp_sentinel.models import (
    HostedMCPServer,
    IncidentCard,
    IncidentNotification,
    Resource,
    SentinelSettings,
)
from mcp_sentinel.prompts import PromptRepository


class StubRunner:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def run(self, starting_agent, input, **kwargs):  # noqa: ANN002, ANN003
        self.calls.append({"agent": starting_agent, "input": input, "kwargs": kwargs})
        return SimpleNamespace(final_output="incident resolved")


@pytest.mark.asyncio
async def test_agent_orchestrator_renders_prompt(tmp_path: Path) -> None:
    prompt_path = tmp_path / "prompts" / "card.md"
    prompt_path.parent.mkdir(parents=True, exist_ok=True)
    prompt_path.write_text(
        "Investigate ${resource_name} state ${resource_state}", encoding="utf-8"
    )

    settings = SentinelSettings()
    card = IncidentCard(
        name="latency",
        resource="web-tier",
        prompt_template=str(prompt_path.relative_to(tmp_path)),
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
        prompt_repository=PromptRepository(base_path=tmp_path),
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
async def test_agent_orchestrator_resolves_hosted_mcp_tools() -> None:
    settings = SentinelSettings(
        mcp_servers=[
            HostedMCPServer(
                name="mcp-juju",
                server_url="https://mcp.juju.example",
            )
        ]
    )
    card = IncidentCard(
        name="ceph-alert",
        resource="ceph-pg",
        prompt_template="Investigate",
        tools=["mcp-juju.controllers", "mcp-juju.exec"],
    )
    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="ceph-pg"),
    )

    runner = StubRunner()
    orchestrator = OpenAIAgentOrchestrator(settings, runner=runner)

    await orchestrator.run_incident(card, notification)

    tool_list = runner.calls[0]["agent"].tools
    assert tool_list, "Hosted MCP tool should be attached to agent"
    assert len(tool_list) == 1
    tool = tool_list[0]
    assert isinstance(tool, HostedMCPTool)
    assert tool.tool_config["server_label"] == "mcp-juju"
    assert tool.tool_config["server_url"] == "https://mcp.juju.example"
    assert tool.tool_config["allowed_tools"] == ["controllers", "exec"]
