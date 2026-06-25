from __future__ import annotations

import json
import re

DOMAIN_RE = re.compile(r"(?i)\b(?:\*\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>'\"()]*)?")
RESTRICTION_HINTS = [
    "out of scope", "out-of-scope", "not eligible", "third-party", "social engineering",
    "dos", "ddos", "brute force", "rate limit", "destructive", "payment", "phishing",
    "spam", "testing prohibited", "blackout", "do not", "must not", "금지", "제외", "아웃스코프",
    "결제", "삭제", "서비스 장애", "과도한 요청",
]


def extract_policy(text: str) -> dict:
    domains = []
    for m in DOMAIN_RE.finditer(text):
        value = m.group(0).strip().strip(".,;:)]}'\"")
        if value and value not in domains:
            domains.append(value)

    lower = text.lower()
    in_scope = []
    out_scope = []
    for domain in domains:
        idx = lower.find(domain.lower().replace("*.", ""))
        window = lower[max(0, idx - 160): idx + 260] if idx >= 0 else ""
        if any(k in window for k in ["out of scope", "out-of-scope", "not eligible", "제외", "아웃스코프", "금지"]):
            out_scope.append(domain)
        else:
            in_scope.append(domain)

    lines = re.split(r"(?<=[.!?。])\s+|[\n\r]+", text)
    restrictions = []
    for line in lines:
        clean = re.sub(r"\s+", " ", line).strip(" -*\t")
        if 8 <= len(clean) <= 450 and any(h in clean.lower() for h in RESTRICTION_HINTS):
            if clean not in restrictions:
                restrictions.append(clean)
        if len(restrictions) >= 50:
            break

    return {
        "in_scope": in_scope[:100],
        "out_scope": out_scope[:100],
        "restrictions": restrictions[:50],
    }


def dumps_extracted(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)
