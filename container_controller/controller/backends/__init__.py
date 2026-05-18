"""
Backend registry
================

Infrastructure backend abstraction layer.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from controller.utilities.config import Settings


class BackendError(Exception):
    """Raised when a backend operation fails."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)

        self.status_code = status_code


class InfraBackend(ABC):
    """Abstract base class for infrastructure backends."""

    def __init__(self, settings: 'Settings') -> None:
        self.settings = settings

    @abstractmethod
    def submit_job(
        self,
        *,
        namespace: str,
        job_name: str,
        image: str,
        command: list[str],
        env: dict[str, str],
        labels: dict[str, str],
        mem_mb: int = 4096,
        gpu: bool = False,
        prefer_node: str | None = None,
    ) -> None:
        """Submit a containerized job to the backend infrastructure."""

        ...

    @abstractmethod
    def read_job_phase(self, job_name: str, namespace: str) -> str | None:
        """Return `'RUNNING'`, `'DONE'`, `'FAILED'`, or None if not found."""

        ...

    @abstractmethod
    def delete_job(self, job_name: str, namespace: str) -> None:
        """Delete a job."""

        ...

    @abstractmethod
    def list_pods(self, namespace: str) -> list[dict[str, Any]]:
        """Return pod info dicts for all pods in namespace."""

        ...

    @abstractmethod
    def list_jobs(self, namespace: str) -> list[dict[str, Any]]:
        """Return job info dicts for all jobs in namespace."""

        ...

    @abstractmethod
    def list_events(self, namespace: str) -> list[dict[str, Any]]:
        """Return the most recent events in namespace."""

        ...

    @abstractmethod
    def get_metrics(self, namespace: str) -> dict[str, list[dict[str, Any]]]:
        """Return `{"nodes": [...], "pods": [...]}` resource metrics."""

        ...

    @abstractmethod
    def read_pod_log(self, pod_name: str, namespace: str, *, tail: int = 100) -> str:
        """Return the last tail log lines of pod_name."""

        ...

    @abstractmethod
    def list_node_images(self) -> list[dict[str, Any]]:
        """Return container images cached on cluster nodes."""

        ...

    @abstractmethod
    def delete_pod(self, pod_name: str, namespace: str) -> None:
        """Delete a pod."""

        ...

    @abstractmethod
    def cleanup_once(
        self,
        *,
        namespace: str,
        jobs_ttl: int,
        max_finished_jobs: int,
    ) -> dict[str, int]:
        """Run a single cleanup pass."""

        ...


_BACKENDS: dict[str, type[InfraBackend]] = {}


def register_backend(name: str, cls: type[InfraBackend]) -> None:
    """Register a backend class under name."""

    _BACKENDS[name] = cls


def create_backend(name: str, settings: 'Settings') -> InfraBackend:
    """Instantiate the backend registered under name."""

    import controller.backends.k8s  # type: ignore[reportUnusedImport]  # noqa: PLC0415
    import controller.backends.rancher  # type: ignore[reportUnusedImport]  # noqa: F401, PLC0415

    if name not in _BACKENDS:
        msg = f'Unknown backend: {name!r}. Available: {sorted(_BACKENDS)}'
        raise ValueError(msg)

    return _BACKENDS[name](settings)
