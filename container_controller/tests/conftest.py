"""
Test fixtures
=============
"""

import time
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

mock_k8s_config: MagicMock = MagicMock()
mock_batch: MagicMock = MagicMock()
mock_core: MagicMock = MagicMock()
mock_custom: MagicMock = MagicMock()

# Patch before any controller module import at the session level.
_env_patch = patch.dict(
    'os.environ',
    {
        'NAMESPACE': 'test-ns',
        'JOBS_TTL': '300',
        'JOBS_CLEANUP_INTERVAL': '60',
        'STORAGE_MODE': 'pvc',
        'PROJECTS_PVC': 'test-pvc',
        'PVC_SUB_PATH': 'projects',
        'TOOLMAP_PATH': '/dev/null',
        'LOCAL_PATH': '/',
        'NODE_SELECTOR_JSON': '{}',
        'TOLERATIONS_JSON': '[]',
        'ONEDATA_ENABLED': 'false',
    },
)
_incluster_patch = patch('kubernetes.config.load_incluster_config', mock_k8s_config)
_kubeconfig_patch = patch('kubernetes.config.load_kube_config', mock_k8s_config)

_env_patch.start()
_incluster_patch.start()
_kubeconfig_patch.start()

import controller.utilities.k8s as k8s_mod  # noqa
from controller import create_app  # noqa
from controller.api.endpoints.jobs import _known_jobs  # noqa
from controller.backends.k8s import K8sBackend  # noqa
from controller.utilities.config import Settings  # noqa
from fastapi import FastAPI  # noqa
from fastapi.testclient import TestClient  # noqa

# Inject mocked clients into the k8s module.
k8s_mod.core = mock_core  # type: ignore
k8s_mod.batch = mock_batch  # type: ignore
k8s_mod.custom_api = mock_custom  # type: ignore


@pytest.fixture(autouse=True)
def _reset_mocks() -> None:
    """Reset all K8s mocks between tests, prevents cross-test leaking."""

    for m in (mock_batch, mock_core, mock_custom):
        m.reset_mock()
        for child in list(m._mock_children.values()):  # type: ignore
            child.side_effect = None
            child.return_value = MagicMock()


@pytest.fixture
def settings() -> Settings:
    """Return the test `Settings` instance."""

    return Settings(
        namespace='test-ns',
        jobs_ttl=300,
        jobs_cleanup_interval=60,
        storage_mode='pvc',
        projects_pvc='test-pvc',
        pvc_sub_path='projects',
        toolmap_path='/dev/null',
        local_path='/',
        onedata_enabled=False,
    )


@pytest.fixture
def backend(settings: Settings) -> K8sBackend:
    """Return a `K8sBackend` backed by mocked K8s clients."""

    return K8sBackend(settings)


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """Create a fresh FastAPI app wired to test settings."""

    return create_app(settings)


@pytest.fixture
def client(app: Any) -> Generator[TestClient]:
    """FastAPI `TestClient` backed by test mocks."""

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def clear_known_jobs() -> Generator[None]:
    """Clear the `_known_jobs` set before and after each test."""

    _known_jobs.clear()

    yield

    _known_jobs.clear()


def make_job(
    name: str = 'scipion-job-100',
    succeeded: int = 0,
    failed: int = 0,
    active: int = 0,
    labels: dict[str, str] | None = None,
    creation_ts: Any = None,
    completion_ts: Any = None,
    start_ts: Any = None,
) -> SimpleNamespace:
    """Create a mock K8s Job object."""

    if creation_ts is None:
        creation_ts = SimpleNamespace(timestamp=lambda: time.time() - 120)

    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels=labels or {'tool': 'xmipp'},
            creation_timestamp=creation_ts,
        ),
        status=SimpleNamespace(
            succeeded=succeeded,
            failed=failed,
            active=active,
            completion_time=completion_ts,
            start_time=start_ts,
        ),
    )


_NO_RESOURCES = object()


def make_pod(
    name: str = 'test-pod',
    phase: str = 'Running',
    node: str | None = 'node-1',
    labels: dict[str, str] | None = None,
    running: bool = True,
    terminated_reason: str | None = None,
    resources: Any = _NO_RESOURCES,
) -> SimpleNamespace:
    """Create a mock K8s Pod object."""

    if running:
        state = SimpleNamespace(running=True, terminated=None)
    elif terminated_reason:
        state = SimpleNamespace(
            running=None,
            terminated=SimpleNamespace(reason=terminated_reason),
        )
    else:
        state = SimpleNamespace(running=None, terminated=None)

    if resources is _NO_RESOURCES:
        resources = SimpleNamespace(
            requests={'cpu': '500m', 'memory': '1Gi'},
            limits={'cpu': '2', 'memory': '4Gi'},
        )

    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            labels=labels or {'app': 'scipion-worker'},
            creation_timestamp=SimpleNamespace(timestamp=lambda: time.time() - 60),
        ),
        status=SimpleNamespace(
            phase=phase,
            container_statuses=[
                SimpleNamespace(
                    name='tool',
                    image='xmipp:v1',
                    ready=running,
                    restart_count=0,
                    state=state,
                )
            ],
        ),
        spec=SimpleNamespace(
            node_name=node,
            containers=[SimpleNamespace(name='tool', resources=resources)],
        ),
    )


def make_event(
    reason: str = 'Scheduled',
    etype: str = 'Normal',
    obj_name: str = 'test-pod',
    message: str = 'Successfully scheduled',
    seconds_ago: int = 10,
) -> SimpleNamespace:
    """Create a mock K8s Event object."""

    return SimpleNamespace(
        type=etype,
        reason=reason,
        involved_object=SimpleNamespace(name=obj_name),
        message=message,
        last_timestamp=SimpleNamespace(timestamp=lambda: time.time() - seconds_ago),
        event_time=None,
        metadata=SimpleNamespace(creation_timestamp=None),
    )
