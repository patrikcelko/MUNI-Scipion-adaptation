#!/usr/bin/env bash

# Relion Wrapper for Scipion Protocol Execution in Kubernetes
#
# Entrypoint wrapper that sets up the environment and dispatches the
# command.

set -euo pipefail

SCIPION_HOME="${SCIPION_HOME:-/opt/scipion}"
export SCIPION_HOME
export PATH="${SCIPION_HOME}:${PATH}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >&2; }

log "Executing: $*"

# Scipion protocol runs contain "pw_protocol_run" in the command line.
if [[ "$*" == *pw_protocol_run* ]]; then
  log "Detected Scipion protocol execution"
  exec "${SCIPION_HOME}/scipion3" "$@"
fi

log "Direct Relion execution"
exec "$@"
