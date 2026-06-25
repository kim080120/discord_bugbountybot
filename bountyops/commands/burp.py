from __future__ import annotations

import asyncio
import discord
from discord import app_commands

from ..services.importer import BurpImporter
from ..services.burp_temp import scan_burp_temp_folder, build_combined_import_text, candidates_to_json
from ..workspace import post_import_summary, refresh_program_thread, find_program_channel, chunk_text


FORMAT_CHOICES = [
    app_commands.Choice(name="auto", value="auto"),
    app_commands.Choice(name="har", value="har"),
    app_commands.Choice(name="raw", value="raw"),
    app_commands.Choice(name="txt", value="txt"),
]


class BurpCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="burp", description="Burp/HAR import and recovery")
        self.bot = bot

    @app_commands.command(name="import_file", description="Upload a Burp raw/HAR file and build endpoint inventory")
    @app_commands.choices(format=FORMAT_CHOICES)
    async def import_file(
        self,
        interaction: discord.Interaction,
        program_name: str,
        file: discord.Attachment,
        format: str = "auto",
        post_refresh: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        if file.size > 8 * 1024 * 1024:
            await interaction.followup.send("File is too large. v0.4.6 supports uploaded files up to 8MB.", ephemeral=True)
            return

        try:
            content = await file.read()
            importer = BurpImporter(self.bot.db, self.bot.settings.storage_dir)
            result = await asyncio.to_thread(
                importer.import_text,
                program=program,
                filename=file.filename,
                content=content,
                format_hint=format,
            )
        except Exception as exc:
            await interaction.followup.send(f"Import failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        await post_import_summary(
            bot=self.bot,
            db=self.bot.db,
            program=program,
            burp_import=result.burp_import,
        )

        if post_refresh:
            await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        msg = (
            f"Import completed: `#{result.burp_import.id}`\n"
            f"- format: `{result.burp_import.format}`\n"
            f"- endpoints: `{result.burp_import.total_items}`\n"
            f"- in-scope: `{result.burp_import.in_scope_items}`\n"
            f"- out-of-scope: `{result.burp_import.out_scope_items}`\n"
            f"- unknown: `{result.burp_import.unknown_scope_items}`\n"
            f"- sanitized: `{result.burp_import.sanitized_path}`\n"
            f"- workspace refresh: `{post_refresh}`"
        )
        await interaction.followup.send(msg, ephemeral=True)

    @app_commands.command(name="temp_scan", description="Scan a Burp temp folder or .cont file for recoverable HTTP/HAR data")
    async def temp_scan(self, interaction: discord.Interaction, folder_path: str, max_files: int = 500):
        # Defer immediately. Heavy scanning runs in a worker thread.
        await interaction.response.defer(ephemeral=True)

        try:
            candidates = await asyncio.to_thread(
                scan_burp_temp_folder,
                folder_path,
                max_files=max(1, min(max_files, 3000)),
            )
        except Exception as exc:
            await interaction.followup.send(f"Temp scan failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        if not candidates:
            await interaction.followup.send(
                "No recoverable HTTP/HAR-looking files found. Try pointing to the parent burp*.tmp folder or a large .cont file such as 0.1.cont.",
                ephemeral=True,
            )
            return

        lines = []
        for idx, cand in enumerate(candidates[:15], 1):
            hosts = ", ".join(cand.hosts[:5]) if cand.hosts else "-"
            lines.append(
                f"`{idx:02}` score `{cand.score}` | {cand.kind} | {cand.size:,} bytes | "
                f"req `{getattr(cand, 'request_count', 0)}` resp `{getattr(cand, 'response_count', 0)}`\n"
                f"`{cand.path}`\n"
                f"hosts: {hosts}"
            )

        msg = (
            f"Found `{len(candidates)}` candidate files/fragments.\n\n"
            + "\n\n".join(lines)
            + "\n\nPerformance tip: `/burp import_temp` defaults to the top 1 candidate. "
              "Use `candidate_limit:2` only when you really need the 2GB container."
        )
        await interaction.followup.send(msg[:1900], ephemeral=True)

    @app_commands.command(name="import_temp", description="Best-effort import from a Burp temp folder or .cont file")
    async def import_temp(
        self,
        interaction: discord.Interaction,
        program_name: str,
        folder_path: str,
        max_files: int = 500,
        max_total_mb: int = 10,
        candidate_limit: int = 1,
        include_hosts: str = "",
        exclude_hosts: str = "",
        post_refresh: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        try:
            candidates = await asyncio.to_thread(
                scan_burp_temp_folder,
                folder_path,
                max_files=max(1, min(max_files, 3000)),
            )
            if not candidates:
                await interaction.followup.send("No recoverable candidates found.", ephemeral=True)
                return

            combined, used = await asyncio.to_thread(
                build_combined_import_text,
                candidates,
                max_total_bytes=max(1, min(max_total_mb, 100)) * 1024 * 1024,
                candidate_limit=max(1, min(candidate_limit, 20)),
                include_hosts=include_hosts or None,
                exclude_hosts=exclude_hosts or None,
            )

            if not combined.strip() or used <= 0:
                await interaction.followup.send(
                    "Candidates were found, but no readable HTTP/HAR text matched the selected host filters.",
                    ephemeral=True,
                )
                return

            importer = BurpImporter(self.bot.db, self.bot.settings.storage_dir)
            result = await asyncio.to_thread(
                importer.import_text,
                program=program,
                filename="recovered_burp_temp.txt",
                content=combined.encode("utf-8", errors="replace"),
                format_hint="raw",
            )
        except Exception as exc:
            await interaction.followup.send(f"Temp import failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        await post_import_summary(
            bot=self.bot,
            db=self.bot.db,
            program=program,
            burp_import=result.burp_import,
        )

        if post_refresh:
            await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)

        ch = find_program_channel(self.bot, program, "burp-imports")
        if ch:
            summary = candidates_to_json(candidates[:50])
            await ch.send("# Burp Temporary Folder Recovery Summary")
            for chunk in chunk_text("```json\n" + summary + "\n```", limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(
            "\n".join(
                [
                    f"Temp import completed: `#{result.burp_import.id}`",
                    f"- candidate files used: `{used}` / found `{len(candidates)}`",
                    f"- candidate_limit: `{candidate_limit}`",
                    f"- include_hosts: `{include_hosts or '-'}`",
                    f"- exclude_hosts: `{exclude_hosts or '-'}`",
                    f"- parsed endpoints: `{result.burp_import.total_items}`",
                    f"- in-scope: `{result.burp_import.in_scope_items}`",
                    f"- out-of-scope: `{result.burp_import.out_scope_items}`",
                    f"- unknown: `{result.burp_import.unknown_scope_items}`",
                    f"- sanitized file: `{result.burp_import.sanitized_path}`",
                    f"- workspace refresh: `{post_refresh}`",
                ]
            ),
            ephemeral=True,
        )


    @app_commands.command(name="delete_import", description="Delete one Burp import and its endpoints")
    async def delete_import(self, interaction: discord.Interaction, import_id: int, confirm: bool = False):
        await interaction.response.defer(ephemeral=True)

        try:
            item = self.bot.db.get_burp_import(import_id)
            program = self.bot.db.get_program_by_id(item.program_id)
        except KeyError:
            await interaction.followup.send(f"Import not found: `{import_id}`", ephemeral=True)
            return

        if not confirm:
            await interaction.followup.send(
                "\n".join(
                    [
                        f"Import `#{item.id}` belongs to program `{program.name}`.",
                        f"Filename: `{item.filename}`",
                        f"Endpoints: `{item.total_items}`",
                        "",
                        "Nothing was deleted.",
                        "Run again with `confirm:true` to delete this import and its endpoints.",
                    ]
                ),
                ephemeral=True,
            )
            return

        self.bot.db.delete_burp_import(import_id)
        await interaction.followup.send(
            f"Deleted Burp import `#{import_id}` and its endpoint rows.",
            ephemeral=True,
        )

    @app_commands.command(name="dedupe", description="Remove duplicate endpoint rows for a program")
    async def dedupe(self, interaction: discord.Interaction, program_name: str):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        removed = self.bot.db.dedupe_endpoints(program.id)
        await interaction.followup.send(
            f"Deduplication completed for `{program.name}`. Removed `{removed}` duplicate endpoint rows.",
            ephemeral=True,
        )



    @app_commands.command(name="watch_start", description="Watch Burp temp files and live-import in-scope traffic")
    async def watch_start(
        self,
        interaction: discord.Interaction,
        program_name: str,
        temp_root: str = "",
        poll_interval: int = 10,
        mode: str = "in_scope_only",
        max_total_mb: int = 10,
        candidate_limit: int = 1,
        include_hosts: str = "",
        exclude_hosts: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        if mode not in {"in_scope_only", "all_except_out", "manual_filters"}:
            await interaction.followup.send(
                "Invalid mode. Use `in_scope_only`, `all_except_out`, or `manual_filters`.",
                ephemeral=True,
            )
            return

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        try:
            await self.bot.burp_live_watcher.start(
                program_name=program_name,
                temp_root=temp_root or None,
                poll_interval=poll_interval,
                mode=mode,
                max_total_mb=max_total_mb,
                candidate_limit=candidate_limit,
                include_hosts=include_hosts,
                exclude_hosts=exclude_hosts,
            )
        except Exception as exc:
            await interaction.followup.send(f"Failed to start watcher: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        await interaction.followup.send(
            "\n".join(
                [
                    f"Burp live watcher started for `{program_name}`.",
                    f"- temp_root: `{temp_root or '%TEMP%'}`",
                    f"- poll_interval: `{poll_interval}` seconds",
                    f"- mode: `{mode}`",
                    f"- max_total_mb: `{max_total_mb}`",
                    f"- candidate_limit: `{candidate_limit}`",
                    f"- include_hosts: `{include_hosts or '-'}`",
                    f"- exclude_hosts: `{exclude_hosts or '-'}`",
                ]
            ),
            ephemeral=True,
        )

    @app_commands.command(name="watch_status", description="Show Burp live watcher status")
    async def watch_status(self, interaction: discord.Interaction):
        stats = getattr(self.bot, "burp_live_watcher", None).stats if getattr(self.bot, "burp_live_watcher", None) else None
        running = getattr(self.bot, "burp_live_watcher", None).is_running() if getattr(self.bot, "burp_live_watcher", None) else False

        if not stats:
            await interaction.response.send_message("Burp live watcher has not been started.", ephemeral=True)
            return

        await interaction.response.send_message(
            "\n".join(
                [
                    f"Burp live watcher running: `{running}`",
                    f"- program: `{stats.program_name}`",
                    f"- temp_root: `{stats.temp_root}`",
                    f"- current_dir: `{stats.current_dir or '-'}`",
                    f"- poll_interval: `{stats.poll_interval}`",
                    f"- mode: `{stats.mode}`",
                    f"- scans: `{stats.scans}`",
                    f"- imports: `{stats.imports}`",
                    f"- endpoints total: `{stats.endpoints}`",
                    f"- in/out/unknown: `{stats.in_scope}` / `{stats.out_scope}` / `{stats.unknown}`",
                    f"- last_message: `{stats.last_message[:500] or '-'}`",
                    f"- last_error: `{stats.last_error or '-'}`",
                ]
            )[:1900],
            ephemeral=True,
        )

    @app_commands.command(name="watch_stop", description="Stop Burp live watcher")
    async def watch_stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        watcher = getattr(self.bot, "burp_live_watcher", None)
        if not watcher or not watcher.is_running():
            await interaction.followup.send("Burp live watcher is not running.", ephemeral=True)
            return

        stats = await watcher.stop()
        await interaction.followup.send(
            f"Burp live watcher stopped. Imports: `{stats.imports if stats else 0}`, endpoints: `{stats.endpoints if stats else 0}`",
            ephemeral=True,
        )


    @app_commands.command(name="imports", description="List recent Burp/HAR imports for a program")
    async def imports(self, interaction: discord.Interaction, program_name: str, limit: int = 10):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        imports = self.bot.db.list_burp_imports(program.id, limit=max(1, min(limit, 20)))
        if not imports:
            await interaction.response.send_message("No imports yet.", ephemeral=True)
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

    @app_commands.command(name="show", description="Show import details")
    async def show(self, interaction: discord.Interaction, import_id: int):
        try:
            item = self.bot.db.get_burp_import(import_id)
            program = self.bot.db.get_program_by_id(item.program_id)
        except KeyError:
            await interaction.response.send_message(f"Import not found: `{import_id}`", ephemeral=True)
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
