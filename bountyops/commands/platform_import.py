from __future__ import annotations

import asyncio
import json
import discord
from discord import app_commands

from ..services.site_crawler import save_crawl_result
from ..services.platform_importers import (
    fetch_naver_targets,
    fetch_kakao_targets,
    fetch_huntr_bounties,
    fetch_bugcrowd_engagement,
    list_bugcrowd_engagements,
    fetch_intigriti_program,
    list_intigriti_programs,
    fetch_yeswehack_program,
    list_yeswehack_programs,
    refetch_for_program,
    scope_values,
    diff_scope,
)
from .hackerone import make_preview_embed


class ImportCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="import", description="플랫폼 스코프 자동 수집 (후보 생성 → /crawl apply)")
        self.bot = bot

    def _store_candidate(self, result) -> int:
        raw_path, parsed_path = save_crawl_result(result, self.bot.settings.storage_dir)
        return self.bot.db.add_site_crawl(
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

    def _latest_pending(self, platform: str, name: str):
        for row in self.bot.db.list_site_crawls(limit=25):
            if (
                row["status"] == "pending"
                and row["platform"] == platform
                and row["suggested_name"] == name
            ):
                return row
        return None

    async def _run_fetch(self, interaction: discord.Interaction, fetch_callable, label: str) -> None:
        await interaction.response.defer(ephemeral=False)
        try:
            result = fetch_callable()
        except Exception as exc:
            await interaction.followup.send(f"{label} 수집 실패: `{type(exc).__name__}: {exc}`")
            return

        new_values = scope_values(result.in_scope) | scope_values(result.out_scope)

        # 1) Identical pending candidate already waiting? Don't create a duplicate.
        prev = self._latest_pending(result.platform, result.suggested_name)
        if prev is not None:
            old = scope_values(json.loads(prev["in_scope_json"])) | scope_values(json.loads(prev["out_scope_json"]))
            if old == new_values:
                await interaction.followup.send(
                    f"⏸️ 동일 스코프 후보가 이미 존재합니다 — `#{prev['id']}` ({len(new_values)}개). "
                    f"새 후보를 만들지 않았어요.\n적용하려면 `/crawl apply crawl_id:{prev['id']}`"
                )
                return

        # 2) Compare against an already-applied program of the same name.
        diff_note = None
        existing = self.bot.db.get_program_by_name(result.suggested_name)
        if existing:
            old_vals = {s.value for s in self.bot.db.list_scope_items(existing.id)}
            added, removed = diff_scope(old_vals, new_values)
            if not added and not removed:
                await interaction.followup.send(
                    f"✅ 기존 `{existing.name}` 프로그램과 스코프가 동일합니다 (변경 없음). 후보를 만들지 않았어요."
                )
                return
            diff_note = (
                f"ℹ️ 기존 `{existing.name}` 대비 **+{len(added)} / -{len(removed)}**. "
                f"기존 프로그램에 반영하려면 아래 후보로 `/crawl update crawl_id:<id>`."
            )

        crawl_id = self._store_candidate(result)
        row = self.bot.db.get_site_crawl(crawl_id)
        await interaction.followup.send(content=diff_note, embed=make_preview_embed(crawl_id, row))

    @app_commands.command(name="naver", description="NAVER 버그바운티 스코프 수집")
    async def naver(self, interaction: discord.Interaction):
        await self._run_fetch(interaction, fetch_naver_targets, "Naver")

    @app_commands.command(name="kakao", description="Kakao 버그바운티 스코프 수집 (best-effort)")
    async def kakao(self, interaction: discord.Interaction):
        await self._run_fetch(interaction, fetch_kakao_targets, "Kakao")

    @app_commands.command(name="huntr", description="huntr.com OSS/AI 바운티 타깃 수집")
    async def huntr(self, interaction: discord.Interaction, limit: int = 250):
        await self._run_fetch(interaction, lambda: fetch_huntr_bounties(limit=limit), "huntr")

    @app_commands.command(name="bugcrowd", description="Bugcrowd engagement 스코프 수집 (slug 지정)")
    async def bugcrowd(self, interaction: discord.Interaction, slug: str):
        await self._run_fetch(interaction, lambda: fetch_bugcrowd_engagement(slug), "Bugcrowd")

    @app_commands.command(name="bugcrowd_list", description="Bugcrowd 공개 bug bounty engagement 목록 (slug 찾기)")
    async def bugcrowd_list(self, interaction: discord.Interaction, page: int = 1):
        await interaction.response.defer(ephemeral=True)
        try:
            engagements, meta = list_bugcrowd_engagements(page)
        except Exception as exc:
            await interaction.followup.send(
                f"Bugcrowd 목록 실패: `{type(exc).__name__}: {exc}`", ephemeral=True
            )
            return
        if not engagements:
            await interaction.followup.send("결과 없음 (페이지 범위 초과일 수 있음).", ephemeral=True)
            return

        total = meta.get("totalCount")
        lines = [f"`{e['slug']}` — {e['name']} ({e['reward'] or 'n/a'})" for e in engagements]
        body = "\n".join(lines)[:3700]
        embed = discord.Embed(
            title=f"Bugcrowd bug bounty engagements (page {page} / total {total})",
            description=f"{body}\n\n수집: `/import bugcrowd slug:<slug>`",
            color=discord.Color.green(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="intigriti", description="Intigriti 프로그램 스코프 수집 (handle 지정)")
    async def intigriti(self, interaction: discord.Interaction, handle: str):
        await self._run_fetch(interaction, lambda: fetch_intigriti_program(handle), "Intigriti")

    @app_commands.command(name="intigriti_list", description="Intigriti 공개 프로그램 목록 (handle 찾기)")
    async def intigriti_list(self, interaction: discord.Interaction, min_reward: int = 0, limit: int = 40):
        await interaction.response.defer(ephemeral=True)
        try:
            programs = await asyncio.to_thread(list_intigriti_programs)
        except Exception as exc:
            await interaction.followup.send(
                f"Intigriti 목록 실패: `{type(exc).__name__}: {exc}`", ephemeral=True
            )
            return
        programs = [p for p in programs if p["reward"] >= min_reward]
        programs.sort(key=lambda p: p["reward"], reverse=True)
        programs = programs[: max(1, limit)]
        if not programs:
            await interaction.followup.send("결과 없음.", ephemeral=True)
            return
        lines = [
            f"`{p['handle']}` — {p['name']} ({p['reward']} {p['currency']}, in {p['in']})"
            for p in programs
        ]
        embed = discord.Embed(
            title=f"Intigriti 공개 프로그램 (top {len(programs)})",
            description="\n".join(lines)[:3800] + "\n\n수집: `/import intigriti handle:<handle>`",
            color=discord.Color.teal(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="yeswehack", description="YesWeHack 프로그램 스코프 수집 (handle 지정)")
    async def yeswehack(self, interaction: discord.Interaction, handle: str):
        await self._run_fetch(interaction, lambda: fetch_yeswehack_program(handle), "YesWeHack")

    @app_commands.command(name="yeswehack_list", description="YesWeHack 공개 프로그램 목록 (handle 찾기)")
    async def yeswehack_list(self, interaction: discord.Interaction, min_reward: int = 0, limit: int = 40):
        await interaction.response.defer(ephemeral=True)
        try:
            programs = await asyncio.to_thread(list_yeswehack_programs)
        except Exception as exc:
            await interaction.followup.send(
                f"YesWeHack 목록 실패: `{type(exc).__name__}: {exc}`", ephemeral=True
            )
            return
        programs = [p for p in programs if p["reward"] >= min_reward]
        programs.sort(key=lambda p: p["reward"], reverse=True)
        programs = programs[: max(1, limit)]
        if not programs:
            await interaction.followup.send("결과 없음.", ephemeral=True)
            return
        lines = [
            f"`{p['handle']}` — {p['name']} ({p['reward']} EUR, in {p['in']})"
            for p in programs
        ]
        embed = discord.Embed(
            title=f"YesWeHack 공개 프로그램 (top {len(programs)})",
            description="\n".join(lines)[:3800] + "\n\n수집: `/import yeswehack handle:<handle>`",
            color=discord.Color.dark_teal(),
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="refresh", description="가져온 모든 플랫폼 스코프를 재탐색하고 변경분을 보고")
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        lines = await run_scope_refresh(self.bot)
        await interaction.followup.send("\n".join(lines)[:1900] or "대상 없음.")


async def run_scope_refresh(bot: discord.Client) -> list[str]:
    """Re-fetch every auto-importable program, create update candidates for changes.

    Returns human-readable summary lines. Shared by `/import refresh` and the
    weekly background loop.
    """
    lines: list[str] = []
    for program in bot.db.list_programs():
        try:
            result = await asyncio.to_thread(refetch_for_program, program)
        except Exception as exc:
            lines.append(f"⚠️ {program.name}: 재탐색 실패 ({type(exc).__name__})")
            continue
        if result is None:
            continue  # platform has no auto-importer (HackerOne / FinderGap / manual)

        new_vals = scope_values(result.in_scope) | scope_values(result.out_scope)
        old_vals = {s.value for s in bot.db.list_scope_items(program.id)}
        added, removed = diff_scope(old_vals, new_vals)
        if not added and not removed:
            lines.append(f"✅ {program.name}: 변경 없음 ({len(old_vals)})")
            continue

        # Don't pile up duplicate update candidates across restarts/runs.
        duplicate = None
        for crow in bot.db.list_site_crawls(limit=25):
            if (
                crow["status"] == "pending"
                and crow["platform"] == result.platform
                and crow["suggested_name"] == program.name
            ):
                cand_vals = scope_values(json.loads(crow["in_scope_json"])) | scope_values(json.loads(crow["out_scope_json"]))
                if cand_vals == new_vals:
                    duplicate = crow
                break
        if duplicate is not None:
            lines.append(
                f"🔄 {program.name}: +{len(added)} / -{len(removed)} (후보 `#{duplicate['id']}` 이미 대기)"
            )
            continue

        raw_path, parsed_path = save_crawl_result(result, bot.settings.storage_dir)
        cid = bot.db.add_site_crawl(
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
        lines.append(
            f"🔄 **{program.name}**: +{len(added)} / -{len(removed)} → 후보 `#{cid}` "
            f"(`/crawl update crawl_id:{cid}`)"
        )
    if not lines:
        lines = ["자동 수집 대상 프로그램이 없습니다 (naver/kakao/huntr/bugcrowd 적용 후 사용)."]
    return lines
