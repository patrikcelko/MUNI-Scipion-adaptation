"""
Dispatcher endpoint
===================
"""

import asyncio
import concurrent.futures
import ipaddress
import json
import logging
import os
import re
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse, urlunparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from controller.api.schemas import ErrorResponse, ImportWorkflowResponse

if TYPE_CHECKING:
    from controller.utilities.config import Settings

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(tags=['dispatcher'])


def _resolve_to_public_ip(hostname: str, timeout: float = 5.0) -> str | None:
    """Resolve *hostname* to its first public IP."""

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(
                socket.getaddrinfo,
                hostname,
                None,
                socket.AF_UNSPEC,
                socket.SOCK_STREAM,
            )
            addrs = future.result(timeout=timeout)
    except (socket.gaierror, OSError, concurrent.futures.TimeoutError):
        return None

    if not addrs:
        return None

    first_ip: str | None = None
    for _family, _type, _proto, _canon, sockaddr in addrs:
        addr = sockaddr[0]
        if not isinstance(addr, str):
            continue  # AF_PACKET / AF_LINK

        ip = ipaddress.ip_address(addr)
        if ip.is_private or ip.is_loopback or ip.is_link_local:
            return None

        if first_ip is None:
            first_ip = addr

    return first_ip


_MAX_WORKFLOW_BYTES: int = 10 * 1024 * 1024  # 10 MB


def _fetch_workflow_json(workflow_url: str) -> list[Any] | JSONResponse:
    """Validate the URL, download, and parse workflow JSON. Returns the parsed list
    of protocols, or a JSONResponse on any error.
    """

    parsed = urlparse(workflow_url)
    if parsed.scheme not in ('https', 'http'):
        return JSONResponse(
            {'error': 'workflow_url must use http(s)'},
            status_code=400,
        )

    resolved_ip = _resolve_to_public_ip(parsed.hostname) if parsed.hostname else None
    if not parsed.hostname or resolved_ip is None:
        return JSONResponse(
            {'error': 'workflow_url must not target private networks'},
            status_code=400,
        )

    ip_str = f'[{resolved_ip}]' if ':' in resolved_ip else resolved_ip
    port_part = f':{parsed.port}' if parsed.port else ''

    safe_url = urlunparse((
        parsed.scheme,
        f'{ip_str}{port_part}',
        parsed.path,
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))
    try:
        req = urllib.request.Request(safe_url, method='GET')
        req.add_header('User-Agent', 'Scipion-Controller/1.0')
        req.add_header('Host', parsed.hostname)  # required for SNI / virtual hosting
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw: str = resp.read(_MAX_WORKFLOW_BYTES + 1).decode('utf-8')

        if len(raw) > _MAX_WORKFLOW_BYTES:
            return JSONResponse(
                {'error': 'Workflow file exceeds 10 MB limit'},
                status_code=400,
            )

        workflow_json: Any = json.loads(raw)
    except (urllib.error.URLError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return JSONResponse(
            {'error': f'Failed to download workflow: {exc}'},
            status_code=400,
        )

    if not isinstance(workflow_json, list):
        return JSONResponse(
            {'error': 'Workflow JSON must be a list of protocols'},
            status_code=400,
        )

    return workflow_json


@router.post('/import_workflow', response_model=ImportWorkflowResponse, responses={400: {'model': ErrorResponse}, 409: {'model': ErrorResponse}})
async def import_workflow(request: Request) -> dict[str, Any] | JSONResponse:
    """Import a Scipion workflow JSON from a URL into a new project."""

    cfg: Settings = request.app.state.settings
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            {'error': 'invalid or missing JSON body'},
            status_code=400,
        )

    workflow_url: str | None = data.get('workflow_url')
    if not workflow_url:
        return JSONResponse(
            {'error': 'workflow_url is required'},
            status_code=400,
        )

    project_name: str = re.sub(r'[^A-Za-z0-9_-]', '_', data.get('project_name', 'DispatcherProject'))[:64]

    result = await asyncio.to_thread(_fetch_workflow_json, workflow_url)
    if isinstance(result, JSONResponse):
        return result

    workflow_json: list[Any] = result

    # Persist workflow file (all blocking I/O offloaded to a thread).
    base_path: Path = Path('/projects' if cfg.storage_mode == 'pvc' else cfg.local_path)
    workflows_dir: Path = base_path / '.dispatcher_workflows'
    workflow_path: Path = workflows_dir / f'{project_name}.json'

    def _persist() -> None:
        workflows_dir.mkdir(parents=True, exist_ok=True)
        with workflow_path.open('x', encoding='utf-8') as fh:
            json.dump(workflow_json, fh)

    try:
        await asyncio.to_thread(_persist)
    except FileExistsError:
        return JSONResponse(
            {'error': f'workflow for project {project_name!r} already exists'},
            status_code=409,
        )

    logger.info(
        'Imported workflow %s (%d protocols) from %s',
        project_name,
        len(workflow_json),
        workflow_url,
    )

    # VNC_HOST should be set via Helm / env var. Do NOT fall back to the
    # user-controlled Host request header, that would allow a Host-header
    # injection to generate a phishing vnc_url.
    vnc_host: str = os.environ.get('VNC_HOST', 'localhost')
    vnc_port: str = os.environ.get('VNC_PORT', '31335')

    return {
        'ok': True,
        'project_name': project_name,
        'protocols_count': len(workflow_json),
        'workflow_path': str(workflow_path),
        'vnc_url': f'http://{vnc_host}:{vnc_port}/vnc.html',
    }
