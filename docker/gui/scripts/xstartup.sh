#!/usr/bin/env bash

# VNC session startup launches XFCE desktop, Scipion GUI and Task Monitor

set -Eeuo pipefail

log(){ echo "[$(date +'%H:%M:%S')] $*"; }

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export SCIPION_HOME="${SCIPION_HOME:-/opt/scipion}"
export __GL_YIELD="USLEEP"

DESKTOP_SETTLE=5
SCIPION_DELAY=3
MONITOR_DELAY=5

USER_HOME="${HOME:-/home/scipion}"

# XDG runtime dir (required by dbus / XFCE)
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="${USER_HOME}/.xdg-runtime"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR"
fi

# Disable DPMS and screen blanking (interferes with VirtualGL rendering pipeline)
xset -dpms >/dev/null 2>&1 || true
xset s off >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

if command -v startxfce4 >/dev/null 2>&1; then
  dbus-launch --exit-with-session startxfce4 &
  DESKTOP_PID=$!
elif command -v xterm >/dev/null 2>&1; then
  xsetroot -solid grey >/dev/null 2>&1 || true
  xterm -fa Monospace -fs 11 -geometry 100x30+10+10 &
  DESKTOP_PID=$!
else
  /bin/sh &
  DESKTOP_PID=$!
fi

sleep "${DESKTOP_SETTLE}"

# Start Scipion and Task Monitor
if [ -d "${SCIPION_HOME}" ]; then
  export PATH="${SCIPION_HOME}/.scipion3/bin:${PATH}"
  export VIRTUAL_ENV="${SCIPION_HOME}/.scipion3"

  # Scipion GUI
  (
    sleep "${SCIPION_DELAY}"
    cd "${HOME}/ScipionUserData" 2>/dev/null || cd ~
    log "Starting Scipion GUI..."
    exec "${SCIPION_HOME}/scipion3" >> ~/scipion.log 2>&1
  ) &

  # Task Monitor dashboard
  (
    sleep "${MONITOR_DELAY}"
    log "Starting Task Monitor..."
    exec env PYTHONPATH=/opt/startup python3 -m monitor >> ~/task-monitor.log 2>&1
  ) &
fi

# Keep session alive until the desktop process exits
wait "${DESKTOP_PID}"
