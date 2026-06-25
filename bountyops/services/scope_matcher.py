
from __future__ import annotations

import fnmatch
from urllib.parse import urlparse

from ..models import ScopeItem


def scope_has_path(value: str) -> bool:
    value = (value or "").strip()
    if "://" in value:
        parsed = urlparse(value)
        return bool(parsed.path and parsed.path not in {"", "/"})
    if "/" in value:
        host, path = value.split("/", 1)
        return bool(path.strip("/"))
    return False


def normalize_scope_value(value: str) -> str:
    value = value.strip()
    if not value:
        return value

    if "://" in value:
        parsed = urlparse(value)
        host = parsed.netloc or parsed.path
    else:
        host = value.split("/", 1)[0]

    host = host.split("@")[-1]
    host = host.split(":")[0]
    return host.lower().strip(".")


def normalize_host(host: str) -> str:
    host = (host or "").lower().strip()
    host = host.split("@")[-1]
    host = host.split(":")[0]
    return host.strip(".")


def host_matches_scope(host: str, scope_value: str) -> bool:
    """
    Host-only scope matcher.

    Important v0.3.2 guard:
    If a scope value contains a path, e.g. https://github.com/vercel/next.js,
    do NOT treat github.com as fully in-scope. Path-aware matching can be added
    later when endpoint path is available.
    """
    if scope_has_path(scope_value):
        return False

    host = normalize_host(host)
    scope = normalize_scope_value(scope_value)

    if not host or not scope:
        return False

    if scope.startswith("*."):
        suffix = scope[2:]
        return host == suffix or host.endswith("." + suffix)

    if "*" in scope:
        return fnmatch.fnmatch(host, scope)

    return host == scope or host.endswith("." + scope)


def classify_scope(host: str, in_scopes: list[ScopeItem], out_scopes: list[ScopeItem]) -> str:
    for item in out_scopes:
        if host_matches_scope(host, item.value):
            return "out"

    for item in in_scopes:
        if host_matches_scope(host, item.value):
            return "in"

    return "unknown"
