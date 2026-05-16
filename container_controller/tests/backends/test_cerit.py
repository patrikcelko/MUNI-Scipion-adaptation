"""
CERIT backend
=============
"""

from types import SimpleNamespace
from typing import Any

import pytest
from kubernetes.client.exceptions import ApiException

from controller.backends import _BACKENDS, BackendError, create_backend
from controller.backends.cerit import (
    _CERIT_DEFAULT_CPU_LIMIT,
    _CERIT_DEFAULT_CPU_REQUEST,
    _CERIT_DEFAULT_MEM_REQUEST_MB,
    _CERIT_GPU_RESOURCE,
    CeritBackend,
)
from controller.utilities.config import Settings
from tests.conftest import mock_batch, mock_core


def _make_settings(**overrides: Any) -> Settings:
    """Build a `Settings` instance with CERIT-SC defaults."""

    defaults: dict[str, Any] = {
        'namespace': 'cerit-ns',
        'jobs_ttl': 600,
        'jobs_cleanup_interval': 120,
        'storage_mode': 'pvc',
        'projects_pvc': 'cerit-pvc',
        'pvc_sub_path': 'projects',
        'toolmap_path': '/dev/null',
        'onedata_enabled': False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_backend(**overrides: Any) -> CeritBackend:
    """Create a `CeritBackend` wired to fake K8s clients."""

    return CeritBackend(_make_settings(**overrides))


def test_cerit_submit_resources_cpu_requests_and_limits() -> None:
    """CPU requests and limits are always set."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='test-job',
        image='harbor.celko.cz/scipion/xmipp:v3',
        command=['/bin/bash', '-c', 'echo hello'],
        env={'FOO': 'bar'},
        labels={'app': 'scipion-worker', 'tool': 'xmipp'},
        mem_mb=8192,
    )

    call_args = mock_batch.create_namespaced_job.call_args
    job_obj = call_args[0][1]
    container = job_obj.spec.template.spec.containers[0]
    resources = container.resources

    assert resources.requests['cpu'] == _CERIT_DEFAULT_CPU_REQUEST
    assert resources.limits['cpu'] == _CERIT_DEFAULT_CPU_LIMIT


def test_cerit_submit_resources_memory_requests_and_limits() -> None:
    """Memory limit = requested mem_mb; request = max(mem_mb // 2, default)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='mem-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        mem_mb=16384,
    )

    call_args = mock_batch.create_namespaced_job.call_args
    container = call_args[0][1].spec.template.spec.containers[0]
    resources = container.resources

    assert resources.limits['memory'] == '16384Mi'
    expected_req = max(16384 // 2, _CERIT_DEFAULT_MEM_REQUEST_MB)
    assert resources.requests['memory'] == f'{expected_req}Mi'


def test_cerit_submit_resources_small_memory_clamped_to_limit() -> None:
    """When mem_mb < default request, request is clamped to mem_mb (not exceeding limit)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='small-mem',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        mem_mb=1024,
    )

    container = mock_batch.create_namespaced_job.call_args[0][
        1
    ].spec.template.spec.containers[0]

    assert container.resources.requests['memory'] == '1024Mi'
    assert container.resources.limits['memory'] == '1024Mi'


def test_cerit_submit_resources_request_never_exceeds_limit() -> None:
    """Memory requests must always be <= memory limits (K8s requirement)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    for mem in (512, 1024, 2048, 4096, 8192, 16384):
        mock_batch.create_namespaced_job.reset_mock()
        backend.submit_job(
            namespace='cerit-ns',
            job_name=f'mem-{mem}',
            image='img:v1',
            command=['echo'],
            env={},
            labels={'app': 'scipion-worker'},
            mem_mb=mem,
        )
        c = mock_batch.create_namespaced_job.call_args[0][
            1
        ].spec.template.spec.containers[0]
        req = int(c.resources.requests['memory'].replace('Mi', ''))
        lim = int(c.resources.limits['memory'].replace('Mi', ''))

        assert req <= lim, f'mem_mb={mem}: request={req}Mi > limit={lim}Mi'


def test_cerit_submit_resources_gpu_sets_nvidia_resource() -> None:
    """GPU flag adds nvidia.com/gpu resource requests and limits."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='gpu-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        gpu=True,
    )

    container = mock_batch.create_namespaced_job.call_args[0][
        1
    ].spec.template.spec.containers[0]
    assert container.resources.limits[_CERIT_GPU_RESOURCE] == '1'
    assert container.resources.requests[_CERIT_GPU_RESOURCE] == '1'


def test_cerit_submit_resources_no_gpu_has_no_nvidia_resource() -> None:
    """Without GPU flag, no nvidia resource is set."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='no-gpu',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        gpu=False,
    )

    container = mock_batch.create_namespaced_job.call_args[0][
        1
    ].spec.template.spec.containers[0]
    assert _CERIT_GPU_RESOURCE not in container.resources.limits
    assert _CERIT_GPU_RESOURCE not in container.resources.requests


def test_cerit_submit_structure_correct_metadata() -> None:
    """Job metadata matches the supplied name, namespace and labels."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='struct-job',
        image='img:v1',
        command=['/bin/bash', '-c', 'echo hi'],
        env={'A': '1'},
        labels={'app': 'scipion-worker', 'tool': 'relion'},
    )

    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.metadata.name == 'struct-job'
    assert job.metadata.namespace == 'cerit-ns'
    assert job.metadata.labels == {'app': 'scipion-worker', 'tool': 'relion'}


def test_cerit_submit_structure_spec_properties() -> None:
    """Job spec has correct backoff, TTL and restart policy."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='spec-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.spec.backoff_limit == 0
    assert job.spec.ttl_seconds_after_finished == 600
    assert job.spec.template.spec.restart_policy == 'Never'


def test_cerit_submit_structure_pvc_volume_mounted() -> None:
    """PVC volume is mounted with correct claim name and sub-path."""

    backend = _make_backend(
        storage_mode='pvc', projects_pvc='my-pvc', pvc_sub_path='data'
    )
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='cerit-ns',
        job_name='pvc-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    spec = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec
    assert len(spec.volumes) == 1
    assert spec.volumes[0].persistent_volume_claim.claim_name == 'my-pvc'
    assert spec.containers[0].volume_mounts[0].sub_path == 'data'


def test_cerit_lifecycle_read_phase_running() -> None:
    """Active job is reported as RUNNING."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.return_value = SimpleNamespace(
        status=SimpleNamespace(active=1, succeeded=0, failed=0)
    )

    assert backend.read_job_phase('j1', 'cerit-ns') == 'RUNNING'


def test_cerit_lifecycle_read_phase_done() -> None:
    """Succeeded job is reported as DONE."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.return_value = SimpleNamespace(
        status=SimpleNamespace(active=0, succeeded=1, failed=0)
    )

    assert backend.read_job_phase('j1', 'cerit-ns') == 'DONE'


def test_cerit_lifecycle_read_phase_not_found() -> None:
    """API error returns None."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.side_effect = Exception('not found')
    assert backend.read_job_phase('j1', 'cerit-ns') is None


def test_cerit_lifecycle_delete_job_success() -> None:
    """Successful deletion does not raise."""

    backend = _make_backend()
    mock_batch.delete_namespaced_job.return_value = None
    backend.delete_job('j1', 'cerit-ns')


def test_cerit_lifecycle_delete_job_api_error() -> None:
    """ApiException is wrapped in BackendError with matching status code."""

    backend = _make_backend()
    mock_batch.delete_namespaced_job.side_effect = ApiException(
        status=404, reason='Not Found'
    )

    with pytest.raises(BackendError) as exc_info:
        backend.delete_job('j1', 'cerit-ns')
    assert exc_info.value.status_code == 404


def test_cerit_monitoring_list_pods_returns_empty() -> None:
    """Empty pod list from API yields empty result."""

    backend = _make_backend()
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    assert backend.list_pods('cerit-ns') == []


def test_cerit_monitoring_list_jobs_returns_empty() -> None:
    """Empty job list from API yields empty result."""

    backend = _make_backend()
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])

    assert backend.list_jobs('cerit-ns') == []


def test_cerit_monitoring_list_events_returns_empty() -> None:
    """Empty event list from API yields empty result."""

    backend = _make_backend()
    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=[])

    assert backend.list_events('cerit-ns') == []


def test_cerit_monitoring_read_pod_log() -> None:
    """Pod log content is returned."""

    backend = _make_backend()
    mock_core.read_namespaced_pod_log.return_value = 'line1\nline2'
    result = backend.read_pod_log('pod-1', 'cerit-ns', tail=50)

    assert 'line1' in result


def test_cerit_admin_list_node_images() -> None:
    """Node images are collected with correct structure."""

    node = SimpleNamespace(
        metadata=SimpleNamespace(name='kub-a10'),
        status=SimpleNamespace(
            images=[
                SimpleNamespace(
                    names=['harbor.celko.cz/scipion/xmipp:v3'],
                    size_bytes=1024 * 1024 * 500,
                )
            ]
        ),
    )
    mock_core.list_node.return_value = SimpleNamespace(items=[node])

    backend = _make_backend()
    result = backend.list_node_images()

    assert len(result) == 1
    assert result[0]['node'] == 'kub-a10'
    assert result[0]['count'] == 1


def test_cerit_admin_delete_pod_success() -> None:
    """Successful pod deletion does not raise."""

    backend = _make_backend()
    mock_core.delete_namespaced_pod.return_value = None
    backend.delete_pod('pod-1', 'cerit-ns')


def test_cerit_admin_delete_pod_not_found() -> None:
    """ApiException on pod deletion is wrapped in BackendError."""

    backend = _make_backend()
    mock_core.delete_namespaced_pod.side_effect = ApiException(
        status=404, reason='Not Found'
    )

    with pytest.raises(BackendError) as exc_info:
        backend.delete_pod('pod-1', 'cerit-ns')
    assert exc_info.value.status_code == 404


def test_cerit_cleanup_empty() -> None:
    """Empty namespace yields zero deletions."""

    backend = _make_backend()
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    result = backend.cleanup_once(
        namespace='cerit-ns', jobs_ttl=300, max_finished_jobs=3
    )
    assert result == {'deleted_ttl': 0, 'deleted_cap': 0, 'evicted': 0}


def test_cerit_registration_registered() -> None:
    """CeritBackend is registered under 'cerit'."""

    assert 'cerit' in _BACKENDS


def test_cerit_registration_create_backend() -> None:
    """create_backend('cerit', ...) returns a CeritBackend instance."""

    backend = create_backend('cerit', _make_settings())
    assert isinstance(backend, CeritBackend)
