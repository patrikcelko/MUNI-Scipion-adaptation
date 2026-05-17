"""
Monitoring endpoints
====================

Read-only views into pods, jobs, events, metrics, and logs of the
configured Kubernetes namespace.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from controller.api.schemas import (
    ErrorResponse,
    EventListResponse,
    JobListResponse,
    LogsResponse,
    MetricsResponse,
    PodListResponse,
)
from controller.utilities import (
    get_namespace,
    is_valid_k8s_name,
)

logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api', tags=['monitoring'])


@router.get('/pods', response_model=PodListResponse)
async def api_pods(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all pods in the namespace with container- and resource-level detail."""

    ns: str = get_namespace(request)
    backend = request.app.state.backend

    return {'pods': backend.list_pods(ns)}


@router.get('/jobs', response_model=JobListResponse)
async def api_jobs(request: Request) -> dict[str, list[dict[str, Any]]]:
    """List all jobs in the namespace with status info."""

    ns: str = get_namespace(request)
    backend = request.app.state.backend
    return {'jobs': backend.list_jobs(ns)}


@router.get('/events', response_model=EventListResponse)
async def api_events(request: Request) -> dict[str, list[dict[str, Any]]]:
    """Return the 50 most recent namespace events."""

    ns: str = get_namespace(request)
    backend = request.app.state.backend
    return {'events': backend.list_events(ns)}


@router.get('/metrics', response_model=MetricsResponse)
async def api_metrics(request: Request) -> dict[str, list[dict[str, Any]]]:
    """Node and pod resource usage from metrics-server."""

    ns: str = get_namespace(request)
    backend = request.app.state.backend
    return backend.get_metrics(ns)


@router.get('/logs/{pod_name}', response_model=LogsResponse, responses={400: {'model': ErrorResponse}, 500: {'model': LogsResponse}})
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
        backend = request.app.state.backend
        logs: str = backend.read_pod_log(pod_name, ns, tail=tail)
        return {'pod': pod_name, 'lines': logs.split('\n') if logs else []}
    except Exception as exc:
        return JSONResponse({'pod': pod_name, 'error': str(exc), 'lines': []}, status_code=500)
