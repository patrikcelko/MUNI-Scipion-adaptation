#!/usr/bin/env bash

# Scipion deployment helper for OpenStack (e-INFRA CZ)
# ====================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMON_DIR="$SCRIPT_DIR/common"

# shellcheck source=controls/common/logging.sh
source "$COMMON_DIR/logging.sh"

ACTION="${1:-deploy}"
INSTANCE_ID="${2:-1}"

case "$ACTION" in
    deploy|teardown|status|help) ;;
    -h|--help)
        ACTION=help
        ;;
    *)
        err "Unknown command: '$ACTION'. Use: deploy | teardown | status | help"
        ;;
esac

# Configuration
CLOUD_INIT="${CLOUD_INIT:-$SCRIPT_DIR/openstack/cloud-init.yaml}"

# Instance identity
INSTANCE_NAME="scipion-k8s-${INSTANCE_ID}"
SECGROUP_NAME="${SECGROUP_NAME:-scipion-${INSTANCE_ID}}"

# OpenStack resource settings
FLAVOR="${FLAVOR:-e1.large}"
IMAGE="${IMAGE:-ubuntu-noble-x86_64}"
NETWORK="${NETWORK:-internal-ipv4-general-private}"
KEYPAIR_NAME="${KEYPAIR_NAME:-scipion-key}"
FLOATING_IP="${FLOATING_IP:-}"
SSH_PUBKEY="${SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}"
K8S_CHANNEL="${K8S_CHANNEL:-1.30/stable}"
RENDERED_CLOUD_INIT=''

# Port allocation, each instance gets unique NodePorts
VNC_NODEPORT=$((31334 + INSTANCE_ID)) # Instance 1 -> 31335, 2 -> 31336, ...
MONITOR_NODEPORT=$((30079 + INSTANCE_ID))  # Instance 1 -> 30080, 2 -> 30081, ...
VNC_PASSWORD="${VNC_PASSWORD:-}"

# shellcheck source=controls/common/utils.sh
source "$COMMON_DIR/utils.sh"

# Verify required CLI tools are present and OpenStack auth is active.
check_tools() {
    command -v openstack >/dev/null \
        || err 'OpenStack CLI not found!'

    command -v jq >/dev/null \
        || err 'jq not found!'

    openstack token issue >/dev/null 2>&1 \
        || err 'OpenStack auth failed!'

    [[ -f "$SSH_PUBKEY" ]] \
        || err "SSH public key not found: $SSH_PUBKEY"

    [[ -f "$CLOUD_INIT" ]] \
        || err "Cloud-init template not found: $CLOUD_INIT"
}

# Render the cloud-init template, substituting variables like SSH key, ports and floating IP.
render_cloud_init() {
    RENDERED_CLOUD_INIT=$(mktemp --suffix=.yaml)

    # shellcheck disable=SC2064
    trap "rm -f '${RENDERED_CLOUD_INIT}'" EXIT

    local src key
    src=$(<"$CLOUD_INIT")
    key=$(tr -d '\n' <"$SSH_PUBKEY")

    src="${src//%%SSH_PUBKEY%%/$key}"
    src="${src//%%INSTANCE_ID%%/$INSTANCE_ID}"
    src="${src//%%FLOATING_IP%%/$FLOATING_IP}"
    src="${src//%%VNC_PASSWORD%%/$VNC_PASSWORD}"
    src="${src//%%K8S_CHANNEL%%/$K8S_CHANNEL}"
    src="${src//%%VNC_NODEPORT%%/$VNC_NODEPORT}"
    src="${src//%%MONITOR_NODEPORT%%/$MONITOR_NODEPORT}"

    printf '%s\n' "$src" > "$RENDERED_CLOUD_INIT"
}

# Print a summary after a successful deployment.
print_deploy_summary() {
    echo ''
    info "Scipion OpenStack deployment summary:"
    info "  Instance: $INSTANCE_NAME (ID: $INSTANCE_ID)"
    info "  Floating IP: $FLOATING_IP"
    info "  Flavor: $FLAVOR"
    info "  K8s channel: $K8S_CHANNEL"
    info "  noVNC URL: http://$FLOATING_IP:$VNC_NODEPORT"
    info "  Monitor URL: http://$FLOATING_IP:$MONITOR_NODEPORT"
    info "  VNC pass: $VNC_PASSWORD"
    echo ''
    warn "To deploy another instance run:"
    warn "  ./deploy-openstack.sh deploy $((INSTANCE_ID + 1))"
}

# Create keypair, security group, render cloud-init, launch instance, assign FIP.
do_deploy() {
    check_tools

    if [[ -z "$VNC_PASSWORD" ]]; then
        VNC_PASSWORD="$(random_password)"
        info "No VNC_PASSWORD set, generated one: $VNC_PASSWORD"
    fi

    info "Deploying Scipion on OpenStack:"
    info "  Instance: $INSTANCE_NAME"
    info "  Flavor: $FLAVOR"
    info "  Image: $IMAGE"
    info "  Network: $NETWORK"
    info "  K8s channel: $K8S_CHANNEL"
    info "  VNC port: $VNC_NODEPORT"
    info "  Monitor port: $MONITOR_NODEPORT"

    if openstack keypair show "$KEYPAIR_NAME" >/dev/null 2>&1; then
        info "Key pair '$KEYPAIR_NAME' already exists."
    else
        info "Creating key pair '$KEYPAIR_NAME'..."
        openstack keypair create --public-key "$SSH_PUBKEY" "$KEYPAIR_NAME"
    fi

    # Per-instance security group with dedicated port rules
    if openstack security group show "$SECGROUP_NAME" >/dev/null 2>&1; then
        info "Security group '$SECGROUP_NAME' already exists."
    else
        info "Creating security group '$SECGROUP_NAME'..."

        openstack security group create "$SECGROUP_NAME" \
            --description "Scipion K8s instance ${INSTANCE_ID}"

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol tcp --dst-port 22 --remote-ip 0.0.0.0/0 \
            --description 'SSH'

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol tcp --dst-port "${VNC_NODEPORT}" --remote-ip 0.0.0.0/0 \
            --description 'Scipion noVNC'

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol tcp --dst-port "${MONITOR_NODEPORT}" --remote-ip 0.0.0.0/0 \
            --description 'Task Monitor'

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol tcp --dst-port 80 --remote-ip 0.0.0.0/0 \
            --description 'HTTP'

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol tcp --dst-port 443 --remote-ip 0.0.0.0/0 \
            --description 'HTTPS'

        openstack security group rule create "$SECGROUP_NAME" \
            --protocol icmp --remote-ip 0.0.0.0/0 \
            --description 'Ping'
    fi

    # Floating IP - resolve before rendering cloud-init so %%FLOATING_IP%% is known
    if [[ -z "$FLOATING_IP" ]]; then
        FLOATING_IP=$(openstack floating ip list --status DOWN \
            -f value -c 'Floating IP Address' | head -1 || true)

        if [[ -z "$FLOATING_IP" ]]; then
            info "Allocating new floating IP..."
            FLOATING_IP=$(openstack floating ip create external-ipv4-general-public \
                -f value -c floating_ip_address)
        fi
    fi

    info "Floating IP: $FLOATING_IP"

    # Render cloud-init template - substitutes SSH key, ports and floating IP
    info "Rendering cloud-init template..."
    render_cloud_init || err "Failed to render cloud-init template!"

    # Launch instance
    if openstack server show "$INSTANCE_NAME" >/dev/null 2>&1; then
        warn "Instance '$INSTANCE_NAME' already exists - skipping creation."
    else
        info "Launching instance '$INSTANCE_NAME'..."
        openstack server create "$INSTANCE_NAME" \
            --flavor "$FLAVOR" \
            --image "$IMAGE" \
            --network "$NETWORK" \
            --key-name "$KEYPAIR_NAME" \
            --security-group "$SECGROUP_NAME" \
            --security-group 'default' \
            --user-data "$RENDERED_CLOUD_INIT" \
            --wait

        info "Instance created."
    fi

    local current_ips
    current_ips=$(openstack server show "$INSTANCE_NAME" -f json \
        | jq -r '.addresses' 2>/dev/null || echo '')

    if echo "$current_ips" | grep -qF "$FLOATING_IP"; then
        info "Floating IP $FLOATING_IP already associated."
    else
        info "Associating floating IP $FLOATING_IP..."
        openstack server add floating ip "$INSTANCE_NAME" "$FLOATING_IP"
    fi

    print_deploy_summary
}

# Disassociate floating IP, delete instance and its per-instance security group.
do_teardown() {
    check_tools

    info "Tearing down Scipion OpenStack instance '$INSTANCE_NAME'..."

    if openstack server show "$INSTANCE_NAME" >/dev/null 2>&1; then
        # Disassociate floating IP before deleting the instance
        local fip
        fip=$(openstack server show "$INSTANCE_NAME" -f json \
            | jq -r '.addresses' \
            | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' \
            | grep -vE '^(10\.|172\.(1[6-9]|2[0-9]|3[01])\.|192\.168\.)' \
            | head -1 || true)

        if [[ -n "$fip" ]]; then
            info "Removing floating IP $fip..."
            openstack server remove floating ip "$INSTANCE_NAME" "$fip" 2>/dev/null || true
        fi

        info "Deleting instance '$INSTANCE_NAME'..."
        openstack server delete "$INSTANCE_NAME" --wait
    else
        warn "Instance '$INSTANCE_NAME' not found - skipping."
    fi

    if openstack security group show "$SECGROUP_NAME" >/dev/null 2>&1; then
        info "Deleting security group '$SECGROUP_NAME'..."
        openstack security group delete "$SECGROUP_NAME"
    fi

    info "Teardown complete."
}

# Print a concise overview of the running OpenStack instance.
do_status() {
    check_tools

    info "OpenStack instance: $INSTANCE_NAME"
    echo ''

    if openstack server show "$INSTANCE_NAME" >/dev/null 2>&1; then
        openstack server show "$INSTANCE_NAME" \
            -f table -c name -c status -c flavor -c addresses -c key_name
    else
        warn "Instance '$INSTANCE_NAME' not found."
    fi
}

# Print a detailed help message.
do_help() {
    echo -e ""
    echo -e "${BOLD}deploy-openstack.sh${NC} - Scipion deployment helper for OpenStack (e-INFRA CZ)"
    echo -e ""
    echo -e "${BOLD}USAGE${NC}"
    echo -e "  source <project>-openrc.sh"
    echo -e "  deploy-openstack.sh <command> [INSTANCE_ID]"
    echo -e ""
    echo -e "  ${CYAN}INSTANCE_ID${NC} Instance number 1, 2, 3... Each gets unique NodePorts. (default: 1)"
    echo -e ""
    echo -e "${BOLD}COMMANDS${NC}"
    echo -e "  ${GREEN}deploy${NC}    Create keypair, security group, launch instance and assign floating IP."
    echo -e "  ${GREEN}teardown${NC}  Remove instance and its security group. Shared keypair is kept."
    echo -e "  ${GREEN}status${NC}    Show current instance state from OpenStack."
    echo -e "  ${GREEN}help${NC}      Show this help message."
    echo -e ""
    echo -e "${BOLD}ENVIRONMENT VARIABLES${NC}"
    echo -e "  ${CYAN}FLAVOR${NC}          OpenStack flavor (default: e1.large)"
    echo -e "  ${CYAN}IMAGE${NC}           OpenStack image name (default: ubuntu-noble-x86_64)"
    echo -e "  ${CYAN}NETWORK${NC}         OpenStack network name (default: internal-ipv4-general-private)"
    echo -e "  ${CYAN}KEYPAIR_NAME${NC}    Key pair name (shared) (default: scipion-key)"
    echo -e "  ${CYAN}SECGROUP_NAME${NC}   Security group name (default: scipion-<INSTANCE_ID>)"
    echo -e "  ${CYAN}FLOATING_IP${NC}     Reuse a specific FIP (auto-detected if unset)"
    echo -e "  ${CYAN}VNC_PASSWORD${NC}    VNC password (auto-generated if unset)"
    echo -e "  ${CYAN}SSH_PUBKEY${NC}      Path to SSH public key (default: ~/.ssh/id_ed25519.pub)"
    echo -e "  ${CYAN}K8S_CHANNEL${NC}     MicroK8s snap channel (default: 1.30/stable)"
    echo -e "  ${CYAN}CLOUD_INIT${NC}      Path to cloud-init file (default: controls/openstack/cloud-init.yaml)"
    echo -e ""
    echo -e "${BOLD}PORT ALLOCATION${NC}"
    echo -e "  noVNC      31334 + INSTANCE_ID (1 -> 31335, 2 -> 31336, ...)"
    echo -e "  Monitor    30079 + INSTANCE_ID (1 -> 30080, 2 -> 30081, ...)"
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
    status)
        do_status
        ;;
    help)
        do_help
        ;;
esac
