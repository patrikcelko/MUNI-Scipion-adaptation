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
    try:
        config.load_kube_config()
        logger.debug('Loaded local kubeconfig')
    except Exception:
        logger.warning('No Kubernetes configuration found; K8s API calls will fail at runtime.')

core: client.CoreV1Api = client.CoreV1Api()
"""`CoreV1Api` - pods, events, nodes, logs, namespaces."""

batch: client.BatchV1Api = client.BatchV1Api()
"""`BatchV1Api` - jobs."""

custom_api: client.CustomObjectsApi = client.CustomObjectsApi()
"""`CustomObjectsApi` - metrics-server resources."""
