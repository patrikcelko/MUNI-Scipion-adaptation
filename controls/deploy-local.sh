#!/usr/bin/env bash

# Scipion deployment helper for local Kubernetes
# ===============================================

set -euo pipefail

ACTION="${1:-deploy}"
RELEASE="${2:-scipion}"
NAMESPACE="${3:-${SCIPION_NAMESPACE:-scipion-local}}"

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
VALUES_LOCAL="${VALUES_LOCAL:-$SCRIPT_DIR/values-local.yaml}"

# Local cluster back-end: microk8s | k8s
CLUSTER_TYPE="${CLUSTER_TYPE:-microk8s}"

# kubectl binary - resolved in check_tools based on CLUSTER_TYPE
KUBECTL=""

# Image tags
GUI_IMAGE_TAG="${GUI_IMAGE_TAG:-latest}"
CTRL_IMAGE_TAG="${CTRL_IMAGE_TAG:-latest}"

# Storage class - auto-detected in check_tools when left empty
STORAGE_CLASS="${STORAGE_CLASS:-}"

# NodePorts - override when defaults clash with existing host services
NODE_PORT_GUI="${NODE_PORT_GUI:-31335}"
NODE_PORT_CTRL="${NODE_PORT_CTRL:-30080}"

VNC_PASSWORD="${VNC_PASSWORD:-}"
WORKER_LABEL="app=scipion-worker"

COMMON_DIR="$SCRIPT_DIR/common"

# shellcheck source=controls/common/logging.sh
source "$COMMON_DIR/logging.sh"

# shellcheck source=controls/common/utils.sh
source "$COMMON_DIR/utils.sh"

# shellcheck source=controls/common/onedata.sh
source "$COMMON_DIR/onedata.sh"

# Verify that required CLI tools and value files are present.
check_tools() {
    command -v helm >/dev/null || err 'Helm not found!'

    case "$CLUSTER_TYPE" in
        microk8s)
            command -v microk8s >/dev/null \
                || err 'microk8s not found. Install with: sudo snap install microk8s --classic'
            KUBECTL="microk8s kubectl"
            STORAGE_CLASS="${STORAGE_CLASS:-microk8s-hostpath}"

            # Export microk8s kubeconfig so that helm can reach the cluster
            export KUBECONFIG
            KUBECONFIG="$(mktemp /tmp/microk8s-kubeconfig-XXXXXX.yaml)"
            microk8s config > "$KUBECONFIG"
            ;;
        k8s)
            command -v kubectl >/dev/null || err 'kubectl not found!'
            KUBECTL="kubectl"
            STORAGE_CLASS="${STORAGE_CLASS:-standard}"
            ;;
        *)
            err "Unknown CLUSTER_TYPE '${CLUSTER_TYPE}'. Supported values: microk8s | k8s"
            ;;
    esac

    $KUBECTL version --request-timeout=10s >/dev/null 2>&1 \
        || err 'Cannot reach Kubernetes API!'

    [[ -f "$VALUES_BASE"  ]] || err "Missing Helm values file: $VALUES_BASE"
    [[ -f "$VALUES_CTRL"  ]] || err "Missing Helm values file: $VALUES_CTRL"
}

# Print a summary after a successful deployment.
print_deploy_summary() {
    local node_ip
    node_ip="$($KUBECTL get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null || echo '127.0.0.1')"

    echo ''
    info "Scipion local deployment complete:"
    info "  Release      : $RELEASE"
    info "  Namespace    : $NAMESPACE"
    info "  Cluster type : $CLUSTER_TYPE"
    info "  Storage class: $STORAGE_CLASS"
    info "  noVNC URL    : http://${node_ip}:${NODE_PORT_GUI}/vnc.html"
    info "  Controller   : http://${node_ip}:${NODE_PORT_CTRL}/docs"
    info "  VNC password : $VNC_PASSWORD"
}

# Create the .mount_projects/ host directory used by microk8s hostpath PVs.
ensure_mount_dir() {
    local mount_dir="${REPO_DIR}/.mount_projects"
    if [[ ! -d "$mount_dir" ]]; then
        info "Creating host mount directory: $mount_dir"
        mkdir -p "$mount_dir"
    else
        info "Host mount directory already exists: $mount_dir"
    fi
}

# Do a Helm upgrade/install of the Scipion release.
do_deploy() {
    check_tools
    ensure_namespace

    # microk8s uses a local hostpath PV - create the backing directory on the host
    [[ "$CLUSTER_TYPE" == microk8s ]] && ensure_mount_dir

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
        --set "controller.backend=k8s"
        --set "persistence.storageClassName=${STORAGE_CLASS}"
        --set "vnc.password=${VNC_PASSWORD}"
        --set "image.tag=${GUI_IMAGE_TAG}"
        --set "controller.image.tag=${CTRL_IMAGE_TAG}"
        --set "image.pullPolicy=$([[ "$GUI_IMAGE_TAG" == latest ]] && echo Always || echo IfNotPresent)"
        --set "controller.image.pullPolicy=$([[ "$CTRL_IMAGE_TAG" == latest ]] && echo Always || echo IfNotPresent)"
        --set "service.nodePort=${NODE_PORT_GUI}"
        --set "controller.service.nodePort=${NODE_PORT_CTRL}"
        --set "ingress.enabled=false"
        --set "seccompProfile.type=Unconfined"
        --wait --timeout 10m
    )

    # Merge optional per-host values file when it exists
    [[ -f "$VALUES_LOCAL" ]] && helm_args+=( -f "$VALUES_LOCAL" )

    # Append any OneData overrides
    helm_args+=( "${onedata_args[@]+"${onedata_args[@]}"}" )

    info "Deploying release '$RELEASE' into namespace '$NAMESPACE':"
    info "  Cluster type  : ${CLUSTER_TYPE}"
    info "  GUI image tag : ${GUI_IMAGE_TAG}"
    info "  Controller tag: ${CTRL_IMAGE_TAG}"
    info "  Storage class : ${STORAGE_CLASS}"

    helm "${helm_args[@]}"

    print_deploy_summary
}

# Print a concise overview of the running deployment.
do_status() {
    check_tools

    info "Release: $RELEASE  |  Namespace: $NAMESPACE  |  Cluster: $CLUSTER_TYPE"
    echo ''

    info "Helm release:"
    helm status "$RELEASE" -n "$NAMESPACE" 2>/dev/null \
        || warn "Release '$RELEASE' not found in namespace '$NAMESPACE'"

    echo ''
    info "Pods:"
    $KUBECTL get pods -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" \
        -o wide 2>/dev/null || true

    echo ''
    info "Worker pods (created by controller):"
    $KUBECTL get pods -n "$NAMESPACE" \
        -l "$WORKER_LABEL" \
        -o wide 2>/dev/null || true

    echo ''
    info "Services:"
    $KUBECTL get svc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "PVCs:"
    $KUBECTL get pvc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "Nodes:"
    $KUBECTL get nodes -o wide 2>/dev/null | head -5 || true
}

# Print a detailed help.
do_help() {
    echo -e ""
    echo -e "${BOLD}deploy-local.sh${NC} - Scipion deployment helper for local Kubernetes"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  ./controls/deploy-local.sh <command> [RELEASE] [NAMESPACE]"
    echo -e ""
    echo -e "  ${CYAN}RELEASE${NC}      Helm release name (default: scipion)"
    echo -e "  ${CYAN}NAMESPACE${NC}    Kubernetes namespace (default: scipion-local)"
    echo -e ""
    echo -e "${BOLD}COMMANDS${NC}"
    echo -e "  ${GREEN}deploy${NC}    Install or upgrade the Scipion Helm release."
    echo -e "  ${GREEN}teardown${NC}  Uninstall the Helm release. PVCs are kept."
    echo -e "  ${GREEN}purge${NC}     Uninstall + delete all PVCs (irreversible, asks for confirmation)."
    echo -e "  ${GREEN}status${NC}    Show pods, services and PVCs for the release."
    echo -e "  ${GREEN}logs${NC}      Tail live controller logs."
    echo -e "  ${GREEN}help${NC}      Show this help message."
    echo -e ""
    echo -e "${BOLD}ENVIRONMENT VARIABLES${NC}"
    echo -e "  ${CYAN}CLUSTER_TYPE${NC}      Local back-end: microk8s | k8s (default: microk8s)"
    echo -e "  ${CYAN}VNC_PASSWORD${NC}      VNC password (auto-generated if unset)"
    echo -e "  ${CYAN}GUI_IMAGE_TAG${NC}     GUI image tag to deploy (default: latest)"
    echo -e "  ${CYAN}CTRL_IMAGE_TAG${NC}    Controller image tag to deploy (default: latest)"
    echo -e "  ${CYAN}STORAGE_CLASS${NC}     Kubernetes storage class (default: auto-detected)"
    echo -e "  ${CYAN}NODE_PORT_GUI${NC}     NodePort for the noVNC GUI (default: 31335)"
    echo -e "  ${CYAN}NODE_PORT_CTRL${NC}    NodePort for the controller API (default: 30080)"
    echo -e "  ${CYAN}SCIPION_NAMESPACE${NC} Default namespace override"
    echo -e "  ${CYAN}HELM_CHART${NC}        Path to Helm chart directory"
    echo -e "  ${CYAN}VALUES_LOCAL${NC}      Optional per-host overrides (default: controls/values-local.yaml)"
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
