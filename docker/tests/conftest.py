"""
Test fixtures
=============

Shared pytest fixtures and path constants for `docker/` tests.
"""

import os
import re
import sys
from pathlib import Path

# Make this directory importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT: Path = Path(__file__).resolve().parents[2]
"""Directory containing all Dockerfiles."""

DOCKER_DIR: Path = REPO_ROOT / 'docker'
"""Directory containing Docker-related code (Dockerfiles, scripts, config)."""

SCRIPTS_DIR: Path = DOCKER_DIR / 'gui' / 'scripts'
"""Directory containing GUI startup scripts."""

CONFIG_DIR: Path = DOCKER_DIR / 'config'
"""Directory containing configuration files."""


ALL_SCRIPTS: list[Path] = sorted(
    [
        *SCRIPTS_DIR.glob('*.sh'),
        *(DOCKER_DIR / 'tools' / 'relion' / 'scripts').glob('*.sh'),
    ]
)
"""All shell scripts in the project."""

ALL_DOCKERFILES: list[Path] = sorted(
    Path(root) / f
    for root, _, files in os.walk(DOCKER_DIR)
    for f in files
    if f == 'Dockerfile' or f.startswith('Dockerfile.')
)
"""All Dockerfiles in the project."""


def parse_dockerfile(path: Path) -> list[tuple[str, str]]:
    """Parse path into `(DIRECTIVE, rest_of_line)` tuples."""

    text = re.sub(r'\\\s*\n', ' ', path.read_text())
    directives: list[tuple[str, str]] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        parts = stripped.split(None, 1)
        if len(parts) == 2:  # noqa: PLR2004
            directives.append((parts[0].upper(), parts[1]))
        elif len(parts) == 1:
            directives.append((parts[0].upper(), ''))

    return directives
