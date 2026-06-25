"""Scope importers for self-hosted / non-HackerOne bug bounty platforms.

Each fetcher returns a CrawlResult (same shape as site_crawler), so it plugs
straight into the existing `add_site_crawl` -> `/crawl apply` pipeline.

Platforms:
- Naver  (bugbounty.naver.com)  : public CMS JSON API, markdown table  -> easy
- Kakao  (bugbounty.kakao.com)  : scope baked into a Vue JS chunk       -> best-effort
- huntr  (huntr.com/bounties)   : GitHub repo + model-format hrefs       -> HTML scrape
- Bugcrowd (bugcrowd.com)       : engagements.json + changelog preview   -> JSON

HackerOne is handled separately by services/hackerone_api.py (official API).

All requests are read-only and unauthenticated (public scope pages only).
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from .site_crawler import CrawlResult


_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Matches bare and wildcard hosts: pay.naver.com, *.pay.naver.com
_HOST_RE = re.compile(r"(?:\*\.)?(?:[a-z0-9-]+\.)+[a-z]{2,}", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_BC_UUID_RE = re.compile(
    r"changelog/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def _http(url: str, *, accept: str = "*/*", max_bytes: int = 4_000_000) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": _UA, "Accept": accept, "Accept-Language": "en,ko;q=0.8"},
    )
    with urllib.request.urlopen(req, timeout=25) as res:
        return res.read(max_bytes)


def _get_text(url: str, *, accept: str = "*/*") -> str:
    return _http(url, accept=accept).decode("utf-8", errors="replace")


def _get_json(url: str, *, accept: str = "*/*") -> dict:
    return json.loads(_get_text(url, accept=accept))


def _clean(text: str) -> str:
    """Strip HTML tags / entities / extra whitespace from a Bugcrowd diff fragment."""
    text = _TAG_RE.sub(" ", text or "")
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _current(field) -> str:
    """Bugcrowd fields are {previous, current} diff objects; read the current value."""
    if isinstance(field, dict):
        return field.get("current") or field.get("previous") or ""
    return field or ""


# --------------------------------------------------------------------------- #
# Naver
# --------------------------------------------------------------------------- #

_NAVER_BASE = "https://bugbounty.naver.com/api/cms/statics/{t}?isKorean=false"


def _md_table_rows(markdown: str) -> list[list[str]]:
    """Return data rows (cell lists) of the first GFM table, after the separator."""
    rows: list[list[str]] = []
    seen_separator = False
    for line in markdown.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if cells and all(set(c) <= set("-: ") for c in cells):
            seen_separator = True
            continue
        if not seen_separator:
            continue  # header row
        rows.append(cells)
    return rows


def _md_to_lines(markdown: str, limit: int = 20) -> list[str]:
    out: list[str] = []
    for line in markdown.splitlines():
        s = line.strip(" \t-*#>|")
        s = re.sub(r"\s+", " ", s).strip()
        if 8 <= len(s) <= 400 and s not in out and not set(s) <= set("-: "):
            out.append(s)
        if len(out) >= limit:
            break
    return out


def _strip_md(text: str) -> str:
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)  # [label](url) -> label
    text = re.sub(r"[*_`#>]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _fmt_date(date) -> str:
    if date in (None, ""):
        return ""
    s = str(date)
    if s.isdigit():  # epoch seconds (or milliseconds) — e.g. Naver notices
        ts = int(s)
        if ts > 10**12:
            ts //= 1000
        try:
            return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")
        except (OverflowError, OSError, ValueError):
            return ""
    return s[:10]  # ISO timestamp -> YYYY-MM-DD


def _fmt_announcement(date, title, body, limit: int = 200) -> str:
    """Format one platform announcement (HTML or markdown) into a #notices line.

    _clean (strip HTML tags) MUST run before _strip_md (which removes '>' and would
    otherwise break unclosed tags).
    """
    title_txt = _strip_md(_clean(str(title or ""))).strip()
    body_txt = _strip_md(_clean(str(body or ""))).strip()
    day = _fmt_date(date)
    head = f"📢 [{day}] {title_txt}" if day else f"📢 {title_txt}"
    snippet = body_txt[:limit].strip()
    return f"{head} — {snippet}" if snippet else head


def _naver_prohibition_sections(md: str) -> tuple[list[str], list[str]]:
    """Split Naver PROHIBITIONS into (rules_of_engagement, bounty_exclusions)."""
    bounty: list[str] = []
    rules: list[str] = []
    mode = "bounty"  # the document opens with the "will not pay the bounty" list
    for line in md.splitlines():
        s = line.strip()
        low = s.lower()
        if "prohibited from performing" in low:
            mode = "rules"
            continue
        if "will not pay the bounty" in low or "will also not pay" in low:
            mode = "bounty"
            continue
        if s.startswith(("*", "-", "•")):
            text = _strip_md(s.lstrip("*-• ").strip())
            if 4 <= len(text) <= 300:
                (rules if mode == "rules" else bounty).append(text)
    return rules, bounty


def _naver_invalid_titles(md: str) -> list[str]:
    return [_strip_md(h) for h in re.findall(r"^###\s+(.+)$", md, re.MULTILINE)]


def scope_values(entries: list[str]) -> set[str]:
    """Host/identifier values out of 'host | note' scope entries (for diffing)."""
    out: set[str] = set()
    for entry in entries:
        value = str(entry).split(" | ", 1)[0].strip()
        if value:
            out.add(value)
    return out


def fetch_naver_targets() -> CrawlResult:
    targets_md = _get_json(_NAVER_BASE.format(t="TARGETS")).get("content", "")
    if not targets_md:
        raise ValueError("Naver TARGETS endpoint returned no content")
    try:
        prohib_md = _get_json(_NAVER_BASE.format(t="PROHIBITIONS")).get("content", "")
    except Exception:
        prohib_md = ""
    try:
        invalid_md = _get_json(_NAVER_BASE.format(t="INVALID_REPORTS")).get("content", "")
    except Exception:
        invalid_md = ""

    in_scope: list[str] = []
    app_targets: list[str] = []
    for cells in _md_table_rows(targets_md):
        category = cells[0] if len(cells) > 0 else ""
        service = cells[1] if len(cells) > 1 else ""
        target = cells[2] if len(cells) > 2 else ""
        remarks = cells[3] if len(cells) > 3 else ""
        note = service or category
        if remarks:
            note = f"{note} — {remarks}" if note else remarks
        hosts = _HOST_RE.findall(target)
        if hosts:
            for host in hosts:
                entry = f"{host} | {note}".strip(" |")
                if entry not in in_scope:
                    in_scope.append(entry)
        elif service or category:
            label = service or category
            app_targets.append(f"{label} ({target})" if target else label)

    rules, bounty_excl = _naver_prohibition_sections(prohib_md)
    invalid_titles = _naver_invalid_titles(invalid_md)
    restrictions = (
        [f"[제약] {r}" for r in rules]
        + [f"[포상금 제외] {b}" for b in bounty_excl]
        + [f"[포상금 제외] {t}" for t in invalid_titles]
    )
    notices = [
        "Source: bugbounty.naver.com TARGETS (auto-imported via public CMS API).",
        f"제약 {len(rules)}건 · 포상금 제외 {len(bounty_excl) + len(invalid_titles)}건 (PROHIBITIONS/INVALID_REPORTS).",
        "NAVER does not publish a machine-readable out-of-scope host list.",
    ]
    if app_targets:
        notices.append("App/binary targets (not web hosts): " + "; ".join(app_targets[:10]))

    try:
        notice_data = _get_json("https://bugbounty.naver.com/api/notices")
        for n in (notice_data.get("content") or [])[:6]:
            notices.append(_fmt_announcement(
                n.get("publishedAt") or n.get("createdAt"), n.get("title"), n.get("content")
            ))
    except Exception:
        pass

    return CrawlResult(
        platform="NaverBugBounty",
        input_value="naver",
        source_url="https://bugbounty.naver.com/contents?type=TARGETS",
        suggested_name="naver",
        reward_max=0,
        source_code=False,
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope[:200],
        out_scope=[],
        restrictions=restrictions[:60],
        notices=notices,
        raw_text=targets_md,
    )


# --------------------------------------------------------------------------- #
# huntr
# --------------------------------------------------------------------------- #

def fetch_huntr_bounties(limit: int = 250) -> CrawlResult:
    doc = _get_text("https://huntr.com/bounties")
    repos = sorted(set(re.findall(
        r"disclose/opensource\?target=(https://github\.com/[\w.-]+/[\w.-]+)", doc
    )))
    formats = sorted(set(re.findall(r"disclose/models\?target=([^\"&]+)", doc)))
    if not repos and not formats:
        raise ValueError("huntr: no targets parsed (page layout may have changed)")

    in_scope = [f"{r} | OSS repo" for r in repos]
    in_scope += [f"model:{urllib.parse.unquote(f)} | model format" for f in formats]
    in_scope = in_scope[:limit]

    notices = [
        f"Source: huntr.com/bounties — {len(repos)} OSS repos, {len(formats)} model formats (auto-imported).",
        "All listed repos/formats are in-scope; per-target exclusions live on each individual rules page.",
        "huntr classic bounties are migrating toward /challenges; re-verify periodically.",
    ]
    return CrawlResult(
        platform="huntr",
        input_value="huntr",
        source_url="https://huntr.com/bounties",
        suggested_name="huntr",
        reward_max=0,
        source_code=True,
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope,
        out_scope=[],
        restrictions=[],
        notices=notices,
        raw_text=doc[:500_000],
    )


# --------------------------------------------------------------------------- #
# Bugcrowd
# --------------------------------------------------------------------------- #

_BC_LIST = (
    "https://bugcrowd.com/engagements.json"
    "?category=bug_bounty&page={page}&sort_by=promoted&sort_direction=desc"
)


def list_bugcrowd_engagements(page: int = 1) -> tuple[list[dict], dict]:
    data = _get_json(_BC_LIST.format(page=page), accept="application/json")
    out: list[dict] = []
    for e in data.get("engagements", []):
        if e.get("isPrivate"):
            continue
        slug = (e.get("briefUrl") or "").rstrip("/").split("/")[-1]
        if not slug:
            continue
        reward = (e.get("rewardSummary") or {}).get("summary") or ""
        out.append({
            "name": (e.get("name") or "").strip(),
            "slug": slug,
            "reward": reward,
            "access": e.get("accessStatus") or "",
        })
    return out, (data.get("paginationMeta") or {})


def _bc_targets(groups) -> list[str]:
    res: list[str] = []
    for grp in (groups or []):
        for t in (grp.get("targets") or []):
            name = _clean(_current(t.get("name")))
            category = _clean(_current(t.get("category")))
            if not name:
                continue
            entry = f"{name} | {category}".strip(" |")
            if entry not in res:
                res.append(entry)
    return res


def fetch_bugcrowd_engagement(slug: str) -> CrawlResult:
    slug = slug.strip().strip("/").split("/")[-1]
    if not slug:
        raise ValueError("Empty Bugcrowd engagement slug")

    brief_html = _get_text(f"https://bugcrowd.com/engagements/{slug}", accept="*/*")
    m = _BC_UUID_RE.search(brief_html)
    if not m:
        raise ValueError(
            f"No brief version found for '{slug}' "
            "(private/invite-only program, or page layout changed)"
        )
    uuid = m.group(1)
    preview = _get_json(
        f"https://bugcrowd.com/engagements/{slug}/changelog/{uuid}/preview",
        accept="*/*",
    )
    reviews = preview.get("reviews") or {}
    in_scope = _bc_targets(reviews.get("inScope"))
    out_scope = _bc_targets(reviews.get("outOfScope"))

    restrictions: list[str] = []
    safe_harbor = _clean(_current(reviews.get("safeHarborStatus")))
    if safe_harbor:
        restrictions.append(f"Safe harbor: {safe_harbor}")

    notices = [
        f"Source: bugcrowd.com/engagements/{slug} (auto-imported via changelog preview API).",
        f"Imported {len(in_scope)} in-scope and {len(out_scope)} out-of-scope targets.",
    ]
    try:
        ann_data = _get_json(
            f"https://bugcrowd.com/engagements/{slug}/announcements.json", accept="*/*"
        )
        for ann in (ann_data.get("announcements") or [])[:5]:
            notices.append(_fmt_announcement(ann.get("publishedAt"), ann.get("title"), ann.get("body")))
    except Exception:
        pass
    source_code = any("github.com" in x.lower() for x in in_scope)

    return CrawlResult(
        platform="Bugcrowd",
        input_value=slug,
        source_url=f"https://bugcrowd.com/engagements/{slug}",
        suggested_name=slug,
        reward_max=0,
        source_code=source_code,
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope[:200],
        out_scope=out_scope[:200],
        restrictions=restrictions[:30],
        notices=notices,
        raw_text=json.dumps(preview, ensure_ascii=False)[:500_000],
    )


# --------------------------------------------------------------------------- #
# Kakao (best-effort: scope is compiled into a Vue webpack chunk)
# --------------------------------------------------------------------------- #

def fetch_kakao_targets(max_chunks: int = 80) -> CrawlResult:
    home = _get_text("https://bugbounty.kakao.com/")
    m = re.search(r'src="(/js/app\.[a-f0-9]+\.js)"', home)
    if not m:
        raise ValueError("Kakao: app.js bundle not found on home page")
    app_js = _get_text("https://bugbounty.kakao.com" + m.group(1))

    # Resolve chunk filenames from the webpack chunk map (id -> hash).
    chunk_map = dict(re.findall(r'(\d+):"([a-f0-9]{6,})"', app_js))
    chunk_js = ""
    chunk_url = ""
    for cid, chash in list(chunk_map.items())[:max_chunks]:
        url = f"https://bugbounty.kakao.com/js/{cid}.{chash}.js"
        try:
            body = _get_text(url)
        except Exception:
            continue
        if "대표URL" in body or 'goExplanation("target")' in body:
            chunk_js = body
            chunk_url = url
            break
    if not chunk_js:
        raise ValueError(
            "Kakao: could not locate the scope chunk (frontend layout changed). "
            "Fall back to /findergap site url:https://bugbounty.kakao.com/home"
        )

    # In-scope service lines look like: "1. 카카오메일 - mail.kakao.com (대표URL : mail.kakao.com)"
    items = re.findall(r'"(\d+\.\s*[^"]{2,250})"', chunk_js)
    in_scope: list[str] = []
    out_scope: list[str] = []
    for raw in items:
        line = raw.strip()
        if "대표URL" not in line and "kakao" not in line.lower():
            continue
        hosts = _HOST_RE.findall(line)
        # service name = text before the first " - " or "("
        name = re.split(r"\s*[-(]", line, 1)[0]
        name = re.sub(r"^\d+\.\s*", "", name).strip()
        # Sandbox domains (e.g. kakaocdn.net) are explicitly out-of-scope.
        bucket = out_scope if ("sandbox" in line.lower() or "샌드박스" in line) else in_scope
        if hosts:
            for host in hosts:
                entry = f"{host} | {name}".strip(" |")
                if entry not in bucket:
                    bucket.append(entry)
        elif "app" in line.lower():
            in_scope.append(f"{name} (App) |")

    if not in_scope:
        raise ValueError("Kakao: scope chunk found but no service hosts parsed")

    # Bounty-exclusion list: 25 numbered items starting at "신고 시점에 재현".
    restrictions: list[str] = []
    start = next((i for i, it in enumerate(items) if "신고 시점에 재현" in it), None)
    if start is not None:
        for it in items[start:start + 25]:
            text = re.sub(r"^\d+\.\s*", "", it).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                restrictions.append(f"[포상금 제외] {text}")

    notices = [
        f"Source: {chunk_url} (Kakao Vue chunk — best-effort parse, verify manually).",
        f"포상금 제외 {len(restrictions)}건 파싱. 전체 규칙/제약: https://bugbounty.kakao.com/home#rule",
        "Kakao does not expose a public scope JSON API; out-of-scope hosts are prose-only.",
    ]
    return CrawlResult(
        platform="KakaoBugBounty",
        input_value="kakao",
        source_url="https://bugbounty.kakao.com/home#target",
        suggested_name="kakao",
        reward_max=0,
        source_code=False,
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope[:200],
        out_scope=out_scope[:50],
        restrictions=restrictions[:40],
        notices=notices,
        raw_text=chunk_js[:500_000],
    )


# --------------------------------------------------------------------------- #
# Re-scan / diff helpers
# --------------------------------------------------------------------------- #

def diff_scope(old_values: set[str], new_values: set[str]) -> tuple[list[str], list[str]]:
    """Return (added, removed) host/identifier values, new vs old."""
    return sorted(new_values - old_values), sorted(old_values - new_values)


def refetch_for_program(program) -> CrawlResult | None:
    """Re-fetch a program's scope using its platform importer.

    Only programs created by a *full-platform* import are eligible. Per-service
    programs (e.g. a hand-made "naver-comic" that shares the NaverBugBounty
    platform) are skipped — refreshing them against the whole platform scope
    would be wrong. Returns None for anything not auto-refreshable.
    """
    platform = (program.platform or "").strip()
    name = (program.name or "").strip().lower()
    if platform == "NaverBugBounty":
        return fetch_naver_targets() if name == "naver" else None
    if platform == "KakaoBugBounty":
        return fetch_kakao_targets() if name == "kakao" else None
    if platform == "huntr":
        return fetch_huntr_bounties() if name == "huntr" else None
    if platform == "Bugcrowd":
        # Bugcrowd programs are named by their engagement slug, so the name *is*
        # the fetch key — every Bugcrowd program is a full-engagement import.
        return fetch_bugcrowd_engagement(program.name)
    if platform == "Intigriti":
        return fetch_intigriti_program(program.name)
    if platform == "YesWeHack":
        return fetch_yeswehack_program(program.name)
    return None


# --------------------------------------------------------------------------- #
# Intigriti  (via arkadiyt/bounty-targets-data daily mirror — 1 request, all data)
# --------------------------------------------------------------------------- #

INTIGRITI_URL = (
    "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/intigriti_data.json"
)

_INTIGRITI_CACHE: dict = {"data": None, "at": 0.0}


def _intigriti_programs() -> list:
    now = time.monotonic()
    if _INTIGRITI_CACHE["data"] is not None and (now - _INTIGRITI_CACHE["at"]) < 1800:
        return _INTIGRITI_CACHE["data"]
    raw = _http(INTIGRITI_URL, max_bytes=24_000_000).decode("utf-8", errors="replace")
    data = json.loads(raw)
    _INTIGRITI_CACHE["data"] = data
    _INTIGRITI_CACHE["at"] = now
    return data


def list_intigriti_programs() -> list[dict]:
    out: list[dict] = []
    for p in _intigriti_programs():
        if p.get("status") != "open" or p.get("confidentiality_level") != "public":
            continue
        targets = p.get("targets") or {}
        in_targets = targets.get("in_scope") or []
        mb = p.get("max_bounty") or {}
        mn = p.get("min_bounty") or {}
        types: dict[str, int] = {}
        for t in in_targets:
            ty = (t.get("type") or "other").strip().lower() or "other"
            types[ty] = types.get(ty, 0) + 1
        out.append({
            "handle": (p.get("handle") or p.get("company_handle") or "").strip(),
            "name": (p.get("name") or "").strip(),
            "reward": int(mb.get("value") or 0),
            "reward_min": int(mn.get("value") or 0),
            "currency": (mb.get("currency") or mn.get("currency") or "").strip() or "USD",
            "in": len(in_targets),
            "out": len(targets.get("out_of_scope") or []),
            "types": types,
            "tac": bool(p.get("tacRequired")),
            "two_fa": bool(p.get("twoFactorRequired")),
        })
    return out


def _intigriti_scope_entries(items) -> list[str]:
    res: list[str] = []
    for t in items or []:
        endpoint = (t.get("endpoint") or "").strip()
        if not endpoint:
            continue
        note = (t.get("type") or "").strip()
        entry = f"{endpoint} | {note}".strip(" |")
        if entry not in res:
            res.append(entry)
    return res


def _intigriti_announcements(company_handle: str, handle: str, limit: int = 6) -> list[str]:
    """Intigriti program updates from the SSR /updates page (Angular my-app-state)."""
    try:
        html = _get_text(f"https://app.intigriti.com/programs/{company_handle}/{handle}/updates")
    except Exception:
        return []
    m = re.search(r'<script id="my-app-state"[^>]*>(.*?)</script>', html, re.DOTALL)
    if not m:
        return []
    txt = html_lib.unescape(m.group(1))
    out: list[str] = []
    pattern = re.compile(
        r'"title":"((?:[^"\\]|\\.)*)","description":"((?:[^"\\]|\\.)*)","publishedAt":(\d+)'
    )
    for om in pattern.finditer(txt):
        try:
            title = json.loads('"' + om.group(1) + '"')
            desc = json.loads('"' + om.group(2) + '"')
        except Exception:
            continue
        out.append(_fmt_announcement(om.group(3), title, desc))
        if len(out) >= limit:
            break
    return out


def fetch_intigriti_program(handle: str) -> CrawlResult:
    handle = handle.strip().strip("/").lower()
    program = next(
        (
            p for p in _intigriti_programs()
            if (p.get("handle") or "").lower() == handle
            or (p.get("company_handle") or "").lower() == handle
        ),
        None,
    )
    if program is None:
        raise ValueError(
            f"Intigriti 프로그램 '{handle}' 없음 (공개 목록에 없거나 핸들 오타). /import intigriti_list로 확인하세요."
        )

    targets = program.get("targets") or {}
    in_scope = _intigriti_scope_entries(targets.get("in_scope"))
    out_scope = _intigriti_scope_entries(targets.get("out_of_scope"))
    mb = program.get("max_bounty") or {}
    reward = int(mb.get("value") or 0)
    notices = [
        f"Source: Intigriti via bounty-targets-data — {program.get('name')}.",
        f"max bounty {reward} {mb.get('currency', '')}"
        + (" · TAC 필요" if program.get("tacRequired") else "")
        + (" · 2FA 필요" if program.get("twoFactorRequired") else "")
        + ".",
    ]
    notices += _intigriti_announcements(
        program.get("company_handle") or handle, program.get("handle") or handle
    )
    return CrawlResult(
        platform="Intigriti",
        input_value=handle,
        source_url=program.get("url") or f"https://app.intigriti.com/programs/{handle}",
        suggested_name=handle,
        reward_max=reward,
        source_code=any("github.com" in s.lower() for s in in_scope),
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope[:200],
        out_scope=out_scope[:200],
        restrictions=[],
        notices=notices,
        raw_text=json.dumps(program, ensure_ascii=False)[:500_000],
    )


# --------------------------------------------------------------------------- #
# YesWeHack  (bounty-targets-data mirror — same shape family as Intigriti)
# --------------------------------------------------------------------------- #

YESWEHACK_URL = (
    "https://raw.githubusercontent.com/arkadiyt/bounty-targets-data/main/data/yeswehack_data.json"
)

_YESWEHACK_CACHE: dict = {"data": None, "at": 0.0}


def _yeswehack_programs() -> list:
    now = time.monotonic()
    if _YESWEHACK_CACHE["data"] is not None and (now - _YESWEHACK_CACHE["at"]) < 1800:
        return _YESWEHACK_CACHE["data"]
    raw = _http(YESWEHACK_URL, max_bytes=24_000_000).decode("utf-8", errors="replace")
    data = json.loads(raw)
    _YESWEHACK_CACHE["data"] = data
    _YESWEHACK_CACHE["at"] = now
    return data


def list_yeswehack_programs() -> list[dict]:
    out: list[dict] = []
    for p in _yeswehack_programs():
        if not p.get("public") or p.get("disabled"):
            continue
        targets = p.get("targets") or {}
        in_targets = targets.get("in_scope") or []
        types: dict[str, int] = {}
        for t in in_targets:
            ty = (t.get("type") or "other").strip().lower() or "other"
            types[ty] = types.get(ty, 0) + 1
        out.append({
            "handle": (p.get("id") or "").strip(),
            "name": (p.get("name") or "").strip(),
            "reward": int(p.get("max_bounty") or 0),
            "reward_min": int(p.get("min_bounty") or 0),
            "currency": "EUR",  # YesWeHack is EUR-based; the mirror has no currency field
            "in": len(in_targets),
            "out": len(targets.get("out_of_scope") or []),
            "types": types,
            "tac": False,
            "two_fa": False,
        })
    return out


def _yeswehack_scope_entries(items) -> list[str]:
    res: list[str] = []
    for t in items or []:
        target = (t.get("target") or "").strip()
        if not target:
            continue
        note = (t.get("type") or "").strip()
        entry = f"{target} | {note}".strip(" |")
        if entry not in res:
            res.append(entry)
    return res


def _yeswehack_announcements(slug: str, limit: int = 6) -> list[str]:
    """YesWeHack program update history (/versions) as dated change events."""
    try:
        v = _get_json(f"https://api.yeswehack.com/programs/{slug}/versions")
    except Exception:
        return []
    items = v.get("items") if isinstance(v, dict) else v
    out: list[str] = []
    for it in (items or [])[:limit]:
        fields = it.get("fields") or []
        title = "프로그램 업데이트: " + (", ".join(fields) if fields else "변경")
        data = it.get("data") or {}
        body = data.get("rules") if isinstance(data.get("rules"), str) else ""
        out.append(_fmt_announcement(it.get("accepted_at"), title, body))
    return out


def fetch_yeswehack_program(handle: str) -> CrawlResult:
    handle = handle.strip().strip("/").lower()
    program = next(
        (p for p in _yeswehack_programs() if (p.get("id") or "").lower() == handle),
        None,
    )
    if program is None:
        raise ValueError(
            f"YesWeHack 프로그램 '{handle}' 없음 (공개 목록에 없거나 핸들 오타). /import yeswehack_list로 확인하세요."
        )
    targets = program.get("targets") or {}
    in_scope = _yeswehack_scope_entries(targets.get("in_scope"))
    out_scope = _yeswehack_scope_entries(targets.get("out_of_scope"))
    reward = int(program.get("max_bounty") or 0)
    notices = [
        f"Source: YesWeHack via bounty-targets-data — {program.get('name')}.",
        f"bounty {int(program.get('min_bounty') or 0)}–{reward} EUR.",
    ]
    notices += _yeswehack_announcements(handle)
    return CrawlResult(
        platform="YesWeHack",
        input_value=handle,
        source_url=f"https://yeswehack.com/programs/{handle}",
        suggested_name=handle,
        reward_max=reward,
        source_code=any("github.com" in s.lower() for s in in_scope),
        has_time_limit=False,
        time_limit_note="",
        in_scope=in_scope[:200],
        out_scope=out_scope[:200],
        restrictions=[],
        notices=notices,
        raw_text=json.dumps(program, ensure_ascii=False)[:500_000],
    )
