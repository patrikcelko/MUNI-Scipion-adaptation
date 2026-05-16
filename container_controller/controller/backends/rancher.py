"""
Rancher backend
===============
"""

import logging

from controller.backends import register_backend
from controller.backends.k8s import K8sBackend

logger: logging.Logger = logging.getLogger(__name__)

_RANCHER_DEFAULT_CPU_REQUEST: str = '1'
_RANCHER_DEFAULT_CPU_LIMIT: str = '4'
_RANCHER_DEFAULT_MEM_REQUEST_MB: int = 2048
_RANCHER_GPU_RESOURCE: str = 'nvidia.com/gpu'


class RancherBackend(K8sBackend):
    """Rancher-managed Kubernetes backend (CERIT-SC clusters)."""

    def _build_resource_requirements(
        self,
        mem_mb: int,
        gpu: bool,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Rancher-managed clusters require matching requests and limits on every
        container, with a higher CPU limit and a memory request floor of 2 GiB.
        """

        mem_request: int = min(max(mem_mb // 2, _RANCHER_DEFAULT_MEM_REQUEST_MB), mem_mb)
        limits: dict[str, str] = {'cpu': _RANCHER_DEFAULT_CPU_LIMIT, 'memory': f'{mem_mb}Mi'}
        requests: dict[str, str] = {'cpu': _RANCHER_DEFAULT_CPU_REQUEST, 'memory': f'{mem_request}Mi'}

        if gpu:
            limits[_RANCHER_GPU_RESOURCE] = '1'
            requests[_RANCHER_GPU_RESOURCE] = '1'

        return limits, requests


register_backend('rancher', RancherBackend)
