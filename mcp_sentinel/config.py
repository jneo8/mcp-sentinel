"""Configuration loading helpers for MCP Sentinel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from loguru import logger
from pydantic import ValidationError

from .models import SentinelSettings

SUPPORTED_CONFIG_EXTENSIONS = {".yaml", ".yml", ".json"}


class ConfigurationError(RuntimeError):
    """Raised when configuration loading or validation fails."""


def load_settings(config_path: Path | str | None) -> SentinelSettings:
    """Load sentinel settings from the provided configuration file.

    If ``config_path`` is ``None`` the default settings object is returned. The loader supports
    YAML (``.yml``/``.yaml``) and JSON files. When the file contains a top-level ``sentinel`` key,
    that mapping is used; otherwise, the entire document is interpreted as the sentinel section.
    """

    if config_path is None:
        logger.debug("No config path supplied, using default SentinelSettings")
        return SentinelSettings()

    path = Path(config_path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    data = _read_mapping(path)
    sentinel_section = data.get("sentinel", data)
    if not isinstance(sentinel_section, Mapping):
        raise ConfigurationError("Sentinel configuration must be a mapping")

    try:
        settings = SentinelSettings.model_validate(dict(sentinel_section))
    except ValidationError as exc:
        logger.error("Configuration validation failed", errors=exc.errors())
        raise ConfigurationError("Invalid sentinel configuration") from exc

    logger.debug(
        "Loaded sentinel configuration",
        incident_cards=len(settings.incident_cards),
        queue_size=settings.dispatcher.queue_size,
    )
    return settings


def _read_mapping(path: Path) -> Mapping[str, Any]:
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_CONFIG_EXTENSIONS:
        raise ConfigurationError(
            f"Unsupported configuration format for {path.name}; expected one of: "
            + ", ".join(sorted(SUPPORTED_CONFIG_EXTENSIONS))
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001 - propagate as config error
        raise ConfigurationError(f"Failed to read configuration file: {path}") from exc

    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import]
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency missing
            raise ConfigurationError(
                "PyYAML is required to load YAML configuration files"
            ) from exc

        loaded = yaml.safe_load(text) or {}
    else:
        loaded = json.loads(text or "{}")

    if not isinstance(loaded, Mapping):
        raise ConfigurationError("Configuration root must be a mapping object")
    return loaded


__all__ = ["ConfigurationError", "load_settings"]
