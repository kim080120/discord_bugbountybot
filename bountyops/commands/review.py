from __future__ import annotations

import discord
from discord import app_commands

from ..workspace import find_program_channel, chunk_text


class ReviewCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="review", description="Workspace review summaries")
        self.bot = bot

    @app_commands.command(name="daily", description="Generate a daily review summary")
    async def daily(self, interaction: discord.Interaction, program_name: str):
        await interaction.response.defer(ephemeral=True)
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        host_rows = self.bot.db.endpoint_host_stats(program.id, scope_filter="all", limit=10)
        imports = self.bot.db.list_burp_imports(program.id, limit=5)
        findings = self.bot.db.list_findings(program.id, status="all", limit=10)
        evidence = self.bot.db.list_evidence(program.id, limit=10)

        lines = [
            f"# Daily Review — {program.name}",
            "",
            "## 1. Program State",
            f"- Platform: {program.platform}",
            f"- Policy URL: {program.policy_url or 'Unknown'}",
            f"- In-scope count: {self.bot.db.count_in_scope(program.id)}",
            "",
            "## 2. Recent Imports",
            *(f"- Import #{x.id}: total {x.total_items}, in {x.in_scope_items}, out {x.out_scope_items}, unknown {x.unknown_scope_items}" for x in imports),
            "",
            "## 3. Top Hosts",
            *(f"- {r['host']}: total {r['total']}, in {r['in_count']}, out {r['out_count']}, unknown {r['unknown_count']}, max_score {r['max_score']}" for r in host_rows),
            "",
            "## 4. Findings",
            *(f"- #{f['id']} {f['title']} [{f['status']}/{f['severity']}]" for f in findings),
            "",
            "## 5. Evidence",
            *(f"- #{e['id']} {e['title']} [{e['evidence_type']}]" for e in evidence),
            "",
            "## 6. Next Actions",
            "- Reclassify unknown hosts.",
            "- Shortlist high-score endpoints.",
            "- Add evidence before report drafting.",
            "- Run redaction checks before submission.",
        ]
        text = "\n".join(lines)
        ch = find_program_channel(self.bot, program, "general")
        if ch:
            for chunk in chunk_text(text, limit=1900):
                await ch.send(chunk)
        await interaction.followup.send("Daily review posted to #general.", ephemeral=True)
