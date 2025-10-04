"""Sink implementations responsible for emitting audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from loguru import logger

from ..models import IncidentCard, IncidentNotification, SentinelSettings, SinkConfig


@dataclass(frozen=True)
class SinkEvent:
    """Structured event emitted to configured sinks."""

    type: str
    card_name: str
    resource_name: str
    message: str
    payload: Mapping[str, Any] = field(default_factory=dict)


class Sink:
    """Protocol for sink implementations."""

    def emit(self, event: SinkEvent) -> None:  # pragma: no cover - interface definition
        raise NotImplementedError


class LoggingSink(Sink):
    """Simple sink that writes events using Loguru."""

    def __init__(self, config: SinkConfig) -> None:
        self._config = config

    def emit(self, event: SinkEvent) -> None:
        level = self._config.level.upper()
        sink_logger = logger.bind(
            sink=self._config.name,
            channel=self._config.channel,
            event_type=event.type,
            resource=event.resource_name,
            card=event.card_name,
        )
        sink_logger.log(level, event.message, payload=dict(event.payload))


def _build_sink(config: SinkConfig) -> Sink:
    if config.type == "logger":
        return LoggingSink(config)
    raise ValueError(f"Unsupported sink type '{config.type}'")


class SinkDispatcher:
    """Dispatches events to named sinks declared in configuration."""

    def __init__(self, sinks: Mapping[str, Sink]) -> None:
        self._sinks = dict(sinks)

    @classmethod
    def from_settings(cls, settings: SentinelSettings) -> "SinkDispatcher":
        registry: MutableMapping[str, Sink] = {}
        for config in settings.sinks:
            if config.name in registry:
                logger.warning(
                    "Duplicate sink definition encountered; keeping first instance",
                    sink=config.name,
                )
                continue
            try:
                registry[config.name] = _build_sink(config)
            except Exception as exc:  # noqa: BLE001 - configuration errors surfaced via logs
                logger.error(
                    "Failed to initialise sink; skipping",
                    sink=config.name,
                    sink_type=config.type,
                    error=str(exc),
                )
        return cls(registry)

    def emit(self, sink_names: Sequence[str], event: SinkEvent) -> None:
        if not sink_names:
            return

        for sink_name in sink_names:
            sink = self._sinks.get(sink_name)
            if not sink:
                logger.warning(
                    "No sink configured for card entry; event skipped",
                    sink=sink_name,
                    event_type=event.type,
                    card=event.card_name,
                    resource=event.resource_name,
                )
                continue
            try:
                sink.emit(event)
            except Exception as exc:  # noqa: BLE001 - sinks should not break dispatching
                logger.exception(
                    "Sink emission failed",
                    sink=sink_name,
                    event_type=event.type,
                    card=event.card_name,
                    resource=event.resource_name,
                )
                logger.debug("Sink error detail", error=str(exc))


def incident_start_event(
    card: IncidentCard, notification: IncidentNotification
) -> SinkEvent:
    resource = notification.resource
    payload = {
        "state": resource.state,
        "value": resource.value,
        "labels": dict(resource.labels),
        "annotations": dict(resource.annotations),
    }
    return SinkEvent(
        type="incident.started",
        card_name=card.name,
        resource_name=resource.name,
        message="Incident processing started",
        payload=payload,
    )


def incident_completion_event(
    card: IncidentCard,
    notification: IncidentNotification,
    *,
    outcome: str,
    result_payload: Mapping[str, Any],
) -> SinkEvent:
    resource = notification.resource
    message = "Incident processing completed" if outcome == "success" else "Incident processing failed"
    return SinkEvent(
        type=f"incident.{outcome}",
        card_name=card.name,
        resource_name=resource.name,
        message=message,
        payload=result_payload,
    )


__all__ = [
    "LoggingSink",
    "Sink",
    "SinkDispatcher",
    "SinkEvent",
    "incident_completion_event",
    "incident_start_event",
]
