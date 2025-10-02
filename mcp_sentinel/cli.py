"""Command-line interface for running MCP Sentinel services."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Dict

import click
from loguru import logger

from .agent import OpenAIAgentOrchestrator
from .config import ConfigurationError, load_settings
from .dispatcher import PrometheusDispatcher
from .models import SentinelSettings


def _configure_logging(level: str, debug: bool) -> None:
    """Initialise loguru with the requested verbosity."""

    logger.remove()
    effective_level = "DEBUG" if debug else level.upper()
    logger.add(sys.stderr, level=effective_level, backtrace=debug, diagnose=debug)


@click.group()
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path, dir_okay=False, file_okay=True, resolve_path=True),
    default=Path("config.yaml"),
    show_default=True,
    help="Path to the sentinel configuration file.",
)
@click.option(
    "--log-level",
    default="INFO",
    show_default=True,
    help="Base log level for Sentinel output.",
)
@click.option(
    "--debug",
    is_flag=True,
    default=False,
    help="Enable verbose debug logging regardless of --log-level.",
)
@click.pass_context
def cli(ctx: click.Context, config_path: Path, log_level: str, debug: bool) -> None:
    """Top-level CLI group initialising shared context."""

    _configure_logging(log_level, debug)
    ctx.ensure_object(dict)
    try:
        settings = load_settings(config_path)
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    ctx.obj["settings"] = settings
    ctx.obj["config_path"] = config_path


@cli.command(help="Start the Prometheus dispatcher loop.")
@click.option(
    "--run-once",
    is_flag=True,
    default=False,
    help="Initialise components and exit without entering the long-running loop.",
)
@click.pass_context
def run(ctx: click.Context, run_once: bool) -> None:
    settings = ctx.obj.get("settings")
    if settings is None:
        raise click.ClickException("Sentinel settings not initialised; invoke via the top-level CLI")

    assert isinstance(settings, SentinelSettings)
    asyncio.run(_run_dispatcher(settings, run_once=run_once))


async def _run_dispatcher(settings: SentinelSettings, *, run_once: bool) -> None:
    orchestrator = OpenAIAgentOrchestrator(settings)
    dispatcher = PrometheusDispatcher(settings=settings, agent_orchestrator=orchestrator)
    started = False
    try:
        await dispatcher.start()
        started = True
        if run_once:
            logger.info("Run-once mode enabled; dispatcher started and will now stop")
            return

        logger.info("Prometheus dispatcher running; awaiting watcher notifications")
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:  # pragma: no cover - defensive guard
        logger.info("Dispatcher task cancelled; shutting down")
    except KeyboardInterrupt:
        logger.info("Shutdown signal received; stopping dispatcher")
    finally:
        if started:
            await dispatcher.stop()


def main() -> None:
    """Entrypoint for console_script integration."""

    cli(standalone_mode=True)


__all__ = ["cli", "main"]
