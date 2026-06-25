"""Run Claude Code headless as the bot's analysis engine.

This calls the locally-installed `claude` CLI in print mode (`-p`) so the bot can
produce analysis/reports with the user's Claude subscription — no API key.

Auth: the CLI needs a long-lived token. Run `claude setup-token` once and put the
result in `.env` as CLAUDE_CODE_OAUTH_TOKEN (passed through as an env var here).

Safety: runs read-only. Permission prompts are bypassed so it never hangs, but
mutating/exec tools (Bash/Write/Edit/...) are hard-disallowed, so the agent can
read project files and web-search but cannot change anything.
"""

from __future__ import annotations

import asyncio
import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


# Tools the headless engine is never allowed to use (read-only analysis only).
DEFAULT_DISALLOWED_TOOLS = ["Bash", "Write", "Edit", "MultiEdit", "NotebookEdit"]


@dataclass
class AIRunResult:
    ok: bool
    text: str
    error: str = ""
    returncode: int | None = None
    duration_s: float = 0.0


def find_claude_bin(explicit: str | None = None) -> str | None:
    """Locate the claude executable.

    1. explicit path from config (CLAUDE_BIN)
    2. on PATH
    3. desktop-app install: %APPDATA%/Claude/claude-code/<version>/claude.exe (latest)
    """
    if explicit:
        p = Path(explicit).expanduser()
        if p.exists():
            return str(p)

    on_path = shutil.which("claude")
    if on_path:
        return on_path

    appdata = os.getenv("APPDATA")
    if appdata:
        pattern = str(Path(appdata) / "Claude" / "claude-code" / "*" / "claude.exe")
        matches = glob.glob(pattern)
        if matches:
            def version_key(path: str) -> tuple[int, ...]:
                name = Path(path).parent.name
                try:
                    return tuple(int(part) for part in name.split("."))
                except ValueError:
                    return (0,)

            matches.sort(key=version_key)
            return matches[-1]

    return None


async def run_claude(
    prompt: str,
    *,
    claude_bin: str,
    cwd: str | Path | None = None,
    oauth_token: str | None = None,
    timeout: float = 600.0,
    disallowed_tools: list[str] | None = None,
    permission_mode: str = "bypassPermissions",
    model: str | None = None,
) -> AIRunResult:
    """Run `claude -p` headless and return the final text response.

    The prompt is sent over stdin to avoid Windows command-line length limits.
    """
    disallowed = disallowed_tools if disallowed_tools is not None else DEFAULT_DISALLOWED_TOOLS

    cli_args: list[str] = [
        "-p",
        "--output-format",
        "text",
        "--permission-mode",
        permission_mode,
    ]
    if disallowed:
        cli_args += ["--disallowedTools", *disallowed]
    if model:
        cli_args += ["--model", model]

    # npm installs the CLI as a `claude.cmd`/`claude.bat` wrapper on Windows, and
    # CreateProcess cannot execute those directly — they must go through cmd.exe.
    # A native-installer or unix `claude(.exe)` runs directly.
    lower = claude_bin.lower()
    if os.name == "nt" and (lower.endswith(".cmd") or lower.endswith(".bat")):
        args = ["cmd", "/c", claude_bin, *cli_args]
    else:
        args = [claude_bin, *cli_args]

    env = os.environ.copy()
    if oauth_token:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = oauth_token

    loop = asyncio.get_event_loop()
    start = loop.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd) if cwd else None,
            env=env,
        )
    except FileNotFoundError:
        return AIRunResult(ok=False, text="", error=f"claude binary not found: {claude_bin}")

    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(input=prompt.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return AIRunResult(
            ok=False,
            text="",
            error=f"timeout after {timeout:.0f}s",
            duration_s=loop.time() - start,
        )

    duration = loop.time() - start
    stdout = (stdout_b or b"").decode("utf-8", errors="replace").strip()
    stderr = (stderr_b or b"").decode("utf-8", errors="replace").strip()

    if proc.returncode != 0:
        combined = f"{stdout}\n{stderr}".lower()
        if "not logged in" in combined or "/login" in combined or "setup-token" in combined:
            error = (
                "Claude CLI not authenticated. In a terminal run `claude setup-token`, "
                "then put the token in .env as CLAUDE_CODE_OAUTH_TOKEN."
            )
        else:
            error = stderr or stdout or f"exit code {proc.returncode}"
        return AIRunResult(
            ok=False,
            text=stdout,
            error=error,
            returncode=proc.returncode,
            duration_s=duration,
        )

    return AIRunResult(ok=True, text=stdout, returncode=0, duration_s=duration)
