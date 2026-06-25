from __future__ import annotations

import discord
from discord import app_commands


EXPECTED_CHANNELS = {
    "general",
    "scope",
    "restrictions",
    "notices",
    "burp-imports",
    "ai-analysis",
    "evidence",
    "report-drafts",
}


def looks_like_bountyops_category(category: discord.CategoryChannel) -> bool:
    channel_names = {ch.name for ch in category.text_channels}
    return len(EXPECTED_CHANNELS.intersection(channel_names)) >= 3


class WorkspaceCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="workspace", description="Workspace/category cleanup tools")
        self.bot = bot

    @app_commands.command(name="list", description="List BountyOps-like Discord workspace categories")
    async def list(self, interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("Run this command inside a server.", ephemeral=True)
            return

        rows = []
        for cat in interaction.guild.categories:
            if looks_like_bountyops_category(cat):
                linked = self.bot.db.get_program_by_category_id(cat.id)
                linked_text = f"linked program `{linked.name}`" if linked else "orphan / not linked in DB"
                rows.append(
                    f"- `{cat.name}` | id `{cat.id}` | {len(cat.channels)} channels | {linked_text}"
                )

        if not rows:
            await interaction.response.send_message("No BountyOps-like categories found.", ephemeral=True)
            return

        embed = discord.Embed(
            title="BountyOps Workspace Categories",
            description="\n".join(rows)[:4000],
            color=discord.Color.blue(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="delete_category", description="Delete an orphan/workspace category by exact name")
    async def delete_category(
        self,
        interaction: discord.Interaction,
        category_name: str,
        confirm: bool = False,
        delete_channels: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("Run this command inside a server.", ephemeral=True)
            return

        category = discord.utils.get(interaction.guild.categories, name=category_name)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send(f"Category not found: `{category_name}`", ephemeral=True)
            return

        if not looks_like_bountyops_category(category):
            await interaction.followup.send(
                "Safety check failed: this category does not look like a BountyOps workspace. "
                "It must contain several expected channels such as general/scope/restrictions/notices.",
                ephemeral=True,
            )
            return

        linked = self.bot.db.get_program_by_category_id(category.id)
        linked_text = f"linked to DB program `{linked.name}`" if linked else "not linked to any DB program"

        if not confirm:
            await interaction.followup.send(
                "\n".join(
                    [
                        f"Category `{category.name}` found and is {linked_text}.",
                        f"Channels: {', '.join(ch.name for ch in category.channels)}",
                        "",
                        "Nothing was deleted.",
                        "Run again with `confirm:true` to delete it.",
                    ]
                )[:1900],
                ephemeral=True,
            )
            return

        try:
            if delete_channels:
                for ch in list(category.channels):
                    await ch.delete(reason=f"BountyOps workspace delete_category {category.name}")
            await category.delete(reason=f"BountyOps workspace delete_category {category.name}")
        except discord.Forbidden:
            await interaction.followup.send("Missing permission to delete category/channels.", ephemeral=True)
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"Delete failed: HTTPException {exc.status}", ephemeral=True)
            return

        await interaction.followup.send(
            f"Deleted category `{category_name}`."
            + (" Channels were deleted too." if delete_channels else " Channels were not deleted."),
            ephemeral=True,
        )

    @app_commands.command(name="adopt", description="Link an existing Discord category to an existing DB program")
    async def adopt(self, interaction: discord.Interaction, program_name: str, category_name: str):
        await interaction.response.defer(ephemeral=True)

        if interaction.guild is None:
            await interaction.followup.send("Run this command inside a server.", ephemeral=True)
            return

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found in DB: `{program_name}`", ephemeral=True)
            return

        category = discord.utils.get(interaction.guild.categories, name=category_name)
        if not isinstance(category, discord.CategoryChannel):
            await interaction.followup.send(f"Category not found: `{category_name}`", ephemeral=True)
            return

        general = discord.utils.get(category.text_channels, name="general")
        self.bot.db.set_program_category(program.id, category.id, general.id if general else None)

        await interaction.followup.send(
            f"Adopted category `{category.name}` for program `{program.name}`.",
            ephemeral=True,
        )
