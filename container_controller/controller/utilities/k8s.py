"""
Kubernetes clients
==================
"""

import logging

from kubernetes import client, config

logger = logging.getLogger(__name__)

try:
    config.load_incluster_config()
    logger.debug('Loaded in-cluster Kubernetes config')
except Exception:
    logger.warning(
        'In-cluster config unavailable, falling back to local kubeconfig.',
    )
    config.load_kube_config()

core: client.CoreV1Api = client.CoreV1Api()
"""`CoreV1Api` - pods, events, nodes, logs, namespaces."""

batch: client.BatchV1Api = client.BatchV1Api()
"""`BatchV1Api` - jobs."""

custom_api: client.CustomObjectsApi = client.CustomObjectsApi()
"""`CustomObjectsApi` - metrics-server resources."""
