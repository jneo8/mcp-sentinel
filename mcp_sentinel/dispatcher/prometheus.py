"""Prometheus dispatcher orchestrates incident processing using watcher notifications."""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional

from loguru import logger

from ..models import (
    DispatcherResult,
    IncidentCard,
    IncidentNotification,
    PrometheusDispatcherSettings,
    SentinelSettings,
)
from ..interfaces import AgentOrchestrator


class PrometheusDispatcher:
    """Async dispatcher that routes Prometheus watcher notifications to agents."""

    def __init__(
        self,
        settings: SentinelSettings,
        agent_orchestrator: AgentOrchestrator,
        *,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._settings = settings
        self._agent = agent_orchestrator
        self._loop = loop or asyncio.get_event_loop()
        self._queue: "asyncio.Queue[IncidentNotification]" = asyncio.Queue(
            maxsize=settings.dispatcher.queue_size
        )
        self._card_index: Dict[str, IncidentCard] = {
            card.resource: card for card in settings.incident_cards
        }
        self._dedupe_cache: Dict[str, float] = {}
        self._workers: list[asyncio.Task[None]] = []
        self._running = False

    async def start(self) -> None:
        """Start worker tasks respecting configured concurrency."""

        if self._running:
            logger.debug("PrometheusDispatcher already running")
            return

        self._running = True
        concurrency = self._settings.dispatcher.worker_concurrency
        logger.info("Starting Prometheus dispatcher", concurrency=concurrency)
        for worker_id in range(concurrency):
            task = self._loop.create_task(self._worker_loop(worker_id))
            self._workers.append(task)

    async def stop(self) -> None:
        """Signal workers to stop and wait for graceful shutdown."""

        if not self._running:
            return

        self._running = False
        logger.info("Stopping Prometheus dispatcher", pending=self._queue.qsize())
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def dispatch(self, notification: IncidentNotification) -> DispatcherResult:
        """Accept a notification and enqueue it for processing."""

        self._purge_expired()
        dedupe_key = notification.resource.dedupe_key()
        ttl_seconds = self._settings.dispatcher.dedupe_ttl_seconds
        now = time.time()

        if dedupe_key in self._dedupe_cache and self._dedupe_cache[dedupe_key] > now:
            logger.debug(
                "Dropping duplicate alert",
                resource=notification.resource.name,
                dedupe_key=dedupe_key,
            )
            return DispatcherResult(status="duplicate", detail="dedupe cache hit")

        matched_card = self._card_index.get(notification.resource.name)
        if not matched_card:
            logger.warning(
                "No incident card mapped for resource", resource=notification.resource.name
            )
            return DispatcherResult(status="dropped", detail="no incident card")

        try:
            self._queue.put_nowait(notification)
        except asyncio.QueueFull:
            logger.error(
                "Dispatcher queue full, dropping alert",
                queue_size=self._queue.qsize(),
                resource=notification.resource.name,
            )
            return DispatcherResult(status="dropped", detail="queue full")

        self._dedupe_cache[dedupe_key] = now + ttl_seconds
        logger.info(
            "Queued notification for processing",
            resource=notification.resource.name,
            incident_card=matched_card.name,
        )
        return DispatcherResult(status="queued", incident_card=matched_card)

    async def _worker_loop(self, worker_id: int) -> None:
        logger.debug("Worker loop started", worker_id=worker_id)
        while self._running:
            try:
                notification = await self._queue.get()
            except asyncio.CancelledError:
                logger.debug("Worker cancelled", worker_id=worker_id)
                break

            try:
                await self._handle_notification(notification, worker_id)
            except Exception as exc:  # noqa: BLE001 - ensure resilience
                logger.exception(
                    "Unhandled error while processing notification",
                    worker_id=worker_id,
                    resource=notification.resource.name,
                )
                logger.debug("Error detail", error=str(exc))
            finally:
                self._queue.task_done()

        logger.debug("Worker loop exited", worker_id=worker_id)

    async def _handle_notification(
        self, notification: IncidentNotification, worker_id: int
    ) -> None:
        resource_name = notification.resource.name
        incident_card = self._card_index.get(resource_name)
        if not incident_card:
            logger.warning(
                "Skipping notification due to missing card",
                resource=resource_name,
                worker_id=worker_id,
            )
            return

        logger.bind(worker_id=worker_id).info(
            "Dispatching incident to agent",
            incident_card=incident_card.name,
            resource=resource_name,
        )

        await self._agent.run_incident(incident_card, notification)

    def _purge_expired(self) -> None:
        expiration_threshold = time.time()
        expired = [
            key for key, expires_at in self._dedupe_cache.items() if expires_at <= expiration_threshold
        ]
        for key in expired:
            del self._dedupe_cache[key]
        if expired:
            logger.debug("Purged expired dedupe entries", count=len(expired))
