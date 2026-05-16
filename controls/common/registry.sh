#!/usr/bin/env bash

# Docker registry utility functions
# =================================

# Verify that docker is available and the daemon is reachable.
check_docker() {
    command -v docker >/dev/null || err 'Docker not found!'
    docker info >/dev/null 2>&1 || err 'Docker daemon is not running!'
}

# Build a Docker image and tag it as REGISTRY/IMAGE_NAME:VERSION and :latest.
do_build() {
    local image_name="$1"
    local dockerfile="$2"
    local build_context="$3"

    [[ -f "$dockerfile" ]] || err "Dockerfile not found: $dockerfile"

    local full_tag="${REGISTRY}/${image_name}:${VERSION}"
    local latest_tag="${REGISTRY}/${image_name}:latest"

    info "Building ${full_tag} ..."
    info "  Dockerfile: $dockerfile"
    info "  Context   : $build_context"

    docker build \
        --network=host \
        --progress=plain \
        --tag "$full_tag" \
        --tag "$latest_tag" \
        --file "$dockerfile" \
        "$build_context"

    info "Built: $full_tag  (also tagged: $latest_tag)"
}

# Push REGISTRY/IMAGE_NAME:VERSION and :latest to the remote registry.
do_push() {
    local image_name="$1"
    local full_tag="${REGISTRY}/${image_name}:${VERSION}"
    local latest_tag="${REGISTRY}/${image_name}:latest"

    info "Pushing ${full_tag} ..."
    docker push "$full_tag"

    info "Pushing ${latest_tag} ..."
    docker push "$latest_tag"

    info "Pushed: $full_tag  +  $latest_tag"
}

# Query the remote registry for available tags of IMAGE_NAME.
do_latest() {
    local image_name="$1"
    local repo="${REGISTRY}/${image_name}"
    local host="${REGISTRY%%/*}"
    local image_path="${REGISTRY#*/}/${image_name}"

    local _list_tags_py
    _list_tags_py="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/list_tags.py"

    info "Tags for ${repo}:"
    python3 "$_list_tags_py" "$host" "$image_path" | sed 's/^/  /' \
        || warn "Could not list tags (registry unreachable or not logged in)."
}
