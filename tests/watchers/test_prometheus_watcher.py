import httpx
import pytest

from mcp_sentinel.models import (
    DispatcherResult,
    PrometheusWatcherSettings,
    ResourceDefinition,
    SentinelSettings,
)
from mcp_sentinel.watchers.prometheus import PrometheusWatcherService


class StubDispatcher:
    def __init__(self) -> None:
        self.notifications = []

    async def dispatch(self, notification):  # noqa: ANN001
        self.notifications.append(notification)
        return DispatcherResult(status="queued")


class StubHTTPClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []
        self.closed = False

    async def get(self, url, timeout=None):  # noqa: ANN001, D401
        self.calls.append({"url": url, "timeout": timeout})
        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return _StubResponse(payload)

    async def aclose(self):  # noqa: D401
        self.closed = True


class _StubResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):  # noqa: D401
        return None

    def json(self):  # noqa: D401
        return self._payload


@pytest.mark.asyncio
async def test_prometheus_watcher_dispatches_matching_alerts() -> None:
    settings = SentinelSettings(
        resources=[
            ResourceDefinition(
                name="web-tier",
                filters={"alertname": "HighLatency"},
            )
        ],
        watchers=[
            PrometheusWatcherSettings(
                name="primary",
                endpoint="https://prometheus.internal/api/v1",
                poll_interval="5s",
                resources=["web-tier"],
            )
        ],
    )
    dispatcher = StubDispatcher()
    client = StubHTTPClient(
        [
            {
                "data": {
                    "alerts": [
                        {
                            "labels": {"alertname": "HighLatency", "severity": "critical"},
                            "annotations": {"summary": "High latency detected"},
                            "status": "firing",
                            "startsAt": "2024-05-01T00:00:00Z",
                        }
                    ]
                }
            }
        ]
    )

    service = PrometheusWatcherService(settings=settings, dispatcher=dispatcher, http_client=client)

    dispatched = await service.poll_once()

    assert dispatched == 1
    assert len(dispatcher.notifications) == 1
    notification = dispatcher.notifications[0]
    assert notification.resource.name == "web-tier"
    assert notification.resource.state == "firing"
    assert notification.resource.labels["severity"] == "critical"
    assert notification.resource.annotations["summary"] == "High latency detected"
    assert client.calls[0]["url"].endswith("/api/v1/alerts")

    await service.stop()
    assert client.closed is True


@pytest.mark.asyncio
async def test_prometheus_watcher_skips_non_matching_alerts() -> None:
    settings = SentinelSettings(
        resources=[
            ResourceDefinition(
                name="web-tier",
                filters={"alertname": "HighLatency"},
            )
        ],
        watchers=[
            PrometheusWatcherSettings(
                name="primary",
                endpoint="https://prometheus.internal/api/v1",
                poll_interval="5s",
                resources=["web-tier"],
            )
        ],
    )
    dispatcher = StubDispatcher()
    client = StubHTTPClient(
        [
            {
                "data": {
                    "alerts": [
                        {
                            "labels": {"alertname": "OtherAlert"},
                            "annotations": {},
                            "status": "firing",
                        }
                    ]
                }
            }
        ]
    )

    service = PrometheusWatcherService(settings=settings, dispatcher=dispatcher, http_client=client)

    dispatched = await service.poll_once()

    assert dispatched == 0
    assert dispatcher.notifications == []

    await service.stop()


@pytest.mark.asyncio
async def test_prometheus_watcher_handles_request_errors() -> None:
    settings = SentinelSettings(
        watchers=[
            PrometheusWatcherSettings(
                name="primary",
                endpoint="https://prometheus.internal/api/v1",
                poll_interval=5,
                resources=["web-tier"],
            )
        ],
    )
    dispatcher = StubDispatcher()
    client = StubHTTPClient([httpx.ConnectError("boom")])

    service = PrometheusWatcherService(settings=settings, dispatcher=dispatcher, http_client=client)

    dispatched = await service.poll_once()

    assert dispatched == 0
    assert dispatcher.notifications == []

    await service.stop()
