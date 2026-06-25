"""Program recommender for multi-program platforms (Bugcrowd, HackerOne, huntr).

Ranks programs for a solo hunter by a transparent 0–100 opportunity score built
from three axes:
  - reward   (payout ceiling)
  - scope    (attack surface: in-scope count / breadth)
  - dup-risk (how picked-over the program already is)

Each platform exposes different signals, so the per-axis computation differs, but
the output shape (ProgramRec) and the 0–100 score are consistent and comparable
within a platform. Duplicate-risk is a PROXY, never a measured duplicate rate —
labels are Low / Med / High with the reasoning shown.

Signals (all public unless noted):
  Bugcrowd : engagements.json (reward, scopeRank) + changelog (scope, age) +
             crowdstream.json (accepted submissions in 6mo = dup-risk).
  HackerOne: Hacker API programs + structured_scopes. NO $ amounts exposed, so
             reward/dup are proxies (offers_bounties + max_severity; age × scope).
  huntr    : /bounties repo list + GitHub API stars/forks/activity (dup-risk).
"""

from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .platform_importers import _get_json, _get_text, _BC_LIST


# Scoring weights — tuned for a solo hunter who avoids crowded programs.
# Competition-avoidance: duplicate-risk is weighted highest.
W_REWARD = 0.30
W_SCOPE = 0.20
W_DUP = 0.50
# huntr has no per-repo reward/scope, so it scores on competition + activity only.
W_HUNTR_DUP = 0.70
W_HUNTR_FRESH = 0.30


@dataclass
class ProgramRec:
    platform: str
    name: str
    key: str          # slug / handle / owner+repo
    url: str
    reward_max: int   # USD, 0 = unknown/not-exposed
    in_scope: int
    out_scope: int
    dup_risk: str     # Low / Med / High / ?
    dup_detail: str
    score: float      # 0–100
    extra: str
    reward_cur: str = "USD"


def _parse_money(value) -> int:
    digits = re.sub(r"[^0-9]", "", str(value or ""))
    return int(digits) if digits else 0


def _months_since(iso: str | None) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).days / 30.44)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Bugcrowd
# --------------------------------------------------------------------------- #

def _bc_detail(slug: str) -> dict:
    changelog = _get_json(f"https://bugcrowd.com/engagements/{slug}/changelog.json", accept="*/*")
    entries = changelog.get("changelogs") or []
    uuid = next((c["id"] for c in entries if c.get("changelogState") == "Latest"), None)
    if not uuid and entries:
        uuid = entries[0].get("id")
    in_scope = out_scope = 0
    age_months = None
    if uuid:
        cj = _get_json(
            f"https://bugcrowd.com/engagements/{slug}/changelog/{uuid}.json", accept="*/*"
        )
        data = cj.get("data") or {}
        for section in data.get("scope") or []:
            n = len(section.get("targets") or [])
            if section.get("inScope"):
                in_scope += n
            else:
                out_scope += n
        age_months = _months_since((data.get("engagement") or {}).get("startsAt"))

    accepted = None
    try:
        cs = _get_json(f"https://bugcrowd.com/engagements/{slug}/crowdstream.json", accept="*/*")
        accepted = (cs.get("pagination_meta") or {}).get("totalCount")
    except Exception:
        accepted = 0  # 404 = no public accepted submissions = fresh/quiet
    return {"in_scope": in_scope, "out_scope": out_scope, "age_months": age_months, "accepted6mo": accepted}


def _dup_from_accepted(accepted) -> tuple[str, float, str]:
    if accepted is None:
        return "?", 0.5, "활동 데이터 없음"
    if accepted == 0:
        return "Low", 1.0, "최근 6개월 채택 0건 (신규/조용)"
    if accepted <= 5:
        return "Low", 0.8, f"최근 6개월 채택 {accepted}건"
    if accepted <= 15:
        return "Med", 0.5, f"최근 6개월 채택 {accepted}건"
    return "High", 0.2, f"최근 6개월 채택 {accepted}건 (경쟁 치열)"


def recommend_bugcrowd(limit: int = 12, min_reward: int = 0, pages: int = 10) -> list[ProgramRec]:
    pool: list[dict] = []
    for page in range(1, pages + 1):
        data = _get_json(_BC_LIST.format(page=page), accept="application/json")
        engagements = data.get("engagements") or []
        if not engagements:
            break
        for e in engagements:
            if e.get("isPrivate") or e.get("isDemo"):
                continue
            if e.get("accessStatus") != "open":
                continue
            if (e.get("productEngagementType") or {}).get("label") != "Bug Bounty":
                continue
            slug = (e.get("briefUrl") or "").rstrip("/").split("/")[-1]
            if not slug:
                continue
            reward_max = _parse_money((e.get("rewardSummary") or {}).get("maxReward"))
            if reward_max < min_reward:
                continue
            pool.append({
                "slug": slug,
                "name": (e.get("name") or "").strip(),
                "reward_max": reward_max,
                "scope_rank": e.get("scopeRank") or 0,
            })

    # Pre-rank cheaply by reward then scope breadth; only the top candidates get
    # the expensive 3-request detail fetch.
    pool.sort(key=lambda p: (p["reward_max"], p["scope_rank"]), reverse=True)

    recs: list[ProgramRec] = []
    for p in pool[: max(1, limit)]:
        try:
            d = _bc_detail(p["slug"])
        except Exception:
            d = {"in_scope": 0, "out_scope": 0, "age_months": None, "accepted6mo": None}
        dup_label, dup_score, dup_detail = _dup_from_accepted(d["accepted6mo"])
        reward_score = min(p["reward_max"], 10000) / 10000
        scope_score = 0.6 * (p["scope_rank"] / 5) + 0.4 * min(d["in_scope"], 20) / 20
        score = (W_REWARD * reward_score + W_SCOPE * scope_score + W_DUP * dup_score) * 100
        age = f"{d['age_months'] / 12:.1f}y" if d["age_months"] is not None else "?"
        recs.append(ProgramRec(
            platform="Bugcrowd",
            name=p["name"],
            key=p["slug"],
            url=f"https://bugcrowd.com/engagements/{p['slug']}",
            reward_max=p["reward_max"],
            in_scope=d["in_scope"],
            out_scope=d["out_scope"],
            dup_risk=dup_label,
            dup_detail=dup_detail,
            score=round(score, 1),
            extra=f"scopeRank {p['scope_rank']} · {age}",
        ))
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs


# --------------------------------------------------------------------------- #
# huntr  (reward is roughly flat; the differentiator is competition via stars)
# --------------------------------------------------------------------------- #

def _github_repo(owner_repo: str, token: str | None) -> tuple[dict | None, str]:
    """Fetch a repo. Returns (trimmed_data | None, status) where status is
    'ok' | 'ratelimit' | 'error'."""
    import json as _json
    import urllib.error
    import urllib.request

    headers = {"User-Agent": "BountyOps/0.6", "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{owner_repo}", headers=headers)
        with urllib.request.urlopen(req, timeout=20) as res:
            g = _json.loads(res.read())
        return {
            "stargazers_count": g.get("stargazers_count") or 0,
            "forks_count": g.get("forks_count") or 0,
            "subscribers_count": g.get("subscribers_count") or 0,
            "pushed_at": g.get("pushed_at"),
            "archived": bool(g.get("archived")),
        }, "ok"
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 429):
            return None, "ratelimit"
        return None, "error"
    except Exception:
        return None, "error"


def _gh_cache_path(cache_dir):
    from pathlib import Path
    return Path(cache_dir) / "github_cache.json" if cache_dir else None


def _load_gh_cache(cache_dir) -> dict:
    p = _gh_cache_path(cache_dir)
    if p and p.exists():
        try:
            import json as _json
            return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_gh_cache(cache_dir, cache: dict) -> None:
    p = _gh_cache_path(cache_dir)
    if not p:
        return
    try:
        import json as _json
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_json.dumps(cache), encoding="utf-8")
    except Exception:
        pass


def _cache_fresh(entry: dict, max_days: float = 3.0) -> bool:
    months = _months_since(entry.get("_ts"))
    return months is not None and months * 30.44 <= max_days


def _dup_from_stars(stars: int) -> tuple[str, float, str]:
    # Continuous: fewer stars = fewer eyes on the code = less picked over.
    # ~316★ -> ~1.0, 10k -> ~0.5, 316k -> ~0.0. Avoids everyone tying in one bucket.
    saturation = max(0.0, math.log10(stars + 1) - 2.5) / 3.0
    dup_score = round(max(0.08, 1 - min(saturation, 1.0)), 3)
    if stars >= 30000:
        label, tag = "High", " (널리 감시됨)"
    elif stars >= 4000:
        label, tag = "Med", ""
    else:
        label, tag = "Low", " (덜 알려짐)"
    return label, dup_score, f"{stars:,}★{tag}"


def recommend_huntr(
    limit: int = 12,
    sample: int = 15,
    github_token: str | None = None,
    cache_dir=None,
) -> list[ProgramRec]:
    token = github_token or os.getenv("GITHUB_TOKEN") or None
    doc = _get_text("https://huntr.com/bounties")
    repos = []
    seen = set()
    for m in re.finditer(r"disclose/opensource\?target=https://github\.com/([\w.-]+/[\w.-]+)", doc):
        r = m.group(1)
        if r not in seen:
            seen.add(r)
            repos.append(r)
    if not repos:
        raise ValueError("huntr: no repos parsed")

    cache = _load_gh_cache(cache_dir)
    rate_limited = False
    recs: list[ProgramRec] = []
    for owner_repo in repos[: max(1, sample)]:
        gh = cache.get(owner_repo)
        if not (gh and _cache_fresh(gh)):
            fetched, status = _github_repo(owner_repo, token)
            if status == "ratelimit":
                rate_limited = True
                if gh is None:  # no cached fallback for this repo
                    continue
            elif fetched is not None:
                fetched["_ts"] = _now_iso()
                cache[owner_repo] = fetched
                gh = fetched
            elif gh is None:
                continue
        if gh is None or gh.get("archived"):
            continue
        stars = gh.get("stargazers_count") or 0
        months_idle = _months_since(gh.get("pushed_at"))
        # freshness: actively maintained repo still has live attack surface
        fresh_score = 1.0 if (months_idle is not None and months_idle <= 3) else (
            0.6 if (months_idle is not None and months_idle <= 12) else 0.3
        )
        dup_label, dup_score, dup_detail = _dup_from_stars(stars)
        score = (W_HUNTR_DUP * dup_score + W_HUNTR_FRESH * fresh_score) * 100
        idle = f"{months_idle:.0f}mo idle" if months_idle is not None else "?"
        recs.append(ProgramRec(
            platform="huntr",
            name=owner_repo,
            key=owner_repo,
            url=f"https://github.com/{owner_repo}",
            reward_max=0,  # huntr reward is a flat category tier ($500–$4000), not per-repo
            in_scope=1,
            out_scope=0,
            dup_risk=dup_label,
            dup_detail=dup_detail,
            score=round(score, 1),
            extra=f"{stars:,}★ · {idle}",
        ))

    _save_gh_cache(cache_dir, cache)
    if not recs and rate_limited:
        raise RuntimeError(
            "GitHub API 한도 초과 (무인증 60회/시간). .env에 GITHUB_TOKEN을 넣거나(5000회/시간) "
            "잠시 후 다시 시도하세요. 한 번 성공하면 결과가 캐시돼 재실행은 무료입니다."
        )
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[: max(1, limit)]


# --------------------------------------------------------------------------- #
# HackerOne  (Hacker API — proxy scores only, no $ amounts exposed)
# --------------------------------------------------------------------------- #

_SEV = {"critical": 1.0, "high": 0.75, "medium": 0.5, "low": 0.25, "none": 0.0}


def recommend_hackerone(*, username: str, token: str, limit: int = 12, pool_size: int = 100) -> list[ProgramRec]:
    from .hackerone_api import h1_get_json

    listing = h1_get_json(f"/hackers/programs?page%5Bsize%5D={pool_size}", username=username, token=token)
    candidates = []
    for item in listing.get("data") or []:
        a = item.get("attributes") or {}
        if a.get("submission_state") != "open":
            continue
        if a.get("state") not in (None, "public_mode"):
            continue
        if not a.get("offers_bounties"):
            continue
        candidates.append(a)

    # Pre-rank: bounty-offering + fast pay + safe harbor + recency of acceptance.
    def pre(a: dict) -> tuple:
        return (
            1 if a.get("gold_standard_safe_harbor") else 0,
            1 if a.get("fast_payments") else 0,
            a.get("started_accepting_at") or "",
        )

    candidates.sort(key=pre, reverse=True)

    ages = [_months_since(a.get("started_accepting_at")) for a in candidates]
    max_age = max([x for x in ages if x is not None], default=1.0) or 1.0

    recs: list[ProgramRec] = []
    for a in candidates[: max(1, limit)]:
        handle = a.get("handle") or ""
        try:
            scopes = h1_get_json(
                f"/hackers/programs/{handle}/structured_scopes?page%5Bsize%5D=100",
                username=username, token=token,
            )
        except Exception:
            scopes = {"data": []}
        in_scope = out_scope = 0
        max_sev = 0.0
        for s in scopes.get("data") or []:
            sa = s.get("attributes") or {}
            if sa.get("eligible_for_submission"):
                in_scope += 1
            else:
                out_scope += 1
            max_sev = max(max_sev, _SEV.get(str(sa.get("max_severity") or "").lower(), 0.0))

        reward_score = (
            0.6
            + 0.25 * max_sev
            + 0.10 * (1 if a.get("fast_payments") else 0)
            + 0.05 * (1 if a.get("gold_standard_safe_harbor") else 0)
        )
        scope_score = math.log1p(in_scope) / math.log1p(20)
        scope_score = min(1.0, scope_score) + (0.1 if a.get("open_scope") else 0)
        age_m = _months_since(a.get("started_accepting_at"))
        age_norm = (age_m / max_age) if age_m is not None else 0.5
        dup_raw = 0.6 * age_norm + 0.4 * (1 / (1 + in_scope))
        dup_score = max(0.0, 1 - dup_raw)
        dup_label = "Low" if dup_score >= 0.6 else ("Med" if dup_score >= 0.35 else "High")
        score = (W_REWARD * min(reward_score, 1.0) + W_SCOPE * min(scope_score, 1.0) + W_DUP * dup_score) * 100

        sev_name = next((k for k, v in _SEV.items() if v == max_sev), "?")
        age_txt = f"{age_m / 12:.1f}y" if age_m is not None else "age?"
        recs.append(ProgramRec(
            platform="HackerOne",
            name=a.get("name") or handle,
            key=handle,
            url=f"https://hackerone.com/{handle}",
            reward_max=0,  # not exposed by the Hacker API
            in_scope=in_scope,
            out_scope=out_scope,
            dup_risk=dup_label,
            dup_detail=f"나이×스코프 추정 (max_sev {sev_name})",
            score=round(score, 1),
            extra=f"max_sev {sev_name} · {age_txt}" + (" · open_scope" if a.get("open_scope") else ""),
        ))
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs


# --------------------------------------------------------------------------- #
# Intigriti  (bounty-targets-data mirror: reward + scope, no public activity data)
# --------------------------------------------------------------------------- #

def recommend_intigriti(limit: int = 12, min_reward: int = 0) -> list[ProgramRec]:
    from .platform_importers import list_intigriti_programs

    recs: list[ProgramRec] = []
    for p in list_intigriti_programs():
        if p["reward"] < min_reward:
            continue
        in_c, out_c = p["in"], p["out"]
        reward_score = min(p["reward"], 10000) / 10000  # EUR, treated USD-ish for normalization

        scope_score = min(in_c, 20) / 20

        # No public submission/activity data on Intigriti's mirror, so dup-risk is a
        # heuristic: bigger scope + signup friction = less contested; high reward on a
        # tiny scope = everyone piles on the same few targets.
        scope_factor = min(in_c, 20) / 20 * 0.5
        reward_pressure = reward_score * 0.4
        friction = 0.15 if (p.get("tac") or p.get("two_fa")) else 0.0
        dup_score = max(0.05, min(1.0, 0.5 + scope_factor - reward_pressure + friction))
        dup_label = "Low" if dup_score >= 0.65 else ("Med" if dup_score >= 0.4 else "High")

        score = (W_REWARD * reward_score + W_SCOPE * scope_score + W_DUP * dup_score) * 100

        types = p.get("types") or {}
        type_str = "·".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda x: -x[1])[:4])
        flags = []
        if p.get("two_fa"):
            flags.append("2FA")
        if p.get("tac"):
            flags.append("TAC")
        min_str = f"min {p['reward_min']:,}" if p.get("reward_min") else ""
        extra = " · ".join(x for x in (type_str, min_str, " ".join(flags)) if x)

        recs.append(ProgramRec(
            platform="Intigriti",
            name=p["name"],
            key=p["handle"],
            url=f"https://app.intigriti.com/programs/{p['handle']}",
            reward_max=p["reward"],
            in_scope=in_c,
            out_scope=out_c,
            dup_risk=dup_label,
            dup_detail="스코프/리워드 추정",
            score=round(score, 1),
            extra=extra,
            reward_cur=p["currency"],
        ))
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[: max(1, limit)]


# --------------------------------------------------------------------------- #
# YesWeHack  (bounty-targets-data mirror — EUR, same heuristic as Intigriti)
# --------------------------------------------------------------------------- #

def recommend_yeswehack(limit: int = 12, min_reward: int = 0) -> list[ProgramRec]:
    from .platform_importers import list_yeswehack_programs

    recs: list[ProgramRec] = []
    for p in list_yeswehack_programs():
        if p["reward"] < min_reward:
            continue
        in_c, out_c = p["in"], p["out"]
        reward_score = min(p["reward"], 10000) / 10000
        scope_score = min(in_c, 20) / 20

        scope_factor = min(in_c, 20) / 20 * 0.5
        reward_pressure = reward_score * 0.4
        dup_score = max(0.05, min(1.0, 0.5 + scope_factor - reward_pressure))
        dup_label = "Low" if dup_score >= 0.65 else ("Med" if dup_score >= 0.4 else "High")

        score = (W_REWARD * reward_score + W_SCOPE * scope_score + W_DUP * dup_score) * 100

        types = p.get("types") or {}
        type_str = "·".join(f"{k} {v}" for k, v in sorted(types.items(), key=lambda x: -x[1])[:4])
        min_str = f"min {p['reward_min']:,}" if p.get("reward_min") else ""
        extra = " · ".join(x for x in (type_str, min_str) if x)

        recs.append(ProgramRec(
            platform="YesWeHack",
            name=p["name"],
            key=p["handle"],
            url=f"https://yeswehack.com/programs/{p['handle']}",
            reward_max=p["reward"],
            in_scope=in_c,
            out_scope=out_c,
            dup_risk=dup_label,
            dup_detail="스코프/리워드 추정",
            score=round(score, 1),
            extra=extra,
            reward_cur="EUR",
        ))
    recs.sort(key=lambda r: r.score, reverse=True)
    return recs[: max(1, limit)]
