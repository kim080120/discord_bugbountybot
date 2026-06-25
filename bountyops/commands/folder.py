from __future__ import annotations

import discord
from discord import app_commands

from ..services.workspace_folders import default_program_folder, init_program_folder, tree_text


class FolderCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="folder", description="Program local workspace folder")
        self.bot = bot

    @app_commands.command(name="set", description="Set local folder path for a program")
    async def set(self, interaction: discord.Interaction, program_name: str, folder_path: str = "", create_dirs: bool = True):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        if not folder_path:
            folder = default_program_folder(self.bot.settings.storage_dir, program)
        else:
            folder = folder_path

        if create_dirs:
            root = init_program_folder(folder)
        else:
            from pathlib import Path
            root = Path(folder).expanduser()

        self.bot.db.set_program_folder(program.id, str(root))

        await interaction.followup.send(
            f"Folder set for `{program.name}`:\n`{root}`\ncreate_dirs=`{create_dirs}`",
            ephemeral=True,
        )

    @app_commands.command(name="info", description="Show local folder path for a program")
    async def info(self, interaction: discord.Interaction, program_name: str):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        folder = self.bot.db.get_program_folder(program.id)
        if not folder:
            await interaction.response.send_message(
                f"No folder set for `{program.name}`. Use `/folder set program_name:{program.name}`.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(f"`{program.name}` folder:\n`{folder}`", ephemeral=True)

    @app_commands.command(name="tree", description="Show local workspace folder tree")
    async def tree(self, interaction: discord.Interaction, program_name: str):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        folder = self.bot.db.get_program_folder(program.id)
        if not folder:
            await interaction.response.send_message("No folder set. Use `/folder set` first.", ephemeral=True)
            return

        text = tree_text(folder)
        await interaction.response.send_message("```text\n" + text[:1800] + "\n```", ephemeral=True)
