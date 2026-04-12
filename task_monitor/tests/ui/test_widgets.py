"""
Tests widgets
=============
"""

import pytest

from monitor.ui.widgets import classify_log_line


@pytest.mark.parametrize(
    'line',
    [
        'RuntimeError: boom',
        'Traceback (most recent call last):',
        'ValueError: bad exception data',
        'ERROR: something broke',
    ],
)
def test_classify_error_keywords(line: str) -> None:
    """Lines containing error-related keywords are tagged 'error'."""

    assert classify_log_line(line) == 'error'


@pytest.mark.parametrize(
    'line',
    [
        'WARNING: deprecated call',
        'warn: resource low',
        'Warning: retry',
    ],
)
def test_classify_warning_keywords(line: str) -> None:
    """Lines containing 'warn' but not 'error' are tagged 'warn'."""

    assert classify_log_line(line) == 'warn'


@pytest.mark.parametrize(
    'line',
    [
        '[cleanup] removed 3 jobs',
        '[startup] booting',
        'Job complete',
        'complete',
    ],
)
def test_classify_info_keywords(line: str) -> None:
    """Lines with cleanup/startup/complete are tagged 'info'."""

    assert classify_log_line(line) == 'info'


@pytest.mark.parametrize(
    'line',
    [
        'Processing step 4/10...',
        '',
        'Normal log output',
        'Download incomplete - retrying',
    ],
)
def test_classify_unclassified_returns_empty(line: str) -> None:
    """Lines without keywords are untagged (empty string)."""

    assert classify_log_line(line) == ''


def test_classify_multiple_keywords_error_wins() -> None:
    """When a line matches both error and warn, error takes priority."""

    assert classify_log_line('Error: warning ignored') == 'error'


def test_classify_keyword_inside_word() -> None:
    """'warning' contains 'warn' — substring matching is intentional."""

    assert classify_log_line('DeprecationWarning: old API') == 'warn'
