"""Fetch a program's past DISCLOSED reports (hacktivity) — what's already been
reported, so a hunter can gauge real duplicate risk and see which vuln patterns
have landed on the target.

Sources (public, no auth):
- huntr    : https://huntr.com/repos/{owner}/{repo}   (report titles + links)
- Bugcrowd : /engagements/{slug}/crowdstream.json      (accepted submissions:
             priority, target, state, researcher, date)

HackerOne hacktivity (GET /hackers/hacktivity) needs the API token and is added
separately once verified against a real token.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass

from .platform_importers import _get_text, _get_json


@dataclass
class DisclosedReport:
    title: str
    meta: str
    url: str


_HUNTR_REPORT_RE = re.compile(
    r'<a id="report-link"[^>]*href="(/bounties/[0-9a-f-]{36})"[^>]*>(.*?)</a>',
    re.DOTALL,
)


def huntr_disclosed(repo: str, limit: int = 15) -> list[DisclosedReport]:
    repo = repo.strip().strip("/")
    repo = re.sub(r"^https?://github\.com/", "", repo, flags=re.IGNORECASE).strip("/")
    if repo.count("/") != 1:
        raise ValueError("repo must be 'owner/name' (예: keras-team/keras)")
    html = _get_text(f"https://huntr.com/repos/{repo}")
    out: list[DisclosedReport] = []
    for m in _HUNTR_REPORT_RE.finditer(html):
        title = html_lib.unescape(re.sub(r"<[^>]+>", " ", m.group(2)))
        title = re.sub(r"\s+", " ", title).strip()
        if not title:
            continue
        out.append(DisclosedReport(title=title[:170], meta="", url="https://huntr.com" + m.group(1)))
        if len(out) >= limit:
            break
    if not out:
        raise ValueError(f"huntr: '{repo}'에서 disclosed report를 찾지 못함 (repo 핸들 확인).")
    return out


def hackerone_disclosed(
    *, username: str, token: str, handle: str | None = None, limit: int = 20, max_pages: int = 4
) -> list[DisclosedReport]:
    """Recent publicly-disclosed HackerOne reports (hacktivity).

    The REST hacktivity API has no working per-program filter, so when a handle is
    given we page through recent disclosed reports and filter client-side — i.e.
    only programs with RECENT disclosed activity will turn up.
    """
    from .hackerone_api import h1_get_json

    want = (handle or "").strip().lower() or None
    out: list[DisclosedReport] = []
    for page in range(1, max_pages + 1):
        path = (
            "/hackers/hacktivity?queryString=disclosed%3Atrue"
            f"&page%5Bsize%5D=100&page%5Bnumber%5D={page}"
        )
        data = (h1_get_json(path, username=username, token=token).get("data") or [])
        if not data:
            break
        for it in data:
            a = it.get("attributes") or {}
            rel = it.get("relationships") or {}
            prog = ((rel.get("program") or {}).get("data") or {}).get("attributes") or {}
            phandle = (prog.get("handle") or "").lower()
            if want and phandle != want:
                continue
            reporter = (((rel.get("reporter") or {}).get("data") or {}).get("attributes") or {}).get("username") or "?"
            bounty = a.get("total_awarded_amount")
            when = str(a.get("disclosed_at") or a.get("latest_disclosable_activity_at") or "")[:10]
            meta = " · ".join(x for x in [
                a.get("severity_rating") or "",
                f"${int(bounty):,}" if bounty else "",
                prog.get("handle") or "",
                f"by {reporter}",
                when,
            ] if x)
            out.append(DisclosedReport(
                title=(a.get("title") or "(제목 비공개)")[:170],
                meta=meta,
                url=a.get("url") or f"https://hackerone.com/{phandle}",
            ))
        if len(out) >= limit:
            break
    return out[:limit]


def bugcrowd_disclosed(slug: str, limit: int = 20) -> tuple[list[DisclosedReport], int]:
    slug = slug.strip().strip("/").split("/")[-1]
    cs = _get_json(f"https://bugcrowd.com/engagements/{slug}/crowdstream.json", accept="*/*")
    total = int((cs.get("pagination_meta") or {}).get("totalCount") or 0)
    out: list[DisclosedReport] = []
    for r in (cs.get("results") or [])[:limit]:
        priority = r.get("priority")
        state = r.get("substate") or ""
        when = r.get("submission_state_date_text") or ""
        who = r.get("researcher_username") or "익명"
        target = r.get("target") or "?"
        pr = f"P{priority}" if priority else "P?"
        out.append(DisclosedReport(
            title=f"{pr} · {target}"[:170],
            meta=f"{state} · {when} · by {who}",
            url=f"https://bugcrowd.com/engagements/{slug}",
        ))
    return out, total
