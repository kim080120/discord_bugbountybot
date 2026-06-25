from __future__ import annotations

import json
import discord
from discord import app_commands

from ..services.hackerone_api import fetch_hackerone_program, save_hackerone_result


def normalize_scope_entry(entry) -> tuple[str, str]:
    """
    Supports both v0.3.2 dict entries and legacy v0.3.1 string entries:
    "value | type=... | bounty=..."
    """
    if isinstance(entry, dict):
        return str(entry.get("value") or "").strip(), str(entry.get("note") or "").strip()

    raw = str(entry).strip()
    if " | " in raw:
        value, note = raw.split(" | ", 1)
        return value.strip(), note.strip()
    return raw, ""


def render_scope_entries(entries, limit: int = 10) -> str:
    lines = []
    for entry in entries[:limit]:
        value, note = normalize_scope_entry(entry)
        if not value:
            continue
        if note:
            lines.append(f"- `{value}` — {note[:180]}")
        else:
            lines.append(f"- `{value}`")
    return "\n".join(lines) or "_None_"


def render_money(value: int) -> str:
    return "Unknown" if int(value or 0) <= 0 else f"{int(value):,}"


def make_preview_embed(crawl_id: int, row) -> discord.Embed:
    in_scope = json.loads(row["in_scope_json"])
    out_scope = json.loads(row["out_scope_json"])
    restrictions = json.loads(row["restrictions_json"])
    notices = json.loads(row["notices_json"])

    embed = discord.Embed(
        title=f"🕷️ Crawl Preview #{crawl_id}",
        description="Workspace has not been created yet. Review this preview, then run `/crawl apply crawl_id:<id>` if it looks correct.",
        color=discord.Color.gold(),
    )
    embed.add_field(name="Platform", value=row["platform"], inline=True)
    embed.add_field(name="Suggested name", value=row["suggested_name"] or "-", inline=True)
    embed.add_field(name="Reward max", value=render_money(row["reward_max"]), inline=True)
    embed.add_field(name="Source URL", value=row["source_url"][:1000] or "-", inline=False)

    rest_text = "\n".join(f"- {x}" for x in restrictions[:5]) or "_None_"
    notice_text = "\n".join(f"- {x}" for x in notices[:5]) or "_None_"

    embed.add_field(name=f"In-scope candidates ({len(in_scope)})", value=render_scope_entries(in_scope)[:1024], inline=False)
    embed.add_field(name=f"Out-of-scope candidates ({len(out_scope)})", value=render_scope_entries(out_scope)[:1024], inline=False)
    embed.add_field(name=f"Restrictions ({len(restrictions)})", value=rest_text[:1024], inline=False)
    embed.add_field(name="Notices", value=notice_text[:1024], inline=False)
    return embed


class HackerOneCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="hackerone", description="HackerOne 프로그램 후보 수집")
        self.bot = bot

    @app_commands.command(name="site", description="HackerOne API로 handle/URL의 structured scope 후보만 저장")
    async def site(self, interaction: discord.Interaction, handle_or_url: str):
        await interaction.response.defer(ephemeral=False)

        username = getattr(self.bot.settings, "hackerone_username", "")
        token = getattr(self.bot.settings, "hackerone_api_token", "")

        if not username or not token:
            await interaction.followup.send(
                "HackerOne API 설정이 없습니다. `.env`에 `HACKERONE_USERNAME`, `HACKERONE_API_TOKEN`을 추가한 뒤 봇을 재시작하세요."
            )
            return

        try:
            result = fetch_hackerone_program(
                handle_or_url,
                username=username,
                token=token,
            )
            raw_path, parsed_path = save_hackerone_result(result, self.bot.settings.storage_dir)

            crawl_id = self.bot.db.add_site_crawl(
                platform=result.platform,
                input_value=result.input_value,
                source_url=result.source_url,
                suggested_name=result.suggested_name,
                reward_max=result.reward_max,
                source_code=result.source_code,
                has_time_limit=result.has_time_limit,
                time_limit_note=result.time_limit_note,
                in_scope_json=json.dumps(result.in_scope, ensure_ascii=False),
                out_scope_json=json.dumps(result.out_scope, ensure_ascii=False),
                restrictions_json=json.dumps(result.restrictions, ensure_ascii=False),
                notices_json=json.dumps(result.notices, ensure_ascii=False),
                raw_path=raw_path,
                parsed_path=parsed_path,
            )
            row = self.bot.db.get_site_crawl(crawl_id)
        except Exception as exc:
            await interaction.followup.send(f"HackerOne API 수집 실패: `{type(exc).__name__}: {exc}`")
            return

        await interaction.followup.send(embed=make_preview_embed(crawl_id, row))
