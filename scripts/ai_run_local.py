"""Run the /ai run pipeline from the command line (no Discord typing needed).

Same logic as the `/ai run` slash command: build the prompt from the DB, run
Claude headless, optionally save the result and post it to #ai-analysis.

Examples:
    # Just print the prompt that would be sent (no Claude call, no auth needed):
    python scripts/ai_run_local.py --program naver-comic --mode idor-review --prompt-only

    # Run Claude and print the report locally (saves to DB, no Discord post):
    python scripts/ai_run_local.py --program naver-comic --mode idor-review

    # Run and also post the report to the program's #ai-analysis channel:
    python scripts/ai_run_local.py --program naver-comic --mode idor-review --post --create-findings
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Korean Windows consoles default to cp949, which cannot encode em-dashes,
# emoji, or the Korean text in reports. Force UTF-8 so printing never crashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Allow running as `python scripts/ai_run_local.py` from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import discord  # noqa: E402

from bountyops.config import Settings  # noqa: E402
from bountyops.db import Database  # noqa: E402
from bountyops.services.ai_prompts import build_ai_prompt, MODE_DESCRIPTIONS  # noqa: E402
from bountyops.services.ai_runner import find_claude_bin, run_claude  # noqa: E402
from bountyops.workspace import chunk_text  # noqa: E402


_FINDING_KEYWORDS = [
    "possible", "candidate", "finding", "vulnerability", "idor",
    "pii", "token", "auth bypass", "exposure",
]


def build_prompt_for(db: Database, program, mode: str) -> str:
    in_scope = db.list_scope_items(program.id, "in")
    out_scope = db.list_scope_items(program.id, "out")
    restrictions = db.list_restrictions(program.id, limit=80)
    endpoints = db.list_endpoints(program_id=program.id, scope_filter="all", limit=80)
    evidence = [dict(r) for r in db.list_evidence(program.id, limit=40)]
    return build_ai_prompt(
        provider="claude",
        mode=mode,
        program_name=program.name,
        platform=program.platform,
        policy_url=program.policy_url,
        in_scope=in_scope,
        out_scope=out_scope,
        restrictions=restrictions,
        endpoints=endpoints,
        evidence=evidence,
    )


def create_findings_from_text(db: Database, program_id: int, text: str, result_id: int) -> list[int]:
    candidates: list[str] = []
    for line in text.splitlines():
        clean = line.strip(" -*\t")
        low = clean.lower()
        if len(clean) < 12 or len(clean) > 220:
            continue
        if any(k in low for k in _FINDING_KEYWORDS) and clean not in candidates:
            candidates.append(clean)
        if len(candidates) >= 10:
            break
    created: list[int] = []
    for c in candidates:
        fid = db.add_finding(
            program_id=program_id,
            title=c[:120],
            vuln_type="AI-candidate",
            severity="unknown",
            endpoint_id=None,
            summary=f"Parsed from AI auto-run #{result_id}: {c}",
            impact="Needs human validation.",
        )
        created.append(fid)
    return created


async def post_to_ai_channel(settings: Settings, program, header: str, body: str) -> bool:
    """Log the bot in briefly and post the report to the program's #ai-analysis channel."""
    category_id = getattr(program, "discord_category_id", None)
    if not category_id:
        print("[post] program has no discord_category_id; skipping post.")
        return False

    intents = discord.Intents.default()
    client = discord.Client(intents=intents)
    state = {"ok": False}

    @client.event
    async def on_ready():  # noqa: ANN202
        try:
            category = client.get_channel(category_id)
            if category is None:
                category = await client.fetch_channel(category_id)
            channel = discord.utils.get(getattr(category, "text_channels", []), name="ai-analysis")
            if channel is None:
                print("[post] #ai-analysis channel not found under category.")
            else:
                await channel.send(header)
                for chunk in chunk_text(body, limit=1900):
                    await channel.send(chunk)
                state["ok"] = True
                print(f"[post] posted report to #{channel.name}.")
        finally:
            await client.close()

    await client.start(settings.discord_token)
    return state["ok"]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run the /ai run pipeline locally.")
    parser.add_argument("--program", required=True, help="program name (e.g. naver-comic)")
    parser.add_argument("--mode", default="idor-review", choices=list(MODE_DESCRIPTIONS.keys()))
    parser.add_argument("--prompt-only", action="store_true", help="print the prompt and exit (no Claude call)")
    parser.add_argument("--post", action="store_true", help="also post the report to #ai-analysis")
    parser.add_argument("--create-findings", action="store_true", help="extract finding candidates into the DB")
    parser.add_argument("--no-save", action="store_true", help="do not store the result in ai_results")
    args = parser.parse_args()

    settings = Settings.load()
    db = Database(settings.database_path)
    db.init()

    program = db.get_program_by_name(args.program)
    if not program:
        print(f"Program not found: {args.program}")
        return 2

    prompt_text = build_prompt_for(db, program, args.mode)

    if args.prompt_only:
        print("=" * 70)
        print(f"PROMPT — {program.name} / {args.mode} ({len(prompt_text)} chars)")
        print("=" * 70)
        print(prompt_text)
        return 0

    claude_bin = find_claude_bin(settings.claude_bin)
    if not claude_bin:
        print("claude.exe not found. Set CLAUDE_BIN in .env.")
        return 3
    print(f"[run] claude: {claude_bin}")
    print(f"[run] {program.name} / {args.mode} — running (timeout {int(settings.ai_timeout)}s)...")

    result = await run_claude(
        prompt_text,
        claude_bin=claude_bin,
        cwd=str(settings.storage_dir.parent),
        oauth_token=settings.claude_oauth_token,
        timeout=settings.ai_timeout,
    )

    if not result.ok:
        print(f"[run] FAILED ({result.duration_s:.0f}s): {result.error}")
        return 4

    text = result.text or "(empty response)"
    print("=" * 70)
    print(f"REPORT — {program.name} / {args.mode}  ({result.duration_s:.0f}s, {len(text)} chars)")
    print("=" * 70)
    print(text)
    print("=" * 70)

    rid = None
    if not args.no_save:
        rid = db.add_ai_result(
            program_id=program.id,
            provider="claude",
            mode=args.mode,
            title=f"{args.mode} auto-run (local)",
            body=text,
        )
        print(f"[db] saved ai_result #{rid}")

    if args.create_findings and rid is not None:
        created = create_findings_from_text(db, program.id, text, rid)
        print(f"[db] created findings: {created or '-'}")

    if args.post:
        header = (
            f"# 🤖 AI Auto-Run{f' #{rid}' if rid else ''} — claude / {args.mode}\n"
            f"- ⏱️ {result.duration_s:.0f}s · local run (read-only)"
        )
        ok = await post_to_ai_channel(settings, program, header, text)
        print(f"[post] {'done' if ok else 'skipped/failed'}")

    db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
