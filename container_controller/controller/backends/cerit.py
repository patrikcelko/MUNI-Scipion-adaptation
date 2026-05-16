"""
CERIT backend
=============
"""

import logging
from typing import TYPE_CHECKING

from kubernetes import client

from controller.backends import register_backend
from controller.backends.k8s import K8sBackend
from controller.utilities import k8s

if TYPE_CHECKING:
    from controller.utilities.config import Settings

logger: logging.Logger = logging.getLogger(__name__)

_CERIT_DEFAULT_CPU_REQUEST: str = '1'
_CERIT_DEFAULT_CPU_LIMIT: str = '4'
_CERIT_DEFAULT_MEM_REQUEST_MB: int = 2048
_CERIT_GPU_RESOURCE: str = 'nvidia.com/gpu'


class CeritBackend(K8sBackend):
    """CERIT-SC Kubernetes backend (Rancher-managed clusters)."""

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
        cfg: Settings = self.settings

        volumes, mounts = self._build_volumes()

        env_vars: list[client.V1EnvVar] = [
            client.V1EnvVar(name=k, value=v) for k, v in env.items()
        ]

        # CERIT-SC requires BOTH requests and limits on every container.
        # Memory request is half of limit but at least the default floor,
        # and never exceeding the limit itself.
        mem_request: int = min(max(mem_mb // 2, _CERIT_DEFAULT_MEM_REQUEST_MB), mem_mb)
        resource_requests: dict[str, str] = {
            'cpu': _CERIT_DEFAULT_CPU_REQUEST,
            'memory': f'{mem_request}Mi',
        }
        resource_limits: dict[str, str] = {
            'cpu': _CERIT_DEFAULT_CPU_LIMIT,
            'memory': f'{mem_mb}Mi',
        }
        if gpu:
            resource_limits[_CERIT_GPU_RESOURCE] = '1'
            resource_requests[_CERIT_GPU_RESOURCE] = '1'

        main_container: client.V1Container = client.V1Container(
            name='tool',
            image=image,
            image_pull_policy='IfNotPresent',
            command=command,
            volume_mounts=mounts,
            env=env_vars,
            resources=client.V1ResourceRequirements(
                limits=resource_limits,
                requests=resource_requests,
            ),
        )

        containers: list[client.V1Container] = [main_container]

        if cfg.onedata_enabled:
            containers.append(self._build_onedata_sidecar(main_container))

        pod_spec: client.V1PodSpec = client.V1PodSpec(
            restart_policy='Never',
            containers=containers,
            volumes=volumes,
            node_selector=cfg.node_selector_json or None,
            tolerations=[
                client.V1Toleration(**t) for t in (cfg.tolerations_json or [])
            ],
        )

        if cfg.storage_mode == 'local' and prefer_node:
            pod_spec.node_name = prefer_node

        template: client.V1PodTemplateSpec = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=labels),
            spec=pod_spec,
        )

        job_metadata_labels = {k: v for k, v in labels.items() if k in ('app', 'tool')}

        job_obj: client.V1Job = client.V1Job(
            api_version='batch/v1',
            kind='Job',
            metadata=client.V1ObjectMeta(
                name=job_name,
                namespace=namespace,
                labels=job_metadata_labels,
            ),
            spec=client.V1JobSpec(
                backoff_limit=0,
                ttl_seconds_after_finished=cfg.jobs_ttl,
                template=template,
            ),
        )

        k8s.batch.create_namespaced_job(namespace, job_obj)

    def _build_volumes(
        self,
    ) -> tuple[list[client.V1Volume], list[client.V1VolumeMount]]:
        cfg: Settings = self.settings
        volumes: list[client.V1Volume] = []
        mounts: list[client.V1VolumeMount] = []

        if cfg.storage_mode == 'pvc':
            volumes.append(
                client.V1Volume(
                    name='projects',
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=cfg.projects_pvc,
                    ),
                )
            )
            mounts.append(
                client.V1VolumeMount(
                    name='projects',
                    mount_path='/projects',
                    sub_path=cfg.pvc_sub_path or None,
                )
            )
        elif cfg.storage_mode == 'local':
            volumes.append(
                client.V1Volume(
                    name='projects',
                    host_path=client.V1HostPathVolumeSource(
                        path=cfg.local_path, type='DirectoryOrCreate'
                    ),
                )
            )
            mounts.append(client.V1VolumeMount(name='projects', mount_path='/projects'))

        return volumes, mounts

    def _build_onedata_sidecar(
        self, main_container: client.V1Container
    ) -> client.V1Container:
        cfg: Settings = self.settings

        return client.V1Container(
            name='oneclient',
            image=cfg.oneclient_image,
            command=['oneclient', '--force-direct-io', cfg.oneclient_space],
            env=[
                client.V1EnvVar(
                    name='ONECLIENT_PROVIDER_HOST',
                    value=cfg.oneclient_provider,
                ),
                client.V1EnvVar(
                    name='ONECLIENT_ACCESS_TOKEN',
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=cfg.oneclient_token_secret, key='token'
                        ),
                    ),
                ),
            ]
            + [
                client.V1EnvVar(name='ONECLIENT_EXTRA', value=a)
                for a in cfg.oneclient_extra
            ],
            volume_mounts=main_container.volume_mounts,
            resources=client.V1ResourceRequirements(
                requests={'cpu': '100m', 'memory': '256Mi'},
                limits={'cpu': '500m', 'memory': '512Mi'},
            ),
            security_context=client.V1SecurityContext(privileged=True),
        )


register_backend('cerit', CeritBackend)
