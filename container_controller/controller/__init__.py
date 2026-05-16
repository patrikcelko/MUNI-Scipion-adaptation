"""
Scipion Container Controller
============================

A FastAPI-based microservice that bridges Scipion queue system to Kubernetes
Jobs. Receives SUBMIT / STATUS / CANCEL commands from the Scipion GUI
container and translates them into Kubernetes batch/v1 Job objects using
special tool container images.
"""

__version__: str = '11.0.0'
__all__: list[str] = ['__version__', 'create_app']

import logging
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from controller.api.endpoints import api_router
from controller.backends import InfraBackend, create_backend
from controller.tasks.cleanup import cleanup_finished_jobs
from controller.utilities.config import Settings, get_settings

logger: logging.Logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Start the background cleanup thread on application startup."""

    settings: Settings = app.state.settings  # type: ignore
    backend: InfraBackend = app.state.backend  # type: ignore
    thread = threading.Thread(
        target=cleanup_finished_jobs,
        kwargs={
            'backend': backend,
            'namespace': settings.namespace,
            'jobs_ttl': settings.jobs_ttl,
            'interval': settings.jobs_cleanup_interval,
            'max_finished_jobs': settings.max_finished_jobs,
        },
        name='cleanup',
        daemon=True,
    )

    thread.start()
    app.state.cleanup_thread = thread  # type: ignore

    logger.info(
        'Job cleanup thread started (TTL=%ds, interval=%ds, max_finished=%d)',
        settings.jobs_ttl,
        settings.jobs_cleanup_interval,
        settings.max_finished_jobs,
    )

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory - creates and configures app instance."""

    if settings is None:
        settings = get_settings()

    backend: InfraBackend = create_backend(settings.backend, settings)

    application = FastAPI(
        title='Scipion Container Controller',
        version=__version__,
        description=('Scipion Kubernetes job controller, translates qsub/qstat/qdel into Kubernetes Jobs.'),
        lifespan=_lifespan,
    )

    application.state.settings = settings  # type: ignore
    application.state.backend = backend  # type: ignore

    application.include_router(api_router)
    return application
