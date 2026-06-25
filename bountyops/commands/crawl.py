from __future__ import annotations

import json
import discord
from discord import app_commands

from ..workspace import create_program_workspace, program_workspace_name
from .hackerone import make_preview_embed


def normalize_scope_entry_for_apply(entry) -> tuple[str, str]:
    if isinstance(entry, dict):
        return str(entry.get("value") or "").strip(), str(entry.get("note") or "").strip()

    raw = str(entry).strip()
    if " | " in raw:
        value, note = raw.split(" | ", 1)
        return value.strip(), note.strip()
    return raw, ""


class CrawlCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="crawl", description="Crawl candidate review/apply/delete")
        self.bot = bot

    @app_commands.command(name="list", description="List recent crawl candidates")
    async def list(self, interaction: discord.Interaction, limit: int = 10):
        rows = self.bot.db.list_site_crawls(limit=limit)
        if not rows:
            await interaction.response.send_message("No crawl candidates yet.", ephemeral=True)
            return

        lines = []
        for row in rows:
            lines.append(
                f'`#{row["id"]}` **{row["platform"]}-{row["suggested_name"]}** '
                f'| status `{row["status"]}` | reward `{int(row["reward_max"]):,}` | {row["source_url"][:80]}'
            )

        embed = discord.Embed(
            title="Crawl Candidates",
            description="\n".join(lines)[:4000],
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="show", description="Show a crawl candidate preview")
    async def show(self, interaction: discord.Interaction, crawl_id: int):
        row = self.bot.db.get_site_crawl(crawl_id)
        if not row:
            await interaction.response.send_message(f"Crawl candidate not found: `{crawl_id}`", ephemeral=True)
            return

        await interaction.response.send_message(embed=make_preview_embed(crawl_id, row), ephemeral=False)

    @app_commands.command(name="apply", description="Create a program workspace from a selected crawl candidate")
    async def apply(self, interaction: discord.Interaction, crawl_id: int):
        await interaction.response.defer(ephemeral=True)

        row = self.bot.db.get_site_crawl(crawl_id)
        if not row:
            await interaction.followup.send(f"Crawl candidate not found: `{crawl_id}`", ephemeral=True)
            return

        if row["status"] == "applied":
            await interaction.followup.send(
                f"This candidate is already applied. program_id=`{row['applied_program_id']}`",
                ephemeral=True,
            )
            return

        name = row["suggested_name"] or f"crawl-{crawl_id}"
        platform = row["platform"]

        existing = self.bot.db.get_program_by_name(name)
        if existing:
            await interaction.followup.send(
                f"Duplicate blocked: program already exists: `{existing.name}`. No workspace was created.",
                ephemeral=True,
            )
            return

        if interaction.guild is None:
            await interaction.followup.send("Run this command inside a server.", ephemeral=True)
            return

        tmp_program = type("Tmp", (), {"platform": platform, "name": name})()
        category_name = program_workspace_name(tmp_program)
        existing_category = discord.utils.get(interaction.guild.categories, name=category_name)
        if existing_category:
            await interaction.followup.send(
                f"Duplicate blocked: category `{category_name}` already exists. No workspace was created.",
                ephemeral=True,
            )
            return

        program = self.bot.db.add_program(
            name=name,
            platform=platform,
            reward_min=0,
            reward_max=int(row["reward_max"] or 0),
            source_code=bool(row["source_code"]),
            has_time_limit=bool(row["has_time_limit"]),
            time_limit_note=row["time_limit_note"] or "",
            policy_url=row["source_url"] or "",
        )

        seen_scope_values = set()

        for entry in json.loads(row["in_scope_json"]):
            value, note = normalize_scope_entry_for_apply(entry)
            if not value or ("in", value) in seen_scope_values:
                continue
            seen_scope_values.add(("in", value))
            self.bot.db.add_scope_item(
                program_id=program.id,
                type="in",
                value=value,
                note=note or "auto-imported candidate",
                source_url=row["source_url"] or "",
            )

        for entry in json.loads(row["out_scope_json"]):
            value, note = normalize_scope_entry_for_apply(entry)
            if not value or ("out", value) in seen_scope_values:
                continue
            seen_scope_values.add(("out", value))
            self.bot.db.add_scope_item(
                program_id=program.id,
                type="out",
                value=value,
                note=note or "auto-imported candidate",
                source_url=row["source_url"] or "",
            )

        for text in json.loads(row["restrictions_json"]):
            self.bot.db.add_restriction(
                program_id=program.id,
                severity="medium",
                text=text,
                source_url=row["source_url"] or "",
            )

        for text in json.loads(row["notices_json"]):
            self.bot.db.add_notice(
                program_id=program.id,
                title="Auto-import notice",
                summary=text,
                source_url=row["source_url"] or "",
            )

        parent_category = None
        parent_category_id = getattr(self.bot.settings, "discord_parent_category_id", None)
        if parent_category_id:
            channel = self.bot.get_channel(parent_category_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(parent_category_id)
                except discord.DiscordException:
                    channel = None
            if isinstance(channel, discord.CategoryChannel):
                parent_category = channel

        try:
            category = await create_program_workspace(
                guild=interaction.guild,
                db=self.bot.db,
                program=program,
                parent_category=parent_category,
            )
        except discord.Forbidden:
            await interaction.followup.send("Workspace creation failed: missing permissions.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Workspace creation failed: HTTPException {exc.status}", ephemeral=True)
            return

        if category is None:
            await interaction.followup.send(
                f"Workspace was not created because category `{category_name}` already exists.",
                ephemeral=True,
            )
            return

        self.bot.db.mark_site_crawl_applied(crawl_id, program.id)
        await interaction.followup.send(
            f"Applied: `{platform}-{name}` → category `{category.name}`",
            ephemeral=True,
        )

    @app_commands.command(name="update", description="후보 스코프를 같은 이름의 기존 프로그램에 반영(추가)")
    async def update(self, interaction: discord.Interaction, crawl_id: int):
        await interaction.response.defer(ephemeral=True)

        row = self.bot.db.get_site_crawl(crawl_id)
        if not row:
            await interaction.followup.send(f"Crawl candidate not found: `{crawl_id}`", ephemeral=True)
            return

        program = self.bot.db.get_program_by_name(row["suggested_name"])
        if not program:
            await interaction.followup.send(
                f"프로그램 `{row['suggested_name']}` 없음. 새로 만들려면 `/crawl apply crawl_id:{crawl_id}`.",
                ephemeral=True,
            )
            return

        existing = {(s.type, s.value) for s in self.bot.db.list_scope_items(program.id)}
        existing_values = {s.value for s in self.bot.db.list_scope_items(program.id)}

        candidate_values: set[str] = set()
        added: list[str] = []
        for scope_type, json_key in (("in", "in_scope_json"), ("out", "out_scope_json")):
            for entry in json.loads(row[json_key]):
                value, note = normalize_scope_entry_for_apply(entry)
                if not value:
                    continue
                candidate_values.add(value)
                if (scope_type, value) in existing:
                    continue
                self.bot.db.add_scope_item(
                    program_id=program.id,
                    type=scope_type,
                    value=value,
                    note=note or "auto-update",
                    source_url=row["source_url"] or "",
                )
                added.append(f"{scope_type}:{value}")

        removed = sorted(existing_values - candidate_values)
        self.bot.db.mark_site_crawl_applied(crawl_id, program.id)

        msg = [
            f"`{program.name}` 스코프 업데이트 완료:",
            f"- 추가 `{len(added)}`건",
            f"- 후보에 없는(제거 후보) `{len(removed)}`건 — 자동 삭제하지 않음(수동 확인)",
        ]
        if added:
            msg.append("추가됨: " + ", ".join(added[:15]) + (" …" if len(added) > 15 else ""))
        if removed:
            msg.append("제거 후보: " + ", ".join(removed[:15]) + (" …" if len(removed) > 15 else ""))
        await interaction.followup.send("\n".join(msg)[:1900], ephemeral=True)

    @app_commands.command(name="delete", description="Delete a pending crawl candidate from DB")
    async def delete(self, interaction: discord.Interaction, crawl_id: int):
        await interaction.response.defer(ephemeral=True)

        row = self.bot.db.get_site_crawl(crawl_id)
        if not row:
            await interaction.followup.send(f"Crawl candidate not found: `{crawl_id}`", ephemeral=True)
            return

        if row["status"] == "applied":
            await interaction.followup.send(
                "This crawl candidate is already applied. Delete the program/workspace separately if needed.",
                ephemeral=True,
            )
            return

        self.bot.db.delete_site_crawl(crawl_id)
        await interaction.followup.send(f"Deleted crawl candidate `#{crawl_id}`.", ephemeral=True)
