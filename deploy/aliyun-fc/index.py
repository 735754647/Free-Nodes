# -*- coding: utf-8 -*-
"""Alibaba Cloud Function Compute HTTP handler for TCP endpoint rechecks.

Set the Function Compute handler entry to ``index.handler``.
The function intentionally performs only a TCP connection check. Protocol,
TLS/SNI, and Google 204 checks are performed by Mihomo in GitHub Actions.
"""

import json
import socket


def handler(event, context):
    """Return ``ok`` when the requested host:port accepts a TCP connection."""
    if isinstance(event, bytes):
        try:
            event = json.loads(event.decode("utf-8"))
        except Exception:
            event = {}

    params = event.get("queryStringParameters") or event.get("queryParameters") or {}
    host = str(params.get("ip") or "").strip()

    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]

    try:
        port = int(params.get("port"))
    except (TypeError, ValueError):
        return {"statusCode": 400, "body": "fail"}

    if not host or not 1 <= port <= 65535:
        return {"statusCode": 400, "body": "fail"}

    try:
        with socket.create_connection((host, port), timeout=4):
            pass
        return {"statusCode": 200, "body": "ok"}
    except OSError:
        return {"statusCode": 200, "body": "fail"}
