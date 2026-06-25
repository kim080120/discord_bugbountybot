from __future__ import annotations

import time
from pathlib import Path

import discord
from discord import app_commands


class StorageCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="storage", description="Storage stats and cleanup")
        self.bot = bot

    @app_commands.command(name="stats", description="storage 사용량 확인")
    async def stats(self, interaction: discord.Interaction):
        root = self.bot.settings.storage_dir
        if not root.exists():
            await interaction.response.send_message("Storage directory does not exist.", ephemeral=True)
            return

        buckets = {}
        total = 0
        file_count = 0
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            file_count += 1
            total += size
            top = p.relative_to(root).parts[0] if p.relative_to(root).parts else "."
            buckets[top] = buckets.get(top, 0) + size

        lines = [
            "# Storage Stats",
            f"- Root: `{root}`",
            f"- Files: `{file_count}`",
            f"- Total: `{total / 1024 / 1024:.2f} MB`",
            "",
            "## Buckets",
        ]
        for k, v in sorted(buckets.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- `{k}`: `{v / 1024 / 1024:.2f} MB`")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(name="cleanup", description="old storage files cleanup")
    async def cleanup(self, interaction: discord.Interaction, older_than_days: int = 7, dry_run: bool = True, confirm: bool = False):
        await interaction.response.defer(ephemeral=True)
        root = self.bot.settings.storage_dir
        if not root.exists():
            await interaction.followup.send("Storage directory does not exist.", ephemeral=True)
            return
        if older_than_days < 1:
            await interaction.followup.send("older_than_days must be >= 1.", ephemeral=True)
            return
        cutoff = time.time() - older_than_days * 86400
        targets = []
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            # Do not clean DB, just storage artifacts.
            if p.suffix.lower() in {".sqlite3", ".db"}:
                continue
            try:
                if p.stat().st_mtime < cutoff:
                    targets.append(p)
            except OSError:
                pass

        total = sum(p.stat().st_size for p in targets if p.exists())
        if dry_run or not confirm:
            await interaction.followup.send(
                f"Dry run: `{len(targets)}` files, `{total / 1024 / 1024:.2f} MB` would be removed. Run with `dry_run:false confirm:true` to delete.",
                ephemeral=True,
            )
            return

        removed = 0
        for p in targets:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
        await interaction.followup.send(f"Cleanup done. Removed `{removed}` files.", ephemeral=True)
