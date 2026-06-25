from __future__ import annotations

from pathlib import Path

import discord
from discord import app_commands

from ..services.redaction import scan_file, scan_text


class RedactCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="redact", description="Redaction checks")
        self.bot = bot

    @app_commands.command(name="scan_file", description="Scan an uploaded file for sensitive tokens/PII")
    async def scan_file(self, interaction: discord.Interaction, file: discord.Attachment):
        await interaction.response.defer(ephemeral=True)
        if file.size > 2 * 1024 * 1024:
            await interaction.followup.send("File too large. Limit is 2MB.", ephemeral=True)
            return
        data = await file.read()
        result = scan_text(data.decode("utf-8", errors="replace"))
        await interaction.followup.send(f"Redaction scan result: `{result or 'clean'}`", ephemeral=True)

    @app_commands.command(name="scan_program", description="Scan local sanitized/import/export files for a program keyword")
    async def scan_program(self, interaction: discord.Interaction, program_name: str):
        await interaction.response.defer(ephemeral=True)
        root = self.bot.settings.storage_dir
        if not root.exists():
            await interaction.followup.send("Storage directory does not exist.", ephemeral=True)
            return

        findings = []
        for path in root.rglob("*"):
            if not path.is_file() or path.stat().st_size > 2_000_000:
                continue
            if program_name.lower() not in str(path).lower():
                continue
            result = scan_file(path)
            if result:
                findings.append(f"`{path}` → {result}")

        if not findings:
            await interaction.followup.send("Redaction scan clean for matching files.", ephemeral=True)
        else:
            await interaction.followup.send("\n".join(findings)[:1900], ephemeral=True)
