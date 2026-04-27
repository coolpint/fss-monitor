# 금감원 징계공시 모니터링

금감원 징계공시에 새 글이 올라오면:
1. 신규 공시를 감지하고
2. Teams 채널로 링크 알림을 보냅니다.

## 핵심 변경사항

- 신규 공시 파싱 로직 강화 (누락 방지)
- 기본 확인 시간: 매일 `02:00`
- 실행 모드
  - 1회 실행: `python monitor.py`
  - 스케줄 상시 실행: `python monitor.py --daemon`
- Teams 전송 기본값: Incoming Webhook 링크 알림
- 선택 기능: `ALERT_LINK_ONLY=0` 설정 시 PDF 다운로드/전송 모드 사용

## 설치

```bash
pip install -r requirements.txt
```

## 사용법

```bash
python monitor.py
python monitor.py --daemon
python monitor.py --check-times 02:00 --daemon
python monitor.py --test
python monitor.py --reset
```

## 로컬 기사화 파이프라인

Teams 링크 알림 이후의 후속 작업(PDF 다운로드, PDF 텍스트 추출, Gemini Gems 입력 준비, CMS 초안 입력 준비)은 로컬 Mac에서 `article_pipeline.py`로 실행합니다.

```bash
python article_pipeline.py --latest
python article_pipeline.py --process-new --max-items 3
python article_pipeline.py --item-url "https://www.fss.or.kr/..."
python article_pipeline.py --daemon
```

생성물은 기본적으로 `runs/` 아래 작업 폴더에 저장됩니다.

- `metadata.json`: 공시 메타데이터
- `pdf/`: 다운로드한 금감원 PDF
- `pdf_text.txt`: PDF 추출 텍스트
- `gemini_article_input.md`: "금감원 징계 해설" Gem에 붙여넣을 입력
- `gemini_cartoon_input_template.md`: "신문만평 제작" Gem에 붙여넣을 입력 템플릿
- `cms_draft_template.md`: moneynlaw.co.kr 기사 입력용 템플릿
- `handoff.md`: 다음 작업 순서
- `status.json`: 작업 상태와 확인 필요 항목

로컬 설정이 필요하면 `service_config.example.json`을 참고해 `service_config.local.json`을 만들거나 환경변수를 사용하세요.

- `FSS_ARTICLE_GEM_URL`: Gemini "금감원 징계 해설" Gem URL
- `FSS_CARTOON_GEM_URL`: Gemini "신문만평 제작" Gem URL
- `FSS_GEMINI_MODEL_MODE`: Gemini Gems에서 사용할 모델 모드. 기본값은 `Pro`
- `FSS_CHROME_PROFILE_NAME`: CMS/Gemini 작업에 사용할 Chrome 프로필. 기본값은 `가리봉동`
- `FSS_CHROME_PROFILE_DIRECTORY`: 로컬 Chrome 프로필 디렉터리. 예: `Profile 4`
- `FSS_CHROME_ACCOUNT_HINT`: 로그인 계정 확인용 힌트. 실제 값은 로컬 설정에만 둡니다.
- `MONEYNLAW_LOGIN_URL`: moneynlaw.co.kr 회원 로그인 URL
- `MONEYNLAW_WRITE_URL`: moneynlaw.co.kr 기사 작성 URL
- `MONEYNLAW_REVIEW_STATUS`: 기사 작성 화면의 `기사검토` 값. 기본값은 `승인요청`

주의:

- 로그인 정보, 쿠키, API 키, 웹훅은 저장소에 저장하지 마세요.
- Gemini Gems 실행 시 "빠른 모델" 대신 `Pro`를 선택하세요.
- 현재 파이프라인은 안전을 위해 공개 발행하지 않고, 기사화 작업 패키지와 `기사검토=승인요청` 저장 인계 파일을 먼저 만듭니다.
- moneynlaw.co.kr에서 `기사검토`가 `승인요청`이면 입력과 이미지 첨부 후 `저장하기`까지 추가 확인 없이 진행할 수 있습니다. 최종 공개 발행은 승인 단계에서 별도 처리합니다.

## 기기 이동 인계

- `runs/`, `pipeline_state.json`, `service_config.local.json`은 기본적으로 로컬 전용입니다.
- 다른 기기에서 이어가야 할 때는, 비밀이 없는 산출물만 `handoff/` 아래 추적 파일로 승격해 GitHub에 저장합니다.
- 현재 저장소에는 샘플 인계 패키지로 [handoff/20260420_202500146_1_주식회사-하나은행-제재관련-공시/README.md](/Users/air/codes/fss-monitor/handoff/20260420_202500146_1_주식회사-하나은행-제재관련-공시/README.md)가 포함됩니다.
- 새 기기에서는 `service_config.example.json`을 복사해 `service_config.local.json`을 다시 만들고, 브라우저 로그인 세션과 로컬 Chrome 프로필 디렉터리만 재설정하면 됩니다.

## Teams 설정

### 1) Webhook만 사용하는 경우 (기존 방식)

- `monitor.py`의 `DEFAULT_WEBHOOK_URL` 또는 환경변수 `TEAMS_WEBHOOK_URL` 설정
- 이 경우 파일 업로드는 불가능하고, 알림 카드만 전송됩니다.

### 2) PDF까지 보내려면 (선택)

기본값은 링크 알림 전용입니다.  
PDF 다운로드/전송까지 하려면 먼저 `ALERT_LINK_ONLY=0`으로 설정하고, 아래 환경변수를 설정하세요.

- `TEAMS_TENANT_ID`
- `TEAMS_CLIENT_ID`
- `TEAMS_CLIENT_SECRET`
- `TEAMS_TEAM_ID`
- `TEAMS_CHANNEL_ID`

Graph 모드에서는 PDF를 채널 파일 폴더에 업로드한 뒤, 채널 메시지에 파일 링크를 함께 보냅니다.

## 자동 실행 방법

### 방법 A: 스크립트를 상시 실행

```bash
python monitor.py --daemon
```

### 방법 B: 작업 스케줄러(권장)

작업 스케줄러에 같은 명령을 1개 트리거로 등록:
- 매일 02:00

실행 명령:
```bash
python monitor.py
```

### 방법 C: GitHub Actions로 실행

- `.github/workflows/monitor.yml` 기준으로 매일 `02:00`(KST)에 실행됩니다.
- GitHub Actions는 **원격 저장소(`origin/main`)의 코드**를 실행하므로, 로컬 수정 후 반드시 `git push`까지 해야 반영됩니다.
- GitHub 리포지토리 `Settings > Secrets and variables > Actions`에 `TEAMS_WEBHOOK_URL`을 등록하세요.

### 방법 D: 주간 상태 점검

- `.github/workflows/weekly-health-check.yml` 기준으로 매주 금요일 `15:45`(KST)에 실행됩니다.
- 최근 7일간 `monitor.yml` scheduled 실행 이력을 점검하고, 이상이 없어도 Teams로 `정상 작동 중` 메시지를 보냅니다.
- 점검 기간은 실제 워크플로 시작 시각이 아니라 주간 점검의 예정 시각(`금요일 15:45 KST`)에 고정해 계산하므로, GitHub Actions 지연 때문에 경계 시각이 흔들려도 예상 실행 횟수를 안정적으로 계산합니다.
- 실패, 실행 누락, 미완료 run이 있으면 Teams에 `점검 필요` 상태로 요약을 보냅니다.

## 주의

- `--reset` 실행 시 기존 기록(`seen.json`)이 초기화되어 이미 있던 공시도 다시 신규로 처리됩니다.
- 첫 실행은 현재 공시 목록을 기준선으로 저장하고 알림을 보내지 않습니다(다음 실행부터 신규만 알림).
- 처음 설정 후에는 `python monitor.py --test`로 연결/설정을 먼저 확인하세요.
