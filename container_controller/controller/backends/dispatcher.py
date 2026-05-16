"""
Dispatcher backend
==================

The Dispatcher exposes an ROCrate-based API::
    - POST /requests/metadata_rocrate/ - submit workflow metadata
    - POST /anon_requests/metadata_rocrate/ - submit without auth
    - GET /requests/{task_id} - poll async task status
    - GET /anon_requests/{task_id} - poll without auth

This backend translates the controllers abstract job operations into
Dispatcher API calls, enabling the controller to route Scipion jobs
through the EOSC Dispatcher instead of directly creating K8s objects.

Configuration:
    DISPATCHER_URL - base URL of the Dispatcher service
    DISPATCHER_TOKEN - optional bearer token for authenticated requests
    DISPATCHER_TIMEOUT - HTTP timeout in seconds (default: 30)
"""

import contextlib
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any

from controller.backends import BackendError, InfraBackend, register_backend
from controller.utilities.config import Settings

logger: logging.Logger = logging.getLogger(__name__)


class DispatcherBackend(InfraBackend):
    """Backend that delegates to a remote EOSC Dispatcher service."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)

        self._base_url: str = settings.dispatcher_url.rstrip('/')
        self._token: str = settings.dispatcher_token
        self._timeout: int = settings.dispatcher_timeout

        # task mapping: job_name -> task_id
        self._tasks: dict[str, str] = {}

        # submission timestamps for TTL-based cleanup
        self._task_submit_time: dict[str, float] = {}

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Send an HTTP request to the Dispatcher and return parsed JSON."""

        url: str = f'{self._base_url}{path}'
        data: bytes | None = json.dumps(body).encode('utf-8') if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header('Content-Type', 'application/json')
        req.add_header('User-Agent', 'Scipion-Controller/1.0')

        if self._token:
            req.add_header('Authorization', f'Bearer {self._token}')

        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw: bytes = resp.read()

            return json.loads(raw.decode('utf-8'))
        except (json.JSONDecodeError, ValueError) as exc:
            msg = f'Dispatcher returned invalid JSON: {exc}'
            raise BackendError(
                msg,
                status_code=502,
            ) from exc
        except urllib.error.HTTPError as exc:
            error_body: str = ''

            with contextlib.suppress(Exception):
                error_body = exc.read().decode('utf-8', errors='replace')[:500]

            msg = f'Dispatcher HTTP {exc.code}: {error_body}'
            raise BackendError(
                msg,
                status_code=exc.code,
            ) from exc
        except urllib.error.URLError as exc:
            msg = f'Dispatcher unreachable: {exc.reason}'
            raise BackendError(msg, status_code=502) from exc

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
        """Submit a job to the Dispatcher as an ROCrate metadata request.

        The Dispatcher determines the appropriate VRE from the workflow
        metadata and enqueues the task asynchronously via Celery.
        """

        # Build a valid ro-crate-metadata.json payload.
        rocrate_metadata: dict[str, Any] = {
            '@context': [
                'https://w3id.org/ro/crate/1.1/context',
                {'runsOn': 'https://w3id.org/ro/terms/test#runsOn'},
            ],
            '@graph': [
                {
                    '@id': './',
                    '@type': 'Dataset',
                    'name': job_name,
                    'mainEntity': {'@id': '#workflow'},
                    'runsOn': {'@id': '#destination'},
                    'hasPart': [
                        {'@id': '#workflow'},
                        {'@id': '#destination'},
                    ],
                },
                {
                    '@id': 'ro-crate-metadata.json',
                    '@type': 'CreativeWork',
                    'about': {'@id': './'},
                    'conformsTo': {
                        '@id': 'https://w3id.org/ro/crate/1.1',
                    },
                },
                {
                    '@id': '#workflow',
                    '@type': [
                        'File',
                        'SoftwareSourceCode',
                        'ComputationalWorkflow',
                    ],
                    'name': job_name,
                    'programmingLanguage': {'@id': '#scipion'},
                    'url': env.get('WORKFLOW_URL', ''),
                },
                {
                    '@id': '#scipion',
                    '@type': 'ComputerLanguage',
                    'name': 'Scipion',
                    'identifier': 'http://scipion.i2pc.es/',
                    'url': {
                        '@id': 'http://scipion.i2pc.es/',
                    },
                },
                {
                    '@id': '#destination',
                    '@type': 'Service',
                    'name': 'Scipion K8s Controller',
                    'url': env.get('CONTROLLER_URL', self._base_url),
                },
            ],
        }

        # Determine endpoint, use authenticated or anonymous based on token.
        endpoint: str = '/requests/metadata_rocrate/' if self._token else '/anon_requests/metadata_rocrate/'

        result: dict[str, Any] = self._request('POST', endpoint, body=rocrate_metadata)

        task_id: str = result.get('task_id', '')
        if not task_id:
            msg = 'Dispatcher did not return a task_id'
            raise BackendError(msg, status_code=502)

        # Store the mapping so status() can look it up.
        self._tasks[job_name] = task_id
        self._task_submit_time[job_name] = time.time()
        logger.info('Submitted job %s to Dispatcher -> task %s', job_name, task_id)

    def read_job_phase(self, job_name: str, namespace: str) -> str | None:
        """Poll the Dispatcher for task status.

        Maps Celery states to the controller's phase model:
            - `PENDING` / `PROGRESS` -> `RUNNING`
            - `SUCCESS` -> `DONE`
            - `FAILURE` / `REVOKED` -> `FAILED`
        """

        task_id: str | None = self._tasks.get(job_name)
        if not task_id:
            return None

        endpoint: str = f'/requests/{task_id}' if self._token else f'/anon_requests/{task_id}'

        try:
            result: dict[str, Any] = self._request('GET', endpoint)
        except BackendError:
            return None

        status: str = result.get('status', '').upper()

        if status in ('PENDING', 'PROGRESS', 'STARTED'):
            return 'RUNNING'

        if status == 'SUCCESS':
            return 'DONE'

        if status in ('FAILURE', 'REVOKED'):
            return 'FAILED'

        return 'RUNNING'

    def delete_job(self, job_name: str, namespace: str) -> None:
        """Remove the task from local tracking. The Dispatcher does not support remote task cancellation, so this
        is a best-effort cleanup that allows the controller to forget about the job. The actual task will still
        run to completion on the Dispatcher side.
        """

        task_id: str | None = self._tasks.pop(job_name, None)
        self._task_submit_time.pop(job_name, None)
        if task_id:
            logger.warning(
                'Removed Dispatcher task %s for job %s from local tracking. ',
                task_id, job_name,
            )

    def list_pods(self, namespace: str) -> list[dict[str, Any]]:
        """Dispatcher backend has no pod-level visibility."""

        return []

    def list_jobs(self, namespace: str) -> list[dict[str, Any]]:
        """Return tracked Dispatcher tasks as pseudo-job entries."""

        result: list[dict[str, Any]] = []
        for job_name in self._tasks:
            phase: str | None = self.read_job_phase(job_name, namespace)
            result.append(
                {
                    'name': job_name,
                    'phase': phase or 'UNKNOWN',
                    'age': '-',
                    'tool': 'dispatcher',
                    'active': 1 if phase == 'RUNNING' else 0,
                    'succeeded': 1 if phase == 'DONE' else 0,
                    'failed': 1 if phase == 'FAILED' else 0,
                }
            )

        return result

    def list_events(self, namespace: str) -> list[dict[str, Any]]:
        """Dispatcher backend has no event-level visibility."""

        return []

    def get_metrics(self, namespace: str) -> dict[str, list[dict[str, Any]]]:
        """Dispatcher backend cannot collect K8s metrics."""

        return {
            'nodes': [{'error': 'metrics not available via Dispatcher backend'}],
            'pods': [{'error': 'metrics not available via Dispatcher backend'}],
        }

    def read_pod_log(self, pod_name: str, namespace: str, *, tail: int = 100) -> str:
        """Dispatcher backend has no pod log access."""

        return ''

    def list_node_images(self) -> list[dict[str, Any]]:
        """Dispatcher backend has no node image visibility."""

        return []

    def delete_pod(self, pod_name: str, namespace: str) -> None:
        """Dispatcher backend cannot delete individual pods."""

        msg = 'Pod deletion not supported via Dispatcher backend'
        raise BackendError(
            msg,
            status_code=501,
        )

    def cleanup_once(
        self,
        *,
        namespace: str,
        jobs_ttl: int,
        max_finished_jobs: int,
    ) -> dict[str, int]:
        """Remove completed tasks from local tracking. Applies two removal strategies:
            - TTL-based: any DONE/FAILED task whose submission time is older
              than jobs_ttl seconds is removed.
            - Cap-based: if the remaining finished tasks exceed
              max_finished_jobs, the oldest surplus entries are removed.
        """

        now: float = time.time()
        deleted_ttl: int = 0
        remaining_finished: list[str] = []

        for job_name in list(self._tasks):
            phase: str | None = self.read_job_phase(job_name, namespace)
            if phase not in ('DONE', 'FAILED'):
                continue

            submit_ts: float = self._task_submit_time.get(job_name, 0.0)
            if jobs_ttl > 0 and (now - submit_ts) > jobs_ttl:
                self._tasks.pop(job_name, None)
                self._task_submit_time.pop(job_name, None)
                deleted_ttl += 1
            else:
                remaining_finished.append(job_name)

        # Cap-based removal of the oldest surplus finished tasks.
        deleted_cap: int = 0
        if max_finished_jobs >= 0 and len(remaining_finished) > max_finished_jobs:
            surplus = len(remaining_finished) - max_finished_jobs

            for name in remaining_finished[:surplus]:
                self._tasks.pop(name, None)
                self._task_submit_time.pop(name, None)
                deleted_cap += 1

        return {'deleted_ttl': deleted_ttl, 'deleted_cap': deleted_cap, 'evicted': 0}


register_backend('dispatcher', DispatcherBackend)
