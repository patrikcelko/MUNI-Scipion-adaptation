"""
Pytest fixtures
===============
"""

import json
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_response():
    """Factory fixture returning a `urlopen` context-manager mock."""

    def _make(payload: dict[str, Any] | list[Any]) -> MagicMock:
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)

        return resp

    return _make
