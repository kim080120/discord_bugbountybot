from __future__ import annotations

import json
import discord
from discord import app_commands

from ..services.site_crawler import crawl_site, save_crawl_result
from .hackerone import make_preview_embed


class FinderGapCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="findergap", description="FinderGap/국내 플랫폼 프로그램 후보 수집")
        self.bot = bot

    @app_commands.command(name="site", description="FinderGap/정책 URL을 크롤링해서 후보만 저장")
    async def site(self, interaction: discord.Interaction, url: str):
        await interaction.response.defer(ephemeral=False)

        try:
            result = crawl_site("FinderGap", url)
            raw_path, parsed_path = save_crawl_result(result, self.bot.settings.storage_dir)
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
            await interaction.followup.send(f"크롤링 실패: `{type(exc).__name__}: {exc}`")
            return

        await interaction.followup.send(embed=make_preview_embed(crawl_id, row))
