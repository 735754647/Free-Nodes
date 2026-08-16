from __future__ import annotations

import base64
import html
import json
import re
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlsplit

import yaml

from .models import Node


SUPPORTED_SCHEMES = ("vless", "vmess", "trojan", "ss", "hysteria2", "hy2", "tuic")
URI_PATTERN = re.compile(
    rf"(?:{'|'.join(SUPPORTED_SCHEMES)})://[^\s\"'<>]+",
    re.IGNORECASE,
)


def _b64decode(value: str) -> bytes:
    compact = "".join(value.split())
    compact += "=" * (-len(compact) % 4)
    return base64.urlsafe_b64decode(compact.encode("ascii"))


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _truthy(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _normalize_ss_cipher(value: str) -> str:
    aliases = {
        "chacha20-poly1305": "chacha20-ietf-poly1305",
        "xchacha20-poly1305": "xchacha20-ietf-poly1305",
    }
    normalized = value.strip().lower()
    normalized = aliases.get(normalized, normalized)
    aes_methods = {
        f"aes-{bits}-{mode}"
        for bits in (128, 192, 256)
        for mode in ("ctr", "cfb", "gcm", "ccm")
    }
    supported = aes_methods | {
        "aes-128-gcm-siv",
        "aes-256-gcm-siv",
        "chacha20-ietf",
        "chacha20",
        "xchacha20",
        "chacha20-ietf-poly1305",
        "xchacha20-ietf-poly1305",
        "chacha8-ietf-poly1305",
        "xchacha8-ietf-poly1305",
        "2022-blake3-aes-128-gcm",
        "2022-blake3-aes-256-gcm",
        "2022-blake3-chacha20-poly1305",
        "lea-128-gcm",
        "lea-192-gcm",
        "lea-256-gcm",
        "rabbit128-poly1305",
        "aegis-128l",
        "aegis-256",
        "aez-384",
        "deoxys-ii-256-128",
        "rc4-md5",
        "none",
    }
    if normalized not in supported:
        raise ValueError(f"unsupported Shadowsocks cipher: {normalized}")
    return normalized


def _credential(parsed: Any) -> str:
    authority = parsed.netloc.rsplit("@", 1)[0] if "@" in parsed.netloc else ""
    return unquote(authority)


def _host_for_uri(host: str) -> str:
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def _node_name(preferred: str, scheme: str, server: str, port: int) -> str:
    clean = preferred.strip()
    return clean or f"{scheme.upper()} {server}:{port}"


def extract_uris(text: str) -> list[str]:
    decoded = html.unescape(text).replace("\\/", "/").replace("\\u0026", "&")
    found = [match.rstrip(".,);]}") for match in URI_PATTERN.findall(decoded)]
    if found:
        return found

    stripped = "".join(decoded.split())
    if len(stripped) < 16:
        return []
    try:
        candidate = _b64decode(stripped).decode("utf-8", errors="strict")
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return []
    return [match.rstrip(".,);]}") for match in URI_PATTERN.findall(html.unescape(candidate))]


def parse_document(text: str, source: str) -> list[Node]:
    nodes: list[Node] = []
    for uri in extract_uris(text):
        try:
            nodes.append(parse_uri(uri, source))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            continue

    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        document = None
    if isinstance(document, dict) and isinstance(document.get("proxies"), list):
        for proxy in document["proxies"]:
            if not isinstance(proxy, dict):
                continue
            try:
                nodes.append(parse_clash_proxy(proxy, source))
            except (ValueError, KeyError, TypeError):
                continue
    return nodes


def parse_uri(uri: str, source: str) -> Node:
    scheme = uri.split(":", 1)[0].lower()
    if scheme == "vless":
        return _parse_vless(uri, source)
    if scheme == "vmess":
        return _parse_vmess(uri, source)
    if scheme == "trojan":
        return _parse_trojan(uri, source)
    if scheme == "ss":
        return _parse_shadowsocks(uri, source)
    if scheme in {"hysteria2", "hy2"}:
        return _parse_hysteria2(uri, source)
    if scheme == "tuic":
        return _parse_tuic(uri, source)
    raise ValueError(f"unsupported scheme: {scheme}")


def _apply_transport(proxy: dict[str, Any], query: dict[str, list[str]]) -> None:
    network = _first(query, "type", "tcp").lower()
    if network != "tcp":
        proxy["network"] = network

    if network == "ws":
        ws_options: dict[str, Any] = {"path": _first(query, "path", "/")}
        host = _first(query, "host")
        if host:
            ws_options["headers"] = {"Host": host}
        proxy["ws-opts"] = ws_options
    elif network == "grpc":
        service_name = _first(query, "serviceName") or _first(query, "service-name")
        proxy["grpc-opts"] = {"grpc-service-name": service_name}
    elif network == "httpupgrade":
        options: dict[str, Any] = {"path": _first(query, "path", "/")}
        host = _first(query, "host")
        if host:
            options["headers"] = {"Host": host}
        proxy["http-upgrade-opts"] = options


def _apply_tls(proxy: dict[str, Any], query: dict[str, list[str]]) -> None:
    security = _first(query, "security").lower()
    if security not in {"tls", "reality"}:
        return
    proxy["tls"] = True
    server_name = _first(query, "sni")
    if server_name:
        proxy["servername"] = server_name
    fingerprint = _first(query, "fp")
    if fingerprint:
        proxy["client-fingerprint"] = fingerprint
    if _truthy(_first(query, "insecure")) or _truthy(_first(query, "allowInsecure")):
        proxy["skip-cert-verify"] = True
    alpn = _first(query, "alpn")
    if alpn:
        proxy["alpn"] = [item.strip() for item in alpn.split(",") if item.strip()]
    if security == "reality":
        public_key = _first(query, "pbk")
        short_id = _first(query, "sid")
        if public_key:
            proxy["reality-opts"] = {"public-key": public_key, "short-id": short_id}


def _parse_vless(uri: str, source: str) -> Node:
    parsed = urlsplit(uri)
    if not parsed.hostname or not parsed.port or not parsed.username:
        raise ValueError("invalid VLESS URI")
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = _node_name(unquote(parsed.fragment), "vless", parsed.hostname, parsed.port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vless",
        "server": parsed.hostname,
        "port": parsed.port,
        "uuid": unquote(parsed.username),
        "udp": True,
    }
    flow = _first(query, "flow")
    if flow:
        proxy["flow"] = flow
    encryption = _first(query, "encryption", "none")
    if encryption != "none":
        proxy["encryption"] = encryption
    _apply_tls(proxy, query)
    _apply_transport(proxy, query)
    return Node(uri=uri, scheme="vless", name=name, clash=proxy, source=source)


def _parse_vmess(uri: str, source: str) -> Node:
    payload = uri.split("://", 1)[1].split("#", 1)[0]
    data = json.loads(_b64decode(payload).decode("utf-8"))
    server = str(data["add"])
    port = int(data["port"])
    name = _node_name(str(data.get("ps", "")), "vmess", server, port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "vmess",
        "server": server,
        "port": port,
        "uuid": str(data["id"]),
        "alterId": int(data.get("aid", 0) or 0),
        "cipher": str(data.get("scy", "auto") or "auto"),
        "udp": True,
    }
    network = str(data.get("net", "tcp") or "tcp")
    if network != "tcp":
        proxy["network"] = network
    if network == "ws":
        ws_options: dict[str, Any] = {"path": str(data.get("path", "/") or "/")}
        if data.get("host"):
            ws_options["headers"] = {"Host": str(data["host"])}
        proxy["ws-opts"] = ws_options
    elif network == "grpc":
        proxy["grpc-opts"] = {"grpc-service-name": str(data.get("path", ""))}
    if str(data.get("tls", "")).lower() in {"tls", "true", "1"}:
        proxy["tls"] = True
        if data.get("sni"):
            proxy["servername"] = str(data["sni"])
        if data.get("fp"):
            proxy["client-fingerprint"] = str(data["fp"])
    return Node(uri=uri, scheme="vmess", name=name, clash=proxy, source=source)


def _parse_trojan(uri: str, source: str) -> Node:
    parsed = urlsplit(uri)
    if not parsed.hostname or not parsed.port:
        raise ValueError("invalid Trojan URI")
    password = _credential(parsed)
    if not password:
        raise ValueError("missing Trojan password")
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = _node_name(unquote(parsed.fragment), "trojan", parsed.hostname, parsed.port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "trojan",
        "server": parsed.hostname,
        "port": parsed.port,
        "password": password,
        "udp": True,
    }
    server_name = _first(query, "sni")
    if server_name:
        proxy["sni"] = server_name
    if _truthy(_first(query, "allowInsecure")) or _truthy(_first(query, "insecure")):
        proxy["skip-cert-verify"] = True
    _apply_transport(proxy, query)
    return Node(uri=uri, scheme="trojan", name=name, clash=proxy, source=source)


def _parse_shadowsocks(uri: str, source: str) -> Node:
    main, _, fragment = uri.partition("#")
    raw = main.split("://", 1)[1]
    raw, _, query_string = raw.partition("?")
    if "@" not in raw:
        raw = _b64decode(raw).decode("utf-8")
    user_info, host_port = raw.rsplit("@", 1)
    if ":" not in user_info:
        user_info = _b64decode(user_info).decode("utf-8")
    method, password = user_info.split(":", 1)
    method = _normalize_ss_cipher(unquote(method))
    password = unquote(password)
    parsed_host = urlsplit(f"ss://x@{host_port}")
    if not parsed_host.hostname or not parsed_host.port:
        raise ValueError("invalid Shadowsocks URI")
    name = _node_name(unquote(fragment), "ss", parsed_host.hostname, parsed_host.port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "ss",
        "server": parsed_host.hostname,
        "port": parsed_host.port,
        "cipher": method,
        "password": password,
        "udp": True,
    }
    query = parse_qs(query_string, keep_blank_values=True)
    plugin = _first(query, "plugin")
    if plugin:
        parts = unquote(plugin).split(";")
        proxy["plugin"] = parts[0]
        options: dict[str, Any] = {}
        for item in parts[1:]:
            key, separator, value = item.partition("=")
            if not separator:
                options[key] = True
            elif value.lower() in {"true", "false"}:
                options[key] = value.lower() == "true"
            elif value.isdigit():
                options[key] = int(value)
            else:
                options[key] = value
        if options:
            proxy["plugin-opts"] = options
    credential = _b64encode(f"{method}:{password}".encode("utf-8"))
    normalized_uri = f"ss://{credential}@{_host_for_uri(parsed_host.hostname)}:{parsed_host.port}"
    if query_string:
        normalized_uri += f"?{query_string}"
    if fragment:
        normalized_uri += f"#{fragment}"
    return Node(uri=normalized_uri, scheme="ss", name=name, clash=proxy, source=source)


def _parse_hysteria2(uri: str, source: str) -> Node:
    parsed = urlsplit(uri)
    if not parsed.hostname or not parsed.port:
        raise ValueError("invalid Hysteria2 URI")
    password = _credential(parsed)
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = _node_name(unquote(parsed.fragment), "hysteria2", parsed.hostname, parsed.port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "hysteria2",
        "server": parsed.hostname,
        "port": parsed.port,
        "password": password,
    }
    server_name = _first(query, "sni")
    if server_name:
        proxy["sni"] = server_name
    if _truthy(_first(query, "insecure")):
        proxy["skip-cert-verify"] = True
    obfs = _first(query, "obfs")
    if obfs:
        proxy["obfs"] = obfs
        proxy["obfs-password"] = _first(query, "obfs-password")
    return Node(uri=uri, scheme="hysteria2", name=name, clash=proxy, source=source)


def _parse_tuic(uri: str, source: str) -> Node:
    parsed = urlsplit(uri)
    if not parsed.hostname or not parsed.port:
        raise ValueError("invalid TUIC URI")
    credential = _credential(parsed)
    uuid, separator, password = credential.partition(":")
    if not separator:
        raise ValueError("invalid TUIC credential")
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = _node_name(unquote(parsed.fragment), "tuic", parsed.hostname, parsed.port)
    proxy: dict[str, Any] = {
        "name": name,
        "type": "tuic",
        "server": parsed.hostname,
        "port": parsed.port,
        "uuid": uuid,
        "password": password,
        "udp-relay-mode": _first(query, "udp_relay_mode", "native"),
        "congestion-controller": _first(query, "congestion_control", "bbr"),
    }
    server_name = _first(query, "sni")
    if server_name:
        proxy["sni"] = server_name
    alpn = _first(query, "alpn")
    if alpn:
        proxy["alpn"] = [item for item in alpn.split(",") if item]
    if _truthy(_first(query, "allow_insecure")):
        proxy["skip-cert-verify"] = True
    return Node(uri=uri, scheme="tuic", name=name, clash=proxy, source=source)


def parse_clash_proxy(proxy: dict[str, Any], source: str) -> Node:
    clash = dict(proxy)
    scheme = str(clash.get("type", "")).lower()
    if scheme not in {"vless", "vmess", "trojan", "ss", "hysteria2", "tuic"}:
        raise ValueError("unsupported Clash proxy")
    if not clash.get("server") or not clash.get("port"):
        raise ValueError("missing Clash endpoint")
    name = str(clash.get("name") or f"{scheme.upper()} {clash['server']}:{clash['port']}")
    clash["name"] = name
    if scheme == "ss" and clash.get("cipher"):
        clash["cipher"] = _normalize_ss_cipher(str(clash["cipher"]))
    uri = clash_to_uri(clash)
    return Node(uri=uri, scheme=scheme, name=name, clash=clash, source=source)


def clash_to_uri(proxy: dict[str, Any]) -> str:
    scheme = str(proxy["type"]).lower()
    server = str(proxy["server"])
    port = int(proxy["port"])
    host = _host_for_uri(server)
    name = quote(str(proxy.get("name", "")))

    if scheme == "vmess":
        data: dict[str, Any] = {
            "v": "2",
            "ps": str(proxy.get("name", "")),
            "add": server,
            "port": str(port),
            "id": str(proxy["uuid"]),
            "aid": str(proxy.get("alterId", 0)),
            "scy": str(proxy.get("cipher", "auto")),
            "net": str(proxy.get("network", "tcp")),
            "type": "none",
            "host": "",
            "path": "",
            "tls": "tls" if proxy.get("tls") else "",
            "sni": str(proxy.get("servername", "")),
        }
        if proxy.get("network") == "ws":
            options = proxy.get("ws-opts", {})
            data["path"] = str(options.get("path", "/"))
            data["host"] = str(options.get("headers", {}).get("Host", ""))
        return f"vmess://{_b64encode(json.dumps(data, separators=(',', ':')).encode('utf-8'))}"

    if scheme == "ss":
        credential = _b64encode(f"{proxy['cipher']}:{proxy['password']}".encode("utf-8"))
        return f"ss://{credential}@{host}:{port}#{name}"

    if scheme == "vless":
        query: dict[str, str] = {"encryption": str(proxy.get("encryption", "none"))}
        query["security"] = "reality" if proxy.get("reality-opts") else ("tls" if proxy.get("tls") else "none")
        _transport_to_query(proxy, query)
        if proxy.get("servername"):
            query["sni"] = str(proxy["servername"])
        if proxy.get("client-fingerprint"):
            query["fp"] = str(proxy["client-fingerprint"])
        if proxy.get("flow"):
            query["flow"] = str(proxy["flow"])
        reality = proxy.get("reality-opts", {})
        if reality:
            query["pbk"] = str(reality.get("public-key", ""))
            query["sid"] = str(reality.get("short-id", ""))
        return f"vless://{quote(str(proxy['uuid']))}@{host}:{port}?{urlencode(query)}#{name}"

    if scheme == "trojan":
        query = {}
        _transport_to_query(proxy, query)
        if proxy.get("sni"):
            query["sni"] = str(proxy["sni"])
        return f"trojan://{quote(str(proxy['password']))}@{host}:{port}?{urlencode(query)}#{name}"

    if scheme == "hysteria2":
        query = {}
        if proxy.get("sni"):
            query["sni"] = str(proxy["sni"])
        if proxy.get("skip-cert-verify"):
            query["insecure"] = "1"
        if proxy.get("obfs"):
            query["obfs"] = str(proxy["obfs"])
            query["obfs-password"] = str(proxy.get("obfs-password", ""))
        return f"hysteria2://{quote(str(proxy['password']))}@{host}:{port}?{urlencode(query)}#{name}"

    if scheme == "tuic":
        query = {
            "congestion_control": str(proxy.get("congestion-controller", "bbr")),
            "udp_relay_mode": str(proxy.get("udp-relay-mode", "native")),
        }
        if proxy.get("sni"):
            query["sni"] = str(proxy["sni"])
        return (
            f"tuic://{quote(str(proxy['uuid']))}:{quote(str(proxy['password']))}"
            f"@{host}:{port}?{urlencode(query)}#{name}"
        )
    raise ValueError(f"cannot convert Clash proxy: {scheme}")


def _transport_to_query(proxy: dict[str, Any], query: dict[str, str]) -> None:
    network = str(proxy.get("network", "tcp"))
    query["type"] = network
    if network == "ws":
        options = proxy.get("ws-opts", {})
        query["path"] = str(options.get("path", "/"))
        host = options.get("headers", {}).get("Host")
        if host:
            query["host"] = str(host)
    elif network == "grpc":
        query["serviceName"] = str(proxy.get("grpc-opts", {}).get("grpc-service-name", ""))
