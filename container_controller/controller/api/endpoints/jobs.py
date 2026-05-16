"""
Job endpoints
=============

`/submit`, `/status/{job_id}`, `/cancel/{job_id}` - the three
core endpoints consumed by Scipion queue adapter running inside
the GUI container.
"""

import base64
import logging
import os
import re
import time
from collections import OrderedDict
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from controller.api.schemas import CancelResponse, ErrorResponse, SubmitResponse
from controller.backends import BackendError
from controller.utilities import is_safe_path, is_valid_k8s_name, resolve_job_name
from controller.utilities.config import Settings
from controller.utilities.routing import (
    choose_tool,
    choose_tool_by_protocol,
    detect_protocol_from_command,
    detect_protocol_run_dir,
    load_toolmap,
)

logger: logging.Logger = logging.getLogger(__name__)

router: APIRouter = APIRouter(tags=['jobs'])

# Bounded set of recently submitted job IDs (max 10 000 entries).
# Used by /status to return non-empty for known jobs, preventing
# Scipion queue monitor from firing "JOB ID not found" before run.db
# has been synced.
_MAX_KNOWN_JOBS: int = 10_000
_known_jobs: OrderedDict[str, None] = OrderedDict()


def get_known_jobs_count() -> int:
    """Return the current number of tracked recently-submitted job IDs."""

    return len(_known_jobs)


# Scipion _libNone patch
_LIBNONE_SCRIPT: str = (
    'import pwem, os\n'
    "f = os.path.join(pwem.__path__[0], 'emlib', '_libNone.py')\n"
    "c = open(f, encoding='utf-8').read()\n"
    "if 'def write' not in c:\n"
    "    c += '\\n# --- K8s robustness: missing Image methods ---\\n'\n"
    "    c += 'Image.write = lambda self, *a: None\\n'\n"
    "    c += 'Image.convert2DataType = lambda self, *a: None\\n'\n"
    "    c += 'Image.applyTransforMatScipion = lambda self, *a: None\\n'\n"
    "    c += 'Image.getData = lambda self: None\\n'\n"
    "    c += 'Image.setData = lambda self, d: None\\n'\n"
    "    c += 'Image.readPreview = lambda self, *a: None\\n'\n"
    "    open(f, 'w', encoding='utf-8').write(c)\n"
)
_LIBNONE_B64: str = base64.b64encode(_LIBNONE_SCRIPT.encode()).decode()
_LIBNONE_PATCH: str = f'echo {_LIBNONE_B64} | base64 -d | python3 - 2>/dev/null; '

# Relion readCoordinates patch (emtable compatibility)
_RELION_PATCH_SCRIPT: str = (
    'import glob\n'
    'f = glob.glob(\n'
    "    '/opt/scipion/.scipion3/lib/python*/site-packages'\n"
    "    '/relion/convert/convert_deprecated.py'\n"
    ')[0]\n'
    's = open(f).read()\n'
    'o = (\n'
    "    'def readCoordinates(mic, fileName, coordsSet):\\n'\n"
    "    '    for row in md.iterRows(fileName):\\n'\n"
    "    '        coord = rowToCoordinate(row)\\n'\n"
    "    '        coord.setX(coord.getX())\\n'\n"
    "    '        coord.setY(coord.getY())\\n'\n"
    "    '        coord.setMicrograph(mic)\\n'\n"
    "    '        coordsSet.append(coord)'\n"
    ')\n'
    'n = (\n'
    "    'def readCoordinates(mic, fileName, coordsSet):\\n'\n"
    "    '    from emtable import Table as _T\\n'\n"
    "    '    import os as _os\\n'\n"
    "    '    if not _os.path.exists(fileName):\\n'\n"
    "    '        return\\n'\n"
    "    '    for row in _T(fileName=fileName):\\n'\n"
    "    '        coord = pwobj.Coordinate()\\n'\n"
    "    '        coord.setX(float(row.rlnCoordinateX))\\n'\n"
    "    '        coord.setY(float(row.rlnCoordinateY))\\n'\n"
    "    '        coord.setMicrograph(mic)\\n'\n"
    "    '        coordsSet.append(coord)'\n"
    ')\n'
    "open(f, 'w').write(s.replace(o, n))\n"
    "print('[PATCH] readCoordinates patched for emtable')\n"
)
_RELION_PATCH_B64: str = base64.b64encode(_RELION_PATCH_SCRIPT.encode()).decode()
_RELION_PATCH_CMD: str = f'echo {_RELION_PATCH_B64} | base64 -d | python3 - 2>/dev/null && '


def _get_settings(request: Request) -> Settings:
    """Retrieve the settings instance"""

    return cast('Settings', request.app.state.settings)


def _find_tool(
    protocol_name: str | None,
    cmd0: str,
    toolmap_path: str,
) -> dict[str, Any] | JSONResponse:
    """Resolve the tool config entry, or return a 422 JSONResponse on failure."""
    tool: dict[str, Any] | None = None
    if protocol_name:
        tool = choose_tool_by_protocol(protocol_name, toolmap_path)
    if not tool:
        logger.debug('Falling back to command-prefix routing: %s', cmd0)
        tool = choose_tool(cmd0, toolmap_path)
    if not tool:
        avail = [t.get('image') for t in load_toolmap(toolmap_path) if t.get('enabled', True)]
        logger.error(
            "No suitable container for protocol '%s'. Available: %s",
            protocol_name or 'unknown',
            avail,
        )
        return JSONResponse(
            {'error': (f"No container mapping found for protocol '{protocol_name or 'unknown'}'")},
            status_code=422,
        )
    return tool


def _build_cleanup_and_chown(
    project_root: str,
    run_dir: str,
) -> tuple[str, str]:
    """Build (cleanup_cmd, chown_cmd) shell fragments for a protocol run directory."""

    cleanup_cmd = (
        f'echo "[CLEANUP] Removing stale outputs in {run_dir}" && '
        f'rm -f "{project_root}/{run_dir}"/*.sqlite '
        f'"{project_root}/{run_dir}"/summary.txt '
        f'"{project_root}/{run_dir}"/summaryForMonitor.txt && '
        f'rm -f "{project_root}/{run_dir}/logs/run.stderr" '
        f'"{project_root}/{run_dir}/logs/run.stdout" '
        f'"{project_root}/{run_dir}/logs/steps.sqlite" && '
    )

    logger.debug('Will clean stale outputs in %s', run_dir)

    run_db_path: str = f'{project_root}/{run_dir}/logs/run.db'
    _script: str = "import sqlite3,sys\nc=sqlite3.connect(sys.argv[1],timeout=10)\nr=c.execute(\"UPDATE Objects SET value=0 WHERE name LIKE '%._streamState' AND value=1\")\nn=r.rowcount;c.commit();c.close()\nprint(f'[STREAM-FIX] Closed {n} open output streams') if n else None\n"
    _b64: str = base64.b64encode(_script.encode()).decode()
    close_streams_cmd: str = f'echo {_b64} | base64 -d | python3 - "{run_db_path}" 2>/dev/null; '

    chown_cmd = f'; _ec=$?; {close_streams_cmd}chown -R 1000:1000 "{project_root}/{run_dir}" 2>/dev/null; chown 1000:1000 "{project_root}/project.sqlite" 2>/dev/null; exit $_ec'

    return cleanup_cmd, chown_cmd


def _register_job(job_id: str) -> None:
    """Track a submitted job ID, evicting the oldest entry when the cap is reached."""

    _known_jobs[job_id] = None
    if len(_known_jobs) > _MAX_KNOWN_JOBS:
        _known_jobs.popitem(last=False)


@router.post('/submit', response_model=SubmitResponse, responses={400: {'model': ErrorResponse}, 422: {'model': ErrorResponse}})
async def submit(request: Request) -> dict[str, str] | JSONResponse:
    """Accept a Scipion command and create a Kubernetes Job for it."""

    cfg: Settings = _get_settings(request)
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({'error': 'invalid or missing JSON body'}, status_code=400)

    original: str = (data.get('originalCmd') or '').strip()
    if not original:
        return JSONResponse({'error': 'missing originalCmd'}, status_code=400)

    cmd0: str = original.split(maxsplit=1)[0]
    logger.debug('Received command: %s', original)

    protocol_name: str | None = detect_protocol_from_command(original)
    logger.debug('Detected protocol: %s', protocol_name or 'unknown')

    tool_result = _find_tool(protocol_name, cmd0, cfg.toolmap_path)
    if isinstance(tool_result, JSONResponse):
        return tool_result

    tool: dict[str, Any] = tool_result

    # Resolve submission parameters
    ns: str = cfg.namespace
    project_root: str = data.get('projectRoot') or '/projects'
    if not is_safe_path(project_root):
        return JSONResponse(
            {'error': 'projectRoot contains invalid characters'},
            status_code=400,
        )

    prefer_node: str | None = data.get('preferNode')
    res: dict[str, Any] = data.get('resources') or {}
    want_gpu: bool = bool(tool.get('needsGpu')) or bool(res.get('gpus', 0))

    job_id: str = f'{int(time.time() * 1000)}-{os.urandom(3).hex()}'
    job_name: str = f'scipion-job-{job_id}'

    # Scipion environment setup
    command: str = original
    scipion_env_setup: str = f'export SCIPION_HOME=/opt/scipion && export XMIPP_HOME=/opt/scipion/software/em/xmipp-devel && export LD_LIBRARY_PATH="/opt/scipion/software/em/xmipp-devel/dist/lib:${{LD_LIBRARY_PATH}}" && . /opt/scipion/.scipion3/bin/activate && {_LIBNONE_PATCH}true'

    if original.startswith('python3 '):
        command = original.replace('python3', 'python -m scipion run python3', 1)
        logger.debug("Wrapping with 'python -m scipion run' for domain init")
    else:
        logger.debug('Running non-python command as-is')

    env: dict[str, str] = {
        'PBS_O_WORKDIR': project_root,
        'PBS_NODEFILE': '/tmp/pbs_nodefile',
        'XMIPP_IN_QUEUE': '1',
        'OMPI_ALLOW_RUN_AS_ROOT': '1',
        'OMPI_ALLOW_RUN_AS_ROOT_CONFIRM': '1',
    }

    tool_setup_cmd: str = _build_tool_setup(protocol_name)

    run_dir: str | None = detect_protocol_run_dir(original)
    if run_dir and not is_safe_path(run_dir):
        return JSONResponse(
            {'error': 'run directory contains invalid characters'},
            status_code=400,
        )
    cleanup_cmd, chown_cmd = _build_cleanup_and_chown(project_root, run_dir) if run_dir else ('', '')

    try:
        mem_mb: int = max(512, min(65536, int(res.get('memoryMb', 4096))))
    except (ValueError, TypeError):
        mem_mb = 4096

    full_shell_cmd: str = f'mkdir -p /home/scipion/ScipionUserData && ln -sfn /projects /home/scipion/ScipionUserData/projects && echo "localhost" > /tmp/pbs_nodefile && {cleanup_cmd}{tool_setup_cmd}{scipion_env_setup} && cd "{project_root}" && {command}{chown_cmd}'

    tool_label: str = re.sub(r'[^A-Za-z0-9._-]', '_', (protocol_name or cmd0))[:63].strip('_.-') or 'unknown'

    backend = request.app.state.backend
    backend.submit_job(
        namespace=ns,
        job_name=job_name,
        image=tool['image'],
        command=['/bin/bash', '-c', full_shell_cmd],
        env=env,
        labels={
            'app': 'scipion-worker',
            'job': job_name,
            'tool': tool_label,
        },
        mem_mb=mem_mb,
        gpu=want_gpu,
        prefer_node=prefer_node,
    )
    _register_job(job_id)
    return {'jobId': job_name, 'jobNumber': job_id}


@router.get('/status/{job_id}')
async def status(job_id: str, request: Request) -> PlainTextResponse:
    """Return the phase of a submitted job. Also returns an empty body
    when the job is finished or unknown, this is the convention Scipion
    queue monitor expects.
    """

    cfg: Settings = _get_settings(request)
    real_name: str = resolve_job_name(job_id)
    if not is_valid_k8s_name(real_name):
        return PlainTextResponse('invalid job id', status_code=400)

    backend = request.app.state.backend
    phase: str | None = backend.read_job_phase(real_name, cfg.namespace)

    if phase is None or phase in ('DONE', 'FAILED'):
        return PlainTextResponse('')

    return PlainTextResponse(phase + '\n')


@router.post('/cancel/{job_id}', response_model=CancelResponse, responses={400: {'model': CancelResponse}, 500: {'model': CancelResponse}})
async def cancel(job_id: str, request: Request) -> dict[str, bool] | JSONResponse:
    """Delete a running job (and its pods)."""

    cfg: Settings = _get_settings(request)
    real_name: str = resolve_job_name(job_id)
    if not is_valid_k8s_name(real_name):
        return JSONResponse({'ok': False, 'error': 'invalid job id'}, status_code=400)

    try:
        backend = request.app.state.backend
        backend.delete_job(real_name, cfg.namespace)

        return {'ok': True}
    except BackendError as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=exc.status_code)
    except Exception as exc:
        return JSONResponse({'ok': False, 'error': str(exc)}, status_code=500)


def _build_tool_setup(protocol_name: str | None) -> str:
    """Generate shell commands for per-protocol tool initialization."""

    if not protocol_name:
        return ''

    cmd: str = ''

    if re.match(r'Xmipp', protocol_name):
        cmd += 'echo "[TOOL-SETUP] Setting up Xmipp binary paths..." && ln -sfn /opt/scipion/software/em/xmipp-devel/dist/bin /opt/scipion/software/em/xmipp-devel/bin 2>/dev/null && echo "[TOOL-SETUP] Xmipp setup complete" && '

    elif 'Relion' in protocol_name:
        cmd += (
            'echo "[TOOL-SETUP] Setting up Relion environment..." && '
            'export RELION_HOME=/usr/local && '
            'mkdir -p /opt/scipion/software/em/relion-4.0/bin && '
            'for bin in /usr/local/bin/relion_*; do '
            '  ln -sf "$bin" '
            '/opt/scipion/software/em/relion-4.0/bin/"$(basename "$bin")"'
            ' 2>/dev/null; '
            'done && '
            '/opt/scipion/.scipion3/bin/pip install'
            ' --no-deps --force-reinstall scipion-em-relion 2>&1 | tail -3 && '
            f'{_RELION_PATCH_CMD}'
            'echo "[TOOL-SETUP] Relion setup complete..." && '
        )

    elif 'CTFFind' in protocol_name or 'Cistem' in protocol_name:
        cmd += (
            'echo "[TOOL-SETUP] Setting up ctffind..." && '
            'mkdir -p /opt/scipion/software/em/ctffind-5.0.2/bin && '
            'cp /usr/local/bin/ctffind /opt/scipion/software/em/ctffind-5.0.2/bin/ctffind && '
            'mkdir -p /opt/scipion/software/em/cistem-1.0.0-beta/bin && '
            'ln -sf /opt/scipion/software/em/ctffind-5.0.2/bin/ctffind '
            '   /opt/scipion/software/em/cistem-1.0.0-beta/bin/ctffind && '
            'echo "[TOOL-SETUP] Ctffind setup completed" && '
        )

    elif 'Gctf' in protocol_name:
        cmd += (
            'echo "[TOOL-SETUP] Setting up Gctf environment..." && '
            "printf '#!/bin/bash\\nexit 0\\n' > /usr/local/bin/conda && "
            'chmod +x /usr/local/bin/conda && '
            'ln -sf /usr/local/bin/gctf /usr/local/bin/Gctf_v1.18_sm30-75_cu10.1 && '
            'ln -sf /usr/local/bin/gctf /usr/local/bin/Gctf_v1.18_sm30_cu8.0 && '
            '/opt/scipion/.scipion3/bin/pip install --no-deps --force-reinstall scipion-em-gctf 2>&1 | tail -3 && '
            'if [ ! -d /opt/scipion/software/em/gctf-1.18 ]; then '
            '  mkdir -p /opt/scipion/software/em/gctf-1.18/bin && '
            '  ln -sf /usr/local/bin/gctf /opt/scipion/software/em/gctf-1.18/bin/Gctf_v1.18_sm30_cu8.0 && '
            '  ln -sf /usr/local/bin/gctf /opt/scipion/software/em/gctf-1.18/bin/Gctf_v1.18_sm30-75_cu10.1 && '
            '  echo "[TOOL-SETUP] Created GCTF_HOME symlinks..."; '
            'fi && '
            'export CONDA_PREFIX=/usr/local/cuda && '
            'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/local/cuda/lib:/usr/lib/x86_64-linux-gnu:${LD_LIBRARY_PATH} && '
            'echo "[TOOL-SETUP] Gctf setup completed" && '
        )

    return cmd
