from __future__ import annotations

import discord
from discord import app_commands

from ..workspace import refresh_program_thread


class NoticeCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="notice", description="프로그램 공지사항 관리")
        self.bot = bot

    @app_commands.command(name="add", description="프로그램 공지사항 추가")
    async def add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        title: str,
        summary: str = "",
        source_url: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        notice = self.bot.db.add_notice(
            program_id=program.id,
            title=title,
            summary=summary,
            source_url=source_url,
        )

        await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        await interaction.followup.send(
            f"공지사항 추가 완료: `{notice.title}`",
            ephemeral=True,
        )
