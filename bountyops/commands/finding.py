from __future__ import annotations

import discord
from discord import app_commands

from ..services.report_builder import build_report_draft
from ..workspace import find_program_channel, chunk_text


STATUS_CHOICES = [
    app_commands.Choice(name="candidate", value="candidate"),
    app_commands.Choice(name="needs-validation", value="needs-validation"),
    app_commands.Choice(name="false-positive", value="false-positive"),
    app_commands.Choice(name="not-reportable", value="not-reportable"),
    app_commands.Choice(name="report-ready", value="report-ready"),
    app_commands.Choice(name="submitted", value="submitted"),
    app_commands.Choice(name="duplicate", value="duplicate"),
]

SEVERITY_CHOICES = [
    app_commands.Choice(name="unknown", value="unknown"),
    app_commands.Choice(name="low", value="low"),
    app_commands.Choice(name="medium", value="medium"),
    app_commands.Choice(name="high", value="high"),
    app_commands.Choice(name="critical", value="critical"),
]


class FindingCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="finding", description="Finding candidate management")
        self.bot = bot

    @app_commands.command(name="add", description="Create a finding candidate")
    @app_commands.choices(severity=SEVERITY_CHOICES)
    async def add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        title: str,
        vuln_type: str = "TODO",
        severity: str = "unknown",
        endpoint_id: int | None = None,
        summary: str = "",
        impact: str = "",
    ):
        await interaction.response.defer(ephemeral=True)
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        fid = self.bot.db.add_finding(
            program_id=program.id,
            title=title,
            vuln_type=vuln_type,
            severity=severity,
            endpoint_id=endpoint_id,
            summary=summary,
            impact=impact,
        )

        ch = find_program_channel(self.bot, program, "ai-analysis") or find_program_channel(self.bot, program, "general")
        if ch:
            await ch.send(
                f"# Finding Candidate #{fid}: {title}\n"
                f"- Type: `{vuln_type}`\n"
                f"- Severity: `{severity}`\n"
                f"- Status: `candidate`\n"
                f"- Endpoint: `{endpoint_id or '-'}`\n"
                f"- Summary: {summary or '_TODO_'}\n"
                f"- Impact: {impact or '_TODO_'}"
            )

        await interaction.followup.send(f"Finding candidate created: `#{fid}`", ephemeral=True)

    @app_commands.command(name="list", description="List finding candidates")
    @app_commands.choices(status=STATUS_CHOICES)
    async def list(self, interaction: discord.Interaction, program_name: str, status: str = "candidate", limit: int = 20):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return
        rows = self.bot.db.list_findings(program.id, status=status if status else "all", limit=limit)
        if not rows:
            await interaction.response.send_message("No findings matched.", ephemeral=True)
            return
        lines = [
            f"`#{r['id']}` **{r['title']}** | `{r['vuln_type']}` | `{r['severity']}` | status `{r['status']}` | endpoint `{r['endpoint_id'] or '-'}`"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=discord.Embed(title=f"Findings — {program.name}", description="\n".join(lines)[:4000], color=discord.Color.red()),
            ephemeral=False,
        )

    @app_commands.command(name="update", description="Update finding status/severity/notes")
    @app_commands.choices(status=STATUS_CHOICES, severity=SEVERITY_CHOICES)
    async def update(self, interaction: discord.Interaction, finding_id: int, status: str | None = None, severity: str | None = None, summary: str | None = None, impact: str | None = None):
        row = self.bot.db.get_finding(finding_id)
        if not row:
            await interaction.response.send_message(f"Finding not found: `{finding_id}`", ephemeral=True)
            return
        self.bot.db.update_finding(finding_id, status=status, severity=severity, summary=summary, impact=impact)
        await interaction.response.send_message(f"Finding `#{finding_id}` updated.", ephemeral=True)

    @app_commands.command(name="link_evidence", description="Link evidence to a finding")
    async def link_evidence(self, interaction: discord.Interaction, finding_id: int, evidence_id: int):
        row = self.bot.db.get_finding(finding_id)
        ev = self.bot.db.get_evidence(evidence_id)
        if not row:
            await interaction.response.send_message(f"Finding not found: `{finding_id}`", ephemeral=True)
            return
        if not ev:
            await interaction.response.send_message(f"Evidence not found: `{evidence_id}`", ephemeral=True)
            return
        self.bot.db.link_finding_evidence(finding_id, evidence_id)
        await interaction.response.send_message(f"Linked evidence `#{evidence_id}` to finding `#{finding_id}`.", ephemeral=True)


    @app_commands.command(name="board", description="Show findings grouped by status")
    async def board(self, interaction: discord.Interaction, program_name: str):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return
        rows = self.bot.db.list_findings(program.id, status="all", limit=200)
        groups = {}
        for r in rows:
            groups.setdefault(r["status"], []).append(r)

        order = ["candidate", "needs-validation", "false-positive", "not-reportable", "report-ready", "submitted", "duplicate"]
        lines = [f"# Finding Board — {program.name}"]
        for status in order:
            items = groups.get(status, [])
            lines.append("")
            lines.append(f"## {status} ({len(items)})")
            if not items:
                lines.append("- _empty_")
            else:
                for f in items[:20]:
                    lines.append(f"- `#{f['id']}` **{f['title']}** [{f['severity']}] endpoint `{f['endpoint_id'] or '-'}`")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=False)


    @app_commands.command(name="promote_report", description="Create a report draft from a finding")
    async def promote_report(self, interaction: discord.Interaction, finding_id: int):
        await interaction.response.defer(ephemeral=True)
        row = self.bot.db.get_finding(finding_id)
        if not row:
            await interaction.followup.send(f"Finding not found: `{finding_id}`", ephemeral=True)
            return
        program = self.bot.db.get_program_by_id(row["program_id"])
        in_scope = self.bot.db.list_scope_items(program.id, "in")
        restrictions = self.bot.db.list_restrictions(program.id, limit=50)
        evidence = [dict(r) for r in self.bot.db.list_finding_evidence(finding_id)]

        body = build_report_draft(
            program_name=program.name,
            platform=program.platform,
            policy_url=program.policy_url,
            in_scope=in_scope,
            restrictions=restrictions,
            evidence=evidence,
            finding_title=row["title"],
            vuln_type=row["vuln_type"],
            affected_asset=f"Endpoint #{row['endpoint_id']}" if row["endpoint_id"] else "TODO",
            summary=row["summary"],
            impact=row["impact"],
        )
        draft_id = self.bot.db.add_report_draft(program_id=program.id, title=row["title"], body=body)
        self.bot.db.update_finding(finding_id, status="report-ready")

        ch = find_program_channel(self.bot, program, "report-drafts")
        if ch:
            await ch.send(f"# Report Draft #{draft_id} from Finding #{finding_id}: {row['title']}")
            for chunk in chunk_text(body, limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(f"Promoted finding `#{finding_id}` to report draft `#{draft_id}`.", ephemeral=True)
