#!/usr/bin/env bash

set -Eeuo pipefail

log(){ echo "[$(date +'%H:%M:%S')] $*"; }

export USER="${USER:-scipion}"
export HOME="${HOME:-/home/${USER}}"
export VNC_DISPLAY="${VNC_DISPLAY:-1}"
export VNC_GEOMETRY="${VNC_GEOMETRY:-1920x1080}"
export VNC_DEPTH="${VNC_DEPTH:-24}"
export PATH="/opt/TurboVNC/bin:/usr/local/bin:/usr/bin:/bin:${PATH}"

disp="${VNC_DISPLAY#:}"
NOVNC_PORT=$((5800 + disp))
RFB_PORT=$((5900 + disp))

mkdir -p "${HOME}" /data /projects || true
chown -R "${USER}:${USER}" "${HOME}" /data /projects 2>/dev/null || true

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

# VNC
# TODO: This needs to be cleaned...
VNC_PASSWORD="${VNC_PASSWORD:-${VNC_PASSWD:-}}"
if command -v vncpasswd >/dev/null 2>&1; then
  if [ -n "${VNC_PASSWORD}" ]; then
    umask 077
    printf '%s\n' "${VNC_PASSWORD}" | vncpasswd -f > "${HOME}/.vnc/passwd"
    chmod 600 "${HOME}/.vnc/passwd"
  else
    umask 077
    RANDPW="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 10)"
    printf '%s\n' "${RANDPW}" | vncpasswd -f > "${HOME}/.vnc/passwd"
    chmod 600 "${HOME}/.vnc/passwd"
  fi
else
  log "Error: 'vncpasswd' failed"
fi

# TurboVNC
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

# Cleanup old stuff
rm -f "/tmp/.X${disp}-lock" 2>/dev/null || true
rm -f "/tmp/.X11-unix/X${disp}" 2>/dev/null || true
vncserver -kill ":${VNC_DISPLAY}" >/dev/null 2>&1 || true

# Websockify (noVNC)
if command -v websockify >/dev/null 2>&1; then
  websockify --web="/usr/share/novnc" "${NOVNC_PORT}" "127.0.0.1:${RFB_PORT}" &
  WSPID=$!
else
  log "Error: 'websockify' failed"
  WSPID=""
fi

# Cleanup to prevent stuck resources
cleanup() {
  log "Killing VNC and websockify…"
  vncserver -kill ":${VNC_DISPLAY}" >/dev/null 2>&1 || true
  [ -n "${WSPID}" ] && kill "${WSPID}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

log "TurboVNC with DISPLAY=:${disp} geometry=${VNC_GEOMETRY}  depth=${VNC_DEPTH}"
exec vncserver -fg ":${VNC_DISPLAY}" \
  -geometry "${VNC_GEOMETRY}" -depth "${VNC_DEPTH}" \
  ${VNC_PASSWORD:+-rfbauth "${HOME}/.vnc/passwd"} \
  -xstartup "${HOME}/.vnc/xstartup.turbovnc" -vgl
