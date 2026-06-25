from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import discord
from discord import app_commands

from ..workspace import find_program_channel
from ..services.bundle_builder import build_finding_bundle


EVIDENCE_TYPES = [
    app_commands.Choice(name="note", value="note"),
    app_commands.Choice(name="screenshot", value="screenshot"),
    app_commands.Choice(name="burp", value="burp"),
    app_commands.Choice(name="ab-test", value="ab-test"),
    app_commands.Choice(name="log", value="log"),
    app_commands.Choice(name="other", value="other"),
]


class EvidenceCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="evidence", description="Evidence management")
        self.bot = bot

    @app_commands.command(name="add", description="Add evidence to a program workspace")
    @app_commands.choices(evidence_type=EVIDENCE_TYPES)
    async def add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        title: str,
        evidence_type: str = "note",
        note: str = "",
        file: discord.Attachment | None = None,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        file_name = ""
        file_path = ""

        if file:
            if file.size > 8 * 1024 * 1024:
                await interaction.followup.send("File is too large. v0.4 supports files up to 8MB.", ephemeral=True)
                return

            ev_dir = self.bot.settings.storage_dir / "evidence"
            ev_dir.mkdir(parents=True, exist_ok=True)
            safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in file.filename)[:120]
            file_name = safe_name
            file_path = str(ev_dir / f"{program.id}_{uuid4().hex[:10]}_{safe_name}")
            content = await file.read()
            Path(file_path).write_bytes(content)

        evidence_id = self.bot.db.add_evidence(
            program_id=program.id,
            title=title,
            evidence_type=evidence_type,
            note=note,
            file_name=file_name,
            file_path=file_path,
        )

        ch = find_program_channel(self.bot, program, "evidence")
        if ch:
            embed = discord.Embed(
                title=f"Evidence #{evidence_id}: {title}",
                description=note or "_No note provided._",
                color=discord.Color.green(),
            )
            embed.add_field(name="Type", value=evidence_type, inline=True)
            if file_name:
                embed.add_field(name="File", value=file_name, inline=True)
            if file_path:
                embed.add_field(name="Stored path", value=f"`{file_path}`"[:1000], inline=False)
            await ch.send(embed=embed)

        await interaction.followup.send(f"Evidence added: `#{evidence_id}`", ephemeral=True)


    @app_commands.command(name="bundle", description="Create a zipped evidence bundle for a finding")
    async def bundle(self, interaction: discord.Interaction, finding_id: int):
        await interaction.response.defer(ephemeral=True)
        try:
            zip_path = build_finding_bundle(self.bot.db, self.bot.settings.storage_dir, finding_id)
        except Exception as exc:
            await interaction.followup.send(f"Bundle failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return
        await interaction.followup.send(f"Evidence bundle created: `{zip_path}`", ephemeral=True)


    @app_commands.command(name="list", description="List evidence for a program")
    async def list(self, interaction: discord.Interaction, program_name: str, limit: int = 10):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rows = self.bot.db.list_evidence(program.id, limit=limit)
        if not rows:
            await interaction.response.send_message("No evidence yet.", ephemeral=True)
            return

        lines = [
            f"`#{r['id']}` **{r['title']}** [{r['evidence_type']}] — {r['note'][:120]}"
            for r in rows
        ]
        embed = discord.Embed(
            title=f"Evidence — {program.name}",
            description="\n".join(lines)[:4000],
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)
