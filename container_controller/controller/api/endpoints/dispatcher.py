"""
Dispatcher endpoint
===================
"""

import asyncio
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
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from controller.utilities.config import Settings

logger = logging.getLogger(__name__)
router: APIRouter = APIRouter(tags=['dispatcher'])


def _is_private_host(hostname: str) -> bool:
    """Return True if hostname resolves to a private/loopback address."""

    try:
        for _family, _type, _proto, _canon, sockaddr in socket.getaddrinfo(
            hostname,
            None,
            socket.AF_UNSPEC,
            socket.SOCK_STREAM,
        ):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local:
                return True

    except socket.gaierror:
        return True  # unresolvable -> reject
    return False


_MAX_WORKFLOW_BYTES: int = 10 * 1024 * 1024  # 10 MB


def _fetch_workflow_json(workflow_url: str) -> list[Any] | JSONResponse:
    """Validate the URL, download, and parse workflow JSON. Returns the parsed list
    of protocols, or a JSONResponse on any error.
    """

    parsed = urlparse(workflow_url)
    if parsed.scheme not in ('https', 'http'):
        return JSONResponse(
            {'ok': False, 'error': 'workflow_url must use http(s)'},
            status_code=400,
        )

    if not parsed.hostname or _is_private_host(parsed.hostname):
        return JSONResponse(
            {'ok': False, 'error': 'workflow_url must not target private networks'},
            status_code=400,
        )

    try:
        req = urllib.request.Request(workflow_url, method='GET')
        req.add_header('User-Agent', 'Scipion-Controller/1.0')
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw: str = resp.read(_MAX_WORKFLOW_BYTES + 1).decode('utf-8')

        if len(raw) > _MAX_WORKFLOW_BYTES:
            return JSONResponse(
                {'ok': False, 'error': 'Workflow file exceeds 10 MB limit'},
                status_code=400,
            )

        workflow_json: Any = json.loads(raw)
    except (urllib.error.URLError, ValueError, json.JSONDecodeError) as exc:
        return JSONResponse(
            {'ok': False, 'error': f'Failed to download workflow: {exc}'},
            status_code=400,
        )

    if not isinstance(workflow_json, list):
        return JSONResponse(
            {'ok': False, 'error': 'Workflow JSON must be a list of protocols'},
            status_code=400,
        )

    return workflow_json


@router.post('/import_workflow', response_model=None)
async def import_workflow(request: Request) -> dict[str, Any] | JSONResponse:
    """Import a Scipion workflow JSON from a URL into a new project."""

    cfg: Settings = request.app.state.settings
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(
            {'ok': False, 'error': 'invalid or missing JSON body'},
            status_code=400,
        )

    workflow_url: str | None = data.get('workflow_url')
    if not workflow_url:
        return JSONResponse(
            {'ok': False, 'error': 'workflow_url is required'},
            status_code=400,
        )

    project_name: str = re.sub(r'[^A-Za-z0-9_-]', '_', data.get('project_name', 'DispatcherProject'))[:64]

    result = _fetch_workflow_json(workflow_url)
    if isinstance(result, JSONResponse):
        return result
    workflow_json: list[Any] = result

    # Persist workflow file (all blocking I/O offloaded to a thread).
    base_path: Path = Path('/projects' if cfg.storage_mode == 'pvc' else cfg.local_path)
    workflows_dir: Path = base_path / '.dispatcher_workflows'
    workflow_path: Path = workflows_dir / f'{project_name}.json'

    def _persist() -> None:
        workflows_dir.mkdir(parents=True, exist_ok=True)
        with workflow_path.open('w', encoding='utf-8') as fh:
            json.dump(workflow_json, fh)

    await asyncio.to_thread(_persist)

    logger.info(
        'Imported workflow %s (%d protocols) from %s',
        project_name,
        len(workflow_json),
        workflow_url,
    )

    vnc_host: str = os.environ.get(
        'VNC_HOST',
        request.headers.get('host', 'localhost').split(':')[0],
    )
    vnc_port: str = os.environ.get('VNC_PORT', '31335')

    return {
        'ok': True,
        'project_name': project_name,
        'protocols_count': len(workflow_json),
        'workflow_path': str(workflow_path),
        'vnc_url': f'http://{vnc_host}:{vnc_port}/vnc.html',
    }
