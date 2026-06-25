from __future__ import annotations

import discord
from discord import app_commands

from ..scoring import rank_programs
from ..workspace import (
    create_program_workspace,
    make_program_embed,
    refresh_program_thread,
    program_workspace_name,
)


SORT_CHOICES = [
    app_commands.Choice(name="score - Overall score", value="score"),
    app_commands.Choice(name="scope - Most in-scope targets", value="scope"),
    app_commands.Choice(name="reward - Highest reward", value="reward"),
    app_commands.Choice(name="source - Source code / GitHub first", value="source"),
    app_commands.Choice(name="time_limit - Has time limit first", value="time_limit"),
]


class ProgramCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="program", description="Bug bounty program management")
        self.bot = bot

    @app_commands.command(name="add", description="Register a program and create a category workspace")
    @app_commands.describe(
        name="Program name",
        platform="HackerOne, Bugcrowd, FinderGap, VDP, etc.",
        reward_min="Minimum reward. Use 0 if unknown.",
        reward_max="Maximum reward. Use 0 if unknown.",
        source_code="Whether public source code / GitHub targets exist",
        has_time_limit="Whether testing time limits exist",
        time_limit_note="Time limit note",
        policy_url="Policy URL",
    )
    async def add(
        self,
        interaction: discord.Interaction,
        name: str,
        platform: str = "Unknown",
        reward_min: int = 0,
        reward_max: int = 0,
        source_code: bool = False,
        has_time_limit: bool = False,
        time_limit_note: str = "",
        policy_url: str = "",
    ):
        await interaction.response.defer(ephemeral=True)

        existing = self.bot.db.get_program_by_name(name)
        if existing:
            await interaction.followup.send(f"Program already exists: `{existing.name}`", ephemeral=True)
            return

        if interaction.guild is not None:
            tmp_program = type("Tmp", (), {"platform": platform, "name": name})()
            category_name = program_workspace_name(tmp_program)
            if discord.utils.get(interaction.guild.categories, name=category_name):
                await interaction.followup.send(
                    f"Duplicate blocked: category `{category_name}` already exists. No new program was created.",
                    ephemeral=True,
                )
                return

        try:
            program = self.bot.db.add_program(
                name=name,
                platform=platform,
                reward_min=reward_min,
                reward_max=reward_max,
                source_code=source_code,
                has_time_limit=has_time_limit,
                time_limit_note=time_limit_note,
                policy_url=policy_url,
            )
        except Exception as exc:
            await interaction.followup.send(f"Registration failed: `{exc}`", ephemeral=True)
            return

        workspace_msg = "category workspace was not created"
        if interaction.guild is None:
            workspace_msg = "category workspace failed: run this command inside a server"
        else:
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
                if category:
                    workspace_msg = f"category workspace created: `{category.name}`"
                else:
                    workspace_msg = "category workspace not created: duplicate category exists"
            except discord.Forbidden:
                workspace_msg = "category workspace failed: missing permissions"
            except discord.HTTPException as exc:
                workspace_msg = f"category workspace failed: HTTPException {exc.status}"

        await interaction.followup.send(
            f"Program registered: `{program.name}`\n{workspace_msg}",
            ephemeral=True,
        )

    @app_commands.command(name="list", description="List programs by ranking criteria")
    @app_commands.choices(sort_by=SORT_CHOICES)
    async def list(self, interaction: discord.Interaction, sort_by: str = "score"):
        programs = self.bot.db.list_programs()
        if not programs:
            await interaction.response.send_message("No programs registered yet.", ephemeral=True)
            return

        ranks = rank_programs(programs, self.bot.db.count_in_scope, sort_by)

        lines = []
        for idx, rank in enumerate(ranks[:20], 1):
            p = rank.program
            source = "SRC" if p.source_code else "NO-SRC"
            time_limit = "TIME" if p.has_time_limit else "NO-TIME"
            channel = f"<#{p.discord_thread_id}>" if p.discord_thread_id else "-"
            lines.append(
                f"`{idx:02}` **{p.name}** [{p.platform}] "
                f"| score `{rank.score}` | scope `{rank.in_scope_count}` | reward `{p.reward_max:,}` "
                f"| {source} | {time_limit} | {channel}"
            )

        embed = discord.Embed(
            title=f"Program Ranking: {sort_by}",
            description="\n".join(lines)[:4000],
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="show", description="Show program details")
    async def show(self, interaction: discord.Interaction, name: str):
        program = self.bot.db.get_program_by_name(name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{name}`", ephemeral=True)
            return

        embed = make_program_embed(self.bot.db, program)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="refresh", description="Post the latest program summary to the workspace")
    async def refresh(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        program = self.bot.db.get_program_by_name(name)
        if not program:
            await interaction.followup.send(f"Program not found: `{name}`", ephemeral=True)
            return

        ok = await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)
        if ok:
            await interaction.followup.send("Workspace summary refreshed.", ephemeral=True)
        else:
            await interaction.followup.send("Refresh failed: output channel not found or inaccessible.", ephemeral=True)

    @app_commands.command(name="delete", description="Delete a program from DB, optionally deleting its Discord category")
    async def delete(
        self,
        interaction: discord.Interaction,
        name: str,
        delete_discord_category: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(name)
        if not program:
            await interaction.followup.send(f"Program not found: `{name}`", ephemeral=True)
            return

        deleted_category = False
        if delete_discord_category and interaction.guild is not None:
            category_id = getattr(program, "discord_category_id", None)
            category = self.bot.get_channel(category_id) if category_id else None

            if category is None and category_id:
                try:
                    category = await self.bot.fetch_channel(category_id)
                except discord.DiscordException:
                    category = None

            if category is None and interaction.guild is not None:
                expected_name = program_workspace_name(program)
                category = discord.utils.get(interaction.guild.categories, name=expected_name)

            if isinstance(category, discord.CategoryChannel):
                try:
                    for ch in list(category.channels):
                        await ch.delete(reason=f"BountyOps delete program {program.name}")
                    await category.delete(reason=f"BountyOps delete program {program.name}")
                    deleted_category = True
                except discord.Forbidden:
                    await interaction.followup.send(
                        "Missing permission to delete Discord category/channels.",
                        ephemeral=True,
                    )
                    return
                except discord.HTTPException as exc:
                    await interaction.followup.send(
                        f"Discord delete failed: HTTPException {exc.status}",
                        ephemeral=True,
                    )
                    return

        self.bot.db.delete_program(program.id)

        msg = f"Program deleted from DB: `{program.name}`"
        if deleted_category:
            msg += "\nDiscord category/channels were also deleted."
        elif delete_discord_category:
            msg += "\nDiscord category was not found."
        await interaction.followup.send(msg, ephemeral=True)
