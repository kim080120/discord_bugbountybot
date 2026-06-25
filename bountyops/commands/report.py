from __future__ import annotations

import discord
from discord import app_commands

from ..services.report_builder import build_report_draft
from ..services.report_check import check_report_text
from ..services.bundle_builder import build_program_report_bundle
from ..workspace import find_program_channel, chunk_text


class ReportCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="report", description="Report draft generation and checks")
        self.bot = bot

    @app_commands.command(name="draft", description="Create a bug bounty report draft")
    async def draft(
        self,
        interaction: discord.Interaction,
        program_name: str,
        finding_title: str,
        vuln_type: str = "TODO",
        affected_asset: str = "TODO",
        summary: str = "",
        impact: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        in_scope = self.bot.db.list_scope_items(program.id, "in")
        restrictions = self.bot.db.list_restrictions(program.id, limit=50)
        evidence = [dict(r) for r in self.bot.db.list_evidence(program.id, limit=50)]

        body = build_report_draft(
            program_name=program.name,
            platform=program.platform,
            policy_url=program.policy_url,
            in_scope=in_scope,
            restrictions=restrictions,
            evidence=evidence,
            finding_title=finding_title,
            vuln_type=vuln_type,
            affected_asset=affected_asset,
            summary=summary,
            impact=impact,
        )

        draft_id = self.bot.db.add_report_draft(
            program_id=program.id,
            title=finding_title,
            body=body,
        )

        ch = find_program_channel(self.bot, program, "report-drafts")
        if ch:
            await ch.send(f"# Report Draft #{draft_id}: {finding_title}")
            for chunk in chunk_text(body, limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(
            f"Report draft created: `#{draft_id}`. Check #report-drafts.",
            ephemeral=True,
        )

    @app_commands.command(name="list", description="List report drafts for a program")
    async def list(self, interaction: discord.Interaction, program_name: str, limit: int = 10):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rows = self.bot.db.list_report_drafts(program.id, limit=limit)
        if not rows:
            await interaction.response.send_message("No report drafts yet.", ephemeral=True)
            return

        lines = [
            f"`#{r['id']}` **{r['title']}** — status `{r['status']}`"
            for r in rows
        ]
        embed = discord.Embed(
            title=f"Report Drafts — {program.name}",
            description="\n".join(lines)[:4000],
            color=discord.Color.purple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)


    @app_commands.command(name="bundle", description="Create a zipped report bundle for a program")
    async def bundle(self, interaction: discord.Interaction, program_name: str):
        await interaction.response.defer(ephemeral=True)
        try:
            zip_path = build_program_report_bundle(self.bot.db, self.bot.settings.storage_dir, program_name)
        except Exception as exc:
            await interaction.followup.send(f"Bundle failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return
        await interaction.followup.send(f"Report bundle created: `{zip_path}`", ephemeral=True)


    @app_commands.command(name="check", description="Check a stored report draft for quality/redaction issues")
    async def check(self, interaction: discord.Interaction, draft_id: int):
        row = self.bot.db.get_report_draft(draft_id)
        if not row:
            await interaction.response.send_message(f"Draft not found: `{draft_id}`", ephemeral=True)
            return

        issues = check_report_text(row["body"])
        if not issues:
            await interaction.response.send_message(f"Draft `#{draft_id}` check passed.", ephemeral=True)
            return

        await interaction.response.send_message(
            "Report check issues:\n" + "\n".join(f"- {x}" for x in issues)[:1800],
            ephemeral=True,
        )
