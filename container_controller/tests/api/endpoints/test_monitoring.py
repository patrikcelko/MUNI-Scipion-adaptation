"""
Monitoring endpoints
====================
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import controller.utilities.k8s as k8s_mod
from tests.conftest import (
    make_event,
    make_job,
    make_pod,
    mock_batch,
    mock_core,
    mock_custom,
)


def test_pods_list(client: Any) -> None:
    """List pods returns correct data."""

    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[make_pod()])

    resp = client.get('/api/pods')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['pods']) == 1
    assert data['pods'][0]['name'] == 'test-pod'
    assert data['pods'][0]['phase'] == 'Running'
    assert data['pods'][0]['node'] == 'node-1'


def test_pods_empty(client: Any) -> None:
    """Empty pod list."""

    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
    resp = client.get('/api/pods')
    assert resp.json()['pods'] == []


def test_pods_terminated_container(client: Any) -> None:
    """Pod with a terminated container."""

    pod = make_pod(
        name='done-pod',
        phase='Succeeded',
        running=False,
        terminated_reason='Completed',
    )
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

    resp = client.get('/api/pods')
    data = resp.json()
    assert 'terminated' in data['pods'][0]['containers'][0]['state']


def test_pods_waiting_container(client: Any) -> None:
    """Pod with a waiting container."""

    pod = make_pod(
        name='pending-pod',
        phase='Pending',
        node=None,
        running=False,
    )
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

    resp = client.get('/api/pods')
    data = resp.json()
    assert data['pods'][0]['containers'][0]['state'] == 'waiting'
    assert data['pods'][0]['node'] == '-'


def test_pods_without_resources(client: Any) -> None:
    """Pod without resource requests/limits."""

    pod = make_pod(name='no-res-pod', resources=None)
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

    resp = client.get('/api/pods')
    assert resp.status_code == 200
    assert resp.json()['pods'][0]['resources'] == {}


def test_pods_labels_filtered(client: Any) -> None:
    """Only specific label keys are included."""

    pod = make_pod(
        name='labeled-pod',
        labels={
            'app': 'scipion-worker',
            'tool': 'xmipp',
            'unrelated': 'yes',
        },
    )
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[pod])

    resp = client.get('/api/pods')
    labels = resp.json()['pods'][0]['labels']
    assert 'app' in labels
    assert 'tool' in labels
    assert 'unrelated' not in labels


def test_jobs_list(client: Any) -> None:
    """List jobs returns correct data."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[make_job(active=1)])

    resp = client.get('/api/jobs')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['jobs']) == 1
    assert data['jobs'][0]['name'] == 'scipion-job-100'
    assert data['jobs'][0]['phase'] == 'RUNNING'


def test_jobs_sorted_running_first(client: Any) -> None:
    """Running jobs appear before completed jobs."""

    jobs = [
        make_job(name='job-done', succeeded=1, labels={'tool': 'xmipp'}),
        make_job(name='job-running', active=1, labels={'tool': 'relion'}),
    ]
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=jobs)

    resp = client.get('/api/jobs')
    data = resp.json()
    assert data['jobs'][0]['phase'] == 'RUNNING'
    assert data['jobs'][1]['phase'] == 'DONE'


def test_jobs_empty(client: Any) -> None:
    """Empty job list."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    resp = client.get('/api/jobs')
    assert resp.json()['jobs'] == []


def test_events_list(client: Any) -> None:
    """List events returns correct data."""

    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=[make_event()])

    resp = client.get('/api/events')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['events']) == 1
    assert data['events'][0]['reason'] == 'Scheduled'
    assert data['events'][0]['type'] == 'Normal'


def test_events_capped_at_50(client: Any) -> None:
    """At most 50 events are returned."""

    events = [
        SimpleNamespace(
            type='Normal',
            reason=f'Event{i}',
            involved_object=SimpleNamespace(name=f'pod-{i}'),
            message=f'msg {i}',
            last_timestamp=datetime.now(UTC) - timedelta(seconds=i),
            event_time=None,
            metadata=SimpleNamespace(creation_timestamp=None),
        )
        for i in range(100)
    ]
    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=events)

    resp = client.get('/api/events')
    assert len(resp.json()['events']) == 50


def test_events_empty(client: Any) -> None:
    """Empty event list."""

    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=[])
    resp = client.get('/api/events')
    assert resp.json()['events'] == []


def test_events_with_none_timestamps(client: Any) -> None:
    """Events with all-None timestamps should not crash sorting."""

    event = SimpleNamespace(
        type='Warning',
        reason='FailedScheduling',
        involved_object=SimpleNamespace(name='pod-x'),
        message='no nodes available',
        last_timestamp=None,
        event_time=None,
        metadata=SimpleNamespace(creation_timestamp=None),
    )
    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=[event])

    resp = client.get('/api/events')
    assert resp.status_code == 200
    assert len(resp.json()['events']) == 1


def test_metrics_returns_node_and_pod_data(client: Any) -> None:
    """Metrics endpoint returns both node and pod data."""

    mock_custom.list_cluster_custom_object.return_value = {
        'items': [
            {
                'metadata': {'name': 'node-1'},
                'usage': {'cpu': '1500m', 'memory': '8192Mi'},
            }
        ]
    }
    mock_core.list_node.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(
                metadata=SimpleNamespace(name='node-1'),
                status=SimpleNamespace(capacity={'cpu': '4', 'memory': '16384Mi'}),
            )
        ]
    )
    mock_custom.list_namespaced_custom_object.return_value = {
        'items': [
            {
                'metadata': {'name': 'test-pod'},
                'containers': [{'usage': {'cpu': '250m', 'memory': '512Mi'}}],
            }
        ]
    }

    resp = client.get('/api/metrics')
    assert resp.status_code == 200
    data = resp.json()
    assert data['nodes'][0]['cpu_used_m'] == 1500
    assert data['nodes'][0]['cpu_capacity_m'] == 4000
    assert data['nodes'][0]['cpu_pct'] == 37.5
    assert data['pods'][0]['cpu_m'] == 250


def test_metrics_no_custom_api(client: Any) -> None:
    """When metrics-server is unavailable."""

    old = k8s_mod.custom_api
    k8s_mod.custom_api = None
    try:
        resp = client.get('/api/metrics')
        assert resp.status_code == 200
        data = resp.json()
        assert 'error' in data['nodes'][0]
    finally:
        k8s_mod.custom_api = old


def test_metrics_api_failure(client: Any) -> None:
    """Metrics API throws an exception."""

    mock_custom.list_cluster_custom_object.side_effect = Exception('timeout')
    mock_custom.list_namespaced_custom_object.side_effect = Exception('timeout')

    resp = client.get('/api/metrics')
    assert resp.status_code == 200
    data = resp.json()
    assert 'error' in data['nodes'][0]
    assert 'error' in data['pods'][0]


def test_logs_get(client: Any) -> None:
    """Retrieve pod logs."""

    mock_core.read_namespaced_pod_log.return_value = 'line1\nline2\nline3'

    resp = client.get('/api/logs/test-pod?tail=50')
    assert resp.status_code == 200
    data = resp.json()
    assert data['pod'] == 'test-pod'
    assert len(data['lines']) == 3


def test_logs_invalid_pod_name(client: Any) -> None:
    """Invalid pod name is rejected."""

    resp = client.get('/api/logs/INVALID_NAME')
    assert resp.status_code == 400
    assert 'invalid' in resp.json()['error']


def test_logs_command_injection(client: Any) -> None:
    """Command injection attempt is rejected."""

    resp = client.get('/api/logs/test;rm%20-rf')
    assert resp.status_code == 400


def test_logs_error(client: Any) -> None:
    """Log retrieval error returns 500."""

    mock_core.read_namespaced_pod_log.side_effect = Exception('not found')

    resp = client.get('/api/logs/test-pod')
    assert resp.status_code == 500
    data = resp.json()
    assert 'error' in data
    assert data['lines'] == []


def test_logs_tail_over_500_rejected(client: Any) -> None:
    """Tail values over 500 are rejected."""

    resp = client.get('/api/logs/test-pod?tail=999')
    assert resp.status_code == 422


def test_logs_empty(client: Any) -> None:
    """Empty log output."""

    mock_core.read_namespaced_pod_log.return_value = ''

    resp = client.get('/api/logs/test-pod')
    assert resp.status_code == 200
    assert resp.json()['lines'] == []


def test_logs_default_tail(client: Any) -> None:
    """Default tail parameter is 100."""

    mock_core.read_namespaced_pod_log.return_value = 'log'

    resp = client.get('/api/logs/test-pod')
    assert resp.status_code == 200
    mock_core.read_namespaced_pod_log.assert_called_once()
    # Verify default tail=100
    call_kwargs = mock_core.read_namespaced_pod_log.call_args
    assert call_kwargs.kwargs.get('tail_lines') == 100 or call_kwargs[1].get('tail_lines') == 100


def test_metrics_list_node_uses_list_not_read(client: Any) -> None:
    """api_metrics uses list_node() instead of per-node read_node()."""

    mock_custom.list_cluster_custom_object.return_value = {
        'items': [
            {'metadata': {'name': 'n1'}, 'usage': {'cpu': '100m', 'memory': '256Mi'}},
            {'metadata': {'name': 'n2'}, 'usage': {'cpu': '200m', 'memory': '512Mi'}},
        ]
    }
    mock_core.list_node.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(
                metadata=SimpleNamespace(name='n1'),
                status=SimpleNamespace(capacity={'cpu': '4', 'memory': '8192Mi'}),
            ),
            SimpleNamespace(
                metadata=SimpleNamespace(name='n2'),
                status=SimpleNamespace(capacity={'cpu': '8', 'memory': '16384Mi'}),
            ),
        ]
    )
    mock_custom.list_namespaced_custom_object.return_value = {'items': []}

    resp = client.get('/api/metrics')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['nodes']) == 2
    assert data['nodes'][0]['name'] == 'n1'
    assert data['nodes'][1]['name'] == 'n2'
    # Ensure list_node was called once (not read_node per-node)
    mock_core.list_node.assert_called_once()


def test_jobs_status_none_with_none_status(client: Any) -> None:
    """Jobs endpoint must not crash when j.status is None."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(
        items=[
            SimpleNamespace(
                metadata=SimpleNamespace(
                    name='new-job',
                    creation_timestamp=SimpleNamespace(timestamp=lambda: 1000.0),
                    labels={'tool': 'xmipp'},
                ),
                status=None,
            ),
        ]
    )
    resp = client.get('/api/jobs')
    assert resp.status_code == 200
    data = resp.json()
    assert len(data['jobs']) == 1
    j = data['jobs'][0]
    assert j['active'] == 0
    assert j['succeeded'] == 0
    assert j['failed'] == 0
    assert j['phase'] == 'RUNNING'


def test_logs_tail_zero_rejected(client: Any) -> None:
    """tail=0 must be rejected."""

    resp = client.get('/api/logs/some-pod?tail=0')
    assert resp.status_code == 422


def test_logs_tail_negative_rejected(client: Any) -> None:
    """tail=-1 must be rejected."""

    resp = client.get('/api/logs/some-pod?tail=-1')
    assert resp.status_code == 422
