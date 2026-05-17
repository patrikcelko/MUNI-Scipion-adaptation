"""
Rancher backend
=============
"""

from types import SimpleNamespace
from typing import Any

import pytest
from kubernetes.client.exceptions import ApiException

from controller.backends import _BACKENDS, BackendError, create_backend
from controller.backends.rancher import (
    _RANCHER_DEFAULT_CPU_LIMIT,
    _RANCHER_DEFAULT_CPU_REQUEST,
    _RANCHER_DEFAULT_MEM_REQUEST_MB,
    _RANCHER_GPU_RESOURCE,
    RancherBackend,
)
from controller.utilities.config import Settings
from tests.conftest import mock_batch, mock_core


def _make_settings(**overrides: Any) -> Settings:
    """Build a `Settings` instance with Rancher defaults."""

    defaults: dict[str, Any] = {
        'namespace': 'rancher-ns',
        'jobs_ttl': 600,
        'jobs_cleanup_interval': 120,
        'storage_mode': 'pvc',
        'projects_pvc': 'rancher-pvc',
        'pvc_sub_path': 'projects',
        'toolmap_path': '/dev/null',
        'onedata_enabled': False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _make_backend(**overrides: Any) -> RancherBackend:
    """Create a `RancherBackend` wired to fake K8s clients."""

    return RancherBackend(_make_settings(**overrides))


def test_rancher_submit_resources_cpu_requests_and_limits() -> None:
    """CPU requests and limits are always set."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='test-job',
        image='cerit.io/scipion/xmipp:v3',
        command=['/bin/bash', '-c', 'echo hello'],
        env={'FOO': 'bar'},
        labels={'app': 'scipion-worker', 'tool': 'xmipp'},
        mem_mb=8192,
    )

    call_args = mock_batch.create_namespaced_job.call_args
    job_obj = call_args[0][1]
    container = job_obj.spec.template.spec.containers[0]
    resources = container.resources

    assert resources.requests['cpu'] == _RANCHER_DEFAULT_CPU_REQUEST
    assert resources.limits['cpu'] == _RANCHER_DEFAULT_CPU_LIMIT


def test_rancher_submit_resources_memory_requests_and_limits() -> None:
    """Memory limit = requested mem_mb; request = max(mem_mb // 2, default)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
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
    expected_req = max(16384 // 2, _RANCHER_DEFAULT_MEM_REQUEST_MB)
    assert resources.requests['memory'] == f'{expected_req}Mi'


def test_rancher_submit_resources_small_memory_clamped_to_limit() -> None:
    """When mem_mb < default request, request is clamped to mem_mb (not exceeding limit)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='small-mem',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        mem_mb=1024,
    )

    container = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]

    assert container.resources.requests['memory'] == '1024Mi'
    assert container.resources.limits['memory'] == '1024Mi'


def test_rancher_submit_resources_request_never_exceeds_limit() -> None:
    """Memory requests must always be <= memory limits (K8s requirement)."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    for mem in (512, 1024, 2048, 4096, 8192, 16384):
        mock_batch.create_namespaced_job.reset_mock()
        backend.submit_job(
            namespace='rancher-ns',
            job_name=f'mem-{mem}',
            image='img:v1',
            command=['echo'],
            env={},
            labels={'app': 'scipion-worker'},
            mem_mb=mem,
        )
        c = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]
        req = int(c.resources.requests['memory'].replace('Mi', ''))
        lim = int(c.resources.limits['memory'].replace('Mi', ''))

        assert req <= lim, f'mem_mb={mem}: request={req}Mi > limit={lim}Mi'


def test_rancher_submit_resources_gpu_sets_nvidia_resource() -> None:
    """GPU flag adds nvidia.com/gpu resource requests and limits."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='gpu-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        gpu=True,
    )

    container = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]
    assert container.resources.limits[_RANCHER_GPU_RESOURCE] == '1'
    assert container.resources.requests[_RANCHER_GPU_RESOURCE] == '1'


def test_rancher_submit_resources_no_gpu_has_no_nvidia_resource() -> None:
    """Without GPU flag, no nvidia resource is set."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='no-gpu',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
        gpu=False,
    )

    container = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]
    assert _RANCHER_GPU_RESOURCE not in container.resources.limits
    assert _RANCHER_GPU_RESOURCE not in container.resources.requests


def test_rancher_submit_structure_correct_metadata() -> None:
    """Job metadata matches the supplied name, namespace and labels."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='struct-job',
        image='img:v1',
        command=['/bin/bash', '-c', 'echo hi'],
        env={'A': '1'},
        labels={'app': 'scipion-worker', 'tool': 'relion'},
    )

    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.metadata.name == 'struct-job'
    assert job.metadata.namespace == 'rancher-ns'
    assert job.metadata.labels == {'app': 'scipion-worker', 'tool': 'relion'}


def test_rancher_submit_structure_spec_properties() -> None:
    """Job spec has correct backoff, TTL and restart policy."""

    backend = _make_backend()
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
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


def test_rancher_submit_structure_pvc_volume_mounted() -> None:
    """PVC volume is mounted with correct claim name and projects sub-path."""

    backend = _make_backend(storage_mode='pvc', projects_pvc='my-pvc', pvc_sub_path='data')
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='pvc-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    spec = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec

    # One PVC volume (no onedata_enabled)
    assert len(spec.volumes) == 1
    assert spec.volumes[0].persistent_volume_claim.claim_name == 'my-pvc'

    # /projects mount uses the configured pvc_sub_path
    project_mount = next(m for m in spec.containers[0].volume_mounts if m.mount_path == '/projects')

    assert project_mount.sub_path == 'data'


def test_rancher_submit_structure_data_mount_present() -> None:
    """/data is mounted from the same PVC with sub_path 'data'."""

    backend = _make_backend(storage_mode='pvc', projects_pvc='my-pvc', pvc_sub_path='projects')
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='data-mount-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    spec = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec
    mounts = spec.containers[0].volume_mounts
    mount_paths = [m.mount_path for m in mounts]
    assert '/data' in mount_paths, 'Worker pod must have /data mount for raw input data'

    data_mount = next(m for m in mounts if m.mount_path == '/data')
    assert data_mount.sub_path == 'data'
    assert data_mount.name == 'projects-vol'


def test_rancher_submit_onedata_datasets_vol_present() -> None:
    """When onedata_enabled, datasets-vol emptyDir and /datasets mount are present."""

    backend = _make_backend(
        storage_mode='pvc',
        projects_pvc='my-pvc',
        pvc_sub_path='projects',
        onedata_enabled=True,
        oneclient_image='onedata/oneclient:latest',
        oneclient_provider='provider.example.com',
        oneclient_space='myspace',
        oneclient_token_secret='od-token',
        oneclient_extra=[],
    )
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='onedata-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    spec = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec
    vol_names = [v.name for v in spec.volumes]
    assert 'datasets-vol' in vol_names, 'datasets-vol emptyDir must be present when onedata_enabled'

    datasets_vol = next(v for v in spec.volumes if v.name == 'datasets-vol')
    assert datasets_vol.empty_dir is not None

    main_mounts = spec.containers[0].volume_mounts
    datasets_mount = next((m for m in main_mounts if m.mount_path == '/datasets'), None)
    assert datasets_mount is not None, 'Main container must have /datasets mount'


def test_rancher_submit_onedata_sidecar_mounts_datasets_not_projects() -> None:
    """Onedata sidecar container mounts /datasets (not /projects) with Bidirectional propagation."""

    backend = _make_backend(
        storage_mode='pvc',
        projects_pvc='my-pvc',
        pvc_sub_path='projects',
        onedata_enabled=True,
        oneclient_image='onedata/oneclient:latest',
        oneclient_provider='provider.example.com',
        oneclient_space='myspace',
        oneclient_token_secret='od-token',
        oneclient_extra=[],
    )
    mock_batch.create_namespaced_job.return_value = None

    backend.submit_job(
        namespace='rancher-ns',
        job_name='sidecar-job',
        image='img:v1',
        command=['echo'],
        env={},
        labels={'app': 'scipion-worker'},
    )

    spec = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec
    sidecar = next((c for c in spec.containers if c.name == 'oneclient'), None)
    assert sidecar is not None, 'oneclient sidecar must be present'

    sidecar_mount_paths = [m.mount_path for m in (sidecar.volume_mounts or [])]
    assert '/datasets' in sidecar_mount_paths, 'Sidecar must mount /datasets'
    assert '/projects' not in sidecar_mount_paths, 'Sidecar must NOT mount /projects (FUSE/PVC conflict)'

    datasets_sidecar_mount = next(m for m in sidecar.volume_mounts if m.mount_path == '/datasets')
    assert datasets_sidecar_mount.mount_propagation == 'Bidirectional'


def test_rancher_lifecycle_read_phase_running() -> None:
    """Active job is reported as RUNNING."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.return_value = SimpleNamespace(status=SimpleNamespace(active=1, succeeded=0, failed=0))

    assert backend.read_job_phase('j1', 'rancher-ns') == 'RUNNING'


def test_rancher_lifecycle_read_phase_done() -> None:
    """Succeeded job is reported as DONE."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.return_value = SimpleNamespace(status=SimpleNamespace(active=0, succeeded=1, failed=0))

    assert backend.read_job_phase('j1', 'rancher-ns') == 'DONE'


def test_rancher_lifecycle_read_phase_not_found() -> None:
    """404 ApiException returns None (job does not exist)."""

    backend = _make_backend()
    mock_batch.read_namespaced_job.side_effect = ApiException(status=404, reason='Not Found')
    assert backend.read_job_phase('j1', 'rancher-ns') is None


def test_rancher_lifecycle_delete_job_success() -> None:
    """Successful deletion does not raise."""

    backend = _make_backend()
    mock_batch.delete_namespaced_job.return_value = None
    backend.delete_job('j1', 'rancher-ns')


def test_rancher_lifecycle_delete_job_api_error() -> None:
    """ApiException is wrapped in BackendError with matching status code."""

    backend = _make_backend()
    mock_batch.delete_namespaced_job.side_effect = ApiException(status=404, reason='Not Found')

    with pytest.raises(BackendError) as exc_info:
        backend.delete_job('j1', 'rancher-ns')
    assert exc_info.value.status_code == 404


def test_rancher_monitoring_list_pods_returns_empty() -> None:
    """Empty pod list from API yields empty result."""

    backend = _make_backend()
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    assert backend.list_pods('rancher-ns') == []


def test_rancher_monitoring_list_jobs_returns_empty() -> None:
    """Empty job list from API yields empty result."""

    backend = _make_backend()
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])

    assert backend.list_jobs('rancher-ns') == []


def test_rancher_monitoring_list_events_returns_empty() -> None:
    """Empty event list from API yields empty result."""

    backend = _make_backend()
    mock_core.list_namespaced_event.return_value = SimpleNamespace(items=[])

    assert backend.list_events('rancher-ns') == []


def test_rancher_monitoring_read_pod_log() -> None:
    """Pod log content is returned."""

    backend = _make_backend()
    mock_core.read_namespaced_pod_log.return_value = 'line1\nline2'
    result = backend.read_pod_log('pod-1', 'rancher-ns', tail=50)

    assert 'line1' in result


def test_rancher_admin_list_node_images() -> None:
    """Node images are collected with correct structure."""

    node = SimpleNamespace(
        metadata=SimpleNamespace(name='kub-a10'),
        status=SimpleNamespace(
            images=[
                SimpleNamespace(
                    names=['cerit.io/scipion/xmipp:v3'],
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


def test_rancher_admin_delete_pod_success() -> None:
    """Successful pod deletion does not raise."""

    backend = _make_backend()
    mock_core.delete_namespaced_pod.return_value = None
    backend.delete_pod('pod-1', 'rancher-ns')


def test_rancher_admin_delete_pod_not_found() -> None:
    """ApiException on pod deletion is wrapped in BackendError."""

    backend = _make_backend()
    mock_core.delete_namespaced_pod.side_effect = ApiException(status=404, reason='Not Found')

    with pytest.raises(BackendError) as exc_info:
        backend.delete_pod('pod-1', 'rancher-ns')
    assert exc_info.value.status_code == 404


def test_rancher_cleanup_empty() -> None:
    """Empty namespace yields zero deletions."""

    backend = _make_backend()
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    result = backend.cleanup_once(namespace='rancher-ns', jobs_ttl=300, max_finished_jobs=3)
    assert result == {'deleted_ttl': 0, 'deleted_cap': 0, 'evicted': 0}


def test_rancher_registration_registered() -> None:
    """RancherBackend is registered under 'rancher'."""

    assert 'rancher' in _BACKENDS


def test_rancher_registration_create_backend() -> None:
    """create_backend('rancher', ...) returns a RancherBackend instance."""

    backend = create_backend('rancher', _make_settings())
    assert isinstance(backend, RancherBackend)
