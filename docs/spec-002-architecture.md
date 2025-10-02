# MCP Sentinel Architecture Specification

## Overview
MCP Sentinel transforms raw alerts into validated incident packages by combining watcher-driven intake, an agent-based orchestration core, and Model Context Protocol (MCP) tool integrations. The system runs each incident through a dedicated agent session that gathers context, enforces deterministic safety checks, and emits audit-ready outputs for human responders.

## Architecture Layers
| Layer | Responsibility | Key Technologies |
| ----- | -------------- | ---------------- |
| Watchers | Monitor external systems, filter alerts, emit `IncidentNotification` objects | Prometheus/Grafana integrations, goroutines, backpressure-aware channels |
| Dispatcher | Map notifications to incident cards, spin up agent sessions, enforce routing policies | Worker queue, config-driven matching |
| Sentinel Agent | Coordinate MCP tools, apply prompts, maintain conversation state, stream events | `openai-agents` runtime, `AgentSession`, shared memory |
| Tool Adapters | Provide typed, read-only access to MCP servers and deterministic checks | `@tool`-annotated wrappers, Pydantic models, retries/circuit breakers |
| Safety Hooks | Run pre/post validations, ensure checklist completion before human handoff | Rules engine callbacks, policy evaluation |
| Sinks & Audit | Deliver outputs to Slack/Matrix/Jira/email and persist transcripts for audit | Streaming event handlers, durable storage |

## Component Interaction
```
┌──────────────┐   notifications   ┌──────────────┐   agent events   ┌──────────────┐
│   Watchers   │ ─────────────────▶│  Dispatcher  │──────────────────▶│ Sentinel Agent│
└──────────────┘                   └──────┬──────┘                   └──────┬───────┘
                                          │                             tool calls
                                          │                                 │
                                          ▼                                 ▼
                                   ┌──────────────┐                 ┌──────────────┐
                                   │  Audit/Sinks │◀─────────────── │  MCP Servers │
                                   └──────────────┘    results      └──────────────┘
```

## Agent Integration Blueprint
- **Session management**: Each incident runs within `agent.session(metadata=...)`, giving resumable control, cancellation hooks, and bounded iterations.
- **Typed tool surface**: MCP queries, enrichment fetches, and checklist validators are exposed with `@tool` annotations so the runtime auto-generates JSON schemas and validates arguments.
- **Streaming runner**: `StreamingAgentRunner` feeds real-time `Item` events (messages, tool calls, logs) to sinks and to the dispatcher for monitoring SLA breaches or circuit breaker triggers.
- **Scoped tool registry**: `SentinelAgentFactory` registers only the tools declared in the incident card, enforcing allowlists and read-only adapters.
- **Memory & context**: Shared, per-incident memory keeps critical facts accessible across tool invocations while long-term history is captured in the audit store.

## End-to-End Flow
1. **Alert intake**: Watcher polls, filters by resource configuration, and emits an `IncidentNotification` with enriched labels/annotations.
2. **Routing**: Dispatcher selects an `IncidentCardConfig`, derives sinks, prompts, and tool allowlists, then enqueues work.
3. **Session bootstrap**: `SentinelAgentFactory.create()` initializes the agent, registers incident-scoped tools, and attaches safety hooks.
4. **Streaming orchestration**:
   - `on_start` events send an initial incident stub to sinks.
   - Tool calls execute through MCP adapters with retries, timeouts, and circuit breakers.
   - Intermediate reasoning is optionally forwarded to collaboration channels for transparency.
5. **Safety validation**: Deterministic rules verify checklist items; failures short-circuit the session and escalate to humans with clear errors.
6. **Emission & audit**: Final incident card, recommended actions, and checklist status are pushed to sinks while the complete transcript plus tool payloads land in the audit repository.

## Configuration Model
```yaml
sentinel:
  openai:
    model: gpt-4.1-mini
    temperature: 0.2
  defaults:
    max_iterations: 6
    retry_policy: { attempts: 2, backoff: exponential }
watchers:
  - type: prometheus
    endpoint: https://prom.example/api/v1
    poll_interval: 15s
    resources: [db-primary, web-tier]
mcp_servers:
  - name: grafana
    transport: http
    url: http://grafana-proxy
    enforce_read_only: true
incident_cards:
  - name: high-latency
    resource: web-tier
    prompt_template: prompts/high-latency.md
    tools: [grafana.snapshot, prom.range_query, rules.check_slo]
    sinks: [slack:oncall-web]
    max_iterations: 4
```
Configuration loads through layered settings (`SentinelSettings`, `WatcherConfig`, `IncidentCardConfig`) backed by Pydantic, enabling `.env` overrides and dry-run execution.

## Operational Concerns
- **Resilience**: Circuit breakers around MCP calls, bounded queues between watchers and dispatcher, and timeouts on agent sessions prevent cascading failures.
- **Scalability**: Watchers run as independent goroutines; dispatcher/agent workers scale horizontally to process concurrent incidents.
- **Observability**: Metrics export latency per tool call, iteration counts, alert-to-notification lag, and sink delivery status. Structured logs capture every agent event with correlation IDs.
- **Incident replay**: Dry-run mode replays historical alerts through the agent without contacting live MCP servers, supporting validation and tabletop exercises.

## Implementation Milestones
1. **Agent foundation**: Build `SentinelAgent`, shared memory, and factory; wire streaming runner into dispatcher.
2. **Tool registry**: Wrap MCP clients and safety rules with typed `@tool` functions; add allowlist enforcement and retries.
3. **Session orchestration**: Implement event handlers for sinks, safety hooks, and iteration limits; ensure graceful cancellation.
4. **Resilience & observability**: Introduce circuit breakers, metrics, and alerting on session failures or tool degradation.
5. **Validation**: Unit tests for tool schemas/config parsing and integration tests covering watcher→agent→sink flow.

## Security & Compliance Posture
- MCP adapters default to read-only; no automated remediation is executed.
- Secrets stay in environment-backed stores; redaction occurs before streaming events reach sinks.
- Audit trail stores hashed transcripts per incident for tamper detection and compliance reporting.
- Manual override (`sentinelctl abort <incident_id>`) terminates runaway sessions safely.
