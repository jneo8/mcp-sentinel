# mcp-sentinel

**Alert-driven MCP incident response automation**

mcp-sentinel includes ICO (Incident Context Orchestrator) that ingests alerts (Alertmanager/Grafana), queries multiple MCP servers for corroborating facts, and emits a Single Incident Card plus a Safety Checklist to human channels (Slack/Matrix/Jira/Email). Deterministic logic is handled by a Rules Engine. An optional Agent (LLM) plugin can refine summaries, hypotheses, and action ranking, but never executes actions directly.

---

## Overview

When an alert fires, jumping across dashboards and shells wastes time and invites mistakes. mcp-sentinel centralizes alert intake, fans out to your MCP servers for contextual facts (logs, metrics, states, runbooks), and produces structured incident documentation with safety-first human handoff.

## Key Features

- **Multi-source observability**: Prometheus alerts, Grafana alerts, generic webhooks
- **Multi-MCP fan-out**: Query many MCP servers in parallel; merge and normalize results
- **Read-only by default**: Safe information gathering without unintended side effects
- **Human-first safety**: Produces structured incident cards and safety checklists for human decision-making
- **Policy as code**: Route alerts to appropriate playbooks based on configurable rules
- **Full audit trail**: Complete traceability of all operations and decisions stored in database
- **Flexible deployment**: Long-running daemon or cron-style periodic execution
- **Plugin architecture**: Extensible observers and sinks for custom integrations
- **Resilient design**: Circuit breakers, timeouts, and graceful degradation for MCP server failures

## Architecture

The system follows a clear pipeline:

1. **Observe**: Receive alerts from configured data sources
2. **Route**: Match incoming alerts to appropriate playbooks based on policies
3. **Query**: Collect context by calling one or more MCP servers in parallel
4. **Analyze**: Use LLM and Rules Engine to generate incident summary and safety checklist
5. **Validate**: Execute safety checklist verification steps before human handoff
6. **Emit**: Produce Single Incident Card with validated context and recommended actions
7. **Notify**: Send completed incident card to configured human channels

## Core Concepts

- **Observer**: Input adapter that receives alerts from various monitoring systems
- **ICO (Incident Context Orchestrator)**: Core LLM-powered service that coordinates alert processing, context gathering, and analysis
- **Rules Engine**: Deterministic logic processor for routing, policies, and safety checklist execution
- **Agent (Enhanced LLM Plugin)**: Optional component for advanced hypothesis generation and pattern analysis (read-only)
- **Single Incident Card**: Structured output containing validated alert context, analysis, and recommended actions
- **Safety Checklist**: Automated verification steps executed before human handoff to ensure data quality and completeness
- **Sink**: Output destination for incident cards and notifications (Slack, Matrix, Jira, email)

## Implementation Considerations

### Development Phases

1. **Phase 1 - Foundation**: Implement ICO core with LLM-powered analysis, basic alert ingestion, and MCP querying
2. **Phase 2 - Rules Engine**: Add deterministic policy routing and safety checklist validation logic
3. **Phase 3 - Resilience**: Add circuit breakers, error handling, and MCP server health monitoring
4. **Phase 4 - Enhanced Agent**: Implement optional advanced LLM plugin for sophisticated pattern analysis

### Technical Requirements

- **Error handling**: Partial failures across MCP servers must degrade gracefully
- **Performance**: Parallel queries require timeouts and circuit breakers
- **Security**: Agent plugins must never execute actions directly, only provide analysis
- **Configuration validation**: Rules Engine syntax errors should fail fast at startup
- **Rate limiting**: Prevent alert storms from overwhelming the system
- **Self-monitoring**: Track mcp-sentinel's own health and performance metrics

### Security Model

- **Pre-validated handoff**: Safety checklist must pass validation before sending incident cards to humans
- **Read-only MCP queries**: System never executes write operations through MCP servers
- **LLM isolation**: All LLM components operate in analysis-only mode with no execution capabilities
- **Audit requirements**: All incident cards, safety validations, and recommendations must be logged with full context
