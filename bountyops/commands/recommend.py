from __future__ import annotations

import asyncio
import discord
from discord import app_commands

from ..services.program_recommender import (
    recommend_bugcrowd,
    recommend_huntr,
    recommend_hackerone,
    recommend_intigriti,
    recommend_yeswehack,
)


_CUR_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£"}


def _money(r) -> str:
    if not r.reward_max:
        return "💰—"
    symbol = _CUR_SYMBOL.get(r.reward_cur)
    if symbol:
        return f"💰{symbol}{r.reward_max:,}"
    return f"💰{r.reward_max:,} {r.reward_cur}"


def _render(recs, title: str, color: discord.Color) -> discord.Embed:
    lines = []
    for i, r in enumerate(recs, 1):
        reward = _money(r)
        lines.append(
            f"`#{i}` **{r.name}** · score **{r.score}**\n"
            f"   {reward} · 📥in {r.in_scope}/out {r.out_scope} · "
            f"⚠️dup **{r.dup_risk}** ({r.dup_detail}) · {r.extra}\n"
            f"   <{r.url}>"
        )
    description = "\n".join(lines)[:4000] or "결과 없음."
    return discord.Embed(title=title, description=description, color=color)


class RecommendCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="recommend", description="프로그램 추천 (포상금/스코프/중복리스크 점수화)")
        self.bot = bot

    @app_commands.command(name="bugcrowd", description="Bugcrowd 프로그램 추천 (수십초 소요)")
    async def bugcrowd(self, interaction: discord.Interaction, limit: int = 12, min_reward: int = 1000):
        await interaction.response.defer(ephemeral=False)
        try:
            recs = await asyncio.to_thread(recommend_bugcrowd, limit, min_reward)
        except Exception as exc:
            await interaction.followup.send(f"Bugcrowd 추천 실패: `{type(exc).__name__}: {exc}`")
            return
        await interaction.followup.send(
            embed=_render(recs, f"🎯 Bugcrowd 추천 (top {len(recs)})", discord.Color.orange())
        )

    @app_commands.command(name="huntr", description="huntr 리포 추천 (덜 경쟁된 활성 repo)")
    async def huntr(self, interaction: discord.Interaction, limit: int = 12, sample: int = 15):
        await interaction.response.defer(ephemeral=False)
        storage_dir = getattr(self.bot.settings, "storage_dir", None)
        try:
            recs = await asyncio.to_thread(recommend_huntr, limit, sample, None, storage_dir)
        except Exception as exc:
            await interaction.followup.send(f"huntr 추천 실패: `{type(exc).__name__}: {exc}`")
            return
        emb = _render(recs, f"🎯 huntr 추천 (top {len(recs)})", discord.Color.purple())
        emb.set_footer(text="huntr 포상금은 카테고리 고정 티어($500~4000)라 repo별 금액은 표시 안 함. 정렬 기준=낮은 경쟁+활성도.")
        await interaction.followup.send(embed=emb)

    @app_commands.command(name="intigriti", description="Intigriti 프로그램 추천 (공개 미러, 1요청)")
    async def intigriti(self, interaction: discord.Interaction, limit: int = 12, min_reward: int = 0):
        await interaction.response.defer(ephemeral=False)
        try:
            recs = await asyncio.to_thread(recommend_intigriti, limit, min_reward)
        except Exception as exc:
            await interaction.followup.send(f"Intigriti 추천 실패: `{type(exc).__name__}: {exc}`")
            return
        emb = _render(recs, f"🎯 Intigriti 추천 (top {len(recs)})", discord.Color.teal())
        emb.set_footer(text="reward는 프로그램별 통화(€/$ 등). 활동데이터가 없어 중복리스크는 스코프/리워드 기반 추정. extra=스코프 타입 분포·최소포상·2FA/TAC.")
        await interaction.followup.send(embed=emb)

    @app_commands.command(name="yeswehack", description="YesWeHack 프로그램 추천 (공개 미러, 1요청)")
    async def yeswehack(self, interaction: discord.Interaction, limit: int = 12, min_reward: int = 0):
        await interaction.response.defer(ephemeral=False)
        try:
            recs = await asyncio.to_thread(recommend_yeswehack, limit, min_reward)
        except Exception as exc:
            await interaction.followup.send(f"YesWeHack 추천 실패: `{type(exc).__name__}: {exc}`")
            return
        emb = _render(recs, f"🎯 YesWeHack 추천 (top {len(recs)})", discord.Color.dark_teal())
        emb.set_footer(text="reward=EUR. 활동데이터가 없어 중복리스크는 스코프/리워드 기반 추정. extra=스코프 타입 분포·최소포상.")
        await interaction.followup.send(embed=emb)

    @app_commands.command(name="hackerone", description="HackerOne 프로그램 추천 (.env 토큰 필요)")
    async def hackerone(self, interaction: discord.Interaction, limit: int = 12):
        await interaction.response.defer(ephemeral=False)
        username = getattr(self.bot.settings, "hackerone_username", "")
        token = getattr(self.bot.settings, "hackerone_api_token", "")
        if not username or not token:
            await interaction.followup.send(
                "HackerOne 토큰이 없습니다. `.env`에 `HACKERONE_USERNAME`/`HACKERONE_API_TOKEN`을 넣고 재시작하세요."
            )
            return
        try:
            recs = await asyncio.to_thread(
                lambda: recommend_hackerone(username=username, token=token, limit=limit)
            )
        except Exception as exc:
            await interaction.followup.send(f"HackerOne 추천 실패: `{type(exc).__name__}: {exc}`")
            return
        emb = _render(recs, f"🎯 HackerOne 추천 (top {len(recs)})", discord.Color.dark_grey())
        emb.set_footer(text="HackerOne Hacker API는 실제 $금액/리포트수를 제공하지 않아 reward·dup은 추정치(proxy)입니다.")
        await interaction.followup.send(embed=emb)
