from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    discord_token: str
    discord_guild_id: int | None
    discord_parent_category_id: int | None
    database_path: Path
    storage_dir: Path
    workspace_mode: str
    hackerone_username: str
    hackerone_api_token: str
    ai_engine: str
    claude_bin: str | None
    claude_oauth_token: str | None
    ai_timeout: float
    scope_refresh_days: int
    scope_refresh_channel_id: int | None

    @classmethod
    def load(cls) -> "Settings":
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_TOKEN is missing. Create .env from .env.example.")

        guild_raw = os.getenv("DISCORD_GUILD_ID", "").strip()
        parent_raw = os.getenv("DISCORD_PARENT_CATEGORY_ID", "").strip()

        db_path = Path(os.getenv("DATABASE_PATH", "./data/bountyops.sqlite3")).expanduser()
        storage_dir = Path(os.getenv("STORAGE_DIR", "./storage")).expanduser()
        workspace_mode = os.getenv("DISCORD_WORKSPACE_MODE", "category").strip().lower() or "category"

        ai_engine = os.getenv("AI_ENGINE", "claude").strip().lower() or "claude"
        claude_bin = os.getenv("CLAUDE_BIN", "").strip() or None
        claude_oauth_token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN", "").strip() or None
        try:
            ai_timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "600").strip() or "600")
        except ValueError:
            ai_timeout = 600.0

        try:
            scope_refresh_days = int(os.getenv("SCOPE_REFRESH_DAYS", "7").strip() or "7")
        except ValueError:
            scope_refresh_days = 7
        refresh_ch = (
            os.getenv("SCOPE_REFRESH_CHANNEL_ID", "").strip()
            or os.getenv("DISCORD_FORUM_CHANNEL_ID", "").strip()
        )
        scope_refresh_channel_id = int(refresh_ch) if refresh_ch.isdigit() else None

        return cls(
            discord_token=token,
            discord_guild_id=int(guild_raw) if guild_raw else None,
            discord_parent_category_id=int(parent_raw) if parent_raw else None,
            database_path=db_path,
            storage_dir=storage_dir,
            workspace_mode=workspace_mode,
            hackerone_username=os.getenv("HACKERONE_USERNAME", "").strip(),
            hackerone_api_token=os.getenv("HACKERONE_API_TOKEN", "").strip(),
            ai_engine=ai_engine,
            claude_bin=claude_bin,
            claude_oauth_token=claude_oauth_token,
            ai_timeout=ai_timeout,
            scope_refresh_days=scope_refresh_days,
            scope_refresh_channel_id=scope_refresh_channel_id,
        )
