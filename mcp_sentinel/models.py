"""Core Pydantic models shared across MCP Sentinel components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Resource(BaseModel):
    """Represents the triggering resource for an incident."""

    type: str = Field(..., description="Type of the resource, e.g. prometheus_alert")
    name: str = Field(..., description="Logical resource identifier used for routing")
    labels: Dict[str, str] = Field(default_factory=dict)
    annotations: Dict[str, str] = Field(default_factory=dict)
    state: Optional[str] = None
    value: Optional[str] = None
    timestamp: Optional[str] = None

    def dedupe_key(self) -> str:
        """Create a deterministic dedupe key for the resource."""

        label_pairs = ",".join(
            f"{key}={value}" for key, value in sorted(self.labels.items())
        )
        annotation_pairs = ",".join(
            f"{key}={value}" for key, value in sorted(self.annotations.items())
        )
        parts: List[str] = [self.type, self.name, label_pairs, annotation_pairs]
        if self.timestamp:
            parts.append(self.timestamp)
        return "|".join(part for part in parts if part)


class IncidentNotification(BaseModel):
    """Notification emitted by watchers when a new incident is detected."""

    resource: Resource
    raw_payload: Dict[str, Any] = Field(default_factory=dict)


class IncidentCard(BaseModel):
    """Configuration for how an incident should be handled."""

    name: str
    resource: str = Field(..., description="Resource name the card applies to")
    prompt_template: str = Field(..., description="Path or identifier for prompt template")
    model: Optional[str] = Field(
        default=None, description="Optional model override for this card"
    )
    tools: List[str] = Field(
        default_factory=list,
        description="List of MCP tool identifiers in server.tool format",
    )
    sinks: List[str] = Field(default_factory=list)
    max_iterations: int = Field(default=6, ge=1, le=20)


class DispatcherSettings(BaseModel):
    """Settings shared across dispatchers."""

    queue_size: int = Field(default=100, ge=1, le=1000)
    dedupe_ttl_seconds: int = Field(default=600, ge=10, le=3600)


class PrometheusDispatcherSettings(DispatcherSettings):
    """Dispatcher-specific tuning flags."""

    worker_concurrency: int = Field(default=4, ge=1, le=32)


class OpenAISettings(BaseModel):
    """Settings controlling how OpenAI models are invoked."""

    model: str = Field(default="gpt-4.1-mini")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)


class SentinelSettings(BaseModel):
    """Top-level application settings used by the dispatcher."""

    incident_cards: List[IncidentCard] = Field(default_factory=list)
    dispatcher: PrometheusDispatcherSettings = Field(
        default_factory=PrometheusDispatcherSettings
    )
    openai: OpenAISettings = Field(default_factory=OpenAISettings)


class DispatcherResult(BaseModel):
    """Result emitted after a notification is processed."""

    incident_card: Optional[IncidentCard] = None
    status: str = Field(..., description="Outcome status, e.g. routed, duplicate, dropped")
    detail: Optional[str] = None


class OpenAISettings(BaseModel):
    """Settings controlling how OpenAI models are invoked."""

    model: str = Field(default="gpt-4.1-mini")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
