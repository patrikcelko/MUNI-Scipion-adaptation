"""
Utility helpers
===============
"""

import time
from types import SimpleNamespace
from typing import Any

from controller.utilities import (
    K8S_NAME_RE,
    age,
    is_safe_path,
    is_valid_k8s_name,
    job_phase,
    load_yaml,
    parse_cpu,
    parse_mem,
    resolve_job_name,
)


def _make_job(succeeded: int = 0, failed: int = 0, active: int = 0) -> SimpleNamespace:
    """Build a minimal Job-like object with the given status counters."""

    return SimpleNamespace(status=SimpleNamespace(succeeded=succeeded, failed=failed, active=active))


def test_load_yaml_loads_list_yaml(tmp_path: Any) -> None:
    """Loads a YAML list file."""

    f = tmp_path / 'tools.yaml'
    f.write_text('- name: relion\n  image: relion:latest\n')
    result = load_yaml(str(f))

    assert isinstance(result, list)
    assert result[0]['name'] == 'relion'


def test_load_yaml_loads_dict_yaml(tmp_path: Any) -> None:
    """Loads a YAML dict file."""

    f = tmp_path / 'config.yaml'
    f.write_text('key: value\n')
    assert load_yaml(str(f)) == {'key': 'value'}


def test_load_yaml_returns_none_for_missing_file() -> None:
    """Returns None for missing file."""

    assert load_yaml('/nonexistent/file.yaml') is None


def test_load_yaml_returns_empty_dict_for_empty_file(tmp_path: Any) -> None:
    """Returns {} for empty file."""

    f = tmp_path / 'empty.yaml'
    f.write_text('')

    assert load_yaml(str(f)) == {}


def test_load_yaml_loads_nested_yaml(tmp_path: Any) -> None:
    """Loads nested YAML."""

    f = tmp_path / 'nested.yaml'
    f.write_text('a:\n  b:\n    c: 42\n')
    result = load_yaml(str(f))

    assert result == {'a': {'b': {'c': 42}}}


def test_load_yaml_loads_multiline_string(tmp_path: Any) -> None:
    """Loads multiline string YAML."""

    f = tmp_path / 'multi.yaml'
    f.write_text('desc: |\n  line1\n  line2\n')
    result = load_yaml(str(f))

    assert isinstance(result, dict)
    assert 'line1' in result['desc']


def test_age_seconds() -> None:
    """30s ago; result ends with 's', val 29-31."""

    ts = SimpleNamespace(timestamp=lambda: time.time() - 30)
    result = age(ts)  # type: ignore
    assert result.endswith('s')
    val = int(result.rstrip('s'))
    assert 29 <= val <= 31


def test_age_minutes() -> None:
    """125s ago; starts with '2m', ends with 's'."""

    ts = SimpleNamespace(timestamp=lambda: time.time() - 125)
    result = age(ts)  # type: ignore
    assert result.startswith('2m')
    assert result.endswith('s')


def test_age_hours() -> None:
    """7260s ago; starts with '2h'."""

    ts = SimpleNamespace(timestamp=lambda: time.time() - 7260)
    result = age(ts)  # type: ignore
    assert result.startswith('2h')


def test_age_none_returns_dash() -> None:
    """age(None) == '-'."""

    assert age(None) == '-'


def test_age_zero_returns_dash() -> None:
    """age(0) == '-'."""

    assert age(0) == '-'  # type: ignore


def test_age_exactly_60_seconds() -> None:
    """60s; '59s' or 'm' in result."""

    ts = SimpleNamespace(timestamp=lambda: time.time() - 60)
    result = age(ts)  # type: ignore

    assert result == '59s' or 'm' in result


def test_age_exactly_3600_seconds() -> None:
    """3600s; '59m59s' or 'h' in result."""

    ts = SimpleNamespace(timestamp=lambda: time.time() - 3600)
    result = age(ts)  # type: ignore

    assert result == '59m59s' or 'h' in result


def test_parse_cpu_millicores() -> None:
    """parse_cpu('250m') == 250.0."""

    assert parse_cpu('250m') == 250.0


def test_parse_cpu_whole_cores() -> None:
    """parse_cpu('2') == 2000.0."""

    assert parse_cpu('2') == 2000.0


def test_parse_cpu_nanocores() -> None:
    """parse_cpu('500000000n') == 500.0."""

    assert parse_cpu('500000000n') == 500.0


def test_parse_cpu_microcores() -> None:
    """parse_cpu('500000u') == 500.0."""

    assert parse_cpu('500000u') == 500.0


def test_parse_cpu_empty_string() -> None:
    """parse_cpu('') == 0.0."""

    assert parse_cpu('') == 0.0


def test_parse_cpu_fractional_core() -> None:
    """parse_cpu('0.5') == 500.0."""

    assert parse_cpu('0.5') == 500.0


def test_parse_cpu_one_millicore() -> None:
    """parse_cpu('1m') == 1.0."""

    assert parse_cpu('1m') == 1.0


def test_parse_cpu_large_nanocores() -> None:
    """parse_cpu('1000000000n') == 1000.0."""

    assert parse_cpu('1000000000n') == 1000.0


def test_parse_mem_mebibytes() -> None:
    """parse_mem('512Mi') == 512.0."""

    assert parse_mem('512Mi') == 512.0


def test_parse_mem_gibibytes() -> None:
    """parse_mem('2Gi') == 2048.0."""

    assert parse_mem('2Gi') == 2048.0


def test_parse_mem_kibibytes() -> None:
    """parse_mem('1024Ki') ≈ 1.0."""

    assert abs(parse_mem('1024Ki') - 1.0) < 0.01


def test_parse_mem_tebibytes() -> None:
    """parse_mem('1Ti') == 1024*1024."""

    assert parse_mem('1Ti') == 1024 * 1024


def test_parse_mem_bytes() -> None:
    """parse_mem('1048576') ≈ 1.0."""

    assert abs(parse_mem('1048576') - 1.0) < 0.01


def test_parse_mem_empty_string() -> None:
    """parse_mem('') == 0.0."""

    assert parse_mem('') == 0.0


def test_parse_mem_decimal_megabytes() -> None:
    """parse_mem('1M') > 0."""

    result = parse_mem('1M')
    assert result > 0


def test_parse_mem_gigabytes() -> None:
    """parse_mem('1G') > 900."""

    result = parse_mem('1G')
    assert result > 900  # ~976 MiB


def test_job_phase_done() -> None:
    """job_phase(succeeded=1) == 'DONE'."""

    assert job_phase(_make_job(succeeded=1)) == 'DONE'


def test_job_phase_failed() -> None:
    """job_phase(failed=1, active=0) == 'FAILED'."""

    assert job_phase(_make_job(failed=1, active=0)) == 'FAILED'


def test_job_phase_running() -> None:
    """job_phase(active=1) == 'RUNNING'."""

    assert job_phase(_make_job(active=1)) == 'RUNNING'


def test_job_phase_no_status() -> None:
    """job.status=None -> 'RUNNING'."""

    job = SimpleNamespace(status=None)
    assert job_phase(job) == 'RUNNING'


def test_job_phase_all_zero() -> None:
    """All zero -> 'RUNNING'."""

    assert job_phase(_make_job()) == 'RUNNING'


def test_job_phase_succeeded_takes_precedence() -> None:
    """If both succeeded and failed are set, succeeded wins."""

    assert job_phase(_make_job(succeeded=1, failed=1)) == 'DONE'


def test_resolve_job_name_already_prefixed() -> None:
    """'scipion-job-12345' unchanged."""

    assert resolve_job_name('scipion-job-12345') == 'scipion-job-12345'


def test_resolve_job_name_plain_number() -> None:
    """'12345' -> 'scipion-job-12345'."""

    assert resolve_job_name('12345') == 'scipion-job-12345'


def test_resolve_job_name_handles_string_id() -> None:
    """'99999' -> 'scipion-job-99999'."""

    assert resolve_job_name('99999') == 'scipion-job-99999'


def test_is_valid_k8s_name_valid_simple() -> None:
    """'my-pod' -> True."""

    assert is_valid_k8s_name('my-pod') is True


def test_is_valid_k8s_name_valid_with_numbers() -> None:
    """'scipion-job-12345' -> True."""

    assert is_valid_k8s_name('scipion-job-12345') is True


def test_is_valid_k8s_name_invalid_uppercase() -> None:
    """'INVALID' -> False."""

    assert is_valid_k8s_name('INVALID') is False


def test_is_valid_k8s_name_invalid_special_chars() -> None:
    """'pod;rm' -> False."""

    assert is_valid_k8s_name('pod;rm') is False


def test_is_valid_k8s_name_invalid_spaces() -> None:
    """'pod name' -> False."""

    assert is_valid_k8s_name('pod name') is False


def test_is_valid_k8s_name_invalid_starts_with_hyphen() -> None:
    """'-leading' -> False."""

    assert is_valid_k8s_name('-leading') is False


def test_is_valid_k8s_name_invalid_ends_with_hyphen() -> None:
    """'trailing-' -> False."""

    assert is_valid_k8s_name('trailing-') is False


def test_is_valid_k8s_name_valid_single_char() -> None:
    """'a' -> True."""

    assert is_valid_k8s_name('a') is True


def test_is_valid_k8s_name_empty_string() -> None:
    """'' -> False."""

    assert is_valid_k8s_name('') is False


def test_is_valid_k8s_name_path_traversal() -> None:
    """'../etc/passwd' -> False."""

    assert is_valid_k8s_name('../etc/passwd') is False


def test_is_valid_k8s_name_command_injection() -> None:
    """'pod$(whoami)' -> False."""

    assert is_valid_k8s_name('pod$(whoami)') is False


def test_is_valid_k8s_name_regex_pattern_matches() -> None:
    """K8S_NAME_RE matches valid names, rejects invalid ones."""

    assert K8S_NAME_RE.match('valid-name-123') is not None
    assert K8S_NAME_RE.match('INVALID') is None


def test_is_safe_path_normal_path() -> None:
    """'/projects' -> True."""

    assert is_safe_path('/projects') is True


def test_is_safe_path_nested_path() -> None:
    """'/projects/my-project/Runs/000001' -> True."""

    assert is_safe_path('/projects/my-project/Runs/000001') is True


def test_is_safe_path_shell_injection_semicolon() -> None:
    """'/projects; rm -rf /' -> False."""

    assert is_safe_path('/projects; rm -rf /') is False


def test_is_safe_path_shell_injection_backtick() -> None:
    """'/projects/`whoami`' -> False."""

    assert is_safe_path('/projects/`whoami`') is False


def test_is_safe_path_shell_injection_dollar() -> None:
    """'/projects/$(id)' -> False."""

    assert is_safe_path('/projects/$(id)') is False


def test_is_safe_path_shell_injection_pipe() -> None:
    """'/projects | cat /etc/passwd' -> False."""

    assert is_safe_path('/projects | cat /etc/passwd') is False


def test_is_safe_path_shell_injection_ampersand() -> None:
    """'/projects && echo pwned' -> False."""

    assert is_safe_path('/projects && echo pwned') is False


def test_is_safe_path_shell_injection_double_quote() -> None:
    """Shell injection via double quote -> False."""

    assert is_safe_path('/projects"; rm -rf /; echo "') is False


def test_is_safe_path_path_traversal() -> None:
    """'/projects/../etc/passwd' -> False."""

    assert is_safe_path('/projects/../etc/passwd') is False


def test_is_safe_path_empty_string() -> None:
    """'' -> False."""

    assert is_safe_path('') is False


def test_is_safe_path_dot_in_path() -> None:
    """'/projects/my.project' -> True."""

    assert is_safe_path('/projects/my.project') is True


def test_is_safe_path_hyphen_in_path() -> None:
    """'/projects/my-project' -> True."""

    assert is_safe_path('/projects/my-project') is True


def test_is_safe_path_underscore_in_path() -> None:
    """'/projects/my_project' -> True."""

    assert is_safe_path('/projects/my_project') is True


def test_age_future_timestamp_future_timestamp_returns_zero() -> None:
    """ts=time.time()+600 -> '0s'."""

    ts = SimpleNamespace(timestamp=lambda: time.time() + 600)
    assert age(ts) == '0s'  # type: ignore


def test_age_future_timestamp_slightly_future_returns_zero() -> None:
    """ts=time.time()+1 -> '0s'."""

    ts = SimpleNamespace(timestamp=lambda: time.time() + 1)
    assert age(ts) == '0s'  # type: ignore


def test_parse_mem_g_suffix_1g_is_approximately_953_mib() -> None:
    """parse_mem('1G') ≈ 953.674 MiB."""

    result = parse_mem('1G')
    expected = 1_000_000_000 / (1024 * 1024)  # 953.674 MiB

    assert abs(result - expected) < 0.01


def test_parse_mem_g_suffix_2g_is_approximately_1907_mib() -> None:
    """parse_mem('2G') ≈ 1907.348 MiB."""

    result = parse_mem('2G')
    expected = 2_000_000_000 / (1024 * 1024)

    assert abs(result - expected) < 0.01


def test_load_yaml_oserror_permission_denied_returns_none(tmp_path: Any) -> None:
    """chmod 0o000, load_yaml -> None."""

    f = tmp_path / 'secret.yaml'
    f.write_text('key: val')
    f.chmod(0o000)

    try:
        result = load_yaml(str(f))
        assert result is None
    finally:
        f.chmod(0o644)


def test_k8s_name_max_length_63_chars_valid() -> None:
    """'a'*63 -> True."""

    name = 'a' * 63
    assert is_valid_k8s_name(name) is True


def test_k8s_name_max_length_64_chars_rejected() -> None:
    """'a'*64 -> False."""

    name = 'a' * 64
    assert is_valid_k8s_name(name) is False


def test_parse_cpu_garbage_alpha_string() -> None:
    """parse_cpu('abc') == 0.0."""

    assert parse_cpu('abc') == 0.0


def test_parse_cpu_garbage_nan_string() -> None:
    """parse_cpu('NaN') == 0.0."""

    assert parse_cpu('NaN') == 0.0


def test_parse_cpu_garbage_special_chars() -> None:
    """parse_cpu('--') == 0.0."""

    assert parse_cpu('--') == 0.0


def test_parse_cpu_garbage_none_coerced() -> None:
    """parse_cpu(None) == 0.0."""

    assert parse_cpu(None) == 0.0  # type: ignore


def test_parse_mem_garbage_alpha_string() -> None:
    """parse_mem('abc') == 0.0."""

    assert parse_mem('abc') == 0.0


def test_parse_mem_garbage_unknown_suffix() -> None:
    """parse_mem('1E') > 0 (E is now a valid suffix)."""

    assert parse_mem('1E') > 0


def test_parse_mem_garbage_invalid_suffix_combo() -> None:
    """parse_mem('fooGi') == 0.0."""

    assert parse_mem('fooGi') == 0.0


def test_parse_mem_garbage_nan_string() -> None:
    """parse_mem('NaN') == 0.0."""

    assert parse_mem('NaN') == 0.0


def test_parse_mem_garbage_none_coerced() -> None:
    """parse_mem(None) == 0.0."""

    assert parse_mem(None) == 0.0  # type: ignore


def test_parse_mem_new_suffixes_exbibytes() -> None:
    """parse_mem('1Ei') == 1024**4."""

    result = parse_mem('1Ei')
    assert result == 1024**4


def test_parse_mem_new_suffixes_pebibytes() -> None:
    """parse_mem('1Pi') == 1024**3."""

    result = parse_mem('1Pi')
    assert result == 1024**3


def test_parse_mem_new_suffixes_terabytes() -> None:
    """parse_mem('1T') ≈ 1_000_000_000_000 / (1024*1024)."""

    result = parse_mem('1T')
    expected = 1_000_000_000_000 / (1024 * 1024)
    assert abs(result - expected) < 0.01


def test_parse_mem_new_suffixes_petabytes() -> None:
    """parse_mem('1P') ≈ 1_000_000_000_000_000 / (1024*1024)."""

    result = parse_mem('1P')
    expected = 1_000_000_000_000_000 / (1024 * 1024)
    assert abs(result - expected) < 0.01


def test_parse_mem_new_suffixes_exabytes() -> None:
    """parse_mem('1E') ≈ 1_000_000_000_000_000_000 / (1024*1024)."""

    result = parse_mem('1E')
    expected = 1_000_000_000_000_000_000 / (1024 * 1024)
    assert abs(result - expected) < 0.01
