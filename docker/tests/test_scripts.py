"""
Shell script tests
==================

Validates every shell script shipped in `docker/`.
"""

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from conftest import ALL_SCRIPTS, DOCKER_DIR, SCRIPTS_DIR

_SHELLCHECK: str | None = shutil.which('shellcheck')
_TASK_SUBMIT: Path = SCRIPTS_DIR / 'task-submit.sh'
_ENTRYPOINT: Path = SCRIPTS_DIR / 'entrypoint.sh'


# Mock that returns a valid controller response and logs the payload to stderr.
_SUBMIT_MOCK = textwrap.dedent("""\
    http_request() {
        echo "$3" >&2
        echo '{"jobNumber": "1234567890"}'
        return 0
    }
""")


def _run_task_submit_func(
    snippet: str,
    *,
    timeout: int = 10,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Source `task-submit.sh` function defs and execute snippet."""

    script_text = _TASK_SUBMIT.read_text()
    end = script_text.find('\ncase "${action}"')
    if end == -1:
        end = script_text.find('\ncase "${action}"')
    assert end > 0, 'Could not find dispatch block in task-submit.sh'

    preamble = script_text[:end].replace('set -Eeuo pipefail', 'set -euo pipefail', 1)

    run_env: dict[str, str] | None = None
    if env is not None:
        run_env = {**os.environ, **env}

    return subprocess.run(
        ['bash', '-c', preamble + '\n' + snippet],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )


def _run_entrypoint_func(
    snippet: str,
    *,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Source pure functions from `entrypoint.sh` and execute snippet."""

    lines = _ENTRYPOINT.read_text().splitlines()

    # Extract everything up to and including the closing "}" of install_config.
    preamble_lines: list[str] = []
    for line in lines:
        if line.startswith('export '):
            break
        preamble_lines.append(line)

    preamble = '\n'.join(preamble_lines)
    return subprocess.run(
        ['bash', '-c', preamble + '\n' + snippet],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _run_task_submit(
    *args: str,
    timeout: int = 10,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run `task-submit.sh` as a subprocess with args.

    NOTE: By default `CTRL_URL` is pointed at an unreachable host so the
    script exercises all local logic but cannot make real HTTP calls.
    """

    run_env = {
        **os.environ,
        'CTRL_URL': 'http://127.0.0.1:1',
        **(env or {}),
    }
    return subprocess.run(
        ['bash', str(_TASK_SUBMIT), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        env=run_env,
    )


_SCRIPT_IDS = [str(p.relative_to(DOCKER_DIR)) for p in ALL_SCRIPTS]


@pytest.mark.parametrize('script', ALL_SCRIPTS, ids=_SCRIPT_IDS)
def test_bash_syntax(script: Path) -> None:
    """`bash -n` must report zero syntax errors."""

    result = subprocess.run(
        ['bash', '-n', str(script)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f'Syntax error in {script.name}:\n{result.stderr}'


@pytest.mark.skipif(not _SHELLCHECK, reason='shellcheck not installed')
@pytest.mark.parametrize('script', ALL_SCRIPTS, ids=_SCRIPT_IDS)
def test_shellcheck(script: Path) -> None:
    """Every script must pass shellcheck with zero warnings."""

    result = subprocess.run(
        [_SHELLCHECK, str(script)],  # type: ignore
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f'shellcheck warnings in {script.name}:\n{result.stdout}'
    )


def test_json_escape_plain_string() -> None:
    """Plain string passes through unchanged."""

    r = _run_task_submit_func('echo "$(json_escape "hello world")"')
    assert r.returncode == 0
    assert r.stdout.strip() == 'hello world'


def test_json_escape_backslash() -> None:
    """Backslash is doubled: `a\b` -> `a\\b`."""

    r = _run_task_submit_func(r'echo "$(json_escape "a\\b")"')
    assert r.returncode == 0
    assert r.stdout.strip() == r'a\\b'


def test_json_escape_double_quote() -> None:
    """Double-quote is escaped: `say "hi"` -> `say \"hi\"`."""

    r = _run_task_submit_func(r'''echo "$(json_escape 'say "hi"')"''')
    assert r.returncode == 0
    assert r.stdout.strip() == r'say \"hi\"'


def test_json_escape_tab() -> None:
    """Tab character becomes literal `\t`."""

    r = _run_task_submit_func('echo "$(json_escape "$(printf \'a\\tb\')")"')
    assert r.returncode == 0
    assert r.stdout.strip() == r'a\tb'


def test_json_escape_newline() -> None:
    """Newline character becomes literal `\n`."""

    r = _run_task_submit_func("""echo "$(json_escape "$(printf 'line1\\nline2')")" """)
    assert r.returncode == 0
    assert r.stdout.strip() == r'line1\nline2'


def test_json_escape_empty() -> None:
    """Empty input produces empty output."""

    r = _run_task_submit_func('echo "$(json_escape "")"')
    assert r.returncode == 0
    assert r.stdout.strip() == ''


def test_has_cmd_returns_0_for_existing_binary() -> None:
    """`has_cmd bash` succeeds - bash is always available."""

    r = _run_task_submit_func('has_cmd bash && echo yes || echo no')
    assert r.stdout.strip() == 'yes'


def test_has_cmd_returns_nonzero_for_missing_binary() -> None:
    """`has_cmd` for a non-existent command returns non-zero."""

    r = _run_task_submit_func('has_cmd nonexistent_cmd_12345 && echo yes || echo no')
    assert r.stdout.strip() == 'no'


def test_debug_silent_when_disabled() -> None:
    """No output when `TASK_SUBMIT_DEBUG` is unset / 0."""

    r = _run_task_submit_func('TASK_SUBMIT_DEBUG=0; debug "secret"')
    assert r.returncode == 0
    assert 'secret' not in r.stderr


def test_debug_writes_to_stderr_when_enabled() -> None:
    """`[DEBUG]` prefix appears on stderr when `TASK_SUBMIT_DEBUG=1`."""

    r = _run_task_submit_func('TASK_SUBMIT_DEBUG=1; debug "visible msg"')
    assert r.returncode == 0
    assert '[DEBUG]' in r.stderr
    assert 'visible msg' in r.stderr


_DISPATCH_SNIPPET = textwrap.dedent("""\
    prog="{prog}"
    action=""
    case "${{prog}}" in
      qsub)  action="submit" ;;
      qstat) action="status" ;;
      qdel)  action="cancel" ;;
    esac
    echo "$action"
""")


@pytest.mark.parametrize(
    ('symlink', 'expected'),
    [('qsub', 'submit'), ('qstat', 'status'), ('qdel', 'cancel')],
    ids=['qsub->submit', 'qstat->status', 'qdel->cancel'],
)
def test_symlink_dispatch(symlink: str, expected: str) -> None:
    """Symlink name is resolved to the correct action verb."""

    r = _run_task_submit_func(_DISPATCH_SNIPPET.format(prog=symlink))
    assert r.stdout.strip() == expected


def test_http_timeout_defaults_to_30() -> None:
    """`HTTP_TIMEOUT` defaults to 30 when not overridden."""

    r = _run_task_submit_func('echo "$HTTP_TIMEOUT"')
    assert r.stdout.strip() == '30'


def test_http_timeout_respects_env_override() -> None:
    """`HTTP_TIMEOUT` can be overridden before sourcing."""

    r = _run_task_submit_func('echo "$HTTP_TIMEOUT"', env={'HTTP_TIMEOUT': '5'})
    assert r.stdout.strip() == '5'


def test_submit_rejects_missing_script() -> None:
    """`submit` exits 2 when the job script does not exist."""

    r = _run_task_submit('submit', '/nonexistent/path.sh')
    assert r.returncode == 2
    assert 'not readable' in r.stderr


@pytest.mark.parametrize('action', ['submit', 'cancel', 'status'])
def test_action_rejects_empty_args(action: str) -> None:
    """Every action exits 2 with usage text when called without arguments."""

    r = _run_task_submit(action)
    assert r.returncode == 2
    assert 'Usage' in r.stderr or 'usage' in r.stderr


def test_submit_extracts_last_command_from_job_script(tmp_path: Path) -> None:
    """`submit` parses the last non-comment, non-blank line as the command.

    `http_request` is overridden to return a valid controller response
    and dump the JSON payload to stderr for inspection.
    """

    job_script = tmp_path / 'Runs' / '000001' / 'tmp' / 'run.job'
    job_script.parent.mkdir(parents=True)
    job_script.write_text(
        textwrap.dedent("""\
            #!/bin/bash
            # This is a comment
            echo "ignored"
            relion_refine --o /projects/test --j 4
        """)
    )

    r = _run_task_submit_func(_SUBMIT_MOCK + f'submit "{job_script}" 0 2 4096\n')
    assert r.returncode == 0
    assert r.stdout.strip() == '1234567890'

    # The payload (on stderr) must contain the extracted command
    assert 'relion_refine' in r.stderr
    assert '--o /projects/test' in r.stderr


def test_submit_skips_comments_and_blanks_in_job_script(tmp_path: Path) -> None:
    """Only the last real command line is submitted, ignoring comments."""

    job_script = tmp_path / 'job.sh'
    job_script.write_text(
        textwrap.dedent("""\
            #!/bin/bash
            # comment 1
            # comment 2

            python3 -m my_protocol --input /data
        """)
    )

    r = _run_task_submit_func(
        _SUBMIT_MOCK + f'PROJECT_DEPTH=0\nsubmit "{job_script}" 0 1 2048\n'
    )
    assert r.returncode == 0
    assert 'my_protocol' in r.stderr

    # The extracted command field must not contain comment lines.
    assert '# comment' not in r.stderr


def test_submit_walks_up_project_depth_dirs(tmp_path: Path) -> None:
    """`submit` walks `PROJECT_DEPTH` levels up to find the project root."""

    # Simulate Scipion layout: project/Runs/000001/tmp/run.job
    run_dir = tmp_path / 'myproject' / 'Runs' / '000001' / 'tmp'
    run_dir.mkdir(parents=True)
    job_script = run_dir / 'run.job'
    job_script.write_text('relion_refine --test\n')

    r = _run_task_submit_func(
        _SUBMIT_MOCK + f'PROJECT_DEPTH=3\nsubmit "{job_script}" 0 1 1024\n'
    )
    assert r.returncode == 0

    # The payload (on stderr) must contain the resolved project root
    assert str(tmp_path / 'myproject') in r.stderr


def test_cancel_calls_correct_endpoint() -> None:
    """`cancel` POSTs to `/cancel/{id}`."""

    r = _run_task_submit_func(
        textwrap.dedent("""\
            http_request() {
                echo "METHOD=$1 URL=$2" >&2
                return 0
            }
            cancel "1234567890"
        """)
    )
    assert r.returncode == 0
    assert '/cancel/1234567890' in r.stderr


def test_status_returns_running_on_http_failure() -> None:
    """On network error `status` reports `RUNNING` to prevent false 'done'."""

    r = _run_task_submit_func(
        textwrap.dedent("""\
            http_request() { return 1; }
            status "1234567890"
        """)
    )
    assert r.returncode == 0
    assert r.stdout.strip() == 'RUNNING'


def test_status_forwards_controller_response() -> None:
    """`status` echoes whatever the controller returns."""

    r = _run_task_submit_func(
        textwrap.dedent("""\
            http_request() { echo "RUNNING"; return 0; }
            status "1234567890"
        """)
    )
    assert r.stdout.strip() == 'RUNNING'


def test_unknown_action_prints_usage() -> None:
    """An unrecognized action exits 2 with usage text."""

    r = _run_task_submit('bogus_action')
    assert r.returncode == 2
    assert 'Usage' in r.stderr or 'usage' in r.stderr


def test_install_config_copies_existing_file(tmp_path: Path) -> None:
    """`install_config` copies source to dest with mode 644."""

    src = tmp_path / 'src.conf'
    dest = tmp_path / 'dest.conf'
    src.write_text('[PYWORKFLOW]\nSCIPION_HOME = /opt/scipion\n')

    r = _run_entrypoint_func(f'install_config "{src}" "{dest}" "test config"')
    assert r.returncode == 0
    assert dest.exists()
    assert dest.read_text() == src.read_text()
    assert oct(dest.stat().st_mode & 0o777) == '0o644'


def test_install_config_skips_missing_file(tmp_path: Path) -> None:
    """`install_config` is a no-op when the source file does not exist."""

    dest = tmp_path / 'dest.conf'

    r = _run_entrypoint_func(f'install_config "/nonexistent/file" "{dest}" "missing"')
    assert r.returncode == 0
    assert not dest.exists()
