#!/usr/bin/env python3
"""
Setup examples
==============

Auto-setup Scipion example projects on container start.

Creates example projects from bundled pipeline JSON definitions.
Each project demonstrates a different subset of the available cryo-EM
tools. All protocols are pre-configured for Kubernetes queue execution.

To disable a project, set `enabled=False` in the `EXAMPLE_PROJECTS`
registry below.  Only projects with `enabled=True` are created!
"""

import json
import os
import sys
import tempfile
import traceback

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyworkflow as pw  # type: ignore
from pyworkflow.project import Manager  # type: ignore


SCIPION_HOME: str = os.environ.get('SCIPION_HOME', '/opt/scipion')
SCIPION_USER_DATA: Path = Path(
    os.environ.get('SCIPION_USER_DATA', '/home/scipion/ScipionUserData')
)

EMPIAR_CANDIDATES: list[Path] = [
    Path('/projects') / 'EMPIAR',
    Path('/data') / 'EMPIAR',
    SCIPION_USER_DATA / 'EMPIAR',
    SCIPION_USER_DATA / 'projects' / 'Example' / 'EMPIAR',
    SCIPION_USER_DATA / 'projects' / 'Example_10248_Scipion3' / 'EMPIAR',
]

PIPELINE_DIR: Path = Path('/opt/startup/pipelines')


@dataclass
class ExampleProject:
    """Single example project definition."""

    name: str
    """Unique project name (must not already exist in Scipion)"""

    pipeline_json: str
    """Filename of the bundled pipeline JSON definition (in PIPELINE_DIR)"""

    description: str
    """Description of the example project"""

    enabled: bool = field(default=True)
    """Whether the example project is enabled"""


EXAMPLE_PROJECTS: list[ExampleProject] = [
    ExampleProject(
        name='Example_QuickValidation',
        pipeline_json='pipeline_D_quick_validation.json',
        description='Quick validation (5 steps): import -> gain -> align -> maxshift -> CTF',
        enabled=True,
    ),
    ExampleProject(
        name='Example_FullSPA',
        pipeline_json='pipeline_A_comprehensive.json',
        description='Full SPA (10 steps): preprocessing -> CTF -> picking -> extraction -> 2D class',
        enabled=True,
    ),
    ExampleProject(
        name='Example_AlternativeSPA',
        pipeline_json='pipeline_C_alternative.json',
        description='Alternative SPA (9 steps): preprocessing -> CTF -> picking -> extract -> CL2D',
        enabled=True,
    ),
    ExampleProject(
        name='Example_Direct2D',
        pipeline_json='pipeline_E_direct_2d.json',
        description='Direct 2D (8 steps): preprocessing -> CTF -> picking -> extraction -> 2D class',
        enabled=True,
    ),
    ExampleProject(
        name='Example_CTFAnalysis',
        pipeline_json='pipeline_F_ctf_analysis.json',
        description='CTF Analysis (7 steps): preprocessing -> CTFFind + Xmipp CTF -> consensus',
        enabled=True,
    ),
    ExampleProject(
        name='Example_FullReconstruction',
        pipeline_json='pipeline_G_full_reconstruction.json',
        description='Full Reconstruction (11 steps): preprocessing -> CTF -> picking -> 2D -> 3D init',
        enabled=True,
    ),
    ExampleProject(
        name='Example_3DClassification',
        pipeline_json='pipeline_H_3d_classification.json',
        description='3D Classification (12 steps): full SPA -> 3D init -> Relion 3D classification',
        enabled=True,
    ),
    ExampleProject(
        name='Example_ReconSignificant',
        pipeline_json='pipeline_I_recon_significant.json',
        description='Reconstruct Significant (10 steps): preprocessing -> CTF -> picking -> Xmipp recon',
        enabled=True,
    ),
    ExampleProject(
        name='Example_MinimalSPA',
        pipeline_json='pipeline_J_minimal_spa.json',
        description='Minimal SPA (6 steps): import -> align -> CTF -> pick -> extract -> 2D class',
        enabled=True,
    ),
    ExampleProject(
        name='Example_3DRefinement',
        pipeline_json='pipeline_K_3d_refinement.json',
        description='3D Refinement (15 steps): SPA -> 3D classify -> Refine3D -> mask -> postprocess',
        enabled=True,
    ),
    ExampleProject(
        name='Example_RelionWorkflow',
        pipeline_json='pipeline_L_relion_workflow.json',
        description='Relion Workflow (11 steps): extract -> preprocess -> 2D -> init model -> reconstruct',
        enabled=True,
    ),
    ExampleProject(
        name='Example_ParticleScreening',
        pipeline_json='pipeline_M_particle_screening.json',
        description='Particle Screening (12 steps): dedup -> eliminate empty -> screen -> 2D -> center',
        enabled=True,
    ),
    ExampleProject(
        name='Example_VolumeAnalysis',
        pipeline_json='pipeline_N_volume_analysis.json',
        description='Volume Analysis (15 steps): SPA -> mask -> crop/resize -> MonoRes -> LocalDeblur',
        enabled=True,
    ),
    ExampleProject(
        name='Example_CistemValidation',
        pipeline_json='pipeline_O_cistem_validation.json',
        description='Cistem Validation (10 steps): Cistem 2D refine -> init model -> compare reproj',
        enabled=True,
    ),
]


def log(msg: str) -> None:
    """Log a message with a consistent prefix and flush immediately."""

    print(f'[SETUP] {msg}', flush=True)


def find_empiar_dir() -> Path | None:
    """Return the first EMPIAR candidate directory that contains TIFF files."""

    for candidate in EMPIAR_CANDIDATES:
        if candidate.exists() and any(candidate.glob('*.tiff')):
            return candidate

    return None


def patch_workflow_paths(
    workflow: list[dict[str, Any]], empiar_dir: Path
) -> list[dict[str, Any]]:
    """Rewrite `filesPath` and `gainFile` entries to point at empiar_dir."""

    for protocol in workflow:
        if 'filesPath' in protocol:
            protocol['filesPath'] = str(empiar_dir) + '/'

        if 'gainFile' in protocol:
            protocol['gainFile'] = str(empiar_dir / 'gain.mrc')

    return workflow


def verify_scipion_config() -> None:
    """Log whether the required Scipion configuration files are present."""

    config_dir = Path.home() / '.config' / 'scipion'
    for name in ('scipion.conf', 'hosts.conf'):
        path = config_dir / name

        if path.exists():
            log(f'Config OK: {path}')
        else:
            log(f'Warning: {path} not found')


def create_project(
    manager: Any, project: ExampleProject, empiar_dir: Path
) -> bool:
    """Create a single Scipion project from a pipeline JSON."""

    if manager.hasProject(project.name):
        log(f"'{project.name}' already exists - skipping")
        return True

    json_path = PIPELINE_DIR / project.pipeline_json
    if not json_path.exists():
        log(f'Pipeline JSON not found: {json_path}')
        return False

    try:
        with open(json_path, encoding='utf-8') as fh:
            workflow: list[dict[str, Any]] = json.load(fh)
        patch_workflow_paths(workflow, empiar_dir)

        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.json', delete=False
        ) as tmp:
            json.dump(workflow, tmp, indent=2)
            tmp_path = tmp.name

        try:
            proj = manager.createProject(project.name)
            prot_dict = proj.loadProtocols(tmp_path)
            proj.mapper.commit()
            log(
                f"Created '{project.name}': "
                f'{len(prot_dict)} protocols - {project.description}'
            )
        finally:
            os.unlink(tmp_path)

        return True
    except Exception as exc:
        log(f"Failed to create '{project.name}': {exc}")
        traceback.print_exc()

        return False


def main() -> int:
    log('Starting Scipion Example Projects auto setup.')

    force = '--force' in sys.argv

    (SCIPION_USER_DATA / 'projects').mkdir(parents=True, exist_ok=True)
    verify_scipion_config()

    empiar_dir = find_empiar_dir()
    if empiar_dir is None:
        if force:
            empiar_dir = Path('/projects/EMPIAR')
            empiar_dir.mkdir(parents=True, exist_ok=True)

            log('EMPIAR data not found - using placeholder paths (--force)')
        else:
            log('EMPIAR data not found - skipping project creation')
            log(f'Searched: {[str(d) for d in EMPIAR_CANDIDATES]}')

            return 0
    else:
        log(f'EMPIAR data found: {empiar_dir}')

    projects = [p for p in EXAMPLE_PROJECTS if p.enabled]
    if not projects:
        log('All projects are disabled - nothing to do')
        return 0

    log(f'Creating {len(projects)} project(s) ({len(EXAMPLE_PROJECTS) - len(projects)} disabled)...')

    pw.Config.setDomain('pwem')
    manager = Manager()

    ok_count = sum(
        1
        for proj in projects
        if create_project(manager, proj, empiar_dir)
    )

    log(f'Setup complete: {ok_count}/{len(projects)} projects created.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
