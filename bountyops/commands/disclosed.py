from __future__ import annotations

import asyncio
import discord
from discord import app_commands

from ..services.disclosed_reports import huntr_disclosed, bugcrowd_disclosed, hackerone_disclosed


def _render(reports, title: str, color: discord.Color, footer: str = "") -> discord.Embed:
    lines = []
    for i, r in enumerate(reports, 1):
        line = f"`#{i}` **{r.title}**"
        if r.meta:
            line += f"\n   {r.meta}"
        line += f"\n   <{r.url}>"
        lines.append(line)
    embed = discord.Embed(title=title, description="\n".join(lines)[:4000] or "결과 없음.", color=color)
    if footer:
        embed.set_footer(text=footer)
    return embed


class DisclosedCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="disclosed", description="프로그램의 과거 공개 제보(disclosed reports) 보기")
        self.bot = bot

    @app_commands.command(name="huntr", description="huntr repo의 공개 제보 목록 (제목+링크)")
    async def huntr(self, interaction: discord.Interaction, repo: str, limit: int = 15):
        await interaction.response.defer(ephemeral=False)
        try:
            reports = await asyncio.to_thread(huntr_disclosed, repo, limit)
        except Exception as exc:
            await interaction.followup.send(f"huntr disclosed 실패: `{type(exc).__name__}: {exc}`")
            return
        await interaction.followup.send(embed=_render(
            reports,
            f"📜 huntr disclosed — {repo} (top {len(reports)})",
            discord.Color.purple(),
            footer="이미 제보된 취약점들 — 중복/패턴 참고용. 상태·날짜는 리포트 클릭해서 확인.",
        ))

    @app_commands.command(name="hackerone", description="HackerOne 최근 공개 제보 (hacktivity, .env 토큰)")
    async def hackerone(self, interaction: discord.Interaction, handle: str = "", limit: int = 20):
        await interaction.response.defer(ephemeral=False)
        username = getattr(self.bot.settings, "hackerone_username", "")
        token = getattr(self.bot.settings, "hackerone_api_token", "")
        if not username or not token:
            await interaction.followup.send(
                "HackerOne 토큰이 없습니다 (.env HACKERONE_USERNAME/HACKERONE_API_TOKEN)."
            )
            return
        want = handle.strip() or None
        try:
            reports = await asyncio.to_thread(
                lambda: hackerone_disclosed(username=username, token=token, handle=want, limit=limit)
            )
        except Exception as exc:
            await interaction.followup.send(f"HackerOne disclosed 실패: `{type(exc).__name__}: {exc}`")
            return
        if not reports:
            await interaction.followup.send(
                f"`{want}` 프로그램의 최근 공개 제보를 못 찾았어요 (REST hacktivity는 프로그램 필터를 지원 안 해, 최근 공개 활동 한정)."
                if want else "최근 공개 제보가 없어요."
            )
            return
        title = f"📜 HackerOne 공개 제보 — {want}" if want else "📜 HackerOne 최근 공개 제보"
        await interaction.followup.send(embed=_render(
            reports, f"{title} (top {len(reports)})", discord.Color.dark_grey(),
            footer="hacktivity 공개 제보. handle은 최근 공개활동 내에서만 필터됨(REST 한계).",
        ))

    @app_commands.command(name="bugcrowd", description="Bugcrowd engagement의 채택된 제보 (CrowdStream)")
    async def bugcrowd(self, interaction: discord.Interaction, slug: str, limit: int = 20):
        await interaction.response.defer(ephemeral=False)
        try:
            reports, total = await asyncio.to_thread(bugcrowd_disclosed, slug, limit)
        except Exception as exc:
            await interaction.followup.send(f"Bugcrowd disclosed 실패: `{type(exc).__name__}: {exc}`")
            return
        await interaction.followup.send(embed=_render(
            reports,
            f"📜 Bugcrowd CrowdStream — {slug} (최근 6개월 채택 {total}건)",
            discord.Color.orange(),
            footer="최근 6개월 채택된 제보 — 우선순위·타깃·연구자. 많고 최근일수록 중복리스크↑.",
        ))
