"""
Admin endpoints
===============

Destructive operations (delete job/pod, manual cleanup) and read-only
cluster housekeeping information (disk, cleanup status, images).
"""

import logging
import shutil
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from controller.api.endpoints.jobs import get_known_jobs_count
from controller.backends import BackendError
from controller.utilities import get_namespace, is_valid_k8s_name

if TYPE_CHECKING:
    from controller.utilities.config import Settings

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(prefix='/api', tags=['admin'])


@router.get('/cleanup')
async def api_cleanup_status(request: Request) -> dict[str, Any]:
    """Show current cleanup configuration and thread health."""

    cfg: Settings = request.app.state.settings
    thread = getattr(request.app.state, 'cleanup_thread', None)
    cleanup_alive: bool = thread is not None and thread.is_alive()

    return {
        'thread_alive': cleanup_alive,
        'ttl_seconds': cfg.jobs_ttl,
        'check_interval': cfg.jobs_cleanup_interval,
        'max_finished_jobs': cfg.max_finished_jobs,
        'known_jobs': get_known_jobs_count(),
    }


@router.get('/disk', response_model=None)
async def api_disk() -> dict[str, Any] | JSONResponse:
    """Report disk usage of the root filesystem."""

    try:
        usage = shutil.disk_usage('/')
        total_gi: float = round(usage.total / (1024**3), 1)
        used_gi: float = round(usage.used / (1024**3), 1)
        free_gi: float = round(usage.free / (1024**3), 1)
        percent: float = round(usage.used / usage.total * 100, 1) if usage.total else 0

        return {
            'total_gi': total_gi,
            'used_gi': used_gi,
            'free_gi': free_gi,
            'percent': percent,
        }
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@router.get('/images', response_model=None)
async def api_images(request: Request) -> dict[str, Any] | JSONResponse:
    """List container images cached on cluster nodes."""

    try:
        backend = request.app.state.backend

        return {'nodes': backend.list_node_images()}
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@router.delete('/job/{job_name}', response_model=None)
async def api_kill_job(
    job_name: str, request: Request
) -> dict[str, str] | JSONResponse:
    """Delete a specific job and its pods."""

    ns: str = get_namespace(request)
    if not is_valid_k8s_name(job_name):
        return JSONResponse({'error': 'invalid job name'}, status_code=400)
    try:
        backend = request.app.state.backend
        backend.delete_job(job_name, ns)
        return {'deleted': job_name}
    except BackendError as exc:
        return JSONResponse({'error': str(exc)}, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@router.delete('/pod/{pod_name}', response_model=None)
async def api_kill_pod(
    pod_name: str, request: Request
) -> dict[str, str] | JSONResponse:
    """Delete a specific pod."""

    ns: str = get_namespace(request)
    if not is_valid_k8s_name(pod_name):
        return JSONResponse({'error': 'invalid pod name'}, status_code=400)

    try:
        backend = request.app.state.backend
        backend.delete_pod(pod_name, ns)

        return {'deleted': pod_name}
    except BackendError as exc:
        return JSONResponse({'error': str(exc)}, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)


@router.post('/cleanup/run', response_model=None)
async def api_cleanup_run(
    request: Request,
) -> dict[str, int] | JSONResponse:
    """Manually trigger cleanup of finished jobs, cap enforcement, and evicted pods."""

    cfg: Settings = request.app.state.settings
    try:
        backend = request.app.state.backend

        return backend.cleanup_once(
            namespace=cfg.namespace,
            jobs_ttl=cfg.jobs_ttl,
            max_finished_jobs=cfg.max_finished_jobs,
        )
    except Exception as exc:
        return JSONResponse({'error': str(exc)}, status_code=500)
