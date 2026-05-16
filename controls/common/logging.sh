#!/usr/bin/env bash

# Logging helper
# ==============

RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[1;32m'
CYAN='\033[0;36m'
NC='\033[0m'
BOLD='\033[1m'

info() {
    echo -e "${CYAN}[INFO ]${NC} $*";
}

warn() {
    echo -e "${YELLOW}[WARN ]${NC} $*";
}

err() {
    echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1;
}
