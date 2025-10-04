import asyncio
from typing import List

import pytest

from mcp_sentinel.dispatcher.prometheus import PrometheusDispatcher
from mcp_sentinel.models import (
    IncidentCard,
    IncidentNotification,
    PrometheusDispatcherSettings,
    Resource,
    SentinelSettings,
)


class StubAgent:
    def __init__(self) -> None:
        self.calls: List[IncidentNotification] = []

    async def run_incident(self, card: IncidentCard, notification: IncidentNotification) -> None:
        await asyncio.sleep(0)  # force context switch
        self.calls.append(notification)


@pytest.mark.asyncio
async def test_dispatcher_processes_notification() -> None:
    settings = SentinelSettings(
        incident_cards=[
            IncidentCard(
                name="high-latency",
                resource="web-tier",
                prompt_template="prompts/high-latency.md",
            )
        ],
        dispatcher=PrometheusDispatcherSettings(queue_size=10, worker_concurrency=1),
    )

    agent = StubAgent()
    dispatcher = PrometheusDispatcher(settings=settings, agent_orchestrator=agent)

    await dispatcher.start()

    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="web-tier")
    )

    result = await dispatcher.dispatch(notification)
    assert result.status == "queued"

    await asyncio.wait_for(dispatcher._queue.join(), timeout=1)  # type: ignore[attr-defined]
    await dispatcher.stop()

    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_dispatcher_dedupes_notifications() -> None:
    settings = SentinelSettings(
        incident_cards=[
            IncidentCard(
                name="high-latency",
                resource="web-tier",
                prompt_template="prompts/high-latency.md",
            )
        ],
        dispatcher=PrometheusDispatcherSettings(queue_size=10, dedupe_ttl_seconds=300),
    )

    agent = StubAgent()
    dispatcher = PrometheusDispatcher(settings=settings, agent_orchestrator=agent)

    await dispatcher.start()

    resource = Resource(type="prometheus_alert", name="web-tier")
    first_result = await dispatcher.dispatch(IncidentNotification(resource=resource))
    second_result = await dispatcher.dispatch(IncidentNotification(resource=resource))

    await asyncio.wait_for(dispatcher._queue.join(), timeout=1)  # type: ignore[attr-defined]
    await dispatcher.stop()

    assert first_result.status == "queued"
    assert second_result.status == "duplicate"
    assert len(agent.calls) == 1


@pytest.mark.asyncio
async def test_dispatcher_drops_when_no_card() -> None:
    settings = SentinelSettings(incident_cards=[])
    agent = StubAgent()
    dispatcher = PrometheusDispatcher(settings=settings, agent_orchestrator=agent)

    await dispatcher.start()

    notification = IncidentNotification(
        resource=Resource(type="prometheus_alert", name="unknown")
    )

    result = await dispatcher.dispatch(notification)
    await dispatcher.stop()

    assert result.status == "dropped"
    assert result.detail == "no incident card"
    assert agent.calls == []
