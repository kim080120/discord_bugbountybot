from __future__ import annotations

import re
import discord

from .db import Database
from .models import Program, BurpImport
from .scoring import calculate_score


DEFAULT_CHANNELS = [
    ("general", "Program summary and workspace notes"),
    ("scope", "In-scope and out-of-scope targets"),
    ("restrictions", "Testing restrictions, rules, and limits"),
    ("notices", "Policy notes, source references, and import messages"),
    ("burp-imports", "Burp/HAR import results"),
    ("ai-analysis", "Codex/Claude/AI analysis results"),
    ("evidence", "Evidence, screenshots, A/B comparison results"),
    ("report-drafts", "Bug bounty report drafts"),
]


def money(value: int) -> str:
    if value <= 0:
        return "Unknown"
    return f"{value:,}"


def safe_name(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9가-힣._-]+", "-", value)
    value = re.sub(r"-{2,}", "-", value).strip("-")
    return value[:90] or "bounty-program"


def program_workspace_name(program: Program) -> str:
    platform = safe_name(program.platform or "program")
    name = safe_name(program.name)
    return f"{platform}-{name}"[:100]


def parse_note(note: str) -> tuple[list[str], str]:
    """
    Convert:
      type=SOURCE_CODE | bounty=True | submission=True | max_severity=critical | long instruction
    into:
      metadata list + free-text note.
    """
    metadata = []
    free_text_parts = []

    for part in [p.strip() for p in (note or "").split("|") if p.strip()]:
        if "=" in part and len(part.split("=", 1)[0]) <= 32:
            metadata.append(part)
        else:
            free_text_parts.append(part)

    return metadata, " | ".join(free_text_parts)


def compact_scope_line(item) -> str:
    metadata, free_text = parse_note(item.note)
    details = []
    if metadata:
        details.append(", ".join(metadata[:4]))
    if free_text:
        details.append(free_text[:140])
    suffix = f" — {'; '.join(details)}" if details else ""
    return f"- `{item.value}`{suffix}"


def readable_scope_block(items, limit: int | None = None) -> str:
    selected = items if limit is None else items[:limit]
    lines: list[str] = []

    for idx, item in enumerate(selected, 1):
        metadata, free_text = parse_note(item.note)
        lines.append(f"{idx}. `{item.value}`")
        if metadata:
            lines.append(f"   - Metadata: {', '.join(metadata[:5])}")
        if free_text:
            lines.append(f"   - Note: {free_text[:260]}")
    return "\n".join(lines) if lines else "_No entries yet._"


def chunk_text(text: str, limit: int = 1850) -> list[str]:
    if not text:
        return [""]

    chunks: list[str] = []
    current = ""

    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line

    if current:
        chunks.append(current)

    return chunks or [""]


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
        description="BountyOps v0.3.4 workspace",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="Platform", value=program.platform or "Unknown", inline=True)
    embed.add_field(name="Reward", value=f"{money(program.reward_min)} ~ {money(program.reward_max)}", inline=True)
    embed.add_field(name="Score", value=str(score), inline=True)
    embed.add_field(name="In-scope targets", value=str(len(in_scope)), inline=True)
    embed.add_field(name="Out-of-scope targets", value=str(len(out_scope)), inline=True)
    embed.add_field(name="Source code", value="Yes" if program.source_code else "Unknown/No", inline=True)
    embed.add_field(name="Time limit", value="Yes" if program.has_time_limit else "Unknown/No", inline=True)
    embed.add_field(name="Burp imports", value=str(import_count), inline=True)
    embed.add_field(name="Endpoints", value=str(endpoint_count), inline=True)

    if program.time_limit_note:
        embed.add_field(name="⏰ Time limit note", value=program.time_limit_note[:1000], inline=False)

    if program.policy_url:
        embed.add_field(name="Policy URL", value=program.policy_url[:1000], inline=False)

    in_scope_text = "\n".join(compact_scope_line(s) for s in in_scope[:6]) or "_No entries yet._"
    out_scope_text = "\n".join(compact_scope_line(s) for s in out_scope[:6]) or "_No entries yet._"
    restriction_text = "\n".join(f"- **{r.severity}**: {r.text}" for r in restrictions[:6]) or "_No entries yet._"
    notice_text = "\n".join(f"- **{n.title}**: {n.summary}" for n in notices[:5]) or "_No entries yet._"

    embed.add_field(name="✅ In-scope preview", value=in_scope_text[:1024], inline=False)
    embed.add_field(name="🚫 Out-of-scope preview", value=out_scope_text[:1024], inline=False)
    embed.add_field(name="⚠️ Restrictions preview", value=restriction_text[:1024], inline=False)
    embed.add_field(name="📢 Notices preview", value=notice_text[:1024], inline=False)

    embed.set_footer(text="Full details are posted in #scope, #restrictions, and #notices")
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


def find_program_channel(bot: discord.Client, program: Program, channel_name: str) -> discord.TextChannel | None:
    category_id = getattr(program, "discord_category_id", None)
    if not category_id:
        return None

    category = bot.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return None

    channel = discord.utils.get(category.text_channels, name=channel_name)
    return channel if isinstance(channel, discord.TextChannel) else None


async def clear_channel_for_workspace(channel: discord.TextChannel, max_messages: int = 20) -> None:
    """
    Best-effort cleanup for newly created channels or manual refresh.
    Missing permissions should not break the bot.
    """
    try:
        async for msg in channel.history(limit=max_messages):
            if msg.author == channel.guild.me:
                try:
                    await msg.delete()
                except discord.DiscordException:
                    pass
    except discord.DiscordException:
        pass


async def populate_workspace_channels(db: Database, program: Program, channels: dict[str, discord.TextChannel]) -> None:
    in_scope = db.list_scope_items(program.id, "in")
    out_scope = db.list_scope_items(program.id, "out")
    restrictions = db.list_restrictions(program.id, limit=80)
    notices = db.list_notices(program.id, limit=80)

    if general := channels.get("general"):
        await general.send(
            content="Workspace created.",
            embed=make_program_embed(db, program),
        )

    if scope := channels.get("scope"):
        text = "\n".join(
            [
                f"# Scope — {program.platform} / {program.name}",
                "",
                "Use this channel as the source of truth for target classification.",
                "",
                "## ✅ In-scope Targets",
                readable_scope_block(in_scope),
                "",
                "## 🚫 Out-of-scope Targets",
                readable_scope_block(out_scope),
                "",
                "## Manual Corrections",
                "If the crawler missed or misclassified a target, add it manually:",
                "`/scope add program_name:<name> type:in value:<target> note:<reason>`",
                "`/scope add program_name:<name> type:out value:<target> note:<reason>`",
            ]
        )
        for chunk in chunk_text(text):
            await scope.send(chunk)

    if restrictions_ch := channels.get("restrictions"):
        lines = [
            f"# Testing Restrictions — {program.platform} / {program.name}",
            "",
            "Review this before any active testing.",
            "",
        ]
        if restrictions:
            for idx, r in enumerate(restrictions, 1):
                lines.append(f"{idx}. **{r.severity.upper()}** — {r.text}")
        else:
            lines.append("_No restrictions recorded yet._")

        for chunk in chunk_text("\n".join(lines)):
            await restrictions_ch.send(chunk)

    if notices_ch := channels.get("notices"):
        lines = [
            f"# Program Notices — {program.platform} / {program.name}",
            "",
            "Crawler notes, import sources, and policy metadata.",
            "",
        ]
        if notices:
            for idx, n in enumerate(notices, 1):
                lines.append(f"{idx}. **{n.title}** — {n.summary}")
        else:
            lines.append("_No notices recorded yet._")

        for chunk in chunk_text("\n".join(lines)):
            await notices_ch.send(chunk)

    if burp := channels.get("burp-imports"):
        await burp.send(
            "\n".join(
                [
                    "# Burp / HAR Imports",
                    "",
                    "Upload Burp raw HTTP, HAR, or txt exports here through the bot command:",
                    "`/burp import_file program_name:<name> file:<file> format:auto`",
                    "",
                    "Import results will be posted in this channel.",
                ]
            )
        )

    if ai := channels.get("ai-analysis"):
        await ai.send(
            "\n".join(
                [
                    "# AI Analysis",
                    "",
                    "Codex, Claude, and other AI analysis results will be stored here.",
                    "Recommended sections:",
                    "- Endpoint inventory review",
                    "- IDOR/BOLA candidates",
                    "- PII exposure review",
                    "- False-positive review",
                ]
            )
        )

    if evidence := channels.get("evidence"):
        await evidence.send(
            "\n".join(
                [
                    "# Evidence",
                    "",
                    "Store evidence references here:",
                    "- Burp request/response IDs",
                    "- Screenshots",
                    "- A/B account comparison notes",
                    "- Reproduction logs",
                    "",
                    "Do not paste raw secrets, cookies, tokens, or private user data.",
                ]
            )
        )

    if drafts := channels.get("report-drafts"):
        await drafts.send(
            "\n".join(
                [
                    "# Report Drafts",
                    "",
                    "Use this channel for report drafts before submission.",
                    "",
                    "Suggested structure:",
                    "1. Summary",
                    "2. Affected asset",
                    "3. Steps to reproduce",
                    "4. Evidence",
                    "5. Impact",
                    "6. Recommended fix",
                    "7. Limitations / false-positive checks",
                ]
            )
        )


async def post_scope_update(bot: discord.Client, program: Program, scope_type: str, value: str, note: str = "") -> bool:
    ch = find_program_channel(bot, program, "scope")
    if not ch:
        return False

    label = "✅ In-scope" if scope_type == "in" else "🚫 Out-of-scope"
    metadata, free_text = parse_note(note)
    lines = [f"## {label} manual update", f"- `{value}`"]
    if metadata:
        lines.append(f"  - Metadata: {', '.join(metadata[:5])}")
    if free_text:
        lines.append(f"  - Note: {free_text}")

    await ch.send("\n".join(lines))
    return True


async def create_program_workspace(
    *,
    guild: discord.Guild,
    db: Database,
    program: Program,
    parent_category: discord.CategoryChannel | None = None,
) -> discord.CategoryChannel | None:
    category_name = program_workspace_name(program)

    category = discord.utils.get(guild.categories, name=category_name)
    if category is not None:
        return None

    position = parent_category.position + 1 if parent_category else None
    category = await guild.create_category(
        name=category_name,
        position=position,
        reason=f"BountyOps category workspace for {program.name}",
    )

    created_channels: dict[str, discord.TextChannel] = {}
    for channel_name, topic in DEFAULT_CHANNELS:
        ch = await guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"BountyOps | {program.platform} - {program.name} | {topic}",
            reason=f"BountyOps default channel for {program.name}",
        )
        created_channels[channel_name] = ch

    general = created_channels.get("general")
    db.set_program_category(program.id, category.id, general.id if general else None)

    await populate_workspace_channels(db, program, created_channels)
    return category


async def create_program_thread(
    *,
    workspace_channel: discord.abc.GuildChannel,
    db: Database,
    program: Program,
) -> discord.Thread | None:
    embed = make_program_embed(db, program)

    if isinstance(workspace_channel, discord.TextChannel):
        thread = await workspace_channel.create_thread(
            name=program_workspace_name(program),
            type=discord.ChannelType.public_thread,
            auto_archive_duration=10080,
            reason=f"BountyOps workspace for {program.name}",
        )
        await thread.send(content="Workspace created.", embed=embed)
        db.set_program_thread(program.id, thread.id)
        return thread

    return None


async def get_program_output_channel(bot: discord.Client, program: Program) -> discord.abc.Messageable | None:
    channel_id = program.discord_thread_id
    if not channel_id:
        return None

    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except discord.DiscordException:
            return None

    if isinstance(channel, (discord.TextChannel, discord.Thread)):
        return channel
    return None


async def refresh_program_thread(
    *,
    bot: discord.Client,
    db: Database,
    program: Program,
) -> bool:
    channel = await get_program_output_channel(bot, program)
    if channel is None:
        return False

    await channel.send(content="🔄 Workspace summary refreshed.", embed=make_program_embed(db, program))

    category = bot.get_channel(getattr(program, "discord_category_id", 0) or 0)
    if isinstance(category, discord.CategoryChannel):
        channels = {ch.name: ch for ch in category.text_channels}
        await populate_workspace_channels(db, program, channels)
    return True


async def post_import_summary(
    *,
    bot: discord.Client,
    db: Database,
    program: Program,
    burp_import: BurpImport,
) -> bool:
    target = find_program_channel(bot, program, "burp-imports")
    if target:
        await target.send(content="📥 New Burp/HAR import parsed.", embed=make_import_embed(db, program, burp_import))
        return True

    channel = await get_program_output_channel(bot, program)
    if channel is None:
        return False

    await channel.send(content="📥 New Burp/HAR import parsed.", embed=make_import_embed(db, program, burp_import))
    return True
