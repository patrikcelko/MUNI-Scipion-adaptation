#!/usr/bin/env bash

# Scipion deployment helper for Rancher
# ===================================

set -euo pipefail

ACTION="${1:-deploy}"
RELEASE="${2:-scipion}"
NAMESPACE="${3:-${SCIPION_NAMESPACE:-celko-ns}}"

case "$ACTION" in
    deploy|teardown|purge|status|logs|help) ;;
    -h|--help)
        ACTION=help
        ;;
    *)
        err "Unknown command: '$ACTION'. Use: deploy | teardown | purge | status | logs | help"
        ;;
esac

# Configuration
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
HELM_CHART="${HELM_CHART:-$REPO_DIR/helm}"

# Helm values files
VALUES_BASE="$HELM_CHART/values.yaml"
VALUES_CTRL="$HELM_CHART/values-controller.yaml"
VALUES_RANCHER="${VALUES_RANCHER:-$SCRIPT_DIR/rancher/values-rancher.yaml}"

# Image tags
GUI_IMAGE_TAG="${GUI_IMAGE_TAG:-latest}"
CTRL_IMAGE_TAG="${CTRL_IMAGE_TAG:-latest}"

INGRESS_HOST="${INGRESS_HOST:-}"
VNC_PASSWORD="${VNC_PASSWORD:-}"
WORKER_LABEL="app=scipion-worker"

COMMON_DIR="$SCRIPT_DIR/common"

# shellcheck source=controls/common/logging.sh
source "$COMMON_DIR/logging.sh"

# shellcheck source=controls/common/utils.sh
source "$COMMON_DIR/utils.sh"

# shellcheck source=controls/common/onedata.sh
source "$COMMON_DIR/onedata.sh"

# Verify that required CLI tools and value files are present!
check_tools() {
    command -v kubectl >/dev/null || err 'Kubectl not found!'
    command -v helm >/dev/null || err 'Helm not found!'

    [[ -n "${KUBECONFIG:-}" || -f "$HOME/.kube/config" ]] \
        || err 'No KUBECONFIG set and ~/.kube/config is missing!'

    kubectl cluster-info >/dev/null 2>&1 \
        || err 'Cannot reach Kubernetes API!'

    [[ -f "$VALUES_BASE"  ]] || err "Missing Helm values file: $VALUES_BASE"
    [[ -f "$VALUES_CTRL"  ]] || err "Missing Helm values file: $VALUES_CTRL"
    [[ -f "$VALUES_RANCHER" ]] || err "Missing Helm values file: $VALUES_RANCHER"
}

# Print a summary box after a successful deployment.
print_deploy_summary() {
    echo ''
    info "Scipion deployment on Rancher cluster complete:"
    info "  Release: $RELEASE"
    info "  Namespace: $NAMESPACE"

    [[ -n "$INGRESS_HOST" ]] \
        && info "  noVNC URL : http://${INGRESS_HOST}/vnc.html"
    info "  VNC pass  : $VNC_PASSWORD"
}

# Do a Helm upgrade/install of the Scipion release.
do_deploy() {
    check_tools
    ensure_namespace

    if [[ -z "$VNC_PASSWORD" ]]; then
        VNC_PASSWORD="$(random_password)"
        info "No VNC_PASSWORD set, generated one: $VNC_PASSWORD"
    fi

    # Collect optional OneData flags
    mapfile -t onedata_args < <(provision_onedata_secret)

    local helm_args=(
        upgrade --install "$RELEASE" "$HELM_CHART"
        --namespace "$NAMESPACE"
        -f "$VALUES_BASE"
        -f "$VALUES_CTRL"
        -f "$VALUES_RANCHER"
        --set "vnc.password=${VNC_PASSWORD}"
        --set "controller.backend=rancher"
        --set "image.tag=${GUI_IMAGE_TAG}"
        --set "controller.image.tag=${CTRL_IMAGE_TAG}"
        --wait --timeout 10m
    )

    [[ -n "$INGRESS_HOST" ]] && helm_args+=( --set "ingress.host=${INGRESS_HOST}" )

    # Append any OneData overrides
    helm_args+=( "${onedata_args[@]+"${onedata_args[@]}"}" )

    info "Deploying release '$RELEASE' into namespace '$NAMESPACE':"
    info "  GUI image tag: ${GUI_IMAGE_TAG}"
    info "  Controller image tag: ${CTRL_IMAGE_TAG}"

    helm "${helm_args[@]}"

    print_deploy_summary
}

# Print a concise overview of the running deployment.
do_status() {
    check_tools

    info "Release: $RELEASE  |  Namespace: $NAMESPACE"
    echo ''

    info "Helm release:"
    helm status "$RELEASE" -n "$NAMESPACE" 2>/dev/null \
        || warn "Release '$RELEASE' not found in namespace '$NAMESPACE'"

    echo ''
    info "Pods:"
    kubectl get pods -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" \
        -o wide 2>/dev/null || true

    echo ''
    info "Services:"
    kubectl get svc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "Ingress:"
    kubectl get ingress -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "PVCs:"
    kubectl get pvc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true
}

# Print a detailed help.
do_help() {
    echo -e ""
    echo -e "${BOLD}deploy-rancher.sh${NC} - Scipion deployment helper for Rancher-SC Kubernetes"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  export KUBECONFIG=/path/to/cluster.yaml"
    echo -e "  deploy-rancher.sh <command> [RELEASE] [NAMESPACE]"
    echo -e ""
    echo -e "  ${CYAN}RELEASE${NC}      Helm release name (default: scipion)"
    echo -e "  ${CYAN}NAMESPACE${NC}    Kubernetes namespace (default: celko-ns)"
    echo -e ""
    echo -e "${BOLD}COMMANDS${NC}"
    echo -e "  ${GREEN}deploy${NC}    Install or upgrade the Scipion Helm release."
    echo -e "  ${GREEN}teardown${NC}  Uninstall the Helm release. PVCs are kept."
    echo -e "  ${GREEN}purge${NC}     Uninstall + delete all PVCs (irreversible, asks for confirmation)."
    echo -e "  ${GREEN}status${NC}    Show pods, services, ingress and PVCs for the release."
    echo -e "  ${GREEN}logs${NC}      Tail live controller logs."
    echo -e "  ${GREEN}help${NC}      Show this help message."
    echo -e ""
    echo -e "${BOLD}ENVIRONMENT VARIABLES${NC}"
    echo -e "  ${CYAN}KUBECONFIG${NC}        Path to Rancher kubeconfig"
    echo -e "  ${CYAN}INGRESS_HOST${NC}      noVNC ingress hostname like scipion.celko-ns.dyn.cloud.e-infra.cz"
    echo -e "  ${CYAN}VNC_PASSWORD${NC}      VNC password (auto-generated if unset)"
    echo -e "  ${CYAN}GUI_IMAGE_TAG${NC}     GUI image tag to deploy"
    echo -e "  ${CYAN}CTRL_IMAGE_TAG${NC}    Controller image tag to deploy"
    echo -e "  ${CYAN}SCIPION_NAMESPACE${NC} Default namespace override"
    echo -e "  ${CYAN}HELM_CHART${NC}        Path to Helm chart directory"
    echo -e ""
    echo -e "${BOLD}ONEDATA VARIABLES${NC}  (all optional)"
    echo -e "  ${CYAN}ONEDATA_TOKEN${NC}     OneData access token"
    echo -e "  ${CYAN}ONEDATA_PROVIDER${NC}  Oneprovider hostname"
    echo -e "  ${CYAN}ONEDATA_SPACE${NC}     Space name to mount"
    echo -e ""
}

# Main entry point, dispatch based on the command
case "$ACTION" in
    deploy)
        do_deploy
        ;;
    teardown)
        do_teardown
        ;;
    purge)
        do_purge
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    help)
        do_help
        ;;
esac
