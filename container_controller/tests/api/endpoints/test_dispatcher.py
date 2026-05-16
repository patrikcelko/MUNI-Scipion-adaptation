"""
Dispatcher endpoint
===================
"""

import json
import re
import urllib.error
from typing import Any
from unittest.mock import MagicMock, Mock, patch

from fastapi.testclient import TestClient

from controller import create_app
from controller.api.endpoints.dispatcher import _resolve_to_public_ip
from controller.utilities.config import Settings


def test_import_workflow_missing_workflow_url(client: Any) -> None:
    """Missing workflow_url returns 400."""

    resp = client.post('/import_workflow', json={})
    assert resp.status_code == 400
    assert 'workflow_url' in resp.json()['error']


def test_import_workflow_invalid_scheme(client: Any) -> None:
    """Non-http(s) scheme returns 400."""

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'ftp://example.com/w.json'},
    )
    assert resp.status_code == 400
    assert 'http' in resp.json()['error']


@patch('urllib.request.urlopen')
def test_import_workflow_successful(mock_urlopen: Any, client: Any, tmp_path: Any) -> None:
    """Successful workflow import returns 200 with project info."""

    workflow = [{'protocol': 'XmippProtMovieGain', 'params': {}}]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(workflow).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    settings = Settings(
        namespace='test-ns',
        storage_mode='local',
        local_path=str(tmp_path),
        toolmap_path='/dev/null',
    )
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(
            '/import_workflow',
            json={
                'workflow_url': 'https://example.com/workflow.json',
                'project_name': 'TestProject',
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data['ok'] is True
        assert data['project_name'] == 'TestProject'
        assert data['protocols_count'] == 1
        assert 'vnc_url' in data


@patch('urllib.request.urlopen')
def test_import_workflow_non_list(mock_urlopen: Any, client: Any) -> None:
    """Non-list workflow body returns 400."""

    mock_resp = MagicMock()
    mock_resp.read.return_value = b'{"not": "a list"}'
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'https://example.com/w.json'},
    )
    assert resp.status_code == 400
    assert 'list' in resp.json()['error']


def test_import_workflow_project_name_sanitisation() -> None:
    """Verify special characters are replaced with underscores."""

    sanitised = re.sub(r'[^A-Za-z0-9_-]', '_', 'My Project!@#$%')[:64]
    assert sanitised == 'My_Project_____'


@patch('urllib.request.urlopen')
def test_import_workflow_default_project_name(mock_urlopen: Any, client: Any, tmp_path: Any) -> None:
    """When project_name is omitted, falls back to 'DispatcherProject'."""

    workflow = [{'protocol': 'A'}]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(workflow).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    settings = Settings(
        namespace='test-ns',
        storage_mode='local',
        local_path=str(tmp_path),
        toolmap_path='/dev/null',
    )
    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.post(
            '/import_workflow',
            json={'workflow_url': 'https://example.com/w.json'},
        )
        assert resp.status_code == 200
        assert resp.json()['project_name'] == 'DispatcherProject'


@patch('urllib.request.urlopen')
def test_import_workflow_download_failure(mock_urlopen: Any, client: Any) -> None:
    """Download failure returns 400 with error message."""

    mock_urlopen.side_effect = urllib.error.URLError('connection refused')

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'https://example.com/w.json'},
    )
    assert resp.status_code == 400
    assert 'Failed' in resp.json()['error']


@patch(
    'controller.api.endpoints.dispatcher._resolve_to_public_ip',
    new=Mock(return_value=None),
)
def test_ssrf_private_ip_blocked(client: Any) -> None:
    """_resolve_to_public_ip returns None for internal networks."""

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'http://10.0.0.1/secret'},
    )
    assert resp.status_code == 400
    assert 'private' in resp.json()['error']


@patch(
    'controller.api.endpoints.dispatcher._resolve_to_public_ip',
    new=Mock(return_value=None),
)
def test_ssrf_localhost_blocked(client: Any) -> None:
    """_resolve_to_public_ip returns None for localhost."""

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'http://127.0.0.1:8080/admin'},
    )
    assert resp.status_code == 400
    assert 'private' in resp.json()['error']


def test_ssrf_no_hostname_blocked(client: Any) -> None:
    """URL with no hostname is rejected."""

    resp = client.post(
        '/import_workflow',
        json={'workflow_url': 'http:///no-host'},
    )
    assert resp.status_code == 400


def test_is_private_host_loopback() -> None:
    """Loopback address is not resolved as public."""

    assert _resolve_to_public_ip('127.0.0.1') is None


def test_is_private_host_private_10() -> None:
    """10.x.x.x range is not resolved as public."""

    assert _resolve_to_public_ip('10.0.0.1') is None


def test_is_private_host_private_192() -> None:
    """192.168.x.x range is not resolved as public."""

    assert _resolve_to_public_ip('192.168.1.1') is None


def test_is_private_host_unresolvable_rejected() -> None:
    """Unresolvable hostname returns None."""

    assert _resolve_to_public_ip('this-host-does-not-exist.invalid') is None


@patch('urllib.request.urlopen')
def test_import_workflow_duplicate_project_returns_409(mock_urlopen: Any, tmp_path: Any) -> None:
    """Second import with the same project_name returns 409 Conflict."""

    workflow = [{'protocol': 'XmippProtMovieGain'}]
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(workflow).encode()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = mock_resp

    settings = Settings(
        namespace='test-ns',
        storage_mode='local',
        local_path=str(tmp_path),
        toolmap_path='/dev/null',
    )
    app = create_app(settings)
    payload = {
        'workflow_url': 'https://example.com/workflow.json',
        'project_name': 'DuplicateProject',
    }

    with TestClient(app, raise_server_exceptions=False) as c:
        resp1 = c.post('/import_workflow', json=payload)
        assert resp1.status_code == 200

        resp2 = c.post('/import_workflow', json=payload)
        assert resp2.status_code == 409
        assert 'already exists' in resp2.json()['error']


def test_dispatcher_invalid_json_plain_text_body(client: Any) -> None:
    """POST /import_workflow with non-JSON body must return 400."""

    resp = client.post(
        '/import_workflow',
        content='not json',
        headers={'content-type': 'text/plain'},
    )
    assert resp.status_code == 400
    assert 'error' in resp.json()
