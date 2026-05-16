"""
Tool routing
============
"""

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

import yaml

import controller.utilities.routing as routing_mod
from controller.utilities.routing import (
    choose_tool,
    choose_tool_by_protocol,
    detect_protocol_from_command,
    detect_protocol_run_dir,
    load_toolmap,
)


def test_detect_protocol_xmipp() -> None:
    """Xmipp protocol extracted from run command."""

    cmd = 'python3 Runs/006383_XmippProtMovieGain/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'XmippProtMovieGain'


def test_detect_protocol_relion() -> None:
    """Relion protocol extracted from run command."""

    cmd = 'python3 Runs/000100_ProtRelionRefine3D/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'ProtRelionRefine3D'


def test_detect_protocol_ctffind() -> None:
    """CTFFind protocol extracted from run command."""

    cmd = 'Runs/000200_CistemProtCTFFind/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'CistemProtCTFFind'


def test_detect_protocol_gctf() -> None:
    """Gctf protocol extracted from run command."""

    cmd = 'python3 Runs/000300_ProtGctf/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'ProtGctf'


def test_detect_protocol_eman() -> None:
    """EMAN protocol extracted from run command."""

    cmd = 'python3 Runs/000400_EmanProtBoxing/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'EmanProtBoxing'


def test_detect_protocol_no_match() -> None:
    """Non-Scipion command returns None."""

    assert detect_protocol_from_command('ls -la') is None


def test_detect_protocol_empty_string() -> None:
    """Empty string returns None."""

    assert detect_protocol_from_command('') is None


def test_detect_protocol_full_path_with_project() -> None:
    """Full absolute path still extracts protocol name."""

    cmd = 'python3 /projects/MyProject/Runs/000001_XmippProtMovieGain/logs/run.db'
    assert detect_protocol_from_command(cmd) == 'XmippProtMovieGain'


def test_detect_run_dir_extracts_run_dir() -> None:
    """Extracts Runs/NNNNN_Protocol directory from command."""

    cmd = 'python3 /projects/myproj/Runs/006383_XmippProtMovieGain/logs/run.db'
    assert detect_protocol_run_dir(cmd) == 'Runs/006383_XmippProtMovieGain'


def test_detect_run_dir_no_match() -> None:
    """Non-matching command returns None."""

    assert detect_protocol_run_dir('echo hello') is None


def test_detect_run_dir_empty_string() -> None:
    """Empty string returns None."""

    assert detect_protocol_run_dir('') is None


def test_detect_run_dir_multiple_runs_dirs() -> None:
    """First match wins."""

    cmd = 'Runs/001_A/logs Runs/002_B/logs'
    result = detect_protocol_run_dir(cmd)
    assert result == 'Runs/001_A'


def test_load_toolmap_list_format(tmp_path: Any) -> None:
    """List-format YAML is loaded and enabled defaults to True."""

    f = tmp_path / 'tools.yaml'
    f.write_text("- image: relion:v1\n  match: '.*'\n")
    result = load_toolmap(str(f))

    assert len(result) == 1
    assert result[0]['enabled'] is True


def test_load_toolmap_dict_format(tmp_path: Any) -> None:
    """Dict-format YAML (tools: key) is loaded."""

    f = tmp_path / 'tools.yaml'
    f.write_text("tools:\n  - image: xmipp:v1\n    match: '.*'\n")
    result = load_toolmap(str(f))

    assert len(result) == 1
    assert result[0]['image'] == 'xmipp:v1'


def test_load_toolmap_missing_file_returns_empty() -> None:
    """Missing file returns empty list."""

    result = load_toolmap('/nonexistent/tools.yaml')
    assert result == []


def test_load_toolmap_preserves_existing_enabled_flag(tmp_path: Any) -> None:
    """Explicit enabled: false is preserved."""

    f = tmp_path / 'tools.yaml'
    f.write_text("- image: test:v1\n  match: '.*'\n  enabled: false\n")
    result = load_toolmap(str(f))

    assert result[0]['enabled'] is False


def test_load_toolmap_multiple_tools(tmp_path: Any) -> None:
    """Multiple tool entries are all loaded."""

    f = tmp_path / 'tools.yaml'
    f.write_text("- image: a:v1\n  match: '.*'\n- image: b:v1\n  match: '^python'\n")
    result = load_toolmap(str(f))

    assert len(result) == 2


def test_load_toolmap_empty_dict_format(tmp_path: Any) -> None:
    """Dict-format with no tools returns empty list."""

    f = tmp_path / 'tools.yaml'
    f.write_text('tools:\n')
    result = load_toolmap(str(f))

    assert result == []


def test_load_toolmap_caching_returns_same_data_without_reread(tmp_path: Any) -> None:
    """Second call with unchanged file uses cache (no re-read)."""

    routing_mod._toolmap_cache = None
    routing_mod._toolmap_mtime = 0.0

    f = tmp_path / 'tools.yaml'
    f.write_text("- image: cached:v1\n  match: '.*'\n")
    r1 = load_toolmap(str(f))
    assert r1[0]['image'] == 'cached:v1'

    r2 = load_toolmap(str(f))
    assert r2[0]['image'] == 'cached:v1'

    r2[0]['image'] = 'mutated'
    r3 = load_toolmap(str(f))
    assert r3[0]['image'] == 'cached:v1'

    routing_mod._toolmap_cache = None
    routing_mod._toolmap_mtime = 0.0


TOOLS: list[dict[str, Any]] = [
    {
        'image': 'harbor.io/xmipp:v1',
        'protocol': 'Xmipp',
        'match': '.*',
        'enabled': True,
        'needsGpu': False,
        'gpu_protocols': ['XmippProtMovieCorr'],
    },
    {'image': 'harbor.io/relion:v1', 'protocol': '.*Relion', 'match': '.*', 'enabled': True, 'needsGpu': False},
    {
        'image': 'harbor.io/ctffind4:v1',
        'protocol': 'Cistem|.*CTFFind',
        'match': '.*',
        'enabled': True,
        'needsGpu': False,
    },
    {'image': 'harbor.io/gctf:v1', 'protocol': '.*Gctf|ProtGctf', 'match': '.*', 'enabled': True, 'needsGpu': True},
    {
        'image': 'harbor.io/motioncor2:v1',
        'protocol': '.*MotionCor',
        'match': '.*',
        'enabled': True,
        'needsGpu': True,
    },
    {'image': 'harbor.io/eman2:v1', 'protocol': 'Eman', 'match': '.*', 'enabled': True, 'needsGpu': False},
    {
        'image': 'harbor.io/scipion3-remote:v1',
        'match': '.*',
        'default': True,
        'enabled': True,
        'needsGpu': False,
    },
]


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_xmipp() -> None:
    """Xmipp protocol routes to xmipp container."""

    result = choose_tool_by_protocol('XmippProtMovieGain', '/dev/null')
    assert result is not None
    assert 'xmipp' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_relion() -> None:
    """Relion protocol routes to relion container."""

    result = choose_tool_by_protocol('ProtRelionRefine3D', '/dev/null')
    assert result is not None
    assert 'relion' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_ctffind() -> None:
    """CTFFind protocol routes to ctffind4 container."""

    result = choose_tool_by_protocol('CistemProtCTFFind', '/dev/null')
    assert result is not None
    assert 'ctffind4' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_gctf() -> None:
    """Gctf protocol routes to gctf container."""

    result = choose_tool_by_protocol('ProtGctf', '/dev/null')
    assert result is not None
    assert 'gctf' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_motioncor() -> None:
    """MotionCorr protocol routes to motioncor2 container."""

    result = choose_tool_by_protocol('ProtMotionCorr', '/dev/null')
    assert result is not None
    assert 'motioncor2' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_eman2() -> None:
    """EMAN protocol routes to eman2 container."""

    result = choose_tool_by_protocol('EmanProtBoxing', '/dev/null')
    assert result is not None
    assert 'eman2' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_unknown_falls_back_to_scipion() -> None:
    """Unknown protocol falls back to scipion3-remote container."""

    result = choose_tool_by_protocol('SomeUnknownProtocol', '/dev/null')
    assert result is not None
    assert 'scipion3-remote' in result['image']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_gpu_override_xmipp_movie_corr() -> None:
    """XmippProtMovieCorr gets GPU override."""

    result = choose_tool_by_protocol('XmippProtMovieCorr', '/dev/null')
    assert result is not None
    assert result['needsGpu'] is True


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_gpu_override_gctf() -> None:
    """ProtGctf gets GPU override."""

    result = choose_tool_by_protocol('ProtGctf', '/dev/null')
    assert result is not None
    assert result['needsGpu'] is True


def test_choose_by_protocol_empty_protocol_name() -> None:
    """Empty protocol name returns None."""

    assert choose_tool_by_protocol('', '/dev/null') is None


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=[]))
def test_choose_by_protocol_empty_toolmap() -> None:
    """Empty toolmap returns None."""

    assert choose_tool_by_protocol('XmippProtMovieGain', '/dev/null') is None


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_choose_by_protocol_returns_copy_not_original() -> None:
    """Returned dict must be a copy so mutations don't affect cache."""

    result = choose_tool_by_protocol('XmippProtMovieGain', '/dev/null')
    assert result is not None

    result['image'] = 'mutated'
    result2 = choose_tool_by_protocol('XmippProtMovieGain', '/dev/null')
    assert result2 is not None
    assert 'xmipp' in result2['image']


def test_choose_tool_matches_prefix() -> None:
    """Matching prefix selects the tool."""

    tools = [{'match': r'^python3', 'image': 'test:v1', 'enabled': True}]
    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        result = choose_tool('python3', '/dev/null')

        assert result is not None
        assert result['image'] == 'test:v1'


def test_choose_tool_no_match() -> None:
    """Non-matching command returns None."""

    tools = [{'match': r'^relion_', 'image': 'test:v1', 'enabled': True}]
    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        assert choose_tool('python3', '/dev/null') is None


def test_choose_tool_disabled_tool_skipped() -> None:
    """Disabled tool is skipped."""

    tools = [{'match': r'^python3', 'image': 'test:v1', 'enabled': False}]
    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        assert choose_tool('python3', '/dev/null') is None


def test_choose_tool_copy_returns_dict_copy() -> None:
    """Mutating the return value must not affect subsequent calls."""

    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump([{'image': 'xmipp:v1', 'match': '^python3', 'enabled': True}], f)
        path = f.name
    try:
        routing_mod._toolmap_cache = None
        result1 = choose_tool('python3', path)

        assert result1 is not None

        result1['MUTATED'] = True
        routing_mod._toolmap_cache = None
        result2 = choose_tool('python3', path)

        assert result2 is not None
        assert 'MUTATED' not in result2
    finally:
        Path(path).unlink()


def test_choose_tool_missing_match_tool_without_match_key_skipped() -> None:
    """Tool without match key is skipped, next matching tool is returned."""

    tools = [
        {'image': 'no-match:v1', 'enabled': True},
        {'image': 'has-match:v1', 'match': '^python3', 'enabled': True},
    ]

    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        result = choose_tool('python3', '/dev/null')

        assert result is not None
        assert result['image'] == 'has-match:v1'


def test_choose_tool_missing_match_all_tools_without_match_returns_none() -> None:
    """All tools without match key returns None."""

    tools = [{'image': 'no-match:v1', 'enabled': True}]
    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        assert choose_tool('python3', '/dev/null') is None


def test_choose_by_protocol_disabled_tool_skipped() -> None:
    """Disabled tool is skipped even when its protocol regex matches."""

    tools = [
        {'image': 'harbor.io/xmipp:v1', 'protocol': 'Xmipp', 'enabled': False, 'needsGpu': False},
        {'image': 'harbor.io/scipion3-remote:v1', 'default': True, 'enabled': True, 'needsGpu': False},
    ]
    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        result = choose_tool_by_protocol('XmippProtMovieGain', '/dev/null')

    assert result is not None
    assert 'scipion3-remote' in result['image']


def test_choose_by_protocol_disabled_default_not_used() -> None:
    """Disabled default entry is not returned as fallback, so result is None."""

    tools = [
        {'image': 'harbor.io/scipion3-remote:v1', 'default': True, 'enabled': False, 'needsGpu': False},
    ]

    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        assert choose_tool_by_protocol('AnyProtocol', '/dev/null') is None


def test_choose_by_protocol_case_insensitive() -> None:
    """Protocol matching uses re.IGNORECASE, so lowercase input still routes correctly."""

    tools = [
        {'image': 'harbor.io/relion:v1', 'protocol': '.*Relion', 'enabled': True, 'needsGpu': False},
        {'image': 'harbor.io/scipion3-remote:v1', 'default': True, 'enabled': True, 'needsGpu': False},
    ]

    with patch('controller.utilities.routing.load_toolmap', return_value=tools):
        result = choose_tool_by_protocol('protrelionrefine3d', '/dev/null')

    assert result is not None
    assert 'relion' in result['image']


def test_load_toolmap_cache_invalidated_on_mtime_change(tmp_path: Any) -> None:
    """Cache is reloaded when the file modification time changes."""

    routing_mod._toolmap_cache = None
    routing_mod._toolmap_mtime = 0.0

    f = tmp_path / 'tools.yaml'
    f.write_text("- image: original:v1\n  match: '.*'\n")
    r1 = load_toolmap(str(f))
    assert r1[0]['image'] == 'original:v1'

    # Overwrite content and advance mtime so the cache check detects a change.
    f.write_text("- image: updated:v1\n  match: '.*'\n")
    stat = f.stat()
    os.utime(str(f), (stat.st_atime + 1, stat.st_mtime + 1))

    r2 = load_toolmap(str(f))
    assert r2[0]['image'] == 'updated:v1'

    routing_mod._toolmap_cache = None
    routing_mod._toolmap_mtime = 0.0
