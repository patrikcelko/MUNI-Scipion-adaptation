#!/usr/bin/env bash

# Kubernetes/Helm utilities
# =========================

# Generate random 12-character alphanumeric string.
random_password() {
    { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom || true; } | head -c 12
}

# Create the target namespace if it does not already exist.
ensure_namespace() {
    local kctl="${KUBECTL:-kubectl}"

    if ! $kctl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        info "Creating namespace '$NAMESPACE'..."
        $kctl create namespace "$NAMESPACE"
    else
        info "Namespace '$NAMESPACE' already exists, reusing."
    fi
}

# Stream live logs from the controller pod for the active release.
do_logs() {
    check_tools

    local kctl="${KUBECTL:-kubectl}"

    info "Tailing controller logs for release '$RELEASE' in namespace '$NAMESPACE'..."
    $kctl logs -n "$NAMESPACE" \
        -l "app.kubernetes.io/name=scipion-controller,app.kubernetes.io/instance=${RELEASE}" \
        --tail=200 -f
}

# Uninstall the Helm release and remove orphaned worker jobs/pods. PVCs are kept.
do_teardown() {
    check_tools

    local kctl="${KUBECTL:-kubectl}"

    info "Uninstalling release '$RELEASE' from namespace '$NAMESPACE'..."
    helm uninstall "$RELEASE" -n "$NAMESPACE" 2>/dev/null \
        || warn "Release '$RELEASE' not found!"

    # Remove orphaned Jobs/Pods created by the Scipion controller at runtime.
    $kctl delete jobs -n "$NAMESPACE" -l "${WORKER_LABEL}" --ignore-not-found 2>/dev/null || true
    $kctl delete pods -n "$NAMESPACE" -l "${WORKER_LABEL}" \
        --ignore-not-found --force --grace-period=0 2>/dev/null || true

    info "Release removed successfully! PVCs preserved - run 'purge' to delete them."
}

# Uninstall the release and permanently delete all associated PVCs.
do_purge() {
    do_teardown

    local kctl="${KUBECTL:-kubectl}"

    warn "Deleting all PVCs for release '$RELEASE' in namespace '$NAMESPACE'..."
    warn "This is irreversible, so all Scipion project data will be lost!"

    read -r -p "Type 'yes' to confirm: " confirm
    [[ "$confirm" == "yes" ]] \
        || { info "Aborted."; exit 0; }

    $kctl delete pvc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" --ignore-not-found

    info "PVCs deleted."
}
