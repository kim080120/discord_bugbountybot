from __future__ import annotations

import discord
from discord import app_commands

from ..scoring import rank_programs
from ..workspace import create_program_thread, make_program_embed, refresh_program_thread


SORT_CHOICES = [
    app_commands.Choice(name="score - 종합 점수", value="score"),
    app_commands.Choice(name="scope - 인스코프 많은순", value="scope"),
    app_commands.Choice(name="reward - 보상금 많은순", value="reward"),
    app_commands.Choice(name="source - 소스코드/GitHub 자료 우선", value="source"),
    app_commands.Choice(name="time_limit - 제한시간 있는 항목 우선", value="time_limit"),
]


class ProgramCommands(app_commands.Group):
    def __init__(self, bot: discord.Client):
        super().__init__(name="program", description="버그바운티 프로그램 관리")
        self.bot = bot

    @app_commands.command(name="add", description="버그바운티 프로그램 등록 및 Forum thread 생성")
    @app_commands.describe(
        name="프로그램 이름",
        platform="HackerOne, Bugcrowd, FinderGap, VDP 등",
        reward_min="최소 보상금. 모르면 0",
        reward_max="최대 보상금. 모르면 0",
        source_code="GitHub 등 공개 소스코드/자료가 있는지",
        has_time_limit="점검시간/테스트 제한시간이 있는지",
        time_limit_note="제한시간 설명",
        policy_url="정책 URL",
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
            await interaction.followup.send(f"이미 등록된 프로그램입니다: `{existing.name}`", ephemeral=True)
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
            await interaction.followup.send(f"등록 실패: `{exc}`", ephemeral=True)
            return

        thread_msg = "Forum thread 생성 안 함"
        forum_channel_id = getattr(self.bot.settings, "discord_forum_channel_id", None)
        if forum_channel_id:
            forum = self.bot.get_channel(forum_channel_id)
            if forum is None:
                try:
                    forum = await self.bot.fetch_channel(forum_channel_id)
                except discord.DiscordException:
                    forum = None

            if isinstance(forum, discord.ForumChannel):
                try:
                    thread = await create_program_thread(
                        forum_channel=forum,
                        db=self.bot.db,
                        program=program,
                    )
                    if thread:
                        thread_msg = f"Forum thread 생성 완료: {thread.mention}"
                except discord.Forbidden:
                    thread_msg = "Forum thread 생성 실패: 권한 부족"
                except discord.HTTPException as exc:
                    thread_msg = f"Forum thread 생성 실패: HTTPException {exc.status}"
            else:
                thread_msg = "Forum thread 생성 실패: DISCORD_FORUM_CHANNEL_ID가 Forum 채널이 아님"

        await interaction.followup.send(
            f"프로그램 등록 완료: `{program.name}`\n{thread_msg}",
            ephemeral=True,
        )

    @app_commands.command(name="list", description="프로그램 목록을 기준별로 정렬해서 보기")
    @app_commands.choices(sort_by=SORT_CHOICES)
    async def list(self, interaction: discord.Interaction, sort_by: str = "score"):
        programs = self.bot.db.list_programs()
        if not programs:
            await interaction.response.send_message("아직 등록된 프로그램이 없습니다.", ephemeral=True)
            return

        ranks = rank_programs(programs, self.bot.db.count_in_scope, sort_by)

        lines = []
        for idx, rank in enumerate(ranks[:20], 1):
            p = rank.program
            source = "SRC" if p.source_code else "NO-SRC"
            time_limit = "TIME" if p.has_time_limit else "NO-TIME"
            thread = f"<#{p.discord_thread_id}>" if p.discord_thread_id else "-"
            lines.append(
                f"`{idx:02}` **{p.name}** [{p.platform}] "
                f"| score `{rank.score}` | scope `{rank.in_scope_count}` | reward `{p.reward_max:,}` "
                f"| {source} | {time_limit} | {thread}"
            )

        embed = discord.Embed(
            title=f"Program Ranking: {sort_by}",
            description="\n".join(lines)[:4000],
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="show", description="프로그램 상세 보기")
    async def show(self, interaction: discord.Interaction, name: str):
        program = self.bot.db.get_program_by_name(name)
        if not program:
            await interaction.response.send_message(f"프로그램을 찾을 수 없습니다: `{name}`", ephemeral=True)
            return

        embed = make_program_embed(self.bot.db, program)
        await interaction.response.send_message(embed=embed, ephemeral=False)

    @app_commands.command(name="refresh", description="프로그램 Discord thread에 최신 요약 게시")
    async def refresh(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        program = self.bot.db.get_program_by_name(name)
        if not program:
            await interaction.followup.send(f"프로그램을 찾을 수 없습니다: `{name}`", ephemeral=True)
            return

        ok = await refresh_program_thread(bot=self.bot, db=self.bot.db, program=program)
        if ok:
            await interaction.followup.send("thread 요약을 갱신했습니다.", ephemeral=True)
        else:
            await interaction.followup.send("thread 갱신 실패: thread id가 없거나 접근할 수 없습니다.", ephemeral=True)
