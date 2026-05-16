#!/usr/bin/env python3

"""
Registry tag helper
===================

Query a Docker Registry v2 API for available image tags.
"""

import sys
import json
import base64
import re
import os

import urllib.request
import urllib.error

from typing import Any


def load_credentials(host: str) -> str:
    """Return 'user:password' for host from ~/.docker/config.json."""

    try:
        cfg_path = os.path.expanduser('~/.docker/config.json')
        with open(cfg_path) as fh:
            cfg = json.load(fh)

        for registry_key, entry in cfg.get('auths', {}).items():
            if host in registry_key:
                raw = entry.get('auth', '')
                if raw:
                    return base64.b64decode(raw).decode()
    except Exception:
        pass
    return ''


def fetch(url: str, headers: dict | None = None) -> Any:
    """GET url with optional headers, returns response or HTTPError."""

    req = urllib.request.Request(url, headers=headers or {})
    try:
        return urllib.request.urlopen(req, timeout=10)
    except urllib.error.HTTPError as exc:
        return exc


def bearer_token(www_auth: str, basic_headers: dict) -> str:
    """Resolve Bearer token from WWW-Authenticate challenge header."""

    realm = re.search(r'realm="([^"]+)"', www_auth)
    service = re.search(r'service="([^"]+)"', www_auth)
    scope = re.search(r'scope="([^"]+)"', www_auth)

    if not realm:
        return ''

    token_url = realm.group(1)
    qs_parts = [
        f'{k}={m.group(1)}'
        for k, m in [('service', service), ('scope', scope)]
        if m
    ]

    if qs_parts:
        token_url += '?' + '&'.join(qs_parts)

    resp = fetch(token_url, basic_headers)
    if getattr(resp, 'status', 0) == 200:
        return json.load(resp).get('token', '')

    return ''


def list_tags(host: str, image_path: str) -> list[str]:
    """Return sorted (newest first) list of tags for image_path on host."""

    url = f'https://{host}/v2/{image_path}/tags/list'

    creds = load_credentials(host)
    basic_headers = (
        {'Authorization': 'Basic ' + base64.b64encode(creds.encode()).decode()}
        if creds
        else {}
    )

    resp = fetch(url, basic_headers)

    if getattr(resp, 'status', 0) == 401:
        www_auth = resp.headers.get('WWW-Authenticate', '')
        token = bearer_token(www_auth, basic_headers)
        if token:
            resp = fetch(url, {'Authorization': f'Bearer {token}'})

    if getattr(resp, 'status', 0) != 200:
        sys.exit(1)

    tags = json.load(resp).get('tags') or []
    return sorted(tags, reverse=True)


def main() -> None:
    if len(sys.argv) != 3:
        print(
            f'Usage: {sys.argv[0]} <host> <repository/image>', file=sys.stderr
        )
        sys.exit(2)

    host, image_path = sys.argv[1], sys.argv[2]
    tags = list_tags(host, image_path)

    if not tags:
        print('(no tags found)')
        return

    for tag in tags[:15]:
        print(tag)


if __name__ == "__main__":
    main()
