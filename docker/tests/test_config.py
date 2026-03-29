"""
Configuration file Tests
========================
"""

import re
from pathlib import Path

import pytest
import yaml

from conftest import CONFIG_DIR

_TOOLS_YAML: Path = CONFIG_DIR / 'tools.yaml'


@pytest.fixture()
def tools() -> list[dict[str, object]]:
    """Parsed content of `tools.yaml`."""

    return yaml.safe_load(_TOOLS_YAML.read_text())  # type: ignore[return-value]


def test_tools_schema(tools: list[dict[str, object]]) -> None:
    """Every entry has all required keys with correct types."""

    required = {'match', 'image', 'needsGpu', 'enabled'}
    for i, tool in enumerate(tools):
        missing = required - set(tool.keys())

        assert not missing, f'Tool #{i} missing keys: {missing}'
        assert isinstance(tool['needsGpu'], bool), f'Tool #{i}: needsGpu not bool'
        assert isinstance(tool['enabled'], bool), f'Tool #{i}: enabled not bool'


def test_tools_match_patterns_compile(tools: list[dict[str, object]]) -> None:
    """Every `match` value must be a valid regex."""

    for tool in tools:
        pattern = str(tool['match'])
        try:
            re.compile(pattern)
        except re.error as exc:
            pytest.fail(f"Invalid regex '{pattern}': {exc}")


def test_tools_images_are_pinned(tools: list[dict[str, object]]) -> None:
    """No image may use `:latest` or be untagged."""

    for tool in tools:
        image = str(tool['image'])
        assert ':' in image, f"Image '{image}' has no tag"
        tag = image.rsplit(':', 1)[1]
        assert tag and tag != 'latest', f"Image '{image}' uses :latest or empty tag"


def test_tools_no_duplicate_patterns(tools: list[dict[str, object]]) -> None:
    """No two tools should share the same match pattern."""

    patterns = [str(t['match']) for t in tools]
    assert len(patterns) == len(set(patterns)), 'Duplicate match patterns found'
