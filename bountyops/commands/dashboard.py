from __future__ import annotations

import discord
from discord import app_commands


class DashboardCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="dashboard", description="Program dashboard")
        self.bot = bot

    @app_commands.command(name="show", description="프로그램 상태 대시보드")
    async def show(self, interaction: discord.Interaction, program_name: str):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        host_rows = self.bot.db.endpoint_host_stats(program.id, scope_filter="all", limit=8)
        finding_counts = self.bot.db.finding_status_counts(program.id)
        imports = self.bot.db.list_burp_imports(program.id, limit=3)

        in_count = len(self.bot.db.list_scope_items(program.id, "in"))
        out_count = len(self.bot.db.list_scope_items(program.id, "out"))

        total_ep = self.bot.db.count_table("endpoints")
        lines = [
            f"# Dashboard — {program.name}",
            "",
            "## Scope",
            f"- In-scope rules: `{in_count}`",
            f"- Out-of-scope rules: `{out_count}`",
            "",
            "## Recent imports",
        ]
        if imports:
            for imp in imports:
                lines.append(f"- #{imp.id}: total `{imp.total_items}`, in `{imp.in_scope_items}`, out `{imp.out_scope_items}`, unknown `{imp.unknown_scope_items}`")
        else:
            lines.append("- No imports yet.")

        lines += ["", "## Top hosts"]
        if host_rows:
            for r in host_rows:
                lines.append(f"- **{r['host']}**: total `{r['total']}`, in `{r['in_count']}`, out `{r['out_count']}`, unknown `{r['unknown_count']}`, max_score `{r['max_score']}`")
        else:
            lines.append("- No endpoints yet.")

        lines += ["", "## Findings"]
        if finding_counts:
            for r in finding_counts:
                lines.append(f"- {r['status']}: `{r['c']}`")
        else:
            lines.append("- No findings yet.")

        lines += [
            "",
            "## Suggested next actions",
            "- Run `/endpoint hosts program_name:<name> scope_filter:unknown`.",
            "- Classify noisy hosts with `/endpoint host_scope`.",
            "- Create findings from promising endpoint candidates.",
            "- Run `/redact scan_program` before report submission.",
        ]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=False)
