"""Utilities for loading and rendering incident prompt templates."""

from __future__ import annotations

from pathlib import Path
from string import Template
from typing import Any, Dict

from loguru import logger

from .models import IncidentNotification


class PromptRepository:
    """Loads prompt templates from disk with graceful fallbacks."""

    def __init__(self, base_path: Path | None = None) -> None:
        self._base_path = base_path or Path.cwd()

    def load(self, prompt_identifier: str) -> str:
        """Return the template string for the provided identifier.

        The identifier is treated as a file path relative to the repository base. If the file does
        not exist, the identifier itself is returned and a warning is logged so the system can still
        operate with inline prompts.
        """

        candidate_path = Path(prompt_identifier)
        if not candidate_path.is_absolute():
            candidate_path = self._base_path / candidate_path

        if candidate_path.exists():
            try:
                return candidate_path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.exception(
                    "Failed to read prompt template", prompt=str(candidate_path), error=str(exc)
                )

        logger.warning(
            "Prompt template not found on disk, using identifier as inline instructions",
            prompt=prompt_identifier,
        )
        return prompt_identifier


class PromptRenderer:
    """Renders prompt templates using notification context."""

    def render(self, template: str, notification: IncidentNotification) -> str:
        context = self._build_context(notification)
        try:
            # Use Template for safe substitution without raising on missing keys
            rendered = Template(template).safe_substitute(context)
            if rendered == template:
                return template.format_map(_DefaultDict(context))
            return rendered
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Prompt rendering failed, returning raw template",
                error=str(exc),
                template_preview=template[:120],
            )
            return template

    def _build_context(self, notification: IncidentNotification) -> Dict[str, Any]:
        resource = notification.resource
        return {
            "resource_name": resource.name,
            "resource_type": resource.type,
            "resource_state": resource.state or "unknown",
            "resource_value": resource.value or "",
            "resource_timestamp": resource.timestamp or "",
            "resource_labels": ", ".join(f"{k}={v}" for k, v in resource.labels.items()),
            "resource_annotations": ", ".join(
                f"{k}={v}" for k, v in resource.annotations.items()
            ),
            "raw_payload": notification.raw_payload,
        }


class _DefaultDict(dict):
    """Helper mapping that returns empty string for missing keys."""

    def __missing__(self, key: str) -> Any:  # type: ignore[override]
        return ""
