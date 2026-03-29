#!/usr/bin/env bash

# Scipion Task Submission Bridge
#
# Replaces qsub/qstat/qdel with HTTP calls to the Controller REST API.
# Scipion -> task-submit.sh -> Controller -> Job Pod
#
# DEBUG: export TASK_SUBMIT_DEBUG=1

set -Eeuo pipefail

CTRL_URL="${CTRL_URL:-http://scipion-controller:5000}"
HTTP_TIMEOUT="${HTTP_TIMEOUT:-30}"
GPUS_DEFAULT="${GPUS:-0}"
HOURS_DEFAULT="${HOURS:-2}"
MEM_MB_DEFAULT="${MEM_MB:-4096}"

# Scipion places job scripts at <project>/Runs/<run_id>/tmp/run.job.
# Walk up from the script directory to reach the project root.
PROJECT_DEPTH="${PROJECT_DEPTH:-3}"

has_cmd() { command -v "$1" >/dev/null 2>&1; }

http_request() {
  local method="$1" url="$2" payload="${3:-}"

  if has_cmd curl; then
    if [[ "$method" == "POST" ]]; then
      curl -fsS --connect-timeout "$HTTP_TIMEOUT" --max-time "$HTTP_TIMEOUT" \
        -H "Content-Type: application/json" -d "$payload" "$url"
    else
      curl -fsS --connect-timeout "$HTTP_TIMEOUT" --max-time "$HTTP_TIMEOUT" "$url"
    fi
  elif has_cmd wget; then
    if [[ "$method" == "POST" ]]; then
      wget -qO- -T "$HTTP_TIMEOUT" \
        --header="Content-Type: application/json" --post-data="$payload" "$url"
    else
      wget -qO- -T "$HTTP_TIMEOUT" "$url"
    fi
  else
    echo "ERROR: neither 'curl' nor 'wget' found" >&2
    return 127
  fi
}

debug() {
  if [[ "${TASK_SUBMIT_DEBUG:-0}" == "1" ]]; then echo "[DEBUG] $*" >&2; fi
}

# Escape a string for safe embedding in a JSON value.
# Handles: \ " tab carriage-return newline
json_escape() {
  sed -e 's/\\/\\\\/g' \
      -e 's/"/\\"/g' \
      -e 's/\t/\\t/g' \
      -e 's/\r/\\r/g' \
    <<< "$1" \
  | awk '{ if (NR>1) printf "\\n"; printf "%s", $0 }'
}

# Symlink-based dispatch: qsub -> submit, qstat -> status, qdel -> cancel
prog="$(basename "${0}")"
action=""

case "${prog}" in
  qsub)  action="submit" ;;
  qstat) action="status" ;;
  qdel)  action="cancel" ;;
  *)
    action="${1:-}"
    shift || true
    ;;
esac

submit() {
  local job_script="${1:-}"
  local gpus="${2:-${GPUS_DEFAULT}}"
  local hours="${3:-${HOURS_DEFAULT}}"
  local mem_mb="${4:-${MEM_MB_DEFAULT}}"

  if [[ -z "$job_script" ]]; then
    echo "Usage: $0 submit <job_script> [gpus] [hours] [mem_mb]" >&2
    exit 2
  fi
  if [[ ! -r "$job_script" ]]; then
    echo "ERROR: job script '$job_script' not readable" >&2
    exit 2
  fi

  # Navigate PROJECT_DEPTH levels up from the job script directory
  local depth_path="."
  for (( i = 0; i < PROJECT_DEPTH; i++ )); do
    depth_path="${depth_path}/.."
  done

  local project_root cwd_at_submit original_cmd
  project_root="$(cd "$(dirname "$job_script")/${depth_path}" && pwd -P)"
  cwd_at_submit="$(pwd -P)"

  original_cmd="$(
    sed -e 's/\r$//' -e '/^[[:space:]]*#/d' -e '/^[[:space:]]*$/d' "$job_script" | tail -n1 || true
  )"
  if [[ -z "$original_cmd" ]]; then
    echo "ERROR: '$job_script' contains no non-comment command line." >&2
    exit 2
  fi

  local escaped_cmd prefer_node instance_ns
  escaped_cmd="$(json_escape "$original_cmd")"
  prefer_node="$(json_escape "${MY_NODE_NAME:-}")"
  project_root="$(json_escape "$project_root")"
  cwd_at_submit="$(json_escape "$cwd_at_submit")"

  if [[ -r /var/run/secrets/kubernetes.io/serviceaccount/namespace ]]; then
    instance_ns="$(json_escape "$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)")"
  else
    instance_ns="default"
  fi

  local payload
  payload="$(cat <<EOF
{
  "projectRoot":"${project_root}",
  "cwd":"${cwd_at_submit}",
  "originalCmd":"${escaped_cmd}",
  "resources":{"gpus":${gpus},"hours":${hours},"memoryMb":${mem_mb}},
  "preferNode":"${prefer_node}",
  "instance":"${instance_ns}"
}
EOF
)"
  debug "CTRL_URL=${CTRL_URL}"
  debug "Payload: ${payload}"

  local response
  response="$(http_request POST "${CTRL_URL}/submit" "${payload}")"
  debug "Response: ${response}"

  # Extract the numeric job ID for Scipion (it parses first \d+ from stdout)
  local job_number
  job_number="$(sed -n 's/.*"jobNumber"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' <<< "$response")"
  if [[ -z "$job_number" ]]; then
    # Fallback: extract first number from response
    job_number="$(grep -oP '\d{10,}' <<< "$response" | head -1)"
  fi

  if [[ -n "$job_number" ]]; then
    echo "$job_number"
  else
    echo "ERROR: could not parse job number from controller response" >&2
    echo "$response" >&2
    exit 1
  fi
}

cancel() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "Usage: $0 cancel <job_id>" >&2
    exit 2
  fi
  # Scipion sends just the number, controller accepts both formats
  local response
  if ! response="$(http_request POST "${CTRL_URL}/cancel/${id}" "{}")"; then
    echo "ERROR: cancel request failed for job '$id'" >&2
    [[ -n "$response" ]] && echo "$response" >&2
    exit 1
  fi
  debug "Cancel response: ${response}"
}

status() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "Usage: $0 status <job_id>" >&2
    exit 2
  fi
  # Scipion sends just the number, but controller resolves to scipion-job-<id>
  # Returns empty string when done (Scipion expects this), "RUNNING" otherwise.
  # On network error, report RUNNING so Scipion keeps polling instead of
  # treating a transient failure as "job finished".
  local response
  if ! response="$(http_request GET "${CTRL_URL}/status/${id}")"; then
    debug "Status request failed for job '$id', reporting RUNNING"
    echo "RUNNING"
    return 0
  fi
  echo "$response"
}

case "${action}" in
  submit) submit "${1:-}" "${2:-}" "${3:-}" "${4:-}" ;;
  cancel) cancel "${1:-}" ;;
  status) status "${1:-}" ;;
  *)
    cat >&2 <<'USAGE'
Usage:
  task-submit.sh submit <job_script> [gpus] [hours] [mem_mb]
  task-submit.sh cancel <job_id>
  task-submit.sh status <job_id>
Or use via symlinks: qsub, qstat, qdel
USAGE
    exit 2 ;;
esac
