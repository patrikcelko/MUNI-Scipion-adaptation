"""
Utilities
=========
"""

import math
import re
import time
from typing import Any, Protocol, cast

import yaml

K8S_NAME_RE: re.Pattern[str] = re.compile(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$')
"""RFC 1123 label: lower-alpha-numeric, hyphens allowed inside, max 63 chars."""


class _HasTimestamp(Protocol):
    """Anything that exposes a `.timestamp() -> float` method."""

    def timestamp(self) -> float: ...  # pragma: no cover


def load_yaml(path: str) -> dict[str, Any] | list[Any] | None:
    """Load a YAML file, returning None when the file does not exist."""

    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return yaml.safe_load(fh) or {}
    except OSError:
        return None


def age(ts: _HasTimestamp | None) -> str:
    """Convert a timestamp to a human-readable relative age string."""

    if not ts:
        return '-'

    delta: int = int(time.time() - ts.timestamp())
    if delta < 0:
        return '0s'

    if delta < 60:
        return f'{delta}s'

    if delta < 3600:
        return f'{delta // 60}m{delta % 60}s'

    return f'{delta // 3600}h{(delta % 3600) // 60}m'


def parse_cpu(val: str) -> float:
    """Parse a Kubernetes CPU quantity to millicores."""

    if not val:
        return 0.0

    try:
        if val.endswith('n'):
            result = float(val[:-1]) / 1_000_000
        elif val.endswith('u'):
            result = float(val[:-1]) / 1_000
        elif val.endswith('m'):
            result = float(val[:-1])
        else:
            result = float(val) * 1000

        return result if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


_MEM_UNITS: dict[str, float] = {
    'Ei': 1024**4,
    'Pi': 1024**3,
    'Ti': 1024 * 1024,
    'Gi': 1024,
    'Mi': 1,
    'Ki': 1 / 1024,
    'E': 1_000_000_000_000 / 1.048576,
    'P': 1_000_000_000 / 1.048576,
    'T': 1_000_000 / 1.048576,
    'G': 1000 / 1.048576,
    'M': 1 / 1.048576,
    'k': 1 / 1048.576,
}
"""Suffix -> MiB multiplier for Kubernetes memory quantities."""


def parse_mem(val: str) -> float:
    """Parse a Kubernetes memory quantity to MiB."""

    if not val:
        return 0.0

    try:
        for suffix, mult in _MEM_UNITS.items():
            if val.endswith(suffix):
                result = float(val[: -len(suffix)]) * mult
                return result if math.isfinite(result) else 0.0

        result = float(val) / (1024 * 1024)
        return result if math.isfinite(result) else 0.0
    except (ValueError, TypeError):
        return 0.0


def job_phase(job: Any) -> str:
    """Determine the phase of a K8s Job."""

    status = job.status
    if status is None:
        return 'RUNNING'

    if (status.succeeded or 0) >= 1:
        return 'DONE'

    if (status.failed or 0) >= 1 and (status.active or 0) == 0:
        return 'FAILED'

    return 'RUNNING'


def resolve_job_name(job_id: str) -> str:
    """Normalize a job identifier to the full `scipion-job-<id>` form. Scipion sends just
    the numeric ID; the Kubernetes Job is always named `scipion-job-<number>`.
    """

    if job_id.startswith('scipion-job-'):
        return job_id

    return f'scipion-job-{job_id}'


def is_valid_k8s_name(name: str) -> bool:
    """Check whether name is a valid RFC 1123 label."""

    return bool(K8S_NAME_RE.match(name))


_SAFE_PATH_RE: re.Pattern[str] = re.compile(r'^[A-Za-z0-9/_.\-]+$')
"""Allowed characters in user-supplied file-system paths."""


def is_safe_path(path: str) -> bool:
    """Return True when path contains only safe characters."""

    if not path or '..' in path.split('/'):
        return False

    return bool(_SAFE_PATH_RE.match(path))


def get_namespace(request: Any) -> str:
    """Return the active namespace from `app.state.settings`."""

    return cast(str, request.app.state.settings.namespace)
