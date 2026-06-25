from __future__ import annotations

import html
import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DOMAIN_RE = re.compile(
    r"(?i)\b(?:\*\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/[^\s<>'\"()]*)?"
)
GITHUB_RE = re.compile(r"(?i)https?://github\.com/[a-z0-9_.-]+/[a-z0-9_.-]+")
REWARD_RE = re.compile(r"(?i)(?:\$|USD\s*)\s?([0-9][0-9,]{2,})|([0-9][0-9,]{4,})\s?(?:원|KRW|USD|\$)")
TIME_RE = re.compile(
    r"(?i)(점검|maintenance|테스트\s*금지|testing\s*prohibited|blackout|매주|매월|"
    r"\b(?:mon|tue|wed|thu|fri|sat|sun)\b|[0-2]?\d:[0-5]\d\s*[-~]\s*[0-2]?\d:[0-5]\d)"
)
RESTRICTION_HINTS = [
    "dos", "ddos", "brute force", "rate limit", "destructive", "payment",
    "third-party", "social engineering", "spam", "phishing", "테스트 금지",
    "점검", "결제", "삭제", "구매", "서비스 장애", "과도한 요청", "무차별",
]


@dataclass(slots=True)
class CrawlResult:
    platform: str
    input_value: str
    source_url: str
    suggested_name: str
    reward_max: int
    source_code: bool
    has_time_limit: bool
    time_limit_note: str
    in_scope: list[str]
    out_scope: list[str]
    restrictions: list[str]
    notices: list[str]
    raw_text: str

    def to_parsed_json(self) -> str:
        return json.dumps(
            {
                "platform": self.platform,
                "input_value": self.input_value,
                "source_url": self.source_url,
                "suggested_name": self.suggested_name,
                "reward_max": self.reward_max,
                "source_code": self.source_code,
                "has_time_limit": self.has_time_limit,
                "time_limit_note": self.time_limit_note,
                "in_scope": self.in_scope,
                "out_scope": self.out_scope,
                "restrictions": self.restrictions,
                "notices": self.notices,
            },
            ensure_ascii=False,
            indent=2,
        )


def fetch_text(url: str, max_bytes: int = 2_000_000) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "BountyOps/0.3-preview (+local researcher tool)",
            "Accept": "text/html,application/json,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        data = res.read(max_bytes + 1)
    if len(data) > max_bytes:
        data = data[:max_bytes]
    return data.decode("utf-8", errors="replace")


def text_from_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def infer_name_from_url(platform: str, input_value: str, source_url: str) -> str:
    if platform.lower() == "hackerone":
        value = input_value.strip().rstrip("/")
        if "://" in value:
            parts = [p for p in urlparse(value).path.split("/") if p]
            return parts[0] if parts else "unknown"
        return value.replace("@", "").strip("/") or "unknown"

    parsed = urlparse(source_url if "://" in source_url else input_value)
    host = parsed.netloc or parsed.path
    host = host.split(":")[0]
    bits = host.split(".")
    if len(bits) >= 2:
        return bits[-2]
    return host or "unknown"


def extract_reward_max(text: str) -> int:
    values: list[int] = []
    for match in REWARD_RE.finditer(text):
        raw = match.group(1) or match.group(2) or ""
        raw = re.sub(r"[^0-9]", "", raw)
        if raw:
            try:
                values.append(int(raw))
            except ValueError:
                pass
    return max(values) if values else 0


def extract_domains(text: str) -> list[str]:
    found = []
    for m in DOMAIN_RE.finditer(text):
        value = m.group(0).strip().strip(".,;:)]}'\"")
        if len(value) < 4:
            continue
        if value.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".js")):
            continue
        if value not in found:
            found.append(value)
    return found[:80]


def extract_restrictions(text: str) -> list[str]:
    sentences = re.split(r"(?<=[.!?。])\s+|[\n\r]+", text)
    out = []
    for s in sentences:
        low = s.lower()
        if any(h in low for h in RESTRICTION_HINTS) or TIME_RE.search(s):
            s = s.strip()
            if 8 <= len(s) <= 350 and s not in out:
                out.append(s)
        if len(out) >= 20:
            break
    return out


def split_scope(text: str, domains: list[str]) -> tuple[list[str], list[str]]:
    low = text.lower()
    out_scope: list[str] = []
    in_scope: list[str] = []

    for d in domains:
        idx = low.find(d.lower().replace("*.", ""))
        window = low[max(0, idx - 120): idx + 160] if idx >= 0 else ""
        if any(k in window for k in ["out of scope", "out-of-scope", "not eligible", "제외", "아웃스코프", "금지"]):
            out_scope.append(d)
        else:
            in_scope.append(d)

    return in_scope[:50], out_scope[:50]


def crawl_site(platform: str, input_value: str) -> CrawlResult:
    platform_clean = platform.strip()
    raw_input = input_value.strip()

    if platform_clean.lower() == "hackerone":
        if raw_input.startswith("http://") or raw_input.startswith("https://"):
            url = raw_input
        else:
            url = f"https://hackerone.com/{raw_input.strip('/')}"
    else:
        url = raw_input

    raw = fetch_text(url)
    text = text_from_html(raw)
    suggested_name = infer_name_from_url(platform_clean, raw_input, url)
    domains = extract_domains(text)
    in_scope, out_scope = split_scope(text, domains)
    reward_max = extract_reward_max(text)
    github_links = GITHUB_RE.findall(raw)
    restrictions = extract_restrictions(text)
    has_time_limit = any(TIME_RE.search(r) for r in restrictions) or bool(TIME_RE.search(text[:3000]))
    time_limit_note = ""
    if has_time_limit:
        for r in restrictions:
            if TIME_RE.search(r):
                time_limit_note = r[:500]
                break
        if not time_limit_note:
            m = TIME_RE.search(text[:3000])
            if m:
                start = max(0, m.start() - 120)
                end = min(len(text), m.end() + 180)
                time_limit_note = text[start:end].strip()[:500]

    notices = []
    if github_links:
        notices.append("GitHub/source code candidate: " + ", ".join(sorted(set(github_links))[:5]))

    return CrawlResult(
        platform=platform_clean,
        input_value=raw_input,
        source_url=url,
        suggested_name=suggested_name,
        reward_max=reward_max,
        source_code=bool(github_links),
        has_time_limit=has_time_limit,
        time_limit_note=time_limit_note,
        in_scope=in_scope,
        out_scope=out_scope,
        restrictions=restrictions,
        notices=notices,
        raw_text=raw,
    )


def save_crawl_result(result: CrawlResult, storage_dir: Path) -> tuple[str, str]:
    raw_dir = storage_dir / "site_crawls" / "raw"
    parsed_dir = storage_dir / "site_crawls" / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"{result.platform}_{result.suggested_name}")[:100]
    raw_path = raw_dir / f"{safe}.html"
    parsed_path = parsed_dir / f"{safe}.json"

    raw_path.write_text(result.raw_text, encoding="utf-8", errors="replace")
    parsed_path.write_text(result.to_parsed_json(), encoding="utf-8")

    return str(raw_path), str(parsed_path)
