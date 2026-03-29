"""
Admin endpoints
===============
"""

import threading
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from kubernetes.client.exceptions import ApiException

from tests.conftest import mock_batch, mock_core


def test_cleanup_status_returns_config(client: Any) -> None:
    """Cleanup status endpoint returns config."""

    resp = client.get('/api/cleanup')
    assert resp.status_code == 200
    data = resp.json()
    assert data['ttl_seconds'] == 300
    assert data['check_interval'] == 60
    assert 'known_jobs' in data
    assert 'thread_alive' in data
    assert isinstance(data['thread_alive'], bool)


def test_cleanup_status_returns_max_finished_jobs(client: Any) -> None:
    """Cleanup status endpoint returns max_finished_jobs."""

    resp = client.get('/api/cleanup')
    assert resp.status_code == 200
    data = resp.json()
    assert 'max_finished_jobs' in data
    assert isinstance(data['max_finished_jobs'], int)


def test_disk_returns_usage(client: Any) -> None:
    """Disk usage endpoint returns usage data."""

    resp = client.get('/api/disk')
    assert resp.status_code == 200

    data = resp.json()
    assert 'total_gi' in data
    assert 'used_gi' in data
    assert 'free_gi' in data
    assert 'percent' in data
    assert 0 <= data['percent'] <= 100


def test_disk_values_are_floats(client: Any) -> None:
    """Disk values are numeric."""

    resp = client.get('/api/disk')
    data = resp.json()
    assert isinstance(data['total_gi'], (int, float))
    assert isinstance(data['used_gi'], (int, float))


def test_images_returns_node_images(client: Any) -> None:
    """Node image listing endpoint returns images per node."""

    node = SimpleNamespace(
        metadata=SimpleNamespace(name='node-1'),
        status=SimpleNamespace(
            images=[
                SimpleNamespace(
                    names=['harbor.celko.cz/scipion/xmipp:v3'],
                    size_bytes=500 * 1024 * 1024,
                ),
                SimpleNamespace(
                    names=['harbor.celko.cz/scipion/relion:v3'],
                    size_bytes=200 * 1024 * 1024,
                ),
            ]
        ),
    )
    mock_core.list_node.return_value = SimpleNamespace(items=[node])

    resp = client.get('/api/images')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['nodes']) == 1
    n = data['nodes'][0]
    assert n['node'] == 'node-1'
    assert n['count'] == 2
    assert n['total_mb'] > 0
    assert n['images'][0]['size_mb'] >= n['images'][1]['size_mb']


def test_images_empty_images(client: Any) -> None:
    """Empty images list returns zero counts."""

    node = SimpleNamespace(
        metadata=SimpleNamespace(name='node-1'),
        status=SimpleNamespace(images=[]),
    )
    mock_core.list_node.return_value = SimpleNamespace(items=[node])

    resp = client.get('/api/images')
    assert resp.status_code == 200
    data = resp.json()
    assert data['nodes'][0]['count'] == 0
    assert data['nodes'][0]['total_mb'] == 0


def test_images_none_images(client: Any) -> None:
    """None images field returns zero count."""

    node = SimpleNamespace(
        metadata=SimpleNamespace(name='node-1'),
        status=SimpleNamespace(images=None),
    )
    mock_core.list_node.return_value = SimpleNamespace(items=[node])

    resp = client.get('/api/images')
    assert resp.status_code == 200
    data = resp.json()
    assert data['nodes'][0]['count'] == 0


def test_images_api_error(client: Any) -> None:
    """API error returns 500."""

    mock_core.list_node.side_effect = Exception('API down')

    resp = client.get('/api/images')
    assert resp.status_code == 500
    assert 'error' in resp.json()


def test_kill_job_success(client: Any) -> None:
    """Job deletion succeeds."""

    mock_batch.delete_namespaced_job.return_value = None

    resp = client.delete('/api/job/scipion-job-12345')
    assert resp.status_code == 200
    assert resp.json()['deleted'] == 'scipion-job-12345'


def test_kill_job_invalid_name(client: Any) -> None:
    """Invalid job name returns 400."""

    resp = client.delete('/api/job/INVALID_NAME!')
    assert resp.status_code == 400
    assert 'invalid' in resp.json()['error']


def test_kill_job_not_found(client: Any) -> None:
    """Missing job returns 404."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(
        status=404, reason='Not Found'
    )

    resp = client.delete('/api/job/nonexistent-job')
    assert resp.status_code == 404


def test_kill_job_server_error(client: Any) -> None:
    """K8s server error returns 500."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(
        status=500, reason='Internal Server Error'
    )

    resp = client.delete('/api/job/nonexistent-job')
    assert resp.status_code == 500


def test_kill_job_command_injection(client: Any) -> None:
    """Command injection attempt returns 400."""

    resp = client.delete('/api/job/job$(whoami)')
    assert resp.status_code == 400


def test_kill_job_empty_name(client: Any) -> None:
    """Empty job name returns 404 or 405."""

    resp = client.delete('/api/job/')
    assert resp.status_code in (404, 405)


def test_kill_pod_success(client: Any) -> None:
    """Pod deletion succeeds."""

    mock_core.delete_namespaced_pod.return_value = None

    resp = client.delete('/api/pod/test-pod-abc123')
    assert resp.status_code == 200
    assert resp.json()['deleted'] == 'test-pod-abc123'


def test_kill_pod_invalid_name(client: Any) -> None:
    """Invalid pod name returns 400."""

    resp = client.delete('/api/pod/BAD!')
    assert resp.status_code == 400


def test_kill_pod_not_found(client: Any) -> None:
    """Missing pod returns 404."""

    mock_core.delete_namespaced_pod.side_effect = ApiException(
        status=404, reason='Not Found'
    )

    resp = client.delete('/api/pod/nonexistent-pod')
    assert resp.status_code == 404


def test_kill_pod_server_error(client: Any) -> None:
    """K8s server error returns 500."""

    mock_core.delete_namespaced_pod.side_effect = ApiException(
        status=500, reason='Internal Server Error'
    )

    resp = client.delete('/api/pod/nonexistent-pod')
    assert resp.status_code == 500


def test_kill_pod_path_traversal(client: Any) -> None:
    """Path traversal attempt is rejected."""

    resp = client.delete('/api/pod/../etc/passwd')
    assert resp.status_code in (400, 404, 422)


def test_kill_pod_empty_name(client: Any) -> None:
    """Empty pod name returns 404 or 405."""

    resp = client.delete('/api/pod/')
    assert resp.status_code in (404, 405)


def test_cleanup_run_returns_three_phase_result(client: Any) -> None:
    """Endpoint returns {deleted_ttl, deleted_cap, evicted}."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    resp = client.post('/api/cleanup/run')
    assert resp.status_code == 200

    data = resp.json()
    assert 'deleted_ttl' in data
    assert 'deleted_cap' in data
    assert 'evicted' in data


def test_cleanup_run_empty(client: Any) -> None:
    """Empty cleanup returns all zeros."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    resp = client.post('/api/cleanup/run')
    assert resp.status_code == 200

    data = resp.json()
    assert data['deleted_ttl'] == 0
    assert data['deleted_cap'] == 0
    assert data['evicted'] == 0


def test_cleanup_run_api_error(client: Any) -> None:
    """API error during cleanup returns 500."""

    mock_batch.list_namespaced_job.side_effect = Exception('API error')

    resp = client.post('/api/cleanup/run')
    assert resp.status_code == 500


def test_cleanup_run_deletes_old_jobs(client: Any) -> None:
    """An old finished job (>TTL) is deleted in phase 1."""

    old_ts = time.time() - 1000
    job = SimpleNamespace(
        metadata=SimpleNamespace(name='old-job'),
        status=SimpleNamespace(
            succeeded=1,
            failed=0,
            active=0,
            completion_time=SimpleNamespace(timestamp=lambda t=old_ts: t),
            start_time=None,
        ),
    )
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[job])
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    resp = client.post('/api/cleanup/run')
    assert resp.status_code == 200
    assert resp.json()['deleted_ttl'] >= 1


def test_disk_error_returns_500(client: Any) -> None:
    """api_disk returns 500 on OS-level errors."""

    with patch('shutil.disk_usage', side_effect=OSError('read-only fs')):
        resp = client.get('/api/disk')
        assert resp.status_code == 500
        assert 'error' in resp.json()


def test_cleanup_thread_alive_field_present(client: Any) -> None:
    """The thread_alive field is present and boolean."""

    resp = client.get('/api/cleanup')
    assert resp.status_code == 200
    assert isinstance(resp.json()['thread_alive'], bool)


def test_cleanup_thread_alive_true_when_cleanup_daemon_running(client: Any) -> None:
    """The thread_alive field reflects daemon thread state."""

    resp = client.get('/api/cleanup')
    data = resp.json()
    assert data['thread_alive'] is True


def test_cleanup_thread_ref_stored_on_app_state(client: Any) -> None:
    """Thread reference is stored on app.state, not found by enumerate()."""

    thread = getattr(client.app.state, 'cleanup_thread', None)
    assert thread is not None
    assert isinstance(thread, threading.Thread)
    assert thread.is_alive()


def test_k8s_status_forwarding_delete_job_403(client: Any) -> None:
    """ApiException 403 is forwarded from job delete."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(
        status=403, reason='Forbidden'
    )
    resp = client.delete('/api/job/scipion-job-100')
    assert resp.status_code == 403


def test_k8s_status_forwarding_delete_pod_404(client: Any) -> None:
    """ApiException 404 is forwarded from pod delete."""

    mock_core.delete_namespaced_pod.side_effect = ApiException(
        status=404, reason='Not Found'
    )
    resp = client.delete('/api/pod/test-pod')
    assert resp.status_code == 404


def test_k8s_status_forwarding_delete_job_409(client: Any) -> None:
    """ApiException 409 is forwarded from job delete."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(
        status=409, reason='Conflict'
    )
    resp = client.delete('/api/job/scipion-job-100')
    assert resp.status_code == 409
