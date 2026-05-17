"""
Test Client
===========
"""

from unittest.mock import MagicMock, patch

import pytest

from monitor.api.client import DEFAULT_URL, ControllerClient

_URLOPEN = 'monitor.api.client.urlopen'
_BASE = 'http://test:5000'


def test_default_url() -> None:
    """Without env or explicit arg, client uses the default URL."""

    assert ControllerClient().base_url == DEFAULT_URL


def test_explicit_url_strips_trailing_slash() -> None:
    """Explicit URL argument has its trailing slash stripped."""

    assert ControllerClient('http://localhost:8080/').base_url == 'http://localhost:8080'


def test_env_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """If CONTROLLER_URL is set, it is used as the base URL."""

    monkeypatch.setenv('CONTROLLER_URL', 'http://env-host:9000')
    assert ControllerClient().base_url == 'http://env-host:9000'


def test_explicit_overrides_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit URL argument takes precedence over environment variable."""

    monkeypatch.setenv('CONTROLLER_URL', 'http://env-host:9000')
    assert ControllerClient('http://explicit:1234').base_url == 'http://explicit:1234'


@patch(_URLOPEN)
def test_fetch_returns_parsed_json(mock_urlopen: MagicMock, mock_response) -> None:
    """A successful fetch returns parsed JSON."""

    mock_urlopen.return_value = mock_response({'jobs': []})
    client = ControllerClient(_BASE)

    assert client.fetch('/api/jobs') == {'jobs': []}
    assert mock_urlopen.call_args[0][0].full_url == f'{_BASE}/api/jobs'


@patch(_URLOPEN)
def test_fetch_network_error_returns_none(mock_urlopen: MagicMock) -> None:
    """Network errors during fetch return None."""

    mock_urlopen.side_effect = OSError('connection refused')
    assert ControllerClient(_BASE).fetch('/api/pods') is None


@patch(_URLOPEN)
def test_fetch_malformed_json_returns_none(mock_urlopen: MagicMock) -> None:
    """Invalid JSON body makes fetch return None."""

    resp = MagicMock()
    resp.read.return_value = b'not-json'
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = resp

    assert ControllerClient(_BASE).fetch('/api/jobs') is None


@patch(_URLOPEN)
def test_fetch_dict_filters_list_response(mock_urlopen: MagicMock, mock_response) -> None:
    """_fetch_dict returns None when the API responds with a JSON array."""

    mock_urlopen.return_value = mock_response([{'name': 'a'}])
    assert ControllerClient(_BASE)._fetch_dict('/api/jobs') is None


@patch(_URLOPEN)
def test_fetch_dict_passes_dict_response(mock_urlopen: MagicMock, mock_response) -> None:
    """_fetch_dict passes through dict responses."""

    mock_urlopen.return_value = mock_response({'jobs': []})
    assert ControllerClient(_BASE)._fetch_dict('/api/jobs') == {'jobs': []}


@patch(_URLOPEN)
def test_mutate_sends_correct_method(mock_urlopen: MagicMock, mock_response) -> None:
    """mutate() sets the HTTP method on the Request."""

    mock_urlopen.return_value = mock_response({'ok': True})
    client = ControllerClient(_BASE)

    client.mutate('DELETE', '/api/job/x')
    assert mock_urlopen.call_args[0][0].get_method() == 'DELETE'

    client.mutate('POST', '/api/cleanup/run')
    assert mock_urlopen.call_args[0][0].get_method() == 'POST'


@patch(_URLOPEN)
def test_mutate_error_returns_none(mock_urlopen: MagicMock) -> None:
    """Network errors during mutate return None."""

    mock_urlopen.side_effect = OSError('timeout')
    assert ControllerClient(_BASE).mutate('DELETE', '/api/job/x') is None


@pytest.mark.parametrize(
    ('method', 'endpoint'),
    [
        ('get_jobs', '/api/jobs'),
        ('get_pods', '/api/pods'),
        ('get_events', '/api/events'),
        ('get_metrics', '/api/metrics'),
        ('get_disk', '/api/disk'),
    ],
)
@patch(_URLOPEN)
def test_get_endpoint_routing(
    mock_urlopen: MagicMock,
    mock_response,
    method: str,
    endpoint: str,
) -> None:
    """GET convenience methods hit the correct endpoints."""

    mock_urlopen.return_value = mock_response({})
    client = ControllerClient(_BASE)

    getattr(client, method)()
    assert mock_urlopen.call_args[0][0].full_url == f'{_BASE}{endpoint}'


@patch(_URLOPEN)
def test_get_logs_with_tail(mock_urlopen: MagicMock, mock_response) -> None:
    """get_logs sends pod name and tail parameter in the URL."""

    mock_urlopen.return_value = mock_response({'lines': ['line1']})
    client = ControllerClient(_BASE)

    assert client.get_logs('my-pod', tail=100) == {'lines': ['line1']}
    assert mock_urlopen.call_args[0][0].full_url == f'{_BASE}/api/logs/my-pod?tail=100'


@patch(_URLOPEN)
def test_get_logs_default_tail(mock_urlopen: MagicMock, mock_response) -> None:
    """get_logs defaults to tail=50."""

    mock_urlopen.return_value = mock_response({'lines': []})
    ControllerClient(_BASE).get_logs('p1')

    assert 'tail=50' in mock_urlopen.call_args[0][0].full_url


@pytest.mark.parametrize(
    ('method', 'args', 'http_method', 'url_part'),
    [
        ('delete_job', ('j1',), 'DELETE', '/api/job/j1'),
        ('delete_pod', ('p1',), 'DELETE', '/api/pod/p1'),
        ('run_cleanup', (), 'POST', '/api/cleanup/run'),
    ],
)
@patch(_URLOPEN)
def test_mutate_convenience_methods(
    mock_urlopen: MagicMock,
    mock_response,
    method: str,
    args: tuple,
    http_method: str,
    url_part: str,
) -> None:
    """delete_job, delete_pod, run_cleanup use the right HTTP method and URL."""

    mock_urlopen.return_value = mock_response({'deleted': 'ok'})
    client = ControllerClient(_BASE)

    result = getattr(client, method)(*args)
    assert result == {'deleted': 'ok'}

    req = mock_urlopen.call_args[0][0]
    assert req.get_method() == http_method
    assert url_part in req.full_url


@pytest.mark.parametrize(
    ('method', 'args'),
    [
        ('get_logs', ('pod/with spaces',)),
        ('delete_job', ('job/with spaces',)),
        ('delete_pod', ('pod/with spaces',)),
    ],
)
@patch(_URLOPEN)
def test_path_segments_are_url_encoded(
    mock_urlopen: MagicMock,
    mock_response,
    method: str,
    args: tuple,
) -> None:
    """Special characters in resource names are percent-encoded."""

    mock_urlopen.return_value = mock_response({})
    client = ControllerClient(_BASE)

    getattr(client, method)(*args)
    url = mock_urlopen.call_args[0][0].full_url
    assert '%2Fwith%20spaces' in url


@patch(_URLOPEN)
def test_run_cleanup_returns_correct_shape(mock_urlopen: MagicMock, mock_response: MagicMock) -> None:
    """run_cleanup passes through the real /api/cleanup/run response shape."""

    payload = {'deleted_ttl': 2, 'deleted_cap': 1, 'evicted': 0}
    mock_urlopen.return_value = mock_response(payload)
    result = ControllerClient(_BASE).run_cleanup()

    assert result == payload

    assert isinstance(result, dict)
    assert 'deleted' not in result
    assert 'deleted_ttl' in result
    assert 'deleted_cap' in result
    assert 'evicted' in result
