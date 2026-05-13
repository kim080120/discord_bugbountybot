from __future__ import annotations

import logging

import discord
from discord import app_commands

from .config import Settings
from .db import Database
from .commands.program import ProgramCommands
from .commands.scope import ScopeCommands
from .commands.notice import NoticeCommands
from .commands.restriction import RestrictionCommands
from .commands.burp import BurpCommands
from .commands.endpoint import EndpointCommands


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bountyops")


class BountyOpsBot(discord.Client):
    def __init__(self, settings: Settings, db: Database):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.settings = settings
        self.db = db
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        self.tree.add_command(ProgramCommands(self))
        self.tree.add_command(ScopeCommands(self))
        self.tree.add_command(NoticeCommands(self))
        self.tree.add_command(RestrictionCommands(self))
        self.tree.add_command(BurpCommands(self))
        self.tree.add_command(EndpointCommands(self))

        if self.settings.discord_guild_id:
            guild = discord.Object(id=self.settings.discord_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Slash commands synced to guild %s", self.settings.discord_guild_id)
        else:
            await self.tree.sync()
            log.info("Slash commands synced globally")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (%s)", self.user, self.user.id if self.user else "unknown")


def main() -> None:
    settings = Settings.load()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    db.init()

    bot = BountyOpsBot(settings=settings, db=db)

    @bot.tree.command(name="ping", description="BountyOps 상태 확인")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("pong - BountyOps v0.2", ephemeral=True)

    try:
        bot.run(settings.discord_token)
    finally:
        db.close()


if __name__ == "__main__":
    main()
