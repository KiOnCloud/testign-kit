"""Tester settings stored in ~/.testign-kit/config.json.

The file is created with defaults on first load. Values in the file override the defaults;
nested objects (``backlog``) are merged key by key so a partial file keeps the other defaults.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

CONFIG_DIR_NAME = ".testign-kit"
CONFIG_FILE_NAME = "config.json"

# Backlog issue keys look like PROJ-123 (project key, hyphen, number).
DEFAULT_TICKET_ID_REGEX = r"\b[A-Z][A-Z0-9_]+-\d+\b"


class ConfigError(Exception):
    """Raised when the config file exists but cannot be used."""


def config_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / CONFIG_DIR_NAME


def config_path(home: Path | None = None) -> Path:
    return config_dir(home) / CONFIG_FILE_NAME


def defaults(home: Path | None = None) -> dict[str, Any]:
    home = home or Path.home()
    return {
        "output_dir": str(home / "Downloads"),
        "lang": "vi",
        "master_ref": "master",
        "develop_ref": "develop",
        "ticket_id_regex": DEFAULT_TICKET_ID_REGEX,
        "backlog": {
            "space": "",
            "project_key": "",
            # Decisions log pages: <prefix>/index, <prefix>/common and one <prefix>/<feature> page per feature.
            "decisions_log_prefix": "QA/Decisions",
            # Text formatting rule of the Backlog project. Only "markdown" is supported for the
            # decisions log; "backlog" (Backlog notation) makes the decisions commands stop with a message.
            "text_format": "markdown",
        },
    }


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load(home: Path | None = None) -> dict[str, Any]:
    """Return the effective config, creating the file with defaults if it does not exist."""
    base = defaults(home)
    path = config_path(home)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return base
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    merged = _merge(base, data)
    merged["output_dir"] = str(Path(merged["output_dir"]).expanduser())
    return merged
