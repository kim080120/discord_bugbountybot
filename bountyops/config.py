from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    discord_forum_channel_id: int | None
    database_path: Path
    storage_dir: Path

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is missing. Create .env from .env.example.")

        guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        forum_raw = os.getenv("DISCORD_FORUM_CHANNEL_ID", "").strip()

        db_path = Path(os.getenv("DATABASE_PATH", "./data/bountyops.sqlite3")).expanduser()
        storage_dir = Path(os.getenv("STORAGE_DIR", "./storage")).expanduser()

        return cls(
            discord_token=token,
            discord_guild_id=int(guild_raw) if guild_raw else None,
            discord_forum_channel_id=int(forum_raw) if forum_raw else None,
            database_path=db_path,
            storage_dir=storage_dir,
        )
