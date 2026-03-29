"""
Dockerfile tests
================

Validates Dockerfiles in `docker/` without building images.
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import ALL_DOCKERFILES, DOCKER_DIR, REPO_ROOT, parse_dockerfile

_DF_IDS = [str(p.relative_to(DOCKER_DIR)) for p in ALL_DOCKERFILES]
_HAS_BUILDX = shutil.which('docker') is not None


@pytest.mark.parametrize('dockerfile', ALL_DOCKERFILES, ids=_DF_IDS)
@pytest.mark.skipif(not _HAS_BUILDX, reason='docker not available')
def test_dockerfile_syntax(dockerfile: Path) -> None:
    """Dockerfile must pass `docker buildx build --check` with no errors."""

    r = subprocess.run(
        ['docker', 'buildx', 'build', '--check', '-f', str(dockerfile), '.'],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )

    if r.returncode != 0:
        has_error = any(line.startswith('ERROR') for line in r.stdout.splitlines())
        assert not has_error, f'Dockerfile syntax error:\n{r.stdout}'


@pytest.mark.parametrize('dockerfile', ALL_DOCKERFILES, ids=_DF_IDS)
def test_no_latest_tag(dockerfile: Path) -> None:
    """`FROM` must not use `:latest` - pin a specific version."""

    for cmd, rest in parse_dockerfile(dockerfile):
        if cmd == 'FROM':
            image = rest.split()[0]
            assert not image.endswith(':latest'), (
                f'FROM {image} uses :latest - pin a specific version'
            )


@pytest.mark.parametrize('dockerfile', ALL_DOCKERFILES, ids=_DF_IDS)
def test_apt_cache_cleaned(dockerfile: Path) -> None:
    """Every `apt-get install` must be paired with cache cleanup."""

    text = dockerfile.read_text()
    installs = len(re.findall(r'apt-get install', text))
    cleanups = len(re.findall(r'rm -rf /var/lib/apt/lists', text))

    assert cleanups >= installs, (
        f'{installs} apt-get install(s) but only {cleanups} cache cleanup(s)'
    )
