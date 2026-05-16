"""
K8s backend
===========
"""

import logging
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from kubernetes import client
from kubernetes.client.exceptions import ApiException

from controller.backends import BackendError, InfraBackend, register_backend
from controller.utilities import age, job_phase, k8s, parse_cpu, parse_mem

if TYPE_CHECKING:
    from controller.utilities.config import Settings

logger: logging.Logger = logging.getLogger(__name__)

_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=UTC)
"""Fallback timestamp for events with all-None time fields."""


class K8sBackend(InfraBackend):
    """Kubernetes backend using the standard K8s Python client."""

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
        env_vars: list[client.V1EnvVar] = [client.V1EnvVar(name=k, value=v) for k, v in env.items()]

        resource_limits: dict[str, str] = {'memory': f'{mem_mb}Mi', 'cpu': '2'}
        resource_requests: dict[str, str] = {
            'memory': f'{max(mem_mb // 2, 512)}Mi',
            'cpu': '500m',
        }
        if gpu:
            resource_limits['nvidia.com/gpu'] = '1'

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

        # OneData sidecar
        if cfg.onedata_enabled:
            containers.append(self._build_onedata_sidecar(main_container))

        # Pod spec
        pod_spec: client.V1PodSpec = client.V1PodSpec(
            restart_policy='Never',
            containers=containers,
            volumes=volumes,
            node_selector=cfg.node_selector_json or None,
            tolerations=[client.V1Toleration(**t) for t in (cfg.tolerations_json or [])],
        )

        if cfg.storage_mode == 'local' and prefer_node:
            pod_spec.node_name = prefer_node

        # Template & Job
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

    def read_job_phase(self, job_name: str, namespace: str) -> str | None:
        try:
            job = k8s.batch.read_namespaced_job(job_name, namespace)
        except Exception:
            return None
        return job_phase(job)

    def delete_job(self, job_name: str, namespace: str) -> None:
        try:
            k8s.batch.delete_namespaced_job(job_name, namespace, propagation_policy='Background')
        except ApiException as exc:
            raise BackendError(str(exc), status_code=exc.status or 500) from exc

    def list_pods(self, namespace: str) -> list[dict[str, Any]]:
        pods = k8s.core.list_namespaced_pod(namespace).items
        result: list[dict[str, Any]] = []

        for p in pods:
            containers: list[dict[str, Any]] = []
            for cs in p.status.container_statuses or []:
                state: str = 'waiting'
                if cs.state.running:
                    state = 'running'
                elif cs.state.terminated:
                    state = f'terminated ({cs.state.terminated.reason or "Unknown"})'
                containers.append(
                    {
                        'name': cs.name,
                        'image': cs.image,
                        'ready': cs.ready,
                        'restarts': cs.restart_count,
                        'state': state,
                    }
                )

            res_info: dict[str, dict[str, str]] = {}
            for c in p.spec.containers or []:
                r = c.resources
                if r:
                    res_info[c.name] = {
                        'req_cpu': (r.requests.get('cpu', '-') if r.requests else '-'),
                        'req_mem': (r.requests.get('memory', '-') if r.requests else '-'),
                        'lim_cpu': (r.limits.get('cpu', '-') if r.limits else '-'),
                        'lim_mem': (r.limits.get('memory', '-') if r.limits else '-'),
                    }

            result.append(
                {
                    'name': p.metadata.name,
                    'phase': p.status.phase,
                    'age': age(p.metadata.creation_timestamp),
                    'node': p.spec.node_name or '-',
                    'labels': {k: v for k, v in (p.metadata.labels or {}).items() if k in ('app', 'app.kubernetes.io/name', 'tool', 'job')},
                    'containers': containers,
                    'resources': res_info,
                }
            )

        return result

    def list_jobs(self, namespace: str) -> list[dict[str, Any]]:
        jobs = k8s.batch.list_namespaced_job(namespace).items
        result: list[dict[str, Any]] = []

        for j in jobs:
            st = j.status
            result.append(
                {
                    'name': j.metadata.name,
                    'phase': job_phase(j),
                    'age': age(j.metadata.creation_timestamp),
                    'tool': (j.metadata.labels or {}).get('tool', '-'),
                    'active': (st.active or 0) if st else 0,
                    'succeeded': (st.succeeded or 0) if st else 0,
                    'failed': (st.failed or 0) if st else 0,
                }
            )

        result.sort(key=lambda x: (x['phase'] != 'RUNNING', x['name']))
        return result

    def list_events(self, namespace: str) -> list[dict[str, Any]]:
        events = k8s.core.list_namespaced_event(namespace).items
        events.sort(
            key=lambda e: e.last_timestamp or e.event_time or e.metadata.creation_timestamp or _EPOCH,
            reverse=True,
        )

        result: list[dict[str, Any]] = []
        for e in events[:50]:
            ts = e.last_timestamp or e.event_time or e.metadata.creation_timestamp
            result.append(
                {
                    'type': e.type,
                    'reason': e.reason,
                    'object': (e.involved_object.name if e.involved_object else '-'),
                    'message': (e.message or '')[:200],
                    'age': age(ts),
                }
            )

        return result

    def get_metrics(self, namespace: str) -> dict[str, list[dict[str, Any]]]:
        node_metrics: list[dict[str, Any]] = []
        pod_metrics: list[dict[str, Any]] = []

        try:
            nodes = k8s.custom_api.list_cluster_custom_object('metrics.k8s.io', 'v1beta1', 'nodes')
            all_nodes = {nd.metadata.name: nd for nd in k8s.core.list_node().items}
            for n in nodes.get('items', []):
                usage = n.get('usage', {})
                cpu_m: float = parse_cpu(usage.get('cpu', '0'))
                mem_mi: float = parse_mem(usage.get('memory', '0'))
                node_obj = all_nodes.get(n['metadata']['name'])
                cap = (node_obj.status.capacity or {}) if node_obj and node_obj.status else {}
                cpu_cap: float = parse_cpu(cap.get('cpu', '0'))
                mem_cap: float = parse_mem(cap.get('memory', '0'))
                node_metrics.append(
                    {
                        'name': n['metadata']['name'],
                        'cpu_used_m': round(cpu_m),
                        'cpu_capacity_m': round(cpu_cap),
                        'cpu_pct': (round(cpu_m / cpu_cap * 100, 1) if cpu_cap else 0),
                        'mem_used_mi': round(mem_mi),
                        'mem_capacity_mi': round(mem_cap),
                        'mem_pct': (round(mem_mi / mem_cap * 100, 1) if mem_cap else 0),
                    }
                )
        except Exception as exc:
            node_metrics = [{'error': str(exc)}]

        try:
            pods = k8s.custom_api.list_namespaced_custom_object('metrics.k8s.io', 'v1beta1', namespace, 'pods')
            for p in pods.get('items', []):
                total_cpu: float = 0
                total_mem: float = 0
                for c in p.get('containers', []):
                    usage = c.get('usage', {})
                    total_cpu += parse_cpu(usage.get('cpu', '0'))
                    total_mem += parse_mem(usage.get('memory', '0'))
                pod_metrics.append(
                    {
                        'name': p['metadata']['name'],
                        'cpu_m': round(total_cpu),
                        'mem_mi': round(total_mem),
                    }
                )
        except Exception as exc:
            pod_metrics = [{'error': str(exc)}]

        return {'nodes': node_metrics, 'pods': pod_metrics}

    def read_pod_log(self, pod_name: str, namespace: str, *, tail: int = 100) -> str:
        return k8s.core.read_namespaced_pod_log(pod_name, namespace, tail_lines=tail, timestamps=True)

    def list_node_images(self) -> list[dict[str, Any]]:
        nodes = k8s.core.list_node().items
        result: list[dict[str, Any]] = []
        for node in nodes:
            node_name: str = node.metadata.name
            images: list[dict[str, Any]] = []
            for img in node.status.images or []:
                names: list[str] = img.names or []
                size_mb: float = round((img.size_bytes or 0) / (1024 * 1024), 1)
                images.append({'names': names, 'size_mb': size_mb})
            images.sort(key=lambda x: x['size_mb'], reverse=True)
            total_mb: float = round(sum(i['size_mb'] for i in images), 1)
            result.append(
                {
                    'node': node_name,
                    'images': images,
                    'total_mb': total_mb,
                    'count': len(images),
                }
            )
        return result

    def delete_pod(self, pod_name: str, namespace: str) -> None:
        try:
            k8s.core.delete_namespaced_pod(pod_name, namespace)
        except ApiException as exc:
            raise BackendError(str(exc), status_code=exc.status or 500) from exc

    def cleanup_once(
        self,
        *,
        namespace: str,
        jobs_ttl: int,
        max_finished_jobs: int,
    ) -> dict[str, int]:
        jobs = k8s.batch.list_namespaced_job(namespace, label_selector='app=scipion-worker').items
        now: float = time.time()
        deleted_ttl: int = 0
        deleted_cap: int = 0

        # TTL-based removal
        finished_jobs: list[Any] = []
        for job in jobs:
            phase: str = job_phase(job)
            if phase not in ('DONE', 'FAILED'):
                continue

            ts_val: float = self._job_finish_ts(job)
            if ts_val and (now - ts_val) > jobs_ttl:
                try:
                    k8s.batch.delete_namespaced_job(
                        job.metadata.name,
                        namespace,
                        propagation_policy='Background',
                    )
                    deleted_ttl += 1
                except Exception:
                    logger.debug('Failed to TTL-delete job %s', job.metadata.name)
            else:
                finished_jobs.append(job)

        # Cap-based removal
        if max_finished_jobs >= 0 and len(finished_jobs) > max_finished_jobs:
            finished_jobs.sort(key=lambda j: self._job_finish_ts(j) or now)
            to_delete = finished_jobs[: len(finished_jobs) - max_finished_jobs]
            for job in to_delete:
                try:
                    k8s.batch.delete_namespaced_job(
                        job.metadata.name,
                        namespace,
                        propagation_policy='Background',
                    )
                    deleted_cap += 1
                except Exception:
                    logger.debug('Failed to cap-delete job %s', job.metadata.name)

        # Evicted pod removal
        evicted: int = self._delete_evicted_pods(namespace)

        return {
            'deleted_ttl': deleted_ttl,
            'deleted_cap': deleted_cap,
            'evicted': evicted,
        }

    def _build_volumes(
        self,
    ) -> tuple[list[client.V1Volume], list[client.V1VolumeMount]]:
        """Build volumes and mounts from *self.settings*."""

        cfg: Settings = self.settings
        volumes: list[client.V1Volume] = []
        mounts: list[client.V1VolumeMount] = []

        if cfg.storage_mode == 'pvc':
            volumes.append(
                client.V1Volume(
                    name='projects-vol',
                    persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                        claim_name=cfg.projects_pvc,
                    ),
                )
            )
            mounts.append(
                client.V1VolumeMount(
                    name='projects-vol',
                    mount_path='/projects',
                    sub_path=cfg.pvc_sub_path or None,
                )
            )
            mounts.append(
                client.V1VolumeMount(
                    name='projects-vol',
                    mount_path='/data',
                    sub_path='data',
                )
            )
        else:
            volumes.append(
                client.V1Volume(
                    name='projects-local',
                    host_path=client.V1HostPathVolumeSource(path=cfg.local_path, type='DirectoryOrCreate'),
                )
            )
            mounts.append(client.V1VolumeMount(name='projects-local', mount_path='/projects'))

        volumes.append(
            client.V1Volume(
                name='datasets-vol',
                empty_dir=client.V1EmptyDirVolumeSource(),
            )
        )
        mounts.append(client.V1VolumeMount(name='datasets-vol', mount_path='/datasets'))

        return volumes, mounts

    def _build_onedata_sidecar(self, main_container: client.V1Container) -> client.V1Container:
        """Build the OneData oneclient sidecar container spec."""

        cfg: Settings = self.settings
        env: list[client.V1EnvVar] = [
            client.V1EnvVar(
                name='ONECLIENT_PROVIDER_HOST',
                value=cfg.oneclient_provider,
            ),
            client.V1EnvVar(name='ONECLIENT_SPACE', value=cfg.oneclient_space),
            client.V1EnvVar(
                name='ONECLIENT_ACCESS_TOKEN',
                value_from=client.V1EnvVarSource(secret_key_ref=client.V1SecretKeySelector(name=cfg.oneclient_token_secret, key='token')),
            ),
        ]
        mount_args: list[str] = (cfg.oneclient_extra or []) + [
            '--force-direct-io',
            '/datasets',
        ]
        sidecar: client.V1Container = client.V1Container(
            name='oneclient',
            image=cfg.oneclient_image,
            security_context=client.V1SecurityContext(privileged=True),
            env=env,
            command=['oneclient'],
            args=mount_args,
            volume_mounts=[
                client.V1VolumeMount(
                    name='datasets-vol',
                    mount_path='/datasets',
                    mount_propagation='Bidirectional',
                )
            ],
            lifecycle=client.V1Lifecycle(pre_stop=client.V1LifecycleHandler(_exec=client.V1ExecAction(command=['fusermount', '-uz', '/datasets']))),
        )

        # Adjust main container mount propagation for shared FUSE mount.
        for mount in main_container.volume_mounts or []:
            if mount.name == 'datasets-vol':
                mount.mount_propagation = 'HostToContainer'

        return sidecar

    @staticmethod
    def _job_finish_ts(job: Any) -> float:
        """Return the UNIX timestamp when a finished job ended (or 0)."""

        if job.status is None:
            return 0.0

        ts = getattr(job.status, 'completion_time', None) or getattr(job.status, 'start_time', None)
        if ts is None:
            return 0.0

        return ts.timestamp()

    @staticmethod
    def _delete_evicted_pods(namespace: str) -> int:
        """Delete all pods in `Failed` phase with reason `Evicted`."""

        deleted: int = 0
        try:
            pods = k8s.core.list_namespaced_pod(namespace, field_selector='status.phase=Failed').items

            for pod in pods:
                reason: str = getattr(pod.status, 'reason', None) or ''
                if reason == 'Evicted':
                    try:
                        k8s.core.delete_namespaced_pod(pod.metadata.name, namespace)
                        deleted += 1
                    except Exception:
                        logger.debug(
                            'Failed to delete evicted pod %s',
                            pod.metadata.name,
                        )
        except Exception:
            logger.debug('Failed to list failed pods in %s', namespace)

        return deleted


register_backend('k8s', K8sBackend)
