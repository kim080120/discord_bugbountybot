from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import tasks

from .config import Settings
from .db import Database
from .services.burp_live_watch import BurpLiveWatcher
from .commands.program import ProgramCommands
from .commands.scope import ScopeCommands
from .commands.notice import NoticeCommands
from .commands.restriction import RestrictionCommands
from .commands.burp import BurpCommands
from .commands.endpoint import EndpointCommands
from .commands.hackerone import HackerOneCommands
from .commands.findergap import FinderGapCommands
from .commands.crawl import CrawlCommands
from .commands.report import ReportCommands
from .commands.workspace import WorkspaceCommands
from .commands.markdown import MarkdownCommands
from .commands.folder import FolderCommands
from .commands.review import ReviewCommands
from .commands.storage import StorageCommands
from .commands.dashboard import DashboardCommands
from .commands.system import SystemCommands
from .commands.redact import RedactCommands
from .commands.policy import PolicyCommands
from .commands.finding import FindingCommands
from .commands.evidence import EvidenceCommands
from .commands.ai import AICommands
from .commands.platform_import import ImportCommands
from .commands.recommend import RecommendCommands
from .commands.disclosed import DisclosedCommands


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
        self.burp_live_watcher = BurpLiveWatcher(self)
        self._scope_refresh_started = False

    async def setup_hook(self) -> None:
        self.tree.add_command(ProgramCommands(self))
        self.tree.add_command(ScopeCommands(self))
        self.tree.add_command(NoticeCommands(self))
        self.tree.add_command(RestrictionCommands(self))
        self.tree.add_command(BurpCommands(self))
        self.tree.add_command(EndpointCommands(self))
        self.tree.add_command(HackerOneCommands(self))
        self.tree.add_command(FinderGapCommands(self))
        self.tree.add_command(CrawlCommands(self))
        self.tree.add_command(ImportCommands(self))
        self.tree.add_command(RecommendCommands(self))
        self.tree.add_command(DisclosedCommands(self))
        self.tree.add_command(EvidenceCommands(self))
        self.tree.add_command(AICommands(self))
        self.tree.add_command(ReportCommands(self))
        self.tree.add_command(WorkspaceCommands(self))
        self.tree.add_command(MarkdownCommands(self))
        self.tree.add_command(FolderCommands(self))
        self.tree.add_command(ReviewCommands(self))
        self.tree.add_command(StorageCommands(self))
        self.tree.add_command(DashboardCommands(self))
        self.tree.add_command(SystemCommands(self))
        self.tree.add_command(RedactCommands(self))
        self.tree.add_command(PolicyCommands(self))
        self.tree.add_command(FindingCommands(self))

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

        if not self._scope_refresh_started and self.settings.scope_refresh_days > 0:
            self.scope_refresh_loop.change_interval(hours=24 * self.settings.scope_refresh_days)
            self.scope_refresh_loop.start()
            self._scope_refresh_started = True
            log.info("Weekly scope refresh enabled (every %d days)", self.settings.scope_refresh_days)

    @tasks.loop(hours=168)
    async def scope_refresh_loop(self) -> None:
        try:
            from .commands.platform_import import run_scope_refresh

            lines = await run_scope_refresh(self)
            changed = [ln for ln in lines if ln.startswith(("🔄", "⚠️"))]
            log.info("Scope refresh: %d programs checked, %d changed", len(lines), len(changed))

            channel_id = self.settings.scope_refresh_channel_id
            if channel_id and changed:
                channel = self.get_channel(channel_id)
                if channel is None:
                    try:
                        channel = await self.fetch_channel(channel_id)
                    except discord.DiscordException:
                        channel = None
                if isinstance(channel, (discord.TextChannel, discord.Thread)):
                    await channel.send("🗓️ 주간 스코프 재탐색 — 변경 감지\n" + "\n".join(changed)[:1800])
        except Exception as exc:  # never let the loop kill the bot
            log.warning("Scope refresh loop failed: %s", exc)

    @scope_refresh_loop.before_loop
    async def _before_scope_refresh(self) -> None:
        await self.wait_until_ready()



HELP_TEXTS = {
    "quick": """# BountyOps 빠른 시작

## 1. 프로그램 만들기
```text
/program add name:naver-comic platform:NaverBugBounty reward_max:0 source_code:false has_time_limit:false policy_url:https://bugbounty.naver.com
```

## 2. 인스코프 추가
```text
/scope add program_name:naver-comic type:in value:comic.naver.com note:official in-scope target
/scope add program_name:naver-comic type:in value:*.comic.naver.com note:official in-scope target
```

## 3. Burp tmp 복구/감시
```text
/burp temp_scan folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp
/burp import_temp program_name:naver-comic folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp max_total_mb:20
```

## 4. endpoint 보기
```text
/endpoint hosts program_name:naver-comic scope_filter:unknown
/endpoint list program_name:naver-comic scope_filter:unknown
```

## 5. 후보 취약점으로 등록
```text
/finding add program_name:naver-comic title:"Possible issue" vuln_type:PII severity:medium endpoint_id:62
```

자세한 도움말:
```text
/help category:burp
/help category:scope
/help category:endpoint
/help category:finding
/help category:report
/help category:cleanup
```""",

    "burp": """# Burp 관련 명령어

## tmp 폴더 후보 찾기
PowerShell:
```powershell
Get-ChildItem $env:TEMP -Directory -Filter "burp*.tmp" |
  Sort-Object LastWriteTime -Descending |
  Select-Object FullName, LastWriteTime
```

## tmp 스캔
```text
/burp temp_scan folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp
```

## tmp import
```text
/burp import_temp program_name:naver-comic folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp max_total_mb:20
```

## 특정 host만 import
```text
/burp import_temp program_name:naver-comic folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp include_hosts:comic.naver.com,*.comic.naver.com max_total_mb:20
```

## 노이즈 host 제외
```text
/burp import_temp program_name:naver-comic folder_path:C:\\Users\\kim08\\AppData\\Local\\Temp\\burp4330004610313913450.tmp exclude_hosts:accounts.google.com,pay.naver.com,nid.naver.com,static.nid.naver.com,ssl.pstatic.net,ncpt.naver.com max_total_mb:20
```

## 실시간 감시 시작
```text
/burp watch_start program_name:naver-comic mode:manual_filters include_hosts:comic.naver.com,*.comic.naver.com poll_interval:10 max_total_mb:10 candidate_limit:1
```

## 실시간 감시 상태/중지
```text
/burp watch_status
/burp watch_stop
```

## import 목록/삭제/중복 제거
```text
/burp imports program_name:naver-comic
/burp delete_import import_id:3 confirm:false
/burp delete_import import_id:3 confirm:true
/burp dedupe program_name:naver-comic
```""",

    "scope": """# Scope 관리 명령어

## in-scope 추가
```text
/scope add program_name:naver-comic type:in value:comic.naver.com note:official in-scope target
/scope add program_name:naver-comic type:in value:*.comic.naver.com note:official in-scope target
```

## out-of-scope 추가
```text
/scope add program_name:naver-comic type:out value:accounts.google.com note:third-party identity provider
/scope add program_name:naver-comic type:out value:pay.naver.com note:not current target
/scope add program_name:naver-comic type:out value:nid.naver.com note:login domain; keep separate unless policy says otherwise
```

## endpoint host를 바로 in/out 처리
```text
/endpoint host_scope program_name:naver-comic host:comic.naver.com type:in note:official in-scope target
/endpoint host_scope program_name:naver-comic host:static.nid.naver.com type:out note:login static resource
```

## scope 바꾼 뒤 재분류
```text
/endpoint reclassify program_name:naver-comic
```""",

    "endpoint": """# Endpoint 분석 명령어

## host별 통계
```text
/endpoint hosts program_name:naver-comic scope_filter:unknown
/endpoint hosts program_name:naver-comic scope_filter:in
/endpoint hosts program_name:naver-comic scope_filter:out
```

## endpoint 목록
```text
/endpoint list program_name:naver-comic scope_filter:unknown
/endpoint list program_name:naver-comic scope_filter:in
/endpoint list program_name:naver-comic scope_filter:out
```

## endpoint 상세
```text
/endpoint show endpoint_id:62
```

## AI 분석용 shortlist 만들기
```text
/endpoint shortlist program_name:naver-comic scope_filter:unknown min_score:20 limit:20
```

## CSV export
```text
/endpoint export_csv program_name:naver-comic scope_filter:unknown limit:1000
```""",

    "finding": """# Finding 후보 관리

## 후보 취약점 추가
```text
/finding add program_name:naver-comic title:"Possible profile info exposure" vuln_type:PII severity:medium endpoint_id:62 summary:"Needs validation" impact:"Potential exposure if confirmed"
```

## 목록 보기
```text
/finding list program_name:naver-comic status:candidate
/finding list program_name:naver-comic status:needs-validation
/finding list program_name:naver-comic status:report-ready
```

## 상태 변경
```text
/finding update finding_id:1 status:needs-validation
/finding update finding_id:1 status:false-positive
/finding update finding_id:1 status:report-ready
```

## evidence 연결
```text
/evidence add program_name:naver-comic title:"Burp evidence" evidence_type:burp note:"Endpoint #62 from recovered temp import"
/finding link_evidence finding_id:1 evidence_id:1
```

## report draft로 승격
```text
/finding promote_report finding_id:1
```""",

    "ai": """# AI 분석 명령어

## ⭐ 자동 실행 (프롬프트 생성 → Claude 실행 → 보고서 게시까지 한 번에)
```text
/ai run program_name:naver-comic mode:idor-review
/ai run program_name:naver-comic mode:pii-review create_findings:true
```
봇이 Claude를 headless로 직접 돌려 결과를 #ai-analysis에 게시합니다.
(최초 1회: 터미널에서 `claude setup-token` 실행 후 토큰을 .env의 CLAUDE_CODE_OAUTH_TOKEN에 입력)

## Codex/Claude 프롬프트만 생성 (수동 복붙용)
```text
/ai prompt program_name:naver-comic provider:codex mode:idor-review
/ai prompt program_name:naver-comic provider:claude mode:pii-review
/ai prompt program_name:naver-comic provider:codex mode:endpoint-inventory
```

## AI 결과 저장
```text
/ai result_add program_name:naver-comic provider:codex mode:pii-review title:"PII review result" text:"여기에 결과 붙여넣기"
/ai result_file program_name:naver-comic provider:claude mode:source-review file:analysis.md
```

## AI 결과 목록
```text
/ai results program_name:naver-comic
```""",

    "scope-import": """# 플랫폼 스코프 자동 수집

각 플랫폼의 공개 스코프를 가져와 후보(candidate)로 저장합니다. 미리보기 확인 후 `/crawl apply`로 적용하세요.

## NAVER / Kakao (국내, 무인증)
```text
/import naver
/import kakao
```

## huntr (OSS/AI 바운티 — GitHub repo 타깃)
```text
/import huntr
/import huntr limit:100
```

## Bugcrowd (engagement 단위)
```text
/import bugcrowd_list
/import bugcrowd_list page:2
/import bugcrowd slug:openai-safety
```

## Intigriti (공개 미러)
```text
/import intigriti_list
/import intigriti_list min_reward:2000
/import intigriti handle:aikido
```

## YesWeHack (공개 미러)
```text
/import yeswehack_list
/import yeswehack handle:outscale
```

## HackerOne (공식 API — .env에 토큰 필요)
```text
/hackerone site handle_or_url:vercel
```

## 후보 검토 → 적용
```text
/crawl list
/crawl show crawl_id:1
/crawl apply crawl_id:1
```

## 재수집 / 업데이트 (스코프 변동 추적)
- 같은 플랫폼을 다시 `/import` 하면 **동일 스코프면 "이미 존재"** 안내, 다르면 변경분(+/-)을 알려줍니다.
- 이미 적용된 프로그램에 변경분 반영:
```text
/crawl update crawl_id:<번호>
```
- 전체 재탐색(naver/kakao/huntr/bugcrowd 일괄):
```text
/import refresh
```
주 1회 자동 재탐색이 켜져 있습니다(.env `SCOPE_REFRESH_DAYS`, 0이면 끔). 변경 감지 시 지정 채널로 알림.

## 제약 / 포상금 제외
스코프와 함께 각 플랫폼의 **제약사항([제약])**과 **포상금 제외([포상금 제외])**가 #restrictions에 라벨로 들어갑니다 (Naver PROHIBITIONS/INVALID_REPORTS, Kakao 규칙 청크).""",

    "recommend": """# 프로그램 추천 (어디를 노릴지)

프로그램이 많은 플랫폼에서 **포상금 · 스코프 크기 · 중복리스크**를 0~100점으로 점수화해 추천합니다.
(naver/kakao는 단일 프로그램이라 추천 대상 아님 — `/import naver` 그대로 사용)

## Bugcrowd (공개, 무인증)
```text
/recommend bugcrowd
/recommend bugcrowd limit:15 min_reward:5000
```
중복리스크 = CrowdStream(최근 6개월 채택 제보 수) + 프로그램 나이.

## huntr (OSS/AI repo)
```text
/recommend huntr
/recommend huntr limit:15 sample:40
```
중복리스크 = GitHub stars/forks (덜 알려졌지만 활성인 repo 우선).

## Intigriti (공개 미러, 1요청)
```text
/recommend intigriti
/recommend intigriti min_reward:2000
```
reward=EUR. 활동데이터가 없어 중복리스크는 스코프/리워드 기반 추정.

## YesWeHack (공개 미러, 1요청)
```text
/recommend yeswehack
/recommend yeswehack min_reward:2000
```

## HackerOne (.env 토큰 필요)
```text
/recommend hackerone
```
주의: HackerOne API는 실제 $금액/리포트수를 안 줘서 reward·중복리스크는 **추정치**입니다.

점수 = 0.4×포상금 + 0.3×스코프 + 0.3×(낮은 중복리스크).

## 과거 공개 제보 (disclosed reports)
이미 제보된 취약점 = 중복리스크의 실제 증거 + 어떤 패턴이 먹혔는지.
```text
/disclosed huntr repo:keras-team/keras
/disclosed bugcrowd slug:tesla
/disclosed hackerone                  (최근 공개 제보 전체)
/disclosed hackerone handle:nodejs    (프로그램 필터 — 최근 활동 한정)
```
huntr=제목+링크 · Bugcrowd=채택제보(우선순위·타깃·연구자) · HackerOne=hacktivity(제목·심각도·포상금)""",

    "report": """# Report / Evidence / Redaction

## report draft 생성
```text
/report draft program_name:naver-comic finding_title:"Possible issue" vuln_type:"PII" affected_asset:"Endpoint #62"
```

## draft 목록/검사
```text
/report list program_name:naver-comic
/report check draft_id:1
```

## evidence 추가
```text
/evidence add program_name:naver-comic title:"A/B response diff" evidence_type:ab-test note:"Account B response differs"
/evidence add program_name:naver-comic title:"Screenshot" evidence_type:screenshot note:"redacted screenshot" file:<attachment>
/evidence list program_name:naver-comic
```

## 민감정보 검사
```text
/redact scan_file file:report.md
/redact scan_program program_name:naver-comic
```

## 일일 리뷰
```text
/review daily program_name:naver-comic
```""",

    "policy": """# Policy import

## 정책 파일 import
```text
/policy import_file program_name:naver-comic file:policy.txt apply:false
```

괜찮으면 적용:
```text
/policy import_file program_name:naver-comic file:policy.txt apply:true
```

## 정책 텍스트 직접 import
```text
/policy import_text program_name:naver-comic text:"여기에 정책 내용" source_name:manual apply:false
```

## policy diff
```text
/policy diff program_name:naver-comic
```""",

    "system": """# System / Dashboard / Storage

## 시스템 상태
```text
/system status
/system migrate
/system db_info
```

## 프로그램 대시보드
```text
/dashboard show program_name:naver-comic
```

## 저장소 용량 확인/정리
```text
/storage stats
/storage cleanup older_than_days:7 dry_run:true
/storage cleanup older_than_days:7 dry_run:false confirm:true
```""",

    "md": """# Markdown / Workspace Folder

## 프로그램별 로컬 폴더 지정
```text
/folder set program_name:naver-comic folder_path:C:/Users/kim08/Desktop/bountyops-workspaces/naver-comic create_dirs:true
/folder info program_name:naver-comic
/folder tree program_name:naver-comic
```

folder_path를 비우면 기본값:
```text
storage/workspaces/<program_name>
```

## Codex/Claude markdown 파일 import
```text
/md import_file program_name:naver-comic file:analysis.md provider:codex mode:pii-review create_findings:false
```

## ai/inbox 폴더 스캔
Codex/Claude가 만든 `.md`를 workspace의 `ai/inbox/`에 넣은 뒤:
```text
/md scan_folder program_name:naver-comic scan_dir:ai/inbox provider:codex mode:analysis create_findings:true move_processed:true
```

## import된 markdown 목록
```text
/md index program_name:naver-comic
```""",

    "cleanup": """# 정리 / 삭제 명령어

## 프로그램 삭제
DB만 삭제:
```text
/program delete name:naver-comic delete_discord_category:false
```

DB + Discord 카테고리/채널 삭제:
```text
/program delete name:naver-comic delete_discord_category:true
```

## 남은 workspace 카테고리 삭제
```text
/workspace list
/workspace delete_category category_name:naverbugbounty-naver-comic confirm:false
/workspace delete_category category_name:naverbugbounty-naver-comic confirm:true delete_channels:true
```

## 잘못 만든 crawl 후보 삭제
```text
/crawl list
/crawl delete crawl_id:1
```

## 잘못 import한 Burp 기록 삭제
```text
/burp imports program_name:naver-comic
/burp delete_import import_id:3 confirm:false
/burp delete_import import_id:3 confirm:true
```

## endpoint 중복 제거
```text
/burp dedupe program_name:naver-comic
```"""
}


def split_help_text(text: str, limit: int = 1900) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks or [text[:limit]]


def main() -> None:
    settings = Settings.load()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)

    db = Database(settings.database_path)
    db.init()

    bot = BountyOpsBot(settings=settings, db=db)

    @bot.tree.command(name="ping", description="BountyOps 상태 확인")
    async def ping(interaction: discord.Interaction):
        await interaction.response.send_message("pong - BountyOps v0.6.3", ephemeral=True)


    @bot.tree.command(name="help", description="BountyOps 한국어 도움말")
    @app_commands.describe(category="보고 싶은 도움말 분류")
    @app_commands.choices(category=[
        app_commands.Choice(name="빠른 시작", value="quick"),
        app_commands.Choice(name="Burp 복구/실시간 감시", value="burp"),
        app_commands.Choice(name="Scope 관리", value="scope"),
        app_commands.Choice(name="Endpoint 분석", value="endpoint"),
        app_commands.Choice(name="Finding 후보", value="finding"),
        app_commands.Choice(name="AI 분석", value="ai"),
        app_commands.Choice(name="플랫폼 스코프 수집", value="scope-import"),
        app_commands.Choice(name="프로그램 추천", value="recommend"),
        app_commands.Choice(name="Report/Evidence/Redaction", value="report"),
        app_commands.Choice(name="Policy import", value="policy"),
        app_commands.Choice(name="시스템/대시보드/저장소", value="system"),
        app_commands.Choice(name="Markdown/폴더", value="md"),
        app_commands.Choice(name="정리/삭제", value="cleanup"),
    ])
    async def help_command(interaction: discord.Interaction, category: str = "quick"):
        text = HELP_TEXTS.get(category, HELP_TEXTS["quick"])
        chunks = split_help_text(text)
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)


    try:
        bot.run(settings.discord_token)
    finally:
        db.close()


if __name__ == "__main__":
    main()
