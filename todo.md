# TODO

- Implement Hosted MCP tool discovery and complete `ToolResolver` logic in `mcp_sentinel/agent/orchestrator.py`.
- Design and wire sink/audit pipeline (Slack, Jira, storage) with configuration and dispatcher hookups.
- Extend watcher support beyond Prometheus: add Grafana webhook driver and remote-write ingestion.
- Add safety hooks and retry/backoff policies per spec, plus integration tests covering error paths.
- Introduce observability metrics (queue depth, latency) and document operational runbooks.
