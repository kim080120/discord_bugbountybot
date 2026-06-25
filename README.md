# BountyOps — 버그바운티 운영 Discord 봇

버그바운티 전 과정을 Discord에서 관리하는 봇.
**타깃 스코프 수집 → 프로그램 추천 → 과거 제보 분석 → AI 자동분석 → 공지 추적**까지 한 곳에서.

지원 플랫폼(7): **Naver · Kakao · huntr · Bugcrowd · HackerOne · Intigriti · YesWeHack**

---

## ⚠️ 보안 (먼저 읽기)

- **`.env`는 절대 커밋하지 않습니다.** `.gitignore`로 제외되며, 실제 토큰은 `.env`에만 둡니다. `.env.example`엔 더미값만.
- 토큰이 한 번이라도 노출(커밋/로그/공유)됐다면 **재발급(rotate)** 하세요: Discord Developer Portal, HackerOne API token, GitHub PAT.
- `data/*.sqlite3`, `storage/`도 스캔 데이터를 담으므로 커밋하지 않습니다(.gitignore 처리됨).

---

## 설치 & 실행

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt    # discord.py, python-dotenv
copy .env.example .env                            # 그리고 .env 값 채우기
python -m bountyops.bot
```

새 슬래시 명령은 봇 **재시작 시 길드에 동기화**됩니다. 도움말: `/help category:<분류>`

---

## .env 설정

```ini
# --- Discord ---
DISCORD_TOKEN=                 # 봇 토큰 (필수)
DISCORD_GUILD_ID=              # 길드 ID (즉시 명령 동기화)
DISCORD_PARENT_CATEGORY_ID=
DISCORD_FORUM_CHANNEL_ID=
DATABASE_PATH=./data/bountyops.sqlite3
STORAGE_DIR=./storage
DISCORD_WORKSPACE_MODE=category

# --- HackerOne (스코프 import + 추천 + hacktivity) ---
HACKERONE_USERNAME=
HACKERONE_API_TOKEN=           # hackerone.com/settings/api_token

# --- AI 자동분석 (/ai run) ---
AI_ENGINE=claude
CLAUDE_BIN=                    # 비우면 claude.exe 자동탐지
CLAUDE_CODE_OAUTH_TOKEN=       # `claude setup-token`으로 발급 (구독 인증, API키 아님)
AI_TIMEOUT_SECONDS=600

# --- 스코프 자동 재탐색 (/import refresh) ---
SCOPE_REFRESH_DAYS=7           # 0이면 주간 자동 루프 끔
SCOPE_REFRESH_CHANNEL_ID=      # 비우면 DISCORD_FORUM_CHANNEL_ID로 폴백

# --- /recommend huntr ---
GITHUB_TOKEN=                  # classic PAT(스코프 불필요). GitHub API 60→5000/시간
```

---

## 주요 기능

### 1. 플랫폼 스코프 자동 수집 — `/import`

각 플랫폼의 공개 스코프를 가져와 **후보(candidate)** 로 저장 → 미리보기 확인 후 `/crawl apply`로 워크스페이스(프로그램 + #scope/#restrictions/#notices/#ai-analysis 등 채널) 생성.

```text
# 국내 (단일 프로그램)
/import naver
/import kakao

# huntr (OSS/AI repo)
/import huntr  [limit:250]

# Bugcrowd / Intigriti / YesWeHack (다중 프로그램)
/import bugcrowd_list           → slug 찾기
/import bugcrowd slug:openai-safety
/import intigriti_list
/import intigriti handle:aikido
/import yeswehack_list
/import yeswehack handle:outscale

# HackerOne (공식 API, 토큰 필요)
/hackerone site handle_or_url:vercel

# 임의 정책 URL (제네릭 크롤러)
/findergap site url:<정책URL>

# 후보 검토 → 적용
/crawl list
/crawl show crawl_id:1
/crawl apply crawl_id:1
```

- **제약 / 포상금 제외**: 스코프와 함께 각 플랫폼의 제약사항(`[제약]`)과 포상금 제외(`[포상금 제외]`)가 `#restrictions`에 라벨로 등록됩니다 (Naver PROHIBITIONS/INVALID_REPORTS, Kakao 규칙 청크).
- **공지(announcements)**: 적용 시 프로그램 공지가 `#notices`에 자동 게시됩니다 (`📢 [날짜] 제목 — 요약`). 지원: **Naver · Bugcrowd · Intigriti · YesWeHack** (HackerOne·Kakao는 공개 소스 없음).

### 2. 재수집 / 업데이트 추적 — `/import refresh`, `/crawl update`

- 같은 플랫폼을 다시 `/import` 하면 **동일 스코프면 "이미 존재"**, 다르면 변경분(+/-)을 안내.
- `/crawl update crawl_id:<N>` — 기존 프로그램에 변경분 반영(추가). 없어진 항목은 자동삭제 안 하고 제거 후보로 보고.
- `/import refresh` — naver/kakao/huntr/bugcrowd/intigriti/yeswehack 일괄 재탐색 후 변경분만 업데이트 후보 생성. **주 1회 자동 루프**도 동작(멱등 — 재시작해도 후보 안 쌓임).

### 3. 프로그램 추천 — `/recommend`

프로그램이 많은 플랫폼에서 **포상금 · 스코프 · 중복리스크**를 0~100점으로 점수화.
점수 = `0.3×포상금 + 0.2×스코프 + 0.5×(낮은 중복리스크)` (경쟁회피 가중치, `program_recommender.py` 상수로 조정 가능).

```text
/recommend bugcrowd   [limit] [min_reward]   # 중복리스크 = CrowdStream(최근6개월 채택 제보 수)+나이
/recommend huntr      [limit] [sample]       # 중복리스크 = GitHub stars/forks + 활성도
/recommend intigriti  [limit] [min_reward]   # 스코프 타입 분포·통화(€/$) 표시
/recommend yeswehack  [limit] [min_reward]
/recommend hackerone  [limit]                # API가 $금액/리포트수 미제공 → 추정치
```

### 4. 과거 공개 제보 — `/disclosed`

이미 제보된 취약점 = **중복리스크의 실제 증거 + 먹히는 패턴**.

```text
/disclosed huntr repo:keras-team/keras     # 제보 제목 + 링크
/disclosed bugcrowd slug:tesla             # 최근6개월 채택 제보(우선순위·타깃·연구자·날짜)
/disclosed hackerone                       # 최근 공개 제보(제목·심각도·프로그램·연구자)
/disclosed hackerone handle:nodejs         # 프로그램 필터(REST 한계로 최근 활동 한정)
```

### 5. AI 자동분석 — `/ai run`

프로그램 컨텍스트(스코프·엔드포인트·증거)를 모아 **Claude Code를 headless로 직접 실행** → 분석 보고서를 `#ai-analysis`에 게시. raw API가 아니라 **구독 인증**(`claude setup-token`)으로 동작.

```text
/ai run program_name:naver mode:idor-review [create_findings:true]
/ai prompt program_name:X provider:claude mode:pii-review     # 프롬프트만 생성(수동용)
/ai results program_name:X
```

> 최초 1회: 봇 PC에 Claude Code CLI 설치(`npm i -g @anthropic-ai/claude-code`) → `claude setup-token` → 토큰을 `.env`의 `CLAUDE_CODE_OAUTH_TOKEN`에 입력.

### 6. 기존 워크플로우 (Burp·엔드포인트·리포트)

```text
/burp temp_scan|import_temp|watch_start ...   # Burp tmp 복구/실시간 감시
/endpoint hosts|list|shortlist|export_csv ...
/finding add|list|update|promote_report ...
/report draft|check ...   /evidence add|list   /redact scan_file|scan_program
/dashboard show   /storage stats|cleanup   /system status
```

전체 도움말: `/help category:quick|burp|scope|endpoint|finding|ai|scope-import|recommend|report|policy|system|md|cleanup`

---

## 아키텍처

```
bountyops/
  bot.py                     # Discord client, 명령 등록, 도움말, 주간 재탐색 루프
  config.py                  # .env -> Settings
  db.py / models.py          # SQLite
  commands/                  # 슬래시 명령 그룹 (import, recommend, disclosed, ai, crawl, ...)
  services/
    platform_importers.py    # Naver/Kakao/huntr/Bugcrowd/Intigriti/YesWeHack 스코프+공지
    program_recommender.py   # 추천 점수 (포상금/스코프/중복리스크)
    disclosed_reports.py     # 과거 공개 제보 (huntr/Bugcrowd/HackerOne)
    hackerone_api.py         # HackerOne 공식 API
    ai_runner.py             # Claude Code headless 실행기
    site_crawler.py          # 제네릭 크롤러 + CrawlResult
scripts/ai_run_local.py      # 디스코드 없이 /ai run 로직 실행 (테스트/스케줄용)
```

모든 외부 요청은 **읽기 전용·무인증(공개 페이지)** 또는 사용자 본인 토큰(HackerOne/GitHub) 사용. 자동 import는 공개 스코프만 읽으며, 실제 테스트는 각 프로그램 약관을 따르세요.
