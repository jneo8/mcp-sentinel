from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Any, Dict

from click.testing import CliRunner
import pytest

from mcp_sentinel.cli import cli


def test_cli_run_handles_keyboard_interrupt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_text = dedent(
        """
        sentinel:
          incident-cards:
            - name: latency-card
              resource: web-tier
              prompt: Investigate latency issues
              max-iterations: 2
        """
    )
    config_path = tmp_path / "config.yaml"
    config_path.write_text(config_text, encoding="utf-8")

    state: Dict[str, Any] = {}

    class StubOrchestrator:
        def __init__(self, settings):  # noqa: ANN001 - signature controlled by CLI
            state["orchestrator_settings"] = settings

    class StubDispatcher:
        def __init__(self, settings, agent_orchestrator, **_kwargs):  # noqa: ANN001, ANN003
            state["dispatcher_settings"] = settings
            state["dispatcher_agent"] = agent_orchestrator
            state["started"] = 0
            state["stopped"] = 0

        async def start(self) -> None:
            state["started"] += 1

        async def stop(self) -> None:
            state["stopped"] += 1

    class StubWatcherService:
        def __init__(self, settings, dispatcher, **_kwargs):  # noqa: ANN001, ANN003
            state["watcher_settings"] = settings
        
        async def start(self) -> None:
            state.setdefault("watcher_start_calls", 0)
            state["watcher_start_calls"] += 1
            raise KeyboardInterrupt

        async def stop(self) -> None:
            state.setdefault("watcher_stop_calls", 0)
            state["watcher_stop_calls"] += 1

    monkeypatch.setattr("mcp_sentinel.cli.OpenAIAgentOrchestrator", StubOrchestrator)
    monkeypatch.setattr("mcp_sentinel.cli.PrometheusDispatcher", StubDispatcher)
    monkeypatch.setattr("mcp_sentinel.cli.PrometheusWatcherService", StubWatcherService)

    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(config_path), "run"])

    assert result.exit_code == 0, result.output
    assert state["started"] == 1
    assert state["stopped"] == 1
    assert state["dispatcher_settings"].incident_cards[0].prompt_template == "Investigate latency issues"
    assert state.get("watcher_start_calls", 0) == 1
    assert state.get("watcher_stop_calls", 0) == 1


def test_cli_missing_config(tmp_path: Path) -> None:
    missing_path = tmp_path / "absent.yaml"
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", str(missing_path), "run"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()
