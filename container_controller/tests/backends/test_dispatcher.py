"""
Dispatcher backend
==================
"""

import http.client
import json
import urllib.error
from io import BytesIO
from typing import Any, Self
from unittest.mock import MagicMock, patch

import pytest

from controller.backends import _BACKENDS, BackendError, create_backend
from controller.backends.dispatcher import DispatcherBackend
from controller.utilities.config import Settings


def _make_settings(**overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        'namespace': 'disp-ns',
        'jobs_ttl': 300,
        'jobs_cleanup_interval': 60,
        'storage_mode': 'pvc',
        'projects_pvc': 'test-pvc',
        'pvc_sub_path': 'projects',
        'toolmap_path': '/dev/null',
        'onedata_enabled': False,
        'dispatcher_url': 'https://dispatcher.example.com',
        'dispatcher_token': 'test-token-123',
        'dispatcher_timeout': 10,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_backend(**overrides: Any) -> DispatcherBackend:
    return DispatcherBackend(_make_settings(**overrides))


class _FakeResponse:
    """Minimal HTTP response object for mocking `urllib.request.urlopen`."""

    def __init__(self, data: dict[str, Any], code: int = 200) -> None:
        self._data = json.dumps(data).encode('utf-8')
        self.code = code

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        pass


def test_dispatcher_init_base_url_strips_trailing_slash() -> None:
    """Constructor stores configuration from Settings."""

    be = _make_backend(dispatcher_url='https://disp.example.com/')
    assert be._base_url == 'https://disp.example.com'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_get_request(mock_urlopen: MagicMock) -> None:
    """GET request returns parsed JSON."""

    mock_urlopen.return_value = _FakeResponse({'ok': True})
    be = _make_backend()
    result = be._request('GET', '/healthz')

    assert result == {'ok': True}


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_post_sends_json_body(mock_urlopen: MagicMock) -> None:
    """POST sends JSON-encoded body."""

    mock_urlopen.return_value = _FakeResponse({'task_id': 't1'})
    be = _make_backend()
    be._request('POST', '/requests/metadata_rocrate/', body={'key': 'val'})

    req_obj = mock_urlopen.call_args[0][0]
    assert req_obj.data == json.dumps({'key': 'val'}).encode('utf-8')
    assert req_obj.get_header('Content-type') == 'application/json'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_post_empty_dict_body_sends_json(
    mock_urlopen: MagicMock,
) -> None:
    """Empty dict `{}` must still be sent as JSON (not treated as no body)."""

    mock_urlopen.return_value = _FakeResponse({'ok': True})
    be = _make_backend()
    be._request('POST', '/test', body={})

    req_obj = mock_urlopen.call_args[0][0]
    assert req_obj.data == b'{}'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_invalid_json_response_raises_backend_error(
    mock_urlopen: MagicMock,
) -> None:
    """Non-JSON response (e.g. HTML from reverse proxy) -> BackendError."""

    fake = MagicMock()
    fake.read.return_value = b'<html>Bad Gateway</html>'
    fake.__enter__ = lambda s: s
    fake.__exit__ = MagicMock(return_value=False)
    mock_urlopen.return_value = fake
    be = _make_backend()

    with pytest.raises(BackendError) as exc_info:
        be._request('GET', '/test')
    assert exc_info.value.status_code == 502


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_auth_header_added_when_token_present(
    mock_urlopen: MagicMock,
) -> None:
    """Auth header is added when a token is present."""

    mock_urlopen.return_value = _FakeResponse({'ok': True})
    be = _make_backend(dispatcher_token='secret')
    be._request('GET', '/test')

    req_obj = mock_urlopen.call_args[0][0]
    assert req_obj.get_header('Authorization') == 'Bearer secret'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_no_auth_header_when_no_token(
    mock_urlopen: MagicMock,
) -> None:
    """No auth header when token is empty."""

    mock_urlopen.return_value = _FakeResponse({'ok': True})
    be = _make_backend(dispatcher_token='')
    be._request('GET', '/test')

    req_obj = mock_urlopen.call_args[0][0]
    assert req_obj.get_header('Authorization') is None


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_http_error_raises_backend_error(
    mock_urlopen: MagicMock,
) -> None:
    """HTTPError is wrapped into BackendError with matching status code."""

    mock_urlopen.side_effect = urllib.error.HTTPError(
        'https://disp/test',
        500,
        'Internal Server Error',
        http.client.HTTPMessage(),
        BytesIO(b'error details'),
    )
    be = _make_backend()

    with pytest.raises(BackendError) as exc_info:
        be._request('GET', '/test')
    assert exc_info.value.status_code == 500


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_request_url_error_raises_backend_error_502(
    mock_urlopen: MagicMock,
) -> None:
    """URLError (connection refused etc.) -> BackendError 502."""

    mock_urlopen.side_effect = urllib.error.URLError('connection refused')
    be = _make_backend()

    with pytest.raises(BackendError) as exc_info:
        be._request('GET', '/test')
    assert exc_info.value.status_code == 502


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_submit_success_stores_task(
    mock_urlopen: MagicMock,
) -> None:
    """Job submission creates an ROCrate request on the Dispatcher."""

    mock_urlopen.return_value = _FakeResponse({'task_id': 'celery-123'})
    be = _make_backend()

    be.submit_job(
        namespace='disp-ns',
        job_name='xmipp-job-1',
        image='xmipp:v3',
        command=['echo'],
        env={'WORKFLOW_URL': 'https://wf.example.com/wf.json'},
        labels={'app': 'scipion-worker'},
    )

    assert be._tasks['xmipp-job-1'] == 'celery-123'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_submit_uses_authenticated_endpoint_with_token(
    mock_urlopen: MagicMock,
) -> None:
    """Authenticated endpoint is used when token is present."""

    mock_urlopen.return_value = _FakeResponse({'task_id': 't1'})
    be = _make_backend(dispatcher_token='my-token')

    be.submit_job(
        namespace='ns',
        job_name='j1',
        image='img:v1',
        command=['echo'],
        env={},
        labels={},
    )

    req_obj = mock_urlopen.call_args[0][0]
    assert '/requests/metadata_rocrate/' in req_obj.full_url


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_submit_uses_anon_endpoint_without_token(
    mock_urlopen: MagicMock,
) -> None:
    """Anonymous endpoint is used when token is empty."""

    mock_urlopen.return_value = _FakeResponse({'task_id': 't1'})
    be = _make_backend(dispatcher_token='')

    be.submit_job(
        namespace='ns',
        job_name='j1',
        image='img:v1',
        command=['echo'],
        env={},
        labels={},
    )

    req_obj = mock_urlopen.call_args[0][0]
    assert '/anon_requests/metadata_rocrate/' in req_obj.full_url


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_submit_includes_rocrate_metadata(
    mock_urlopen: MagicMock,
) -> None:
    """Submitted body contains valid ROCrate metadata."""

    mock_urlopen.return_value = _FakeResponse({'task_id': 't1'})
    be = _make_backend()

    be.submit_job(
        namespace='ns',
        job_name='my-job',
        image='img:v1',
        command=['echo'],
        env={'WORKFLOW_URL': 'https://wf.example.com/wf.json'},
        labels={},
    )

    req_obj = mock_urlopen.call_args[0][0]
    body = json.loads(req_obj.data.decode('utf-8'))
    assert '@graph' in body

    # Metadata descriptor is mandatory for ROCrate spec
    descriptors = [
        e for e in body['@graph'] if e.get('@id') == 'ro-crate-metadata.json'
    ]
    assert len(descriptors) == 1

    # Workflow uses @id reference to #scipion (not inline)
    workflow = [e for e in body['@graph'] if e.get('@id') == '#workflow']
    assert len(workflow) == 1
    assert workflow[0]['programmingLanguage'] == {'@id': '#scipion'}
    assert 'ComputationalWorkflow' in workflow[0]['@type']

    # #scipion entity has the correct identifier
    scipion = [e for e in body['@graph'] if e.get('@id') == '#scipion']
    assert len(scipion) == 1
    assert scipion[0]['identifier'] == 'http://scipion.i2pc.es/'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_submit_no_task_id_raises_error(
    mock_urlopen: MagicMock,
) -> None:
    """Missing task_id in response raises BackendError."""

    mock_urlopen.return_value = _FakeResponse({})
    be = _make_backend()

    with pytest.raises(BackendError, match='task_id'):
        be.submit_job(
            namespace='ns',
            job_name='j1',
            image='img:v1',
            command=['echo'],
            env={},
            labels={},
        )


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_pending_maps_to_running(mock_urlopen: MagicMock) -> None:
    """PENDING Celery state maps to RUNNING."""

    mock_urlopen.return_value = _FakeResponse({'status': 'PENDING'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'RUNNING'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_progress_maps_to_running(
    mock_urlopen: MagicMock,
) -> None:
    """PROGRESS Celery state maps to RUNNING."""

    mock_urlopen.return_value = _FakeResponse({'status': 'PROGRESS'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'RUNNING'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_started_maps_to_running(mock_urlopen: MagicMock) -> None:
    """STARTED Celery state maps to RUNNING."""

    mock_urlopen.return_value = _FakeResponse({'status': 'STARTED'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'RUNNING'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_success_maps_to_done(mock_urlopen: MagicMock) -> None:
    """SUCCESS Celery state maps to DONE."""

    mock_urlopen.return_value = _FakeResponse({'status': 'SUCCESS'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'DONE'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_failure_maps_to_failed(mock_urlopen: MagicMock) -> None:
    """FAILURE Celery state maps to FAILED."""

    mock_urlopen.return_value = _FakeResponse({'status': 'FAILURE'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'FAILED'


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_revoked_maps_to_failed(mock_urlopen: MagicMock) -> None:
    """REVOKED Celery state maps to FAILED."""

    mock_urlopen.return_value = _FakeResponse({'status': 'REVOKED'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    assert be.read_job_phase('j1', 'ns') == 'FAILED'


def test_dispatcher_read_phase_unknown_job_returns_none() -> None:
    """Unknown job name returns None."""

    be = _make_backend()
    assert be.read_job_phase('nonexistent', 'ns') is None


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_read_phase_http_error_returns_none(mock_urlopen: MagicMock) -> None:
    """HTTP error when polling phase returns None."""

    mock_urlopen.side_effect = urllib.error.HTTPError(
        'url',
        404,
        'Not Found',
        http.client.HTTPMessage(),
        BytesIO(b''),
    )
    be = _make_backend()
    be._tasks['j1'] = 't1'

    assert be.read_job_phase('j1', 'ns') is None


def test_dispatcher_delete_removes_tracked_task() -> None:
    """Deletion removes from local tracking."""

    be = _make_backend()
    be._tasks['j1'] = 't1'
    be.delete_job('j1', 'ns')
    assert 'j1' not in be._tasks


def test_dispatcher_delete_nonexistent_is_noop() -> None:
    """Deleting a nonexistent job is a no-op."""

    be = _make_backend()
    be.delete_job('nonexistent', 'ns')


def test_dispatcher_monitoring_list_pods_empty() -> None:
    """list_pods returns empty list."""

    assert _make_backend().list_pods('ns') == []


def test_dispatcher_monitoring_list_events_empty() -> None:
    """list_events returns empty list."""

    assert _make_backend().list_events('ns') == []


def test_dispatcher_monitoring_read_pod_log_empty() -> None:
    """read_pod_log returns empty string."""

    assert _make_backend().read_pod_log('pod-1', 'ns') == ''


def test_dispatcher_monitoring_get_metrics_error_messages() -> None:
    """get_metrics returns error stubs."""

    result = _make_backend().get_metrics('ns')
    assert 'error' in result['nodes'][0]
    assert 'error' in result['pods'][0]


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_monitoring_list_jobs_returns_tracked_tasks(
    mock_urlopen: MagicMock,
) -> None:
    """list_jobs returns all tracked tasks."""

    mock_urlopen.return_value = _FakeResponse({'status': 'PENDING'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    be._tasks['j2'] = 't2'

    jobs = be.list_jobs('ns')
    assert len(jobs) == 2
    names = {j['name'] for j in jobs}
    assert names == {'j1', 'j2'}


def test_dispatcher_admin_list_node_images_empty() -> None:
    """list_node_images returns empty list."""

    assert _make_backend().list_node_images() == []


def test_dispatcher_admin_delete_pod_raises_501() -> None:
    """delete_pod raises BackendError 501."""

    with pytest.raises(BackendError) as exc_info:
        _make_backend().delete_pod('pod-1', 'ns')
    assert exc_info.value.status_code == 501


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_cleanup_empty_tasks(mock_urlopen: MagicMock) -> None:
    """Cleanup with no tasks returns zeroes."""

    be = _make_backend()
    result = be.cleanup_once(namespace='ns', jobs_ttl=300, max_finished_jobs=5)
    assert result == {'deleted_ttl': 0, 'deleted_cap': 0, 'evicted': 0}


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_cleanup_removes_done_tasks_over_cap(
    mock_urlopen: MagicMock,
) -> None:
    """Finished tasks exceeding cap are removed."""

    mock_urlopen.return_value = _FakeResponse({'status': 'SUCCESS'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    be._tasks['j2'] = 't2'
    be._tasks['j3'] = 't3'

    result = be.cleanup_once(namespace='ns', jobs_ttl=300, max_finished_jobs=1)
    assert result['deleted_cap'] == 2


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_cleanup_keeps_running_tasks(
    mock_urlopen: MagicMock,
) -> None:
    """Running tasks are not removed during cleanup."""

    mock_urlopen.return_value = _FakeResponse({'status': 'PENDING'})
    be = _make_backend()
    be._tasks['j1'] = 't1'

    result = be.cleanup_once(namespace='ns', jobs_ttl=300, max_finished_jobs=0)
    assert result['deleted_cap'] == 0
    assert 'j1' in be._tasks


@patch('controller.backends.dispatcher.urllib.request.urlopen')
def test_dispatcher_cleanup_disabled_when_max_negative(
    mock_urlopen: MagicMock,
) -> None:
    """max_finished_jobs=-1 means cap is disabled: never remove."""

    mock_urlopen.return_value = _FakeResponse({'status': 'SUCCESS'})
    be = _make_backend()
    be._tasks['j1'] = 't1'
    be._tasks['j2'] = 't2'

    result = be.cleanup_once(namespace='ns', jobs_ttl=300, max_finished_jobs=-1)
    assert result['deleted_cap'] == 0
    assert len(be._tasks) == 2  # nothing removed


def test_dispatcher_registration_registered() -> None:
    """DispatcherBackend is registered under 'dispatcher'."""

    assert 'dispatcher' in _BACKENDS


def test_dispatcher_registration_create_backend() -> None:
    """create_backend returns a DispatcherBackend instance."""

    be = create_backend('dispatcher', _make_settings())
    assert isinstance(be, DispatcherBackend)
