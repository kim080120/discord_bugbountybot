from __future__ import annotations

import discord
from discord import app_commands

from ..workspace import refresh_program_thread


SEVERITY_CHOICES = [
    app_commands.Choice(name="low", value="low"),
    app_commands.Choice(name="medium", value="medium"),
    app_commands.Choice(name="high", value="high"),
    app_commands.Choice(name="critical", value="critical"),
]


class RestrictionCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="restriction", description="프로그램 제한사항 관리")
        self.bot = bot

    @app_commands.command(name="add", description="프로그램 제한사항 추가")
    @app_commands.choices(severity=SEVERITY_CHOICES)
    async def add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        severity: str,
        text: str,
        source_url: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        restriction = self.bot.db.add_restriction(
            program_id=program.id,
            severity=severity,
            text=text,
            source_url=source_url,
        )

        await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        await interaction.followup.send(
            f"제한사항 추가 완료: `{restriction.severity}` - {restriction.text[:80]}",
            ephemeral=True,
        )
