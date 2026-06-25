from __future__ import annotations

import re
from pathlib import Path

PATTERNS = {
    "authorization_header": re.compile(r"(?i)\bAuthorization\s*:\s*(Bearer|Basic|Token)?\s*[A-Za-z0-9._~+/=-]{12,}"),
    "cookie_header": re.compile(r"(?i)\bCookie\s*:\s*[^\r\n]{20,}"),
    "set_cookie_header": re.compile(r"(?i)\bSet-Cookie\s*:\s*[^\r\n]{20,}"),
    "access_token": re.compile(r"(?i)\b(access_token|refresh_token|id_token|session|sessionid|csrf|xsrf)[\"'\s:=]+[A-Za-z0-9._~+/=-]{12,}"),
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone_kr": re.compile(r"\b01[016789][-.\s]?\d{3,4}[-.\s]?\d{4}\b"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
}


def scan_text(text: str) -> dict[str, int]:
    return {name: len(pattern.findall(text)) for name, pattern in PATTERNS.items() if pattern.findall(text)}


def scan_file(path: str | Path, max_bytes: int = 2_000_000) -> dict[str, int]:
    data = Path(path).read_bytes()[:max_bytes]
    text = data.decode("utf-8", errors="replace")
    return scan_text(text)
