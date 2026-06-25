from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import discord

from .burp_temp import scan_burp_temp_folder, build_combined_import_text
from .importer import BurpImporter
from ..workspace import find_program_channel
from .scope_matcher import host_matches_scope


def default_temp_root() -> Path:
    return Path(os.getenv("TEMP") or os.getenv("TMP") or ".").expanduser()


def find_burp_tmp_dirs(temp_root: str | Path, limit: int = 5) -> list[Path]:
    root = Path(temp_root).expanduser()
    if not root.exists() or not root.is_dir():
        return []

    dirs = [p for p in root.glob("burp*.tmp") if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return dirs[:limit]


def newest_burp_tmp_dir(temp_root: str | Path) -> Path | None:
    dirs = find_burp_tmp_dirs(temp_root, limit=1)
    return dirs[0] if dirs else None


def scope_patterns_from_program(db, program, mode: str) -> tuple[str, str]:
    """
    mode:
    - in_scope_only: include only in-scope host patterns and exclude out-scope patterns
    - all_except_out: no include filter, only exclude out-scope
    """
    in_scopes = db.list_scope_items(program.id, "in")
    out_scopes = db.list_scope_items(program.id, "out")

    include_hosts = ""
    exclude_hosts = ",".join(s.value for s in out_scopes)

    if mode == "in_scope_only":
        include_hosts = ",".join(s.value for s in in_scopes)

    return include_hosts, exclude_hosts


@dataclass(slots=True)
class WatchStats:
    program_name: str
    temp_root: str
    current_dir: str = ""
    poll_interval: int = 10
    mode: str = "in_scope_only"
    max_total_mb: int = 10
    candidate_limit: int = 1
    include_hosts: str = ""
    exclude_hosts: str = ""
    scans: int = 0
    imports: int = 0
    endpoints: int = 0
    in_scope: int = 0
    out_scope: int = 0
    unknown: int = 0
    last_message: str = ""
    last_error: str = ""
    started_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class BurpLiveWatcher:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.task: asyncio.Task | None = None
        self.stop_event = asyncio.Event()
        self.stats: WatchStats | None = None
        self._seen_signature: set[tuple[str, int, int]] = set()

    def is_running(self) -> bool:
        return self.task is not None and not self.task.done()

    async def start(
        self,
        *,
        program_name: str,
        temp_root: str | None = None,
        poll_interval: int = 10,
        mode: str = "in_scope_only",
        max_total_mb: int = 10,
        candidate_limit: int = 1,
        include_hosts: str = "",
        exclude_hosts: str = "",
    ) -> None:
        if self.is_running():
            raise RuntimeError("Burp live watcher is already running. Stop it first.")

        self.stop_event = asyncio.Event()
        root = str(Path(temp_root).expanduser()) if temp_root else str(default_temp_root())
        self.stats = WatchStats(
            program_name=program_name,
            temp_root=root,
            poll_interval=max(3, min(poll_interval, 120)),
            mode=mode,
            max_total_mb=max(1, min(max_total_mb, 100)),
            candidate_limit=max(1, min(candidate_limit, 10)),
            include_hosts=include_hosts,
            exclude_hosts=exclude_hosts,
        )
        self._seen_signature = set()
        self.task = asyncio.create_task(self._run())

    async def stop(self) -> WatchStats | None:
        if not self.task:
            return self.stats

        self.stop_event.set()
        try:
            await asyncio.wait_for(self.task, timeout=10)
        except asyncio.TimeoutError:
            self.task.cancel()

        return self.stats

    async def _send_status(self, program, message: str) -> None:
        ch = find_program_channel(self.bot, program, "burp-imports") or find_program_channel(self.bot, program, "general")
        if ch:
            await ch.send(message[:1900])

    async def _run(self) -> None:
        assert self.stats is not None

        while not self.stop_event.is_set():
            self.stats.updated_at = time.time()

            try:
                program = self.bot.db.get_program_by_name(self.stats.program_name)
                if not program:
                    self.stats.last_error = f"Program not found: {self.stats.program_name}"
                    await asyncio.sleep(self.stats.poll_interval)
                    continue

                current = newest_burp_tmp_dir(self.stats.temp_root)
                if current is None:
                    self.stats.current_dir = ""
                    self.stats.last_message = "No burp*.tmp directory found."
                    await asyncio.sleep(self.stats.poll_interval)
                    continue

                self.stats.current_dir = str(current)
                self.stats.scans += 1

                if self.stats.mode in {"in_scope_only", "all_except_out"}:
                    include_auto, exclude_auto = scope_patterns_from_program(self.bot.db, program, self.stats.mode)
                else:
                    include_auto, exclude_auto = "", ""

                include_hosts = self.stats.include_hosts or include_auto
                exclude_hosts = ",".join(x for x in [exclude_auto, self.stats.exclude_hosts] if x)

                candidates = await asyncio.to_thread(scan_burp_temp_folder, str(current), max_files=500)
                if not candidates:
                    self.stats.last_message = f"No recoverable candidates in {current}"
                    await asyncio.sleep(self.stats.poll_interval)
                    continue

                # Signature only checks candidate path/size/mtime. If no change, skip.
                signatures: list[tuple[str, int, int]] = []
                for cand in candidates[: self.stats.candidate_limit]:
                    p = Path(cand.path)
                    try:
                        signatures.append((cand.path, int(p.stat().st_size), int(p.stat().st_mtime)))
                    except OSError:
                        pass

                sig_tuple = tuple(signatures)
                if sig_tuple and sig_tuple in self._seen_signature:
                    self.stats.last_message = "No changed candidate files."
                    await asyncio.sleep(self.stats.poll_interval)
                    continue

                if sig_tuple:
                    self._seen_signature.add(sig_tuple)

                combined, used = await asyncio.to_thread(
                    build_combined_import_text,
                    candidates,
                    max_total_bytes=self.stats.max_total_mb * 1024 * 1024,
                    candidate_limit=self.stats.candidate_limit,
                    include_hosts=include_hosts or None,
                    exclude_hosts=exclude_hosts or None,
                )

                if not combined.strip() or used <= 0:
                    self.stats.last_message = "Changed temp files found, but no snippets matched host filters."
                    await asyncio.sleep(self.stats.poll_interval)
                    continue

                importer = BurpImporter(self.bot.db, self.bot.settings.storage_dir)
                result = await asyncio.to_thread(
                    importer.import_text,
                    program=program,
                    filename="live_recovered_burp_temp.txt",
                    content=combined.encode("utf-8", errors="replace"),
                    format_hint="raw",
                )

                # Dedupe immediately to keep live monitoring usable.
                removed = await asyncio.to_thread(self.bot.db.dedupe_endpoints, program.id)

                b = result.burp_import
                self.stats.imports += 1
                self.stats.endpoints += b.total_items
                self.stats.in_scope += b.in_scope_items
                self.stats.out_scope += b.out_scope_items
                self.stats.unknown += b.unknown_scope_items

                msg = (
                    f"📡 **Burp live import** for `{program.name}`\n"
                    f"- temp: `{current}`\n"
                    f"- import: `#{b.id}`\n"
                    f"- candidates used: `{used}`\n"
                    f"- endpoints: `{b.total_items}` | in `{b.in_scope_items}` | out `{b.out_scope_items}` | unknown `{b.unknown_scope_items}`\n"
                    f"- dedupe removed: `{removed}`\n"
                    f"- mode: `{self.stats.mode}`\n"
                    f"- include: `{include_hosts or '-'}`\n"
                    f"- exclude: `{exclude_hosts or '-'}`"
                )
                self.stats.last_message = msg
                await self._send_status(program, msg)

            except Exception as exc:
                self.stats.last_error = f"{type(exc).__name__}: {exc}"

            await asyncio.sleep(self.stats.poll_interval)
