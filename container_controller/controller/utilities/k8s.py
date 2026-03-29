"""
Kubernetes clients
==================
"""

from kubernetes import client, config

try:
    config.load_incluster_config()
except Exception:
    config.load_kube_config()

core: client.CoreV1Api = client.CoreV1Api()
"""`CoreV1Api` - pods, events, nodes, logs, namespaces."""

batch: client.BatchV1Api = client.BatchV1Api()
"""`BatchV1Api` - jobs."""

custom_api: client.CustomObjectsApi = client.CustomObjectsApi()
"""`CustomObjectsApi` - metrics-server resources."""
