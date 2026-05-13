from __future__ import annotations

import discord
from discord import app_commands


SCOPE_FILTER_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="in", value="in"),
    app_commands.Choice(name="out", value="out"),
    app_commands.Choice(name="unknown", value="unknown"),
]


class EndpointCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="endpoint", description="Endpoint inventory 조회")
        self.bot = bot

    @app_commands.command(name="list", description="파싱된 endpoint 목록 보기")
    @app_commands.choices(scope_filter=SCOPE_FILTER_CHOICES)
    async def list(
        self,
        interaction: discord.Interaction,
        program_name: str,
        scope_filter: str = "all",
        limit: int = 20,
    ):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        endpoints = self.bot.db.list_endpoints(
            program_id=program.id,
            scope_filter=scope_filter,
            limit=max(1, min(limit, 30)),
        )

        if not endpoints:
            await interaction.response.send_message("표시할 endpoint가 없습니다.", ephemeral=True)
            return

        lines = []
        for ep in endpoints:
            flags = []
            if ep.auth_present:
                flags.append("AUTH")
            if ep.state_changing:
                flags.append("STATE")
            if ep.query_keys:
                flags.append(f"Q:{ep.query_keys}")
            flag_text = ", ".join(flags) if flags else "-"

            status = ep.status_code if ep.status_code is not None else "-"
            lines.append(
                f"`#{ep.id}` `{ep.scope_status}` score `{ep.interesting_score}` "
                f"`{ep.method}` **{ep.host}**`{ep.path}` status `{status}` flags `{flag_text}`"
            )

        embed = discord.Embed(
            title=f"Endpoints: {program.name} / {scope_filter}",
            description="\n".join(lines)[:4000],
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="show", description="endpoint 상세 보기")
    async def show(self, interaction: discord.Interaction, endpoint_id: int):
        try:
            ep = self.bot.db.get_endpoint(endpoint_id)
            program = self.bot.db.get_program_by_id(ep.program_id)
        except KeyError:
            await interaction.response.send_message(f"endpoint를 찾을 수 없습니다: `{endpoint_id}`", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Endpoint #{ep.id}",
            description=f"Program: **{program.name}**",
            color=discord.Color.teal(),
        )
        embed.add_field(name="Scope", value=ep.scope_status, inline=True)
        embed.add_field(name="Score", value=str(ep.interesting_score), inline=True)
        embed.add_field(name="Method", value=ep.method, inline=True)
        embed.add_field(name="Host", value=ep.host or "-", inline=False)
        embed.add_field(name="Path", value=ep.path or "/", inline=False)
        embed.add_field(name="Query keys", value=ep.query_keys or "-", inline=False)
        embed.add_field(name="Status", value=str(ep.status_code) if ep.status_code is not None else "-", inline=True)
        embed.add_field(name="Content-Type", value=ep.content_type or "-", inline=True)
        embed.add_field(name="Auth present", value=str(ep.auth_present), inline=True)
        embed.add_field(name="State changing", value=str(ep.state_changing), inline=True)
        embed.add_field(name="Import ID", value=str(ep.import_id), inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=False)
