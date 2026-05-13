from __future__ import annotations

import discord

from .db import Database
from .models import Program, BurpImport
from .scoring import calculate_score


def money(value: int) -> str:
    if value <= 0:
        return "미기재"
    return f"{value:,}"


def make_program_embed(db: Database, program: Program) -> discord.Embed:
    in_scope = db.list_scope_items(program.id, "in")
    out_scope = db.list_scope_items(program.id, "out")
    notices = db.list_notices(program.id, limit=5)
    restrictions = db.list_restrictions(program.id, limit=10)
    import_count = db.count_imports(program.id)
    endpoint_count = db.count_endpoints(program.id)

    score = calculate_score(program, len(in_scope))

    embed = discord.Embed(
        title=f"🎯 {program.name}",
        description="BountyOps v0.2 workspace",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Platform", value=program.platform or "미기재", inline=True)
    embed.add_field(name="Reward", value=f"{money(program.reward_min)} ~ {money(program.reward_max)}", inline=True)
    embed.add_field(name="Score", value=str(score), inline=True)
    embed.add_field(name="In-scope count", value=str(len(in_scope)), inline=True)
    embed.add_field(name="Source code / GitHub", value="있음" if program.source_code else "없음/미확인", inline=True)
    embed.add_field(name="Time limit", value="있음" if program.has_time_limit else "없음/미확인", inline=True)
    embed.add_field(name="Burp imports", value=str(import_count), inline=True)
    embed.add_field(name="Endpoints", value=str(endpoint_count), inline=True)

    if program.time_limit_note:
        embed.add_field(name="⏰ Time limit note", value=program.time_limit_note[:1000], inline=False)

    if program.policy_url:
        embed.add_field(name="Policy URL", value=program.policy_url[:1000], inline=False)

    in_scope_text = "\n".join(f"- `{s.value}` {s.note}" for s in in_scope[:20]) or "아직 등록 없음"
    out_scope_text = "\n".join(f"- `{s.value}` {s.note}" for s in out_scope[:20]) or "아직 등록 없음"
    restriction_text = "\n".join(f"- **{r.severity}**: {r.text}" for r in restrictions[:10]) or "아직 등록 없음"
    notice_text = "\n".join(f"- **{n.title}**: {n.summary}" for n in notices[:5]) or "아직 등록 없음"

    embed.add_field(name="✅ In-scope", value=in_scope_text[:1024], inline=False)
    embed.add_field(name="🚫 Out-of-scope", value=out_scope_text[:1024], inline=False)
    embed.add_field(name="⚠️ Restrictions", value=restriction_text[:1024], inline=False)
    embed.add_field(name="📢 Notices", value=notice_text[:1024], inline=False)

    embed.set_footer(text="Use /burp import_file, /endpoint list, /program refresh")
    return embed


def make_import_embed(db: Database, program: Program, burp_import: BurpImport) -> discord.Embed:
    embed = discord.Embed(
        title=f"📥 Burp Import #{burp_import.id}",
        description=f"Program: **{program.name}**",
        color=discord.Color.orange(),
    )
    embed.add_field(name="Filename", value=burp_import.filename[:1000], inline=False)
    embed.add_field(name="Format", value=burp_import.format, inline=True)
    embed.add_field(name="Total endpoints", value=str(burp_import.total_items), inline=True)
    embed.add_field(name="In-scope", value=str(burp_import.in_scope_items), inline=True)
    embed.add_field(name="Out-of-scope", value=str(burp_import.out_scope_items), inline=True)
    embed.add_field(name="Unknown", value=str(burp_import.unknown_scope_items), inline=True)
    embed.add_field(name="Sanitized file", value=f"`{burp_import.sanitized_path}`"[:1000], inline=False)
    embed.set_footer(text="Use /endpoint list to inspect parsed endpoints")
    return embed


async def create_program_thread(
    *,
    forum_channel: discord.ForumChannel,
    db: Database,
    program: Program,
) -> discord.Thread | None:
    embed = make_program_embed(db, program)

    result = await forum_channel.create_thread(
        name=f"[{program.platform}] {program.name}"[:100],
        content="새 버그바운티 프로그램 workspace가 생성되었습니다.",
        embed=embed,
    )

    thread = getattr(result, "thread", None)
    if thread is None and isinstance(result, tuple):
        thread = result[0]
    if thread is None and isinstance(result, discord.Thread):
        thread = result

    if thread is not None:
        db.set_program_thread(program.id, thread.id)

    return thread


async def get_program_thread(bot: discord.Client, program: Program) -> discord.Thread | None:
    if not program.discord_thread_id:
        return None

    thread = bot.get_channel(program.discord_thread_id)
    if thread is None:
        try:
            thread = await bot.fetch_channel(program.discord_thread_id)
        except discord.DiscordException:
            return None

    if isinstance(thread, discord.Thread):
        return thread
    return None


async def refresh_program_thread(
    *,
    bot: discord.Client,
    db: Database,
    program: Program,
) -> bool:
    thread = await get_program_thread(bot, program)
    if thread is None:
        return False

    embed = make_program_embed(db, program)
    await thread.send(content="🔄 Workspace summary refreshed.", embed=embed)
    return True


async def post_import_summary(
    *,
    bot: discord.Client,
    db: Database,
    program: Program,
    burp_import: BurpImport,
) -> bool:
    thread = await get_program_thread(bot, program)
    if thread is None:
        return False

    embed = make_import_embed(db, program, burp_import)
    await thread.send(content="📥 New Burp/HAR import parsed.", embed=embed)
    return True
