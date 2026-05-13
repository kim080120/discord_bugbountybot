from __future__ import annotations

import discord
from discord import app_commands

from ..services.importer import BurpImporter
from ..workspace import post_import_summary, refresh_program_thread


FORMAT_CHOICES = [
    app_commands.Choice(name="auto", value="auto"),
    app_commands.Choice(name="har", value="har"),
    app_commands.Choice(name="raw", value="raw"),
    app_commands.Choice(name="txt", value="txt"),
]


class BurpCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="burp", description="Burp/HAR import 관리")
        self.bot = bot

    @app_commands.command(name="import_file", description="Burp raw/HAR 파일을 업로드해서 endpoint inventory 생성")
    @app_commands.choices(format=FORMAT_CHOICES)
    async def import_file(
        self,
        interaction: discord.Interaction,
        program_name: str,
        file: discord.Attachment,
        format: str = "auto",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        if file.size > 8 * 1024 * 1024:
            await interaction.followup.send("파일이 너무 큽니다. v0.2는 8MB 이하만 처리합니다.", ephemeral=True)
            return

        try:
            content = await file.read()
            importer = BurpImporter(self.bot.db, self.bot.settings.storage_dir)
            result = importer.import_text(
                program=program,
                filename=file.filename,
                content=content,
                format_hint=format,
            )
        except Exception as exc:
            await interaction.followup.send(f"import 실패: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        await post_import_summary(
            bot=self.bot,
            db=self.bot.db,
            program=program,
            burp_import=result.burp_import,
        )
        await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        msg = (
            f"Import 완료: `#{result.burp_import.id}`\n"
            f"- format: `{result.burp_import.format}`\n"
            f"- endpoints: `{result.burp_import.total_items}`\n"
            f"- in-scope: `{result.burp_import.in_scope_items}`\n"
            f"- out-of-scope: `{result.burp_import.out_scope_items}`\n"
            f"- unknown: `{result.burp_import.unknown_scope_items}`\n"
            f"- sanitized: `{result.burp_import.sanitized_path}`"
        )
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="imports", description="프로그램의 최근 Burp/HAR import 목록 보기")
    async def imports(self, interaction: discord.Interaction, program_name: str, limit: int = 10):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"프로그램을 찾을 수 없습니다: `{program_name}`", ephemeral=True)
            return

        imports = self.bot.db.list_burp_imports(program.id, limit=max(1, min(limit, 20)))
        if not imports:
            await interaction.response.send_message("아직 import가 없습니다.", ephemeral=True)
            return

        lines = []
        for item in imports:
            lines.append(
                f"`#{item.id}` **{item.filename}** | {item.format} | total `{item.total_items}` "
                f"| in `{item.in_scope_items}` | out `{item.out_scope_items}` | unknown `{item.unknown_scope_items}`"
            )

        embed = discord.Embed(
            title=f"Burp Imports: {program.name}",
            description="\n".join(lines)[:4000],
            color=discord.Color.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="show", description="import 상세 보기")
    async def show(self, interaction: discord.Interaction, import_id: int):
        try:
            item = self.bot.db.get_burp_import(import_id)
            program = self.bot.db.get_program_by_id(item.program_id)
        except KeyError:
            await interaction.response.send_message(f"import를 찾을 수 없습니다: `{import_id}`", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"Burp Import #{item.id}",
            description=f"Program: **{program.name}**",
            color=discord.Color.orange(),
        )
        embed.add_field(name="Filename", value=item.filename, inline=False)
        embed.add_field(name="Format", value=item.format, inline=True)
        embed.add_field(name="Total", value=str(item.total_items), inline=True)
        embed.add_field(name="In / Out / Unknown", value=f"{item.in_scope_items} / {item.out_scope_items} / {item.unknown_scope_items}", inline=True)
        embed.add_field(name="Raw path", value=f"`{item.raw_path}`"[:1024], inline=False)
        embed.add_field(name="Sanitized path", value=f"`{item.sanitized_path}`"[:1024], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=False)
