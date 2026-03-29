"""
Cleanup
=======

Background cleanup thread for expired Kubernetes jobs:
    - Deletes `batch/v1 Job` objects older than jobs_ttl seconds.
    - Enforces a max_finished_jobs cap, so when more finished
      jobs exist, the oldest are deleted regardless of their age.
    - Removes pods stuck in `Evicted` state.
"""

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from controller.backends import InfraBackend

logger: logging.Logger = logging.getLogger(__name__)


def run_cleanup_once(
    *,
    backend: 'InfraBackend',
    namespace: str,
    jobs_ttl: int,
    max_finished_jobs: int,
) -> dict[str, int]:
    """Execute a single cleanup pass via the backend."""

    return backend.cleanup_once(
        namespace=namespace,
        jobs_ttl=jobs_ttl,
        max_finished_jobs=max_finished_jobs,
    )


def cleanup_finished_jobs(
    *,
    backend: 'InfraBackend',
    namespace: str,
    jobs_ttl: int,
    interval: int,
    max_finished_jobs: int = 3,
) -> None:  # pragma: no cover - runs forever in a thread
    """Infinite loop: periodically clean up finished jobs and evicted pods."""

    while True:
        try:
            result = run_cleanup_once(
                backend=backend,
                namespace=namespace,
                jobs_ttl=jobs_ttl,
                max_finished_jobs=max_finished_jobs,
            )
            total: int = sum(result.values())

            if total:
                logger.info(
                    'TTL=%d cap=%d evicted=%d',
                    result['deleted_ttl'],
                    result['deleted_cap'],
                    result['evicted'],
                )
        except Exception as exc:
            logger.error('Cleanup error: %s', exc)

        time.sleep(interval)
