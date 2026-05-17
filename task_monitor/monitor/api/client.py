"""
API client
==========
"""

import json
import os
from typing import Any, cast
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from monitor.api.types import (
    CleanupRunData,
    DeletedData,
    DiskData,
    EventListData,
    JobListData,
    LogsData,
    MetricsData,
    PodListData,
)

DEFAULT_URL = 'http://container-controller:5000'
"""Default controller URL."""

_TIMEOUT_GET = 5
_TIMEOUT_MUTATE = 10


class ControllerClient:
    """Stateless HTTP client for the Scipion controller."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = (base_url or os.environ.get('CONTROLLER_URL') or DEFAULT_URL).rstrip('/')

    def fetch(self, endpoint: str) -> dict[str, Any] | list[Any] | None:
        """HTTP GET returning parsed JSON, or `None` on failure."""

        try:
            req = Request(
                f'{self.base_url}{endpoint}',
                headers={'Accept': 'application/json'},
            )
            with urlopen(req, timeout=_TIMEOUT_GET) as resp:
                return json.loads(resp.read())
        except (URLError, OSError, json.JSONDecodeError, ValueError):
            return None

    def _fetch_dict(self, endpoint: str) -> dict[str, Any] | None:
        """HTTP GET expecting a JSON object. Returns `None` for non-dict responses."""

        result = self.fetch(endpoint)
        return result if isinstance(result, dict) else None

    def mutate(self, method: str, endpoint: str) -> dict[str, Any] | None:
        """HTTP DELETE / POST returning parsed JSON, or `None`."""

        try:
            req = Request(
                f'{self.base_url}{endpoint}',
                headers={'Accept': 'application/json'},
                method=method,
            )
            with urlopen(req, timeout=_TIMEOUT_MUTATE) as resp:
                return json.loads(resp.read())
        except (URLError, OSError, json.JSONDecodeError, ValueError):
            return None

    def get_jobs(self) -> JobListData | None:
        """`GET /api/jobs` - job list with phase/tool/age."""

        return cast('JobListData | None', self._fetch_dict('/api/jobs'))

    def get_pods(self) -> PodListData | None:
        """`GET /api/pods` - pod list with container detail."""

        return cast('PodListData | None', self._fetch_dict('/api/pods'))

    def get_events(self) -> EventListData | None:
        """`GET /api/events` - most recent namespace events."""

        return cast('EventListData | None', self._fetch_dict('/api/events'))

    def get_metrics(self) -> MetricsData | None:
        """`GET /api/metrics` - node + pod resource usage."""

        return cast('MetricsData | None', self._fetch_dict('/api/metrics'))

    def get_disk(self) -> DiskData | None:
        """`GET /api/disk` - root filesystem usage."""

        return cast('DiskData | None', self._fetch_dict('/api/disk'))

    def get_logs(self, pod_name: str, tail: int = 50) -> LogsData | None:
        """`GET /api/logs/{pod_name}` - last *tail* log lines."""

        safe_name = quote(pod_name, safe='')
        return cast('LogsData | None', self._fetch_dict(f'/api/logs/{safe_name}?tail={tail}'))

    def delete_job(self, job_name: str) -> DeletedData | None:
        """`DELETE /api/job/{job_name}` - remove job + pods."""

        safe_name = quote(job_name, safe='')
        return cast('DeletedData | None', self.mutate('DELETE', f'/api/job/{safe_name}'))

    def delete_pod(self, pod_name: str) -> DeletedData | None:
        """`DELETE /api/pod/{pod_name}` - remove a single pod."""

        safe_name = quote(pod_name, safe='')
        return cast('DeletedData | None', self.mutate('DELETE', f'/api/pod/{safe_name}'))

    def run_cleanup(self) -> CleanupRunData | None:
        """`POST /api/cleanup/run` - force finished-job cleanup."""

        return cast('CleanupRunData | None', self.mutate('POST', '/api/cleanup/run'))
