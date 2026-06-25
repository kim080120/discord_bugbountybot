from __future__ import annotations

import json
import re
from typing import Any


SENSITIVE_HEADER_NAMES = {
    "authorization",
    "cookie",
    "set-cookie",
    "x-api-key",
    "x-csrf-token",
    "x-xsrf-token",
    "x-auth-token",
    "proxy-authorization",
}

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"(access[_-]?token|refresh[_-]?token|id[_-]?token)", re.I),
    re.compile(r"(session|sessid|jwt|secret|password|passwd|api[_-]?key|csrf|xsrf)", re.I),
]

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"\b(?:010|011|016|017|018|019)[-\s]?\d{3,4}[-\s]?\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,19}\b")


def _mask_card_like(match: re.Match[str]) -> str:
    raw = match.group(0)
    digits = re.sub(r"\D", "", raw)
    if len(digits) < 13 or len(digits) > 19:
        return raw
    return f"[REDACTED_CARD:{digits[:6]}…{digits[-4:]}]"


def sanitize_text(text: str) -> str:
    if not text:
        return text

    lines = []
    for line in text.splitlines():
        if ":" in line:
            name, value = line.split(":", 1)
            if name.strip().lower() in SENSITIVE_HEADER_NAMES:
                lines.append(f"{name}: [REDACTED]")
                continue
        lines.append(line)

    text = "\n".join(lines)
    text = EMAIL_RE.sub("[REDACTED_EMAIL]", text)
    text = PHONE_RE.sub("[REDACTED_PHONE]", text)
    text = CARD_RE.sub(_mask_card_like, text)

    for pat in SENSITIVE_KEY_PATTERNS:
        text = re.sub(
            rf'("{pat.pattern}"\s*:\s*")([^"]+)(")',
            r'\1[REDACTED]\3',
            text,
            flags=re.I,
        )

    # Query/body style key=value tokens
    for key in [
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "session",
        "password",
        "passwd",
        "secret",
        "api_key",
        "apikey",
        "csrf",
        "xsrf",
    ]:
        text = re.sub(
            rf"(?i)({re.escape(key)}=)[^&\s]+",
            rf"\1[REDACTED]",
            text,
        )

    return text


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    clean = {}
    for key, value in headers.items():
        if key.lower() in SENSITIVE_HEADER_NAMES:
            clean[key] = "[REDACTED]"
        else:
            clean[key] = sanitize_text(str(value))
    return clean


def sanitize_jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if any(p.search(str(k)) for p in SENSITIVE_KEY_PATTERNS):
                out[k] = "[REDACTED]"
            else:
                out[k] = sanitize_jsonable(v)
        return out

    if isinstance(value, list):
        return [sanitize_jsonable(v) for v in value]

    if isinstance(value, str):
        return sanitize_text(value)

    return value


def sanitize_json_text(text: str) -> str:
    try:
        obj = json.loads(text)
    except Exception:
        return sanitize_text(text)

    return json.dumps(sanitize_jsonable(obj), ensure_ascii=False, indent=2)
