from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from email.parser import Parser
from typing import Iterable
from urllib.parse import urlparse, parse_qsl


@dataclass(slots=True)
class ParsedEndpoint:
    method: str
    scheme: str
    host: str
    port: int | None
    path: str
    query_keys: list[str]
    status_code: int | None
    content_type: str
    auth_present: bool
    state_changing: bool
    raw_request: str
    raw_response: str

    @property
    def full_path(self) -> str:
        return self.path or "/"


STATE_CHANGING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _headers_to_dict(headers: list[dict]) -> dict[str, str]:
    out = {}
    for h in headers or []:
        name = h.get("name", "")
        value = h.get("value", "")
        if name:
            out[name] = value
    return out


def _raw_from_har_message(msg: dict) -> str:
    if "text" in msg and isinstance(msg["text"], str):
        return msg["text"]
    return ""


def parse_har(text: str) -> list[ParsedEndpoint]:
    data = json.loads(text)
    entries = data.get("log", {}).get("entries", [])
    endpoints: list[ParsedEndpoint] = []

    for entry in entries:
        req = entry.get("request", {})
        res = entry.get("response", {})
        method = str(req.get("method", "GET")).upper()
        url = req.get("url", "")
        parsed = urlparse(url)
        host = parsed.hostname or ""
        scheme = parsed.scheme or ""
        port = parsed.port
        path = parsed.path or "/"
        query_keys = sorted({k for k, _ in parse_qsl(parsed.query, keep_blank_values=True)})

        req_headers = _headers_to_dict(req.get("headers", []))
        res_headers = _headers_to_dict(res.get("headers", []))
        auth_present = any(k.lower() in {"authorization", "cookie", "x-api-key", "x-auth-token"} for k in req_headers)
        content_type = ""
        for k, v in res_headers.items():
            if k.lower() == "content-type":
                content_type = v
                break

        raw_request_lines = [f"{method} {parsed.path or '/'}{'?' + parsed.query if parsed.query else ''} HTTP/1.1"]
        if host:
            raw_request_lines.append(f"Host: {host}")
        for k, v in req_headers.items():
            raw_request_lines.append(f"{k}: {v}")

        post_data = req.get("postData", {})
        if post_data.get("text"):
            raw_request_lines.append("")
            raw_request_lines.append(post_data.get("text", ""))

        raw_response_lines = [f"HTTP/1.1 {res.get('status', '')} {res.get('statusText', '')}".strip()]
        for k, v in res_headers.items():
            raw_response_lines.append(f"{k}: {v}")
        content = res.get("content", {})
        body = content.get("text", "")
        if content.get("encoding") == "base64":
            try:
                body = base64.b64decode(body).decode("utf-8", errors="replace")
            except Exception:
                body = ""
        if body:
            raw_response_lines.append("")
            raw_response_lines.append(body)

        endpoints.append(
            ParsedEndpoint(
                method=method,
                scheme=scheme,
                host=host,
                port=port,
                path=path,
                query_keys=query_keys,
                status_code=int(res["status"]) if str(res.get("status", "")).isdigit() else None,
                content_type=content_type,
                auth_present=auth_present,
                state_changing=method in STATE_CHANGING_METHODS,
                raw_request="\n".join(raw_request_lines),
                raw_response="\n".join(raw_response_lines),
            )
        )

    return endpoints


REQUEST_LINE_RE = re.compile(r"^(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(\S+)\s+HTTP/\d(?:\.\d)?$", re.I)
STATUS_LINE_RE = re.compile(r"^HTTP/\d(?:\.\d)?\s+(\d{3})")


def _parse_headers(lines: list[str]) -> dict[str, str]:
    headers = {}
    joined = "\n".join(lines)
    parser = Parser()
    try:
        parsed = parser.parsestr(joined)
        for k, v in parsed.items():
            headers[k] = v
    except Exception:
        for line in lines:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
    return headers


def _split_blocks(text: str) -> list[str]:
    # Burp raw exports often have several HTTP messages separated by blank lines
    # before a new request line. Keep this permissive.
    indices = []
    lines = text.replace("\r\n", "\n").split("\n")
    for i, line in enumerate(lines):
        if REQUEST_LINE_RE.match(line.strip()):
            indices.append(i)
    if not indices:
        return [text]

    blocks = []
    for pos, start in enumerate(indices):
        end = indices[pos + 1] if pos + 1 < len(indices) else len(lines)
        blocks.append("\n".join(lines[start:end]).strip())
    return [b for b in blocks if b]


def parse_raw_http(text: str) -> list[ParsedEndpoint]:
    endpoints: list[ParsedEndpoint] = []
    for block in _split_blocks(text):
        lines = block.replace("\r\n", "\n").split("\n")
        if not lines:
            continue

        m = REQUEST_LINE_RE.match(lines[0].strip())
        if not m:
            continue

        method = m.group(1).upper()
        target = m.group(2)

        # find end of request headers
        empty_idx = None
        for i, line in enumerate(lines[1:], start=1):
            if line.strip() == "":
                empty_idx = i
                break
            if STATUS_LINE_RE.match(line.strip()):
                empty_idx = i
                break
        if empty_idx is None:
            empty_idx = len(lines)

        req_header_lines = lines[1:empty_idx]
        req_headers = _parse_headers(req_header_lines)
        host = req_headers.get("Host", "") or req_headers.get("host", "")
        scheme = "https" if req_headers.get("X-Forwarded-Proto", "").lower() == "https" else ""

        # If absolute URL exists, trust it.
        if target.startswith("http://") or target.startswith("https://"):
            parsed = urlparse(target)
            scheme = parsed.scheme
            host = parsed.hostname or host
            port = parsed.port
            path = parsed.path or "/"
            query = parsed.query
        else:
            host_no_port = host.split(":")[0]
            port = None
            if ":" in host:
                try:
                    port = int(host.rsplit(":", 1)[1])
                except ValueError:
                    port = None
            parsed = urlparse(target)
            host = host_no_port
            path = parsed.path or "/"
            query = parsed.query

        query_keys = sorted({k for k, _ in parse_qsl(query, keep_blank_values=True)})
        auth_present = any(k.lower() in {"authorization", "cookie", "x-api-key", "x-auth-token"} for k in req_headers)

        raw_response = ""
        status_code = None
        content_type = ""

        # response may be embedded later in block
        status_index = None
        for i, line in enumerate(lines):
            sm = STATUS_LINE_RE.match(line.strip())
            if sm:
                status_index = i
                status_code = int(sm.group(1))
                break

        if status_index is not None:
            raw_response = "\n".join(lines[status_index:])
            # parse response headers until blank
            response_header_lines = []
            for line in lines[status_index + 1:]:
                if line.strip() == "":
                    break
                response_header_lines.append(line)
            res_headers = _parse_headers(response_header_lines)
            for k, v in res_headers.items():
                if k.lower() == "content-type":
                    content_type = v
                    break

        raw_request = "\n".join(lines[:status_index]) if status_index is not None else block

        endpoints.append(
            ParsedEndpoint(
                method=method,
                scheme=scheme,
                host=host,
                port=port,
                path=path,
                query_keys=query_keys,
                status_code=status_code,
                content_type=content_type,
                auth_present=auth_present,
                state_changing=method in STATE_CHANGING_METHODS,
                raw_request=raw_request,
                raw_response=raw_response,
            )
        )

    return endpoints


def parse_auto(filename: str, text: str, format_hint: str = "auto") -> tuple[str, list[ParsedEndpoint]]:
    hint = (format_hint or "auto").lower()
    lower = filename.lower()

    if hint == "har" or lower.endswith(".har"):
        return "har", parse_har(text)

    if hint in {"raw", "txt"}:
        return "raw", parse_raw_http(text)

    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            data = json.loads(text)
            if "log" in data and "entries" in data.get("log", {}):
                return "har", parse_har(text)
        except Exception:
            pass

    return "raw", parse_raw_http(text)


IDOR_HINTS = {"id", "user", "userid", "user_id", "member", "memberid", "order", "orderid", "profile", "comment", "post", "object"}
SENSITIVE_PATH_HINTS = {"admin", "internal", "debug", "token", "auth", "session", "payment", "billing", "invoice", "download", "upload"}


def interesting_score(endpoint: ParsedEndpoint) -> int:
    score = 0

    if endpoint.auth_present:
        score += 15
    if endpoint.state_changing:
        score += 15
    if endpoint.status_code and 200 <= endpoint.status_code < 300:
        score += 5

    query_blob = " ".join(endpoint.query_keys).lower()
    path_blob = endpoint.path.lower()

    if any(h in query_blob for h in IDOR_HINTS):
        score += 20
    if any(h in path_blob for h in IDOR_HINTS):
        score += 20
    if any(h in path_blob for h in SENSITIVE_PATH_HINTS):
        score += 20

    if endpoint.method == "GET" and endpoint.auth_present:
        score += 5

    return min(score, 100)
