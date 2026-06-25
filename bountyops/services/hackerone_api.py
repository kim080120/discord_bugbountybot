from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


H1_API_BASE = "https://api.hackerone.com/v1"

TARGET_ASSET_TYPES = {
    "URL",
    "DOMAIN",
    "WILDCARD",
    "IP_ADDRESS",
    "CIDR",
    "SOURCE_CODE",
    "ANDROID",
    "IOS",
    "APPLE_IOS",
    "GOOGLE_PLAY_APP_ID",
    "WINDOWS_APP_STORE_APP_ID",
    "EXECUTABLES",
    "DOWNLOADABLE_EXECUTABLES",
    "HARDWARE",
    "API",
}

TIER_RE = re.compile(r"(?i)^\s*tier\s*\d+\s*$")
TIME_LIMIT_RE = re.compile(
    r"(?i)(blackout|testing\s+prohibited|test(?:ing)?\s+window|do\s+not\s+test|"
    r"maintenance\s+window|테스트\s*금지|점검\s*시간|[0-2]?\d:[0-5]\d\s*[-~]\s*[0-2]?\d:[0-5]\d)"
)


@dataclass(slots=True)
class HackerOneProgramResult:
    platform: str
    input_value: str
    source_url: str
    suggested_name: str
    reward_max: int
    source_code: bool
    has_time_limit: bool
    time_limit_note: str
    in_scope: list[dict[str, str]]
    out_scope: list[dict[str, str]]
    restrictions: list[str]
    notices: list[str]
    raw_json: dict

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


def normalize_h1_handle(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("HackerOne handle is empty")

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        parts = [p for p in parsed.path.split("/") if p]
        if not parts:
            raise ValueError("Could not infer HackerOne handle from URL")
        value = parts[0]

    value = value.strip("/").strip("@")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value):
        raise ValueError(f"Invalid HackerOne handle: {value!r}")
    return value


def _basic_auth_header(username: str, token: str) -> str:
    raw = f"{username}:{token}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def h1_get_json(path: str, *, username: str, token: str) -> dict:
    if not username or not token:
        raise RuntimeError("HACKERONE_USERNAME or HACKERONE_API_TOKEN is missing in .env")

    url = H1_API_BASE + path
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": _basic_auth_header(username, token),
            "Accept": "application/json",
            "User-Agent": "BountyOps/0.3.3 (+local researcher tool)",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            data = res.read(5_000_000)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read(1000).decode("utf-8", errors="replace")
        except Exception:
            pass
        raise RuntimeError(f"HackerOne API HTTP {exc.code}: {body[:500]}") from exc

    return json.loads(data.decode("utf-8", errors="replace"))


def _scope_entry(item: dict) -> dict[str, str] | None:
    attrs = item.get("attributes", {}) if isinstance(item, dict) else {}

    value = str(attrs.get("asset_identifier") or "").strip()
    if not value:
        return None

    asset_type = str(attrs.get("asset_type") or "").strip()
    max_severity = str(attrs.get("max_severity") or "").strip()
    eligible_bounty = attrs.get("eligible_for_bounty")
    eligible_submission = attrs.get("eligible_for_submission")
    instruction = str(attrs.get("instruction") or "").strip()

    note_parts: list[str] = []
    if asset_type:
        note_parts.append(f"type={asset_type}")
    if eligible_bounty is not None:
        note_parts.append(f"bounty={eligible_bounty}")
    if eligible_submission is not None:
        note_parts.append(f"submission={eligible_submission}")
    if max_severity:
        note_parts.append(f"max_severity={max_severity}")
    if instruction:
        cleaned = re.sub(r"\s+", " ", instruction)
        note_parts.append(cleaned[:300])

    return {
        "value": value,
        "note": " | ".join(note_parts),
        "asset_type": asset_type,
        "eligible_for_bounty": str(eligible_bounty),
        "eligible_for_submission": str(eligible_submission),
        "max_severity": max_severity,
    }


def _is_real_target_scope(entry: dict[str, str]) -> bool:
    value = entry.get("value", "").strip()
    asset_type = entry.get("asset_type", "").strip().upper()

    if not value:
        return False

    # HackerOne sometimes uses OTHER/Tier 1/Tier 2/Tier 3 as reward buckets.
    # Those are not actual test targets and must not enter host/scope matching.
    if TIER_RE.match(value):
        return False

    if asset_type in TARGET_ASSET_TYPES:
        return True

    # Conservative fallback: keep if it looks like a concrete target.
    low = value.lower()
    if low.startswith(("http://", "https://", "git://", "ssh://")):
        return True
    if "github.com/" in low or "gitlab.com/" in low:
        return True
    if re.fullmatch(r"(?:\*\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/.*)?", low):
        return True

    return False


def _extract_program_restrictions(program_json: dict) -> list[str]:
    text_chunks: list[str] = []

    def walk(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if any(word in lk for word in ["policy", "instruction", "submission", "rule", "requirement", "safe_harbor"]):
                    if isinstance(v, str):
                        text_chunks.append(v)
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(program_json)

    joined = "\n".join(text_chunks)
    lines = re.split(r"(?<=[.!?。])\s+|[\n\r]+", joined)
    hints = [
        "dos", "ddos", "brute force", "rate limit", "destructive", "payment",
        "third-party", "social engineering", "spam", "phishing", "maintenance",
        "testing prohibited", "blackout", "do not", "must not", "prohibited",
        "scanner", "qps", "ai generated", "production systems",
        "금지", "점검", "결제", "삭제", "구매", "서비스 장애", "과도한 요청",
    ]
    out = []
    for s in lines:
        cleaned = re.sub(r"\s+", " ", s).strip(" -*\t")
        if len(cleaned) < 8 or len(cleaned) > 450:
            continue
        low = cleaned.lower()
        if any(h in low for h in hints) and cleaned not in out:
            out.append(cleaned)
        if len(out) >= 30:
            break
    return out


def _infer_reward_max_safely(program_json: dict) -> int:
    candidates: list[int] = []
    monetary_key_re = re.compile(r"(maximum|highest|max).*?(bounty|reward)|(?:bounty|reward).*?(maximum|highest|max)", re.I)

    def walk(obj: Any):
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k)
                if monetary_key_re.search(key):
                    if isinstance(v, (int, float)) and int(v) >= 50:
                        candidates.append(int(v))
                    elif isinstance(v, str):
                        if "$" in v or "usd" in v.lower() or "krw" in v.lower() or "원" in v:
                            raw = re.sub(r"[^0-9]", "", v)
                            if raw:
                                val = int(raw)
                                if val >= 50:
                                    candidates.append(val)
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(program_json)
    return max(candidates) if candidates else 0


def _time_limit_note(restrictions: list[str]) -> str:
    for r in restrictions:
        if TIME_LIMIT_RE.search(r):
            return r
    return ""


def fetch_hackerone_program(handle_or_url: str, *, username: str, token: str) -> HackerOneProgramResult:
    handle = normalize_h1_handle(handle_or_url)

    scopes_json = h1_get_json(
        f"/hackers/programs/{urllib.parse.quote(handle)}/structured_scopes",
        username=username,
        token=token,
    )

    program_json: dict = {}
    program_meta_error = ""
    try:
        program_json = h1_get_json(
            f"/hackers/programs/{urllib.parse.quote(handle)}",
            username=username,
            token=token,
        )
    except Exception as exc:
        program_meta_error = str(exc)

    in_scope: list[dict[str, str]] = []
    out_scope: list[dict[str, str]] = []
    scope_meta: list[str] = []
    seen_in: set[str] = set()
    seen_out: set[str] = set()
    source_code = False

    for item in scopes_json.get("data", []):
        attrs = item.get("attributes", {}) if isinstance(item, dict) else {}
        eligible_submission = attrs.get("eligible_for_submission")
        entry = _scope_entry(item)
        if entry is None:
            continue

        value = entry["value"]
        asset_type = entry.get("asset_type", "")
        if asset_type.upper() == "SOURCE_CODE" or "github.com/" in value.lower():
            source_code = True

        if not _is_real_target_scope(entry):
            meta = value
            if entry.get("note"):
                meta += f" — {entry['note']}"
            scope_meta.append(meta)
            continue

        if eligible_submission is True:
            if value not in seen_in:
                in_scope.append(entry)
                seen_in.add(value)
        else:
            if value not in seen_out:
                out_scope.append(entry)
                seen_out.add(value)

    reward_max = _infer_reward_max_safely(program_json) if program_json else 0
    restrictions = _extract_program_restrictions(program_json) if program_json else []
    time_note = _time_limit_note(restrictions)

    notices = [
        f"HackerOne API source: structured_scopes for handle `{handle}`",
        "Scope values are stored as asset_identifier only; metadata is stored in note.",
        "Workspace was not created automatically. Use /crawl apply after review.",
    ]
    if scope_meta:
        notices.append("Non-target scope metadata: " + " ; ".join(scope_meta[:10]))
    if reward_max == 0:
        notices.append("Reward max is Unknown/0 because HackerOne reward tables were not confidently parsed.")
    if program_meta_error:
        notices.append(f"Program metadata endpoint failed; scopes were still imported. Error: {program_meta_error[:250]}")

    combined_raw = {
        "structured_scopes": scopes_json,
        "program": program_json,
        "program_meta_error": program_meta_error,
    }

    return HackerOneProgramResult(
        platform="HackerOne",
        input_value=handle_or_url,
        source_url=f"https://hackerone.com/{handle}",
        suggested_name=handle,
        reward_max=reward_max,
        source_code=source_code,
        has_time_limit=bool(time_note),
        time_limit_note=time_note,
        in_scope=in_scope[:100],
        out_scope=out_scope[:100],
        restrictions=restrictions[:30],
        notices=notices,
        raw_json=combined_raw,
    )


def save_hackerone_result(result: HackerOneProgramResult, storage_dir: Path) -> tuple[str, str]:
    raw_dir = storage_dir / "site_crawls" / "raw"
    parsed_dir = storage_dir / "site_crawls" / "parsed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    parsed_dir.mkdir(parents=True, exist_ok=True)

    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"hackerone_{result.suggested_name}")[:100]
    raw_path = raw_dir / f"{safe}.json"
    parsed_path = parsed_dir / f"{safe}.parsed.json"

    raw_path.write_text(json.dumps(result.raw_json, ensure_ascii=False, indent=2), encoding="utf-8")
    parsed_path.write_text(result.to_parsed_json(), encoding="utf-8")

    return str(raw_path), str(parsed_path)
