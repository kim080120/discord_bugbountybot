from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import discord
from discord import app_commands


class SystemCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="system", description="System status and migration")
        self.bot = bot

    @app_commands.command(name="status", description="BountyOps 상태 확인")
    async def status(self, interaction: discord.Interaction):
        db_ok = True
        db_error = ""
        try:
            self.bot.db.conn.execute("SELECT 1").fetchone()
        except Exception as exc:
            db_ok = False
            db_error = f"{type(exc).__name__}: {exc}"

        h1_user = getattr(self.bot.settings, "hackerone_username", "")
        h1_token = getattr(self.bot.settings, "hackerone_api_token", "")
        watcher = getattr(self.bot, "burp_live_watcher", None)
        watcher_running = watcher.is_running() if watcher else False

        storage_size = 0
        if self.bot.settings.storage_dir.exists():
            for p in self.bot.settings.storage_dir.rglob("*"):
                if p.is_file():
                    try:
                        storage_size += p.stat().st_size
                    except OSError:
                        pass

        lines = [
            "# BountyOps System Status",
            f"- Version: `v0.6.0`",
            f"- DB: `{'OK' if db_ok else 'ERROR'}` {db_error}",
            f"- DB path: `{self.bot.settings.database_path}`",
            f"- Storage: `{self.bot.settings.storage_dir}` ({storage_size / 1024 / 1024:.2f} MB)",
            f"- Discord guild id: `{self.bot.settings.discord_guild_id or '-'}`",
            f"- HackerOne API: `{'configured' if h1_user and h1_token else 'not configured'}`",
            f"- Burp watcher: `{'running' if watcher_running else 'stopped'}`",
            "",
            "## Counts",
        ]
        for table in ["programs", "scope_items", "burp_imports", "endpoints", "findings", "evidence", "report_drafts", "ai_results", "policy_snapshots", "endpoint_tags"]:
            try:
                lines.append(f"- {table}: `{self.bot.db.count_table(table)}`")
            except Exception:
                lines.append(f"- {table}: `n/a`")

        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)

    @app_commands.command(name="migrate", description="DB migration/schema 생성 확인")
    async def migrate(self, interaction: discord.Interaction):
        # Opening Database at startup already creates tables. This command verifies key tables.
        expected = [
            "programs", "scope_items", "burp_imports", "endpoints", "findings",
            "evidence", "report_drafts", "ai_results", "policy_snapshots",
            "endpoint_tags", "seen_requests", "system_meta",
        ]
        rows = self.bot.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        names = {r["name"] for r in rows}
        missing = [x for x in expected if x not in names]
        if missing:
            await interaction.response.send_message(f"Missing tables: `{missing}`. Restart with the latest code or recreate DB.", ephemeral=True)
            return
        self.bot.db.set_meta("schema_checked_by", "system.migrate")
        await interaction.response.send_message("DB schema check OK. All expected tables exist.", ephemeral=True)

    @app_commands.command(name="db_info", description="DB 테이블 정보 확인")
    async def db_info(self, interaction: discord.Interaction):
        rows = self.bot.db.conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        lines = ["# DB Tables"]
        for r in rows:
            name = r["name"]
            if name.startswith("sqlite_"):
                continue
            try:
                count = self.bot.db.conn.execute(f"SELECT COUNT(*) AS c FROM {name}").fetchone()["c"]
            except Exception:
                count = "?"
            lines.append(f"- `{name}`: `{count}`")
        await interaction.response.send_message("\n".join(lines)[:1900], ephemeral=True)
