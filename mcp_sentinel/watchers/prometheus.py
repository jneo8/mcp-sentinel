"""Prometheus watcher implementation that polls alert endpoints."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any, Dict, List, Protocol, Sequence
from urllib.parse import urljoin

import httpx
from loguru import logger

from ..models import (
    DispatcherResult,
    IncidentNotification,
    PrometheusWatcherSettings,
    Resource,
    ResourceDefinition,
    SentinelSettings,
)


class DispatcherProtocol(Protocol):
    """Protocol describing the dispatcher contract used by watchers."""

    async def dispatch(self, notification: IncidentNotification) -> DispatcherResult:
        ...


class PrometheusWatcher:
    """Polls a Prometheus endpoint and forwards matching alerts to the dispatcher."""

    def __init__(
        self,
        config: PrometheusWatcherSettings,
        dispatcher: DispatcherProtocol,
        resource_index: Dict[str, ResourceDefinition],
        http_client: httpx.AsyncClient,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
    ) -> None:
        self._config = config
        self._dispatcher = dispatcher
        self._client = http_client
        self._loop = loop or asyncio.get_event_loop()
        self._alerts_url = _derive_alerts_url(config.endpoint)
        self._poll_interval = config.poll_interval_seconds
        self._timeout = config.timeout_seconds

        self._resource_defs: List[ResourceDefinition] = []
        for resource_name in config.resources:
            resource_def = resource_index.get(resource_name)
            if resource_def is None:
                logger.warning(
                    "Watcher references unknown resource; defaulting to alertname filter",
                    watcher=config.name,
                    resource=resource_name,
                )
                resource_def = ResourceDefinition(
                    name=resource_name,
                    filters={"alertname": resource_name},
                )
            self._resource_defs.append(resource_def)

        if not self._resource_defs:
            logger.warning(
                "Prometheus watcher configured without resources; no alerts will be dispatched",
                watcher=config.name,
            )

        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        if self._task is not None:
            return
        self._running = True
        self._task = self._loop.create_task(self._poll_loop())
        logger.info("Prometheus watcher started", watcher=self._config.name)

    async def stop(self) -> None:
        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None
        logger.info("Prometheus watcher stopped", watcher=self._config.name)

    async def poll_once(self) -> int:
        """Fetch alerts once and dispatch any matches."""

        alerts = await self._fetch_alerts()
        if not alerts or not self._resource_defs:
            return 0

        dispatched = 0
        for alert in alerts:
            dispatched += await self._handle_alert(alert)
        if dispatched:
            logger.debug(
                "Dispatched incidents from Prometheus poll",
                watcher=self._config.name,
                dispatched=dispatched,
            )
        return dispatched

    async def _poll_loop(self) -> None:
        try:
            while self._running:
                try:
                    await self.poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # noqa: BLE001 - guard loop from crashing
                    logger.exception(
                        "Prometheus watcher poll failed",
                        watcher=self._config.name,
                        error=str(exc),
                    )
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:  # pragma: no cover - normal shutdown
            pass

    async def _fetch_alerts(self) -> Sequence[Dict[str, Any]]:
        try:
            response = await self._client.get(
                self._alerts_url,
                timeout=self._timeout,
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            logger.warning(
                "Prometheus request failed",
                watcher=self._config.name,
                error=str(exc),
            )
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Prometheus responded with error status",
                watcher=self._config.name,
                status_code=exc.response.status_code,
            )
            return []

        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to decode Prometheus response",
                watcher=self._config.name,
                error=str(exc),
            )
            return []

        alerts = payload.get("data", {}).get("alerts", [])
        if not isinstance(alerts, list):  # pragma: no cover - defensive
            logger.warning(
                "Unexpected alerts payload format",
                watcher=self._config.name,
                payload_type=type(alerts).__name__,
            )
            return []
        return alerts

    async def _handle_alert(self, alert: Dict[str, Any]) -> int:
        labels = dict(alert.get("labels") or {})
        annotations = dict(alert.get("annotations") or {})
        dispatched = 0

        for resource_def in self._resource_defs:
            if not _matches_filters(labels, resource_def.filters):
                continue

            resource_annotations = {**resource_def.annotations, **annotations}
            status = alert.get("status")
            if isinstance(status, dict):
                state = status.get("state") or status.get("value")
            else:
                state = status

            value = alert.get("value")
            if value is not None:
                value = str(value)

            timestamp = alert.get("startsAt") or alert.get("activeAt")

            resource = Resource(
                type=resource_def.type,
                name=resource_def.name,
                labels=labels,
                annotations=resource_annotations,
                state=state,
                value=value,
                timestamp=timestamp,
            )

            notification = IncidentNotification(resource=resource, raw_payload=alert)
            result = await self._dispatcher.dispatch(notification)
            logger.debug(
                "Prometheus watcher dispatched notification",
                watcher=self._config.name,
                resource=resource_def.name,
                status=result.status,
            )
            if result.status == "queued":
                dispatched += 1
        return dispatched


class PrometheusWatcherService:
    """Coordinates one or more Prometheus watchers based on Sentinel settings."""

    def __init__(
        self,
        settings: SentinelSettings,
        dispatcher: DispatcherProtocol,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._dispatcher = dispatcher
        self._resource_index = {resource.name: resource for resource in settings.resources}
        self._watcher_configs = [
            watcher for watcher in settings.watchers if watcher.type == "prometheus"
        ]
        self._client = http_client or httpx.AsyncClient()
        self._owns_client = http_client is None
        self._watchers: List[PrometheusWatcher] = [
            PrometheusWatcher(
                config,
                dispatcher,
                self._resource_index,
                self._client,
                loop=self._loop,
            )
            for config in self._watcher_configs
        ]

    async def start(self) -> None:
        if not self._watchers:
            logger.info("No Prometheus watchers configured; skipping startup")
            return
        for watcher in self._watchers:
            await watcher.start()

    async def stop(self) -> None:
        for watcher in self._watchers:
            await watcher.stop()
        try:
            await self._client.aclose()
        except Exception as exc:  # noqa: BLE001 - ensure shutdown continues
            logger.warning(
                "Failed to close Prometheus watcher HTTP client",
                error=str(exc),
            )

    async def poll_once(self) -> int:
        """Trigger a single poll across all configured watchers (useful for tests)."""

        dispatched = 0
        for watcher in self._watchers:
            dispatched += await watcher.poll_once()
        return dispatched


def _derive_alerts_url(endpoint: str) -> str:
    trimmed = endpoint.rstrip("/")
    if trimmed.endswith("/alerts"):
        return trimmed
    base = trimmed + "/"
    url = urljoin(base, "alerts")
    return url.rstrip("/")


def _matches_filters(labels: Dict[str, str], filters: Dict[str, str]) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        if labels.get(key) != expected:
            return False
    return True


__all__ = ["PrometheusWatcherService", "PrometheusWatcher"]
