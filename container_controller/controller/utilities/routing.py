"""
Tool routing
============

This module extracts the protocol name (`XmippProtMovieGain`) and tries to map
it to the correct specialized Docker image (`xmipp`, `relion`, …).
"""

import logging
import re
from pathlib import Path
from typing import Any

from controller.utilities import load_yaml

logger: logging.Logger = logging.getLogger(__name__)

# Toolmap cache (avoid re-reading YAML on every request)
_toolmap_cache: list[dict[str, Any]] | None = None
_toolmap_mtime: float = 0.0


def detect_protocol_from_command(cmd: str) -> str | None:
    """Extract the Scipion protocol class name from a run command."""

    match: re.Match[str] | None = re.search(r'Runs/\d+_([^/]+)/', cmd)
    return match.group(1) if match else None


def detect_protocol_run_dir(cmd: str) -> str | None:
    """Extract the relative protocol working directory from a command."""

    match: re.Match[str] | None = re.search(r'(Runs/\d+_[^/]+)/', cmd)
    return match.group(1) if match else None


def load_toolmap(toolmap_path: str) -> list[dict[str, Any]]:
    """Load and normalise the tool configuration file. Results are cached and re-read
    only when the file modification time changes.
    """

    global _toolmap_cache, _toolmap_mtime

    try:
        mtime = Path(toolmap_path).stat().st_mtime
    except OSError:
        mtime = 0.0

    if _toolmap_cache is not None and mtime == _toolmap_mtime:
        return [dict(t) for t in _toolmap_cache]

    data: dict[str, Any] | list[Any] | None = load_yaml(toolmap_path)
    items: list[dict[str, Any]]

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get('tools') or []
    else:
        items = []

    for tool in items:
        tool.setdefault('enabled', True)

    _toolmap_cache = items
    _toolmap_mtime = mtime

    return [dict(t) for t in items]


def choose_tool_by_protocol(
    protocol_name: str,
    toolmap_path: str,
) -> dict[str, Any] | None:
    """Map a Scipion protocol name to the best matching tool container. The mapping is
    driven entirely by the `protocol` regex fields in the toolmap YAML. Each tool entry
    may additionally carry a `gpu_protocols` list to mark specific protocol class
    names that require GPU even if the tool itself defaults to CPU.
    """

    if not protocol_name:
        return None

    tools: list[dict[str, Any]] = load_toolmap(toolmap_path)
    fallback: dict[str, Any] | None = None

    for tool in tools:
        if not tool.get('enabled', True):
            continue

        if tool.get('default', False):
            if fallback is None:
                fallback = tool
            continue

        pattern: str = tool.get('protocol', '')
        if not pattern:
            continue

        if re.match(pattern, protocol_name, re.IGNORECASE):
            result: dict[str, Any] = dict(tool)
            if protocol_name in tool.get('gpu_protocols', []):
                result['needsGpu'] = True
            logger.info(
                "Protocol '%s' -> %s%s",
                protocol_name,
                result.get('image'),
                ' (GPU override)' if result.get('needsGpu') else '',
            )
            return result

    if fallback:
        logger.info(
            "Protocol '%s' -> %s (default)",
            protocol_name,
            fallback.get('image'),
        )
        return dict(fallback)

    return None


def choose_tool(cmd0: str, toolmap_path: str) -> dict[str, Any] | None:
    """Command-prefix routing."""

    for tool in load_toolmap(toolmap_path):
        if not tool.get('enabled', True):
            continue

        pattern = tool.get('match', '')
        if pattern and re.match(pattern, cmd0):
            return dict(tool)

    return None
