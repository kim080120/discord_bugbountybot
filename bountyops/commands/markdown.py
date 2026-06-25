from __future__ import annotations

import discord
from discord import app_commands

from ..services.workspace_folders import default_program_folder, init_program_folder
from ..services.md_organizer import import_markdown_text, scan_markdown_folder
from ..workspace import find_program_channel, chunk_text


class MarkdownCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="md", description="Codex/Claude markdown organizer")
        self.bot = bot

    def _workspace_root(self, program):
        folder = self.bot.db.get_program_folder(program.id)
        if folder:
            return folder
        root = default_program_folder(self.bot.settings.storage_dir, program)
        init_program_folder(root)
        self.bot.db.set_program_folder(program.id, str(root))
        return str(root)

    async def _post_result(self, program, result):
        ch = find_program_channel(self.bot, program, "ai-analysis") or find_program_channel(self.bot, program, "general")
        if not ch:
            return
        info = result["summary"]
        if result.get("skipped"):
            await ch.send(
                f"## Markdown skipped: duplicate\n"
                f"- Existing markdown id: `{result.get('markdown_id')}`\n"
                f"- Title: `{info.title}`\n"
                f"- Category: `{info.category}`"
            )
            return

        lines = [
            f"# Markdown Imported #{result['markdown_id']}: {info.title}",
            f"- Category: `{info.category}`",
            f"- Stored path: `{result['stored_path']}`",
            f"- AI result: `#{result['ai_result_id']}`",
            f"- Findings created: `{result['findings'] or '-'}`",
            "",
            "## Summary",
            info.summary,
        ]
        if info.candidates:
            lines += ["", "## Candidate lines"]
            lines += [f"- {c}" for c in info.candidates[:10]]
        for chunk in chunk_text("\n".join(lines), limit=1900):
            await ch.send(chunk)

    @app_commands.command(name="import_file", description="Import a Codex/Claude markdown attachment")
    async def import_file(
        self,
        interaction: discord.Interaction,
        program_name: str,
        file: discord.Attachment,
        provider: str = "codex",
        mode: str = "analysis",
        create_findings: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        if file.size > 2 * 1024 * 1024:
            await interaction.followup.send("Markdown file too large. Limit is 2MB.", ephemeral=True)
            return

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        text = (await file.read()).decode("utf-8", errors="replace")
        root = self._workspace_root(program)

        try:
            result = import_markdown_text(
                db=self.bot.db,
                program=program,
                workspace_root=root,
                source_name=file.filename,
                text=text,
                provider=provider,
                mode=mode,
                create_findings=create_findings,
            )
        except Exception as exc:
            await interaction.followup.send(f"Markdown import failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        await self._post_result(program, result)
        await interaction.followup.send(
            f"Markdown import done. skipped=`{result.get('skipped', False)}`, category=`{result['summary'].category}`, findings=`{result.get('findings') or '-'}`",
            ephemeral=True,
        )

    @app_commands.command(name="scan_folder", description="Scan workspace ai/inbox or a local folder for markdown files")
    async def scan_folder(
        self,
        interaction: discord.Interaction,
        program_name: str,
        scan_dir: str = "ai/inbox",
        provider: str = "codex",
        mode: str = "analysis",
        create_findings: bool = False,
        move_processed: bool = True,
        limit: int = 50,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        root = self._workspace_root(program)

        try:
            results = await __import__("asyncio").to_thread(
                scan_markdown_folder,
                db=self.bot.db,
                program=program,
                workspace_root=root,
                scan_dir=scan_dir,
                provider=provider,
                mode=mode,
                create_findings=create_findings,
                move_processed=move_processed,
                limit=limit,
            )
        except Exception as exc:
            await interaction.followup.send(f"Markdown folder scan failed: `{type(exc).__name__}: {exc}`", ephemeral=True)
            return

        for result in results[:10]:
            await self._post_result(program, result)

        imported = sum(1 for r in results if not r.get("skipped"))
        skipped = sum(1 for r in results if r.get("skipped"))
        findings = sum(len(r.get("findings") or []) for r in results)

        await interaction.followup.send(
            f"Markdown scan done. imported=`{imported}`, skipped=`{skipped}`, findings_created=`{findings}`, workspace=`{root}`",
            ephemeral=True,
        )

    @app_commands.command(name="index", description="List imported markdown analysis files")
    async def index(self, interaction: discord.Interaction, program_name: str, limit: int = 20):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rows = self.bot.db.list_ai_markdown_files(program.id, limit=limit)
        if not rows:
            await interaction.response.send_message("No markdown files imported yet.", ephemeral=True)
            return

        lines = [
            f"`#{r['id']}` **{r['title']}** | `{r['category']}` | `{r['provider']}` / `{r['mode']}`\n`{r['stored_path']}`"
            for r in rows
        ]
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"Markdown Index — {program.name}",
                description="\n\n".join(lines)[:4000],
                color=discord.Color.blue(),
            ),
            ephemeral=False,
        )
