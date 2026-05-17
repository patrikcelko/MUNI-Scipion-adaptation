#!/usr/bin/env bash

# Scipion tool image builder
# ==========================

set -euo pipefail

ACTION="${1:-build}"
TOOL="${2:-all}"
VERSION="${3:-}"

case "$ACTION" in
    build|push|build-push|latest|list|help) ;;
    -h|--help)
        ACTION=help
        ;;
    *)
        err "Unknown command: '$ACTION'. Use: build | push | build-push | latest | list | help"
        ;;
esac

[[ "$ACTION" != help && "$ACTION" != list && "$ACTION" != latest && -z "$VERSION" ]] \
    && { echo "VERSION is required (use like ./build-tools.sh build all v2.0.0)" >&2; exit 1; }

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
TOOLS_DIR="$REPO_DIR/docker/tools"

# Docker registry stuff
REGISTRY="${REGISTRY:-harbor.celko.cz/scipion-adaptation}"
COMMON_DIR="$SCRIPT_DIR/common"

# shellcheck source=controls/common/logging.sh
source "$COMMON_DIR/logging.sh"

# shellcheck source=controls/common/registry.sh
source "$COMMON_DIR/registry.sh"

# Return a list of all buildable tool names.
available_tools() {
    local tools=()
    for d in "$TOOLS_DIR"/*/; do
        [[ -f "${d}Dockerfile" ]] && tools+=("$(basename "$d")")
    done

    printf '%s\n' "${tools[@]}"
}

# Validate TOOL argument early.
if [[ "$ACTION" != help && "$ACTION" != list && "$TOOL" != all ]]; then
    [[ -d "$TOOLS_DIR/$TOOL" && -f "$TOOLS_DIR/$TOOL/Dockerfile" ]] \
        || { err "Unknown tool '$TOOL'. Run './build-tools.sh list' for available tools."; }
fi

# Expand "all" to the full tool list
resolve_tools() {
    local arg="$1"

    if [[ "$arg" == all ]]; then
        available_tools
    else
        [[ -d "$TOOLS_DIR/$arg" && -f "$TOOLS_DIR/$arg/Dockerfile" ]] \
            || err "Unknown tool '${arg}'. Available: $(available_tools | tr '\n' ' ')"
        echo "$arg"
    fi
}

# Verify build prerequisites.
check_tools() {
    check_docker
    [[ -d "$TOOLS_DIR" ]] || err "Tools docker directory not found: $TOOLS_DIR"
}

# Build the Docker image for a single tool.
# NOTE: When Dockerfile.gpu exists a second image tagged ${tool}-gpu is also built.
do_build_tools() {
    local tool="$1"
    local tool_dir="$TOOLS_DIR/$tool"
    local common_patch="$TOOLS_DIR/common/patch_libnone.py"
    local copied_patch=""

    # If the tool Dockerfile uses patch_libnone.py, stage the shared copy into
    # the tool build context for the duration of the build.
    if grep -q "COPY patch_libnone.py" "$tool_dir/Dockerfile" 2>/dev/null; then
        cp "$common_patch" "$tool_dir/patch_libnone.py"
        copied_patch="$tool_dir/patch_libnone.py"
    fi

    do_build "$tool" "$tool_dir/Dockerfile" "$tool_dir"
    local rc=$?

    # Build GPU variant when Dockerfile.gpu is present (tagged as ${tool}-gpu).
    if [[ $rc -eq 0 && -f "$tool_dir/Dockerfile.gpu" ]]; then
        info "GPU Dockerfile found for '$tool', building ${tool}-gpu variant..."
        do_build "${tool}-gpu" "$tool_dir/Dockerfile.gpu" "$tool_dir"
        rc=$?
    fi

    [[ -n "$copied_patch" ]] && rm -f "$copied_patch"

    return $rc
}

# Build Docker images for all resolved tools.
do_build_action() {
    check_tools
    local failed=()

    while IFS= read -r tool; do
        info "Tool: $tool..."
        do_build_tools "$tool" || failed+=("$tool")
    done < <(resolve_tools "$TOOL")

    if [[ ${#failed[@]} -gt 0 ]]; then
        err "Build failed for: ${failed[*]}"
    fi

    info "All builds complete."
}

# Push Docker images for all resolved tools.
do_push_action() {
    check_tools
    local failed=()

    while IFS= read -r tool; do
        info "Tool: $tool..."
        do_push "$tool" || failed+=("$tool")
        # Push GPU variant if Dockerfile.gpu exists.
        if [[ -f "$TOOLS_DIR/$tool/Dockerfile.gpu" ]]; then
            do_push "${tool}-gpu" || failed+=("${tool}-gpu")
        fi
    done < <(resolve_tools "$TOOL")

    if [[ ${#failed[@]} -gt 0 ]]; then
        err "Push failed for: ${failed[*]}"
    fi

    info "All pushes complete."
}

# Build then push Docker images for all resolved tools.
do_build_push_action() {
    check_tools
    local failed=()

    while IFS= read -r tool; do
        info "Tool: $tool..."
        if do_build_tools "$tool"; then
            do_push "$tool" || failed+=("$tool")
            # Push GPU variant if Dockerfile.gpu exists.
            if [[ -f "$TOOLS_DIR/$tool/Dockerfile.gpu" ]]; then
                do_push "${tool}-gpu" || failed+=("${tool}-gpu")
            fi
        else
            failed+=("$tool")
        fi
    done < <(resolve_tools "$TOOL")

    if [[ ${#failed[@]} -gt 0 ]]; then
        err "Build-push failed for: ${failed[*]}"
    fi

    info "All build-push complete."
}

# Show latest remote tags for all resolved tools.
do_latest_action() {
    while IFS= read -r tool; do
        info "Tool: $tool..."
        do_latest "$tool"
    done < <(resolve_tools "$TOOL")
}

# List all buildable tools.
do_list() {
    info "Buildable tools in $TOOLS_DIR:"
    available_tools | while read -r t; do
        echo "    $t"
    done
}

# Print a detailed help message.
do_help() {
    echo -e ""
    echo -e "${BOLD}build-tools.sh${NC} - Scipion tool Docker image builder"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  build-tools.sh <command> [tool] [version]"
    echo -e ""
    echo -e "  ${CYAN}tool${NC}      Tool name or 'all' (default: all)"
    echo -e "  ${CYAN}version${NC}   Image tag to build/push, like. v2.0.0 (required for build/push)"
    echo -e ""
    echo -e "${BOLD}COMMANDS${NC}"
    echo -e "  ${GREEN}build${NC}        Build images locally."
    echo -e "  ${GREEN}push${NC}         Push already-built images to registry."
    echo -e "  ${GREEN}build-push${NC}   Build and immediately push images."
    echo -e "  ${GREEN}latest${NC}       Show latest tags available on the remote registry."
    echo -e "  ${GREEN}list${NC}         List all buildable tools."
    echo -e "  ${GREEN}help${NC}         Show this help message."
    echo -e ""
    echo -e "${BOLD}ENVIRONMENT VARIABLES${NC}"
    echo -e "  ${CYAN}REGISTRY${NC}    Docker registry base URL (default: harbor.celko.cz/scipion-adaptation)"
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
    list)
        do_list
        ;;
    help)
        do_help
        ;;
esac
