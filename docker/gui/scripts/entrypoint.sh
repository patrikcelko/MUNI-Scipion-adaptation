#!/usr/bin/env bash

# Scipion Entrypoint Script

set -Eeuo pipefail

log(){ echo "[$(date +'%H:%M:%S')] $*"; }

# Install a config file: install_config <src> <dest> <label>
install_config() {
  local src="$1" dest="$2" label="$3"
  if [ -f "${src}" ]; then
    cp "${src}" "${dest}"
    chmod 644 "${dest}"
    log "Installed ${label}"
  fi
}

export USER="${USER:-scipion}"
export HOME="/home/${USER}"
export SCIPION_USER_DATA="${HOME}/ScipionUserData"
export VNC_DISPLAY="${VNC_DISPLAY:-1}"
export VNC_GEOMETRY="${VNC_GEOMETRY:-1920x1080}"
export VNC_DEPTH="${VNC_DEPTH:-24}"
export PATH="/opt/TurboVNC/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

disp="${VNC_DISPLAY#:}"
NOVNC_PORT=$((5800 + disp))
RFB_PORT=$((5900 + disp))

mkdir -p "${HOME}" /data || true
chown -R "${USER}:${USER}" "${HOME}" /data 2>/dev/null || true

# Ensure ScipionUserData directory exists (PVC mounted here)
mkdir -p "${SCIPION_USER_DATA}" 2>/dev/null || true

# Create projects symlink: ScipionUserData/projects -> /projects
#   - PVC is mounted at /projects (subPath: projects)
#   - Project directories live directly inside /projects/
#   - Scipion expects them at ~/ScipionUserData/projects/
if [ -d "/projects" ]; then
  if [ ! -L "${SCIPION_USER_DATA}/projects" ]; then
    rm -rf "${SCIPION_USER_DATA}/projects" 2>/dev/null || true
    ln -sfn /projects "${SCIPION_USER_DATA}/projects"
    log "Linked ${SCIPION_USER_DATA}/projects -> /projects"
  fi
else
  mkdir -p "${SCIPION_USER_DATA}/projects" 2>/dev/null || true
fi

if [ -e "${HOME}/.vnc" ] && [ ! -d "${HOME}/.vnc" ]; then
  mv "${HOME}/.vnc" "${HOME}/.vnc.bak.$(date +%s)"
fi

# VNC Permissions
mkdir -p "${HOME}/.vnc"
chmod 700 "${HOME}/.vnc"
chown -R "${USER}:${USER}" "${HOME}/.vnc" 2>/dev/null || true

# Xauthority
touch "${HOME}/.Xauthority" || true
chmod 600 "${HOME}/.Xauthority" || true

# VNC password
VNC_PASSWORD="${VNC_PASSWORD:-${VNC_PASSWD:-${VNC_SECRET_PASSWORD:-}}}"
if command -v vncpasswd >/dev/null 2>&1; then
  if [ -z "${VNC_PASSWORD}" ]; then
    # Generate random password
    VNC_PASSWORD="$(set +o pipefail; tr -dc 'A-Za-z0-9' </dev/urandom | head -c 10)"
  fi
  umask 077
  printf '%s\n' "${VNC_PASSWORD}" | vncpasswd -f > "${HOME}/.vnc/passwd"
  chmod 600 "${HOME}/.vnc/passwd"
else
  log "Error: 'vncpasswd' not found"
fi

# TurboVNC
if [ -f "/opt/startup/xstartup.sh" ]; then
  cp /opt/startup/xstartup.sh "${HOME}/.vnc/xstartup.turbovnc"
  chmod 755 "${HOME}/.vnc/xstartup.turbovnc"
  log "Using custom xstartup with Scipion auto-launch"
else
  # Fallback to basic XFCE startup
  cat > "${HOME}/.vnc/xstartup.turbovnc" <<'EOF'
#!/bin/sh
set -e
export SHELL=/bin/bash
export XAUTHORITY="$HOME/.Xauthority"
[ -r "$HOME/.Xresources" ] && xrdb -merge "$HOME/.Xresources" || true
if command -v dbus-launch >/dev/null 2>&1; then
  exec dbus-launch --exit-with-session startxfce4
else
  exec startxfce4
fi
EOF
  chmod 755 "${HOME}/.vnc/xstartup.turbovnc"
  log "Warning: Using fallback xstartup (no auto-launch)"
fi

# Cleanup old stuff
rm -f "/tmp/.X${disp}-lock" 2>/dev/null || true
rm -f "/tmp/.X11-unix/X${disp}" 2>/dev/null || true
vncserver -kill ":${VNC_DISPLAY}" >/dev/null 2>&1 || true

# Websockify (noVNC)
start_websockify() {
  if command -v websockify >/dev/null 2>&1; then
    websockify --web="/usr/share/novnc" "${NOVNC_PORT}" "127.0.0.1:${RFB_PORT}" &
    WSPID=$!
  else
    log "Error: websockify not found"
    WSPID=""
  fi
}

# Cleanup to prevent stuck resources
cleanup() {
  log "Shutting down..."
  vncserver -kill ":${VNC_DISPLAY}" >/dev/null 2>&1 || true
  if [ -n "${WSPID:-}" ]; then kill "${WSPID}" >/dev/null 2>&1 || true; fi
  # Terminate remaining child processes (Scipion GUI, Task Monitor, etc.)
  local child
  for child in $(jobs -p 2>/dev/null); do
    kill "${child}" >/dev/null 2>&1 || true
  done
}
trap cleanup EXIT

log "TurboVNC with DISPLAY=:${disp} geometry=${VNC_GEOMETRY} depth=${VNC_DEPTH}"

# Setup Scipion configuration
mkdir -p "${HOME}/.config/scipion"

install_config "/opt/startup/scipion.conf" \
  "${HOME}/.config/scipion/scipion.conf" "scipion.conf"

install_config "/opt/startup/hosts.conf" \
  "${HOME}/.config/scipion/hosts.conf" "hosts.conf (queue routing)"

# Symlink SCIPION_HOME/config -> actual config dir so the Python API
# (which resolves config via SCIPION_HOME) can find hosts.conf / scipion.conf
SCIPION_HOME="${SCIPION_HOME:-/opt/scipion}"
mkdir -p "${SCIPION_HOME}/config"
ln -sf "${HOME}/.config/scipion/hosts.conf"  "${SCIPION_HOME}/config/hosts.conf"
ln -sf "${HOME}/.config/scipion/scipion.conf" "${SCIPION_HOME}/config/scipion.conf"
log "Linked ${SCIPION_HOME}/config -> ${HOME}/.config/scipion"

# Setup example project before starting VNC
if [ -f "/opt/startup/setup_example.py" ]; then
  log "Setting up example projects..."
  if ! /opt/scipion/scipion3 run python3 /opt/startup/setup_example.py --download >> /tmp/setup_example.log 2>&1; then
    log "Warning: Example setup failed (see /tmp/setup_example.log)"
  fi
fi

# Start VNC server in the foreground
vncserver -fg ":${VNC_DISPLAY}" \
  -geometry "${VNC_GEOMETRY}" -depth "${VNC_DEPTH}" \
  ${VNC_PASSWORD:+-rfbauth "${HOME}/.vnc/passwd"} \
  -xstartup "${HOME}/.vnc/xstartup.turbovnc" -vgl &
VNC_PID=$!

# Start websockify now that the RFB port is being served
start_websockify

# Block until VNC exits, cleanup trap fires on EXIT
wait "${VNC_PID}"
