"""Core Pydantic models shared across MCP Sentinel components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


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

    model_config = ConfigDict(populate_by_name=True)

    name: str
    resource: str = Field(..., description="Resource name the card applies to")
    prompt_template: str = Field(
        ...,
        description="Path or identifier for prompt template",
        validation_alias=AliasChoices("prompt_template", "prompt", "prompt-template"),
    )
    model: Optional[str] = Field(
        default=None,
        description="Optional model override for this card",
        validation_alias=AliasChoices("model", "model-name"),
    )
    tools: List[str] = Field(
        default_factory=list,
        description="List of MCP tool identifiers in server.tool format",
        validation_alias=AliasChoices("tools", "tool-list"),
    )
    sinks: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("sinks", "sink-list"),
    )
    max_iterations: int = Field(
        default=6,
        ge=1,
        le=20,
        validation_alias=AliasChoices("max_iterations", "max-iterations"),
    )


class DispatcherSettings(BaseModel):
    """Settings shared across dispatchers."""

    model_config = ConfigDict(populate_by_name=True)

    queue_size: int = Field(
        default=100,
        ge=1,
        le=1000,
        validation_alias=AliasChoices("queue_size", "queue-size"),
    )
    dedupe_ttl_seconds: int = Field(
        default=600,
        ge=10,
        le=3600,
        validation_alias=AliasChoices("dedupe_ttl_seconds", "dedupe-ttl-seconds"),
    )


class PrometheusDispatcherSettings(DispatcherSettings):
    """Dispatcher-specific tuning flags."""

    worker_concurrency: int = Field(
        default=4,
        ge=1,
        le=32,
        validation_alias=AliasChoices("worker_concurrency", "worker-concurrency"),
    )


class OpenAISettings(BaseModel):
    """Settings controlling how OpenAI models are invoked."""

    model_config = ConfigDict(populate_by_name=True)

    model: str = Field(
        default="gpt-4.1-mini",
        validation_alias=AliasChoices("model", "model-name"),
    )
    temperature: float = Field(
        default=0.2,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("temperature", "temp"),
    )


class HostedMCPServer(BaseModel):
    """Configuration for a hosted MCP server exposed to agents."""

    model_config = ConfigDict(populate_by_name=True)

    name: str = Field(..., description="Unique identifier referenced by incident cards")
    server_label: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("server_label", "server-label", "label"),
        description="Label presented to the agent runtime; defaults to name",
    )
    server_url: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("server_url", "server-url", "url"),
    )
    connector_id: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("connector_id", "connector-id"),
    )
    authorization: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("authorization", "auth-token", "token"),
    )
    headers: Dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("headers", "http-headers"),
    )
    require_approval: Optional[Union[Literal["always", "never"], Dict[str, Any]]] = Field(
        default=None,
        validation_alias=AliasChoices("require_approval", "require-approval"),
        description="Optional approval policy forwarded to HostedMCP tools",
    )
    description: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("description", "server-description"),
    )
    default_allowed_tools: Optional[List[str]] = Field(
        default=None,
        validation_alias=AliasChoices("default_allowed_tools", "default-allowed-tools"),
        description="Baseline allowlist applied when cards omit specific tools",
    )

    @model_validator(mode="after")
    def _validate_endpoint(self) -> "HostedMCPServer":
        if not self.server_url and not self.connector_id:
            raise ValueError(
                "Hosted MCP server requires either server_url or connector_id to be configured"
            )
        return self

    def to_mcp_config(self, *, allowed_tools: Optional[List[str]] = None) -> Dict[str, Any]:
        """Build a Hosted MCP tool configuration dictionary."""

        tool_allowlist = allowed_tools or self.default_allowed_tools
        config: Dict[str, Any] = {
            "server_label": self.server_label or self.name,
            "type": "mcp",
        }
        if tool_allowlist:
            config["allowed_tools"] = list(dict.fromkeys(tool_allowlist))
        if self.server_url:
            config["server_url"] = self.server_url
        if self.connector_id:
            config["connector_id"] = self.connector_id
        if self.authorization:
            config["authorization"] = self.authorization
        if self.headers:
            config["headers"] = dict(self.headers)
        if self.require_approval:
            config["require_approval"] = self.require_approval
        if self.description:
            config["server_description"] = self.description
        return config


class SentinelSettings(BaseModel):
    """Top-level application settings used by the dispatcher."""

    model_config = ConfigDict(populate_by_name=True)

    incident_cards: List[IncidentCard] = Field(
        default_factory=list,
        validation_alias=AliasChoices("incident_cards", "incident-cards"),
    )
    dispatcher: PrometheusDispatcherSettings = Field(
        default_factory=PrometheusDispatcherSettings,
        validation_alias=AliasChoices("dispatcher", "dispatcher"),
    )
    openai: OpenAISettings = Field(
        default_factory=OpenAISettings,
        validation_alias=AliasChoices("openai", "openai-settings"),
    )
    mcp_servers: List[HostedMCPServer] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "mcp_servers", "mcp-servers", "hosted_mcp_servers", "hosted-mcp-servers"
        ),
    )


class DispatcherResult(BaseModel):
    """Result emitted after a notification is processed."""

    incident_card: Optional[IncidentCard] = None
    status: str = Field(..., description="Outcome status, e.g. routed, duplicate, dropped")
    detail: Optional[str] = None
