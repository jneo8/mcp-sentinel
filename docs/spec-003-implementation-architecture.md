# Spec-003 Python Implementation Architecture

## Purpose
This document explains how the current Python implementation realises the Sentinel architecture defined in `spec-001` and `spec-002`, and which parts remain stubbed. It focuses on the dispatcher, orchestrator, CLI, and shared models that already exist in the repository.

## Technology Stack
- Python 3.11 managed via `uv` for reproducible environments.
- `click` powers the CLI surface described in `spec-002`.
- `pydantic` models mirror architecture contracts such as `IncidentNotification`, `IncidentCard`, and dispatcher settings.
- `loguru` centralises structured logging.
- `openai-agents` (OpenAI Agent SDK) executes MCP-aware agent runs.
- `pytest` exercises dispatcher routing, prompt rendering, and CLI behaviour.

## Package Layout (Current)
```
mcp_sentinel/
├── __init__.py
├── __main__.py              # console_script shim
├── cli.py                   # click commands (run, flags)
├── config.py                # YAML loader + configuration error types
├── interfaces.py            # Protocols for dispatcher/orchestrator contracts
├── models.py                # Shared pydantic models (cards, notifications, servers)
├── prompts.py               # Prompt repository + renderer utilities
├── dispatcher/
│   └── prometheus.py        # Async queue, dedupe cache, worker loop
├── agent/
│   └── orchestrator.py      # openai-agents integration & prompt hydration
└── services/
    └── registry.py          # Hosted MCP tool registry & resolver
```
Tests reside in `tests/` and shadow the runtime namespaces. Watchers and sink pipelines are still pending implementations aligned with `spec-002`.

## Alignment With Spec-002 Layers
- **Watchers**: Prometheus/Grafana watchers are still pending. The dispatcher exposes an async `dispatch` API intended for whichever watcher implementation (`asyncio` tasks or background threads) we introduce. Spec-002's goroutine language is interpreted here as concurrent async tasks in Python.
- **Dispatcher**: `mcp_sentinel.dispatcher.prometheus.PrometheusDispatcher` delivers the queue, dedupe TTL, and routing logic mandated by Spec-002. It currently logs drops and successes but does not yet publish metrics or feed sinks.
- **Sentinel Agent**: `OpenAIAgentOrchestrator` wraps the `openai-agents` Runner. `ToolResolver` now delegates to `services.ToolRegistry`, which collapses incident card tool identifiers into `HostedMCPTool` instances with per-card allowlists.
- **Tool Adapters & Safety Hooks**: Not yet implemented. The orchestrator logs a warning when tools are requested to make these gaps visible.
- **Sinks & Audit**: No sinks have been wired; dispatcher/orchestrator log at INFO as a placeholder until streaming sink handlers are added per Spec-002.

## Control Flow (Today)
1. `sentinel run` (defined in `cli.py`) loads `SentinelSettings` from YAML, configures logging, constructs the orchestrator, then starts the Prometheus dispatcher.
2. The dispatcher maintains an `asyncio.Queue` sized by `SentinelSettings.dispatcher.queue_size` and spawns `worker_concurrency` tasks.
3. A watcher (once implemented) will call `dispatcher.dispatch(notification)`; the method performs dedupe checks, validates card mappings, enqueues the alert, and returns a `DispatcherResult` summarising the action.
4. Worker tasks dequeue notifications and call `OpenAIAgentOrchestrator.run_incident(card, notification)`.
5. The orchestrator loads instructions using `PromptRepository`, renders them via `PromptRenderer`, builds an `Agent`, and runs it through `openai-agents.Runner`. Outcomes are logged; exceptions bubble up for now (future retry/backoff policy TBD).

## Configuration Model
`mcp_sentinel.models` defines `SentinelSettings` with:
- `incident_cards`: list of `IncidentCard` objects keyed by `resource`. Cards declare prompt paths, optional `model` overrides, tool identifiers, sink identifiers, and `max_iterations`.
- `dispatcher`: `PrometheusDispatcherSettings` capturing queue size, worker concurrency, and dedupe TTL.
- `openai`: `OpenAISettings` for default model/temperature; additional OpenAI-specific parameters from Spec-002 can be added here.
- `mcp_servers`: collection of `HostedMCPServer` entries that drive Hosted MCP tool resolution (labels, URLs, headers, approval policy).

`mcp_sentinel.config.load_settings` loads YAML files (default `config.yaml`) and validates them against `SentinelSettings`. Alias support allows `prompt`, `max-iterations`, `mcp-servers`, etc., to match Spec-002 examples.

## Observability & Logging
- `cli._configure_logging` initialises Loguru with configurable level and debug mode.
- Dispatcher logs queue events, dedupe purges, and worker lifecycle messages.
- Orchestrator logs initiation and completion of agent runs, surfacing truncated outputs for debugging.
- Metrics exporters and structured audit sinks remain TODO items aligned with Spec-002's observability requirements.

## Open TODOs Relative to Spec-002
- Implement Prometheus watcher ingestion layer (webhook, polling, or remote write) that pushes notifications into the dispatcher.
- Extend the tool registry with cached server discovery, approval callbacks, and richer error handling once MCP watchers land.
- Add sink/audit pipeline to stream agent events to Slack/Jira/etc.
- Introduce safety hooks and retries/backoff policies around agent runs.
- Expose metrics (queue depth, latency) and incorporate signal handling for graceful shutdown.

## Testing Notes
- `tests/dispatcher/test_prometheus_dispatcher.py` asserts queueing, dedupe, and worker behaviour with async fixtures.
- `tests/prompts/test_prompts.py` covers prompt repository fallbacks and rendering context.
- `tests/test_cli.py` validates CLI flag parsing and config loading.
- Integration tests for watcher → dispatcher → agent flow and orchestrator error handling are pending until the missing layers land.

This document will evolve as watcher integrations, tool registries, and sinks are added so that implementation details stay consistent with the architecture in `spec-002`.
