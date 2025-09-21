#!/usr/bin/env bash
set -Eeuo pipefail

export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"

USER_HOME="${HOME:-/home/scipion}"

# VNC auth stuff
mkdir -p "${USER_HOME}/.vnc"
chmod 700 "${USER_HOME}/.vnc"

# Xauthority
touch "${USER_HOME}/.Xauthority"
chmod 600 "${USER_HOME}/.Xauthority"

# XDG runtime dir
if [[ -z "${XDG_RUNTIME_DIR:-}" ]]; then
  export XDG_RUNTIME_DIR="${USER_HOME}/.xdg-runtime"
  mkdir -p "$XDG_RUNTIME_DIR"
  chmod 700 "$XDG_RUNTIME_DIR"
fi

# Disable screen blanking (breaks GPU mount... ~30 hours wasted on it)
xset -dpms >/dev/null 2>&1 || true
xset s off >/dev/null 2>&1 || true
xset s noblank >/dev/null 2>&1 || true

# Prefer GPU by default
export __GL_YIELD="USLEEP"

# TODO: maybe dbus-launch is needed here as well?
#       Also clean it up...
if command -v startxfce4 >/dev/null 2>&1; then
  exec dbus-launch --exit-with-session startxfce4
elif command -v xfce4-session >/dev/null 2>&1; then
  exec dbus-launch --exit-with-session xfce4-session
elif command -v xterm >/dev/null 2>&1; then
  xsetroot -solid grey >/dev/null 2>&1 || true
  exec xterm -fa Monospace -fs 11 -geometry 100x30+10+10
else
  exec /bin/sh
fi
