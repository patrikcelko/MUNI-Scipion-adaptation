"""
Configuration file Tests
========================
"""

import re
from pathlib import Path

import pytest
import yaml

from conftest import TOOLS_YAML

_TOOLS_YAML: Path = TOOLS_YAML


@pytest.fixture()
def tools() -> list[dict[str, object]]:
    """Parsed content of `tools.yaml`."""

    return yaml.safe_load(_TOOLS_YAML.read_text()) or []


def test_tools_schema(tools: list[dict[str, object]]) -> None:
    """Every entry has required keys with correct types.

    - 'image', 'needsGpu', 'enabled' are always required.
    - 'protocol' OR 'default: true' must be present (routing needs one or the other).
    - 'match' is optional (fallback, not required).
    """

    for i, tool in enumerate(tools):
        assert 'image' in tool, f'Tool #{i} missing key: image'
        assert isinstance(tool['needsGpu'], bool), f'Tool #{i}: needsGpu not bool'
        assert isinstance(tool['enabled'], bool), f'Tool #{i}: enabled not bool'

        has_routing = 'protocol' in tool or tool.get('default') is True
        assert has_routing, f'Tool #{i} has neither protocol nor default:true'


def test_tools_match_patterns_compile(tools: list[dict[str, object]]) -> None:
    """Every `match` value, where present, must be a valid regex."""

    for tool in tools:
        if 'match' not in tool:
            continue
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

    patterns = [str(t['match']) for t in tools if 'match' in t]
    assert len(patterns) == len(set(patterns)), 'Duplicate match patterns found'


def test_tools_protocol_patterns_compile(tools: list[dict[str, object]]) -> None:
    """Every `protocol` value, where present, must be a valid regex."""

    for i, tool in enumerate(tools):
        if 'protocol' not in tool:
            continue

        pattern = str(tool['protocol'])
        try:
            re.compile(pattern)
        except re.error as exc:
            pytest.fail(f"Tool #{i}: invalid protocol regex '{pattern}': {exc}")


def test_tools_no_duplicate_protocol_patterns(tools: list[dict[str, object]]) -> None:
    """No two enabled tools should share the same protocol pattern."""

    patterns = [str(t['protocol']) for t in tools if 'protocol' in t and t.get('enabled', True)]
    assert len(patterns) == len(set(patterns)), 'Duplicate protocol patterns found'


def test_tools_exactly_one_default(tools: list[dict[str, object]]) -> None:
    """Exactly one enabled tool must carry default: true (the fallback container)."""

    defaults = [t for t in tools if t.get('default') is True and t.get('enabled', True)]
    assert len(defaults) == 1, f'Expected exactly 1 enabled default, got {len(defaults)}'


def test_tools_gpu_protocols_are_strings(tools: list[dict[str, object]]) -> None:
    """Every entry in gpu_protocols must be a non-empty string."""

    for i, tool in enumerate(tools):
        for j, proto in enumerate(tool.get('gpu_protocols', [])):  # type: ignore[union-attr]
            assert isinstance(proto, str) and proto, (
                f'Tool #{i} gpu_protocols[{j}] is not a non-empty string'
            )


@pytest.mark.parametrize('protocol_name,expected_image_fragment', [
    ('XmippProtMovieGain', 'xmipp'),
    ('XmippProtMovieCorr', 'xmipp'),
    ('ProtRelionRefine3D', 'relion'),
    ('CistemProtCTFFind', 'ctffind4'),
])
def test_tools_known_protocols_route_to_correct_image(
    tools: list[dict[str, object]],
    protocol_name: str,
    expected_image_fragment: str,
) -> None:
    """Known Scipion protocol class names match the expected enabled tool entry."""

    for tool in tools:
        if not tool.get('enabled', True):
            continue

        pattern = str(tool.get('protocol', ''))
        if not pattern:
            continue

        if re.match(pattern, protocol_name, re.IGNORECASE):
            assert expected_image_fragment in str(tool['image']), (
                f"'{protocol_name}' matched tool with image '{tool['image']}', "
                f"expected fragment '{expected_image_fragment}'"
            )

            return

    pytest.fail(f"No enabled tool matched protocol '{protocol_name}'")
