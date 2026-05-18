"""
Dispatcher schemas
==================
"""

from pydantic import BaseModel, Field


class ImportWorkflowResponse(BaseModel):
    """`POST /import_workflow` - successful import result."""

    ok: bool = Field(
        ...,
        description='Always `True` on success (errors use JSONResponse).',
    )
    """On failure the endpoint returns a plain `JSONResponse` with
    `ok=False` and an `error` field instead of this model.
    """

    project_name: str = Field(
        ...,
        description='Filesystem-safe project name (alphanumeric + _ -, max 64 chars).',
    )
    """Sanitised from the request body or defaults to `'DispatcherProject'`."""

    protocols_count: int = Field(
        ...,
        description='Number of protocol objects in the imported workflow.',
    )
    """Equal to `len(workflow_json)` where the root must be a JSON list."""

    workflow_path: str = Field(
        ...,
        description='Absolute path where the workflow JSON was saved.',
    )
    """Pattern: `{base}/.dispatcher_workflows/{project_name}.json`."""

    inputs_path: str | None = Field(
        default=None,
        description='Absolute path where input_files metadata was saved, or null if none provided.',
    )
    """Pattern: `{base}/.dispatcher_workflows/{project_name}_inputs.json`. Null when
    the request contained no `input_files` list.
    """

    vnc_url: str = Field(
        ...,
        description='HTTP URL for VNC GUI access to the Scipion desktop.',
    )
    """Format: `http://{host}:{port}/vnc.html`. Host and port come exclusively
    from the `VNC_HOST` / `VNC_PORT` environment variables
    """
