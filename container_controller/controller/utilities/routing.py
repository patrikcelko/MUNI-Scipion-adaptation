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


#  Protocol mapping tables
PROTOCOL_MAPPINGS: list[tuple[str, str]] = [
    (r'Xmipp', 'xmipp'),
    (r'.*Relion', 'relion'),
    (r'.*MotionCor', 'motioncor2'),
    (r'.*Gctf|ProtGctf', 'gctf'),
    (r'Cistem|.*CTFFind', 'ctffind4'),
    (r'Eman', 'eman2'),
    (r'Sphire|.*CRYOLO', 'scipion3-remote'),
]

GPU_PROTOCOLS: frozenset[str] = frozenset(
    {
        'XmippProtMovieCorr',
        'ProtGctf',
    }
)


def choose_tool_by_protocol(
    protocol_name: str,
    toolmap_path: str,
) -> dict[str, Any] | None:
    """Map a Scipion protocol name to the best matching tool container."""

    if not protocol_name:
        return None

    tools: list[dict[str, Any]] = load_toolmap(toolmap_path)

    for pattern, tool_substr in PROTOCOL_MAPPINGS:
        if re.match(pattern, protocol_name, re.IGNORECASE):
            for tool in tools:
                if not tool.get('enabled', True):
                    continue

                if tool_substr in tool.get('image', '').lower():
                    result: dict[str, Any] = dict(tool)
                    if protocol_name in GPU_PROTOCOLS:
                        result['needsGpu'] = True
                    logger.info(
                        "Protocol '%s' -> %s%s",
                        protocol_name,
                        result.get('image'),
                        ' (GPU override)' if result.get('needsGpu') else '',
                    )

                    return result

    for tool in tools:
        if 'scipion3-remote' in tool.get('image', '').lower():
            logger.info(
                "Protocol '%s' -> %s (default)",
                protocol_name,
                tool.get('image'),
            )
            return dict(tool)

    return None


def choose_tool(cmd0: str, toolmap_path: str) -> dict[str, Any] | None:
    """Legacy command-prefix routing (backward compatibility)."""

    # TODO: Will be removed
    for tool in load_toolmap(toolmap_path):
        if not tool.get('enabled', True):
            continue

        pattern = tool.get('match', '')
        if pattern and re.match(pattern, cmd0):
            return dict(tool)

    return None
