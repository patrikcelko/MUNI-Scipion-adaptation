"""
Monitoring endpoints
====================

Read-only views into pods, jobs, events, metrics, and logs of the
configured Kubernetes namespace.
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from controller.utilities import (
    age,
    get_namespace,
    is_valid_k8s_name,
    job_phase,
    k8s,
    parse_cpu,
    parse_mem,
)

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api', tags=['monitoring'])

_EPOCH: datetime = datetime(1970, 1, 1, tzinfo=UTC)
"""Fallback timestamp for events with all-None time fields."""


@router.get('/pods')
async def api_pods(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all pods in the namespace with container- and resource-level detail."""

    ns: str = get_namespace(request)
    pods = k8s.core.list_namespaced_pod(ns).items
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
                    'req_cpu': r.requests.get('cpu', '-') if r.requests else '-',
                    'req_mem': r.requests.get('memory', '-') if r.requests else '-',
                    'lim_cpu': r.limits.get('cpu', '-') if r.limits else '-',
                    'lim_mem': r.limits.get('memory', '-') if r.limits else '-',
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

    return {'pods': result}


@router.get('/jobs')
async def api_jobs(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all jobs in the namespace with status info."""

    ns: str = get_namespace(request)
    jobs = k8s.batch.list_namespaced_job(ns).items
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
    return {'jobs': result}


@router.get('/events')
async def api_events(request: Request) -> dict[str, list[dict[str, Any]]]:
    """Return the 50 most recent namespace events."""

    ns: str = get_namespace(request)
    events = k8s.core.list_namespaced_event(ns).items
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
                'object': e.involved_object.name if e.involved_object else '-',
                'message': (e.message or '')[:200],
                'age': age(ts),
            }
        )

    return {'events': result}


@router.get('/metrics')
async def api_metrics(
    request: Request,
) -> dict[str, list[dict[str, Any]]]:
    """Node and pod resource usage from metrics-server."""

    ns: str = get_namespace(request)
    node_metrics: list[dict[str, Any]] = []
    pod_metrics: list[dict[str, Any]] = []

    # Node metrics
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
                    'cpu_pct': round(cpu_m / cpu_cap * 100, 1) if cpu_cap else 0,
                    'mem_used_mi': round(mem_mi),
                    'mem_capacity_mi': round(mem_cap),
                    'mem_pct': round(mem_mi / mem_cap * 100, 1) if mem_cap else 0,
                }
            )
    except Exception as exc:
        node_metrics = [{'error': str(exc)}]

    # Pod metrics
    try:
        pods = k8s.custom_api.list_namespaced_custom_object('metrics.k8s.io', 'v1beta1', ns, 'pods')

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


@router.get('/logs/{pod_name}', response_model=None)
async def api_logs(
    pod_name: str,
    request: Request,
    tail: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any] | JSONResponse:
    """Return the last *tail* lines of a pod's logs (with timestamps)."""

    ns: str = get_namespace(request)
    if not is_valid_k8s_name(pod_name):
        return JSONResponse({'error': 'invalid pod name'}, status_code=400)

    try:
        logs: str = k8s.core.read_namespaced_pod_log(pod_name, ns, tail_lines=tail, timestamps=True)
        return {'pod': pod_name, 'lines': logs.split('\n') if logs else []}
    except Exception as exc:
        return JSONResponse({'pod': pod_name, 'error': str(exc), 'lines': []}, status_code=500)
