from __future__ import annotations

import discord
from discord import app_commands

from ..services.ai_prompts import build_ai_prompt, MODE_DESCRIPTIONS
from ..services.ai_runner import find_claude_bin, run_claude
from ..workspace import find_program_channel, chunk_text


# Heuristic keywords used to pull finding candidates out of an AI report.
_FINDING_KEYWORDS = [
    "possible", "candidate", "finding", "vulnerability", "idor",
    "pii", "token", "auth bypass", "exposure",
]


PROVIDERS = [
    app_commands.Choice(name="codex", value="codex"),
    app_commands.Choice(name="claude", value="claude"),
    app_commands.Choice(name="generic", value="generic"),
]

MODES = [
    app_commands.Choice(name=name, value=name)
    for name in MODE_DESCRIPTIONS.keys()
]


class AICommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="ai", description="AI prompt/result management")
        self.bot = bot

    @app_commands.command(name="prompt", description="Generate a Codex/Claude-ready analysis prompt")
    @app_commands.choices(provider=PROVIDERS, mode=MODES)
    async def prompt(
        self,
        interaction: discord.Interaction,
        program_name: str,
        provider: str = "codex",
        mode: str = "idor-review",
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        in_scope = self.bot.db.list_scope_items(program.id, "in")
        out_scope = self.bot.db.list_scope_items(program.id, "out")
        restrictions = self.bot.db.list_restrictions(program.id, limit=80)
        endpoints = self.bot.db.list_endpoints(program_id=program.id, scope_filter="all", limit=80)
        evidence_rows = self.bot.db.list_evidence(program.id, limit=40)
        evidence = [dict(r) for r in evidence_rows]

        prompt_text = build_ai_prompt(
            provider=provider,
            mode=mode,
            program_name=program.name,
            platform=program.platform,
            policy_url=program.policy_url,
            in_scope=in_scope,
            out_scope=out_scope,
            restrictions=restrictions,
            endpoints=endpoints,
            evidence=evidence,
        )

        ch = find_program_channel(self.bot, program, "ai-analysis")
        if ch:
            await ch.send(f"# AI Prompt — {provider} / {mode}")
            for chunk in chunk_text("```text\n" + prompt_text + "\n```", limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(
            f"AI prompt generated for `{program.name}` using `{provider}` / `{mode}`. Check #ai-analysis.",
            ephemeral=True,
        )

    @app_commands.command(name="run", description="Run Claude analysis automatically and post the report")
    @app_commands.choices(mode=MODES)
    async def run(
        self,
        interaction: discord.Interaction,
        program_name: str,
        mode: str = "idor-review",
        create_findings: bool = False,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        settings = self.bot.settings
        if settings.ai_engine != "claude":
            await interaction.followup.send(
                f"`AI_ENGINE={settings.ai_engine}`는 아직 자동 실행을 지원하지 않아요. 지금은 `claude`만 됩니다.",
                ephemeral=True,
            )
            return

        claude_bin = find_claude_bin(settings.claude_bin)
        if not claude_bin:
            await interaction.followup.send(
                "`claude` 실행파일을 찾을 수 없어요. `.env`에 "
                "`CLAUDE_BIN=C:\\...\\claude.exe` 경로를 설정하세요.",
                ephemeral=True,
            )
            return

        in_scope = self.bot.db.list_scope_items(program.id, "in")
        out_scope = self.bot.db.list_scope_items(program.id, "out")
        restrictions = self.bot.db.list_restrictions(program.id, limit=80)
        endpoints = self.bot.db.list_endpoints(program_id=program.id, scope_filter="all", limit=80)
        evidence = [dict(r) for r in self.bot.db.list_evidence(program.id, limit=40)]

        prompt_text = build_ai_prompt(
            provider="claude",
            mode=mode,
            program_name=program.name,
            platform=program.platform,
            policy_url=program.policy_url,
            in_scope=in_scope,
            out_scope=out_scope,
            restrictions=restrictions,
            endpoints=endpoints,
            evidence=evidence,
        )

        await interaction.followup.send(
            f"⏳ Claude 분석 실행 중… (`{program.name}` / mode: `{mode}`) — 최대 "
            f"{int(settings.ai_timeout)}초. 잠시 기다려주세요.",
            ephemeral=True,
        )

        result = await run_claude(
            prompt_text,
            claude_bin=claude_bin,
            cwd=str(settings.storage_dir.parent),
            oauth_token=settings.claude_oauth_token,
            timeout=settings.ai_timeout,
        )

        if not result.ok:
            await interaction.followup.send(f"❌ 분석 실패: {result.error}", ephemeral=True)
            return

        text = result.text or "_(빈 응답)_"
        rid = self.bot.db.add_ai_result(
            program_id=program.id,
            provider="claude",
            mode=mode,
            title=f"{mode} auto-run",
            body=text,
        )

        ch = find_program_channel(self.bot, program, "ai-analysis")
        if ch:
            await ch.send(
                f"# 🤖 AI Auto-Run #{rid} — claude / {mode}\n"
                f"- ⏱️ {result.duration_s:.0f}s · 자동 생성 (read-only)"
            )
            for chunk in chunk_text(text, limit=1900):
                await ch.send(chunk)

        created: list[int] = []
        if create_findings:
            created = self._create_findings_from_text(program.id, text, rid)

        suffix = f" · findings 생성: `{created or '-'}`" if create_findings else ""
        target = "#ai-analysis" if ch else "(ai-analysis 채널 없음 — DB에만 저장)"
        await interaction.followup.send(
            f"✅ 완료 — AI result `#{rid}` 저장 + {target} 게시 ({result.duration_s:.0f}s){suffix}",
            ephemeral=True,
        )

    def _create_findings_from_text(self, program_id: int, text: str, result_id: int) -> list[int]:
        """Pull up to 10 candidate findings out of an AI report (same heuristic as parse_result)."""
        candidates: list[str] = []
        for line in text.splitlines():
            clean = line.strip(" -*\t")
            low = clean.lower()
            if len(clean) < 12 or len(clean) > 220:
                continue
            if any(k in low for k in _FINDING_KEYWORDS) and clean not in candidates:
                candidates.append(clean)
            if len(candidates) >= 10:
                break

        created: list[int] = []
        for c in candidates:
            fid = self.bot.db.add_finding(
                program_id=program_id,
                title=c[:120],
                vuln_type="AI-candidate",
                severity="unknown",
                endpoint_id=None,
                summary=f"Parsed from AI auto-run #{result_id}: {c}",
                impact="Needs human validation.",
            )
            created.append(fid)
        return created

    @app_commands.command(name="result_add", description="Store an AI analysis result")
    async def result_add(
        self,
        interaction: discord.Interaction,
        program_name: str,
        provider: str,
        mode: str,
        title: str,
        text: str,
    ):
        await interaction.response.defer(ephemeral=True)

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rid = self.bot.db.add_ai_result(
            program_id=program.id,
            provider=provider,
            mode=mode,
            title=title,
            body=text,
        )

        ch = find_program_channel(self.bot, program, "ai-analysis")
        if ch:
            await ch.send(f"# AI Result #{rid}: {title}\n- Provider: `{provider}`\n- Mode: `{mode}`")
            for chunk in chunk_text(text, limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(f"AI result saved: `#{rid}`", ephemeral=True)

    @app_commands.command(name="result_file", description="Store an AI analysis result from an uploaded file")
    async def result_file(
        self,
        interaction: discord.Interaction,
        program_name: str,
        provider: str,
        mode: str,
        file: discord.Attachment,
    ):
        await interaction.response.defer(ephemeral=True)

        if file.size > 2 * 1024 * 1024:
            await interaction.followup.send("File too large. Limit is 2MB.", ephemeral=True)
            return

        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.followup.send(f"Program not found: `{program_name}`", ephemeral=True)
            return

        text = (await file.read()).decode("utf-8", errors="replace")
        rid = self.bot.db.add_ai_result(
            program_id=program.id,
            provider=provider,
            mode=mode,
            title=file.filename,
            body=text,
        )

        ch = find_program_channel(self.bot, program, "ai-analysis")
        if ch:
            await ch.send(f"# AI Result #{rid}: {file.filename}\n- Provider: `{provider}`\n- Mode: `{mode}`")
            for chunk in chunk_text(text, limit=1900):
                await ch.send(chunk)

        await interaction.followup.send(f"AI result saved: `#{rid}`", ephemeral=True)


    @app_commands.command(name="parse_result", description="Parse an AI result into finding candidates")
    async def parse_result(self, interaction: discord.Interaction, result_id: int, create_findings: bool = False):
        await interaction.response.defer(ephemeral=True)
        row = self.bot.db.conn.execute("SELECT * FROM ai_results WHERE id=?", (result_id,)).fetchone()
        if not row:
            await interaction.followup.send(f"AI result not found: `{result_id}`", ephemeral=True)
            return
        program = self.bot.db.get_program_by_id(row["program_id"])
        text = row["body"]

        candidates = []
        for line in text.splitlines():
            clean = line.strip(" -*\t")
            low = clean.lower()
            if len(clean) < 12 or len(clean) > 220:
                continue
            if any(k in low for k in ["possible", "candidate", "finding", "vulnerability", "idor", "pii", "token", "auth bypass", "exposure"]):
                if clean not in candidates:
                    candidates.append(clean)
            if len(candidates) >= 10:
                break

        created = []
        if create_findings:
            for c in candidates:
                fid = self.bot.db.add_finding(
                    program_id=program.id,
                    title=c[:120],
                    vuln_type="AI-candidate",
                    severity="unknown",
                    endpoint_id=None,
                    summary=f"Parsed from AI result #{result_id}: {c}",
                    impact="Needs human validation.",
                )
                created.append(fid)

        msg = [
            f"Parsed AI result `#{result_id}`.",
            f"- candidates found: `{len(candidates)}`",
            f"- findings created: `{created or '-'}`",
            "",
            "## Candidates",
            *(f"- {c}" for c in candidates),
        ]
        await interaction.followup.send("\n".join(msg)[:1900], ephemeral=True)


    @app_commands.command(name="results", description="List stored AI results")
    async def results(self, interaction: discord.Interaction, program_name: str, limit: int = 10):
        program = self.bot.db.get_program_by_name(program_name)
        if not program:
            await interaction.response.send_message(f"Program not found: `{program_name}`", ephemeral=True)
            return

        rows = self.bot.db.list_ai_results(program.id, limit=limit)
        if not rows:
            await interaction.response.send_message("No AI results stored.", ephemeral=True)
            return

        lines = [f"`#{r['id']}` **{r['title']}** | `{r['provider']}` / `{r['mode']}`" for r in rows]
        await interaction.response.send_message(
            embed=discord.Embed(
                title=f"AI Results — {program.name}",
                description="\n".join(lines)[:4000],
                color=discord.Color.blue(),
            ),
            ephemeral=False,
        )
