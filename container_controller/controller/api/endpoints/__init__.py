"""
Endpoints
=========
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from controller import __version__
from controller.api.endpoints.admin import router as admin_router
from controller.api.endpoints.dispatcher import router as dispatcher_router
from controller.api.endpoints.jobs import router as jobs_router
from controller.api.endpoints.monitoring import router as monitoring_router

api_router: APIRouter = APIRouter()
"""Top-level router for all controller API endpoints."""

api_router.include_router(jobs_router)
api_router.include_router(monitoring_router)
api_router.include_router(admin_router)
api_router.include_router(dispatcher_router)


@api_router.get('/healthz', tags=['health'])
async def healthz() -> PlainTextResponse:
    """Kubernetes liveness / readiness probe."""

    return PlainTextResponse('ok\n')


@api_router.get('/', tags=['health'])
async def root() -> PlainTextResponse:
    """Human-friendly landing page."""

    return PlainTextResponse(f'Welcome to Scipion Controller v{__version__}\n')
