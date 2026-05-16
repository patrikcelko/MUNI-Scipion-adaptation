#!/usr/bin/env bash

# OneData utilities
# =================

# Create/update OneData Kubernetes secret and print Helm --set= flags.
provision_onedata_secret() {
    [[ -z "${ONEDATA_TOKEN:-}" ]] && return 0

    local kctl="${KUBECTL:-kubectl}"

    info 'OneData integration enabled, provisioning secret scipion-onedata-token...'

    $kctl -n "$NAMESPACE" create secret generic scipion-onedata-token \
        --from-literal=token="$ONEDATA_TOKEN" \
        --dry-run=client -o yaml | $kctl apply -f -

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
