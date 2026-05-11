#!/usr/bin/env bash

# Scipion deployment helper for CERIT
# ===================================

set -euo pipefail


# Parse command-line arguments

ACTION="${1:-deploy}"
RELEASE="${2:-scipion}"
NAMESPACE="${3:-${SCIPION_NAMESPACE:-celko-ns}}"

case "$ACTION" in
    deploy|teardown|purge|status|logs|help) ;;
    -h|--help)
        ACTION=help
        ;;
    *)
        echo "Unknown command: '$ACTION'. Use: deploy | teardown | purge | status | logs | help" >&2
        exit 1
        ;;
esac

# Configuration

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
HELM_CHART="${HELM_CHART:-$REPO_DIR/helm}"

# Helm values files
VALUES_BASE="$HELM_CHART/values.yaml"
VALUES_CTRL="$HELM_CHART/values-controller.yaml"
VALUES_CERIT="$SCRIPT_DIR/values-cerit.yaml"

# Latest image tags
GUI_IMAGE_TAG="${GUI_IMAGE_TAG:-v2}"
CTRL_IMAGE_TAG="${CTRL_IMAGE_TAG:-v51}"

INGRESS_HOST="${INGRESS_HOST:-}"
VNC_PASSWORD="${VNC_PASSWORD:-}"

# Logging helpers

RED='\033[0;31m';
YELLOW='\033[1;33m';
GREEN='\033[1;32m';
CYAN='\033[0;36m';
NC='\033[0m';
BOLD='\033[1m';


log()  {
    echo -e "${GREEN}[CERIT]${NC} $*";
}

info() {
    echo -e "${CYAN}[INFO ]${NC} $*";
}

warn() {
    echo -e "${YELLOW}[WARN ]${NC} $*";
}

err()  {
    echo -e "${RED}[ERROR]${NC} $*" >&2;
    exit 1;
}

# Verify that required CLI tools and value files are present!
check_tools() {
    command -v kubectl >/dev/null || err 'Kubectl not found!'
    command -v helm >/dev/null || err 'Helm not found!'

    [[ -n "${KUBECONFIG:-}" || -f "$HOME/.kube/config" ]] \
        || err 'No KUBECONFIG set and ~/.kube/config is missing!'

    kubectl version --request-timeout=10s >/dev/null 2>&1 \
        || err 'Cannot reach Kubernetes API!'

    [[ -f "$VALUES_BASE"  ]] || err "Missing Helm values file: $VALUES_BASE"
    [[ -f "$VALUES_CTRL"  ]] || err "Missing Helm values file: $VALUES_CTRL"
    [[ -f "$VALUES_CERIT" ]] || err "Missing Helm values file: $VALUES_CERIT"
}

# Create the target namespace if it does not already exist.
ensure_namespace() {
    if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
        log "Creating namespace '$NAMESPACE'..."
        kubectl create namespace "$NAMESPACE"
    else
        info "Namespace '$NAMESPACE' already exists, reusing..."
    fi
}

# If ONEDATA_TOKEN is set, update Kubernetes secret that holds the OneData access token.
provision_onedata_secret() {
    if [[ -z "${ONEDATA_TOKEN:-}" ]]; then
        return 0
    fi

    log 'OneData integration enabled, provisioning secret scipion-onedata-token...'
    kubectl -n "$NAMESPACE" create secret generic scipion-onedata-token \
        --from-literal=token="$ONEDATA_TOKEN" \
        --dry-run=client -o yaml | kubectl apply -f -

    echo "--set=onedata.enabled=true"
    echo "--set=onedata.tokenSecret=scipion-onedata-token"
    echo "--set=controller.onedata.enabled=true"
    echo "--set=controller.onedata.tokenSecret=scipion-onedata-token"

    [[ -n "${ONEDATA_PROVIDER:-}" ]] && {
        echo "--set=onedata.provider=${ONEDATA_PROVIDER}"
        echo "--set=controller.onedata.provider=${ONEDATA_PROVIDER}"
    }
    [[ -n "${ONEDATA_SPACE:-}" ]] && {
        echo "--set=onedata.space=${ONEDATA_SPACE}"
        echo "--set=controller.onedata.space=${ONEDATA_SPACE}"
    }
}

# Generate a random 12-character alphanumeric password.
random_password() {
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 12
}

# Print a summary box after a successful deployment.
print_deploy_summary() {
    echo ''
    log "Scipion deployment on CERIT-SC complete:"
    log "  Release: $RELEASE"
    log "  Namespace: $NAMESPACE"

    [[ -n "$INGRESS_HOST" ]] \
        && log "  noVNC URL : http://${INGRESS_HOST}/vnc.html"
    log "  VNC pass  : $VNC_PASSWORD"
}

# Do a Helm upgrade/install of the Scipion release.
do_deploy() {
    check_tools
    ensure_namespace

    if [[ -z "$VNC_PASSWORD" ]]; then
        VNC_PASSWORD="$(random_password)"
        log "No VNC_PASSWORD set, generated one: $VNC_PASSWORD"
    fi

    # Collect optional OneData flags
    mapfile -t onedata_args < <(provision_onedata_secret)

    local helm_args=(
        upgrade --install "$RELEASE" "$HELM_CHART"
        --namespace "$NAMESPACE"
        -f "$VALUES_BASE"
        -f "$VALUES_CTRL"
        -f "$VALUES_CERIT"
        --set "vnc.password=${VNC_PASSWORD}"
        --set "controller.backend=cerit"
        --set "image.tag=${GUI_IMAGE_TAG}"
        --set "controller.image.tag=${CTRL_IMAGE_TAG}"
        --set "ingress.tls.enabled=false"
        --wait --timeout 10m
    )

    [[ -n "$INGRESS_HOST" ]] && helm_args+=( --set "ingress.host=${INGRESS_HOST}" )

    # Append any OneData overrides
    helm_args+=( "${onedata_args[@]+"${onedata_args[@]}"}" )

    log "Deploying release '$RELEASE' into namespace '$NAMESPACE':"
    info "  GUI image tag: ${GUI_IMAGE_TAG}"
    info "  Controller image tag: ${CTRL_IMAGE_TAG}"

    helm "${helm_args[@]}"

    print_deploy_summary
}

# Uninstall the Helm release. PVCs are intentionally kept!
do_teardown() {
    check_tools

    log "Uninstalling release '$RELEASE' from namespace '$NAMESPACE'..."
    helm uninstall "$RELEASE" -n "$NAMESPACE" 2>/dev/null \
        || warn "Release '$RELEASE' not found!"

    # Remove orphaned Jobs/Pods created by the Scipion controller at runtime
    kubectl delete jobs -n "$NAMESPACE" -l 'app=scipion-tool' --ignore-not-found
    kubectl delete pods -n "$NAMESPACE" -l 'app=scipion-tool' \
        --ignore-not-found --force --grace-period=0 2>/dev/null || true

    log "Release removed successfully!"
}

# Uninstall the release AND delete all associated PVCs.
do_purge() {
    do_teardown

    warn "Deleting all PVCs for release '$RELEASE' in namespace '$NAMESPACE'..."
    warn "This is irreversible, so all Scipion project data will be lost!"
    read -r -p "Type 'yes' to confirm: " confirm
    [[ "$confirm" == "yes" ]] \
        || { log "Aborted."; exit 0; }

    kubectl delete pvc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" --ignore-not-found

    log "PVCs deleted."
}

# Print a concise overview of the running deployment.
do_status() {
    check_tools

    log "Release: $RELEASE  |  Namespace: $NAMESPACE"
    echo ''

    info "--- Helm release ---"
    helm status "$RELEASE" -n "$NAMESPACE" 2>/dev/null \
        || warn "Release '$RELEASE' not found in namespace '$NAMESPACE'"

    echo ''
    info "--- Pods ---"
    kubectl get pods -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" \
        -o wide 2>/dev/null || true

    echo ''
    info "--- Services ---"
    kubectl get svc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "--- Ingress ---"
    kubectl get ingress -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true

    echo ''
    info "--- PVCs ---"
    kubectl get pvc -n "$NAMESPACE" \
        -l "app.kubernetes.io/instance=${RELEASE}" 2>/dev/null || true
}

# Print a detailed help.
do_help() {
    echo -e ""
    echo -e "${BOLD}deploy-cerit.sh${NC} - Scipion deployment helper for CERIT-SC Kubernetes"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  export KUBECONFIG=/path/to/cluster.yaml"
    echo -e "  deploy-cerit.sh <command> [RELEASE] [NAMESPACE]"
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
    echo -e "  ${CYAN}KUBECONFIG${NC}        Path to CERIT Rancher kubeconfig"
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

# Stream live logs from the controller pod.
do_logs() {
    check_tools

    log "Tailing controller logs for release '$RELEASE' in namespace '$NAMESPACE'..."
    kubectl logs -n "$NAMESPACE" \
        -l "app.kubernetes.io/name=scipion-controller,app.kubernetes.io/instance=${RELEASE}" \
        --tail=200 -f
}

# Main entry point, dispatch based on the command
case "$ACTION" in
    deploy)   do_deploy   ;;
    teardown) do_teardown ;;
    purge)    do_purge    ;;
    status)   do_status   ;;
    logs)     do_logs     ;;
    help)     do_help     ;;
esac
