"""
K8s backend
===========
"""

import contextlib
import time
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from controller.backends.k8s import K8sBackend
from controller.tasks.cleanup import cleanup_finished_jobs, run_cleanup_once
from controller.utilities.config import Settings
from tests.conftest import mock_batch, mock_core


def _make_settings() -> Settings:
    """Create a Settings instance for cleanup tests."""

    return Settings(
        namespace='test-ns',
        jobs_ttl=300,
        jobs_cleanup_interval=60,
        storage_mode='pvc',
        projects_pvc='test-pvc',
        pvc_sub_path='projects',
        toolmap_path='/dev/null',
        onedata_enabled=False,
    )


def _make_backend() -> K8sBackend:
    """Create a K8sBackend instance backed by mocked K8s clients."""

    return K8sBackend(_make_settings())


def _make_finished_job(
    name: str, *, age_s: float = 1000, succeeded: int = 1, failed: int = 0
) -> SimpleNamespace:
    """Helper: create a finished job SimpleNamespace."""

    ts_val = time.time() - age_s

    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(
            succeeded=succeeded,
            failed=failed,
            active=0,
            completion_time=SimpleNamespace(timestamp=lambda t=ts_val: t),
            start_time=None,
        ),
    )


def _make_running_job(name: str) -> SimpleNamespace:
    """Helper: create a running job SimpleNamespace."""

    return SimpleNamespace(
        metadata=SimpleNamespace(name=name),
        status=SimpleNamespace(
            succeeded=0,
            failed=0,
            active=1,
            completion_time=None,
            start_time=SimpleNamespace(timestamp=lambda: time.time() - 60),
        ),
    )


def test_job_finish_ts_returns_completion_time() -> None:
    """Completion timestamp is returned when present."""

    job = _make_finished_job('j1', age_s=100)
    ts = K8sBackend._job_finish_ts(job)

    assert ts > 0


def test_job_finish_ts_falls_back_to_start_time() -> None:
    """Falls back to start_time when completion_time is None."""

    job = SimpleNamespace(
        metadata=SimpleNamespace(name='j2'),
        status=SimpleNamespace(
            succeeded=1,
            failed=0,
            active=0,
            completion_time=None,
            start_time=SimpleNamespace(timestamp=lambda: 12345.0),
        ),
    )

    assert K8sBackend._job_finish_ts(job) == 12345.0


def test_job_finish_ts_returns_zero_when_no_timestamp() -> None:
    """Returns 0.0 when both completion_time and start_time are None."""

    job = SimpleNamespace(
        metadata=SimpleNamespace(name='j3'),
        status=SimpleNamespace(
            succeeded=1,
            failed=0,
            active=0,
            completion_time=None,
            start_time=None,
        ),
    )

    assert K8sBackend._job_finish_ts(job) == 0.0


def test_cleanup_ttl_deletes_old_finished_jobs() -> None:
    """TTL-based deletion via run_cleanup_once."""

    jobs = [
        _make_finished_job('old-done', age_s=1000),
        _make_finished_job('recent-done', age_s=10),
        _make_running_job('active'),
    ]
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=jobs)
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=300, max_finished_jobs=100
    )
    assert result['deleted_ttl'] == 1

    mock_batch.delete_namespaced_job.assert_called_once_with(
        'old-done', 'test-ns', propagation_policy='Background'
    )


def test_cleanup_ttl_skips_jobs_without_timestamp() -> None:
    """Jobs without any timestamp are not deleted by TTL."""

    job = SimpleNamespace(
        metadata=SimpleNamespace(name='no-ts'),
        status=SimpleNamespace(
            succeeded=1,
            failed=0,
            active=0,
            completion_time=None,
            start_time=None,
        ),
    )
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[job])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=300, max_finished_jobs=100
    )

    assert result['deleted_ttl'] == 0


def test_cleanup_ttl_deletes_failed_jobs() -> None:
    """Failed jobs past TTL are also deleted."""

    job = _make_finished_job('failed-old', age_s=1000, succeeded=0, failed=1)
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[job])
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=300, max_finished_jobs=100
    )
    assert result['deleted_ttl'] == 1


def test_cleanup_cap_deletes_oldest_beyond_cap() -> None:
    """With max_finished_jobs=2, the oldest of 4 recent jobs is deleted."""

    jobs = [_make_finished_job(f'job-{i}', age_s=100 * (i + 1)) for i in range(4)]
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=jobs)
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=9999, max_finished_jobs=2
    )

    assert result['deleted_cap'] == 2
    assert result['deleted_ttl'] == 0


def test_cleanup_cap_no_deletion_when_under_cap() -> None:
    """No cap deletion when finished count is below the limit."""

    jobs = [_make_finished_job('job-1', age_s=10)]
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=jobs)
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=9999, max_finished_jobs=3
    )

    assert result['deleted_cap'] == 0


def test_cleanup_cap_zero_deletes_all_finished() -> None:
    """Cap of zero removes every finished job."""

    jobs = [_make_finished_job(f'j-{i}', age_s=10) for i in range(3)]
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=jobs)
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=9999, max_finished_jobs=0
    )

    assert result['deleted_cap'] == 3


def test_delete_evicted_deletes_evicted_pods() -> None:
    """Evicted pods are deleted, other failure reasons are left alone."""

    evicted = SimpleNamespace(
        metadata=SimpleNamespace(name='evicted-pod'),
        status=SimpleNamespace(phase='Failed', reason='Evicted'),
    )
    normal = SimpleNamespace(
        metadata=SimpleNamespace(name='normal-pod'),
        status=SimpleNamespace(phase='Failed', reason='OOMKilled'),
    )
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(
        items=[evicted, normal]
    )
    mock_core.delete_namespaced_pod.return_value = None

    count = K8sBackend._delete_evicted_pods('test-ns')

    assert count == 1
    mock_core.delete_namespaced_pod.assert_called_once_with('evicted-pod', 'test-ns')


def test_delete_evicted_no_evicted_pods() -> None:
    """Returns zero when there are no pods at all."""

    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])
    assert K8sBackend._delete_evicted_pods('test-ns') == 0


def test_delete_evicted_api_error_returns_zero() -> None:
    """API errors are caught and zero is returned."""

    mock_core.list_namespaced_pod.side_effect = Exception('API down')
    assert K8sBackend._delete_evicted_pods('test-ns') == 0


@patch('controller.tasks.cleanup.time.sleep', side_effect=StopIteration)
def test_cleanup_thread_calls_sleep(mock_sleep: Any) -> None:
    """The loop calls time.sleep with the configured interval."""

    backend = _make_backend()
    with contextlib.suppress(StopIteration):
        cleanup_finished_jobs(
            backend=backend,
            namespace='test-ns',
            jobs_ttl=300,
            interval=60,
            max_finished_jobs=3,
        )

    mock_sleep.assert_called_once_with(60)


@patch('controller.tasks.cleanup.time.sleep', side_effect=[None, StopIteration])
def test_cleanup_thread_runs_one_iteration(mock_sleep: Any) -> None:
    """One full iteration deletes expired jobs."""

    old_job = _make_finished_job('expired', age_s=1000)
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[old_job])
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    with contextlib.suppress(StopIteration):
        cleanup_finished_jobs(
            backend=backend,
            namespace='test-ns',
            jobs_ttl=300,
            interval=60,
            max_finished_jobs=3,
        )

    mock_batch.delete_namespaced_job.assert_called()


@patch('controller.tasks.cleanup.time.sleep', side_effect=[None, StopIteration])
def test_cleanup_thread_handles_api_error(mock_sleep: Any) -> None:
    """API errors inside the loop do not crash the thread."""

    mock_batch.list_namespaced_job.side_effect = Exception('API down')

    backend = _make_backend()
    with contextlib.suppress(StopIteration):
        cleanup_finished_jobs(
            backend=backend,
            namespace='test-ns',
            jobs_ttl=300,
            interval=60,
            max_finished_jobs=3,
        )


@patch('controller.tasks.cleanup.time.sleep', side_effect=StopIteration)
def test_cleanup_immediate_called_before_first_sleep(mock_sleep: Any) -> None:
    """run_cleanup_once should be called before time.sleep on first iteration."""

    mock_batch.list_namespaced_job.return_value = SimpleNamespace(items=[])
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    with contextlib.suppress(StopIteration):
        cleanup_finished_jobs(
            backend=backend,
            namespace='test-ns',
            jobs_ttl=300,
            interval=60,
            max_finished_jobs=3,
        )

    # If sleep were first, list_namespaced_job would never be called
    mock_batch.list_namespaced_job.assert_called_once()


def test_cap_sort_no_timestamp_job_preserved_over_old_ones() -> None:
    """A job without timestamp should NOT be deleted before one with a real old ts."""

    # 2 old jobs with timestamps + 1 job without timestamp
    old_job = _make_finished_job('old-with-ts', age_s=50)
    no_ts_job = SimpleNamespace(
        metadata=SimpleNamespace(name='no-ts-job'),
        status=SimpleNamespace(
            succeeded=1,
            failed=0,
            active=0,
            completion_time=None,
            start_time=None,
        ),
    )
    mock_batch.list_namespaced_job.return_value = SimpleNamespace(
        items=[old_job, no_ts_job]
    )
    mock_batch.delete_namespaced_job.return_value = None
    mock_core.list_namespaced_pod.return_value = SimpleNamespace(items=[])

    backend = _make_backend()
    result = run_cleanup_once(
        backend=backend, namespace='test-ns', jobs_ttl=9999, max_finished_jobs=1
    )
    # cap=1, 2 finished jobs -> 1 deleted;
    # old_job (with real ts) should be deleted, not no_ts_job
    assert result['deleted_cap'] == 1
    deleted_name = mock_batch.delete_namespaced_job.call_args[0][0]
    assert deleted_name == 'old-with-ts'


def test_job_finish_ts_none_status_returns_zero() -> None:
    """_job_finish_ts returns 0.0 when job.status is None."""

    job = SimpleNamespace(status=None)
    assert K8sBackend._job_finish_ts(job) == 0.0


def test_job_finish_ts_none_status_normal_still_works() -> None:
    """Normal status with completion_time still returns the correct timestamp."""

    ts = time.time() - 100
    ct = SimpleNamespace(timestamp=lambda: ts)
    job = SimpleNamespace(status=SimpleNamespace(completion_time=ct, start_time=None))

    assert abs(K8sBackend._job_finish_ts(job) - ts) < 1.0
