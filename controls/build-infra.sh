#!/usr/bin/env bash

# Scipion infrastructure image builder
# ====================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMON_DIR="$SCRIPT_DIR/common"

# shellcheck source=controls/common/logging.sh
source "$COMMON_DIR/logging.sh"

ACTION="${1:-build}"
COMPONENT="${2:-all}"
VERSION="${3:-}"

case "$ACTION" in
    build|push|build-push|latest|help) ;;
    -h|--help)
        ACTION=help
        ;;
    *)
        err "Unknown command: '$ACTION'. Use: build | push | build-push | latest | help" >&2
        ;;
esac

[[ "$ACTION" != help && "$ACTION" != latest && -z "$VERSION" ]] \
    && { err "VERSION is required (use like ./build-infra.sh build all v1.0.0)"; }

case "$COMPONENT" in
    all|gui|controller) ;;
    *)
        err "Unknown component: '$COMPONENT'. Use: all | gui | controller"
        ;;
esac

# Configuration
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DOCKER_DIR="$REPO_DIR/docker"
REGISTRY="${REGISTRY:-harbor.celko.cz/scipion-adaptation}"

# Image names as published to the registry
GUI_IMAGE="${GUI_IMAGE:-scipion3-remote}"
CTRL_IMAGE="${CTRL_IMAGE:-container-controller}"

# shellcheck source=controls/common/registry.sh
source "$COMMON_DIR/registry.sh"

# Verify build prerequisites and Dockerfile existence.
check_tools() {
    check_docker
    [[ -f "$DOCKER_DIR/gui/Dockerfile" ]] || err "Dockerfile not found: $DOCKER_DIR/gui/Dockerfile"
    [[ -f "$DOCKER_DIR/controller/Dockerfile" ]] || err "Dockerfile not found: $DOCKER_DIR/controller/Dockerfile"
}

# Build the GUI Docker image.
build_gui() {
    info "GUI ($GUI_IMAGE:$VERSION):"
    do_build "$GUI_IMAGE" "$DOCKER_DIR/gui/Dockerfile" "$REPO_DIR"
}

# Push the GUI Docker image to the registry.
push_gui() {
    do_push "$GUI_IMAGE"
}

# Build the controller Docker image.
build_controller() {
    info "Controller ($CTRL_IMAGE:$VERSION):"
    do_build "$CTRL_IMAGE" "$DOCKER_DIR/controller/Dockerfile" "$REPO_DIR"
}

# Push the controller Docker image to the registry.
push_controller() {
    do_push "$CTRL_IMAGE"
}

# Build the selected component images.
do_build_action() {
    check_tools

    case "$COMPONENT" in
        all)
            build_gui; build_controller
            ;;
        gui)
            build_gui
            ;;
        controller)
            build_controller
            ;;
    esac

    info "Build complete."
}

# Push selected component images to the registry.
do_push_action() {
    check_tools

    case "$COMPONENT" in
        all)
            info "GUI ($GUI_IMAGE:$VERSION):"
            push_gui

            info "Controller ($CTRL_IMAGE:$VERSION):"
            push_controller
            ;;
        gui)
            info "GUI ($GUI_IMAGE:$VERSION):"
            push_gui
            ;;
        controller)
            info "Controller ($CTRL_IMAGE:$VERSION):"
            push_controller
            ;;
    esac

    info "Push complete."
}

# Build then push the selected component images.
do_build_push_action() {
    check_tools

    case "$COMPONENT" in
        all)
            build_gui; push_gui
            build_controller; push_controller
            ;;
        gui)
            build_gui; push_gui
            ;;
        controller)
            build_controller; push_controller
            ;;
    esac

    info "Build-push complete."
}

# Show latest remote tags for the selected components.
do_latest_action() {
    case "$COMPONENT" in
        all)
            info "$GUI_IMAGE:"
            do_latest "$GUI_IMAGE"

            info "$CTRL_IMAGE:"
            do_latest "$CTRL_IMAGE"
            ;;
        gui)
            info "$GUI_IMAGE:"
            do_latest "$GUI_IMAGE"
            ;;
        controller)
            info "$CTRL_IMAGE:"
            do_latest "$CTRL_IMAGE"
            ;;
    esac
}

# Print a detailed help message.
do_help() {
    echo -e ""
    echo -e "${BOLD}build-infra.sh${NC} - Scipion infrastructure Docker image builder"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  build-infra.sh <command> [component] [version]"
    echo -e ""
    echo -e "  ${CYAN}component${NC}   gui | controller | all (default: all)"
    echo -e "  ${CYAN}version${NC}     Image tag to build/push, like v1.0.10 (required for build/push)"
    echo -e ""
    echo -e "${BOLD}COMMANDS${NC}"
    echo -e "  ${GREEN}build${NC}        Build images locally."
    echo -e "  ${GREEN}push${NC}         Push already-built images to registry."
    echo -e "  ${GREEN}build-push${NC}   Build and immediately push images."
    echo -e "  ${GREEN}latest${NC}       Show latest tags available on the remote registry."
    echo -e "  ${GREEN}help${NC}         Show this help message."
    echo -e ""
    echo -e "${BOLD}ENVIRONMENT VARIABLES${NC}"
    echo -e "  ${CYAN}REGISTRY${NC}    Docker registry base URL (default: harbor.celko.cz/scipion-adaptation)"
    echo -e "  ${CYAN}GUI_IMAGE${NC}   GUI image name (default: scipion3-remote)"
    echo -e "  ${CYAN}CTRL_IMAGE${NC}  Controller image name (default: container-controller)"
    echo -e ""
}

# Main entry point, dispatch based on the command
case "$ACTION" in
    build)
        do_build_action
        ;;
    push)
        do_push_action
        ;;
    build-push)
        do_build_push_action
        ;;
    latest)
        do_latest_action
        ;;
    help)
        do_help
        ;;
esac
