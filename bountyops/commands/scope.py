from __future__ import annotations

import discord
from discord import app_commands

from ..workspace import refresh_program_thread


SCOPE_TYPE_CHOICES = [
    app_commands.Choice(name="in - 인스코프", value="in"),
    app_commands.Choice(name="out - 아웃스코프", value="out"),
]


class ScopeCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="scope", description="인스코프/아웃스코프 관리")
        self.bot = bot

    @app_commands.command(name="add", description="프로그램에 스코프 항목 추가")
    @app_commands.choices(type=SCOPE_TYPE_CHOICES)
    async def add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        type: str,
        value: str,
        note: str = "",
        source_url: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        item = self.bot.db.add_scope_item(
            program_id=program.id,
            type=type,
            value=value,
            note=note,
            source_url=source_url,
        )

        await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        label = "In-scope" if item.type == "in" else "Out-of-scope"
        await interaction.followup.send(
            f"{label} 추가 완료: `{item.value}`",
            ephemeral=True,
        )
