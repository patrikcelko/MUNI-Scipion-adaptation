"""
CERIT backend
=============
"""

import logging

from controller.backends import register_backend
from controller.backends.k8s import K8sBackend

logger: logging.Logger = logging.getLogger(__name__)

_CERIT_DEFAULT_CPU_REQUEST: str = '1'
_CERIT_DEFAULT_CPU_LIMIT: str = '4'
_CERIT_DEFAULT_MEM_REQUEST_MB: int = 2048
_CERIT_GPU_RESOURCE: str = 'nvidia.com/gpu'


class CeritBackend(K8sBackend):
    """CERIT-SC Kubernetes backend (Rancher-managed clusters)."""

    def _build_resource_requirements(
        self,
        mem_mb: int,
        gpu: bool,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """CERIT-SC requires matching requests and limits on every container,
        with a higher CPU limit and a memory request floor of 2 GiB.
        """

        mem_request: int = min(max(mem_mb // 2, _CERIT_DEFAULT_MEM_REQUEST_MB), mem_mb)
        limits: dict[str, str] = {'cpu': _CERIT_DEFAULT_CPU_LIMIT, 'memory': f'{mem_mb}Mi'}
        requests: dict[str, str] = {'cpu': _CERIT_DEFAULT_CPU_REQUEST, 'memory': f'{mem_request}Mi'}

        if gpu:
            limits[_CERIT_GPU_RESOURCE] = '1'
            requests[_CERIT_GPU_RESOURCE] = '1'

        return limits, requests


register_backend('cerit', CeritBackend)
