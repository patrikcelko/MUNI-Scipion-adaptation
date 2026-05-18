# MUNI-Scipion-adaptation

This repository contains the implementation of the master's thesis Adapting Scipion software to run in EOSC Data Player made by Patrik Čelko at the Faculty of Informatics, Masaryk University.

The primary goal of this work was to adapt the [Scipion](https://scipion.i2pc.es/) cryo-EM framework, originally designed as a monolithic HPC application for containerised deployment on Kubernetes, without modifying Scipions own source code. The adaptation introduces a lightweight controller that intercepts Scipions native `qsub`/`qstat`/`qdel` queue calls and translates them into Kubernetes Jobs, a TurboVNC/noVNC GUI container providing browser-based remote desktop access with hardware-accelerated 3D rendering via VirtualGL, and individual tool containers for each computational plugin (Relion, Xmipp, CTFFind4, MotionCor2, Gctf, EMAN2). The entire system is packaged as a Helm chart for one-command cluster deployment.

Additionally, the system is integrated with the [EOSC Data Player (Dispatcher)](https://github.com/EOSC-Data-Commons/Dispatcher) through a dedicated `VREScipion` plugin, enabling automated workflow submission via [RO-Crate](https://www.researchobject.org/ro-crate/) objects. Remote dataset access is handled transparently via a OneData FUSE sidecar injected into each tool pod.

## Controls

All deployment and image management scripts live in the `controls/` directory. Each script is self-documenting using command `help` to print its full usage.

### Local Deploy

Deploys Scipion onto a locally accessible Kubernetes cluster. Supports both **MicroK8s**and any standard `kubectl` clusters.

```bash
# Deploy with defaults (MicroK8s, namespace: scipion-local)
./controls/deploy-local.sh deploy

# Deploy a named release into a custom namespace
./controls/deploy-local.sh deploy my-release my-namespace

# Check status of the running deployment
./controls/deploy-local.sh status

# Tail live controller logs
./controls/deploy-local.sh logs

# Uninstall the release (PVCs are kept)
./controls/deploy-local.sh teardown

# Uninstall and delete all PVCs (irreversible, prompts for confirmation)
./controls/deploy-local.sh purge
```

| Environment Variable | Description | Default |
| -------------------- | ----------- | ------- |
| `CLUSTER_TYPE` | Local backend: `microk8s` or `k8s` | `microk8s` |
| `VNC_PASSWORD` | VNC password for the remote desktop | auto-generated |
| `GUI_IMAGE_TAG` | Tag of the GUI image to deploy | `latest` |
| `CTRL_IMAGE_TAG` | Tag of the controller image to deploy | `latest` |
| `STORAGE_CLASS` | Kubernetes storage class | auto-detected |
| `NODE_PORT_GUI` | NodePort for the noVNC interface | `31335` |
| `NODE_PORT_CTRL` | NodePort for the controller REST API | `30080` |
| `SCIPION_NAMESPACE` | Default namespace override | - |
| `HELM_CHART` | Path to the Helm chart directory | `helm/` |
| `VALUES_LOCAL` | Optional per-host value overrides | `controls/values-local.yaml` |

**OneData variables** (all optional):

| Variable | Description |
| -------- | ----------- |
| `ONEDATA_TOKEN` | OneData access token |
| `ONEDATA_PROVIDER` | Oneprovider hostname |
| `ONEDATA_SPACE` | Space name to mount |

After a successful deploy the script prints a summary including the **noVNC URL** and generated VNC password.

> **Note:** For MicroK8s deployments the script automatically creates a `.mount_projects/` directory in the repository root as the backing store for the hostpath PersistentVolume.

---

### OpenStack Deploy

Provisions a full Scipion Kubernetes environment on the **e-INFRA CZ OpenStack** cloud from scratch. The script creates an SSH keypair, a dedicated per-instance security group with the required port rules, renders a `cloud-init` template that bootstraps MicroK8s and installs the Scipion Helm chart on the new VM, launches an `e1.large` Ubuntu 24.04 instance, and assigns a floating IP.

Multiple parallel instances are supported, each `INSTANCE_ID` automatically receives unique NodePorts to avoid conflicts.

```bash
# Source your OpenStack RC file first
source <project>-openrc.sh

# Deploy instance 1 (default)
./controls/deploy-openstack.sh deploy

# Deploy a second parallel instance
./controls/deploy-openstack.sh deploy 2

# Check current instance state
./controls/deploy-openstack.sh status 1

# Remove instance and its security group
./controls/deploy-openstack.sh teardown 1
```

| Environment Variable | Description | Default |
| -------------------- | ----------- | ------- |
| `FLAVOR` | OpenStack instance flavor | `e1.large` |
| `IMAGE` | OpenStack image name | `ubuntu-noble-x86_64` |
| `NETWORK` | OpenStack network | `internal-ipv4-general-private` |
| `KEYPAIR_NAME` | SSH keypair name (shared across instances) | `scipion-key` |
| `SECGROUP_NAME` | Security group name | `scipion-<INSTANCE_ID>` |
| `FLOATING_IP` | Reuse a specific floating IP | auto-detected |
| `VNC_PASSWORD` | VNC password | auto-generated |
| `SSH_PUBKEY` | Path to SSH public key | `~/.ssh/id_ed25519.pub` |
| `K8S_CHANNEL` | MicroK8s snap channel | `1.30/stable` |
| `GUI_IMAGE_TAG` | Scipion GUI image tag | `latest` |
| `CTRL_IMAGE_TAG` | Scipion controller image tag | `latest` |
| `CLOUD_INIT` | Path to cloud-init template | `controls/openstack/cloud-init.yaml` |

**Port allocation per instance ID:**

| Service | Formula | Instance 1 | Instance 2 |
| ------- | ------- | ---------- | ---------- |
| noVNC | 31334 + ID | 31335 | 31336 |
| Task Monitor | 30079 + ID | 30080 | 30081 |

---

### Rancher Deploy

Deploys Scipion onto an existing Rancher managed Kubernetes cluster such as the CERIT-SC infrastructure. Requires a valid `KUBECONFIG` pointing at the target cluster. Uses NFS-CSI storage and a `ClusterIP` service type and access is provided through an NGINX Ingress with an automatically derived hostname following the CERIT pattern `<release>.<namespace>.dyn.cloud.e-infra.cz`.

```bash
# Set cluster credentials
export KUBECONFIG=/path/to/rancher-cluster.yaml

# Deploy with defaults (release: scipion, namespace: celko-ns)
./controls/deploy-rancher.sh deploy

# Deploy with a custom release name and namespace
./controls/deploy-rancher.sh deploy my-release my-namespace

# Check pods, services, ingress and PVCs
./controls/deploy-rancher.sh status

# Tail live controller logs
./controls/deploy-rancher.sh logs

# Uninstall release (PVCs are kept)
./controls/deploy-rancher.sh teardown

# Uninstall and delete all PVCs (irreversible, prompts for confirmation)
./controls/deploy-rancher.sh purge
```

| Environment Variable | Description | Default |
| -------------------- | ----------- | ------- |
| `KUBECONFIG` | Path to Rancher kubeconfig | `~/.kube/config` |
| `INGRESS_HOST` | noVNC ingress hostname | `<release>.<namespace>.dyn.cloud.e-infra.cz` |
| `VNC_PASSWORD` | VNC password | auto-generated |
| `GUI_IMAGE_TAG` | GUI image tag to deploy | `latest` |
| `CTRL_IMAGE_TAG` | Controller image tag to deploy | `latest` |
| `SCIPION_NAMESPACE` | Default namespace override | - |
| `HELM_CHART` | Path to Helm chart directory | `helm/` |

**OneData variables** (all optional):

| Variable | Description |
| -------- | ----------- |
| `ONEDATA_TOKEN` | OneData access token |
| `ONEDATA_PROVIDER` | Oneprovider hostname |
| `ONEDATA_SPACE` | Space name to mount |

## Build & Push

### Infrastructure Images

Builds and publishes the two core infrastructure images: the **Scipion GUI** container (`scipion3-remote`) and the **Container Controller** (`container-controller`). Both Dockerfiles reside under `docker/`.

```bash
# Build both images locally tagged v1.2.0
./controls/build-infra.sh build all v1.2.0

# Build only the GUI image
./controls/build-infra.sh build gui v1.2.0

# Build only the controller image
./controls/build-infra.sh build controller v1.2.0

# Push already-built images to the registry
./controls/build-infra.sh push all v1.2.0

# Build and push in a single step
./controls/build-infra.sh build-push all v1.2.0

# Show the latest tags currently available on the registry
./controls/build-infra.sh latest all
```

| Environment Variable | Description | Default |
| -------------------- | ----------- | ------- |
| `REGISTRY` | Docker registry base URL | `cerit.io/scipion` |
| `GUI_IMAGE` | GUI image name | `scipion3-remote` |
| `CTRL_IMAGE` | Controller image name | `container-controller` |

---

### Tool Images

Builds and publishes individual computational tool images. Each tool has its own directory under `docker/tools/` with a `Dockerfile`. Tools that also ship a `Dockerfile.gpu` automatically get a second image tagged `<tool>-gpu` built alongside the CPU variant.

Available tools: `relion`, `xmipp`, `ctffind4`, `motioncor2`, `gctf`, `eman2`.

```bash
# List all buildable tools
./controls/build-tools.sh list

# Build all tools tagged v2.0.0
./controls/build-tools.sh build all v2.0.0

# Build a single tool
./controls/build-tools.sh build relion v2.0.0

# Push all tools to the registry
./controls/build-tools.sh push all v2.0.0

# Build and push a single tool in one step
./controls/build-tools.sh build-push xmipp v2.0.0

# Show latest tags on the registry for all tools
./controls/build-tools.sh latest all
```

| Environment Variable | Description | Default |
| -------------------- | ----------- | ------- |
| `REGISTRY` | Docker registry base URL | `cerit.io/scipion` |

> **Note:** Tools with `Dockerfile.gpu` produce both a CPU image `<tool>:VERSION` and a GPU-accelerated image `<tool>-gpu:VERSION` automatically.

## License

Copyright 2025-2026, created by Patrik Čelko, see [LICENSE](LICENSE) for more details.
