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
from .watchers import PrometheusWatcherService
from .models import SentinelSettings


def _configure_logging(level: str, debug: bool) -> None:
    """Initialise loguru with the requested verbosity."""

    logger.remove()
    effective_level = "DEBUG" if debug else level.upper()

    # Custom format that includes structured data
    if debug:
        # In debug mode, show all structured data
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
            "{extra}\n"
        )
    else:
        # In normal mode, use simpler format but still show extra data
        format_string = (
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan> - "
            "<level>{message}</level>"
            "{extra}\n"
        )

    def format_extra(record):
        """Format extra fields as a dict."""
        extra_data = {}
        for key, value in record["extra"].items():
            if key not in ["name", "function", "line"]:  # Skip built-in fields
                extra_data[key] = value

        if extra_data:
            import json
            try:
                # Use JSON for clean dict-like formatting
                return " " + json.dumps(extra_data, default=str, ensure_ascii=False)
            except Exception:
                # Fallback to repr if JSON fails
                return " " + repr(extra_data)
        return ""

    # Add the format_extra function to each record
    def format_record(record):
        record["extra_formatted"] = format_extra(record)
        return format_string.replace("{extra}", "{extra_formatted}")

    logger.add(
        sys.stderr,
        level=effective_level,
        backtrace=debug,
        diagnose=debug,
        format=format_record
    )


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
@click.pass_context
def run(ctx: click.Context) -> None:
    settings = ctx.obj.get("settings")
    if settings is None:
        raise click.ClickException("Sentinel settings not initialised; invoke via the top-level CLI")

    assert isinstance(settings, SentinelSettings)
    asyncio.run(_run_dispatcher(settings))


async def _run_dispatcher(settings: SentinelSettings) -> None:
    orchestrator = OpenAIAgentOrchestrator(settings)
    dispatcher = PrometheusDispatcher(settings=settings, agent_orchestrator=orchestrator)
    watcher_service = PrometheusWatcherService(settings=settings, dispatcher=dispatcher)
    started = False
    try:
        await dispatcher.start()
        started = True
        await watcher_service.start()

        logger.info("Prometheus dispatcher running; awaiting watcher notifications")
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:  # pragma: no cover - defensive guard
        logger.info("Dispatcher task cancelled; shutting down")
    except KeyboardInterrupt:
        logger.info("Shutdown signal received; stopping dispatcher")
    finally:
        await watcher_service.stop()
        if started:
            await dispatcher.stop()


def main() -> None:
    """Entrypoint for console_script integration."""

    cli(standalone_mode=True)


__all__ = ["cli", "main"]
