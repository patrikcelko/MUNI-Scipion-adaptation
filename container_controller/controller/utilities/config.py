"""
Configuration
=============
"""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _read_ns_file() -> str | None:
    """Try to read the in-cluster namespace file."""

    try:
        with Path('/var/run/secrets/kubernetes.io/serviceaccount/namespace').open(
            encoding='utf-8',
        ) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class Settings:
    """Application settings."""

    # Core
    namespace: str = 'default'
    jobs_ttl: int = 600
    jobs_cleanup_interval: int = 120
    max_finished_jobs: int = 3

    # Storage
    storage_mode: str = 'pvc'
    local_path: str = '/srv/scipion/projects'
    projects_pvc: str = 'scipion-projects'
    pvc_sub_path: str = 'projects'

    # Node scheduling
    node_selector_json: dict[str, Any] = field(default_factory=dict)
    tolerations_json: list[dict[str, Any]] = field(default_factory=list)

    # OneData
    onedata_enabled: bool = False
    oneclient_image: str = 'onedata/oneclient:latest'
    oneclient_provider: str = ''
    oneclient_space: str = ''
    oneclient_token_secret: str = 'onedata-credentials'
    oneclient_extra: list[str] = field(default_factory=list)

    # Toolmap
    toolmap_path: str = '/config/tools.yaml'

    # Worker pod image pull policy
    worker_pull_policy: str = 'Always'

    # Apply restricted PodSecurity securityContext to tool Job pods
    # (required for namespaces with restricted PodSecurity policy, e.g. CERIT Rancher)
    restricted_security_context: bool = False

    # Backend
    backend: str = 'k8s'

    # Server
    port: int = 5000


def _safe_storage_mode(raw: str) -> str:
    """Validate raw is a known storage mode, defaulting to `"pvc"`."""

    valid = ('pvc', 'local')
    if raw in valid:
        return raw

    logger.warning("Unknown STORAGE_MODE=%r, falling back to 'pvc'", raw)

    return 'pvc'


def _safe_int(env_var: str, default: int) -> int:
    """Read an integer from env_var, falling back to default on error."""

    raw = os.environ.get(env_var)
    if raw is None:
        return default

    try:
        return int(raw)
    except (ValueError, TypeError):
        logger.warning('Invalid integer for %s=%r, using default %d', env_var, raw, default)
        return default


def _safe_str_dict(env_var: str, value: dict[str, Any]) -> dict[str, str]:
    """Validate that all values in a parsed dict are strings. K8s node selectors require
    `dict[str, str]`. Returns an empty dict and logs a warning when the constraint is
    violated.
    """

    if not all(isinstance(v, str) for v in value.values()):
        logger.warning(
            '%s values must all be strings (K8s label format); using empty dict',
            env_var,
        )
        return {}

    return value


def _safe_json(env_var: str, default: Any, expected_type: type) -> Any:
    """Read a JSON value of expected_type from env_var, falling back to default."""

    raw = os.environ.get(env_var) or ''
    if not raw:
        return default

    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning('Invalid JSON for %s=%r, using default', env_var, raw[:80])
        return default

    if not isinstance(parsed, expected_type):
        logger.warning(
            'Expected %s for %s, got %s, using default',
            expected_type.__name__,
            env_var,
            type(parsed).__name__,
        )
        return default

    return parsed


def get_settings() -> Settings:
    """Build a :class:`Settings` instance from environment variables."""

    namespace: str = os.environ.get('NAMESPACE') or _read_ns_file() or 'default'

    return Settings(
        namespace=namespace,
        jobs_ttl=max(1, _safe_int('JOBS_TTL', 600)),
        jobs_cleanup_interval=max(1, _safe_int('JOBS_CLEANUP_INTERVAL', 120)),
        max_finished_jobs=max(0, _safe_int('MAX_FINISHED_JOBS', 3)),
        storage_mode=_safe_storage_mode(os.environ.get('STORAGE_MODE', 'pvc')),
        local_path=os.environ.get('LOCAL_PATH', '/srv/scipion/projects'),
        projects_pvc=os.environ.get('PROJECTS_PVC', 'scipion-projects'),
        pvc_sub_path=os.environ.get('PVC_SUB_PATH', 'projects'),
        node_selector_json=_safe_str_dict('NODE_SELECTOR_JSON', _safe_json('NODE_SELECTOR_JSON', {}, dict)),
        tolerations_json=_safe_json('TOLERATIONS_JSON', [], list),
        onedata_enabled=(os.environ.get('ONEDATA_ENABLED', 'false').lower() == 'true'),
        oneclient_image=os.environ.get('ONECLIENT_IMAGE', 'onedata/oneclient:latest'),
        oneclient_provider=os.environ.get('ONECLIENT_PROVIDER', ''),
        oneclient_space=os.environ.get('ONECLIENT_SPACE', ''),
        oneclient_token_secret=os.environ.get('ONECLIENT_TOKEN_SECRET', 'onedata-credentials'),
        oneclient_extra=_safe_json('ONECLIENT_EXTRA', [], list),
        toolmap_path=os.environ.get('TOOLMAP_PATH', '/config/tools.yaml'),
        worker_pull_policy=os.environ.get('WORKER_PULL_POLICY', 'Always'),
        restricted_security_context=(os.environ.get('RESTRICTED_SECURITY_CONTEXT', 'false').lower() == 'true'),
        backend=os.environ.get('BACKEND', 'k8s'),
        port=max(1, min(65535, _safe_int('PORT', 5000))),
    )
