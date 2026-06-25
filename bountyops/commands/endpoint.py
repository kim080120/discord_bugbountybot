from __future__ import annotations

import csv
import discord
from discord import app_commands

from ..services.endpoint_triage import reclassify_program_endpoints
from ..workspace import find_program_channel, chunk_text


SCOPE_FILTER_CHOICES = [
    app_commands.Choice(name="all", value="all"),
    app_commands.Choice(name="in", value="in"),
    app_commands.Choice(name="out", value="out"),
    app_commands.Choice(name="unknown", value="unknown"),
]

SCOPE_TYPE_CHOICES = [
    app_commands.Choice(name="in", value="in"),
    app_commands.Choice(name="out", value="out"),
]


class EndpointCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="endpoint", description="Endpoint inventory and triage")
        self.bot = bot

    @app_commands.command(name="list", description="List parsed endpoints")
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
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        endpoints = self.bot.db.list_endpoints(
            program_id=program.id,
            scope_filter=scope_filter,
            limit=max(1, min(limit, 30)),
        )

        if not endpoints:
            await interaction.response.send_message("No endpoints to display.", ephemeral=True)
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

    @app_commands.command(name="hosts", description="Show endpoint counts grouped by host")
    @app_commands.choices(scope_filter=SCOPE_FILTER_CHOICES)
    async def hosts(
        self,
        interaction: discord.Interaction,
        program_name: str,
        scope_filter: str = "all",
        limit: int = 30,
    ):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rows = self.bot.db.endpoint_host_stats(
            program_id=program.id,
            scope_filter=scope_filter,
            limit=max(1, min(limit, 50)),
        )

        if not rows:
            await interaction.response.send_message("No host statistics to display.", ephemeral=True)
            return

        lines = []
        for r in rows:
            lines.append(
                f"**{r['host'] or '-'}** | total `{r['total']}` | in `{r['in_count']}` | out `{r['out_count']}` "
                f"| unknown `{r['unknown_count']}` | max_score `{r['max_score']}` | auth `{r['auth_count']}` | state `{r['state_count']}`"
            )

        embed = discord.Embed(
            title=f"Endpoint Hosts: {program.name} / {scope_filter}",
            description="\n".join(lines)[:4000],
            color=discord.Color.teal(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="reclassify", description="Recompute endpoint scope after scope changes")
    async def reclassify(self, interaction: discord.Interaction, program_name: str):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        result = reclassify_program_endpoints(self.bot.db, program)
        await interaction.followup.send(
            "\n".join(
                [
                    f"Reclassified endpoints for `{program.name}`.",
                    f"- total: `{result.total}`",
                    f"- changed: `{result.changed}`",
                    f"- in: `{result.in_count}`",
                    f"- out: `{result.out_count}`",
                    f"- unknown: `{result.unknown_count}`",
                ]
            ),
            ephemeral=True,
        )

    @app_commands.command(name="host_scope", description="Add a host to in/out scope and reclassify endpoints")
    @app_commands.choices(type=SCOPE_TYPE_CHOICES)
    async def host_scope(
        self,
        interaction: discord.Interaction,
        program_name: str,
        host: str,
        type: str,
        note: str = "manual host classification",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        item = self.bot.db.add_scope_item(
            program_id=program.id,
            type=type,
            value=host.strip(),
            note=note,
            source_url="manual:endpoint.host_scope",
        )

        result = reclassify_program_endpoints(self.bot.db, program)

        scope_ch = find_program_channel(self.bot, program, "scope")
        if scope_ch:
            label = "✅ In-scope" if type == "in" else "🚫 Out-of-scope"
            await scope_ch.send(
                f"## {label} host classification\n"
                f"- `{item.value}` — {item.note}\n"
                f"- Reclassified endpoints: changed `{result.changed}`, in `{result.in_count}`, out `{result.out_count}`, unknown `{result.unknown_count}`"
            )

        await interaction.followup.send(
            f"Added `{host}` as `{type}` scope and reclassified `{result.total}` endpoints. Changed `{result.changed}`.",
            ephemeral=True,
        )

    @app_commands.command(name="shortlist", description="Post top endpoint candidates to #ai-analysis")
    @app_commands.choices(scope_filter=SCOPE_FILTER_CHOICES)
    async def shortlist(
        self,
        interaction: discord.Interaction,
        program_name: str,
        scope_filter: str = "unknown",
        min_score: int = 20,
        limit: int = 20,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        endpoints = self.bot.db.list_endpoints(
            program_id=program.id,
            scope_filter=scope_filter,
            limit=max(1, min(limit, 50)),
        )
        endpoints = [ep for ep in endpoints if ep.interesting_score >= min_score]

        if not endpoints:
            await interaction.followup.send("No endpoints matched the shortlist criteria.", ephemeral=True)
            return

        lines = [
            f"# Endpoint Shortlist — {program.name} / {scope_filter}",
            "",
            f"Minimum score: `{min_score}`",
            "",
        ]

        for ep in endpoints:
            flags = []
            if ep.auth_present:
                flags.append("AUTH")
            if ep.state_changing:
                flags.append("STATE")
            if ep.query_keys:
                flags.append(f"Q:{ep.query_keys}")
            flag_text = ", ".join(flags) if flags else "-"
            lines.append(
                f"- `#{ep.id}` score `{ep.interesting_score}` `{ep.scope_status}` "
                f"`{ep.method}` `{ep.host}{ep.path}` status `{ep.status_code or '-'}` flags `{flag_text}`"
            )

        target = find_program_channel(self.bot, program, "ai-analysis") or find_program_channel(self.bot, program, "general")
        if target:
            for chunk in chunk_text("\n".join(lines), limit=1900):
                await target.send(chunk)

        await interaction.followup.send(f"Posted `{len(endpoints)}` endpoints to #ai-analysis.", ephemeral=True)

    @app_commands.command(name="export_csv", description="Export endpoints to a local CSV file")
    @app_commands.choices(scope_filter=SCOPE_FILTER_CHOICES)
    async def export_csv(
        self,
        interaction: discord.Interaction,
        program_name: str,
        scope_filter: str = "all",
        limit: int = 1000,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        endpoints = self.bot.db.list_endpoints(
            program_id=program.id,
            scope_filter=scope_filter,
            limit=max(1, min(limit, 5000)),
        )
        if not endpoints:
            await interaction.followup.send("No endpoints to export.", ephemeral=True)
            return

        export_dir = self.bot.settings.storage_dir / "exports"
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"{program.name}_{scope_filter}_endpoints.csv"

        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "id", "scope_status", "interesting_score", "method", "scheme", "host", "port",
                "path", "query_keys", "status_code", "content_type", "auth_present", "state_changing", "import_id",
            ])
            for ep in endpoints:
                writer.writerow([
                    ep.id, ep.scope_status, ep.interesting_score, ep.method, ep.scheme, ep.host, ep.port,
                    ep.path, ep.query_keys, ep.status_code, ep.content_type, ep.auth_present, ep.state_changing, ep.import_id,
                ])

        await interaction.followup.send(f"Exported `{len(endpoints)}` endpoints to `{path}`", ephemeral=True)


    @app_commands.command(name="tag", description="Add a tag to an endpoint")
    async def tag(self, interaction: discord.Interaction, endpoint_id: int, tag: str, note: str = ""):
        try:
            ep = self.bot.db.get_endpoint(endpoint_id)
        except KeyError:
            await interaction.response.send_message(f"Endpoint not found: `{endpoint_id}`", ephemeral=True)
            return
        self.bot.db.add_endpoint_tag(endpoint_id, tag, note)
        await interaction.response.send_message(f"Tagged endpoint `#{endpoint_id}` with `{tag.lower()}`.", ephemeral=True)

    @app_commands.command(name="tags", description="List tags for an endpoint")
    async def tags(self, interaction: discord.Interaction, endpoint_id: int):
        rows = self.bot.db.list_endpoint_tags(endpoint_id)
        if not rows:
            await interaction.response.send_message("No tags for this endpoint.", ephemeral=True)
            return
        lines = [f"- `{r['tag']}` — {r['note']}" for r in rows]
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(name="list_by_tag", description="List endpoints by tag")
    async def list_by_tag(self, interaction: discord.Interaction, program_name: str, tag: str, limit: int = 30):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return
        endpoints = self.bot.db.list_endpoints_by_tag(program.id, tag, limit=limit)
        if not endpoints:
            await interaction.response.send_message("No endpoints matched this tag.", ephemeral=True)
            return
        lines = [
            f"`#{ep.id}` `{ep.scope_status}` score `{ep.interesting_score}` `{ep.method}` **{ep.host}**`{ep.path}`"
            for ep in endpoints
        ]
        await interaction.response.send_message(
            embed=discord.Embed(title=f"Endpoints tagged `{tag}` — {program.name}", description="\n".join(lines)[:4000], color=discord.Color.teal()),
            ephemeral=False,
        )


    @app_commands.command(name="show", description="Show endpoint details")
    async def show(self, interaction: discord.Interaction, endpoint_id: int):
        try:
            ep = self.bot.db.get_endpoint(endpoint_id)
            program = self.bot.db.get_program_by_id(ep.program_id)
        except KeyError:
            await interaction.response.send_message(f"Endpoint not found: `{endpoint_id}`", ephemeral=True)
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
